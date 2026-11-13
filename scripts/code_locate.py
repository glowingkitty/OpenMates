#!/usr/bin/env python3
"""Find the source files a coding task most likely touches: local search, then Jev ranking.

Purpose: one call instead of a grep loop when an agent needs to know where code lives.
Pipeline:
  load_index  git-tracked source files under ROOTS (tests and generated files left
              out). Per file: first doc line, top-level symbols, definition and
              comment lines, and identifier word counts. Entries are cached by git
              blob hash in CACHE_DIR, so worktrees share them and a new commit only
              re-reads the files it changed.
  retrieve    BM25 over path (weight 3), doc+symbols (2) and content (1), fused with
              one search per clause of the query.
  locate      the best K files go to Jev (code_locate_jev.py: daily cost cap, private
              word check, fallback to search order); final order = Jev score (0..4)
              plus a small bonus for a high search rank.
Measured on 259 real tasks: a target file in the top 5 for 81% with Jev, 69.5%
with local search alone. CLI: python3 scripts/code_map.py find "<area>: <change>".
"""

from __future__ import annotations

import fcntl
import gzip
import hashlib
import json
import math
import os
import re
import subprocess
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import code_map  # noqa: E402  (sibling script, not a package)

ROOTS = ["backend", "frontend/packages", "frontend/apps/web_app/src", "packages", "apple", "scripts"]
EXTS = {".py", ".rs", ".ts", ".svelte", ".swift"}
SKIP_PARTS = {"node_modules", "target", "build", "dist", "generated", "__tests__", "tests", ".git",
              "__pycache__", ".svelte-kit"}
MAX_BYTES = 400_000
SALIENT_LINES = 120
CACHE_DIR = Path(os.environ.get("OPENMATES_CODE_LOCATE_CACHE", Path.home() / ".cache" / "openmates-code-locate"))
CACHE_KEEP_DAYS = 7
DEFAULT_K = 40
RANK_BONUS = 0.1  # weight of the search-rank prior next to the Jev score (tuned on 40 commits)
STOPWORDS = set("""a an and are as at be by for from in into is it of on or that the this to with
via per when while after before not no all any can its their his her new use used using now only
also than then so but if we you they them each both more most other some such own same make makes
made one two three get gets set sets add adds fix fixes feat""".split())
COMMENT_RE = re.compile(r"^\s*(#|//|///|/\*|\*|\"\"\"|<!--)")
DEF_RE = re.compile(r"^\s*(pub\s+)?(async\s+)?(def|class|fn|struct|enum|trait|impl|func|function|export|"
                    r"interface|type|const|let|var|protocol|extension|mod)\b")


def is_test_or_generated(rel: str) -> bool:
    name = rel.rsplit("/", 1)[-1]
    if set(rel.split("/")) & SKIP_PARTS or "generated" in rel:
        return True
    return (".test." in name or ".spec." in name or name.endswith("_tests.rs")
            or name.startswith("test_") or name.endswith(".lock"))


def tokenize(text: str) -> list[str]:
    """Lowercase words with camelCase/snake_case split, stopwords dropped, plural folded."""
    text = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", text)
    out = []
    for tok in re.split(r"[^A-Za-z0-9]+", text.lower()):
        if len(tok) < 2 or tok in STOPWORDS or tok.isdigit():
            continue
        out.append(tok[:-1] if len(tok) > 3 and tok.endswith("s") and not tok.endswith("ss") else tok)
    return out


def _git(root: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(root), *args], check=True, capture_output=True, text=True).stdout


def _blob_sha(data: bytes) -> str:
    return hashlib.sha1(b"blob %d\0" % len(data) + data).hexdigest()


def tracked_sources(root: Path) -> dict[str, str]:
    """Map repo-relative path -> git blob hash of its working-tree content."""
    files: dict[str, str] = {}
    for record in _git(root, "ls-files", "-s", "-z", "--", *ROOTS).split("\0"):
        if "\t" not in record:
            continue
        meta, path = record.split("\t", 1)
        if Path(path).suffix in EXTS and not is_test_or_generated(path):
            files[path] = meta.split()[1]
    for path in _git(root, "diff", "--name-only", "-z", "HEAD", "--", *ROOTS).split("\0"):
        if path not in files:
            continue
        target = root / path
        if target.is_file():
            files[path] = _blob_sha(target.read_bytes())
        else:
            del files[path]
    return files


def _salient(lines: list[str]) -> list[str]:
    picked = []
    for line in lines:
        text = line.strip()
        if 8 <= len(text) <= 200 and (COMMENT_RE.match(line) or DEF_RE.match(line)):
            picked.append(text[:160])
            if len(picked) >= SALIENT_LINES:
                break
    return picked


def analyze(path: Path) -> dict | None:
    """Index entry for one file, or None when it is too large or not text."""
    if path.stat().st_size > MAX_BYTES or not code_map._is_text(path):
        return None
    lines = code_map._read_lines(path)
    symbols = [label.split(" ", 1)[-1].split("(")[0].strip()
               for _, label in code_map.definitions(path, lines) if not label.startswith(" ")][:40]
    counts = Counter(tokenize("\n".join(lines)))
    return {"doc": code_map._first_comment(lines), "symbols": symbols, "salient": _salient(lines),
            "terms": dict(counts), "length": sum(counts.values())}


def load_index(root: Path, cache_dir: Path | None = None) -> list[dict]:
    """Rows (path + entry) for every indexed file of `root`; refreshes the shared cache."""
    cache_dir = cache_dir or CACHE_DIR
    cache_dir.mkdir(parents=True, exist_ok=True)
    cache_file = cache_dir / "entries-v1.json.gz"
    files = tracked_sources(root)
    today = time.strftime("%Y-%m-%d", time.gmtime())
    with open(cache_dir / "entries.lock", "w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        cache = json.loads(gzip.decompress(cache_file.read_bytes())) if cache_file.exists() else {}
        entries, used = cache.get("entries", {}), cache.get("used", {})
        missing = [(p, s) for p, s in files.items() if s not in entries]
        if len(missing) > 200:
            print(f"code_locate: indexing {len(missing)} files (first run takes about a minute)", file=sys.stderr)
        for path, sha in missing:
            try:
                entries[sha] = analyze(root / path)
            except (OSError, UnicodeDecodeError):
                entries[sha] = None
        stale = [s for s in files.values() if used.get(s) != today]
        if missing or stale:
            for sha in files.values():
                used[sha] = today
            cutoff = time.strftime("%Y-%m-%d", time.gmtime(time.time() - CACHE_KEEP_DAYS * 86400))
            keep = {s for s, day in used.items() if day >= cutoff}
            tmp = cache_file.with_suffix(f".{os.getpid()}.tmp")
            tmp.write_bytes(gzip.compress(json.dumps({
                "entries": {s: e for s, e in entries.items() if s in keep},
                "used": {s: d for s, d in used.items() if s in keep}}).encode(), compresslevel=3))
            os.replace(tmp, cache_file)
    return [{"path": p, **entries[s]} for p, s in sorted(files.items()) if entries.get(s)]


class Retriever:
    """BM25 over path, doc+symbols and content; field scores are weighted and summed."""

    WEIGHTS = {"path": 3.0, "meta": 2.0, "content": 1.0}

    def __init__(self, rows: list[dict]) -> None:
        self.rows = rows
        self.n = len(rows)
        self.content: dict[str, list[tuple[int, int]]] = defaultdict(list)
        self.fields: dict[str, dict[str, list[int]]] = {"path": defaultdict(list), "meta": defaultdict(list)}
        for doc, row in enumerate(rows):
            for term, tf in row["terms"].items():
                self.content[term].append((doc, tf))
            for term in set(tokenize(row["path"])):
                self.fields["path"][term].append(doc)
            for term in set(tokenize(row["doc"] + " " + " ".join(row["symbols"]))):
                self.fields["meta"][term].append(doc)
        self.avg_len = sum(r["length"] for r in rows) / max(1, self.n)

    def _idf(self, df: int) -> float:
        return math.log(1 + (self.n - df + 0.5) / (df + 0.5))

    def search(self, query: str, k: int) -> list[int]:
        total: dict[int, float] = defaultdict(float)
        k1, b = 1.2, 0.75
        for term in set(tokenize(query)):
            post = self.content.get(term)
            if post:
                idf = self._idf(len(post))
                for doc, tf in post:
                    norm = tf * (k1 + 1) / (tf + k1 * (1 - b + b * self.rows[doc]["length"] / self.avg_len))
                    total[doc] += self.WEIGHTS["content"] * idf * norm
            for field in ("path", "meta"):
                docs = self.fields[field].get(term)
                if docs:
                    idf = self._idf(len(docs))
                    for doc in docs:
                        total[doc] += self.WEIGHTS[field] * idf
        return [doc for doc, _ in sorted(total.items(), key=lambda item: -item[1])[:k]]


def clauses(query: str) -> list[str]:
    """Split a multi-part task sentence into clauses worth their own search."""
    parts = [p.strip() for p in re.split(r";|,|\band\b|\bplus\b", query)]
    return [p for p in parts if len(tokenize(p)) >= 2]


def retrieve(retriever: Retriever, query: str, k: int) -> list[int]:
    """Full-query ranking fused with one ranking per clause (reciprocal rank fusion)."""
    runs = [retriever.search(query, 4 * k)]
    parts = clauses(query)
    if len(parts) > 1:
        runs += [retriever.search(part, 2 * k) for part in parts]
    fused: dict[int, float] = defaultdict(float)
    for weight, run in zip([2.0] + [1.0] * (len(runs) - 1), runs):
        for rank, doc in enumerate(run):
            fused[doc] += weight / (30 + rank + 1)
    return [doc for doc, _ in sorted(fused.items(), key=lambda item: -item[1])[:k]]


def matching_lines(row: dict, query: str, limit: int = 3) -> list[str]:
    terms = set(tokenize(query))
    scored = [(len(terms & set(tokenize(line))), line) for line in row["salient"]]
    return [line for overlap, line in sorted(scored, key=lambda item: -item[0])[:limit] if overlap]


def candidate_view(row: dict, query: str) -> dict:
    """What Jev sees per file: path, summary, symbols and the lines that best match the task."""
    return {"path": row["path"], "summary": row["doc"][:160], "symbols": row["symbols"][:10],
            "matching_lines": matching_lines(row, query)}


def fuse(paths: list[str], scores: dict[str, float]) -> list[str]:
    """Order by Jev score plus a small prior for a high search rank."""
    rank = {p: i for i, p in enumerate(paths)}
    return sorted(paths, key=lambda p: -(scores.get(p, 0.0) + RANK_BONUS * 4 / (1 + rank[p] / 5)))


def confidence(top_score: float) -> str:
    """Measured: top score >= 3.5 -> target in top 5 for 92%; < 3 -> 58%."""
    return "high" if top_score >= 3.5 else "medium" if top_score >= 3.0 else "low"


def locate(query: str, root: Path, *, k: int = DEFAULT_K, top: int = 5, use_jev: bool = True,
           jev_score=None) -> dict:
    """Return ranked files with mode, confidence and cost; never raises on a Jev problem."""
    started = time.perf_counter()
    rows = load_index(root)
    retriever = Retriever(rows)
    candidates = [rows[d] for d in retrieve(retriever, query, k)]
    paths = [r["path"] for r in candidates]
    result = {"query": query, "mode": "search", "reason": "jev disabled" if not use_jev else "",
              "files": [], "confidence": None, "input_tokens": 0, "usd": 0.0}
    order, scores = paths, {}
    if use_jev and candidates:
        if jev_score is None:
            import code_locate_jev
            jev_score = code_locate_jev.score
        outcome = jev_score(query, [candidate_view(r, query) for r in candidates])
        result.update(input_tokens=outcome.get("input_tokens", 0), usd=outcome.get("usd", 0.0))
        if outcome.get("scores"):
            scores = outcome["scores"]
            order = fuse(paths, scores)
            result.update(mode="jev", confidence=confidence(max(scores.values())))
        else:
            result["reason"] = outcome.get("fallback", "jev unavailable")
        result["budget"] = outcome.get("budget")
    by_path = {r["path"]: r for r in candidates}
    for path in order[:top]:
        summary = by_path[path]["doc"][:120]
        summary = "" if path in summary else summary
        lines = [ln for ln in matching_lines(by_path[path], query, 2) if path not in ln and ln[:60] not in summary]
        result["files"].append({"path": path, "score": scores.get(path), "summary": summary,
                                "line": lines[0] if lines else ""})
    result["latency_ms"] = round((time.perf_counter() - started) * 1000)
    return result


def format_result(result: dict) -> str:
    out = [f'Files for: "{result["query"]}"']
    for i, item in enumerate(result["files"], 1):
        score = f"  (Jev {item['score']:.1f})" if item["score"] is not None else ""
        out.append(f"{i}. {item['path']}{score}")
        if item["summary"]:
            out.append(f"     {item['summary']}")
        if item["line"]:
            out.append(f"     > {item['line'][:140]}")
    if not result["files"]:
        out.append("No matching files. Rephrase with the area and concrete names, or grep.")
    if result["mode"] == "jev":
        note = {"high": "high", "medium": "medium: check the top files first",
                "low": "low: guesses only, confirm with grep before relying on them"}[result["confidence"]]
        out.append(f"Confidence: {note}")
    else:
        out.append(f"Ranking: local search only ({result['reason']}); confirm with grep.")
    budget = result.get("budget")
    if budget:
        out.append(f"Jev today: USD {budget["spent_usd"]:.4f} of {budget["cap_usd"]:g}")
    return "\n".join(out)
