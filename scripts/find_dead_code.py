#!/usr/bin/env python3
"""
Dead code detection script for OpenMates.

Detects unused code across Python, TypeScript, Svelte, and CSS.
Outputs a structured report that can be used by Claude to safely remove dead code.

Usage:
    python3 scripts/find_dead_code.py                    # default: 30 items
    python3 scripts/find_dead_code.py --limit 50         # custom limit
    python3 scripts/find_dead_code.py --category python  # only Python
    python3 scripts/find_dead_code.py --json             # JSON output (for automation)
    python3 scripts/find_dead_code.py --all              # no limit

Categories: python, typescript, svelte, css, all (default: all)

Architecture: docs/architecture/dead-code-detection.md
"""

import argparse
import json
import os
import re
import subprocess
import sys
from dataclasses import dataclass, field, asdict
from enum import Enum
from pathlib import Path
from typing import Optional


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

REPO_ROOT = Path(__file__).resolve().parent.parent

# Directories to always skip
SKIP_DIRS = {
    "node_modules", "__pycache__", ".git", "dist", "build", ".turbo",
    ".venv", "venv", "coverage", ".svelte-kit", ".vercel", "tree-sitter-env",
}

# Files/patterns known to be false positives
FALSE_POSITIVE_PATTERNS = [
    r"# noqa",                          # explicit suppression
    r"eslint-disable",                  # explicit suppression
    r"svelte-ignore",                   # Svelte suppression
    r"TYPE_CHECKING",                   # typing-only imports
    r"__all__",                         # explicit public API
    r"if TYPE_CHECKING",               # conditional imports
]

# Python files that are expected to have "unused" imports (re-exports, __init__, etc.)
PYTHON_REEXPORT_FILES = {
    "__init__.py",
}

# Backend directories
BACKEND_DIR = REPO_ROOT / "backend"
FRONTEND_DIR = REPO_ROOT / "frontend"
UI_PKG_DIR = FRONTEND_DIR / "packages" / "ui"
WEB_APP_DIR = FRONTEND_DIR / "apps" / "web_app"
STYLES_DIR = UI_PKG_DIR / "src" / "styles"


class Confidence(str, Enum):
    """How confident we are this is truly dead code."""
    HIGH = "high"       # Safe to delete — confirmed unused
    MEDIUM = "medium"   # Likely unused but check dynamic usage
    LOW = "low"         # Possibly used dynamically — needs manual review


class Category(str, Enum):
    PYTHON = "python"
    TYPESCRIPT = "typescript"
    SVELTE = "svelte"
    CSS = "css"


@dataclass
class DeadCodeItem:
    """A single dead code finding."""
    category: str
    subcategory: str        # e.g. "unused_import", "unused_function", "unused_class"
    file: str               # relative path
    line: Optional[int]     # line number
    code: str               # the dead code snippet
    message: str            # human-readable explanation
    confidence: str         # Confidence level
    auto_fixable: bool      # Can ruff/eslint auto-fix this?
    context: str = ""       # surrounding context for review


@dataclass
class DeadCodeReport:
    """Full dead code report."""
    total_found: int = 0
    items: list = field(default_factory=list)
    summary: dict = field(default_factory=dict)

    def add(self, item: DeadCodeItem):
        self.items.append(item)
        self.total_found = len(self.items)

    def to_dict(self):
        return {
            "total_found": self.total_found,
            "summary": self.summary,
            "items": [asdict(i) for i in self.items],
        }


# ---------------------------------------------------------------------------
# Python dead code detection (ruff-based)
# ---------------------------------------------------------------------------

def detect_python_dead_code(report: DeadCodeReport, limit: int) -> None:
    """Use ruff to find unused imports and variables in Python backend."""
    if not BACKEND_DIR.exists():
        return

    # F401 = unused import, F841 = unused local variable
    result = subprocess.run(
        ["ruff", "check", "--select", "F401,F841", "--exclude", "*.ipynb",
         "--output-format", "json", str(BACKEND_DIR)],
        capture_output=True, text=True, cwd=str(REPO_ROOT)
    )

    if result.returncode not in (0, 1):  # 1 = findings found (normal)
        print(f"  [WARN] ruff failed: {result.stderr[:200]}", file=sys.stderr)
        return

    try:
        findings = json.loads(result.stdout) if result.stdout.strip() else []
    except json.JSONDecodeError:
        print("  [WARN] ruff JSON parse failed", file=sys.stderr)
        return

    for f in findings:
        if limit > 0 and len([i for i in report.items if i.category == "python"]) >= limit:
            break

        filepath = f.get("filename", "")
        rel_path = os.path.relpath(filepath, REPO_ROOT) if filepath else ""
        code_text = f.get("message", "")
        line_num = f.get("location", {}).get("row")
        rule = f.get("code", "")

        # Skip __init__.py files (often re-export intentionally)
        if os.path.basename(filepath) in PYTHON_REEXPORT_FILES:
            # But only if it looks like a re-export pattern
            if _is_likely_reexport(filepath, line_num):
                continue

        # Check for noqa/suppression on that line
        if _line_has_suppression(filepath, line_num):
            continue

        # Determine confidence
        confidence = Confidence.HIGH.value
        if "TYPE_CHECKING" in code_text:
            confidence = Confidence.LOW.value
        elif "__init__" in rel_path:
            confidence = Confidence.MEDIUM.value

        subcategory = "unused_import" if rule == "F401" else "unused_variable"

        report.add(DeadCodeItem(
            category="python",
            subcategory=subcategory,
            file=rel_path,
            line=line_num,
            code=code_text,
            message=f"[{rule}] {code_text}",
            confidence=confidence,
            auto_fixable=(f.get("fix") or {}).get("applicability", "") == "safe",
            context=_get_context_lines(filepath, line_num, 2),
        ))


def _is_likely_reexport(filepath: str, line_num: Optional[int]) -> bool:
    """Check if an import in __init__.py is a re-export."""
    if not line_num:
        return False
    try:
        with open(filepath, "r", errors="replace") as fh:
            lines = fh.readlines()
            if line_num <= len(lines):
                line = lines[line_num - 1]
                # Patterns like `from .module import X` in __init__.py are re-exports
                if re.match(r"from \.", line):
                    return True
    except (OSError, UnicodeDecodeError):
        pass
    return False


# ---------------------------------------------------------------------------
# Python: Deprecated functions with zero callers
# ---------------------------------------------------------------------------

def detect_python_deprecated(report: DeadCodeReport, limit: int) -> None:
    """Find functions/methods marked DEPRECATED that have no callers."""
    if not BACKEND_DIR.exists():
        return

    # Find all DEPRECATED markers
    result = subprocess.run(
        ["rg", "-n", r'""".*DEPRECATED|# DEPRECATED|# deprecated',
         str(BACKEND_DIR), "-g", "*.py", "--no-heading"],
        capture_output=True, text=True, cwd=str(REPO_ROOT)
    )
    if not result.stdout.strip():
        return

    for line in result.stdout.strip().split("\n"):
        if limit > 0 and len([i for i in report.items if i.category == "python" and i.subcategory == "deprecated_function"]) >= limit:
            break

        match = re.match(r"^(.+?):(\d+):(.*)", line)
        if not match:
            continue

        filepath, line_num_str, content = match.groups()
        line_num = int(line_num_str)
        rel_path = os.path.relpath(filepath, REPO_ROOT)

        # Try to find the function/method name near this deprecation marker
        func_name = _find_nearest_function(filepath, line_num)
        if not func_name:
            continue

        # Check if this function is called anywhere else
        caller_count = _count_callers(func_name, filepath)

        if caller_count == 0:
            report.add(DeadCodeItem(
                category="python",
                subcategory="deprecated_function",
                file=rel_path,
                line=line_num,
                code=func_name,
                message=f"Deprecated function `{func_name}` has 0 callers outside its own file",
                confidence=Confidence.MEDIUM.value,
                auto_fixable=False,
                context=_get_context_lines(filepath, line_num, 3),
            ))


def _find_nearest_function(filepath: str, line_num: int) -> Optional[str]:
    """Find the function/method name closest to a line number (searching upward)."""
    try:
        with open(filepath, "r", errors="replace") as fh:
            lines = fh.readlines()
    except (OSError, UnicodeDecodeError):
        return None

    # Search from line_num upward for a def/async def
    for i in range(line_num - 1, max(line_num - 10, -1), -1):
        if i < 0 or i >= len(lines):
            continue
        m = re.match(r"\s*(?:async\s+)?def\s+(\w+)", lines[i])
        if m:
            return m.group(1)
    # Also search downward (docstring at top of function)
    for i in range(line_num, min(line_num + 5, len(lines))):
        m = re.match(r"\s*(?:async\s+)?def\s+(\w+)", lines[i])
        if m:
            return m.group(1)
    return None


def _count_callers(func_name: str, source_file: str) -> int:
    """Count how many times a function is referenced outside its own file."""
    # Skip common names that would produce too many false matches
    if func_name in ("__init__", "__str__", "__repr__", "get", "set", "run", "execute", "process"):
        return 999  # assume used

    result = subprocess.run(
        ["rg", "-l", rf"\b{re.escape(func_name)}\b", str(BACKEND_DIR),
         "-g", "*.py", "--no-heading"],
        capture_output=True, text=True
    )
    if not result.stdout.strip():
        return 0

    files = [f for f in result.stdout.strip().split("\n")
             if os.path.abspath(f) != os.path.abspath(source_file)]
    return len(files)


# ---------------------------------------------------------------------------
# TypeScript/Svelte: unused exports (grep-based, no knip dependency)
# ---------------------------------------------------------------------------

def detect_ts_unused_exports(report: DeadCodeReport, limit: int) -> None:
    """Find exported TS functions/consts that are never imported anywhere."""
    if not UI_PKG_DIR.exists():
        return

    # Also search web_app for exports
    search_dirs = [str(UI_PKG_DIR / "src")]
    web_app_src = WEB_APP_DIR / "src"
    if web_app_src.exists():
        search_dirs.append(str(web_app_src))

    # Get file+line info for all exported symbols
    result_full = subprocess.run(
        ["rg", "-n",
         r"^export\s+(?:async\s+)?(?:function|const|let|class|enum)\s+(\w+)",
         *search_dirs, "-g", "*.ts", "--no-heading"],
        capture_output=True, text=True
    )

    export_lines = result_full.stdout.strip().split("\n") if result_full.stdout.strip() else []

    checked = 0
    for line in export_lines:
        if limit > 0 and len([i for i in report.items if i.category == "typescript"]) >= limit:
            break

        match = re.match(r"^(.+?):(\d+):\s*export\s+(?:async\s+)?(?:function|const|let|class|enum)\s+(\w+)", line)
        if not match:
            continue

        filepath, line_num_str, name = match.groups()
        line_num = int(line_num_str)
        rel_path = os.path.relpath(filepath, REPO_ROOT)

        # Skip very common/short names that would have too many false positives
        if len(name) <= 2 or name.startswith("_"):
            continue

        # Skip index.ts / barrel files
        if os.path.basename(filepath) == "index.ts":
            continue

        # Skip test files
        if ".test." in filepath or ".spec." in filepath or "/tests/" in filepath:
            continue

        # Count how many OTHER files reference this name
        import_count = _count_ts_references(name, filepath)

        if import_count == 0:
            # Check: is it used internally within its own file (non-export reference)?
            internal_usage = _count_internal_references(name, filepath)
            if internal_usage > 0:
                # Used internally but never imported externally — the export keyword is unnecessary
                # but the code itself isn't dead. Lower confidence.
                confidence = Confidence.LOW.value
                message = f"Exported `{name}` is used internally but never imported externally — consider removing `export`"
            else:
                confidence = Confidence.MEDIUM.value
                message = f"Exported `{name}` is never imported in any other file"

            # Skip low-confidence items to keep the report focused
            if confidence == Confidence.LOW.value:
                checked += 1
                continue

            report.add(DeadCodeItem(
                category="typescript",
                subcategory="unused_export",
                file=rel_path,
                line=line_num,
                code=name,
                message=message,
                confidence=confidence,
                auto_fixable=False,
                context=_get_context_lines(filepath, line_num, 2),
            ))

        checked += 1
        if checked % 100 == 0:
            print(f"  ... checked {checked} TS exports", file=sys.stderr)


def _count_ts_references(name: str, source_file: str) -> int:
    """Count files that import/reference a TS export (excluding its own file and coverage)."""
    result = subprocess.run(
        ["rg", "-l", rf"\b{re.escape(name)}\b",
         str(FRONTEND_DIR), "-g", "*.ts", "-g", "*.svelte", "-g", "*.js",
         "--no-heading", "--glob", "!coverage/**", "--glob", "!node_modules/**"],
        capture_output=True, text=True
    )
    if not result.stdout.strip():
        return 0

    files = [f for f in result.stdout.strip().split("\n")
             if os.path.abspath(f) != os.path.abspath(source_file)]
    return len(files)


def _count_internal_references(name: str, filepath: str) -> int:
    """Count non-export references to a name within its own file."""
    try:
        with open(filepath, "r", errors="replace") as fh:
            content = fh.read()
    except (OSError, UnicodeDecodeError):
        return 0

    # Remove the export line itself, then count remaining references
    # This catches: function calls, assignments, property access, etc.
    matches = re.findall(rf"\b{re.escape(name)}\b", content)
    # Subtract 1 for the export definition itself
    return max(0, len(matches) - 1)


# ---------------------------------------------------------------------------
# Svelte: unused component files
# ---------------------------------------------------------------------------

def detect_unused_svelte_components(report: DeadCodeReport, limit: int) -> None:
    """Find .svelte files that are never imported anywhere."""
    if not UI_PKG_DIR.exists():
        return

    # Get all .svelte files in the components directory
    components_dir = UI_PKG_DIR / "src" / "components"
    if not components_dir.exists():
        return

    svelte_files = list(components_dir.rglob("*.svelte"))

    checked = 0
    for svelte_file in sorted(svelte_files):
        if limit > 0 and len([i for i in report.items if i.category == "svelte"]) >= limit:
            break

        rel_path = os.path.relpath(svelte_file, REPO_ROOT)
        component_name = svelte_file.stem  # e.g. "Button" from "Button.svelte"

        # Skip files that are SvelteKit route files
        if "+page" in component_name or "+layout" in component_name or "+error" in component_name:
            continue

        # Search for imports of this component across the entire frontend
        # Match both: `import Foo from '...'` and `from '..../Foo.svelte'`
        import_count = _count_svelte_imports(component_name, str(svelte_file))

        if import_count == 0:
            # Double-check: is it referenced in barrel exports?
            barrel_ref = _is_in_barrel_export(component_name)

            confidence = Confidence.HIGH.value if not barrel_ref else Confidence.MEDIUM.value

            report.add(DeadCodeItem(
                category="svelte",
                subcategory="unused_component",
                file=rel_path,
                line=1,
                code=component_name,
                message=f"Svelte component `{component_name}` is never imported" +
                        (" (but is in barrel export)" if barrel_ref else ""),
                confidence=confidence,
                auto_fixable=False,
                context="",  # No context needed for entire file
            ))

        checked += 1
        if checked % 50 == 0:
            print(f"  ... checked {checked}/{len(svelte_files)} Svelte components", file=sys.stderr)


def _count_svelte_imports(component_name: str, source_file: str) -> int:
    """Count how many files import a Svelte component."""
    # Search for the component name in import statements (exclude coverage/node_modules)
    result = subprocess.run(
        ["rg", "-l",
         rf"(?:import\s+.*\b{re.escape(component_name)}\b|from\s+['\"].*/{re.escape(component_name)}\.svelte['\"]|/{re.escape(component_name)}\.svelte)",
         str(FRONTEND_DIR), "-g", "*.ts", "-g", "*.svelte", "-g", "*.js",
         "--no-heading", "--glob", "!coverage/**", "--glob", "!node_modules/**"],
        capture_output=True, text=True
    )
    if not result.stdout.strip():
        return 0

    files = [f for f in result.stdout.strip().split("\n")
             if os.path.abspath(f) != os.path.abspath(source_file)]
    return len(files)


def _is_in_barrel_export(component_name: str) -> bool:
    """Check if component is exported from UI barrel."""
    barrel_file = UI_PKG_DIR / "index.ts"
    if not barrel_file.exists():
        return False
    try:
        content = barrel_file.read_text()
        return bool(re.search(rf"\b{re.escape(component_name)}\b", content))
    except (OSError, UnicodeDecodeError):
        return False


# ---------------------------------------------------------------------------
# CSS: unused global classes
# ---------------------------------------------------------------------------

def detect_unused_css_classes(report: DeadCodeReport, limit: int) -> None:
    """Find CSS classes in global stylesheets that are never referenced."""
    if not STYLES_DIR.exists():
        return

    css_files = list(STYLES_DIR.glob("*.css"))

    # Track already-reported class names to deduplicate (same class in media queries)
    reported_classes: set = set()

    for css_file in sorted(css_files):
        if limit > 0 and len([i for i in report.items if i.category == "css"]) >= limit:
            break

        rel_css_path = os.path.relpath(css_file, REPO_ROOT)

        # Extract class names from this CSS file
        classes = _extract_css_classes(css_file)

        for class_name, line_num in classes:
            if limit > 0 and len([i for i in report.items if i.category == "css"]) >= limit:
                break

            # Deduplicate: only report each class once per CSS file
            dedup_key = f"{rel_css_path}:{class_name}"
            if dedup_key in reported_classes:
                continue

            # Skip CSS custom property definitions (--var-name), animation names, pseudo-classes
            if class_name.startswith("-") or len(class_name) <= 2:
                continue

            # Skip common utility classes that might be used dynamically
            if class_name in ("hidden", "visible", "active", "disabled", "error", "loading",
                              "selected", "focused", "open", "closed", "dark", "light"):
                continue

            # Count references in Svelte/TS/HTML files
            ref_count = _count_css_class_references(class_name, str(css_file))

            if ref_count == 0:
                reported_classes.add(dedup_key)
                report.add(DeadCodeItem(
                    category="css",
                    subcategory="unused_class",
                    file=rel_css_path,
                    line=line_num,
                    code=f".{class_name}",
                    message=f"CSS class `.{class_name}` is never referenced in Svelte/TS/HTML files",
                    confidence=Confidence.MEDIUM.value,  # dynamic class binding possible
                    auto_fixable=False,
                    context=_get_context_lines(str(css_file), line_num, 2),
                ))


def _extract_css_classes(css_file: Path) -> list:
    """Extract class names and their line numbers from a CSS file."""
    classes = []
    try:
        with open(css_file, "r", errors="replace") as fh:
            for i, line in enumerate(fh, 1):
                # Match class selectors: .class-name
                # But not inside comments or property values
                stripped = line.strip()
                if stripped.startswith("/*") or stripped.startswith("*") or stripped.startswith("//"):
                    continue
                for m in re.finditer(r"\.([a-zA-Z_][\w-]*)", stripped):
                    class_name = m.group(1)
                    # Skip pseudo-elements/classes that look like class names
                    if class_name in ("hover", "focus", "active", "before", "after",
                                       "first-child", "last-child", "nth-child", "not",
                                       "root", "global"):
                        continue
                    classes.append((class_name, i))
    except (OSError, UnicodeDecodeError):
        pass
    return classes


def _count_css_class_references(class_name: str, source_file: str) -> int:
    """Count references to a CSS class in Svelte/TS/HTML files (excluding CSS definitions)."""
    # Search in Svelte and TS files for the class name (NOT in CSS files — that would match definitions)
    result = subprocess.run(
        ["rg", "-l", rf"\b{re.escape(class_name)}\b",
         str(FRONTEND_DIR), "-g", "*.svelte", "-g", "*.ts", "-g", "*.html",
         "--no-heading", "--glob", "!coverage/**", "--glob", "!node_modules/**"],
        capture_output=True, text=True
    )
    if not result.stdout.strip():
        return 0

    return len(result.stdout.strip().split("\n"))


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _line_has_suppression(filepath: str, line_num: Optional[int]) -> bool:
    """Check if a specific line has a noqa/eslint-disable suppression."""
    if not line_num:
        return False
    try:
        with open(filepath, "r", errors="replace") as fh:
            lines = fh.readlines()
            if line_num <= len(lines):
                line = lines[line_num - 1]
                return any(p in line for p in ["# noqa", "# type: ignore", "eslint-disable"])
    except (OSError, UnicodeDecodeError):
        pass
    return False


def _get_context_lines(filepath: str, line_num: Optional[int], context: int = 2) -> str:
    """Get surrounding lines for context."""
    if not line_num:
        return ""
    try:
        with open(filepath, "r", errors="replace") as fh:
            lines = fh.readlines()
            start = max(0, line_num - 1 - context)
            end = min(len(lines), line_num + context)
            context_lines = []
            for i in range(start, end):
                marker = ">>>" if i == line_num - 1 else "   "
                context_lines.append(f"{marker} {i + 1:4d} | {lines[i].rstrip()}")
            return "\n".join(context_lines)
    except (OSError, UnicodeDecodeError):
        return ""


# ---------------------------------------------------------------------------
# Report formatting
# ---------------------------------------------------------------------------

def format_markdown_report(report: DeadCodeReport) -> str:
    """Format the report as Markdown."""
    lines = []
    lines.append("# Dead Code Detection Report")
    lines.append("")
    lines.append(f"**Total findings: {report.total_found}**")
    lines.append("")

    # Summary by category
    if report.summary:
        lines.append("## Summary")
        lines.append("")
        lines.append("| Category | Count | High Confidence | Auto-fixable |")
        lines.append("|----------|-------|-----------------|--------------|")
        for cat, stats in report.summary.items():
            lines.append(f"| {cat} | {stats['count']} | {stats['high_confidence']} | {stats['auto_fixable']} |")
        lines.append("")

    # Group items by category
    by_category = {}
    for item in report.items:
        by_category.setdefault(item.category, []).append(item)

    for category, items in by_category.items():
        lines.append(f"## {category.upper()} ({len(items)} findings)")
        lines.append("")

        # Sub-group by subcategory
        by_sub = {}
        for item in items:
            by_sub.setdefault(item.subcategory, []).append(item)

        for subcategory, sub_items in by_sub.items():
            lines.append(f"### {subcategory.replace('_', ' ').title()} ({len(sub_items)})")
            lines.append("")

            for item in sub_items:
                confidence_icon = {"high": "🔴", "medium": "🟡", "low": "🟢"}.get(item.confidence, "⚪")
                fix_tag = " `[auto-fix]`" if item.auto_fixable else ""

                lines.append(f"- {confidence_icon} **{item.file}:{item.line or '?'}**{fix_tag}")
                lines.append(f"  {item.message}")
                if item.context:
                    lines.append("  ```")
                    lines.append(f"  {item.context}")
                    lines.append("  ```")
                lines.append("")

    # Legend
    lines.append("---")
    lines.append("**Confidence:** 🔴 High (safe to delete) | 🟡 Medium (check dynamic usage) | 🟢 Low (likely false positive)")
    lines.append("`[auto-fix]` = ruff can safely auto-fix this finding")
    lines.append("")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Detect dead code in OpenMates")
    parser.add_argument("--limit", type=int, default=30,
                        help="Max findings per category (default: 30, 0 = unlimited)")
    parser.add_argument("--category", choices=["python", "typescript", "svelte", "css", "all"],
                        default="all", help="Which category to scan (default: all)")
    parser.add_argument("--json", action="store_true", dest="json_output",
                        help="Output as JSON instead of Markdown")
    parser.add_argument("--all", action="store_true",
                        help="No limit (overrides --limit)")
    args = parser.parse_args()

    if args.all:
        args.limit = 0

    report = DeadCodeReport()

    categories = (
        ["python", "typescript", "svelte", "css"]
        if args.category == "all"
        else [args.category]
    )

    per_category_limit = args.limit  # per-category limit

    for cat in categories:
        print(f"Scanning {cat}...", file=sys.stderr)

        if cat == "python":
            detect_python_dead_code(report, per_category_limit)
            detect_python_deprecated(report, per_category_limit)
        elif cat == "typescript":
            detect_ts_unused_exports(report, per_category_limit)
        elif cat == "svelte":
            detect_unused_svelte_components(report, per_category_limit)
        elif cat == "css":
            detect_unused_css_classes(report, per_category_limit)

    # Build summary
    for item in report.items:
        cat = item.category
        if cat not in report.summary:
            report.summary[cat] = {"count": 0, "high_confidence": 0, "auto_fixable": 0}
        report.summary[cat]["count"] += 1
        if item.confidence == "high":
            report.summary[cat]["high_confidence"] += 1
        if item.auto_fixable:
            report.summary[cat]["auto_fixable"] += 1

    # Output
    if args.json_output:
        print(json.dumps(report.to_dict(), indent=2))
    else:
        print(format_markdown_report(report))

    print(f"\nDone. {report.total_found} findings total.", file=sys.stderr)


if __name__ == "__main__":
    main()
