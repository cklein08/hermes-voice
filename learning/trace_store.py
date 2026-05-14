"""
Hermes Voice — Trace Store
Logs every LLM interaction to SQLite for learning and cost tracking.
Inspired by OpenJarvis TraceStore (src/openjarvis/telemetry/store.py).

Schema tracks: query, tool routed to, model used, tokens, latency, cost,
success/failure, and user feedback. This feeds into:
  - Cost dashboard (daily/weekly spend)
  - Trace-driven routing (which model works best for which query type)
  - ICL mining (best traces become few-shot examples)
"""

import sqlite3
import time
import json
import os
from pathlib import Path
from datetime import datetime, timedelta

DB_PATH = Path(os.environ.get("HERMES_TRACE_DB",
               Path.home() / ".hermes" / "hermes-voice" / "traces.db"))

# Cost per million tokens (input/output) — OpenRouter pricing May 2026
MODEL_COSTS = {
    "google/gemini-2.5-flash":    {"input": 0.15,  "output": 0.60},
    "google/gemini-2.5-pro":      {"input": 1.25,  "output": 10.00},
    "anthropic/claude-sonnet-4":  {"input": 3.00,  "output": 15.00},
    "anthropic/claude-haiku-3.5": {"input": 0.80,  "output": 4.00},
}

def _get_conn():
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    """Create the traces table if it doesn't exist."""
    conn = _get_conn()
    conn.execute("""
        CREATE TABLE IF NOT EXISTS traces (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT NOT NULL,
            query TEXT NOT NULL,
            query_class TEXT DEFAULT '',
            tool TEXT DEFAULT '',
            model TEXT NOT NULL,
            input_tokens INTEGER DEFAULT 0,
            output_tokens INTEGER DEFAULT 0,
            total_tokens INTEGER DEFAULT 0,
            latency_ms INTEGER DEFAULT 0,
            cost_usd REAL DEFAULT 0.0,
            success INTEGER DEFAULT 1,
            error TEXT DEFAULT '',
            classifier_output TEXT DEFAULT '',
            response_preview TEXT DEFAULT '',
            feedback REAL DEFAULT -1.0
        )
    """)
    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_traces_timestamp ON traces(timestamp)
    """)
    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_traces_query_class ON traces(query_class)
    """)
    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_traces_model ON traces(model)
    """)
    conn.commit()
    conn.close()

def estimate_cost(model: str, input_tokens: int, output_tokens: int) -> float:
    """Estimate cost in USD for a given model and token count."""
    costs = MODEL_COSTS.get(model, MODEL_COSTS["google/gemini-2.5-flash"])
    return (input_tokens * costs["input"] + output_tokens * costs["output"]) / 1_000_000

def classify_query(query: str) -> str:
    """Simple heuristic query classifier for routing decisions.
    Returns a category like 'email', 'calendar', 'chat', etc."""
    q = query.lower()
    if any(w in q for w in ["email", "mail", "inbox", "send to", "compose"]):
        return "email"
    if any(w in q for w in ["calendar", "schedule", "meeting", "event", "what's on"]):
        return "calendar"
    if any(w in q for w in ["remind", "reminder", "task", "todo"]):
        return "reminders"
    if any(w in q for w in ["search", "look up", "find", "google", "what is"]):
        return "web_search"
    if any(w in q for w in ["note", "noteplan", "write", "save", "dossier"]):
        return "noteplan"
    if any(w in q for w in ["dashboard", "briefing", "brief"]):
        return "dashboard"
    if any(w in q for w in ["terminal", "run", "command", "disk", "system"]):
        return "terminal"
    return "chat"

def record_trace(
    query: str,
    tool: str,
    model: str,
    input_tokens: int = 0,
    output_tokens: int = 0,
    latency_ms: int = 0,
    success: bool = True,
    error: str = "",
    classifier_output: str = "",
    response_preview: str = "",
):
    """Record a single interaction trace."""
    cost = estimate_cost(model, input_tokens, output_tokens)
    query_class = classify_query(query)
    conn = _get_conn()
    conn.execute("""
        INSERT INTO traces (timestamp, query, query_class, tool, model,
                           input_tokens, output_tokens, total_tokens,
                           latency_ms, cost_usd, success, error,
                           classifier_output, response_preview)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        datetime.now().isoformat(),
        query[:500],  # Cap query length
        query_class,
        tool,
        model,
        input_tokens,
        output_tokens,
        input_tokens + output_tokens,
        latency_ms,
        cost,
        1 if success else 0,
        error[:500],
        classifier_output[:1000],
        response_preview[:500],
    ))
    conn.commit()
    conn.close()
    return cost

def get_cost_summary(days: int = 7) -> dict:
    """Get cost summary for the last N days."""
    conn = _get_conn()
    cutoff = (datetime.now() - timedelta(days=days)).isoformat()
    row = conn.execute("""
        SELECT COUNT(*) as count,
               SUM(cost_usd) as total_cost,
               SUM(input_tokens) as total_input,
               SUM(output_tokens) as total_output,
               SUM(total_tokens) as total_tokens,
               AVG(latency_ms) as avg_latency,
               SUM(CASE WHEN success = 1 THEN 1 ELSE 0 END) as successes
        FROM traces WHERE timestamp >= ?
    """, (cutoff,)).fetchone()
    conn.close()
    count = row["count"] or 0
    return {
        "period_days": days,
        "interactions": count,
        "total_cost_usd": round(row["total_cost"] or 0, 6),
        "total_tokens": row["total_tokens"] or 0,
        "avg_latency_ms": round(row["avg_latency"] or 0, 1),
        "success_rate": round((row["successes"] or 0) / max(count, 1) * 100, 1),
        "cost_per_interaction": round((row["total_cost"] or 0) / max(count, 1), 6),
    }

def get_daily_costs(days: int = 7) -> list:
    """Get cost breakdown by day."""
    conn = _get_conn()
    cutoff = (datetime.now() - timedelta(days=days)).isoformat()
    rows = conn.execute("""
        SELECT DATE(timestamp) as day,
               COUNT(*) as count,
               SUM(cost_usd) as cost,
               SUM(total_tokens) as tokens
        FROM traces WHERE timestamp >= ?
        GROUP BY DATE(timestamp)
        ORDER BY day DESC
    """, (cutoff,)).fetchall()
    conn.close()
    return [dict(r) for r in rows]

def get_model_stats() -> list:
    """Get per-model performance stats."""
    conn = _get_conn()
    rows = conn.execute("""
        SELECT model,
               COUNT(*) as count,
               SUM(cost_usd) as total_cost,
               AVG(latency_ms) as avg_latency,
               AVG(CASE WHEN success = 1 THEN 1.0 ELSE 0.0 END) as success_rate
        FROM traces
        GROUP BY model
        ORDER BY count DESC
    """).fetchall()
    conn.close()
    return [dict(r) for r in rows]

def get_query_class_stats() -> list:
    """Get per-query-class stats for routing optimization."""
    conn = _get_conn()
    rows = conn.execute("""
        SELECT query_class, model,
               COUNT(*) as count,
               AVG(latency_ms) as avg_latency,
               SUM(cost_usd) as total_cost,
               AVG(CASE WHEN success = 1 THEN 1.0 ELSE 0.0 END) as success_rate
        FROM traces
        GROUP BY query_class, model
        ORDER BY query_class, count DESC
    """).fetchall()
    conn.close()
    return [dict(r) for r in rows]

def get_best_traces(query_class: str = None, min_feedback: float = 0.7, limit: int = 5) -> list:
    """Get highest-quality traces for ICL mining.
    Returns traces with positive feedback for use as few-shot examples."""
    conn = _get_conn()
    if query_class:
        rows = conn.execute("""
            SELECT query, tool, classifier_output, response_preview
            FROM traces
            WHERE query_class = ? AND feedback >= ? AND success = 1
            ORDER BY feedback DESC, latency_ms ASC
            LIMIT ?
        """, (query_class, min_feedback, limit)).fetchall()
    else:
        rows = conn.execute("""
            SELECT query, query_class, tool, classifier_output, response_preview
            FROM traces
            WHERE feedback >= ? AND success = 1
            ORDER BY feedback DESC, latency_ms ASC
            LIMIT ?
        """, (min_feedback, limit)).fetchall()
    conn.close()
    return [dict(r) for r in rows]

def record_feedback(trace_id: int, feedback: float):
    """Record user feedback (0.0 to 1.0) for a trace.
    Called when user explicitly corrects or praises a response."""
    conn = _get_conn()
    conn.execute("UPDATE traces SET feedback = ? WHERE id = ?", (feedback, trace_id))
    conn.commit()
    conn.close()

# Initialize on import
init_db()
