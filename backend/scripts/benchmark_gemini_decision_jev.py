"""Benchmark Gemini Decision 1 against Jev on OpenMates' labelled decision tasks.

Architecture: one paired runner for every decision purpose. Suites in
backend/scripts/decision_bench/ build labelled cases with the PRODUCTION
question builders; this runner sends each case to both models with the same
state, questions and images, then scores accuracy, safety false positives and
false negatives, response validity, refusals, latency, tokens and cost.
Data: synthetic or labelled test data only, never user data. Private suites
(e.g. the image-safety set) read their files from --private-dir and are never
committed.
Production behaviour: "gemini+fallback" replays the routed path: Gemini's
answer, or Jev's answer for the same case when Gemini failed, refused or took
longer than the production Gemini timeout (latency then adds both calls).
--resummarize DIR recomputes summary.json from an earlier run's rows.jsonl.
Usage (inside the api container, Vault credentials):
  python backend/scripts/benchmark_gemini_decision_jev.py --suite all --repeats 2 \
      --output-dir /tmp/gemini-jev [--private-dir /tmp/private-bench]

Case format (dict), produced by a suite's ``cases(private_dir)``:
  id, suite: str
  state: JSON value; questions: production question definitions
  images: optional {asset_uuid: image path}; each is prepared like production
  expected: {question_id: value | [acceptable values]}; unscored questions are omitted
      choice -> option key; noul -> bool; score -> level index (int)
  rules: optional {question_id: {"at": 0.65}} for noul cut-offs, or
      {"option": "block", "at": 0.9, "else": "allow"} for a choice cut-off, or
      {"at_least": 7} for a score cut-off (the prediction becomes a bool)
  positive: optional {question_id: value} = the "unsafe"/flagged class, for FP/FN rates
  critical: optional bool, a miss here is a critical false negative
"""
from __future__ import annotations

import argparse
import asyncio
import base64
import importlib
import json
import math
import statistics
import sys
import time
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

# Mirrors client.GEMINI_TIMEOUT_SECONDS: a slower Gemini answer is dropped and Jev decides.
PRODUCTION_GEMINI_TIMEOUT_MS = 2500
JEV_USD_PER_M = 0.042
GEMINI_USD_PER_M = 0.10
ENGINES = ("jev", "gemini")


def load_suites(names: str) -> list[Any]:
    from decision_bench import SUITES

    selected = list(SUITES) if names == "all" else names.split(",")
    return [importlib.import_module(f"decision_bench.{name}") for name in selected]


def prepared_assets(case: dict[str, Any]) -> dict[str, dict[str, str]]:
    from backend.apps.pdf.services.pdf_safety import prepare_image_for_jev

    assets = {}
    for reference, path in (case.get("images") or {}).items():
        jpeg = prepare_image_for_jev(Path(path).read_bytes())
        if jpeg is None:
            raise ValueError(f"{case['id']}: image {path} cannot be prepared")
        assets[reference] = {"type": "image", "format": "jpg", "data_base64": base64.b64encode(jpeg).decode()}
    return assets


def answer_dict(answer: Any) -> dict[str, Any]:
    return answer.model_dump() if hasattr(answer, "model_dump") else dict(answer)


async def call(engine: str, case: dict[str, Any], assets: dict[str, Any], secrets: Any, http: Any) -> dict[str, Any]:
    from backend.shared.providers.google.decisions import GeminiDecisionClient, GeminiDecisionError, images_from_assets
    from backend.shared.providers.typesafe.client import DecisionProviderError, JevDecisionClient

    started = time.perf_counter()
    row: dict[str, Any] = {"case": case["id"], "suite": case["suite"], "engine": engine}
    try:
        if engine == "jev":
            client = JevDecisionClient(secrets_manager=secrets, provider="typesafe", http_client=http,
                                       timeout_seconds=15.0, max_retries=0)
            response = await client.evaluate(state=case["state"], questions=case["questions"], assets=assets or None)
        else:
            client = GeminiDecisionClient(secrets_manager=secrets, timeout_seconds=15.0)
            response = await client.evaluate(http, state=case["state"], questions=case["questions"],
                                             images=images_from_assets(assets))
        row.update(ok=True, answers={k: answer_dict(v) for k, v in response.answers.items()},
                   input_tokens=response.usage.input_tokens)
    except GeminiDecisionError as exc:
        row.update(ok=False, error=exc.reason, blocked=exc.reason == "blocked", detail=str(exc)[:160])
    except (DecisionProviderError, ValueError) as exc:
        row.update(ok=False, error=type(exc).__name__, blocked=False, detail=str(exc)[:160])
    row["ms"] = (time.perf_counter() - started) * 1000
    return row


def predicted(question: dict[str, Any], answer: dict[str, Any], rule: dict[str, Any] | None) -> Any:
    kind = question["type"]
    if kind == "noul":
        return float(answer["noul"]) >= (rule or {}).get("at", 0.5)
    if kind == "score":
        probabilities = answer.get("probabilities") or {}
        level = int(max(probabilities, key=probabilities.get)) if probabilities else round(answer["score"])
        return level >= rule["at_least"] if rule and "at_least" in rule else level
    if rule and "option" in rule:
        return rule["option"] if (answer.get("probabilities") or {}).get(rule["option"], 0) >= rule["at"] else rule["else"]
    return answer.get("choice")


def normalize_case(case: dict[str, Any]) -> dict[str, Any]:
    """Score cut-off rules turn level labels (e.g. [7, 8, 9]) into the bool production acts on."""
    for qid, rule in (case.get("rules") or {}).items():
        if "at_least" not in rule:
            continue
        levels = case["expected"].get(qid)
        levels = levels if isinstance(levels, list) else [levels]
        if all(isinstance(level, int) and not isinstance(level, bool) for level in levels):
            flags = {level >= rule["at_least"] for level in levels}
            if len(flags) != 1:
                raise ValueError(f"{case['id']}: labels {levels} straddle the cut-off {rule['at_least']}")
            case["expected"][qid] = flags.pop()
        positive = (case.get("positive") or {}).get(qid)
        if isinstance(positive, int) and not isinstance(positive, bool):
            case["positive"][qid] = positive >= rule["at_least"]
    return case


def score_row(row: dict[str, Any], case: dict[str, Any]) -> None:
    row["questions"] = {}
    if not row["ok"]:
        return
    for qid, expected in case["expected"].items():
        answer = row["answers"].get(qid)
        if answer is None:
            row["questions"][qid] = {"correct": False, "pred": None}
            continue
        pred = predicted(case["questions"][qid], answer, (case.get("rules") or {}).get(qid))
        accepted = expected if isinstance(expected, list) else [expected]
        row["questions"][qid] = {"correct": pred in accepted, "pred": pred}


def percentile(values: list[float], q: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    return ordered[max(0, math.ceil(len(ordered) * q) - 1)]


def mcnemar_worse_p(jev_right: list[bool], gem_right: list[bool]) -> float:
    """One-sided exact McNemar p-value that Gemini is worse than Jev on paired outcomes."""
    b = sum(j and not g for j, g in zip(jev_right, gem_right))
    c = sum(g and not j for j, g in zip(jev_right, gem_right))
    n = b + c
    if n == 0:
        return 1.0
    return sum(math.comb(n, k) for k in range(b, n + 1)) / 2 ** n


def summarize(rows: list[dict[str, Any]], cases: dict[str, dict[str, Any]]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for suite in sorted({r["suite"] for r in rows}):
        suite_rows = [r for r in rows if r["suite"] == suite]
        by_key = {(r["engine"], r["case"], r["rep"]): r for r in suite_rows}
        keys = sorted({(r["case"], r["rep"]) for r in suite_rows})
        stats: dict[str, Any] = {}
        def served(k: tuple[str, int]) -> bool:
            """Production keeps Gemini's answer only when it arrived within its timeout."""
            row = by_key[("gemini",) + k]
            return row["ok"] and row["ms"] <= PRODUCTION_GEMINI_TIMEOUT_MS

        variants = {"jev": lambda k: by_key[("jev",) + k], "gemini": lambda k: by_key[("gemini",) + k],
                    "gemini+fallback": lambda k: by_key[("gemini",) + k] if served(k) else by_key[("jev",) + k]}
        correctness: dict[str, list[bool]] = {}
        for name, pick in variants.items():
            picked = [pick(k) for k in keys]
            right, fp, fn, neg, pos, crit_fn, q_right, q_total = [], 0, 0, 0, 0, 0, 0, 0
            per_question: dict[str, list[int]] = {}
            for (case_id, _), row in zip(keys, picked):
                case = cases[case_id]
                qs = row.get("questions") or {}
                case_ok = row["ok"] and all(q["correct"] for q in qs.values())
                right.append(case_ok)
                for qid in case["expected"]:
                    q = qs.get(qid, {"correct": False, "pred": None})
                    q_total += 1
                    q_right += q["correct"]
                    per_question.setdefault(qid, [0, 0])
                    per_question[qid][0] += q["correct"]
                    per_question[qid][1] += 1
                for qid, flagged in (case.get("positive") or {}).items():
                    expected = case["expected"].get(qid)
                    truth = flagged in (expected if isinstance(expected, list) else [expected])
                    pred = qs.get(qid, {}).get("pred")
                    hit = pred == flagged
                    if truth:
                        pos += 1
                        if not hit:
                            fn += 1
                            crit_fn += bool(case.get("critical"))
                    else:
                        neg += 1
                        fp += hit
            correctness[name] = right
            if name == "gemini+fallback":
                ms = [by_key[("gemini",) + k]["ms"] if served(k) else
                      min(by_key[("gemini",) + k]["ms"], PRODUCTION_GEMINI_TIMEOUT_MS) + by_key[("jev",) + k]["ms"]
                      for k in keys]
            else:
                ms = [row["ms"] for row in picked]
            tokens = [row.get("input_tokens") or 0 for row in picked if row["ok"]]
            rate = JEV_USD_PER_M if name == "jev" else GEMINI_USD_PER_M
            errors: dict[str, int] = {}
            for row in picked:
                if not row["ok"]:
                    errors[row["error"]] = errors.get(row["error"], 0) + 1
            stats[name] = {
                "attempts": len(picked), "valid": sum(r["ok"] for r in picked),
                "fallbacks": sum(not served(k) for k in keys) if name == "gemini+fallback" else None,
                "case_accuracy": sum(right) / len(right) if right else None,
                "question_accuracy": q_right / q_total if q_total else None,
                "per_question": {q: round(a / t, 3) for q, (a, t) in per_question.items()},
                "false_positive_rate": fp / neg if neg else None, "false_negative_rate": fn / pos if pos else None,
                "critical_false_negatives": crit_fn, "positives": pos, "negatives": neg,
                "errors": errors, "blocked": sum(bool(r.get("blocked")) for r in picked),
                "p50_ms": percentile(ms, 0.5), "p95_ms": percentile(ms, 0.95),
                "mean_input_tokens": statistics.mean(tokens) if tokens else None,
                "usd_per_1k": statistics.mean(tokens) * rate / 1000 if tokens else None,
            }
        flips = {}
        for engine in ENGINES:
            per_case: dict[str, set[str]] = {}
            for (case_id, rep) in keys:
                row = by_key[(engine, case_id, rep)]
                if row["ok"]:
                    per_case.setdefault(case_id, set()).add(json.dumps(
                        {q: v["pred"] for q, v in row["questions"].items()}, sort_keys=True))
            flips[engine] = sum(len(v) > 1 for v in per_case.values())
        stats["repeat_flips"] = flips
        stats["verdict"] = verdict(stats, correctness)
        out[suite] = stats
    return out


def verdict(stats: dict[str, Any], correctness: dict[str, list[bool]]) -> dict[str, Any]:
    """Gemini default only when it is not measurably worse than Jev on accuracy, reliability or safety."""
    jev, gem, routed = stats["jev"], stats["gemini"], stats["gemini+fallback"]
    p_worse = mcnemar_worse_p(correctness["jev"], correctness["gemini+fallback"])
    reasons = []
    if p_worse < 0.1:
        reasons.append(f"accuracy worse (McNemar p={p_worse:.3f})")
    if (routed["case_accuracy"] or 0) < (jev["case_accuracy"] or 0) - 0.03:
        reasons.append("accuracy more than 3 points lower")
    if gem["valid"] < jev["valid"] - max(1, 0.01 * jev["attempts"]):
        reasons.append("fewer valid responses")
    if routed["critical_false_negatives"] > jev["critical_false_negatives"]:
        reasons.append("more critical false negatives")
    if routed["false_negative_rate"] is not None and jev["false_negative_rate"] is not None \
            and routed["false_negative_rate"] > jev["false_negative_rate"] + 0.02:
        reasons.append("higher safety false-negative rate")
    return {"gemini_default": not reasons, "reasons": reasons, "p_worse": round(p_worse, 4)}


async def run(args: argparse.Namespace) -> None:
    import httpx
    from backend.core.api.app.utils.secrets_manager import SecretsManager

    suites = load_suites(args.suite)
    cases: dict[str, dict[str, Any]] = {}
    for module in suites:
        for case in module.cases(args.private_dir):
            if case["id"] in cases:
                raise ValueError(f"duplicate case id {case['id']}")
            cases[case["id"]] = normalize_case(case)
    if args.limit:
        cases = dict(list(cases.items())[: args.limit])
    print(f"{len(cases)} cases x {len(ENGINES)} engines x {args.repeats} repeats", flush=True)
    if args.dry_run:
        return
    if args.resummarize:
        rows = [json.loads(line) for line in (args.resummarize / "rows.jsonl").read_text().splitlines() if line]
        rows = [row for row in rows if row["case"] in cases]
        for row in rows:
            score_row(row, cases[row["case"]])
        report(summarize(rows, cases), args.resummarize)
        return
    secrets = SecretsManager()
    await secrets.initialize()
    semaphores = {engine: asyncio.Semaphore(args.concurrency) for engine in ENGINES}
    rows: list[dict[str, Any]] = []
    async with httpx.AsyncClient(timeout=20) as http:
        async def one(case: dict[str, Any], engine: str, rep: int, assets: dict[str, Any]) -> None:
            async with semaphores[engine]:
                row = await call(engine, case, assets, secrets, http)
            row["rep"] = rep
            score_row(row, case)
            rows.append(row)

        jobs = []
        for case in cases.values():
            assets = prepared_assets(case)
            jobs += [one(case, engine, rep, assets) for rep in range(args.repeats) for engine in ENGINES]
        await asyncio.gather(*jobs)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    with (args.output_dir / "rows.jsonl").open("w") as handle:
        for row in sorted(rows, key=lambda r: (r["suite"], r["case"], r["engine"], r["rep"])):
            handle.write(json.dumps(row, default=str) + "\n")
    report(summarize(rows, cases), args.output_dir)


def report(summary: dict[str, Any], output_dir: Path) -> None:
    (output_dir / "summary.json").write_text(json.dumps(summary, indent=1, default=str))
    for suite, stats in summary.items():
        print(f"\n## {suite}  verdict={'GEMINI' if stats['verdict']['gemini_default'] else 'JEV'} "
              f"{stats['verdict']['reasons']}")
        for name in ("jev", "gemini", "gemini+fallback"):
            s = stats[name]
            print(f"  {name:16} acc={s['case_accuracy']:.3f} q={s['question_accuracy']:.3f} "
                  f"valid={s['valid']}/{s['attempts']} blocked={s['blocked']} fallbacks={s['fallbacks']} "
                  f"fp={s['false_positive_rate']} "
                  f"fn={s['false_negative_rate']} critFN={s['critical_false_negatives']} "
                  f"p50={s['p50_ms']:.0f} p95={s['p95_ms']:.0f} $/1k={s['usd_per_1k']}")


def arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--suite", default="all", help="comma-separated suite modules or 'all'")
    parser.add_argument("--repeats", type=int, default=2)
    parser.add_argument("--concurrency", type=int, default=4)
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--private-dir", type=Path, default=None)
    parser.add_argument("--output-dir", type=Path, default=Path("/tmp/gemini-jev"))
    parser.add_argument("--dry-run", action="store_true", help="build and count cases without calling providers")
    parser.add_argument("--resummarize", type=Path, default=None, help="rescore an earlier run directory")
    return parser.parse_args()


if __name__ == "__main__":
    asyncio.run(run(arguments()))
