"""
Configuration for the VibeLocate AI micro-service.

Following Chapter 4 (System Design) of the SRS:
- This service is the "AI & NLP Processing Service (Inference Engine)"
- Built with Python / FastAPI
- Delegates all LLM work to the DeepSeek API (per Limitations 1.4:
  "No self-hosted AI models")
"""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # DeepSeek uses an OpenAI-compatible API, so we reuse the openai SDK
    # and just point it at DeepSeek's base_url.
    deepseek_api_key: str = "sk-placeholder-set-me-in-env"
    deepseek_base_url: str = "https://api.deepseek.com"
    deepseek_model: str = "deepseek-chat"

    # NFR1.01: search results within 2 seconds. We give the LLM call
    # a hard timeout well under that budget so the API can still
    # fall back gracefully (NFR3.01) instead of hanging.
    llm_timeout_seconds: float = 8.0

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")


settings = Settings()
