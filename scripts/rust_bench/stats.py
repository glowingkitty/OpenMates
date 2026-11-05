"""Statistics and paired-order helpers for the Rust-vs-TypeScript CLI benchmark.

Pure functions only (no IO) so they are cheap to unit test.
"""

from __future__ import annotations

import math
from typing import Iterable, Sequence

ARMS = ("rust", "typescript")
METRICS = ("wallMs", "cpuMs", "cpuUserMs", "cpuSystemMs", "peakMemKiB", "maxRssKiB")


def paired_order(samples: int, arms: Sequence[str] = ARMS) -> list[tuple[int, str]]:
    """Alternate the starting arm per pair: AB, BA, AB, ... (counterbalanced ABAB).

    Returns a list of (sample_index, arm). Each arm gets exactly `samples` slots
    and the first arm alternates so neither arm is always measured first.
    """
    if samples < 1:
        raise ValueError("samples must be >= 1")
    if len(arms) != 2 or arms[0] == arms[1]:
        raise ValueError("exactly two distinct arms are required")
    order: list[tuple[int, str]] = []
    for index in range(samples):
        pair = arms if index % 2 == 0 else (arms[1], arms[0])
        order.extend((index, arm) for arm in pair)
    return order


def percentile(values: Sequence[float], q: float) -> float:
    """Linear-interpolated percentile (same as numpy's default 'linear')."""
    if not values:
        raise ValueError("percentile of empty sequence")
    if not 0.0 <= q <= 100.0:
        raise ValueError("q must be within [0, 100]")
    ordered = sorted(float(v) for v in values)
    if len(ordered) == 1:
        return ordered[0]
    rank = (len(ordered) - 1) * q / 100.0
    low = math.floor(rank)
    high = math.ceil(rank)
    if low == high:
        return ordered[low]
    return ordered[low] + (ordered[high] - ordered[low]) * (rank - low)


def summarize(values: Iterable[float]) -> dict:
    data = [float(v) for v in values]
    if not data:
        return {"n": 0, "median": None, "p95": None, "mean": None, "min": None, "max": None}
    return {
        "n": len(data),
        "median": round(percentile(data, 50), 3),
        "p95": round(percentile(data, 95), 3),
        "mean": round(sum(data) / len(data), 3),
        "min": round(min(data), 3),
        "max": round(max(data), 3),
    }


def ratio(rust: float | None, typescript: float | None) -> float | None:
    """Rust / TypeScript. < 1 means Rust is lower (faster / less CPU / less memory)."""
    if rust is None or typescript is None or typescript == 0:
        return None
    return round(rust / typescript, 4)


def flow_summary(samples: Sequence[dict], metrics: Sequence[str] = METRICS) -> dict:
    """Aggregate successful samples of one flow into per-arm stats and Rust/TS ratios.

    `samples` entries look like {"arm": "rust", "ok": True, "metrics": {...}}.
    Only ok samples contribute; failures are counted separately.
    """
    arms: dict = {}
    for arm in ARMS:
        rows = [s for s in samples if s["arm"] == arm]
        good = [s["metrics"] for s in rows if s.get("ok")]
        arms[arm] = {
            "samples": len(rows),
            "failures": len(rows) - len(good),
            "metrics": {
                metric: summarize(m[metric] for m in good if m.get(metric) is not None)
                for metric in metrics
            },
        }
    ratios = {
        metric: {
            stat: ratio(arms["rust"]["metrics"][metric][stat], arms["typescript"]["metrics"][metric][stat])
            for stat in ("median", "p95", "mean")
        }
        for metric in metrics
    }
    return {"arms": arms, "ratioRustOverTypescript": ratios}


def _fmt(value: float | None, digits: int = 1) -> str:
    return "-" if value is None else f"{value:.{digits}f}"


TABLE_METRICS = (("wallMs", "wall ms"), ("cpuMs", "cpu ms"), ("peakMemKiB", "peak KiB"))


def markdown_table(report: dict) -> str:
    """Compact table: one row per flow x metric, median/p95/mean per arm, ratio of medians."""
    lines = [
        f"Rust vs TypeScript CLI ({report['config']['samples']} paired samples, "
        f"memory={report['meter']['memory']}, cpu={report['meter']['cpu']})",
        "",
        "| flow | metric | rust median | rust p95 | rust mean | ts median | ts p95 | ts mean "
        "| ratio median | ratio p95 | fail r/ts |",
        "|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---|",
    ]
    for flow in report["flows"]:
        if flow.get("skipped"):
            lines.append(f"| {flow['name']} | skipped: {flow['skipped']} |  |  |  |  |  |  |  |  |  |")
            continue
        summary = flow["summary"]
        rust, ts = summary["arms"]["rust"], summary["arms"]["typescript"]
        for key, label in TABLE_METRICS:
            r, t = rust["metrics"][key], ts["metrics"][key]
            q = summary["ratioRustOverTypescript"][key]
            digits = 0 if key == "peakMemKiB" else 1
            lines.append(
                f"| {flow['name']} | {label} | {_fmt(r['median'], digits)} | {_fmt(r['p95'], digits)} "
                f"| {_fmt(r['mean'], digits)} | {_fmt(t['median'], digits)} | {_fmt(t['p95'], digits)} "
                f"| {_fmt(t['mean'], digits)} | {_fmt(q['median'], 3)} | {_fmt(q['p95'], 3)} "
                f"| {rust['failures']}/{ts['failures']} |"
            )
    lines.append("")
    lines.append("ratio = Rust / TypeScript; < 1.0 means Rust used less.")
    return "\n".join(lines) + "\n"
