#!/usr/bin/env python3
"""Helper script: drop sample files into the inbox for quick testing.

Usage:
    python scripts/drop_test_files.py

Author: Pranav N
"""

from pathlib import Path

INBOX = Path("data/inbox")
INBOX.mkdir(parents=True, exist_ok=True)

samples = {
    "research_note.md": """\
# The Future of AI Research Pipelines

## Introduction

Automated research pipelines represent a significant leap forward in how knowledge
workers interact with large volumes of information. By combining file-system monitoring
with large language model APIs, we can create systems that continuously index, summarise,
and cross-reference documents without any manual intervention.

## Key Technologies

- **watchdog** for cross-platform file monitoring
- **Google Gemini** for state-of-the-art text summarisation
- **Pydantic v2** for strict data validation
- **asyncio** for non-blocking concurrent processing
- **SQLite WAL** for reliable local persistence

## Conclusion

NexusMind demonstrates that production-grade AI pipelines can be built with
a small, focused Python codebase that is both testable and maintainable.
""",
    "python_tips.txt": """\
Python 3.12 Performance Tips for Production Systems

1. Use asyncio.TaskGroup for structured concurrency.
   Available from Python 3.11+, provides better error propagation and cleaner
   cancellation semantics compared to asyncio.gather().

2. Pydantic v2 strict mode catches bugs at the boundary, not deep in business logic.
   Always validate external data (API responses, file metadata) immediately on entry.

3. SQLite WAL (Write-Ahead Logging) allows concurrent readers without blocking
   writers. Enable it with PRAGMA journal_mode=WAL for any production SQLite usage.

4. Use filelock for cross-process file safety. The OS does not guarantee atomic
   file writes across all platforms.

5. tenacity is the gold standard for retry logic. Use wait_exponential with jitter
   to avoid thundering-herd problems when backing off from API rate limits.

6. loguru beats the standard logging library for production:
   structured JSON output, automatic rotation, and async-safe enqueue mode.

7. Always store file paths as absolute paths. Relative paths break when the
   working directory changes between sessions or inside Docker containers.
""",
}

for filename, content in samples.items():
    path = INBOX / filename
    path.write_text(content, encoding="utf-8")
    print(f"✅ Created: {path}")

print(f"\n📥 {len(samples)} test files dropped into {INBOX.resolve()}")
print("Start NexusMind to process them: nexusmind")
