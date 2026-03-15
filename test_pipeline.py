"""Integration tests for the processing pipeline.

Author: Pranav N
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from nexusmind.config import Settings
from nexusmind.database import Database
from nexusmind.models import AISummary, FileMetadata, FileStatus
from nexusmind.monitor import FileMonitor
from nexusmind.pipeline import Pipeline
from nexusmind.processor import LLMProcessor


def _make_settings(tmp_path: Path) -> Settings:
    with patch.dict("os.environ", {"GEMINI_API_KEY": "fake"}):
        s = Settings(
            gemini_api_key="fake",
            inbox_dir=tmp_path / "inbox",
            processed_dir=tmp_path / "processed",
            failed_dir=tmp_path / "failed",
            db_path=tmp_path / "test.db",
            log_dir=tmp_path / "logs",
            worker_count=1,
        )
        s.create_directories()
        return s


def _make_summary(file_hash: str) -> AISummary:
    return AISummary(
        file_hash=file_hash,
        title="Test Title",
        summary="This is a test summary that is long enough to pass all validation checks.",
        key_topics=["AI", "Python"],
        entities=["Pranav N"],
        word_count=20,
        language="en",
        model_used="gemini-1.5-flash",
    )


@pytest.mark.asyncio
async def test_pipeline_processes_file_successfully(tmp_path: Path) -> None:
    """A valid file should end up as COMPLETED in the database."""
    settings = _make_settings(tmp_path)

    f = settings.inbox_dir / "paper.txt"
    f.write_text("This is a detailed research paper about machine learning.")

    db = Database(settings.db_path)
    await db.init()

    queue: asyncio.Queue = asyncio.Queue()
    loop = asyncio.get_event_loop()
    monitor = FileMonitor(settings, queue, loop)

    metadata = FileMetadata.from_path(f)
    summary = _make_summary(metadata.sha256_hash)

    mock_processor = MagicMock(spec=LLMProcessor)
    mock_processor.summarise = AsyncMock(return_value=summary)

    pipeline = Pipeline(settings, queue, db, monitor, mock_processor)

    await queue.put(metadata)
    pipeline.request_shutdown()
    await pipeline.run()

    records = await db.get_all_records()
    assert len(records) == 1
    assert records[0]["status"] == FileStatus.COMPLETED.value
    assert records[0]["title"] == "Test Title"

    await db.close()


@pytest.mark.asyncio
async def test_pipeline_handles_duplicate(tmp_path: Path) -> None:
    """A duplicate file (same hash) should be marked DUPLICATE, not re-processed."""
    settings = _make_settings(tmp_path)

    f = settings.inbox_dir / "dup.txt"
    f.write_text("duplicate content")

    db = Database(settings.db_path)
    await db.init()

    queue: asyncio.Queue = asyncio.Queue()
    loop = asyncio.get_event_loop()
    monitor = FileMonitor(settings, queue, loop)

    metadata = FileMetadata.from_path(f)
    summary = _make_summary(metadata.sha256_hash)

    # Pre-insert the record to simulate duplicate
    await db.upsert_record(metadata, summary=summary, status=FileStatus.COMPLETED)

    mock_processor = MagicMock(spec=LLMProcessor)
    mock_processor.summarise = AsyncMock(return_value=summary)

    # Write the file back (it was consumed by from_path earlier)
    f2 = settings.inbox_dir / "dup2.txt"
    f2.write_text("duplicate content")
    meta2 = FileMetadata.from_path(f2)
    # Manually set same hash
    meta2 = meta2.model_copy(update={"sha256_hash": metadata.sha256_hash})

    pipeline = Pipeline(settings, queue, db, monitor, mock_processor)
    await queue.put(meta2)
    pipeline.request_shutdown()
    await pipeline.run()

    # summarise should NOT have been called
    mock_processor.summarise.assert_not_called()
    await db.close()


@pytest.mark.asyncio
async def test_pipeline_marks_failed_on_processing_error(tmp_path: Path) -> None:
    """A ProcessingError in summarise should mark the file as FAILED."""
    from nexusmind.processor import ProcessingError

    settings = _make_settings(tmp_path)
    f = settings.inbox_dir / "bad.txt"
    f.write_text("some content")

    db = Database(settings.db_path)
    await db.init()

    queue: asyncio.Queue = asyncio.Queue()
    loop = asyncio.get_event_loop()
    monitor = FileMonitor(settings, queue, loop)

    metadata = FileMetadata.from_path(f)

    mock_processor = MagicMock(spec=LLMProcessor)
    mock_processor.summarise = AsyncMock(
        side_effect=ProcessingError("Simulated LLM failure")
    )

    pipeline = Pipeline(settings, queue, db, monitor, mock_processor)
    await queue.put(metadata)
    pipeline.request_shutdown()
    await pipeline.run()

    records = await db.get_all_records()
    assert records[0]["status"] == FileStatus.FAILED.value
    assert "Simulated LLM failure" in (records[0]["error_message"] or "")

    await db.close()
