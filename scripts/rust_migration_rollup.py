"""Overview roll-ups for docs/migration/rust/overview.yml: overall percent and performance summary.

Used by scripts/rust_migration_yaml.py. Pure functions over already-built area summaries and the
append-only performance-history.yml; no git, no clock, so `--check` is deterministic in a
shallow CI clone.

  overall      weighted average of area percents (weights and decision date below)
  performance  latest entry per (flow, metric) with age relative to the newest web Rust slice
  perf_attention  latest entries whose verdict is rust_worse, plus known unrecorded problems

Architecture: docs/architecture/platforms/rust-migration-status.md
"""

from __future__ import annotations

from collections import Counter
from datetime import date

WEIGHTS = {"web_app": 0.4, "shared_client": 0.2, "cli": 0.25, "sdk": 0.15}
SDK_AREAS = ("sdk_rust", "sdk_npm", "sdk_python")
WEIGHTS_DECIDED = "2026-11-08"
OVERALL_FORMULA = ("overall = round(0.4 * web_app + 0.2 * shared_client + 0.25 * cli + 0.15 * sdk, 1), "
                   "sdk = mean(sdk_rust, sdk_npm, sdk_python); each term is the area percent")
STALE_AFTER_HOURS = 24
STALE_RULE = ("age_hours = (reference_date - entry date) * 24, reference_date = as_of date of "
              "capabilities.yml (last capability status audit); stale when age_hours > 24. Day "
              "granularity: history entries carry dates, not times.")
VERDICT_ORDER = ("rust_not_worse", "inconclusive", "rust_worse", "invalid_measurement", "unverified")
# Problems known from lane reports that have no history entry yet. Remove a line once its
# measurement is recorded with scripts/record_perf_measurement.py.
UNRECORDED = (
    {"flow": "search", "metric": "snippet text", "verdict": "not_recorded",
     "note": "Rust search snippets differ from the TS snippets in the search bench (functional mismatch); not yet recorded in performance-history.yml."},
)
# rust_worse items someone is working on; others show status "open".
INVESTIGATING = {("send", "draftSaveP95Ms"): "under investigation (draft-save Rust path lane, 2026-11-08)"}


def overall(percents: dict[str, float]) -> dict:
    """Weighted overall percent from per-area percents (keys of ORDER in rust_migration_yaml)."""
    sdk = round(sum(percents[a] for a in SDK_AREAS) / len(SDK_AREAS), 1)
    terms = {"web_app": percents["web_app"], "shared_client": percents["shared_client"], "cli": percents["cli"], "sdk": sdk}
    value = round(sum(WEIGHTS[k] * v for k, v in terms.items()), 1)
    return {"percent": value, "formula": OVERALL_FORMULA, "weights": dict(WEIGHTS), "weights_decided": WEIGHTS_DECIDED,
            "inputs": terms}


def validate_overall(block: dict, percents: dict[str, float]) -> list[str]:
    errors = []
    if block.get("weights") != WEIGHTS or abs(sum(WEIGHTS.values()) - 1.0) > 1e-9:
        errors.append("overview overall: weights must be web_app 0.4, shared_client 0.2, cli 0.25, sdk 0.15 (sum 1)")
    if block != overall(percents):
        errors.append(f"overview overall: percent {block.get('percent')} differs from the formula over the area percents")
    return errors


def _copy(value: list | None) -> list | None:
    """Fresh list so the YAML dump writes values, not &anchors/*aliases, for repeated intervals."""
    return list(value) if value is not None else None


def _age_hours(entry_date: str, reference: str) -> int:
    return (date.fromisoformat(reference) - date.fromisoformat(entry_date)).days * 24


def latest_by_metric(history: dict) -> dict[tuple[str, str], dict]:
    """Last entry per (flow, metric) in history order, whatever its verdict."""
    latest: dict[tuple[str, str], dict] = {}
    for entry in history["measurements"]:
        latest[(entry["flow"], entry["metric"])] = entry
    return latest


def performance(history: dict, reference_date: str) -> dict:
    """Latest measurement per (flow, metric), sorted by flow and metric."""
    rows = []
    for (flow, metric), e in sorted(latest_by_metric(history).items()):
        age = _age_hours(str(e["date"]), reference_date)
        rows.append({"flow": flow, "metric": metric, "id": e["id"], "value": e["value"], "value_kind": e["value_kind"],
                     "ci95": _copy(e["ci95"]), "n_pairs": e["n_pairs"], "verdict": e["verdict"], "date": str(e["date"]),
                     "source_commit": e["source_commit"], "age_hours": age, "stale": age > STALE_AFTER_HOURS})
    by_verdict = Counter(r["verdict"] for r in rows)
    return {"source": "performance-history.yml", "reference_date": reference_date, "stale_rule": STALE_RULE,
            "latest_count": len(rows), "stale_count": sum(1 for r in rows if r["stale"]),
            "by_verdict": {v: by_verdict.get(v, 0) for v in VERDICT_ORDER}, "latest": rows}


def perf_attention(perf_block: dict) -> list[dict]:
    """rust_worse latest entries first, then known problems without a history entry."""
    out = [{"flow": r["flow"], "metric": r["metric"], "id": r["id"], "verdict": r["verdict"], "value": r["value"],
            "ci95": _copy(r["ci95"]), "stale": r["stale"], "status": INVESTIGATING.get((r["flow"], r["metric"]), "open")}
           for r in perf_block["latest"] if r["verdict"] == "rust_worse"]
    return out + [dict(u) for u in UNRECORDED]
