"""
Thin wrapper around the LLM provider's OpenAI-compatible chat completions
API (currently routed through OpenRouter — see config.py).

This version is optimized for fast failure and graceful fallback.

Why:
- Free-tier OpenRouter models may return 429 rate limits.
- Some upstream providers may return temporary overload / 502 errors.
- Long retry chains can make Laravel exceed PHP's execution timeout.

Behavior:
1. Try the primary model.
2. Retry it only once if rate-limited.
3. If it fails, immediately try the fallback model.
4. Retry the fallback only once if rate-limited.
5. If both fail, raise DeepSeekUnavailableError quickly.

This prevents AI contextual search from blocking Laravel for 60+ seconds.
"""

import json
import logging
import time

from openai import (
    APIError,
    APITimeoutError,
    OpenAI,
    RateLimitError,
)

from app.config import settings


logger = logging.getLogger("vibelocate.llm")


# --------------------------------------------------------------------------
# Fast-failure configuration
# --------------------------------------------------------------------------

# Maximum time allowed for ONE model request.
# Contextual search requests are small, so we do not want to wait
# 30-60 seconds for an overloaded free-tier provider.
REQUEST_TIMEOUT_SECONDS = 6.0

# Number of EXTRA attempts after the first request when we receive 429.
#
# 1 means:
#   attempt 1
#   wait briefly
#   attempt 2
#
# Then fail/fallback.
MAX_RATE_LIMIT_RETRIES = 1

BASE_BACKOFF_SECONDS = 1.0
MAX_BACKOFF_SECONDS = 2.0

_client = OpenAI(
    api_key=settings.deepseek_api_key,
    base_url=settings.deepseek_base_url,
    timeout=REQUEST_TIMEOUT_SECONDS,
    max_retries=0,
)

class DeepSeekUnavailableError(Exception):
    """
    Raised when the LLM provider cannot return a usable response.

    The name is preserved because other application modules already
    import this exception.
    """


def _call_once(
    model: str,
    system_prompt: str,
    user_prompt: str,
) -> dict:
    """
    Call one model.

    Rate-limit behavior:
    - Retry only a very small number of times.
    - Use short exponential backoff.
    - Never keep the API request blocked for a long time.

    Other provider failures such as:
    - timeout
    - 5xx/provider overload
    - malformed response
    immediately fail this model so call_json() can try the fallback.
    """

    last_error: Exception | None = None

    total_attempts = MAX_RATE_LIMIT_RETRIES + 1

    for attempt in range(total_attempts):
        try:
            logger.info(
                "Calling model %s (attempt %d/%d)",
                model,
                attempt + 1,
                total_attempts,
            )

            response = _client.chat.completions.create(
                model=model,
                messages=[
                    {
                        "role": "system",
                        "content": system_prompt,
                    },
                    {
                        "role": "user",
                        "content": user_prompt,
                    },
                ],
                response_format={
                    "type": "json_object",
                },
                temperature=0.1,

                # Explicit per-request timeout.
                timeout=REQUEST_TIMEOUT_SECONDS,
            )

            # --------------------------------------------------------------
            # Defensive validation
            # --------------------------------------------------------------

            # Some upstream providers occasionally respond successfully
            # at the HTTP layer but provide no completion choices.
            if not response.choices:
                logger.error(
                    "Model %s returned no choices. Raw response: %s",
                    model,
                    response,
                )

                raise DeepSeekUnavailableError(
                    f"Empty response from {model} (no choices)"
                )

            content = response.choices[0].message.content

            if not content:
                logger.error(
                    "Model %s returned empty message content.",
                    model,
                )

                raise DeepSeekUnavailableError(
                    f"Empty message content from {model}"
                )

            try:
                parsed = json.loads(content)

            except json.JSONDecodeError as exc:
                logger.error(
                    "Model %s returned invalid JSON: %s",
                    model,
                    content,
                )

                raise DeepSeekUnavailableError(
                    f"Invalid JSON response from {model}"
                ) from exc

            if not isinstance(parsed, dict):
                logger.error(
                    "Model %s returned JSON that is not an object: %s",
                    model,
                    parsed,
                )

                raise DeepSeekUnavailableError(
                    f"Unexpected JSON structure from {model}"
                )

            logger.info(
                "Model %s completed successfully.",
                model,
            )

            return parsed

        # ------------------------------------------------------------------
        # Rate limiting
        # ------------------------------------------------------------------

        except RateLimitError as exc:
            last_error = exc

            if attempt < MAX_RATE_LIMIT_RETRIES:
                delay = min(
                    BASE_BACKOFF_SECONDS * (2 ** attempt),
                    MAX_BACKOFF_SECONDS,
                )

                logger.warning(
                    "Model %s rate-limited "
                    "(attempt %d/%d). Retrying in %.1fs.",
                    model,
                    attempt + 1,
                    total_attempts,
                    delay,
                )

                time.sleep(delay)

                continue

            logger.error(
                "Model %s remained rate-limited after %d attempts.",
                model,
                total_attempts,
            )

            break

        # ------------------------------------------------------------------
        # Timeout
        # ------------------------------------------------------------------

        except APITimeoutError as exc:
            logger.error(
                "Model %s timed out after %.1f seconds: %s",
                model,
                REQUEST_TIMEOUT_SECONDS,
                exc,
            )

            raise DeepSeekUnavailableError(
                f"Timeout while calling {model}"
            ) from exc

        # ------------------------------------------------------------------
        # Provider/API errors
        # ------------------------------------------------------------------

        except APIError as exc:
            logger.error(
                "Model %s API/provider call failed: %s",
                model,
                exc,
            )

            raise DeepSeekUnavailableError(
                f"Provider error from {model}: {exc}"
            ) from exc

        # ------------------------------------------------------------------
        # Response structure errors
        # ------------------------------------------------------------------

        except (
            IndexError,
            AttributeError,
            TypeError,
        ) as exc:
            logger.error(
                "Model %s returned malformed response: %s",
                model,
                exc,
            )

            raise DeepSeekUnavailableError(
                f"Malformed LLM response from {model}"
            ) from exc

        # DeepSeekUnavailableError may be intentionally raised by
        # our defensive checks above. Preserve it as-is.
        except DeepSeekUnavailableError:
            raise

    # ----------------------------------------------------------------------
    # Rate-limit retries exhausted
    # ----------------------------------------------------------------------

    if last_error is not None:
        raise DeepSeekUnavailableError(
            f"Model {model} unavailable after "
            f"{total_attempts} attempts: {last_error}"
        ) from last_error

    raise DeepSeekUnavailableError(
        f"Model {model} is unavailable"
    )


def call_json(
    system_prompt: str,
    user_prompt: str,
) -> dict:
    """
    Try the primary model first.

    If the primary model fails because of:
    - timeout
    - provider overload
    - HTTP/API error
    - exhausted rate limit
    - malformed response

    try the configured fallback model immediately.

    Only raise DeepSeekUnavailableError if BOTH models fail.
    """

    primary_model = settings.deepseek_model
    fallback_model = settings.deepseek_fallback_model

    # ----------------------------------------------------------------------
    # Primary model
    # ----------------------------------------------------------------------

    try:
        logger.info(
            "Trying primary LLM model: %s",
            primary_model,
        )

        return _call_once(
            primary_model,
            system_prompt,
            user_prompt,
        )

    except DeepSeekUnavailableError as primary_error:

        # No fallback configured.
        if not fallback_model:
            logger.error(
                "Primary model %s failed and no fallback model "
                "is configured: %s",
                primary_model,
                primary_error,
            )

            raise

        # Prevent accidentally retrying the exact same model.
        if fallback_model == primary_model:
            logger.error(
                "Fallback model is identical to primary model: %s",
                primary_model,
            )

            raise DeepSeekUnavailableError(
                f"Primary model failed and fallback model is identical: "
                f"{primary_error}"
            ) from primary_error

        logger.warning(
            "Primary model (%s) failed: %s. "
            "Trying fallback model (%s).",
            primary_model,
            primary_error,
            fallback_model,
        )

    # ----------------------------------------------------------------------
    # Fallback model
    # ----------------------------------------------------------------------

    try:
        return _call_once(
            fallback_model,
            system_prompt,
            user_prompt,
        )

    except DeepSeekUnavailableError as fallback_error:
        logger.error(
            "Fallback model (%s) also failed: %s",
            fallback_model,
            fallback_error,
        )

        raise DeepSeekUnavailableError(
            "Both primary and fallback models failed. "
            f"Primary: {primary_error} | "
            f"Fallback: {fallback_error}"
        ) from fallback_error