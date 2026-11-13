#!/usr/bin/env python3
"""Compact code maps for agents: file outline and directory overview.

Usage:
  code_map.py outline <file>
  code_map.py dir <path> [--depth N]
  code_map.py find "<area>: <what changes>" [--no-jev] [--top N] [--json]
  code_map.py find-report [--days N]

`find` ranks the files a task most likely touches (local search, then Jev with a
daily cost cap; see code_locate.py). Write a focused query naming the area and
concrete behaviour, not the user's raw message.

Python files use ``ast``; other languages use conservative line regexes.
Output is capped so it is cheap to read instead of whole files.
"""

from __future__ import annotations

import argparse
import ast
import re
import sys
from pathlib import Path

OUTLINE_MAX_LINES = 120
DIR_MAX_LINES = 200
SKIP_DIRS = {
    "node_modules", "target", ".git", "generated", "build", "dist", ".svelte-kit",
    "__pycache__", ".venv", "venv", ".next", "coverage", ".openmates-agent-worktrees",
}
SOURCE_EXTS = {
    ".py", ".rs", ".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs", ".svelte",
    ".swift", ".sh", ".bash",
}
TS_EXTS = {".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs", ".svelte"}

_RUST = re.compile(
    r"^(\s*)(?:pub(?:\([^)]*\))?\s+)?(?:async\s+|unsafe\s+|const\s+)*"
    r"(fn|struct|enum|impl|trait|mod|type)\b\s*([A-Za-z_<][\w:<>, ]*)?"
)
_TS = re.compile(
    r"^(\s*)(?:export\s+)?(?:default\s+)?(?:declare\s+)?(?:abstract\s+)?(?:async\s+)?"
    r"(class|function\*?|interface|type|enum|namespace)\s+([A-Za-z_$][\w$]*)"
)
_TS_CONST = re.compile(r"^(\s*)export\s+(?:const|let)\s+([A-Za-z_$][\w$]*)")
_SWIFT = re.compile(
    r"^(\s*)(?:(?:public|private|fileprivate|internal|open|final|static|override|"
    r"mutating|@\w+(?:\([^)]*\))?)\s+)*"
    r"(func|class|struct|enum|extension|protocol|actor)\s+([A-Za-z_][\w.]*)"
)
_SHELL = re.compile(r"^(?:function\s+)?([A-Za-z_][\w-]*)\s*\(\)\s*\{?|^function\s+([A-Za-z_][\w-]*)")


def _read_lines(path: Path) -> list[str]:
    return path.read_text(encoding="utf-8", errors="replace").splitlines()


def _python_defs(text: str) -> list[tuple[int, str]]:
    tree = ast.parse(text)
    out: list[tuple[int, str]] = []

    def visit(nodes: list[ast.stmt], depth: int) -> None:
        for node in nodes:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                if isinstance(node, ast.ClassDef):
                    kind = "class"
                elif isinstance(node, ast.AsyncFunctionDef):
                    kind = "async def"
                else:
                    kind = "def"
                out.append((node.lineno, f"{'  ' * depth}{kind} {node.name}"))
                if isinstance(node, ast.ClassDef):
                    visit(node.body, depth + 1)

    visit(tree.body, 0)
    return out


def _match_line(line: str, suffix: str) -> tuple[str, int] | None:
    """Return (label, indent width) when the line is a definition."""
    if suffix == ".rs":
        m = _RUST.match(line)
        if m:
            return f"{m.group(2)} {(m.group(3) or '').strip()}".strip(), len(m.group(1))
    elif suffix in TS_EXTS:
        m = _TS.match(line)
        if m:
            return f"{m.group(2)} {m.group(3)}", len(m.group(1))
        m = _TS_CONST.match(line)
        if m:
            return f"export {m.group(2)}", len(m.group(1))
    elif suffix == ".swift":
        m = _SWIFT.match(line)
        if m:
            return f"{m.group(2)} {m.group(3)}", len(m.group(1))
    elif suffix in {".sh", ".bash"}:
        m = _SHELL.match(line)
        if m:
            return f"function {m.group(1) or m.group(2)}", 0
    return None


def _regex_defs(lines: list[str], suffix: str) -> list[tuple[int, str]]:
    out: list[tuple[int, str]] = []
    for number, line in enumerate(lines, 1):
        if len(line) > 300:
            continue
        found = _match_line(line, suffix)
        if found and found[1] <= 8:
            out.append((number, f"{'  ' * (found[1] // 4)}{found[0]}"))
    return out


def _svelte_script_bounds(lines: list[str]) -> list[tuple[int, int]]:
    bounds: list[tuple[int, int]] = []
    start = None
    for number, line in enumerate(lines, 1):
        if start is None and re.match(r"\s*<script\b", line):
            start = number
        if start is not None and "</script>" in line:
            bounds.append((start, number))
            start = None
    return bounds


def definitions(path: Path, lines: list[str]) -> list[tuple[int, str]]:
    suffix = path.suffix.lower()
    if suffix == ".py":
        try:
            return _python_defs("\n".join(lines))
        except SyntaxError:
            return []
    defs = _regex_defs(lines, suffix)
    if suffix == ".svelte":
        bounds = _svelte_script_bounds(lines)
        defs = [d for d in defs if any(a <= d[0] <= b for a, b in bounds)]
    return defs


def outline(path: Path) -> str:
    lines = _read_lines(path)
    defs = definitions(path, lines)
    out = [f"{path.name}: {len(lines)} lines"]
    shown = defs[: OUTLINE_MAX_LINES - 1]
    out.extend(f"{number}: {label}" for number, label in shown)
    if len(defs) > len(shown):
        out.append(f"... {len(defs) - len(shown)} more")
    return "\n".join(out)


def _first_comment(lines: list[str]) -> str:
    skip = {'"""', "'''", "/*", "/**", "<script>", "---"}
    for line in lines[:30]:
        s = line.strip()
        if not s or s.startswith("#!") or s in skip:
            continue
        for prefix in ('"""', "'''", "//!", "///", "//", "/**", "/*", "#", "*"):
            if s.startswith(prefix):
                s = s[len(prefix):].strip(" \"'*/")
                return s[:100] if s else ""
        return ""
    return ""


def _top_symbols(path: Path, lines: list[str]) -> list[str]:
    names: list[str] = []
    for _, label in definitions(path, lines):
        if label.startswith(" "):
            continue
        names.append(label.split(" ", 1)[-1].split("(")[0].strip())
        if len(names) >= 6:
            break
    return names


def _is_text(path: Path) -> bool:
    try:
        with path.open("rb") as handle:
            return b"\0" not in handle.read(2048)
    except OSError:
        return False


def _walk(root: Path, depth: int, level: int = 0):
    try:
        entries = sorted(root.iterdir(), key=lambda p: (p.is_dir(), p.name))
    except OSError:
        return
    for entry in entries:
        if entry.is_dir():
            if entry.name in SKIP_DIRS or entry.name.startswith(".") or level + 1 >= depth:
                continue
            yield from _walk(entry, depth, level + 1)
        elif entry.suffix.lower() in SOURCE_EXTS:
            yield entry


def dir_map(root: Path, depth: int) -> str:
    out: list[str] = []
    files = list(_walk(root, depth))
    for entry in files:
        if len(out) >= DIR_MAX_LINES - 1:
            out.append(f"... {len(files) - len(out)} more files; narrow the path")
            break
        if not _is_text(entry):
            continue
        lines = _read_lines(entry)
        symbols = ", ".join(_top_symbols(entry, lines))
        doc = _first_comment(lines)
        rel = entry.relative_to(root)
        out.append(f"{rel} ({len(lines)}) {doc} | {symbols}".rstrip(" |"))
    return "\n".join(out) if out else f"{root}: no source files found"


def _find(args) -> int:
    """`find` and `find-report`; imported lazily so outline/dir stay dependency-free."""
    import json
    import os
    import subprocess
    import time

    import code_locate
    import code_locate_jev

    if args.cmd == "find-report":
        print(code_locate_jev.report(args.days))
        return 0
    top = subprocess.run(["git", "rev-parse", "--show-toplevel"], capture_output=True, text=True, check=False)
    root = Path(top.stdout.strip()) if top.returncode == 0 else Path(__file__).resolve().parents[1]
    query = " ".join(args.query).strip()
    result = code_locate.locate(query, root, top=max(1, args.top), use_jev=not args.no_jev)
    code_locate_jev.log_usage({
        "ts": time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime()), "chat": os.environ.get("CLAUDE_CODE_SESSION_ID", ""),
        "root": str(root), "query": query, "mode": result["mode"], "reason": result["reason"],
        "files": [f["path"] for f in result["files"]], "scores": [f["score"] for f in result["files"]],
        "confidence": result["confidence"], "input_tokens": result["input_tokens"], "usd": result["usd"],
        "latency_ms": result["latency_ms"]})
    print(json.dumps(result, indent=1) if args.json else code_locate.format_result(result))
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="cmd", required=True)
    p_out = sub.add_parser("outline")
    p_out.add_argument("file")
    p_dir = sub.add_parser("dir")
    p_dir.add_argument("path")
    p_dir.add_argument("--depth", type=int, default=2)
    p_find = sub.add_parser("find", help="rank the files a coding task most likely touches")
    p_find.add_argument("query", nargs="+")
    p_find.add_argument("--no-jev", action="store_true", help="local search only (free, offline)")
    p_find.add_argument("--top", type=int, default=5)
    p_find.add_argument("--json", action="store_true")
    p_rep = sub.add_parser("find-report", help="summarize find usage, Jev spend and hit evidence")
    p_rep.add_argument("--days", type=int, default=7)
    args = parser.parse_args(argv)
    if args.cmd in ("find", "find-report"):
        return _find(args)
    if args.cmd == "outline":
        path = Path(args.file)
        if not path.is_file():
            print(f"not a file: {path}", file=sys.stderr)
            return 1
        print(outline(path))
    else:
        path = Path(args.path)
        if not path.is_dir():
            print(f"not a directory: {path}", file=sys.stderr)
            return 1
        print(dir_map(path, max(1, args.depth)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
