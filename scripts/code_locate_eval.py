#!/usr/bin/env python3
"""Re-measure code_map.py find on real commits: local search alone vs search + Jev.

Purpose: check the locate quality after changes to code_locate before trusting them.
Cases: feat/fix commits on origin/dev; query = "<scope>: <subject>" (the area an agent
knows) or the bare subject; targets = changed non-test source files that still exist.
The index is today's tree, which already contains each change (it locates existing code).
Usage:
  code_locate_eval.py prepare [--cases 120]
  code_locate_eval.py retrieval [--no-scope]                    free, local only
  code_locate_eval.py jev --max-usd 0.05 [--limit 40] [--no-scope]
Jev runs use their own ledger with the given cap, never the agents' daily budget.
Results go to ~/.cache/openmates-code-locate/eval/.
"""

from __future__ import annotations

import argparse
import json
import statistics
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import code_locate  # noqa: E402  (sibling script, not a package)
import code_locate_jev  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
OUT = code_locate.CACHE_DIR / "eval"


def build_cases(rows: list[dict], n: int) -> list[dict]:
    known = {r["path"] for r in rows}
    log = subprocess.run(["git", "-C", str(ROOT), "log", "origin/dev", "--no-merges", "-2500",
                          "--format=%x01%H%x02%s", "--name-only"], check=True, capture_output=True, text=True).stdout
    cases = []
    for block in log.split("\x01")[1:]:
        head, _, names = block.partition("\n")
        sha, _, subject = head.partition("\x02")
        if not subject.startswith(("feat", "fix")) or ":" not in subject:
            continue
        prefix, text = subject.split(":", 1)
        targets = [f for f in names.split("\n") if f in known]
        if 1 <= len(targets) <= 8:
            scope = prefix[prefix.find("(") + 1: prefix.find(")")] if "(" in prefix and ")" in prefix else ""
            cases.append({"sha": sha[:10], "subject": text.strip(), "scope": scope, "targets": targets})
        if len(cases) == n:
            break
    return cases


def query_of(case: dict, scope: bool) -> str:
    return f"{case['scope']}: {case['subject']}" if scope and case["scope"] else case["subject"]


def any_hit(ranked: list[str], targets: list[str], k: int = 5) -> bool:
    return bool(set(ranked[:k]) & set(targets))


def cmd_prepare(args) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    cases = build_cases(code_locate.load_index(ROOT), args.cases)
    (OUT / "cases.json").write_text(json.dumps(cases, indent=1))
    print(f"{len(cases)} cases written to {OUT / 'cases.json'}")


def _ranked(retriever, rows, query, k):
    return [rows[d]["path"] for d in code_locate.retrieve(retriever, query, k)]


def cmd_retrieval(args) -> None:
    rows = code_locate.load_index(ROOT)
    retriever = code_locate.Retriever(rows)
    cases = json.loads((OUT / "cases.json").read_text())
    for k in (5, 10, 40, 100):
        hits = sum(any_hit(_ranked(retriever, rows, query_of(c, not args.no_scope), 100), c["targets"], k)
                   for c in cases)
        print(f"target among the first {k:3}: {hits / len(cases):.3f}  ({len(cases)} cases)")


def cmd_jev(args) -> None:
    rows = code_locate.load_index(ROOT)
    retriever = code_locate.Retriever(rows)
    by_path = {r["path"]: r for r in rows}
    cases = json.loads((OUT / "cases.json").read_text())[: args.limit]
    ledger = code_locate_jev.Ledger(OUT / "eval-spend.json", args.max_usd)
    results = []
    for case in cases:
        query = query_of(case, not args.no_scope)
        paths = _ranked(retriever, rows, query, code_locate.DEFAULT_K)
        out = code_locate_jev.score(query, [code_locate.candidate_view(by_path[p], query) for p in paths],
                                    ledger=ledger)
        ranked = code_locate.fuse(paths, out["scores"]) if out.get("scores") else []
        results.append({**case, "query": query, "search_top": paths[:10], "jev_top": ranked[:10],
                        "top_score": max(out["scores"].values()) if out.get("scores") else None,
                        "fallback": out.get("fallback"), "usd": out.get("usd", 0.0)})
        if out.get("fallback", "").startswith("daily"):
            print("eval cap reached; stopping")
            break
    done = [r for r in results if r["jev_top"]]
    name = OUT / f"jev-{'subject' if args.no_scope else 'scope'}.json"
    name.write_text(json.dumps(results, indent=1))
    if not done:
        print("no Jev results", {r["fallback"] for r in results})
        return
    print(f"cases {len(done)} (fallbacks {len(results) - len(done)}), USD {sum(r['usd'] for r in results):.4f}")
    print(f"target in top 5: search {statistics.mean(any_hit(r['search_top'], r['targets']) for r in done):.3f}, "
          f"search+Jev {statistics.mean(any_hit(r['jev_top'], r['targets']) for r in done):.3f}")
    print(f"wrote {name}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("prepare").add_argument("--cases", type=int, default=120)
    sub.add_parser("retrieval").add_argument("--no-scope", action="store_true")
    jev = sub.add_parser("jev")
    jev.add_argument("--max-usd", type=float, required=True)
    jev.add_argument("--limit", type=int, default=40)
    jev.add_argument("--no-scope", action="store_true")
    args = parser.parse_args()
    {"prepare": cmd_prepare, "retrieval": cmd_retrieval, "jev": cmd_jev}[args.cmd](args)


if __name__ == "__main__":
    main()
