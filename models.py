"""NexusMind Pydantic Data Models.

All data structures used across the pipeline are validated here using
Pydantic v2 in strict mode to enforce a fail-early pattern.
Author: Pranav N
"""

from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class FileStatus(str, Enum):
    """Lifecycle status of a file through the pipeline."""

    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"
    DUPLICATE = "duplicate"
    SKIPPED = "skipped"


class SupportedExtension(str, Enum):
    """File extensions the pipeline can process."""

    PDF = ".pdf"
    MD = ".md"
    TXT = ".txt"


class FileMetadata(BaseModel):
    """Validated metadata for a file discovered in the inbox.

    Uses strict mode to ensure all fields are explicitly typed.
    """

    model_config = ConfigDict(strict=True, frozen=False)

    file_path: Path
    file_name: str
    extension: str
    size_bytes: int = Field(..., ge=0)
    sha256_hash: str = Field(..., min_length=64, max_length=64)
    discovered_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    status: FileStatus = Field(default=FileStatus.PENDING)
    error_message: str | None = None
    retry_count: int = Field(default=0, ge=0)

    @field_validator("sha256_hash")
    @classmethod
    def validate_sha256(cls, v: str) -> str:
        """Ensure hash is valid hexadecimal."""
        try:
            int(v, 16)
        except ValueError as exc:
            raise ValueError(f"Invalid SHA-256 hash: {v!r}") from exc
        return v.lower()

    @field_validator("extension")
    @classmethod
    def validate_extension(cls, v: str) -> str:
        """Normalise extension to lowercase."""
        return v.lower()

    @model_validator(mode="after")
    def validate_path_matches_name(self) -> FileMetadata:
        """Ensure file_name matches the stem of file_path."""
        if self.file_path.name != self.file_name:
            raise ValueError(
                f"file_name '{self.file_name}' does not match path filename "
                f"'{self.file_path.name}'"
            )
        return self

    @classmethod
    def from_path(cls, path: Path) -> "FileMetadata":
        """Construct FileMetadata by reading the file from disk.

        Args:
            path: Absolute path to the file.

        Returns:
            Validated FileMetadata instance.

        Raises:
            FileNotFoundError: If the path does not exist.
            ValueError: If the file is not a supported type.
        """
        if not path.exists():
            raise FileNotFoundError(f"File not found: {path}")

        sha256 = hashlib.sha256(path.read_bytes()).hexdigest()

        return cls(
            file_path=path.resolve(),
            file_name=path.name,
            extension=path.suffix.lower(),
            size_bytes=int(path.stat().st_size),
            sha256_hash=sha256,
        )


class AISummary(BaseModel):
    """Structured summary produced by the LLM for a processed file.

    Validated strictly to ensure only clean data enters the database.
    """

    model_config = ConfigDict(strict=False, frozen=False)

    file_hash: str = Field(..., min_length=64, max_length=64)
    title: str = Field(..., min_length=1, max_length=500)
    summary: str = Field(..., min_length=10, max_length=10000)
    key_topics: list[str] = Field(default_factory=list, max_length=20)
    entities: list[str] = Field(default_factory=list, max_length=50)
    word_count: int = Field(default=0, ge=0)
    language: str = Field(default="en", max_length=10)
    confidence_score: Annotated[float, Field(ge=0.0, le=1.0)] = Field(default=1.0)
    model_used: str = Field(default="unknown", max_length=100)
    processed_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    raw_response: str | None = None

    @field_validator("key_topics", "entities", mode="before")
    @classmethod
    def sanitise_list(cls, v: list[str] | None) -> list[str]:
        """Strip whitespace and remove empty strings from lists."""
        if not v:
            return []
        return [item.strip() for item in v if isinstance(item, str) and item.strip()]


class ProcessingRecord(BaseModel):
    """Full audit record combining metadata + AI summary for DB storage."""

    model_config = ConfigDict(strict=False)

    id: int | None = None
    file_path: str
    file_name: str
    sha256_hash: str
    size_bytes: int
    status: FileStatus
    title: str | None = None
    summary: str | None = None
    key_topics: str | None = None  # JSON-serialised list
    entities: str | None = None     # JSON-serialised list
    word_count: int = 0
    language: str = "en"
    model_used: str = "unknown"
    error_message: str | None = None
    retry_count: int = 0
    discovered_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    processed_at: datetime | None = None
