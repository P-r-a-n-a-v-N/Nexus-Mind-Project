<div align="center">

# 🧠 NexusMind
### AI-Powered Second Brain — Automated Research Pipeline

**by Pranav N**

[![Python](https://img.shields.io/badge/Python-3.12+-blue?logo=python)](https://python.org)
[![Gemini](https://img.shields.io/badge/Google-Gemini_AI-4285F4?logo=google)](https://ai.google.dev)
[![Pydantic](https://img.shields.io/badge/Pydantic-v2-E92063)](https://docs.pydantic.dev)
[![Tests](https://img.shields.io/badge/Tests-44_passing-brightgreen)](tests/)
[![License](https://img.shields.io/badge/License-MIT-green)](LICENSE)

*Drop a file. Get a structured AI summary. Build your knowledge base.*

</div>

---

## What Is NexusMind?

NexusMind watches a folder on your computer (`data/inbox`). When you drop any `.pdf`, `.md`, or `.txt` file into it, NexusMind automatically:

1. **Reads** the file safely (with file-locking to prevent conflicts)
2. **Extracts** the text content
3. **Sends it to Google Gemini AI** to generate a structured summary
4. **Saves** the title, summary, key topics, and entities to a local database
5. **Moves** the file to `data/processed/` when done

You also get a **dark-mode web dashboard** (Streamlit) to search and browse everything NexusMind has learned.

---

## Architecture at a Glance

```
data/inbox/
    │  (you drop files here)
    ▼
[FileMonitor] ─── watchdog PollingObserver
    │              + filelock (race-condition safety)
    ▼
[asyncio.Queue] ── producer-consumer buffer (max 100 items)
    │
    ▼
[Pipeline Workers] ── asyncio.TaskGroup (3 parallel workers)
    │    ├─ Deduplication check (SHA-256 hash → SQLite)
    │    ├─ Text extraction (pypdf / plain text)
    │    ├─ Gemini API call (with exponential retry)
    │    └─ Pydantic validation of AI response
    ▼
[SQLite Database] ── WAL mode, tenacity retry on locks
    │
    ▼
data/processed/     (success)
data/failed/        (error — inspect manually)
```

---

## Project Structure

```
nexusmind/
├── src/nexusmind/
│   ├── __init__.py        # Package metadata
│   ├── config.py          # All settings via Pydantic + python-dotenv
│   ├── models.py          # Pydantic v2 data models (FileMetadata, AISummary)
│   ├── logger.py          # Loguru setup — rotating JSON logs + console
│   ├── database.py        # Async SQLite (SQLAlchemy + aiosqlite + WAL)
│   ├── monitor.py         # watchdog PollingObserver + filelock
│   ├── processor.py       # Gemini API integration + tenacity retries
│   ├── pipeline.py        # asyncio.TaskGroup worker pool
│   ├── main.py            # Entry point + signal handlers (SIGINT/SIGTERM)
│   └── ui.py              # Streamlit dashboard (dark mode)
├── tests/
│   ├── conftest.py
│   ├── test_models.py     # 13 tests
│   ├── test_config.py     # 5 tests
│   ├── test_database.py   # 7 tests
│   ├── test_monitor.py    # 6 tests
│   ├── test_processor.py  # 8 tests
│   └── test_pipeline.py   # 3 integration tests  (44 total, all passing)
├── data/
│   ├── inbox/             # Drop files here
│   ├── processed/         # Successfully processed files
│   └── failed/            # Files that errored (check logs)
├── logs/                  # Rotating JSON logs
├── .env.example           # Template — copy to .env
├── .gitignore
├── Dockerfile
├── docker-compose.yml
└── pyproject.toml
```

---

## Quick Start (5 minutes)

### Step 1 — Clone the repo

```bash
git clone https://github.com/YOUR_USERNAME/nexusmind.git
cd nexusmind
```

### Step 2 — Set up Python environment

```bash
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -e .
```

### Step 3 — Add your Gemini API key

```bash
cp .env.example .env
```

Open `.env` and set:

```
GEMINI_API_KEY=your_actual_api_key_here
```

Get a free API key at [https://aistudio.google.com/app/apikey](https://aistudio.google.com/app/apikey)

### Step 4 — Run NexusMind

**Terminal 1 — Start the pipeline:**
```bash
nexusmind
```

**Terminal 2 — Start the dashboard:**
```bash
streamlit run src/nexusmind/ui.py
```

Open [http://localhost:8501](http://localhost:8501) in your browser.

### Step 5 — Drop a file and watch it work

```bash
cp any_research_paper.pdf data/inbox/
```

Within seconds, NexusMind will process it and you'll see the summary in the dashboard.

---

## Docker Deployment

```bash
# Build and run everything
docker compose up --build

# Run in background
docker compose up -d

# View pipeline logs
docker compose logs -f nexusmind

# Stop everything
docker compose down
```

The dashboard will be at [http://localhost:8501](http://localhost:8501).

---

## Running Tests

```bash
# Install test dependencies
pip install -e ".[dev]"

# Run all 44 tests
pytest

# With detailed coverage report
pytest --cov=src/nexusmind --cov-report=html
open htmlcov/index.html

# Run only a specific test file
pytest tests/test_models.py -v

# Run only fast unit tests (skip integration)
pytest tests/test_models.py tests/test_config.py tests/test_processor.py -v
```

**Current test results: 44 passed, 0 failed**

---

## Configuration Reference

All settings go in your `.env` file. Here are the most important ones:

| Setting | Default | What it does |
|---|---|---|
| `GEMINI_API_KEY` | *required* | Your Google Gemini API key |
| `GEMINI_MODEL` | `gemini-1.5-flash` | Which Gemini model to use |
| `WORKER_COUNT` | `3` | How many files to process in parallel |
| `POLL_INTERVAL` | `2.0` | How often (seconds) to check the inbox folder |
| `MAX_FILE_SIZE_MB` | `50` | Skip files larger than this |
| `MAX_RETRIES` | `5` | Retry attempts before marking a file as failed |
| `INBOX_DIR` | `data/inbox` | Folder to watch for new files |

---

## Supported File Types

| Extension | How it's read |
|---|---|
| `.pdf` | Text extracted using `pypdf` |
| `.md` | Read as UTF-8 text |
| `.txt` | Read as UTF-8 text (falls back to latin-1) |

---

## Troubleshooting

### Problem: "database is locked"

**What's happening:** Multiple workers tried to write to SQLite at the same time.

**Fix:** NexusMind handles this automatically with tenacity retry (up to 5 attempts with exponential back-off). If you see it in logs, it's not a crash — it's self-healing. If it persists, reduce `WORKER_COUNT` to `1` in your `.env`.

---

### Problem: "Rate limit hit" / API 429 errors

**What's happening:** You've sent too many requests to the Gemini API in a short time.

**Fix:** NexusMind automatically backs off and retries. Files will re-queue themselves after a 30-second wait. If you're processing many files at once, try:
- Setting `WORKER_COUNT=1` to slow down the pipeline
- Using `gemini-1.5-flash` (higher rate limits than Pro)
- Spreading your files across multiple sessions

---

### Problem: File is stuck in "processing" status

**What's happening:** The pipeline crashed mid-file (e.g., power cut, force-quit).

**Fix:**
1. The file will still be in `data/inbox/` (or `data/failed/`)
2. Restart NexusMind — it will scan the inbox on startup and re-queue the file
3. NexusMind also checks for duplicate hashes, so reprocessing is safe

---

### Problem: "File too large" warning

**What's happening:** The file exceeds `MAX_FILE_SIZE_MB` (default: 50 MB).

**Fix:** Either increase `MAX_FILE_SIZE_MB` in `.env`, or split your large document into smaller parts before dropping it in the inbox.

---

### Problem: "Extracted text is empty" for a PDF

**What's happening:** The PDF is a scanned image (no selectable text inside).

**Fix:** Use an OCR tool like `tesseract` or Adobe Acrobat to convert it to a text-based PDF first. NexusMind processes text content, not images.

---

### Problem: "filelock.Timeout" in logs

**What's happening:** Another process (your OS, a download manager) is still writing to the file when NexusMind tries to read it.

**Fix:** Wait a moment and copy the file in — do not move an incomplete download directly into the inbox. You can increase `FILE_LOCK_TIMEOUT` in `.env` as well.

---

### Problem: Dashboard shows "Database not available"

**What's happening:** The pipeline hasn't been started yet, or the `DB_PATH` is incorrect.

**Fix:**
1. Start the pipeline first: `nexusmind`
2. Check that your `.env` has the correct `DB_PATH`
3. Make sure both terminal sessions are in the same project directory

---

## Security Notes

- **Never commit your `.env` file** — it contains your API key. It's in `.gitignore` by default.
- API keys are loaded from environment variables only (via `python-dotenv`). They are never hardcoded anywhere.
- The SQLite database stores only summaries and metadata — not the original file content.

---

## License

MIT License — see [LICENSE](LICENSE)

---

## Author

**Pranav N** — Built with ❤️ using Python 3.12, Google Gemini, Pydantic v2, and asyncio.

*"Your research, organised automatically."*
