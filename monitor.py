"""NexusMind File Monitor.

Uses watchdog PollingObserver for cross-platform file-system event detection.
Implements file-level locking and producer-consumer queue feeding.
Author: Pranav N
"""

from __future__ import annotations

import asyncio
import shutil
from pathlib import Path

from filelock import FileLock, Timeout
from loguru import logger
from pydantic import ValidationError
from watchdog.events import FileCreatedEvent, FileSystemEventHandler
from watchdog.observers.polling import PollingObserver

from nexusmind.config import Settings
from nexusmind.models import FileMetadata, SupportedExtension


class InboxEventHandler(FileSystemEventHandler):
    """Handles new file events from watchdog and feeds them to the async queue.

    Uses a synchronous callback to put paths onto an asyncio.Queue via
    call_soon_threadsafe to safely bridge the watchdog thread and the event loop.
    """

    _SUPPORTED = {ext.value for ext in SupportedExtension}

    def __init__(
        self,
        queue: asyncio.Queue,
        loop: asyncio.AbstractEventLoop,
        settings: Settings,
    ) -> None:
        """Initialise the handler.

        Args:
            queue: Async queue to push discovered file paths.
            loop: The running event loop (for thread-safe scheduling).
            settings: Application settings.
        """
        super().__init__()
        self._queue = queue
        self._loop = loop
        self._settings = settings
        self._seen: set[str] = set()

    def on_created(self, event: FileCreatedEvent) -> None:
        """Called by watchdog when a new file appears in the inbox.

        Args:
            event: Watchdog file-system event.
        """
        if event.is_directory:
            return

        path = Path(str(event.src_path))

        if path.suffix.lower() not in self._SUPPORTED:
            logger.debug("Skipping unsupported file: {}", path.name)
            return

        if str(path) in self._seen:
            return
        self._seen.add(str(path))

        logger.info("📄 Detected new file: {}", path.name)
        # Schedule coroutine from the watchdog thread safely
        asyncio.run_coroutine_threadsafe(
            self._enqueue(path), self._loop
        )

    async def _enqueue(self, path: Path) -> None:
        """Safely acquire a file lock and push validated metadata to the queue.

        Args:
            path: Path to the file to enqueue.
        """
        lock_path = path.with_suffix(path.suffix + ".lock")
        lock = FileLock(str(lock_path), timeout=self._settings.file_lock_timeout)

        try:
            with lock.acquire(timeout=self._settings.file_lock_timeout):
                if not path.exists():
                    logger.warning("File disappeared before processing: {}", path.name)
                    return

                size = path.stat().st_size
                if size > self._settings.max_file_size_bytes:
                    logger.warning(
                        "File too large ({} MB > {} MB): {}",
                        size / 1_048_576,
                        self._settings.max_file_size_mb,
                        path.name,
                    )
                    return

                try:
                    metadata = FileMetadata.from_path(path.resolve())
                except (ValidationError, ValueError) as exc:
                    logger.error("Metadata validation failed for {}: {}", path.name, exc)
                    return

                await self._queue.put(metadata)
                logger.debug("Enqueued: {} (queue size: {})", path.name, self._queue.qsize())

        except Timeout:
            logger.error(
                "Could not acquire lock for {} — file may be locked by another process.",
                path.name,
            )
        except Exception as exc:  # noqa: BLE001
            logger.error("Unexpected error enqueuing {}: {}", path.name, exc)
        finally:
            # Clean up lock file
            if lock_path.exists():
                try:
                    lock_path.unlink()
                except OSError:
                    pass


class FileMonitor:
    """Manages the watchdog PollingObserver lifecycle.

    Scans an inbox directory continuously using polling so that NAS and
    cross-platform environments are supported reliably.
    """

    def __init__(
        self,
        settings: Settings,
        queue: asyncio.Queue,
        loop: asyncio.AbstractEventLoop,
    ) -> None:
        """Initialise the monitor.

        Args:
            settings: Application settings.
            queue: Async queue to feed discovered files into.
            loop: The running asyncio event loop.
        """
        self._settings = settings
        self._queue = queue
        self._loop = loop
        self._observer: PollingObserver | None = None
        self._handler = InboxEventHandler(queue, loop, settings)

    def start(self) -> None:
        """Start the polling observer in a background thread."""
        self._observer = PollingObserver(timeout=self._settings.poll_interval)
        self._observer.schedule(
            self._handler,
            str(self._settings.inbox_dir),
            recursive=False,
        )
        self._observer.start()
        logger.info(
            "👁 FileMonitor started. Watching: {} (poll={:.1f}s)",
            self._settings.inbox_dir,
            self._settings.poll_interval,
        )

    def stop(self) -> None:
        """Stop the polling observer gracefully."""
        if self._observer and self._observer.is_alive():
            self._observer.stop()
            self._observer.join(timeout=10)
            logger.info("FileMonitor stopped.")

    async def scan_existing(self) -> None:
        """On startup, enqueue any files already present in the inbox.

        This ensures files dropped while the service was offline are processed.
        """
        inbox = self._settings.inbox_dir
        supported = {ext.value for ext in SupportedExtension}
        found = 0

        for path in inbox.iterdir():
            if path.is_file() and path.suffix.lower() in supported:
                await self._handler._enqueue(path.resolve())
                found += 1

        if found:
            logger.info("Startup scan found {} existing file(s) in inbox.", found)

    def move_to_processed(self, path: Path) -> None:
        """Move a successfully processed file to the processed directory.

        Args:
            path: Source file path.
        """
        dest = self._settings.processed_dir / path.name
        try:
            shutil.move(str(path), str(dest))
            logger.debug("Moved {} → processed/", path.name)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Could not move {} to processed: {}", path.name, exc)

    def move_to_failed(self, path: Path) -> None:
        """Move a failed file to the failed directory for manual inspection.

        Args:
            path: Source file path.
        """
        dest = self._settings.failed_dir / path.name
        try:
            shutil.move(str(path), str(dest))
            logger.warning("Moved {} → failed/", path.name)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Could not move {} to failed: {}", path.name, exc)
