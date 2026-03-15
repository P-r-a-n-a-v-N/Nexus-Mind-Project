"""NexusMind Processing Pipeline.

Worker pool using asyncio.TaskGroup. Each worker pulls from the queue,
processes files through the LLM, and persists results to the database.
Author: Pranav N
"""

from __future__ import annotations

import asyncio

from loguru import logger

from nexusmind.config import Settings
from nexusmind.database import Database
from nexusmind.models import FileMetadata, FileStatus
from nexusmind.monitor import FileMonitor
from nexusmind.processor import LLMProcessor, ProcessingError, RateLimitError, extract_text


class Pipeline:
    """Coordinates the producer-consumer processing pipeline.

    Each worker:
        1. Pulls FileMetadata from the queue
        2. Checks DB for duplicates (idempotency)
        3. Extracts text from the file
        4. Calls the LLM for a structured summary
        5. Persists the result to SQLite
        6. Moves the file to processed/ or failed/
    """

    def __init__(
        self,
        settings: Settings,
        queue: asyncio.Queue,
        db: Database,
        monitor: FileMonitor,
        processor: LLMProcessor,
    ) -> None:
        self._settings = settings
        self._queue = queue
        self._db = db
        self._monitor = monitor
        self._processor = processor
        self._shutdown = asyncio.Event()

    def request_shutdown(self) -> None:
        """Signal all workers to stop after finishing current tasks."""
        self._shutdown.set()
        logger.info("Shutdown requested — workers will finish current tasks.")

    async def run(self) -> None:
        """Start N workers using asyncio.TaskGroup (Python 3.11+).

        Workers run concurrently. If one raises, others continue due to
        individual try/except inside each worker coroutine.
        """
        logger.info("Starting {} pipeline workers.", self._settings.worker_count)
        async with asyncio.TaskGroup() as tg:
            for i in range(self._settings.worker_count):
                tg.create_task(self._worker(worker_id=i))
        logger.info("All pipeline workers have exited.")

    async def _worker(self, worker_id: int) -> None:
        """Single pipeline worker coroutine.

        Continuously dequeues and processes files until shutdown is requested
        and the queue is empty.

        Args:
            worker_id: Numeric identifier for log tracing.
        """
        logger.info("Worker-{} started.", worker_id)
        while not (self._shutdown.is_set() and self._queue.empty()):
            try:
                metadata: FileMetadata = await asyncio.wait_for(
                    self._queue.get(), timeout=1.0
                )
            except asyncio.TimeoutError:
                continue
            except asyncio.CancelledError:
                logger.info("Worker-{} received CancelledError — exiting cleanly.", worker_id)
                return

            logger.info(
                "Worker-{} → processing: {} (queue remaining: {})",
                worker_id,
                metadata.file_name,
                self._queue.qsize(),
            )

            await self._process_one(metadata, worker_id)
            self._queue.task_done()

        logger.info("Worker-{} finished.", worker_id)

    async def _process_one(self, metadata: FileMetadata, worker_id: int) -> None:
        """Execute the full processing pipeline for a single file.

        Args:
            metadata: Validated file metadata.
            worker_id: Worker identifier for logging.
        """
        # ── Idempotency check ─────────────────────────────────────────────
        if await self._db.is_duplicate(metadata.sha256_hash):
            logger.info(
                "Worker-{}: Skipping duplicate file: {} (hash: {})",
                worker_id,
                metadata.file_name,
                metadata.sha256_hash[:12],
            )
            metadata.status = FileStatus.DUPLICATE
            await self._db.upsert_record(metadata, status=FileStatus.DUPLICATE)
            return

        # ── Mark as processing ────────────────────────────────────────────
        await self._db.upsert_record(metadata, status=FileStatus.PROCESSING)

        try:
            # ── Text extraction ───────────────────────────────────────────
            logger.debug("Worker-{}: Extracting text from {}", worker_id, metadata.file_name)
            text = extract_text(metadata.file_path)

            if not text.strip():
                raise ProcessingError(
                    f"No readable text found in {metadata.file_name}"
                )

            # ── LLM summarisation ─────────────────────────────────────────
            summary = await self._processor.summarise(metadata, text)

            # ── Persist success ───────────────────────────────────────────
            await self._db.upsert_record(
                metadata, summary=summary, status=FileStatus.COMPLETED
            )
            self._monitor.move_to_processed(metadata.file_path)
            logger.success(
                "Worker-{}: ✅ Completed: {} | Topics: {}",
                worker_id,
                metadata.file_name,
                ", ".join(summary.key_topics[:3]),
            )

        except ProcessingError as exc:
            logger.error("Worker-{}: ❌ ProcessingError for {}: {}", worker_id, metadata.file_name, exc)
            metadata.status = FileStatus.FAILED
            metadata.retry_count += 1
            await self._db.upsert_record(
                metadata, status=FileStatus.FAILED, error=str(exc)
            )
            self._monitor.move_to_failed(metadata.file_path)

        except RateLimitError as exc:
            logger.warning(
                "Worker-{}: ⏳ RateLimitError for {} — re-queuing.", worker_id, metadata.file_name
            )
            metadata.retry_count += 1
            await self._db.upsert_record(
                metadata, status=FileStatus.PENDING, error=str(exc)
            )
            # Re-queue with a delay to allow back-off
            await asyncio.sleep(30)
            await self._queue.put(metadata)

        except Exception as exc:  # noqa: BLE001
            logger.exception(
                "Worker-{}: 💥 Unexpected error for {}: {}", worker_id, metadata.file_name, exc
            )
            metadata.status = FileStatus.FAILED
            await self._db.upsert_record(
                metadata, status=FileStatus.FAILED, error=f"Unexpected: {exc}"
            )
            self._monitor.move_to_failed(metadata.file_path)
