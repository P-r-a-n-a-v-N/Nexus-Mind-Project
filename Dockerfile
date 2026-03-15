# ── Build stage ────────────────────────────────────────────────────────────────
FROM python:3.12-slim AS builder

WORKDIR /app

# Install build dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml ./
COPY src/ ./src/

RUN pip install --upgrade pip && \
    pip install --no-cache-dir -e .

# ── Runtime stage ──────────────────────────────────────────────────────────────
FROM python:3.12-slim AS runtime

LABEL maintainer="Pranav N"
LABEL version="1.0.0"
LABEL description="NexusMind — AI Second Brain Pipeline"

WORKDIR /app

# Create non-root user
RUN useradd -m -u 1000 nexusmind

# Copy installed packages from builder
COPY --from=builder /usr/local/lib/python3.12 /usr/local/lib/python3.12
COPY --from=builder /usr/local/bin /usr/local/bin
COPY --from=builder /app /app

# Create data directories
RUN mkdir -p data/inbox data/processed data/failed logs && \
    chown -R nexusmind:nexusmind /app

USER nexusmind

# Environment defaults (override with --env-file or -e flags)
ENV INBOX_DIR=data/inbox \
    PROCESSED_DIR=data/processed \
    FAILED_DIR=data/failed \
    DB_PATH=data/nexusmind.db \
    LOG_DIR=logs \
    WORKER_COUNT=3 \
    GEMINI_MODEL=gemini-1.5-flash

# Expose Streamlit port
EXPOSE 8501

VOLUME ["/app/data", "/app/logs"]

# Default: run the pipeline
CMD ["nexusmind"]
