"""
Configuration for the VibeLocate AI micro-service.
"""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    deepseek_api_key: str = "sk-placeholder-set-me-in-env"
    deepseek_base_url: str = "https://openrouter.ai/api/v1"
    deepseek_model: str = "nvidia/nemotron-3-ultra:free"
    deepseek_fallback_model: str = ""
    llm_timeout_seconds: float = 20.0

    # UPDATED: base URL of the Laravel backend. Used by property_matcher.py
    # to fetch real property listings. No dedicated filter/search endpoint
    # has been confirmed with the backend team yet, so we currently fetch
    # everything from /api/home and filter client-side — see
    # property_matcher.py's module docstring for the plan to swap this
    # out once a real filter endpoint is confirmed.
    laravel_base_url: str = "https://vibelocate-laravel.onrender.com"
    laravel_timeout_seconds: float = 15.0

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")


settings = Settings()
