"""NexusMind LLM Processing Engine.

Handles file reading, text extraction, and Gemini API interaction.
Uses the modern google-genai SDK (google.genai).
Implements retry decorators, rate-limit back-off, and fail-early validation.
Author: Pranav N
"""

from __future__ import annotations

import asyncio
import json
import re
from pathlib import Path

from google import genai
from google.genai import types as genai_types
from loguru import logger
from pydantic import ValidationError
from tenacity import (
    AsyncRetrying,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from nexusmind.models import AISummary, FileMetadata

_SYSTEM_PROMPT = """You are an expert research analyst. Analyse the provided document and return
a JSON object with EXACTLY these fields (no extra text, no markdown fences):
{
  "title": "concise document title (max 100 chars)",
  "summary": "comprehensive 3-5 paragraph summary",
  "key_topics": ["topic1", "topic2"],
  "entities": ["person/org/concept1"],
  "word_count": <integer>,
  "language": "ISO 639-1 code e.g. en"
}
Return ONLY valid JSON — no preamble, no code fences."""


class RateLimitError(Exception):
    """Raised when the Gemini API returns a quota/rate-limit error."""


class ProcessingError(Exception):
    """Raised for non-retryable processing failures."""


def _extract_text_from_txt(path: Path) -> str:
    """Read plain text from a .txt or .md file."""
    try:
        return path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return path.read_text(encoding="latin-1", errors="replace")


def _extract_text_from_pdf(path: Path) -> str:
    """Extract text from a PDF using pypdf."""
    try:
        from pypdf import PdfReader
        reader = PdfReader(str(path))
        pages = [page.extract_text() or "" for page in reader.pages]
        return "\n\n".join(p for p in pages if p.strip())
    except Exception as exc:
        logger.warning("PDF extraction error for {}: {}", path.name, exc)
        return ""


def extract_text(path: Path) -> str:
    """Extract raw text from a supported file type.

    Args:
        path: Absolute path to the file.

    Returns:
        Extracted text content.

    Raises:
        ProcessingError: If the file extension is not supported.
    """
    ext = path.suffix.lower()
    if ext == ".pdf":
        return _extract_text_from_pdf(path)
    elif ext in {".md", ".txt"}:
        return _extract_text_from_txt(path)
    else:
        raise ProcessingError(f"Unsupported file extension: {ext!r}")


def _parse_llm_response(raw: str, file_hash: str, model_name: str) -> AISummary:
    """Parse and validate the JSON response from the LLM.

    Args:
        raw: Raw string returned by the model.
        file_hash: SHA-256 hash of the source file.
        model_name: Gemini model name used.

    Returns:
        Validated AISummary.

    Raises:
        ProcessingError: On JSON parse errors or Pydantic validation failure.
    """
    # Strip any accidental markdown code fences
    clean = re.sub(r"```(?:json)?\s*|\s*```", "", raw).strip()
    try:
        data = json.loads(clean)
    except json.JSONDecodeError as exc:
        raise ProcessingError(f"LLM returned invalid JSON: {exc}") from exc

    try:
        return AISummary(
            file_hash=file_hash,
            model_used=model_name,
            raw_response=raw[:2000],
            **{
                k: data[k]
                for k in ("title", "summary", "key_topics", "entities", "word_count", "language")
                if k in data
            },
        )
    except (ValidationError, TypeError) as exc:
        raise ProcessingError(f"LLM response failed Pydantic validation: {exc}") from exc


class LLMProcessor:
    """Manages Gemini API calls with retry and exponential back-off.

    Attributes:
        model_name: Gemini model identifier string.
        max_retries: Maximum retry attempts for rate-limited requests.
    """

    def __init__(self, api_key: str, model_name: str, max_retries: int = 5) -> None:
        """Initialise the processor.

        Args:
            api_key: Google Gemini API key.
            model_name: Gemini model name (e.g. "gemini-1.5-flash").
            max_retries: Max retries on rate-limit errors.
        """
        self._client = genai.Client(api_key=api_key)
        self.model_name = model_name
        self.max_retries = max_retries
        logger.info("LLMProcessor ready. Model: {}", model_name)

    async def summarise(self, metadata: FileMetadata, text: str) -> AISummary:
        """Generate a structured summary using the Gemini API.

        Retries with exponential back-off on rate-limit errors.
        Validates the response before returning.

        Args:
            metadata: Validated file metadata.
            text: Extracted text content from the file.

        Returns:
            Validated AISummary instance.

        Raises:
            ProcessingError: On non-retryable failures.
            RateLimitError: If all retries are exhausted due to quota limits.
        """
        if not text.strip():
            raise ProcessingError("Extracted text is empty — nothing to summarise.")

        truncated = text[:500_000]
        prompt = (
            f"{_SYSTEM_PROMPT}\n\n"
            f"File: {metadata.file_name}\n"
            f"Size: {metadata.size_bytes} bytes\n\n"
            f"--- DOCUMENT ---\n{truncated}\n--- END ---"
        )

        async for attempt in AsyncRetrying(
            stop=stop_after_attempt(self.max_retries),
            wait=wait_exponential(multiplier=2, min=2, max=120),
            retry=retry_if_exception_type(RateLimitError),
            reraise=True,
        ):
            with attempt:
                try:
                    logger.debug(
                        "Sending {} ({} chars) to {} [attempt {}]",
                        metadata.file_name,
                        len(truncated),
                        self.model_name,
                        attempt.retry_state.attempt_number,
                    )
                    response = await asyncio.get_event_loop().run_in_executor(
                        None,
                        lambda: self._client.models.generate_content(
                            model=self.model_name,
                            contents=prompt,
                            config=genai_types.GenerateContentConfig(
                                temperature=0.2,
                                max_output_tokens=4096,
                            ),
                        ),
                    )

                    raw_text = response.text
                    if not raw_text:
                        raise ProcessingError("Gemini returned an empty response.")

                    summary = _parse_llm_response(raw_text, metadata.sha256_hash, self.model_name)
                    logger.info("✓ Summarised: {}", metadata.file_name)
                    return summary

                except ProcessingError:
                    raise
                except Exception as exc:
                    err_str = str(exc).lower()
                    if any(k in err_str for k in ("quota", "rate", "429", "resource_exhausted")):
                        logger.warning(
                            "Rate limit hit for {} (attempt {}). Backing off...",
                            metadata.file_name,
                            attempt.retry_state.attempt_number,
                        )
                        raise RateLimitError(str(exc)) from exc
                    logger.error("Unexpected API error for {}: {}", metadata.file_name, exc)
                    raise ProcessingError(str(exc)) from exc

        raise RateLimitError("All retries exhausted due to rate limiting.")
