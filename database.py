"""NexusMind Database Layer.

Thread-safe SQLite operations using SQLAlchemy async with WAL mode.
Includes idempotency checks (SHA-256 deduplication) and tenacity retries.
Author: Pranav N
"""

from __future__ import annotations

import json
from pathlib import Path

from loguru import logger
from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Integer,
    String,
    Text,
    event,
    text,
)
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, create_async_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker
from tenacity import (
    AsyncRetrying,
    retry_if_exception_message,
    stop_after_attempt,
    wait_exponential,
)

from nexusmind.models import AISummary, FileMetadata, FileStatus, ProcessingRecord


class Base(DeclarativeBase):
    """SQLAlchemy declarative base."""
    pass


class FileRecord(Base):
    """ORM model for the processed_files table."""

    __tablename__ = "processed_files"

    id = Column(Integer, primary_key=True, autoincrement=True)
    file_path = Column(String(1024), nullable=False)
    file_name = Column(String(512), nullable=False)
    sha256_hash = Column(String(64), unique=True, nullable=False, index=True)
    size_bytes = Column(Integer, nullable=False)
    status = Column(String(32), nullable=False, default=FileStatus.PENDING.value)
    title = Column(String(500), nullable=True)
    summary = Column(Text, nullable=True)
    key_topics = Column(Text, nullable=True)   # JSON array
    entities = Column(Text, nullable=True)      # JSON array
    word_count = Column(Integer, default=0)
    language = Column(String(10), default="en")
    model_used = Column(String(100), nullable=True)
    error_message = Column(Text, nullable=True)
    retry_count = Column(Integer, default=0)
    is_duplicate = Column(Boolean, default=False)
    discovered_at = Column(DateTime, nullable=False)
    processed_at = Column(DateTime, nullable=True)


class Database:
    """Async, thread-safe database interface.

    Features:
        - SQLite WAL mode for concurrency
        - SHA-256 based idempotency checks
        - Tenacity retry on locked-DB errors
    """

    def __init__(self, db_path: Path) -> None:
        """Initialise with path to the SQLite file.

        Args:
            db_path: Absolute path to the .db file.
        """
        self._db_path = db_path
        db_url = f"sqlite+aiosqlite:///{db_path.resolve()}"
        self._engine: AsyncEngine = create_async_engine(
            db_url,
            echo=False,
            connect_args={"check_same_thread": False, "timeout": 30},
        )
        self._session_factory = sessionmaker(
            bind=self._engine,
            class_=AsyncSession,
            expire_on_commit=False,
        )

        # Enable WAL mode on every new connection
        @event.listens_for(self._engine.sync_engine, "connect")
        def set_wal_mode(dbapi_conn, connection_record):  # noqa: ANN001
            cursor = dbapi_conn.cursor()
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.execute("PRAGMA synchronous=NORMAL")
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.close()

    async def init(self) -> None:
        """Create all tables if they don't exist."""
        async with self._engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        logger.info("Database initialised at {}", self._db_path)

    async def close(self) -> None:
        """Dispose the connection pool gracefully."""
        await self._engine.dispose()
        logger.info("Database connection pool closed.")

    async def is_duplicate(self, sha256_hash: str) -> bool:
        """Check whether a file hash already exists in the DB.

        Args:
            sha256_hash: SHA-256 hex digest of the file.

        Returns:
            True if the hash is already present.
        """
        async with self._session_factory() as session:
            result = await session.execute(
                text("SELECT 1 FROM processed_files WHERE sha256_hash = :h LIMIT 1"),
                {"h": sha256_hash},
            )
            return result.fetchone() is not None

    async def upsert_record(
        self,
        metadata: FileMetadata,
        summary: AISummary | None = None,
        status: FileStatus = FileStatus.PENDING,
        error: str | None = None,
    ) -> None:
        """Insert or update a file processing record with retry logic.

        Args:
            metadata: Validated file metadata.
            summary: Optional AI summary (None for failures/pending).
            status: Current pipeline status.
            error: Error message if the file failed.
        """
        async for attempt in AsyncRetrying(
            stop=stop_after_attempt(5),
            wait=wait_exponential(multiplier=1, min=0.5, max=10),
            retry=retry_if_exception_message(match="database is locked"),
            reraise=True,
        ):
            with attempt:
                async with self._session_factory() as session:
                    async with session.begin():
                        # Check for existing record
                        result = await session.execute(
                            text(
                                "SELECT id FROM processed_files "
                                "WHERE sha256_hash = :h LIMIT 1"
                            ),
                            {"h": metadata.sha256_hash},
                        )
                        row = result.fetchone()

                        if row:
                            # Update existing record
                            update_vals: dict = {
                                "status": status.value,
                                "error_message": error,
                                "retry_count": metadata.retry_count,
                            }
                            if summary:
                                update_vals.update(
                                    {
                                        "title": summary.title,
                                        "summary": summary.summary,
                                        "key_topics": json.dumps(summary.key_topics),
                                        "entities": json.dumps(summary.entities),
                                        "word_count": summary.word_count,
                                        "language": summary.language,
                                        "model_used": summary.model_used,
                                        "processed_at": summary.processed_at,
                                    }
                                )
                            set_clause = ", ".join(
                                f"{k} = :{k}" for k in update_vals
                            )
                            update_vals["row_id"] = row[0]
                            await session.execute(
                                text(
                                    f"UPDATE processed_files SET {set_clause} "
                                    "WHERE id = :row_id"
                                ),
                                update_vals,
                            )
                        else:
                            # Insert new record
                            record = FileRecord(
                                file_path=str(metadata.file_path),
                                file_name=metadata.file_name,
                                sha256_hash=metadata.sha256_hash,
                                size_bytes=metadata.size_bytes,
                                status=status.value,
                                title=summary.title if summary else None,
                                summary=summary.summary if summary else None,
                                key_topics=(
                                    json.dumps(summary.key_topics) if summary else None
                                ),
                                entities=(
                                    json.dumps(summary.entities) if summary else None
                                ),
                                word_count=summary.word_count if summary else 0,
                                language=summary.language if summary else "en",
                                model_used=summary.model_used if summary else None,
                                error_message=error,
                                retry_count=metadata.retry_count,
                                discovered_at=metadata.discovered_at,
                                processed_at=(
                                    summary.processed_at if summary else None
                                ),
                            )
                            session.add(record)

    async def get_all_records(self) -> list[dict]:
        """Return all processing records as a list of dicts (for the UI)."""
        async with self._session_factory() as session:
            result = await session.execute(
                text("SELECT * FROM processed_files ORDER BY discovered_at DESC")
            )
            rows = result.fetchall()
            cols = result.keys()
            return [dict(zip(cols, row)) for row in rows]

    async def get_stats(self) -> dict:
        """Return pipeline statistics."""
        async with self._session_factory() as session:
            result = await session.execute(
                text(
                    "SELECT status, COUNT(*) as cnt "
                    "FROM processed_files GROUP BY status"
                )
            )
            rows = result.fetchall()
            stats = {row[0]: row[1] for row in rows}
            total = sum(stats.values())
            stats["total"] = total
            return stats
