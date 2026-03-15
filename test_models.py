"""Unit tests for Pydantic data models.

Author: Pranav N
"""

import hashlib
from datetime import datetime
from pathlib import Path

import pytest
from pydantic import ValidationError

from nexusmind.models import AISummary, FileMetadata, FileStatus, ProcessingRecord


# ── FileMetadata tests ─────────────────────────────────────────────────────────


def _make_valid_hash() -> str:
    return hashlib.sha256(b"test").hexdigest()


def test_file_metadata_valid(tmp_path: Path) -> None:
    """FileMetadata should be constructable from a valid file."""
    f = tmp_path / "test.txt"
    f.write_text("hello world")
    meta = FileMetadata.from_path(f)
    assert meta.file_name == "test.txt"
    assert meta.extension == ".txt"
    assert meta.size_bytes == len("hello world")
    assert len(meta.sha256_hash) == 64
    assert meta.status == FileStatus.PENDING


def test_file_metadata_pdf(tmp_path: Path) -> None:
    """FileMetadata should accept .pdf extension."""
    f = tmp_path / "doc.pdf"
    f.write_bytes(b"%PDF-1.4 fake content")
    meta = FileMetadata.from_path(f)
    assert meta.extension == ".pdf"


def test_file_metadata_invalid_hash() -> None:
    """Constructing with an invalid hash should raise ValidationError."""
    with pytest.raises(ValidationError):
        FileMetadata(
            file_path=Path("/some/path/test.txt"),
            file_name="test.txt",
            extension=".txt",
            size_bytes=100,
            sha256_hash="not_a_real_hash",
        )


def test_file_metadata_path_name_mismatch() -> None:
    """file_name must match the filename in file_path."""
    valid_hash = _make_valid_hash()
    with pytest.raises(ValidationError):
        FileMetadata(
            file_path=Path("/some/path/actual.txt"),
            file_name="different.txt",
            extension=".txt",
            size_bytes=100,
            sha256_hash=valid_hash,
        )


def test_file_metadata_missing_file() -> None:
    """from_path should raise FileNotFoundError for non-existent file."""
    with pytest.raises(FileNotFoundError):
        FileMetadata.from_path(Path("/nonexistent/file.txt"))


def test_file_metadata_negative_size() -> None:
    """Negative size_bytes should fail validation."""
    valid_hash = _make_valid_hash()
    with pytest.raises(ValidationError):
        FileMetadata(
            file_path=Path("/some/path/test.txt"),
            file_name="test.txt",
            extension=".txt",
            size_bytes=-1,
            sha256_hash=valid_hash,
        )


# ── AISummary tests ────────────────────────────────────────────────────────────


def test_ai_summary_valid() -> None:
    """AISummary should be constructable with all valid fields."""
    summary = AISummary(
        file_hash=_make_valid_hash(),
        title="Test Document",
        summary="This is a test summary with enough content to pass validation.",
        key_topics=["AI", "testing", "Python"],
        entities=["Pranav N", "NexusMind"],
        word_count=10,
        language="en",
        model_used="gemini-1.5-flash",
    )
    assert summary.title == "Test Document"
    assert len(summary.key_topics) == 3


def test_ai_summary_empty_topics() -> None:
    """key_topics can be empty."""
    summary = AISummary(
        file_hash=_make_valid_hash(),
        title="Empty Topics",
        summary="A summary with no topics identified at all here.",
        key_topics=[],
    )
    assert summary.key_topics == []


def test_ai_summary_sanitises_whitespace() -> None:
    """key_topics should strip whitespace and remove empty strings."""
    summary = AISummary(
        file_hash=_make_valid_hash(),
        title="Whitespace Test",
        summary="A long enough summary to pass the minimum length check.",
        key_topics=["  Python  ", "", "  AI  ", "   "],
    )
    assert summary.key_topics == ["Python", "AI"]


def test_ai_summary_short_summary_fails() -> None:
    """Summary shorter than 10 chars should fail validation."""
    with pytest.raises(ValidationError):
        AISummary(
            file_hash=_make_valid_hash(),
            title="Test",
            summary="short",  # < 10 chars
        )


def test_ai_summary_confidence_out_of_range() -> None:
    """confidence_score outside [0, 1] should fail."""
    with pytest.raises(ValidationError):
        AISummary(
            file_hash=_make_valid_hash(),
            title="Test",
            summary="A sufficiently long summary to pass validation.",
            confidence_score=1.5,
        )


# ── FileStatus tests ───────────────────────────────────────────────────────────


def test_file_status_enum_values() -> None:
    """All expected statuses should be accessible."""
    statuses = {
        FileStatus.PENDING, FileStatus.PROCESSING,
        FileStatus.COMPLETED, FileStatus.FAILED,
        FileStatus.DUPLICATE, FileStatus.SKIPPED,
    }
    assert len(statuses) == 6


def test_file_status_string_comparison() -> None:
    """FileStatus members should compare equal to their string values."""
    assert FileStatus.COMPLETED == "completed"
    assert FileStatus.FAILED == "failed"
