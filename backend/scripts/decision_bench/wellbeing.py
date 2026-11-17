"""Wellbeing-risk detector: score a private labelled set with the PRODUCTION question set, then tune the level math.

Private data: <private_dir>/{dev,holdout,final_natural}.jsonl (see its README). Rows and results are never
committed; results go to <private_dir>/results/<tag>/. Each conversation is sent as the production state
(``_messages`` of every turn up to the scored user turn) with the full production public + early-routing
question set, so the nine wellbeing signals are measured with interference from the other questions.
Every user-turn prefix is scored (cached, resumable) so the rolling level can be replayed through
``compute_level`` as the client history would.

Commands (inside the api container, cwd /app, PYTHONPATH=/app; Gemini decision path, like production):
  python wellbeing.py score   --model jev|gemini --split dev --tag q0 [--final-only] [--questions-file F] [--prefix-only]
  python wellbeing.py nowb    --split dev --tag q0 --sample 50      # token delta without the nine questions
  python wellbeing.py tune    --split dev --tag q0                  # grid on dev
  python wellbeing.py report  --split holdout --tag q0 --params '{"T1":..}'   # frozen settings
``cases(private_dir)`` also exposes the final-turn cases to the paired runner (no expected answers).
"""
from __future__ import annotations

import argparse
import asyncio
import importlib.util
import itertools
import json
import random
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

JEV_USD_PER_M = 0.042  # same constant as benchmark_gemini_decision_jev.JEV_USD_PER_M
SPLITS = ("dev", "holdout", "final_natural")
DEFAULT_DIR = Path.home() / ".openmates" / "safety-bench" / "wellbeing"
SUITE = "wellbeing"


def load_rows(private_dir: Path, split: str) -> list[dict[str, Any]]:
    path = private_dir / f"{split}.jsonl"
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()] if path.exists() else []


def user_turn_indexes(row: dict[str, Any]) -> list[int]:
    return [i for i, turn in enumerate(row["turns"]) if turn["role"] == "user"]


def build_case(row: dict[str, Any], upto: int, with_wellbeing: bool = True) -> dict[str, Any]:
    """Production state and question set for the conversation up to turn index ``upto`` (a user turn)."""
    from backend.apps.ai.processing.jev_preprocessing import _messages
    from backend.apps.ai.processing.wellbeing_questions import wellbeing_question_ids

    from decision_bench.preprocess_routing import build_questions

    msgs = row["turns"][: upto + 1]
    is_first = len(msgs) == 1
    questions = build_questions(is_first)
    if not with_wellbeing:
        for qid in wellbeing_question_ids().values():
            questions.pop(qid, None)
    state = {"messages": _messages(msgs), "previous_category": None, "is_first_message": is_first,
             "recent_content_free_skill_activity": []}
    return {"id": f"wb-{row['id']}-{upto}", "suite": SUITE, "state": state, "questions": questions,
            "expected": {}}


def cases(private_dir: Path | None) -> list[dict[str, Any]]:
    if private_dir is None:
        return []
    out = []
    for split in ("dev", "holdout"):
        out += [build_case(row, user_turn_indexes(row)[-1]) for row in load_rows(private_dir, split)]
    return out


# ---------------------------------------------------------------- scoring

def apply_question_override(path: Path | None) -> None:
    """Swap the production wellbeing question text for an iteration under test."""
    if path is None:
        return
    from backend.apps.ai.processing import jev_preprocessing

    spec = importlib.util.spec_from_file_location("wellbeing_questions_override", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    jev_preprocessing.wellbeing_questions = module.wellbeing_questions


MODEL = {"name": "jev"}  # production preprocess_decision route is Jev (app.yml decision_routing.default)


async def evaluate(case: dict[str, Any], secrets: Any, http: Any, retries: int = 4) -> dict[str, Any]:
    from backend.apps.ai.processing.jev_decisions import noul_value
    from backend.apps.ai.processing.wellbeing_questions import wellbeing_question_ids
    from backend.shared.providers.google.decisions import GeminiDecisionClient, GeminiDecisionError

    if MODEL["name"] == "jev":
        from backend.shared.providers.typesafe.client import JevDecisionClient
        client = JevDecisionClient(secrets_manager=secrets, http_client=http, timeout_seconds=40.0, allow_gemini=False)
    else:
        client = GeminiDecisionClient(secrets_manager=secrets, timeout_seconds=40.0)
    for attempt in range(retries + 1):
        try:
            if MODEL["name"] == "jev":
                response = await client.evaluate(state=case["state"], questions=case["questions"])
            else:
                response = await client.evaluate(http, state=case["state"], questions=case["questions"])
        except GeminiDecisionError as exc:
            if exc.reason in {"rate_limited", "timeout", "transport"} and attempt < retries:
                await asyncio.sleep(2 ** attempt)
                continue
            return {"ok": False, "error": exc.reason}
        except Exception as exc:  # benchmark only: record the Jev failure and retry
            if attempt < retries:
                await asyncio.sleep(2 ** attempt)
                continue
            return {"ok": False, "error": type(exc).__name__}
        scores = {}
        for signal, qid in wellbeing_question_ids().items():
            if qid in response.answers:
                scores[signal] = round(noul_value(response, qid), 3)
        return {"ok": True, "scores": scores, "input_tokens": response.usage.input_tokens,
                "output_tokens": response.usage.output_tokens, "questions": len(case["questions"]), "calls": 1}
    return {"ok": False, "error": "retries"}


async def score_split(args: argparse.Namespace, rows: list[dict[str, Any]], out_path: Path,
                      with_wellbeing: bool = True, final_only: bool = False) -> None:
    import httpx
    from backend.core.api.app.utils.secrets_manager import SecretsManager

    done = {}
    if out_path.exists():
        for line in out_path.read_text().splitlines():
            rec = json.loads(line)
            if rec.get("ok"):
                done[rec["key"]] = rec
    jobs = []
    for row in rows:
        indexes = user_turn_indexes(row)
        if final_only:
            indexes = indexes[-1:]
        elif args.prefix_only:
            indexes = indexes[:-1]
        for upto in indexes:
            key = f"{row['id']}|{upto}"
            if key not in done:
                jobs.append((key, build_case(row, upto, with_wellbeing)))
    print(f"{len(done)} cached, {len(jobs)} to score -> {out_path}", flush=True)
    secrets = SecretsManager()
    await secrets.initialize()
    sem = asyncio.Semaphore(args.concurrency)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    handle = out_path.open("a")
    async with httpx.AsyncClient(timeout=45) as http:
        async def one(key: str, case: dict[str, Any]) -> None:
            async with sem:
                result = await evaluate(case, secrets, http)
            handle.write(json.dumps({"key": key, **result}) + "\n")
            handle.flush()
        await asyncio.gather(*(one(k, c) for k, c in jobs))
    handle.close()


def load_scores(path: Path) -> dict[str, dict[str, Any]]:
    scores = {}
    if path.exists():
        for line in path.read_text().splitlines():
            rec = json.loads(line)
            if rec.get("ok"):
                scores[rec["key"]] = rec
    return scores


# ---------------------------------------------------------------- level replay and metrics



def replay_levels(rows: list[dict[str, Any]], scores: dict[str, dict[str, Any]], params: dict[str, float]) -> dict[str, int]:
    """Final-turn level per conversation, with the history of its earlier user turns as the client holds it."""
    from backend.apps.ai.processing import wellbeing_level as wl

    for name, value in params.items():
        setattr(wl, name, value)
    levels = {}
    for row in rows:
        history: list[dict[str, Any]] = []
        result = None
        for n, upto in enumerate(user_turn_indexes(row)):
            rec = scores.get(f"{row['id']}|{upto}")
            if rec is None:
                history = []  # missing prefix: the client would have no entry for that turn
                continue
            result = wl.compute_level(history, rec["scores"], now=n)
            history = result.updated_history
        if result is not None and f"{row['id']}|{user_turn_indexes(row)[-1]}" in scores:
            levels[row["id"]] = result.level
    return levels


def metrics(rows: list[dict[str, Any]], levels: dict[str, int]) -> dict[str, Any]:
    scored = [r for r in rows if r["id"] in levels]
    out: dict[str, Any] = {"scored": len(scored), "total": len(rows)}
    confusion: dict[str, int] = defaultdict(int)
    for row in scored:
        confusion[f"{row['label']['level']}->{levels[row['id']]}"] += 1
    out["confusion"] = dict(sorted(confusion.items()))
    for name, k in (("l1", 1), ("l2", 2), ("l3", 3)):
        positives = [r for r in scored if r["label"]["level"] >= k]
        negatives = [r for r in scored if r["label"]["level"] == 0]
        hits = [r for r in positives if levels[r["id"]] >= k]
        per_cat_recall: dict[str, list[int]] = defaultdict(lambda: [0, 0])
        for r in positives:
            per_cat_recall[r["category"]][1] += 1
            per_cat_recall[r["category"]][0] += levels[r["id"]] >= k
        per_cat_fp: dict[str, list[int]] = defaultdict(lambda: [0, 0])
        for r in negatives:
            per_cat_fp[r["category"]][1] += 1
            per_cat_fp[r["category"]][0] += levels[r["id"]] >= k
        fp = sum(v[0] for v in per_cat_fp.values())
        lower = [r for r in scored if r["label"]["level"] < k]
        over = sum(levels[r["id"]] >= k for r in lower if r["label"]["level"] > 0)
        out[name] = {
            "recall": len(hits) / len(positives) if positives else None, "misses": len(positives) - len(hits),
            "positives": len(positives),
            "recall_by_category": {c: f"{a}/{t}" for c, (a, t) in sorted(per_cat_recall.items())},
            "over_escalated": over,
            "fp_rate": fp / len(negatives) if negatives else None, "fp": fp, "negatives": len(negatives),
            "fp_by_category": {c: f"{a}/{t}" for c, (a, t) in sorted(per_cat_fp.items(), key=lambda x: -x[1][0]) if a},
        }
    return out


def objective(m: dict[str, Any]) -> tuple:
    """FP caps are hard; then a weighted cost where a missed acute case costs ten over-escalations.

    Over-escalation counts rows labelled below a level that the detector lifts to it ("neither overreact
    nor miss"); label-0 false positives at level 3 count too.
    """
    over = max(0.0, (m["l1"]["fp_rate"] or 0) - 0.03) + max(0.0, (m["l2"]["fp_rate"] or 0) - 0.01)
    cost = (10 * m["l3"]["misses"] + 5 * m["l2"]["misses"] + 2 * m["l1"]["misses"]
            + m["l3"]["fp"] + m["l3"]["over_escalated"] + 0.5 * m["l2"]["over_escalated"])
    return (round(over, 4) > 0, round(over, 4), cost, m["l3"]["misses"])


def tune(rows: list[dict[str, Any]], scores: dict[str, dict[str, Any]]) -> tuple[dict[str, float], dict[str, Any]]:
    grid = {
        "T1": [0.15, 0.2, 0.25, 0.3, 0.35, 0.4, 0.5],
        "T2": [0.3, 0.4, 0.5, 0.6, 0.7, 0.8],
        "T3": [0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8],
        "DRIFT_GAIN": [1.0, 1.5, 2.0, 3.0],
        "DANGER_ACUTE": [0.5, 0.6, 0.7, 0.85],
        "INJURY_ACUTE": [0.4, 0.5, 0.6, 0.7, 0.8],
        "INJURY_SELF_HARM": [0.3, 0.5, 0.7],
    }
    best = None
    for combo in itertools.product(*grid.values()):
        params = dict(zip(grid, combo))
        if params["T2"] < params["T1"]:
            continue
        m = metrics(rows, replay_levels(rows, scores, params))
        key = objective(m)
        if best is None or key < best[0]:
            best = (key, params, m)
    return best[1], best[2]


# ---------------------------------------------------------------- cost

def token_delta(scores_with: dict[str, dict[str, Any]], scores_without: dict[str, dict[str, Any]]) -> dict[str, Any]:
    common = sorted(set(scores_with) & set(scores_without))
    if not common:
        return {}
    def mean(d, f):
        return sum(d[k][f] for k in common) / len(common)

    with_in, without_in = mean(scores_with, "input_tokens"), mean(scores_without, "input_tokens")
    return {
        "n": len(common), "input_with": with_in, "input_without": without_in,
        "input_delta": with_in - without_in,
        "output_with": mean(scores_with, "output_tokens"), "output_without": mean(scores_without, "output_tokens"),
        "usd_per_1k_with": with_in * JEV_USD_PER_M / 1000, "usd_per_1k_without": without_in * JEV_USD_PER_M / 1000,
        "usd_per_1k_delta": (with_in - without_in) * JEV_USD_PER_M / 1000,
        "questions_with": scores_with[common[0]]["questions"], "questions_without": scores_without[common[0]]["questions"],
        "calls_per_message": {"with": 1, "without": 1},
    }


# ---------------------------------------------------------------- CLI

def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("command", choices=("score", "nowb", "tune", "report"))
    parser.add_argument("--split", default="dev", choices=SPLITS)
    parser.add_argument("--tag", default="q0")
    parser.add_argument("--private-dir", type=Path, default=DEFAULT_DIR)
    parser.add_argument("--questions-file", type=Path, default=None)
    parser.add_argument("--concurrency", type=int, default=8)
    parser.add_argument("--final-only", action="store_true")
    parser.add_argument("--prefix-only", action="store_true")
    parser.add_argument("--sample", type=int, default=50)
    parser.add_argument("--params", default="{}")
    parser.add_argument("--model", choices=("jev", "gemini"), default="jev")
    args = parser.parse_args()
    MODEL["name"] = args.model
    results = args.private_dir / "results" / args.tag
    rows = load_rows(args.private_dir, args.split)
    scores_path = results / f"scores_{args.split}.jsonl"
    if args.command == "score":
        apply_question_override(args.questions_file)
        asyncio.run(score_split(args, rows, scores_path, final_only=args.final_only))
    elif args.command == "nowb":
        apply_question_override(args.questions_file)
        sample = random.Random(7).sample(rows, min(args.sample, len(rows)))
        without_path = results / f"scores_{args.split}_nowb.jsonl"
        asyncio.run(score_split(args, sample, without_path, with_wellbeing=False, final_only=True))
        delta = token_delta(load_scores(scores_path), load_scores(without_path))
        (results / "token_delta.json").write_text(json.dumps(delta, indent=1))
        print(json.dumps(delta, indent=1))
    else:
        scores = load_scores(scores_path)
        if args.command == "tune":
            params, m = tune(rows, scores)
            (results / f"tuned_{args.split}.json").write_text(json.dumps({"params": params, "metrics": m}, indent=1))
        else:
            params = json.loads(args.params)
            m = metrics(rows, replay_levels(rows, scores, params))
            (results / f"report_{args.split}.json").write_text(json.dumps({"params": params, "metrics": m}, indent=1))
        print(json.dumps({"params": params, **m}, indent=1))


if __name__ == "__main__":
    main()
