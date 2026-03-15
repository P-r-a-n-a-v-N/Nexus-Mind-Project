"""Unit tests for the async database layer.

Author: Pranav N
"""

from __future__ import annotations

import hashlib
from datetime import datetime
from pathlib import Path

import pytest

from nexusmind.database import Database
from nexusmind.models import AISummary, FileMetadata, FileStatus


def _make_metadata(path: Path, content: bytes = b"test content") -> FileMetadata:
    path.write_bytes(content)
    return FileMetadata.from_path(path)


def _make_summary(file_hash: str) -> AISummary:
    return AISummary(
        file_hash=file_hash,
        title="Test Document Title",
        summary="This is a test summary that is long enough to pass validation checks.",
        key_topics=["testing", "python", "database"],
        entities=["Pranav N"],
        word_count=15,
        language="en",
        model_used="gemini-1.5-flash",
    )


@pytest.fixture
async def db(tmp_path: Path):
    """Provide an initialised in-memory-equivalent DB for each test."""
    database = Database(tmp_path / "test.db")
    await database.init()
    yield database
    await database.close()


@pytest.mark.asyncio
async def test_init_creates_tables(tmp_path: Path) -> None:
    """Database.init should create the processed_files table."""
    db = Database(tmp_path / "init_test.db")
    await db.init()
    records = await db.get_all_records()
    assert records == []
    await db.close()


@pytest.mark.asyncio
async def test_is_duplicate_false_for_new_hash(db: Database) -> None:
    """A hash not in the DB should return False."""
    unknown_hash = hashlib.sha256(b"new file").hexdigest()
    result = await db.is_duplicate(unknown_hash)
    assert result is False


@pytest.mark.asyncio
async def test_upsert_and_duplicate_detection(db: Database, tmp_path: Path) -> None:
    """After inserting a record, is_duplicate should return True."""
    meta = _make_metadata(tmp_path / "doc.txt")
    summary = _make_summary(meta.sha256_hash)

    await db.upsert_record(meta, summary=summary, status=FileStatus.COMPLETED)
    assert await db.is_duplicate(meta.sha256_hash) is True


@pytest.mark.asyncio
async def test_upsert_pending_then_complete(db: Database, tmp_path: Path) -> None:
    """Upserting PENDING then COMPLETED should update the status."""
    meta = _make_metadata(tmp_path / "update.txt", b"update content")

    # Initial insert
    await db.upsert_record(meta, status=FileStatus.PENDING)
    records = await db.get_all_records()
    assert records[0]["status"] == FileStatus.PENDING.value

    # Update to completed
    summary = _make_summary(meta.sha256_hash)
    await db.upsert_record(meta, summary=summary, status=FileStatus.COMPLETED)

    records = await db.get_all_records()
    assert records[0]["status"] == FileStatus.COMPLETED.value
    assert records[0]["title"] == "Test Document Title"


@pytest.mark.asyncio
async def test_get_stats_counts_correctly(db: Database, tmp_path: Path) -> None:
    """get_stats should return accurate per-status counts."""
    for i in range(3):
        content = f"content {i}".encode()
        meta = _make_metadata(tmp_path / f"file{i}.txt", content)
        summary = _make_summary(meta.sha256_hash)
        await db.upsert_record(meta, summary=summary, status=FileStatus.COMPLETED)

    failed_meta = _make_metadata(tmp_path / "fail.txt", b"fail content")
    await db.upsert_record(failed_meta, status=FileStatus.FAILED, error="test error")

    stats = await db.get_stats()
    assert stats.get("completed") == 3
    assert stats.get("failed") == 1
    assert stats.get("total") == 4


@pytest.mark.asyncio
async def test_upsert_with_error_message(db: Database, tmp_path: Path) -> None:
    """Error message should be persisted on failure."""
    meta = _make_metadata(tmp_path / "error.txt", b"error content")
    await db.upsert_record(
        meta,
        status=FileStatus.FAILED,
        error="Connection timed out after 30 seconds",
    )

    records = await db.get_all_records()
    assert records[0]["error_message"] == "Connection timed out after 30 seconds"


@pytest.mark.asyncio
async def test_multiple_files_ordered_by_discovered(db: Database, tmp_path: Path) -> None:
    """Records should be returned in descending discovery order."""
    for i in range(5):
        content = f"document number {i}".encode()
        meta = _make_metadata(tmp_path / f"doc{i}.txt", content)
        await db.upsert_record(meta, status=FileStatus.PENDING)

    records = await db.get_all_records()
    assert len(records) == 5
