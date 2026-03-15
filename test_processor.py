"""Unit tests for LLM processor — extraction and response parsing.

Author: Pranav N
"""

import hashlib
import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from nexusmind.models import FileMetadata
from nexusmind.processor import (
    ProcessingError,
    _parse_llm_response,
    extract_text,
)


def _make_metadata(path: Path) -> FileMetadata:
    return FileMetadata.from_path(path)


def _fake_hash() -> str:
    return hashlib.sha256(b"test").hexdigest()


# ── extract_text ──────────────────────────────────────────────────────────────

def test_extract_text_txt(tmp_path: Path) -> None:
    f = tmp_path / "sample.txt"
    f.write_text("Hello, NexusMind! This is a test.")
    assert extract_text(f) == "Hello, NexusMind! This is a test."


def test_extract_text_md(tmp_path: Path) -> None:
    f = tmp_path / "notes.md"
    f.write_text("# Title\n\nSome **bold** content.")
    result = extract_text(f)
    assert "Title" in result and "bold" in result


def test_extract_text_unsupported(tmp_path: Path) -> None:
    f = tmp_path / "data.csv"
    f.write_text("a,b,c")
    with pytest.raises(ProcessingError, match="Unsupported"):
        extract_text(f)


def test_extract_text_latin1_fallback(tmp_path: Path) -> None:
    f = tmp_path / "latin.txt"
    f.write_bytes("café résumé".encode("latin-1"))
    assert len(extract_text(f)) > 0


# ── _parse_llm_response ───────────────────────────────────────────────────────

def test_parse_valid_json() -> None:
    raw = json.dumps({
        "title": "AI Research",
        "summary": "This paper discusses advances in artificial intelligence and machine learning.",
        "key_topics": ["AI", "ML"],
        "entities": ["OpenAI"],
        "word_count": 1500,
        "language": "en",
    })
    summary = _parse_llm_response(raw, _fake_hash(), "gemini-1.5-flash")
    assert summary.title == "AI Research"
    assert summary.word_count == 1500


def test_parse_json_with_code_fences() -> None:
    raw = """```json
{"title": "Python Guide",
 "summary": "A comprehensive guide to Python programming for beginners and experts.",
 "key_topics": ["Python"], "entities": [], "word_count": 500, "language": "en"}
```"""
    summary = _parse_llm_response(raw, _fake_hash(), "gemini-1.5-flash")
    assert summary.title == "Python Guide"


def test_parse_invalid_json_raises() -> None:
    with pytest.raises(ProcessingError, match="invalid JSON"):
        _parse_llm_response("not valid json {{", _fake_hash(), "gemini-1.5-flash")


def test_parse_missing_title_raises() -> None:
    raw = json.dumps({"summary": "Only summary present here, no title at all."})
    with pytest.raises(ProcessingError):
        _parse_llm_response(raw, _fake_hash(), "gemini-1.5-flash")


# ── LLMProcessor (mocked) ─────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_llm_processor_summarise_success(tmp_path: Path) -> None:
    f = tmp_path / "doc.txt"
    f.write_text("This is a research document about neural networks.")
    metadata = _make_metadata(f)

    mock_response = MagicMock()
    mock_response.text = json.dumps({
        "title": "Neural Networks",
        "summary": "This document discusses neural network architectures in depth.",
        "key_topics": ["Neural Networks", "AI"],
        "entities": ["Pranav N"],
        "word_count": 10,
        "language": "en",
    })

    with patch("nexusmind.processor.genai") as mock_genai:
        mock_client = MagicMock()
        mock_client.models.generate_content.return_value = mock_response
        mock_genai.Client.return_value = mock_client
        mock_genai.types = MagicMock()

        from nexusmind.processor import LLMProcessor
        proc = LLMProcessor(api_key="fake-key", model_name="gemini-1.5-flash")
        summary = await proc.summarise(metadata, "Neural networks are key AI components.")

    assert summary.title == "Neural Networks"


@pytest.mark.asyncio
async def test_llm_processor_empty_text_raises(tmp_path: Path) -> None:
    f = tmp_path / "empty.txt"
    f.write_text("   \n   ")
    metadata = _make_metadata(f)

    with patch("nexusmind.processor.genai") as mock_genai:
        mock_genai.Client.return_value = MagicMock()

        from nexusmind.processor import LLMProcessor
        proc = LLMProcessor(api_key="fake-key", model_name="gemini-1.5-flash")
        with pytest.raises(ProcessingError, match="empty"):
            await proc.summarise(metadata, "   ")
