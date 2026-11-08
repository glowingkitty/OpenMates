#!/usr/bin/env python3
"""Honest web-app Rust progress: TS code lines that route to shared Rust under the flag.

The web app is "done" when its portable TypeScript logic runs in the shared Rust core
Worker behind VITE_OPENMATES_RUST_CORE. Counting installed Worker namespaces says
nothing about that, so this module measures area instead:

  denominator = code lines of the portable TS under docs/migration/rust/web-port-ledger.yml
                `scope` (services/, utils/, stores/ minus the bridge and the listed
                non-portable files, each with a reason)
  numerator   = code lines of the TS functions the ledger lists, each of which must
                actually route to Rust under the flag (see `routing_functions`).

A function "routes" when its body (comments stripped) reads the flag
(import.meta.env.VITE_OPENMATES_RUST_CORE), a flag constant derived from it in the
same file or exported by another file, or a value imported from a Rust bridge module
(services/rustCore/**, *Rust.ts). Every routing function in scope must be in exactly
one ledger slice and every ledger function must route, so the ledger can neither
under- nor over-claim. `twins` are flag-off TS helpers without a flag read that a
ledgered routing function of the same slice calls; they count too.

Code line = non-blank line that is not only a comment. Function extents assume the
repo's formatted TS: a block ends at the first later line with the same indentation
that starts with a closing brace.

  python3 scripts/rust_web_port_ledger.py --suggest   # print YAML stubs for unledgered routing functions

Used by scripts/rust_migration_yaml.py (web-app.yml port_ledger, overview web_app area).
Architecture: docs/architecture/platforms/rust-migration-status.md
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from collections import defaultdict
from dataclasses import dataclass, field
from fnmatch import fnmatch
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
LEDGER = Path("docs/migration/rust/web-port-ledger.yml")
SCHEMA_VERSION = 1
FLAG = "VITE_OPENMATES_RUST_CORE"
PROOFS = ("e2e-flag-on", "vectors", "none")
HEX_COMMIT = re.compile(r"^[0-9a-f]{7,40}$")
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
IDENT = r"[A-Za-z_$][\w$]*"
KEYWORDS = {"if", "for", "while", "switch", "catch", "return", "function", "await", "typeof", "new", "else",
            "do", "try", "with", "super", "import", "export", "throw", "case", "void", "delete", "in", "of", "async"}
FUNC_RES = (
    re.compile(rf"^(?:export\s+)?(?:default\s+)?(?:async\s+)?function\s*\*?\s*({IDENT})\s*[<(]"),
    re.compile(rf"^(?:export\s+)?(?:const|let|var)\s+({IDENT})\s*(?::[^=]*)?=\s*(?:async\b\s*)?(?:function\b|\(|<|{IDENT}\s*=>)"),
    re.compile(rf"^(?:(?:public|private|protected|static|async|override|readonly|get|set)\s+)*({IDENT})\s*(?:<[^>]*>)?\s*\("),
    re.compile(rf"^(?:(?:public|private|protected|static|readonly)\s+)*({IDENT})\s*(?::[^=]*)?=\s*(?:async\b\s*)?(?:function\b|\(|{IDENT}\s*=>)"),
    re.compile(rf"^({IDENT})\s*:\s*(?:async\b\s*)?(?:function\b|\()"),
)
# A line that closes a declaration block: `}`, `};`, `});`, `},`, `})();` (not `}> {` of a return type).
BLOCK_CLOSE = re.compile(r"^\}[)\];,\s]*(?:\(\))?[)\];,\s]*$")
IMPORT_RE =re.compile(r"import\s+(type\s+)?(?:(" + IDENT + r")\s*,?\s*)?(?:\{([^}]*)\})?\s*from\s*['\"]([^'\"]+)['\"]", re.S)


# --- source model -------------------------------------------------------------------


def strip_comments(text: str, blank_strings: bool = False) -> list[str]:
    """Lines with // and /* */ comments removed; with blank_strings, string/template contents too
    (so a log message that mentions "logout" is not a read of a `logout` marker)."""
    out, in_block = [], False
    quote = None
    for line in text.splitlines():
        result, i = [], 0
        if quote != "`":
            quote = None
        while i < len(line):
            two = line[i:i + 2]
            if in_block:
                if two == "*/":
                    in_block, i = False, i + 2
                    continue
                i += 1
                continue
            ch = line[i]
            if quote:
                if ch == "\\" and i + 1 < len(line):
                    result.append("  " if blank_strings else line[i:i + 2])
                    i += 2
                    continue
                if ch == quote:
                    quote = None
                    result.append(ch)
                else:
                    result.append(" " if blank_strings else ch)
                i += 1
                continue
            if ch in "'\"`":
                quote = ch
            elif two == "//":
                break
            elif two == "/*":
                in_block, i = True, i + 2
                continue
            result.append(ch)
            i += 1
        out.append("".join(result))
    return out


def is_code_line(line: str) -> bool:
    s = line.strip()
    return bool(s) and not s.startswith(("//", "/*", "*", "*/"))


@dataclass
class Function:
    name: str
    qualified: str
    start: int  # 0-based, inclusive
    end: int  # 0-based, inclusive
    markers: list[int] = field(default_factory=list)  # lines that read the flag or a bridge value


@dataclass
class SourceFile:
    path: str
    raw: list[str]
    code: list[str]  # comment-stripped (strings kept: import specifiers)
    bare: list[str]  # comment- and string-stripped (identifier reads, braces)
    functions: list[Function] = field(default_factory=list)

    def code_lines(self, lines: set[int] | None = None) -> int:
        rng = range(len(self.raw)) if lines is None else lines
        return sum(1 for i in rng if is_code_line(self.raw[i]))


def _function_start(stripped: str, nested: bool) -> str | None:
    """Declared name, or None. Inside another function only `function`/`const` forms count:
    there `name(...) {` is a call with a callback (setTimeout(() => {), not a method."""
    for index, regex in enumerate(FUNC_RES):
        if nested and index >= 2:
            break
        m = regex.match(stripped)
        if m and m.group(1) not in KEYWORDS:
            return m.group(1)
    return None


def extract_functions(code: list[str]) -> list[Function]:
    found: list[tuple[str, int, int]] = []
    for i, line in enumerate(code):
        stripped = line.strip()
        name = _function_start(stripped, any(s < i <= e for _, s, e in found))
        if not name:
            continue
        indent = line[: len(line) - len(line.lstrip())]
        header = " ".join(code[i:i + 8])
        if "=>" not in header and "function" not in header and "{" not in header:
            continue
        end = i
        if not (stripped.endswith(";") and "{" not in stripped):
            for j in range(i + 1, len(code)):
                other = code[j]
                if other.strip() and other[: len(other) - len(other.lstrip())] == indent and BLOCK_CLOSE.match(other.strip()):
                    end = j
                    break
                if other.strip() and len(other) - len(other.lstrip()) < len(indent):
                    break
        if stripped.endswith(";") and "=>" not in stripped and "{" not in stripped:
            continue  # overload signature or declaration without a body
        if end == i and not stripped.endswith(("{", ";")) and "=>" not in stripped:
            continue  # a call or expression, not a declaration
        if end == i and stripped.endswith("{"):
            continue  # unterminated block: not a function we can measure
        found.append((name, i, end))
    functions: list[Function] = []
    for name, start, end in found:
        parents = [n for n, s, e in found if s < start and e >= end and (s, e) != (start, end)]
        functions.append(Function(name, ".".join(parents + [name]), start, end))
    return functions


def load_source(path: str) -> SourceFile:
    text = (ROOT / path).read_text(encoding="utf-8")
    src = SourceFile(path, text.splitlines(), strip_comments(text), strip_comments(text, blank_strings=True))
    src.functions = extract_functions(src.bare)
    return src


def innermost(src: SourceFile, line: int) -> Function | None:
    best = None
    for fn in src.functions:
        if fn.start <= line <= fn.end and (best is None or fn.end - fn.start < best.end - best.start):
            best = fn
    return best


def find_function(src: SourceFile, name: str) -> list[Function]:
    return [f for f in src.functions if f.qualified == name or f.name == name and "." not in name]


# --- scope ----------------------------------------------------------------------------


def load_ledger(path: Path | None = None) -> dict:
    return yaml.safe_load((path or ROOT / LEDGER).read_text(encoding="utf-8"))


def scope_files(ledger: dict) -> tuple[list[str], list[str], list[str]]:
    """(portable, non_portable, bridge) repo-relative TS paths under the scope roots."""
    scope = ledger["scope"]
    excluded = [e["glob"] for e in scope["excluded"]]
    bridge_globs = [e["glob"] for e in scope["bridge"]]
    non_portable = [e["glob"] for e in ledger["non_portable"]]
    portable, np, bridge = [], [], []
    for root in scope["roots"]:
        for p in sorted((ROOT / root).rglob("*.ts")):
            rel = p.relative_to(ROOT).as_posix()
            if any(fnmatch(rel, g) for g in excluded):
                continue
            if any(fnmatch(rel, g) for g in bridge_globs):
                bridge.append(rel)
            elif any(fnmatch(rel, g) for g in non_portable):
                np.append(rel)
            else:
                portable.append(rel)
    return portable, np, bridge


def resolve_import(from_path: str, spec: str) -> str | None:
    if not spec.startswith("."):
        return None
    base = (ROOT / from_path).parent / spec
    for candidate in (base.with_name(base.name + ".ts"), base / "index.ts", base):
        if candidate.is_file() and candidate.suffix == ".ts":
            return candidate.resolve().relative_to(ROOT).as_posix()
    return None


def _imports(src: SourceFile) -> list[tuple[str, list[str]]]:
    text = "\n".join(src.code)
    out = []
    for m in IMPORT_RE.finditer(text):
        if m.group(1):
            continue
        names = [m.group(2)] if m.group(2) else []
        for spec in (m.group(3) or "").split(","):
            spec = spec.strip()
            if not spec or spec.startswith("type "):
                continue
            names.append(spec.split(" as ")[-1].strip())
        out.append((m.group(4), [n for n in names if n]))
    return out


def module_flag_constants(src: SourceFile, seeds: set[str]) -> set[str]:
    """Module-level identifiers whose initializer reads the flag or another marker (fixpoint)."""
    markers = set(seeds)
    # Function bodies (and function-valued consts) are not flag constants.
    inside = {i for fn in src.functions for i in range(fn.start, fn.end + 1)}
    decl = re.compile(rf"^(?:export\s+)?(?:const|let|var)\s+({IDENT})")  # column 0 = module level
    changed = True
    while changed:
        changed = False
        for i, line in enumerate(src.bare):
            m = decl.match(line)
            if not m or i in inside or m.group(1) in markers:
                continue
            stmt = line
            j = i
            while not stmt.rstrip().endswith(";") and j + 1 < len(src.bare) and j - i < 6:
                j += 1
                stmt += " " + src.bare[j]
            rhs = stmt.split("=", 1)[1] if "=" in stmt else ""
            if FLAG in rhs or any(re.search(rf"\b{re.escape(k)}\b", rhs) for k in markers - {FLAG}):
                markers.add(m.group(1))
                changed = True
    return markers


DYNAMIC_IMPORT = re.compile(r"import\(\s*['\"]([^'\"]+)['\"]\s*\)")


def lazy_bridge_loaders(src: SourceFile, bridge: set[str]) -> set[str]:
    """Functions whose body dynamically imports a bridge module (`() => import('./rustCore/...')`), and
    one-to-three-line flag helpers (`function flagOn() { return import.meta.env... === '1'; }`)."""
    def small(fn: Function, limit: int) -> bool:
        return src.code_lines(set(range(fn.start, fn.end + 1))) <= limit

    names = {fn.name for fn in src.functions if small(fn, 3) and any(FLAG in src.code[i] for i in range(fn.start, fn.end + 1))}
    for i, line in enumerate(src.code):
        for spec in DYNAMIC_IMPORT.findall(line):
            fn = innermost(src, i)
            # Only dedicated loaders; a long function with an inline import() is a routing site, not a loader.
            if fn is not None and small(fn, 6) and resolve_import(src.path, spec) in bridge:
                names.add(fn.name)
    return names


def exported_flag_constants(sources: dict[str, SourceFile], bridge: set[str]) -> dict[str, set[str]]:
    """Per file: exported flag constants and exported lazy bridge loaders other files may import."""
    out = {}
    for path, src in sources.items():
        names = module_flag_constants(src, {FLAG} | lazy_bridge_loaders(src, bridge)) - {FLAG}
        exported = {n for n in names if any(re.match(rf"^\s*export\s+(?:const|let|var|(?:async\s+)?function)\s+{re.escape(n)}\b", line) for line in src.code)}
        if exported:
            out[path] = exported
    return out


def file_markers(src: SourceFile, bridge: set[str], exported: dict[str, set[str]]) -> set[str]:
    seeds = {FLAG} | lazy_bridge_loaders(src, bridge)
    for spec, names in _imports(src):
        target = resolve_import(src.path, spec)
        if target in bridge:
            seeds.update(names)
        elif target in exported:
            seeds.update(n for n in names if n in exported[target])
    return module_flag_constants(src, seeds)


def routing_functions(src: SourceFile, markers: set[str], bridge: set[str]) -> dict[str, Function]:
    """Innermost named function around every marker read or inline bridge import(), by qualified name."""
    names = sorted(m for m in markers if m != FLAG)
    words = [(m, re.compile(rf"(?<![\w$.]){re.escape(m)}(?![\w$])")) for m in names]
    glue = lazy_bridge_loaders(src, bridge)  # loaders and flag helpers are bridge glue, not ported logic
    out: dict[str, Function] = {}
    for i, line in enumerate(src.bare):
        hits = [m for m, w in words if w.search(line)]
        inline_bridge = any(resolve_import(src.path, s) in bridge for s in DYNAMIC_IMPORT.findall(src.code[i]))
        if FLAG not in line and not hits and not inline_bridge:
            continue
        fn = innermost(src, i)
        if fn is None or fn.name in glue:
            continue
        if fn.start == i and FLAG not in line and not inline_bridge and hits == [fn.name]:
            continue  # the declaration of a lazy loader or flag helper names itself
        out.setdefault(fn.qualified, fn).markers.append(i)
    return out


def _block_end(code: list[str], i: int, limit: int) -> int:
    """Last line of the statement or block that starts at line i (bounded by limit)."""
    line = code[i]
    indent = line[: len(line) - len(line.lstrip())]
    stripped = line.rstrip()
    if stripped.endswith(("{", "(", "[")):
        for j in range(i + 1, limit + 1):
            other = code[j]
            if other.strip() and other[: len(other) - len(other.lstrip())] == indent and other.strip()[0] in "})]":
                if re.match(r"^\s*\}\s*(?:else|catch|finally)\b.*\{\s*$", other):
                    return _block_end(code, j, limit)
                return j
        return limit
    j = i
    while j < limit and not code[j].rstrip().endswith((";", "{", "}")) and j - i < 15:
        j += 1
    return j


def claimed_lines(src: SourceFile, fn: Function, full_max: int) -> tuple[set[int], bool]:
    """(lines, full): whole function up to full_max code lines, else only its flag decision sites."""
    whole = set(range(fn.start, fn.end + 1))
    if src.code_lines(whole) <= full_max or not fn.markers:
        return whole, True
    sites: set[int] = set()
    for i in fn.markers:
        sites.update(range(i, _block_end(src.bare, i, fn.end) + 1))
    return sites, False


# --- measurement ------------------------------------------------------------------------


@dataclass
class Model:
    ledger: dict
    portable: list[str]
    non_portable: list[str]
    bridge: list[str]
    sources: dict[str, SourceFile]
    routing: dict[str, dict[str, Function]]
    ledgered_bodies: dict[tuple[str, str], str] = field(default_factory=dict)  # (file, qualified) -> code


def _ledgered_bodies(model: Model) -> dict[tuple[str, str], str]:
    out = {}
    for sl in model.ledger["slices"]:
        for item in sl.get("ts", []):
            src = model.sources.get(item["file"])
            if src is None:
                continue
            for name in item.get("functions", []) + item.get("twins", []):
                for fn in find_function(src, name):
                    out[(src.path, fn.qualified)] = "\n".join(src.bare[fn.start:fn.end + 1])
    return out


def build_model(ledger: dict) -> Model:
    portable, non_portable, bridge = scope_files(ledger)
    sources = {p: load_source(p) for p in portable + non_portable + bridge}
    bridge_set = set(bridge)
    exported = exported_flag_constants(sources, bridge_set)
    routing = {}
    for path in portable:
        found = routing_functions(sources[path], file_markers(sources[path], bridge_set, exported), bridge_set)
        if found:
            routing[path] = found
    model = Model(ledger, portable, non_portable, bridge, sources, routing)
    model.ledgered_bodies = _ledgered_bodies(model)
    return model


def proof_level(slice_: dict) -> str:
    if slice_.get("e2e"):
        return "e2e-flag-on"
    return "vectors" if slice_.get("vectors") else "none"


def _slice_lines(model: Model, slice_: dict, errors: list[str]) -> tuple[dict[str, set[int]], int]:
    """(lines per file claimed by a slice, functions counted at decision sites only); appends errors."""
    label = f"{LEDGER.name} slice {slice_.get('id', '?')}"
    full_max = model.ledger["counting"]["full_function_max_code_lines"]
    claimed: dict[str, set[int]] = defaultdict(set)
    partial = 0
    for item in slice_.get("ts", []):
        path = item["file"]
        if path not in model.sources or path not in model.portable:
            errors.append(f"{label}: {path} is not a portable scope file")
            continue
        src = model.sources[path]
        routing = model.routing.get(path, {})
        for kind in ("functions", "twins"):
            for name in item.get(kind, []):
                matches = find_function(src, name)
                if len(matches) != 1:
                    errors.append(f"{label}: {path} {kind[:-1]} {name} " + ("not found" if not matches else "is ambiguous; use the qualified name " + ", ".join(m.qualified for m in matches)))
                    continue
                fn = matches[0]
                if kind == "functions" and fn.qualified not in routing:
                    errors.append(f"{label}: {path} {name} does not route to Rust under the flag (no flag or bridge read in its body)")
                    continue
                call = re.compile(rf"(?<![\w$.]){re.escape(fn.name)}\s*\(|\.{re.escape(fn.name)}\s*\(")
                if kind == "twins" and not any(call.search(body) for key, body in model.ledgered_bodies.items() if key != (path, fn.qualified)):
                    errors.append(f"{label}: {path} twin {name} is not called by any ledgered function or twin")
                    continue
                fn = routing.get(fn.qualified, fn)
                rows, full = claimed_lines(src, fn, full_max)
                partial += 0 if full else 1
                claimed[path].update(rows)
    return claimed, partial


def measure(model: Model) -> tuple[dict, list[str]]:
    """Summary for web-app.yml plus validation errors."""
    ledger, errors = model.ledger, []
    if ledger.get("schema_version") != SCHEMA_VERSION:
        errors.append(f"{LEDGER.name}: schema_version must be {SCHEMA_VERSION}")
    for entry in ledger["non_portable"]:
        if not str(entry.get("reason", "")).strip():
            errors.append(f"{LEDGER.name}: non_portable {entry.get('glob')} needs a reason")
        if not any(fnmatch(p, entry["glob"]) for p in model.non_portable):
            errors.append(f"{LEDGER.name}: non_portable {entry['glob']} matches no scope file (moved or deleted?)")
    ids = [s.get("id") for s in ledger["slices"]]
    if len(set(ids)) != len(ids):
        errors.append(f"{LEDGER.name}: slice ids must be unique")
    owner: dict[tuple[str, str], str] = {}
    union: dict[str, set[int]] = defaultdict(set)
    by_proof: dict[str, set[tuple[str, int]]] = {p: set() for p in PROOFS}
    slices_out = []
    partial_total = 0
    for sl in ledger["slices"]:
        label = f"{LEDGER.name} slice {sl.get('id', '?')}"
        commit = sl.get("commit")
        if commit is not None and not HEX_COMMIT.match(str(commit)):
            errors.append(f"{label}: commit must be a lowercase hex id or null (null = the commit that adds this entry)")
        if not DATE_RE.match(str(sl.get("date", ""))):
            errors.append(f"{label}: date must be YYYY-MM-DD")
        for key in ("rust", "vectors", "e2e"):
            for path in sl.get(key, []):
                if not (ROOT / path).is_file():
                    errors.append(f"{label}: {key} file missing: {path}")
        claimed, partial = _slice_lines(model, sl, errors)
        partial_total += partial
        for item in sl.get("ts", []):
            for name in item.get("functions", []) + item.get("twins", []):
                key = (item["file"], name)
                if key in owner:
                    errors.append(f"{label}: {item['file']} {name} is already claimed by slice {owner[key]}")
                owner[key] = sl.get("id")
        proof = proof_level(sl)
        lines = 0
        for path, rows in claimed.items():
            union[path] |= rows
            by_proof[proof] |= {(path, r) for r in rows}
            lines += model.sources[path].code_lines(rows)
        slices_out.append({"id": sl.get("id"), "commit": commit, "date": str(sl.get("date")), "proof": proof,
                           "functions": sum(len(i.get("functions", [])) + len(i.get("twins", [])) for i in sl.get("ts", [])),
                           "ts_code_lines": lines})
    ledgered = {(i["file"], n) for sl in ledger["slices"] for i in sl.get("ts", []) for n in i.get("functions", [])}
    ledgered_q = set()
    for path, name in ledgered:
        if path in model.sources:
            ledgered_q |= {(path, f.qualified) for f in find_function(model.sources[path], name)}
    unledgered = sorted(f"{p} {q}" for p, fns in model.routing.items() for q in fns if (p, q) not in ledgered_q)
    errors += [f"{LEDGER.name}: routing function without ledger entry: {u} (append it to a slice; see docs/migration/rust/README.md)" for u in unledgered]
    portable_lines = sum(model.sources[p].code_lines() for p in model.portable)
    ported = sum(model.sources[p].code_lines(rows) for p, rows in union.items())
    # A line claimed by slices with different proofs counts once, at the strongest proof.
    seen: set[tuple[str, int]] = set()
    proof_lines = {}
    for proof in PROOFS:
        rows = by_proof[proof] - seen
        seen |= rows
        proof_lines[proof] = sum(1 for p, r in rows if is_code_line(model.sources[p].raw[r]))
    summary = {
        "unit": "TS code lines",
        "portable_files": len(model.portable),
        "portable_code_lines": portable_lines,
        "ported_code_lines": ported,
        "percent": round(100 * ported / portable_lines, 1) if portable_lines else 0.0,
        "ported_by_proof": proof_lines,
        "files_with_ported_code": len([p for p, rows in union.items() if rows]),
        "routing_functions": sum(len(f) for f in model.routing.values()),
        "functions_counted_at_decision_sites_only": partial_total,
        "non_portable": {"files": len(model.non_portable), "code_lines": sum(model.sources[p].code_lines() for p in model.non_portable)},
        "bridge_excluded": {"files": len(model.bridge), "code_lines": sum(model.sources[p].code_lines() for p in model.bridge)},
        "slices": slices_out,
    }
    return summary, errors


# --- suggest (lane helper) ------------------------------------------------------------------


def _blame_commit(path: str, line: int) -> str:
    return _git("blame", "--porcelain", "-L", f"{line + 1},{line + 1}", "--", path).split(" ", 1)[0][:10]


def _git(*args: str) -> str:
    return subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True, check=True).stdout


def _commit_stub(commit: str, files: dict[str, list[str]]) -> dict:
    """Slice stub whose evidence lists come from the files the commit touched (still present)."""
    ts = [{"file": p, "functions": sorted(set(n))} for p, n in sorted(files.items())]
    if set(commit) == {"0"}:
        return {"id": "TODO-uncommitted", "commit": None, "date": "TODO", "title": "TODO", "rust": [], "vectors": [], "e2e": [], "ts": ts}
    date, subject = _git("show", "-s", "--format=%cs%x09%s", commit).strip().split("\t", 1)
    touched = [p for p in _git("show", "--name-only", "--format=", commit).split() if (ROOT / p).is_file()]
    slug = re.sub(r"[^a-z0-9]+", "-", re.sub(r"^\w+(\([^)]*\))?:\s*", "", subject.lower())).strip("-")[:48].strip("-")
    return {"id": f"{slug}-{commit[:7]}", "commit": commit, "date": date, "title": subject,
            "rust": [p for p in touched if p.startswith("packages/openmates-rust/src/") and p.endswith(".rs")][:6],
            "vectors": [p for p in touched if re.search(r"(Vectors|SharedUnit|Parity)[^/]*\.test\.ts$", p)][:6],
            "e2e": [p for p in touched if re.match(r"frontend/apps/web_app/tests/web-rust-core-[^/]*\.spec\.ts$", p) and "bench" not in p][:6],
            "ts": ts}


def suggest(model: Model) -> str:
    """YAML stubs for routing functions that no slice lists, grouped by the commit that last wrote their first flag read."""
    _, errors = measure(model)
    prefix = "routing function without ledger entry: "
    groups: dict[str, dict[str, list[str]]] = defaultdict(lambda: defaultdict(list))
    for err in errors:
        if prefix not in err:
            continue
        path, qualified = err.split(prefix, 1)[1].split(" (", 1)[0].split(" ", 1)
        fn = model.routing[path][qualified]
        commit = _blame_commit(path, fn.markers[0] if fn.markers else fn.start)
        leaf = fn.name if len(find_function(model.sources[path], fn.name)) == 1 else qualified
        groups[commit][path].append(leaf)
    stubs = [_commit_stub(c, files) for c, files in groups.items()]
    stubs.sort(key=lambda s: (str(s["date"]), str(s["commit"])))
    return yaml.dump(stubs, Dumper=_FlowListDumper, sort_keys=False, width=110)


class _FlowListDumper(yaml.SafeDumper):
    """Block mappings, lists of scalars on one line."""


_FlowListDumper.add_representer(list, lambda d, data: d.represent_sequence(
    "tag:yaml.org,2002:seq", data, flow_style=bool(data) and all(not isinstance(x, (dict, list)) for x in data)))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--suggest", action="store_true", help="print slice stubs for unledgered routing functions")
    args = parser.parse_args()
    model = build_model(load_ledger())
    if args.suggest:
        print(suggest(model))
        return 0
    summary, errors = measure(model)
    print(yaml.safe_dump({k: v for k, v in summary.items() if k != "slices"}, sort_keys=False))
    for line in errors:
        print(line, file=sys.stderr)
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
