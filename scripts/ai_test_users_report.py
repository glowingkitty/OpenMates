"""Daily summary, report.md, cost estimate and the once-per-day push marker for AI test users."""

from __future__ import annotations

import json
import os
from datetime import date
from pathlib import Path

DAILY_CAP_USD = 3.0
WEEKLY_CAP_USD = 6.0
MAX_IDS_IN_PUSH = 5
USD_PER_CREDIT = 0.001


def cap_for(kind: str, override: float | None = None) -> float:
    if override is not None:
        return override
    return WEEKLY_CAP_USD if kind == "weekly" else DAILY_CAP_USD


def estimate_usd(count: int, harness_cap: float, e2b_cap: float) -> float:
    """Worst-case cost of `count` sessions: harness and E2B caps (gift card credits are not cash cost)."""
    return round(count * (harness_cap + e2b_cap), 3)


def check_cap(kind: str, count: int, harness_cap: float, e2b_cap: float, override: float | None = None) -> None:
    cap, cost = cap_for(kind, override), estimate_usd(count, harness_cap, e2b_cap)
    if cost > cap:
        raise SystemExit(f"{kind} run would cost up to {cost:.2f} USD, above the {cap:.2f} USD cap")


def summary_text(kind: str, run_date: str, results: list[dict], areas: list[str]) -> str:
    """One or two sentences: counts, the top finding and at most five short report IDs."""
    ran = [r for r in results if r.get("status") not in ("skipped", "prod_disabled", "no_gift_card")]
    reports = [r for r in results for rep in r.get("reports", [])]
    ids = [rep["short_issue_id"] for r in results for rep in r.get("reports", []) if rep.get("short_issue_id")]
    kept = sum(r.get("findings_kept") or 0 for r in results)
    label = "Weekly AI test-user run" if kind == "weekly" else "AI test users"
    first = f"✅ {label} {run_date}: {len(ran)} personas ran, {kept} findings kept, {len(ids)} reports filed."
    if len(reports) == 0 and not ids:
        first = f"✅ {label} {run_date}: {len(ran)} personas ran, {kept} findings kept, no reports filed."
    second = ""
    if ids:
        shown = ", ".join(ids[:MAX_IDS_IN_PUSH])
        more = f" (+{len(ids) - MAX_IDS_IN_PUSH} more)" if len(ids) > MAX_IDS_IN_PUSH else ""
        second = f" Reports: {shown}{more}."
    elif areas:
        second = f" Areas: {', '.join(areas[:3])}."
    return first + second


def marker_path(base: Path, day: str) -> Path:
    return base / "daily-push" / f"{day}.sent"


def push_due(base: Path, day: str) -> bool:
    return not marker_path(base, day).exists()


def mark_pushed(base: Path, day: str) -> None:
    path = marker_path(base, day)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(day)
    os.chmod(path, 0o600)


def report_markdown(run: dict, run_dir: Path) -> str:
    lines = [f"# AI test users {run['date']} ({run['kind']})", "",
             f"Areas: {', '.join(run.get('areas') or []) or 'none'}",
             f"Estimated cost: {run['estimate_usd']} USD (cap {run['cap_usd']}); "
             f"measured: {run['totals']['total_usd']} USD", ""]
    lines.append("## Personas")
    for r in run["personas"]:
        link = f" - [transcript]({run_dir / r['target'] / r['persona'] / 'transcript.md'})" if r.get("persona") else ""
        lines.append(f"- {r['target']}/{r['persona']}: {r.get('status')}, kept {r.get('findings_kept', 0)} of "
                     f"{r.get('findings_total', 0)}, deletion {r.get('deletion_status', 'n/a')}{link}")
    lines += ["", "## Reports filed"]
    reports = [(r, rep) for r in run["personas"] for rep in r.get("reports", [])]
    lines += [f"- {rep.get('short_issue_id')} ({r['target']}/{r['persona']}): {rep.get('status')}, "
              f"investigation {rep.get('queued', 'not queued')}" for r, rep in reports] or ["- none"]
    lines += ["", "## False positives (dropped by Jev)"]
    dropped = [f"- {r['target']}/{r['persona']}: {r['findings_total'] - r['findings_kept']}"
               for r in run["personas"] if (r.get("findings_total") or 0) > (r.get("findings_kept") or 0)]
    lines += dropped or ["- none"]
    lines += ["", "## Demo candidates"]
    demos = [f"- {r['target']}/{r['persona']}: {json.dumps(r['demo_candidate'], ensure_ascii=False)[:300]}"
             for r in run["personas"] if r.get("demo_candidate")]
    lines += demos or ["- none"]
    totals = run["totals"]
    lines += ["", "## Cost", f"harness {totals['harness_usd']:.3f} USD, E2B {totals['e2b_usd']:.3f} USD, "
              f"app credits (list price) {totals['app_usd_list_price']:.3f} USD"]
    return "\n".join(lines) + "\n"


def parse_date(text: str | None) -> date:
    return date.fromisoformat(text) if text else date.today()
