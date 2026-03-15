"""NexusMind Configuration Management.

Loads all settings from environment variables with strong validation.
Author: Pranav N
"""

from pathlib import Path
from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application-wide settings loaded from .env file.

    All secrets are sourced from environment variables — never hardcoded.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # ── API Keys ──────────────────────────────────────────────────────────
    gemini_api_key: str = Field(..., description="Google Gemini API key")

    # ── Paths ─────────────────────────────────────────────────────────────
    inbox_dir: Path = Field(default=Path("data/inbox"), description="Directory to monitor")
    processed_dir: Path = Field(default=Path("data/processed"), description="Processed files")
    failed_dir: Path = Field(default=Path("data/failed"), description="Failed files")
    db_path: Path = Field(default=Path("data/nexusmind.db"), description="SQLite DB path")
    log_dir: Path = Field(default=Path("logs"), description="Log directory")

    # ── LLM Settings ──────────────────────────────────────────────────────
    gemini_model: str = Field(default="gemini-1.5-flash", description="Gemini model name")
    max_tokens: int = Field(default=8192, ge=256, le=32768)
    temperature: float = Field(default=0.2, ge=0.0, le=2.0)

    # ── Pipeline Settings ─────────────────────────────────────────────────
    queue_maxsize: int = Field(default=100, ge=1, le=1000)
    worker_count: int = Field(default=3, ge=1, le=20)
    poll_interval: float = Field(default=2.0, ge=0.5, le=60.0)
    file_lock_timeout: float = Field(default=10.0, ge=1.0, le=120.0)
    max_file_size_mb: float = Field(default=50.0, ge=0.1, le=500.0)

    # ── Retry Settings ────────────────────────────────────────────────────
    max_retries: int = Field(default=5, ge=1, le=20)
    retry_min_wait: float = Field(default=1.0)
    retry_max_wait: float = Field(default=60.0)

    @field_validator("inbox_dir", "processed_dir", "failed_dir", "log_dir", mode="before")
    @classmethod
    def ensure_path(cls, v: str | Path) -> Path:
        """Convert string paths to Path objects."""
        return Path(v)

    @property
    def max_file_size_bytes(self) -> int:
        """Return max file size in bytes."""
        return int(self.max_file_size_mb * 1024 * 1024)

    def create_directories(self) -> None:
        """Ensure all required directories exist."""
        for directory in [
            self.inbox_dir,
            self.processed_dir,
            self.failed_dir,
            self.log_dir,
            self.db_path.parent,
        ]:
            directory.mkdir(parents=True, exist_ok=True)


_settings: Settings | None = None


def get_settings() -> Settings:
    """Return cached application settings (singleton)."""
    global _settings
    if _settings is None:
        _settings = Settings()  # type: ignore[call-arg]
    return _settings
