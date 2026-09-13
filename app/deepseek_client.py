"""
Thin wrapper around the LLM provider's OpenAI-compatible chat completions
API (currently routed through OpenRouter — see config.py).

UPDATED: added automatic fallback to a secondary model. Free-tier models
on OpenRouter occasionally return a 502 "Service temporarily overloaded"
from the upstream provider (we've hit this repeatedly with Nemotron 3
Ultra) even after our retry-with-backoff logic exhausts its attempts.
Rather than give up immediately, we now try one backup model before
surfacing DeepSeekUnavailableError to the caller.
"""

import json
import logging
import time

from openai import APIError, APITimeoutError, OpenAI, RateLimitError

from app.config import settings

logger = logging.getLogger("vibelocate.llm")

_client = OpenAI(
    api_key=settings.deepseek_api_key,
    base_url=settings.deepseek_base_url,
    timeout=settings.llm_timeout_seconds,
)

MAX_RATE_LIMIT_RETRIES = 5
BASE_BACKOFF_SECONDS = 3.0
MAX_BACKOFF_SECONDS = 15.0


class DeepSeekUnavailableError(Exception):
    """Raised when the LLM call fails or times out (NFR3.01: graceful degradation)."""


def _call_once(model: str, system_prompt: str, user_prompt: str) -> dict:
    """
    Calls a single model with retry-with-backoff on 429 (rate limit).
    Raises DeepSeekUnavailableError on any unrecoverable failure for
    THIS model — the caller (call_json) decides whether to fall back
    to a different model or give up entirely.
    """
    last_error: Exception | None = None

    for attempt in range(MAX_RATE_LIMIT_RETRIES + 1):
        try:
            response = _client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                response_format={"type": "json_object"},
                temperature=0.1,
            )

            # Defensive check: some providers return a 200 with an empty
            # `choices` when their upstream is overloaded (502-in-a-200),
            # instead of raising a normal HTTP error.
            if not response.choices:
                logger.error("Model %s returned no choices — raw response: %s", model, response)
                raise DeepSeekUnavailableError(f"Empty response from {model} (no choices)")

            content = response.choices[0].message.content
            if not content:
                logger.error("Model %s returned empty message content.", model)
                raise DeepSeekUnavailableError(f"Empty message content from {model}")

            return json.loads(content)

        except RateLimitError as exc:
            last_error = exc
            if attempt < MAX_RATE_LIMIT_RETRIES:
                delay = min(BASE_BACKOFF_SECONDS * (2 ** attempt), MAX_BACKOFF_SECONDS)
                logger.warning(
                    "Model %s rate-limited (attempt %d/%d), retrying in %.1fs",
                    model, attempt + 1, MAX_RATE_LIMIT_RETRIES, delay,
                )
                time.sleep(delay)
                continue
            logger.error("Model %s still rate-limited after %d retries", model, MAX_RATE_LIMIT_RETRIES)

        except (APIError, APITimeoutError) as exc:
            logger.error("Model %s call failed: %s", model, exc)
            raise DeepSeekUnavailableError(str(exc)) from exc

        except (json.JSONDecodeError, IndexError, AttributeError, TypeError) as exc:
            logger.error("Model %s returned malformed response: %s", model, exc)
            raise DeepSeekUnavailableError("Malformed LLM response") from exc

    raise DeepSeekUnavailableError(str(last_error))


def call_json(system_prompt: str, user_prompt: str) -> dict:
    """
    Tries the primary model first. If it fails for ANY reason (rate limit
    exhausted, provider 502, timeout, malformed response), automatically
    tries the backup model before giving up. Only raises
    DeepSeekUnavailableError if BOTH models fail.
    """
    try:
        return _call_once(settings.deepseek_model, system_prompt, user_prompt)
    except DeepSeekUnavailableError as primary_error:
        if not settings.deepseek_fallback_model:
            raise  # no backup configured — behave exactly as before

        logger.warning(
            "Primary model (%s) failed: %s — trying fallback model (%s)",
            settings.deepseek_model, primary_error, settings.deepseek_fallback_model,
        )
        try:
            return _call_once(settings.deepseek_fallback_model, system_prompt, user_prompt)
        except DeepSeekUnavailableError as fallback_error:
            logger.error(
                "Fallback model (%s) also failed: %s",
                settings.deepseek_fallback_model, fallback_error,
            )
            raise DeepSeekUnavailableError(
                f"Both primary and fallback models failed. "
                f"Primary: {primary_error} | Fallback: {fallback_error}"
            ) from fallback_error