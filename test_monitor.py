"""Unit tests for the file monitor module.

Author: Pranav N
"""

from __future__ import annotations

import asyncio
import hashlib
import shutil
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from nexusmind.config import Settings
from nexusmind.monitor import FileMonitor, InboxEventHandler


def _make_settings(tmp_path: Path) -> Settings:
    """Build a minimal Settings object pointing at tmp directories."""
    with patch.dict("os.environ", {"GEMINI_API_KEY": "fake-key"}):
        s = Settings(
            gemini_api_key="fake-key",
            inbox_dir=tmp_path / "inbox",
            processed_dir=tmp_path / "processed",
            failed_dir=tmp_path / "failed",
            db_path=tmp_path / "test.db",
            log_dir=tmp_path / "logs",
        )
        s.create_directories()
        return s


@pytest.mark.asyncio
async def test_scan_existing_enqueues_files(tmp_path: Path) -> None:
    """scan_existing should enqueue all supported files already in inbox."""
    settings = _make_settings(tmp_path)

    # Create files in inbox
    (settings.inbox_dir / "paper.txt").write_text("Research paper content here.")
    (settings.inbox_dir / "notes.md").write_text("# Notes\nSome notes here.")
    (settings.inbox_dir / "data.csv").write_text("a,b,c")  # Should be ignored

    queue: asyncio.Queue = asyncio.Queue()
    loop = asyncio.get_event_loop()
    monitor = FileMonitor(settings, queue, loop)

    await monitor.scan_existing()

    assert queue.qsize() == 2  # CSV should be skipped


@pytest.mark.asyncio
async def test_scan_existing_empty_inbox(tmp_path: Path) -> None:
    """scan_existing on an empty inbox should leave queue empty."""
    settings = _make_settings(tmp_path)
    queue: asyncio.Queue = asyncio.Queue()
    loop = asyncio.get_event_loop()
    monitor = FileMonitor(settings, queue, loop)

    await monitor.scan_existing()
    assert queue.empty()


def test_move_to_processed(tmp_path: Path) -> None:
    """move_to_processed should relocate file to processed dir."""
    settings = _make_settings(tmp_path)
    f = settings.inbox_dir / "report.txt"
    f.write_text("content")

    queue: asyncio.Queue = asyncio.Queue()
    loop = asyncio.get_event_loop()
    monitor = FileMonitor(settings, queue, loop)
    monitor.move_to_processed(f)

    assert not f.exists()
    assert (settings.processed_dir / "report.txt").exists()


def test_move_to_failed(tmp_path: Path) -> None:
    """move_to_failed should relocate file to failed dir."""
    settings = _make_settings(tmp_path)
    f = settings.inbox_dir / "broken.pdf"
    f.write_bytes(b"bad pdf data")

    queue: asyncio.Queue = asyncio.Queue()
    loop = asyncio.get_event_loop()
    monitor = FileMonitor(settings, queue, loop)
    monitor.move_to_failed(f)

    assert not f.exists()
    assert (settings.failed_dir / "broken.pdf").exists()


def test_event_handler_skips_unsupported() -> None:
    """InboxEventHandler should ignore files with unsupported extensions."""
    queue = asyncio.Queue()
    loop = asyncio.new_event_loop()
    settings = MagicMock()
    settings.file_lock_timeout = 5.0

    handler = InboxEventHandler(queue, loop, settings)

    mock_event = MagicMock()
    mock_event.is_directory = False
    mock_event.src_path = "/inbox/data.csv"

    # Should not enqueue anything
    handler.on_created(mock_event)
    assert queue.empty()
    loop.close()


def test_event_handler_skips_directories() -> None:
    """InboxEventHandler should ignore directory creation events."""
    queue = asyncio.Queue()
    loop = asyncio.new_event_loop()
    settings = MagicMock()

    handler = InboxEventHandler(queue, loop, settings)

    mock_event = MagicMock()
    mock_event.is_directory = True
    mock_event.src_path = "/inbox/somedir"

    handler.on_created(mock_event)
    assert queue.empty()
    loop.close()
