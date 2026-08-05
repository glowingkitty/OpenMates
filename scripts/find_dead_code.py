#!/usr/bin/env python3
"""
Deterministic stale-code detector for OpenMates.

The detector favors precision over recall. Only Ruff findings with a safe fix
may be deletion-ready; ambiguous Python symbols, TypeScript exports, Svelte
components, and CSS selectors remain review-only or are explicitly suppressed.
Architecture: docs/specs/deterministic-stale-code-reporting/spec.yml.
"""

from __future__ import annotations

import argparse
import ast
from collections import Counter
from dataclasses import asdict, dataclass, field
from enum import Enum
from functools import lru_cache
import hashlib
import io
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tokenize
from typing import Iterable


REPO_ROOT = Path(__file__).resolve().parent.parent
SKIP_DIRS = {
    ".git",
    ".openmates-agent-worktrees",
    ".pnpm-store",
    ".svelte-kit",
    ".turbo",
    ".venv",
    ".vercel",
    "__pycache__",
    "build",
    "coverage",
    "dist",
    "node_modules",
    "venv",
}
COMPATIBILITY_MARKERS = (
    "backward compatibility",
    "backwards compatibility",
    "compatibility shim",
    "public api",
    "external consumer",
    "do not remove",
)
GENERATED_PATH_MARKERS = ("generated", ".gen.", "locales/")
PYTHON_EXCLUDED_PATH_MARKERS = ("/migrations/", "/fixtures/", "/alembic/")
RUFF_PROTECTED_PATH_MARKERS = (
    "/alembic/",
    "/fixtures/",
    "/migrations/",
    "/routers/",
    "/routes/",
    "/scripts/",
    "/tasks/",
    "/tests/",
)


class Classification(str, Enum):
    DELETION_READY = "deletion_ready"
    REVIEW_ONLY = "review_only"
    SUPPRESSED = "suppressed"


class Confidence(str, Enum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


@dataclass
class DeadCodeItem:
    category: str
    subcategory: str
    file: str
    line: int | None
    code: str
    message: str
    confidence: str
    auto_fixable: bool
    classification: str
    evidence: list[str] = field(default_factory=list)
    suppression_reasons: list[str] = field(default_factory=list)
    context: str = ""
    fingerprint: str = ""

    def ensure_fingerprint(self) -> None:
        if not self.fingerprint:
            self.fingerprint = stable_fingerprint(
                self.category,
                self.subcategory,
                self.file,
                self.line,
                self.code,
            )


@dataclass
class DeadCodeReport:
    status: str = "ok"
    total_found: int = 0
    items: list[DeadCodeItem] = field(default_factory=list)
    summary: dict[str, dict[str, int]] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)
    analyzers: dict[str, str] = field(default_factory=dict)

    def add(self, item: DeadCodeItem) -> None:
        item.ensure_fingerprint()
        self.items.append(item)

    def finalize(self) -> None:
        self.items.sort(
            key=lambda item: (
                item.file,
                item.line or 0,
                item.category,
                item.subcategory,
                item.code,
            )
        )
        self.total_found = len(self.items)
        summary: dict[str, dict[str, int]] = {}
        for item in self.items:
            stats = summary.setdefault(
                item.category,
                {
                    "count": 0,
                    "deletion_ready": 0,
                    "review_only": 0,
                    "suppressed": 0,
                    "auto_fixable": 0,
                },
            )
            stats["count"] += 1
            stats[item.classification] += 1
            stats["auto_fixable"] += int(item.auto_fixable)
        self.summary = dict(sorted(summary.items()))

    def to_dict(self) -> dict:
        self.finalize()
        return {
            "status": self.status,
            "total_found": self.total_found,
            "summary": self.summary,
            "errors": list(self.errors),
            "analyzers": dict(sorted(self.analyzers.items())),
            "items": [asdict(item) for item in self.items],
        }


def stable_fingerprint(
    category: str,
    subcategory: str,
    file: str,
    line: int | None,
    code: str,
) -> str:
    payload = "\0".join((category, subcategory, file, str(line or 0), code))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _iter_files(root: Path, extensions: set[str]) -> Iterable[Path]:
    if not root.exists():
        return
    for path in sorted(root.rglob("*")):
        if not path.is_file() or path.suffix not in extensions:
            continue
        if any(part in SKIP_DIRS for part in path.relative_to(root).parts):
            continue
        yield path


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def _relative(path: Path, root: Path) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return os.path.relpath(path, root)


def _context(path: Path, line: int | None, radius: int = 2) -> str:
    if not line:
        return ""
    lines = _read_text(path).splitlines()
    start = max(0, line - radius - 1)
    end = min(len(lines), line + radius)
    return "\n".join(
        f"{'>>>' if index == line - 1 else '   '} {index + 1:4d} | {lines[index]}"
        for index in range(start, end)
    )


def _has_compatibility_marker(text: str) -> bool:
    lowered = text.lower()
    return any(marker in lowered for marker in COMPATIBILITY_MARKERS)


def _window(path: Path, line: int | None, before: int = 4, after: int = 2) -> str:
    if not line:
        return ""
    lines = _read_text(path).splitlines()
    return "\n".join(lines[max(0, line - before - 1) : min(len(lines), line + after)])


def _is_generated_or_protected(relative_path: str) -> bool:
    lowered = relative_path.lower()
    return any(marker in lowered for marker in GENERATED_PATH_MARKERS)


def _extract_backtick_name(message: str) -> str:
    match = re.search(r"`([^`]+)`", message)
    return match.group(1) if match else message


def _detect_python_ruff(root: Path, report: DeadCodeReport, limit: int) -> None:
    backend = root / "backend"
    if not backend.exists():
        report.analyzers["ruff"] = "not_applicable"
        return
    ruff = shutil.which("ruff")
    if not ruff:
        report.status = "error"
        report.errors.append("Required analyzer ruff is unavailable; Python findings were not promoted.")
        report.analyzers["ruff"] = "unavailable"
        return

    result = subprocess.run(
        [
            ruff,
            "check",
            "--select",
            "F401,F841",
            "--exclude",
            "*.ipynb",
            "--output-format",
            "json",
            str(backend),
        ],
        capture_output=True,
        text=True,
        cwd=root,
        check=False,
    )
    if result.returncode not in (0, 1):
        report.status = "error"
        report.errors.append(f"ruff failed with exit {result.returncode}: {result.stderr[:300]}")
        report.analyzers["ruff"] = "failed"
        return
    try:
        findings = json.loads(result.stdout or "[]")
    except json.JSONDecodeError as exc:
        report.status = "error"
        report.errors.append(f"ruff returned invalid JSON: {exc}")
        report.analyzers["ruff"] = "failed"
        return

    report.analyzers["ruff"] = "ok"
    emitted = 0
    for finding in findings:
        if limit and emitted >= limit:
            break
        raw_path = Path(finding.get("filename", ""))
        path = raw_path if raw_path.is_absolute() else root / raw_path
        relative_path = _relative(path, root)
        line = finding.get("location", {}).get("row")
        rule = finding.get("code", "")
        message = finding.get("message", "")
        name = _extract_backtick_name(message)
        safe_fix = (finding.get("fix") or {}).get("applicability") == "safe"
        reasons: list[str] = []

        if _is_generated_or_protected(relative_path):
            reasons.append("Generated or derived file")
        if any(marker in f"/{relative_path}" for marker in RUFF_PROTECTED_PATH_MARKERS):
            reasons.append("Framework, test, fixture, migration, task, route, or script path")
        if "/__init__.py" in f"/{relative_path}":
            reasons.append("Package re-export boundary")
        if _has_compatibility_marker(_window(path, line)):
            reasons.append("Compatibility or public API marker near finding")
        imported_root = name.split(".", 1)[0]
        if rule == "F401" and imported_root not in sys.stdlib_module_names:
            reasons.append("Non-standard-library import may have registration or import-time side effects")

        if reasons:
            classification = Classification.SUPPRESSED.value
        elif rule == "F401" and safe_fix:
            classification = Classification.DELETION_READY.value
        else:
            classification = Classification.REVIEW_ONLY.value

        if rule == "F841":
            evidence = [
                "Ruff identified an unused local binding; preserve the expression and remove only the binding after review."
            ]
            subcategory = "unused_variable"
        else:
            evidence = [
                f"Ruff {rule} reported the import unused.",
                f"Ruff safe-fix applicability: {str(safe_fix).lower()}.",
            ]
            subcategory = "unused_import"

        report.add(
            DeadCodeItem(
                category="python",
                subcategory=subcategory,
                file=relative_path,
                line=line,
                code=name,
                message=f"[{rule}] {message}",
                confidence=Confidence.HIGH.value if classification == Classification.DELETION_READY.value else Confidence.MEDIUM.value,
                auto_fixable=safe_fix and classification == Classification.DELETION_READY.value,
                classification=classification,
                evidence=evidence,
                suppression_reasons=reasons,
                context=_context(path, line),
            )
        )
        emitted += 1


def _python_name_counts(files: list[Path]) -> Counter[str]:
    counts: Counter[str] = Counter()
    for path in files:
        try:
            tokens = tokenize.generate_tokens(io.StringIO(_read_text(path)).readline)
            counts.update(token.string for token in tokens if token.type == tokenize.NAME)
        except (IndentationError, SyntaxError, tokenize.TokenError):
            continue
    return counts


def _module_all_names(tree: ast.AST) -> set[str]:
    names: set[str] = set()
    for node in getattr(tree, "body", []):
        if not isinstance(node, ast.Assign):
            continue
        if not any(isinstance(target, ast.Name) and target.id == "__all__" for target in node.targets):
            continue
        if isinstance(node.value, (ast.List, ast.Tuple)):
            names.update(
                element.value
                for element in node.value.elts
                if isinstance(element, ast.Constant) and isinstance(element.value, str)
            )
    return names


def _detect_python_symbols(root: Path, report: DeadCodeReport, limit: int) -> None:
    files = list(_iter_files(root / "backend", {".py"}))
    counts = _python_name_counts(files)
    emitted = 0
    for path in files:
        if limit and emitted >= limit:
            break
        relative_path = _relative(path, root)
        if any(marker in f"/{relative_path}" for marker in PYTHON_EXCLUDED_PATH_MARKERS):
            continue
        if "/tests/" in f"/{relative_path}" or "/scripts/" in f"/{relative_path}" or path.name.startswith("test_"):
            continue
        if _is_generated_or_protected(relative_path):
            continue
        text = _read_text(path)
        try:
            tree = ast.parse(text)
        except SyntaxError:
            continue
        public_names = _module_all_names(tree)
        for node in tree.body:
            if limit and emitted >= limit:
                break
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                continue
            name = node.name
            if not name.startswith("_") or name.startswith("__") or counts[name] != 1:
                continue
            reasons: list[str] = []
            if node.decorator_list:
                reasons.append("Decorated framework or registration hook")
            if name in public_names:
                reasons.append("Exported through __all__")
            node_text = ast.get_source_segment(text, node) or _window(path, node.lineno, after=8)
            if _has_compatibility_marker(node_text):
                reasons.append("Compatibility or public API marker")
            if reasons:
                classification = Classification.SUPPRESSED.value
            else:
                classification = Classification.REVIEW_ONLY.value
            kind = "unused_class" if isinstance(node, ast.ClassDef) else "unused_function"
            report.add(
                DeadCodeItem(
                    category="python",
                    subcategory=kind,
                    file=relative_path,
                    line=node.lineno,
                    code=name,
                    message=f"Top-level {kind.removeprefix('unused_')} `{name}` has no other lexical references.",
                    confidence=Confidence.LOW.value,
                    auto_fixable=False,
                    classification=classification,
                    evidence=["Python token index found only the definition name; dynamic usage is not disproved."],
                    suppression_reasons=reasons,
                    context=_context(path, node.lineno),
                )
            )
            emitted += 1
    report.analyzers["python_symbol_index"] = "ok"


def _identifier_counts(files: list[Path]) -> Counter[str]:
    counts: Counter[str] = Counter()
    pattern = re.compile(r"\b[A-Za-z_$][\w$]*\b")
    for path in files:
        counts.update(pattern.findall(_read_text(path)))
    return counts


def _detect_typescript(root: Path, report: DeadCodeReport, limit: int) -> None:
    frontend = root / "frontend"
    files = list(_iter_files(frontend, {".ts", ".js", ".svelte"}))
    counts = _identifier_counts(files)
    export_pattern = re.compile(
        r"^\s*export\s+(?:default\s+)?(?:async\s+)?(?:function|const|let|class|enum)\s+([A-Za-z_$][\w$]*)",
        re.MULTILINE,
    )
    emitted = 0
    for path in files:
        if path.suffix != ".ts" or ".test." in path.name or ".spec." in path.name:
            continue
        relative_path = _relative(path, root)
        text = _read_text(path)
        for match in export_pattern.finditer(text):
            if limit and emitted >= limit:
                break
            name = match.group(1)
            if counts[name] != 1:
                continue
            line = text.count("\n", 0, match.start()) + 1
            reasons: list[str] = []
            if _is_generated_or_protected(relative_path):
                reasons.append("Generated or derived file")
            if path.name in {"index.ts", "index.js"} or path.suffix == ".d.ts":
                reasons.append("Package public export boundary")
            if _has_compatibility_marker(_window(path, line, after=0)):
                reasons.append("Compatibility or public API marker near export")
            classification = Classification.SUPPRESSED.value if reasons else Classification.REVIEW_ONLY.value
            report.add(
                DeadCodeItem(
                    category="typescript",
                    subcategory="unused_export",
                    file=relative_path,
                    line=line,
                    code=name,
                    message=f"Exported `{name}` has no other lexical references.",
                    confidence=Confidence.LOW.value,
                    auto_fixable=False,
                    classification=classification,
                    evidence=["Repository identifier index found only the export definition; external and dynamic consumers are not disproved."],
                    suppression_reasons=reasons,
                    context=_context(path, line),
                )
            )
            emitted += 1
    report.analyzers["typescript_identifier_index"] = "ok"


@lru_cache(maxsize=16)
def _dynamic_context(root_value: str) -> tuple[str, str]:
    root = Path(root_value)
    frontend_parts: list[str] = []
    for path in _iter_files(root / "frontend", {".ts", ".js", ".svelte", ".html"}):
        frontend_parts.append(_read_text(path))
    metadata_parts = [
        _read_text(path)
        for path in _iter_files(root / "backend" / "apps", {".yml", ".yaml", ".json"})
    ]
    return "\n".join(frontend_parts), "\n".join(metadata_parts)


def classify_svelte_file(root: Path, path: Path) -> tuple[str, list[str]]:
    relative_path = _relative(path, root)
    reasons: list[str] = []
    if path.name.startswith(("+page", "+layout", "+error", "+server")) or "/routes/" in f"/{relative_path}":
        reasons.append("SvelteKit route convention")
    if _is_generated_or_protected(relative_path):
        reasons.append("Generated or derived file")

    frontend_text, metadata_text = _dynamic_context(str(root.resolve()))
    if path.name in metadata_text:
        reasons.append("Component filename is registered in app metadata")

    normalized = relative_path.replace("\\", "/")
    if "/components/" in f"/{normalized}" and "components/**/*.svelte" in frontend_text:
        reasons.append("Component tree is loaded by import.meta.glob")
    if path.name.endswith("EmbedFullscreen.svelte") and "**/*EmbedFullscreen.svelte" in frontend_text:
        reasons.append("Fullscreen embed family is loaded by import.meta.glob")
    if path.name.endswith("EmbedPreview.svelte") and "**/*EmbedPreview.svelte" in frontend_text:
        reasons.append("Preview embed family is loaded by import.meta.glob")

    if reasons:
        return Classification.SUPPRESSED.value, sorted(set(reasons))
    return Classification.REVIEW_ONLY.value, []


def _detect_svelte(root: Path, report: DeadCodeReport, limit: int) -> None:
    components = root / "frontend" / "packages" / "ui" / "src" / "components"
    files = list(_iter_files(components, {".svelte"}))
    frontend_text, _metadata_text = _dynamic_context(str(root.resolve()))
    emitted = 0
    for path in files:
        if limit and emitted >= limit:
            break
        own_text = _read_text(path)
        filename = path.name
        stem = path.stem
        filename_refs = frontend_text.count(filename) - own_text.count(filename)
        import_ref_pattern = re.compile(rf"\bimport\s+{re.escape(stem)}\b")
        import_refs = len(import_ref_pattern.findall(frontend_text)) - len(import_ref_pattern.findall(own_text))
        if filename_refs > 0 or import_refs > 0:
            continue
        classification, reasons = classify_svelte_file(root, path)
        report.add(
            DeadCodeItem(
                category="svelte",
                subcategory="unused_component",
                file=_relative(path, root),
                line=1,
                code=stem,
                message=f"Svelte component `{stem}` has no literal imports.",
                confidence=Confidence.LOW.value,
                auto_fixable=False,
                classification=classification,
                evidence=["No literal filename or component import was found; glob and metadata contracts were checked separately."],
                suppression_reasons=reasons,
            )
        )
        emitted += 1
    report.analyzers["svelte_reference_index"] = "ok"


def classify_css_class(root: Path, class_name: str) -> tuple[str, list[str]]:
    frontend_text, _metadata_text = _dynamic_context(str(root.resolve()))
    reasons: list[str] = []
    if class_name.startswith("app-") and any(marker in frontend_text for marker in ("app-{", "app-${", "app-`", "`app-")):
        reasons.append("App CSS class family is constructed dynamically")
    if class_name.startswith("provider-") and any(
        marker in frontend_text for marker in ("provider-{", "provider-${", "provider-`", "`provider-")
    ):
        reasons.append("Provider CSS class family is constructed dynamically")
    if reasons:
        return Classification.SUPPRESSED.value, sorted(set(reasons))
    return Classification.REVIEW_ONLY.value, []


def _extract_css_classes(path: Path) -> list[tuple[str, int]]:
    classes: list[tuple[str, int]] = []
    in_comment = False
    for line_number, line in enumerate(_read_text(path).splitlines(), start=1):
        stripped = line.strip()
        if "/*" in stripped:
            in_comment = True
        if not in_comment:
            classes.extend((match.group(1), line_number) for match in re.finditer(r"\.([A-Za-z_][\w-]*)", stripped))
        if "*/" in stripped:
            in_comment = False
    return classes


def _detect_css(root: Path, report: DeadCodeReport, limit: int) -> None:
    frontend = root / "frontend"
    styles = root / "frontend" / "packages" / "ui" / "src" / "styles"
    source_files = list(_iter_files(frontend, {".ts", ".js", ".svelte", ".html"}))
    source_text = "\n".join(_read_text(path) for path in source_files)
    emitted = 0
    seen: set[tuple[str, str]] = set()
    for path in _iter_files(styles, {".css"}):
        for class_name, line in _extract_css_classes(path):
            if limit and emitted >= limit:
                break
            key = (_relative(path, root), class_name)
            if key in seen:
                continue
            seen.add(key)
            if re.search(rf"(?<![-\w]){re.escape(class_name)}(?![-\w])", source_text):
                continue
            classification, reasons = classify_css_class(root, class_name)
            report.add(
                DeadCodeItem(
                    category="css",
                    subcategory="unused_class",
                    file=_relative(path, root),
                    line=line,
                    code=f".{class_name}",
                    message=f"CSS class `.{class_name}` has no literal source reference.",
                    confidence=Confidence.LOW.value,
                    auto_fixable=False,
                    classification=classification,
                    evidence=["No literal class reference was found; rendered and computed class usage is not disproved."],
                    suppression_reasons=reasons,
                    context=_context(path, line),
                )
            )
            emitted += 1
    report.analyzers["css_reference_index"] = "ok"


def scan_repository(
    root: Path = REPO_ROOT,
    *,
    categories: set[str] | None = None,
    limit: int = 0,
) -> DeadCodeReport:
    root = root.resolve()
    selected = categories or {"python", "typescript", "svelte", "css"}
    report = DeadCodeReport()
    if "python" in selected:
        _detect_python_ruff(root, report, limit)
        if report.analyzers.get("ruff") in {"ok", "not_applicable"}:
            _detect_python_symbols(root, report, limit)
    if "typescript" in selected:
        _detect_typescript(root, report, limit)
    if "svelte" in selected:
        _detect_svelte(root, report, limit)
    if "css" in selected:
        _detect_css(root, report, limit)
    report.finalize()
    return report


def format_markdown_report(report: DeadCodeReport) -> str:
    data = report.to_dict()
    lines = [
        "# Deterministic Stale Code Report",
        "",
        f"Status: **{data['status']}**",
        f"Total candidates: **{data['total_found']}**",
        "",
        "## Summary",
        "",
        "| Category | Total | Deletion-ready | Review-only | Suppressed |",
        "| --- | ---: | ---: | ---: | ---: |",
    ]
    for category, stats in data["summary"].items():
        lines.append(
            f"| {category} | {stats['count']} | {stats['deletion_ready']} | "
            f"{stats['review_only']} | {stats['suppressed']} |"
        )
    if data["errors"]:
        lines.extend(["", "## Errors", ""])
        lines.extend(f"- {error}" for error in data["errors"])
    for classification in (
        Classification.DELETION_READY.value,
        Classification.REVIEW_ONLY.value,
        Classification.SUPPRESSED.value,
    ):
        items = [item for item in report.items if item.classification == classification]
        lines.extend(["", f"## {classification.replace('_', ' ').title()} ({len(items)})", ""])
        if not items:
            lines.append("None.")
            continue
        for item in items:
            lines.append(f"- `{item.file}:{item.line or '?'}` `{item.code}` ({item.fingerprint[:12]})")
            lines.append(f"  - {item.message}")
            for evidence in item.evidence:
                lines.append(f"  - Evidence: {evidence}")
            for reason in item.suppression_reasons:
                lines.append(f"  - Suppressed: {reason}")
    lines.extend(
        [
            "",
            "Only deletion-ready findings may be passed to the remove-stale-code skill.",
            "Review-only and suppressed findings are not deletion instructions.",
            "",
        ]
    )
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="Detect deterministically stale code in OpenMates")
    parser.add_argument("--limit", type=int, default=100, help="Maximum findings per category; 0 means unlimited")
    parser.add_argument("--all", action="store_true", help="Do not limit findings")
    parser.add_argument(
        "--category",
        choices=["python", "typescript", "svelte", "css", "all"],
        default="all",
    )
    parser.add_argument("--json", action="store_true", dest="json_output")
    parser.add_argument("--root", type=Path, default=REPO_ROOT, help="Repository root, primarily for deterministic tests")
    args = parser.parse_args()
    limit = 0 if args.all else args.limit
    categories = None if args.category == "all" else {args.category}
    report = scan_repository(args.root, categories=categories, limit=limit)
    if args.json_output:
        print(json.dumps(report.to_dict(), indent=2))
    else:
        print(format_markdown_report(report))
    print(f"Done. {report.total_found} findings; status={report.status}.", file=sys.stderr)
    return 1 if report.status == "error" else 0


if __name__ == "__main__":
    raise SystemExit(main())
