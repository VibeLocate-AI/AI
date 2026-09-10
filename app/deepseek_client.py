"""
Thin wrapper around the LLM provider's OpenAI-compatible chat completions
API (currently routed through OpenRouter — see config.py).
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


def call_json(system_prompt: str, user_prompt: str) -> dict:
    last_error: Exception | None = None

    for attempt in range(MAX_RATE_LIMIT_RETRIES + 1):
        try:
            response = _client.chat.completions.create(
                model=settings.deepseek_model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                response_format={"type": "json_object"},
                temperature=0.1,
            )

            # DEFENSIVE CHECK: some free-tier models occasionally return a
            # 200 response with no actual choices (empty/malformed reply
            # from the provider, not a Python-level exception). Without
            # this check, response.choices[0] raises an unhandled
            # TypeError instead of the graceful DeepSeekUnavailableError
            # path, crashing whatever script/endpoint called us.
            if not response.choices:
                logger.error("LLM returned no choices — raw response: %s", response)
                raise DeepSeekUnavailableError("Empty response from LLM (no choices)")

            content = response.choices[0].message.content
            if not content:
                logger.error("LLM returned an empty message content.")
                raise DeepSeekUnavailableError("Empty message content from LLM")

            return json.loads(content)

        except RateLimitError as exc:
            last_error = exc
            if attempt < MAX_RATE_LIMIT_RETRIES:
                delay = min(BASE_BACKOFF_SECONDS * (2 ** attempt), MAX_BACKOFF_SECONDS)
                logger.warning(
                    "LLM rate-limited (attempt %d/%d), retrying in %.1fs",
                    attempt + 1, MAX_RATE_LIMIT_RETRIES, delay,
                )
                time.sleep(delay)
                continue
            logger.error("LLM still rate-limited after %d retries", MAX_RATE_LIMIT_RETRIES)

        except (APIError, APITimeoutError) as exc:
            logger.error("LLM call failed: %s", exc)
            raise DeepSeekUnavailableError(str(exc)) from exc

        except (json.JSONDecodeError, IndexError, AttributeError, TypeError) as exc:
            logger.error("LLM returned malformed response: %s", exc)
            raise DeepSeekUnavailableError("Malformed LLM response") from exc

    raise DeepSeekUnavailableError(str(last_error))