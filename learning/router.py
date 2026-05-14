"""
Hermes Voice — Trace-Driven Model Router
Inspired by OpenJarvis TraceDrivenPolicy + HeuristicRouter.

Selects the best model for each query based on historical performance.
Starts with heuristic defaults, learns from traces over time.

Reward function (from OpenJarvis):
  score = 0.4 * (1 - latency/30s) + 0.3 * (1 - cost/$0.01) + 0.3 * success_rate

After enough traces (>= 20 per query class), switches from heuristic
to data-driven routing.
"""

import json
from pathlib import Path
from .trace_store import get_query_class_stats, classify_query

# Model tiers
FAST_CHEAP = "google/gemini-2.5-flash"      # Default: fast, cheap
SMART_MID  = "google/gemini-2.5-pro"         # Fallback: smarter, moderate cost
SMART_FULL = "anthropic/claude-sonnet-4"     # Premium: best quality, expensive

# Heuristic defaults — used until we have enough trace data
HEURISTIC_ROUTES = {
    "email":      FAST_CHEAP,   # Email is structured, Flash handles it
    "calendar":   FAST_CHEAP,   # Calendar queries are simple tool calls
    "reminders":  FAST_CHEAP,   # Simple routing
    "web_search": FAST_CHEAP,   # Just needs to pick the right query
    "noteplan":   FAST_CHEAP,   # File operations
    "dashboard":  FAST_CHEAP,   # Open command
    "terminal":   FAST_CHEAP,   # Simple routing
    "chat":       FAST_CHEAP,   # Conversational — Flash is fine for most
}

MIN_TRACES_FOR_LEARNING = 20  # Per query class

def compute_reward(latency_ms: float, cost_usd: float, success_rate: float) -> float:
    """Compute reward score (0-1) balancing latency, cost, and quality.
    Directly from OpenJarvis HeuristicRewardFunction."""
    latency_score = max(0, 1 - (latency_ms / 30000))  # 30s max
    cost_score = max(0, 1 - (cost_usd / 0.01))         # $0.01 max per interaction
    return 0.4 * latency_score + 0.3 * cost_score + 0.3 * success_rate

def get_best_model(query: str, default_model: str = FAST_CHEAP) -> str:
    """Select the best model for a query based on trace data.
    Falls back to heuristic if not enough data."""
    query_class = classify_query(query)

    # Get trace stats per query_class + model
    stats = get_query_class_stats()

    # Filter to this query class
    class_stats = [s for s in stats if s["query_class"] == query_class]

    # Not enough data — use heuristic
    total_traces = sum(s["count"] for s in class_stats)
    if total_traces < MIN_TRACES_FOR_LEARNING:
        return HEURISTIC_ROUTES.get(query_class, default_model)

    # Score each model
    best_model = default_model
    best_score = -1

    for s in class_stats:
        if s["count"] < 3:  # Need at least 3 traces per model
            continue
        avg_cost = s["total_cost"] / s["count"]
        score = compute_reward(s["avg_latency"], avg_cost, s["success_rate"])
        if score > best_score:
            best_score = score
            best_model = s["model"]

    return best_model

def get_routing_report() -> dict:
    """Get a report of current routing decisions and their basis."""
    stats = get_query_class_stats()

    report = {}
    for qc in set(s["query_class"] for s in stats):
        class_stats = [s for s in stats if s["query_class"] == qc]
        total = sum(s["count"] for s in class_stats)
        learned = total >= MIN_TRACES_FOR_LEARNING

        models = {}
        for s in class_stats:
            avg_cost = s["total_cost"] / max(s["count"], 1)
            models[s["model"]] = {
                "count": s["count"],
                "avg_latency_ms": round(s["avg_latency"], 1),
                "success_rate": round(s["success_rate"], 3),
                "avg_cost": round(avg_cost, 6),
                "reward": round(compute_reward(s["avg_latency"], avg_cost, s["success_rate"]), 3),
            }

        report[qc] = {
            "total_traces": total,
            "routing_mode": "learned" if learned else "heuristic",
            "current_model": get_best_model(qc + " query"),  # Trigger classification
            "models": models,
        }

    return report
