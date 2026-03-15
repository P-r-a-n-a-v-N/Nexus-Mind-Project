"""NexusMind Streamlit Dashboard.

Dark-mode optimised UI for monitoring pipeline status and browsing summaries.
Author: Pranav N

Run with: streamlit run src/nexusmind/ui.py
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import streamlit as st

# ── Page config (must be first Streamlit call) ─────────────────────────────────
st.set_page_config(
    page_title="NexusMind — AI Second Brain",
    page_icon="🧠",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ── Dark-mode CSS ──────────────────────────────────────────────────────────────
st.markdown(
    """
    <style>
    :root {
        --background: #0d1117;
        --surface: #161b22;
        --border: #30363d;
        --text: #e6edf3;
        --muted: #8b949e;
        --accent: #58a6ff;
        --success: #3fb950;
        --warning: #d29922;
        --error: #f85149;
    }
    .stApp { background-color: var(--background); color: var(--text); }
    .metric-card {
        background: var(--surface);
        border: 1px solid var(--border);
        border-radius: 8px;
        padding: 16px;
        text-align: center;
    }
    .metric-value { font-size: 2rem; font-weight: bold; color: var(--accent); }
    .metric-label { font-size: 0.85rem; color: var(--muted); }
    .status-completed { color: var(--success); }
    .status-failed { color: var(--error); }
    .status-pending { color: var(--warning); }
    .summary-card {
        background: var(--surface);
        border: 1px solid var(--border);
        border-radius: 8px;
        padding: 20px;
        margin-bottom: 12px;
    }
    </style>
    """,
    unsafe_allow_html=True,
)


def _get_db():
    """Lazy-load DB connection (cached per session)."""
    try:
        from dotenv import load_dotenv
        load_dotenv()
    except ImportError:
        pass

    from nexusmind.config import get_settings
    from nexusmind.database import Database

    settings = get_settings()
    return Database(settings.db_path), settings


def _run_async(coro):
    """Run an async coroutine from sync Streamlit context."""
    try:
        loop = asyncio.get_event_loop()
        if loop.is_closed():
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
        return loop.run_until_complete(coro)
    except RuntimeError:
        return asyncio.run(coro)


# ── Sidebar ────────────────────────────────────────────────────────────────────
with st.sidebar:
    st.markdown("# 🧠 NexusMind")
    st.markdown("**AI Second Brain**")
    st.markdown("*by Pranav N*")
    st.divider()

    page = st.radio(
        "Navigate",
        ["📊 Dashboard", "📄 Knowledge Base", "⚙️ Settings", "📤 Upload"],
        label_visibility="collapsed",
    )

    st.divider()
    if st.button("🔄 Refresh Data", use_container_width=True):
        st.rerun()

# ── Main content ───────────────────────────────────────────────────────────────
try:
    db, settings = _get_db()
    records = _run_async(db.get_all_records())
    stats = _run_async(db.get_stats())
    db_available = True
except Exception as e:
    records, stats, db_available = [], {}, False
    st.warning(f"⚠️ Database not available: {e}. Start NexusMind first.")


# ══════════════════════════════════════════════════════════════════════════════
# PAGE: Dashboard
# ══════════════════════════════════════════════════════════════════════════════
if page == "📊 Dashboard":
    st.title("📊 Pipeline Dashboard")

    # Metric cards
    cols = st.columns(5)
    metric_data = [
        ("Total Files", stats.get("total", 0), "accent"),
        ("✅ Completed", stats.get("completed", 0), "success"),
        ("⏳ Pending", stats.get("pending", 0) + stats.get("processing", 0), "warning"),
        ("❌ Failed", stats.get("failed", 0), "error"),
        ("♻️ Duplicates", stats.get("duplicate", 0), "muted"),
    ]
    for col, (label, value, color) in zip(cols, metric_data):
        with col:
            st.metric(label=label, value=value)

    st.divider()

    # Recent activity table
    st.subheader("Recent Activity")
    if records:
        import pandas as pd

        df = pd.DataFrame(records)[
            ["file_name", "status", "title", "word_count", "language", "processed_at"]
        ].head(20)
        df.columns = ["File", "Status", "Title", "Words", "Lang", "Processed At"]
        st.dataframe(df, use_container_width=True, hide_index=True)
    else:
        st.info("No files processed yet. Drop a .pdf, .md, or .txt file into your inbox folder.")

    # Status distribution chart
    if stats.get("total", 0) > 0:
        st.subheader("Status Distribution")
        import plotly.graph_objects as go

        labels = [k for k in stats if k != "total"]
        values = [stats[k] for k in labels]
        colors = {
            "completed": "#3fb950", "failed": "#f85149",
            "pending": "#d29922", "processing": "#58a6ff",
            "duplicate": "#8b949e", "skipped": "#6e7681",
        }
        fig = go.Figure(data=[go.Pie(
            labels=labels,
            values=values,
            marker_colors=[colors.get(l, "#58a6ff") for l in labels],
            hole=0.4,
        )])
        fig.update_layout(
            paper_bgcolor="rgba(0,0,0,0)",
            plot_bgcolor="rgba(0,0,0,0)",
            font=dict(color="#e6edf3"),
            margin=dict(t=20, b=20),
            height=300,
        )
        st.plotly_chart(fig, use_container_width=True)


# ══════════════════════════════════════════════════════════════════════════════
# PAGE: Knowledge Base
# ══════════════════════════════════════════════════════════════════════════════
elif page == "📄 Knowledge Base":
    st.title("📄 Knowledge Base")

    completed = [r for r in records if r.get("status") == "completed"]

    if not completed:
        st.info("No completed summaries yet.")
    else:
        # Search
        search = st.text_input("🔍 Search by title, topic, or keyword...", "")

        filtered = completed
        if search:
            q = search.lower()
            filtered = [
                r for r in completed
                if q in (r.get("title") or "").lower()
                or q in (r.get("summary") or "").lower()
                or q in (r.get("key_topics") or "").lower()
            ]

        st.caption(f"Showing {len(filtered)} of {len(completed)} documents")

        for r in filtered:
            with st.expander(f"📄 {r.get('title') or r.get('file_name', 'Untitled')}"):
                col1, col2 = st.columns([3, 1])
                with col1:
                    st.markdown(f"**Summary**")
                    st.write(r.get("summary", "No summary available."))
                with col2:
                    topics_raw = r.get("key_topics")
                    if topics_raw:
                        try:
                            topics = json.loads(topics_raw)
                            st.markdown("**Key Topics**")
                            for t in topics[:8]:
                                st.markdown(f"- {t}")
                        except Exception:
                            pass

                    entities_raw = r.get("entities")
                    if entities_raw:
                        try:
                            entities = json.loads(entities_raw)
                            st.markdown("**Entities**")
                            for e in entities[:6]:
                                st.markdown(f"- {e}")
                        except Exception:
                            pass

                st.caption(
                    f"File: `{r.get('file_name')}` | "
                    f"Words: {r.get('word_count', 0)} | "
                    f"Lang: {r.get('language', 'en')} | "
                    f"Model: {r.get('model_used', 'N/A')}"
                )


# ══════════════════════════════════════════════════════════════════════════════
# PAGE: Upload
# ══════════════════════════════════════════════════════════════════════════════
elif page == "📤 Upload":
    st.title("📤 Upload Files")
    st.info("Files uploaded here are placed directly into the inbox for processing.")

    uploaded = st.file_uploader(
        "Choose files (.pdf, .md, .txt)",
        type=["pdf", "md", "txt"],
        accept_multiple_files=True,
    )

    if uploaded and db_available:
        for f in uploaded:
            dest = settings.inbox_dir / f.name
            dest.write_bytes(f.read())
            st.success(f"✅ Queued: **{f.name}** ({f.size:,} bytes)")
        st.info("Files added to inbox. NexusMind will process them shortly.")
    elif uploaded:
        st.error("Start the NexusMind pipeline first.")


# ══════════════════════════════════════════════════════════════════════════════
# PAGE: Settings
# ══════════════════════════════════════════════════════════════════════════════
elif page == "⚙️ Settings":
    st.title("⚙️ Configuration")

    if db_available:
        col1, col2 = st.columns(2)
        with col1:
            st.subheader("Paths")
            st.code(f"Inbox:     {settings.inbox_dir.resolve()}")
            st.code(f"Processed: {settings.processed_dir.resolve()}")
            st.code(f"Failed:    {settings.failed_dir.resolve()}")
            st.code(f"Database:  {settings.db_path.resolve()}")
        with col2:
            st.subheader("Pipeline")
            st.metric("Gemini Model", settings.gemini_model)
            st.metric("Workers", settings.worker_count)
            st.metric("Queue Max", settings.queue_maxsize)
            st.metric("Max File Size", f"{settings.max_file_size_mb} MB")
    else:
        st.warning("Set `GEMINI_API_KEY` in your `.env` file to view settings.")
        st.code("""# .env
GEMINI_API_KEY=your_api_key_here
GEMINI_MODEL=gemini-1.5-flash
WORKER_COUNT=3
MAX_FILE_SIZE_MB=50
""")
