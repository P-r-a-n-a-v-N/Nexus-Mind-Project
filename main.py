"""NexusMind Main Entry Point.

Wires all components together and handles graceful shutdown via signal handlers.
Author: Pranav N
"""

from __future__ import annotations

import asyncio
import signal
import sys
from pathlib import Path

from loguru import logger

from nexusmind.config import get_settings
from nexusmind.database import Database
from nexusmind.logger import setup_logging
from nexusmind.monitor import FileMonitor
from nexusmind.pipeline import Pipeline
from nexusmind.processor import LLMProcessor


async def _run_app() -> None:
    """Core async application lifecycle."""
    settings = get_settings()
    settings.create_directories()
    setup_logging(settings.log_dir)

    logger.info("=" * 60)
    logger.info(" NexusMind v1.0.0 — AI Second Brain")
    logger.info(" Author: Pranav N")
    logger.info(" Inbox: {}", settings.inbox_dir.resolve())
    logger.info(" Model: {}", settings.gemini_model)
    logger.info(" Workers: {}", settings.worker_count)
    logger.info("=" * 60)

    # ── Initialise components ─────────────────────────────────────────────
    db = Database(settings.db_path)
    await db.init()

    queue: asyncio.Queue = asyncio.Queue(maxsize=settings.queue_maxsize)
    loop = asyncio.get_running_loop()

    processor = LLMProcessor(
        api_key=settings.gemini_api_key,
        model_name=settings.gemini_model,
        max_retries=settings.max_retries,
    )

    monitor = FileMonitor(settings, queue, loop)
    pipeline = Pipeline(settings, queue, db, monitor, processor)

    # ── Signal handlers for graceful shutdown ─────────────────────────────
    def _handle_signal(sig: int) -> None:
        sig_name = signal.Signals(sig).name
        logger.warning("Received {} — initiating graceful shutdown...", sig_name)
        pipeline.request_shutdown()

    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, _handle_signal, sig)
        except (NotImplementedError, OSError):
            # Windows doesn't support add_signal_handler
            signal.signal(sig, lambda s, f: _handle_signal(s))

    # ── Start monitoring ──────────────────────────────────────────────────
    monitor.start()
    await monitor.scan_existing()   # Process any pre-existing files

    # ── Run pipeline (blocks until shutdown) ──────────────────────────────
    try:
        await pipeline.run()
    finally:
        monitor.stop()
        await queue.join()
        await db.close()

        stats = await db.get_stats() if not db._engine.is_disposed else {}
        logger.info("Final pipeline stats: {}", stats)
        logger.info("NexusMind shutdown complete. Goodbye! 👋")


def cli_entry() -> None:
    """CLI entry point registered via pyproject.toml scripts."""
    # Load .env before anything else
    try:
        from dotenv import load_dotenv
        load_dotenv()
    except ImportError:
        pass

    try:
        asyncio.run(_run_app())
    except KeyboardInterrupt:
        logger.info("Interrupted by user.")
        sys.exit(0)
    except Exception as exc:
        logger.exception("Fatal error: {}", exc)
        sys.exit(1)


if __name__ == "__main__":
    cli_entry()
