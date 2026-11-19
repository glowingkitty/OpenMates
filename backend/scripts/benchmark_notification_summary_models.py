"""Opt-in benchmark of the notification type + summary; run in the dev API container only.

Reuses the provider boundary of `benchmark_postprocessing_models` (the full production
post-processing prompt and tool, no retries or fallbacks, nothing persisted) and
scores only the two notification fields on ~100 synthetic, clearly labelled
assistant replies: correct type, length limit, chat language, invented numbers,
latency, cost per summary and reliability. The synthetic replies are not real
user data. The summary is a platform cost; this run never touches a user account.

Run: docker exec api python /app/backend/scripts/benchmark_notification_summary_models.py \
         --allow-live-inference --out /tmp/notification-summary.json
"""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import logging
import re
from pathlib import Path
from typing import Any

import httpx
import yaml

from backend.scripts import benchmark_postprocessing_models as base
from backend.scripts.notification_summary_benchmark_cases import CASES, CASE_BY_ID, EXPECTED_TYPES

# Candidates. "gemini-lite" is today's post-processing model (baseline).
base.ARMS['gemini-4-hydrogen'] = ('google_ai_studio', 'gemini-4-hydrogen')
# Hydrogen is not in backend/providers/google.yml yet; list price from third-party
# trackers of Google's launch price (verify against Google's pricing page before relying on it).
base.PRICING['gemini-4-hydrogen'] = {'regular': (1.50, 7.50), 'promo': (1.50, 7.50),
                                     'source': 'third-party trackers of the 2026-11-12 launch price (unverified)'}
ARMS = ('gemini-lite', 'mercury-low', 'gemini-flash', 'gemini-4-hydrogen')
SUMMARY_LIMIT = 90
HARD_LIMIT = 100
_ENGLISH = re.compile(r'\b(the|and|with|added|tests?|pass|is|are|to|for|your|of)\b', re.I)
_CJK = re.compile(r'[぀-ヿ一-鿿]')


def score_row(case, output: dict[str, Any] | None) -> dict[str, Any]:
    """Deterministic scores for one provider answer; invalid or missing output scores zero."""
    kind = (output or {}).get('notification_type')
    summary = (output or {}).get('notification_summary')
    valid = kind in ('done', 'question', 'info') and isinstance(summary, str) and bool(summary.strip())
    result = {'valid': valid, 'type_ok': False, 'length_ok': False, 'language_ok': False, 'facts_ok': False}
    if not valid:
        return result
    text = case.assistant + ' ' + case.user
    numbers = re.findall(r'\d+(?:[.,]\d+)?', summary)
    language_ok = bool(_CJK.search(summary)) if case.language == 'ja' else (
        case.language == 'en' or len(_ENGLISH.findall(summary)) < 2)
    result.update(type_ok=kind in EXPECTED_TYPES[case.expected], length_ok=len(summary) <= HARD_LIMIT,
                  within_prompt_limit=len(summary) <= SUMMARY_LIMIT, language_ok=language_ok,
                  facts_ok=all(number in text for number in numbers))
    return result


def summarize(rows: list[dict]) -> dict[str, Any]:
    """Per-arm quality, latency, cost per 1k summaries and reliability."""
    summary: dict[str, Any] = {}
    for arm in sorted({row['arm'] for row in rows}):
        mine = [row for row in rows if row['arm'] == arm]
        scored = [row['score'] for row in mine]
        count = len(mine)

        def pct(key: str) -> float:
            return round(100 * sum(1 for score in scored if score.get(key)) / count, 1) if count else 0.0
        latencies = [row['complete_latency_seconds'] for row in mine if row.get('availability_status') == 'available']
        usages = [base.token_usage(row) for row in mine]
        known = [usage for usage in usages if usage]
        prices = base.PRICING[arm]

        def cost(kind: str) -> float | None:
            if not known:
                return None
            cheap, dear = prices[kind]
            return round(sum(i * cheap + o * dear for i, o in known) / len(known) / 1e6 * 1000, 4)
        summary[arm] = {
            'runs': count, 'reliability_pct': pct('valid'), 'type_correct_pct': pct('type_ok'),
            'length_ok_pct': pct('length_ok'), 'within_90_pct': pct('within_prompt_limit'),
            'language_ok_pct': pct('language_ok'), 'no_invented_numbers_pct': pct('facts_ok'),
            'p50_latency_s': round(base.percentile(latencies, 0.5) or 0, 2),
            'p95_latency_s': round(base.percentile(latencies, 0.95) or 0, 2),
            'cost_per_1k_summaries_usd_regular': cost('regular'), 'cost_per_1k_summaries_usd_promo': cost('promo'),
            'provider': base.ARMS[arm][0],
        }
    return summary


def render_markdown(report: dict) -> str:
    lines = ['# Notification type + summary benchmark', '',
             f"Revision: {report['revision']}; synthetic cases: {len(report['cases'])}; "
             f"results: {len(report['results'])}.", '',
             '| model | valid % | type % | <=100 chars % | language % | no invented numbers % | p50 s | p95 s | cost / 1k (regular / promo USD) |',
             '|---|---|---|---|---|---|---|---|---|']
    for arm, row in report['summary'].items():
        lines.append(f"| {arm} | {row['reliability_pct']} | {row['type_correct_pct']} | {row['length_ok_pct']} | "
                     f"{row['language_ok_pct']} | {row['no_invented_numbers_pct']} | {row['p50_latency_s']} | "
                     f"{row['p95_latency_s']} | {row['cost_per_1k_summaries_usd_regular']} / "
                     f"{row['cost_per_1k_summaries_usd_promo']} |")
    return '\n'.join(lines) + '\n'


def finalize(path: Path) -> None:
    """Score stored outputs (re-runnable without provider calls) and write the table."""
    report = json.loads(path.read_text())
    cases = {case['id']: case for case in report['cases']}
    for row in report['results']:
        case = CASE_BY_ID[row['case']] if row['case'] in CASE_BY_ID else None
        row['score'] = score_row(case, row.get('output')) if case and row.get('quality_evaluated') else score_row(case, None)
        row.pop('request', None)
        row.pop('raw_response', None)
        row['summary_text'] = (row.get('output') or {}).get('notification_summary')
        row['notification_type'] = (row.get('output') or {}).get('notification_type')
        row['expected'] = cases[row['case']]['expected']
    report['summary'] = summarize(report['results'])
    base.write_report(path, report)
    path.with_suffix('.md').write_text(render_markdown(report))


async def run(args) -> None:
    from backend.apps.ai.processing import postprocessor
    from backend.core.api.app.utils.secrets_manager import SecretsManager

    logging.disable(logging.CRITICAL)
    base_bytes = (Path(__file__).resolve().parents[1] / 'apps/ai/base_instructions.yml').read_bytes()
    instructions = yaml.safe_load(base_bytes)
    manager = SecretsManager()
    await manager.initialize()
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(60, connect=5)) as client:
            async def runner(case, arm):
                return await base.run_case(case, arm, manager=manager, client=client, base=instructions,
                                           postprocessor=postprocessor)
            await base.execute(arms=args.arms, cases=[CASE_BY_ID[c] for c in args.cases] if args.cases else list(CASES),
                               repeats=args.repeats, output=args.output, revision=args.revision, runner=runner,
                               base_hash=hashlib.sha256(base_bytes).hexdigest())
    finally:
        await manager.close()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--allow-live-inference', action='store_true')
    parser.add_argument('--out', '--output', dest='output', type=Path, required=True)
    parser.add_argument('--revision', default='workspace')
    parser.add_argument('--arms', nargs='+', choices=ARMS, default=list(ARMS))
    parser.add_argument('--cases', nargs='+', choices=list(CASE_BY_ID))
    parser.add_argument('--runs', '--repeats', dest='repeats', type=int, default=1)
    parser.add_argument('--finalize', action='store_true', help='score an existing --out file without provider calls')
    args = parser.parse_args()
    if args.finalize:
        finalize(args.output)
        return
    if not args.allow_live_inference:
        parser.error('--allow-live-inference is required for provider calls')
    asyncio.run(run(args))
    finalize(args.output)


if __name__ == '__main__':
    main()
