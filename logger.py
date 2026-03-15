"""NexusMind Logging Setup.

Configures Loguru with rotating JSON file logs + coloured console output.
Author: Pranav N
"""

import sys
from pathlib import Path

from loguru import logger


def setup_logging(log_dir: Path, level: str = "INFO") -> None:
    """Configure structured logging for the application.

    Args:
        log_dir: Directory where log files will be written.
        level: Minimum log level (DEBUG, INFO, WARNING, ERROR).
    """
    log_dir.mkdir(parents=True, exist_ok=True)

    # Remove default handler
    logger.remove()

    # ── Console handler (human-readable) ──────────────────────────────────
    logger.add(
        sys.stderr,
        level=level,
        colorize=True,
        format=(
            "<green>{time:YYYY-MM-DD HH:mm:ss}</green> | "
            "<level>{level: <8}</level> | "
            "<cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> | "
            "<level>{message}</level>"
        ),
        backtrace=True,
        diagnose=True,
    )

    # ── Rotating JSON file handler (production) ───────────────────────────
    logger.add(
        log_dir / "nexusmind_{time:YYYY-MM-DD}.log",
        level=level,
        rotation="50 MB",
        retention="30 days",
        compression="zip",
        serialize=True,   # JSON format
        backtrace=True,
        diagnose=False,   # Don't expose vars in prod logs
        enqueue=True,     # Thread-safe async logging
    )

    # ── Error-only log ────────────────────────────────────────────────────
    logger.add(
        log_dir / "errors.log",
        level="ERROR",
        rotation="10 MB",
        retention="90 days",
        compression="zip",
        serialize=True,
        backtrace=True,
        enqueue=True,
    )

    logger.info("Logging initialised. Log directory: {}", log_dir)
