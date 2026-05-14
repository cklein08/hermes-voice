"""
Hermes Voice — ICL (In-Context Learning) Miner
Inspired by OpenJarvis ICLUpdaterPolicy.

Extracts the best successful traces and formats them as few-shot
examples for the classifier prompt. The classifier prompt literally
gets better over time as we accumulate high-quality traces.

Flow:
  1. Query trace store for high-feedback, successful traces
  2. Group by query_class
  3. Pick top N per class (diverse, highest reward)
  4. Format as few-shot examples for the classifier prompt
  5. Cache to disk so they persist across restarts
"""

import json
from pathlib import Path
from .trace_store import get_best_traces, get_query_class_stats, classify_query

CACHE_PATH = Path.home() / ".hermes" / "hermes-voice" / "learning" / "icl_cache.json"
MAX_EXAMPLES_PER_CLASS = 2
MAX_TOTAL_EXAMPLES = 8  # Keep prompt lean

def mine_examples() -> list:
    """Mine the best traces for use as ICL examples.
    Returns list of {query, tool, output} dicts."""

    # Get all query classes with enough data
    stats = get_query_class_stats()
    classes = set(s["query_class"] for s in stats)

    examples = []
    for qc in classes:
        traces = get_best_traces(query_class=qc, min_feedback=0.7,
                                 limit=MAX_EXAMPLES_PER_CLASS)
        for t in traces:
            if t.get("classifier_output"):
                examples.append({
                    "query_class": qc,
                    "query": t["query"],
                    "classifier_output": t["classifier_output"],
                })

    # Cap total
    examples = examples[:MAX_TOTAL_EXAMPLES]

    # Cache to disk
    CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(CACHE_PATH, "w") as f:
        json.dump(examples, f, indent=2)

    return examples

def load_cached_examples() -> list:
    """Load cached ICL examples from disk."""
    if CACHE_PATH.exists():
        try:
            with open(CACHE_PATH) as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError):
            pass
    return []

def format_icl_prompt_section() -> str:
    """Format ICL examples as a prompt section for the classifier.
    Returns empty string if no examples available."""
    examples = load_cached_examples()
    if not examples:
        return ""

    lines = ["\n[LEARNED EXAMPLES — from your best past interactions]"]
    for ex in examples:
        lines.append(f"User: {ex['query']}")
        lines.append(f"Response: {ex['classifier_output']}")
        lines.append("")

    return "\n".join(lines)

def refresh_if_needed(min_traces: int = 20) -> bool:
    """Refresh ICL examples if we have enough new traces.
    Call periodically (e.g., every 50 interactions)."""
    stats = get_query_class_stats()
    total = sum(s["count"] for s in stats)
    if total >= min_traces:
        mine_examples()
        return True
    return False
