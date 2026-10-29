"""
SilentGPT Backend — config.py
All settings are loaded from environment variables (.env file).
No secrets are hardcoded.
"""

from pathlib import Path
from functools import lru_cache
from pydantic_settings import BaseSettings, SettingsConfigDict

_ENV_FILE = Path(__file__).resolve().parent / ".env"


class Settings(BaseSettings):
    # ── Ollama ──────────────────────────────────────────────────
    OLLAMA_BASE_URL: str = "http://localhost:11434"
    OLLAMA_MODEL: str = "gemma4:26b"          # default text model
    OLLAMA_VISION_MODEL: str = "llava:latest" # vision/image model

    # ── Gemini ──────────────────────────────────────────────────
    GEMINI_API_KEY: str = ""

    # ── Web Search ──────────────────────────────────────────────
    # Set SEARCH_PROVIDER to "tavily" or "serper"
    SEARCH_PROVIDER: str = "tavily"
    TAVILY_API_KEY: str = ""
    SERPER_API_KEY: str = ""
    SEARCH_MAX_RESULTS: int = 5

    # ── CORS ────────────────────────────────────────────────────
    # In production, replace "*" with your actual frontend URL
    ALLOWED_ORIGINS: list[str] = ["*"]

    # ── Image ───────────────────────────────────────────────────
    MAX_IMAGE_SIZE_MB: int = 10  # reject images above this size

    # ── Zero Data Retention ─────────────────────────────────────
    # These flags enforce ZDR behaviour in code — do not change.
    ZERO_DATA_RETENTION: bool = True
    LOG_USER_MESSAGES: bool = False  # must stay False for privacy

    model_config = SettingsConfigDict(
        env_file=(_ENV_FILE, ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )


@lru_cache()
def get_settings() -> Settings:
    """Cached settings instance — loaded once per process."""
    return Settings()
