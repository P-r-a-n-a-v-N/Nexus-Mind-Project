"""Unit tests for configuration and settings validation.

Author: Pranav N
"""

from pathlib import Path
from unittest.mock import patch

import pytest
from pydantic import ValidationError

from nexusmind.config import Settings


def test_settings_with_env_vars(tmp_path: Path) -> None:
    """Settings should load correctly from environment variables."""
    with patch.dict("os.environ", {
        "GEMINI_API_KEY": "test-api-key-12345",
        "WORKER_COUNT": "5",
        "QUEUE_MAXSIZE": "50",
    }):
        s = Settings(
            gemini_api_key="test-api-key-12345",
            inbox_dir=tmp_path / "inbox",
        )
        assert s.gemini_api_key == "test-api-key-12345"
        assert s.inbox_dir == tmp_path / "inbox"


def test_max_file_size_bytes_property() -> None:
    """max_file_size_bytes should convert MB to bytes correctly."""
    s = Settings(gemini_api_key="fake", max_file_size_mb=10.0)
    assert s.max_file_size_bytes == 10 * 1024 * 1024


def test_create_directories(tmp_path: Path) -> None:
    """create_directories should create all required paths."""
    s = Settings(
        gemini_api_key="fake",
        inbox_dir=tmp_path / "in",
        processed_dir=tmp_path / "proc",
        failed_dir=tmp_path / "fail",
        db_path=tmp_path / "db" / "nexusmind.db",
        log_dir=tmp_path / "logs",
    )
    s.create_directories()
    for d in [s.inbox_dir, s.processed_dir, s.failed_dir, s.log_dir, s.db_path.parent]:
        assert d.exists(), f"Expected directory to exist: {d}"


def test_temperature_out_of_range_raises() -> None:
    """Temperature above 2.0 should fail validation."""
    with pytest.raises(ValidationError):
        Settings(gemini_api_key="fake", temperature=3.0)


def test_worker_count_zero_raises() -> None:
    """Worker count of 0 should fail validation."""
    with pytest.raises(ValidationError):
        Settings(gemini_api_key="fake", worker_count=0)
