#!/usr/bin/env python3
"""Run a deterministic static accessibility audit for web and Apple code.

The audit is Linux-safe and CI-friendly: it does not start the web app, run
Playwright, call Xcode, or require package installs. It scans source files for
known accessibility risk patterns, writes machine-readable JSON, and writes a
Markdown summary that can be reviewed by humans or OpenCode.
"""

from __future__ import annotations

import argparse
import json
import re
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Sequence


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT_DIR = REPO_ROOT / "test-results" / "accessibility"
DEFAULT_JSON_OUTPUT = DEFAULT_OUTPUT_DIR / "latest.json"
DEFAULT_MARKDOWN_OUTPUT = DEFAULT_OUTPUT_DIR / "latest.md"

WEB_ROOT = REPO_ROOT / "frontend"
WEB_COMPONENT_ROOT = REPO_ROOT / "frontend" / "packages" / "ui" / "src" / "components"
WEB_TEST_ROOT = REPO_ROOT / "frontend" / "apps" / "web_app" / "tests"
THEME_TOKENS = REPO_ROOT / "frontend" / "packages" / "ui" / "src" / "tokens" / "generated" / "theme.generated.css"

APPLE_ROOT = REPO_ROOT / "apple" / "OpenMates" / "Sources"
APPLE_TYPOGRAPHY_TOKENS = (
    REPO_ROOT
    / "frontend"
    / "packages"
    / "ui"
    / "src"
    / "tokens"
    / "generated"
    / "swift"
    / "TypographyTokens.generated.swift"
)

SEVERITY_ORDER = {"critical": 0, "high": 1, "medium": 2, "low": 3, "info": 4}
FAIL_SEVERITIES = tuple(SEVERITY_ORDER.keys())

SVELTE_FILE_SKIP_PARTS = (
    "/node_modules/",
    "/.svelte-kit/",
    "/dist/",
    "/build/",
)
SWIFT_FILE_SKIP_PARTS = (
    "/DerivedData/",
    "/.build/",
)

NATIVE_APPLE_PATTERNS = {
    "List": re.compile(r"\bList\s*\{"),
    "Form": re.compile(r"\bForm\s*\{"),
    "NavigationStack": re.compile(r"\bNavigationStack\b"),
    "NavigationLink": re.compile(r"\bNavigationLink\b"),
    "toolbar": re.compile(r"\.toolbar\s*\{"),
    "navigationTitle": re.compile(r"\.navigationTitle\s*\("),
    "sheet": re.compile(r"\.sheet\s*\("),
    "alert": re.compile(r"\.alert\s*\("),
    "contextMenu": re.compile(r"\.contextMenu\s*\{"),
    "Menu": re.compile(r"\bMenu\s*\{"),
    "Picker": re.compile(r"\bPicker\s*\("),
    "Toggle": re.compile(r"\bToggle\s*\("),
}


@dataclass(frozen=True)
class Finding:
    id: str
    area: str
    category: str
    severity: str
    title: str
    description: str
    path: str
    line: int
    snippet: str
    recommendation: str
    wcag: tuple[str, ...] = ()


def repo_path(path: Path) -> str:
    try:
        return path.relative_to(REPO_ROOT).as_posix()
    except ValueError:
        return path.as_posix()


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace")


def iter_files(root: Path, suffixes: Sequence[str], skip_parts: Sequence[str]) -> Iterable[Path]:
    if not root.exists():
        return
    for path in sorted(root.rglob("*")):
        if not path.is_file() or path.suffix not in suffixes:
            continue
        normalized = path.as_posix()
        if any(part in normalized for part in skip_parts):
            continue
        yield path


def finding(
    *,
    id: str,
    area: str,
    category: str,
    severity: str,
    title: str,
    description: str,
    path: Path,
    line: int,
    snippet: str,
    recommendation: str,
    wcag: Sequence[str] = (),
) -> Finding:
    return Finding(
        id=id,
        area=area,
        category=category,
        severity=severity,
        title=title,
        description=description,
        path=repo_path(path),
        line=line,
        snippet=snippet.strip(),
        recommendation=recommendation,
        wcag=tuple(wcag),
    )


def sorted_findings(findings: list[Finding]) -> list[Finding]:
    return sorted(findings, key=lambda item: (SEVERITY_ORDER[item.severity], item.area, item.path, item.line, item.id))


def hex_to_rgb(value: str) -> tuple[float, float, float]:
    value = value.lstrip("#")
    return tuple(int(value[i : i + 2], 16) / 255 for i in (0, 2, 4))  # type: ignore[return-value]


def relative_luminance(rgb: tuple[float, float, float]) -> float:
    def channel(value: float) -> float:
        return value / 12.92 if value <= 0.03928 else ((value + 0.055) / 1.055) ** 2.4

    red, green, blue = (channel(value) for value in rgb)
    return 0.2126 * red + 0.7152 * green + 0.0722 * blue


def contrast_ratio(foreground: str, background: str = "#ffffff") -> float:
    fg_lum = relative_luminance(hex_to_rgb(foreground))
    bg_lum = relative_luminance(hex_to_rgb(background))
    lighter = max(fg_lum, bg_lum)
    darker = min(fg_lum, bg_lum)
    return (lighter + 0.05) / (darker + 0.05)


def extract_static_test_ids() -> tuple[set[str], set[str]]:
    get_by_test_id = re.compile(r"getByTestId\(\s*['\"]([^'\"]+)['\"]\s*\)")
    data_test_id = re.compile(r"data-testid\s*=\s*['\"]([^'\"]+)['\"]")
    locator_test_id = re.compile(r"\[data-testid=['\"]([^'\"]+)['\"]\]")
    accessibility_id = re.compile(r"accessibilityIdentifier\(\s*\"([^\"]+)\"\s*\)")

    web_ids: set[str] = set()
    for path in iter_files(WEB_TEST_ROOT, (".ts",), SVELTE_FILE_SKIP_PARTS):
        text = read_text(path)
        web_ids.update(get_by_test_id.findall(text))
        web_ids.update(data_test_id.findall(text))
        web_ids.update(locator_test_id.findall(text))

    apple_ids: set[str] = set()
    for path in iter_files(APPLE_ROOT, (".swift",), SWIFT_FILE_SKIP_PARTS):
        apple_ids.update(accessibility_id.findall(read_text(path)))

    return web_ids, apple_ids


def check_web_contrast_tokens() -> list[Finding]:
    findings: list[Finding] = []
    if not THEME_TOKENS.exists():
        return findings

    token_re = re.compile(r"--(?P<name>color-font-[\w-]+):\s*(?P<value>#[0-9a-fA-F]{6});")
    for index, line in enumerate(read_text(THEME_TOKENS).splitlines(), start=1):
        if line.strip() == '/* Dark theme overrides */':
            break
        match = token_re.search(line)
        if not match:
            continue
        token_name = match.group("name")
        token_value = match.group("value")
        if token_name == "color-font-button":
            continue
        ratio = contrast_ratio(token_value)
        if ratio < 4.5:
            findings.append(
                finding(
                    id="web.contrast.font-token",
                    area="web",
                    category="contrast",
                    severity="high",
                    title="Font color token is below WCAG AA contrast on light backgrounds",
                    description=f"{token_name} ({token_value}) has an estimated {ratio:.2f}:1 contrast ratio against white.",
                    path=THEME_TOKENS,
                    line=index,
                    snippet=line,
                    recommendation="Adjust the token to at least 4.5:1 for normal text or stop using it for normal-sized text.",
                    wcag=("1.4.3",),
                )
            )
    return findings


def check_web_test_exceptions() -> list[Finding]:
    findings: list[Finding] = []
    for path in (WEB_TEST_ROOT / "a11y-helpers.ts", WEB_TEST_ROOT / "a11y-pages.spec.ts"):
        if not path.exists():
            continue
        for index, line in enumerate(read_text(path).splitlines(), start=1):
            if "color-contrast" in line:
                findings.append(
                    finding(
                        id="web.tests.allowed-contrast",
                        area="web",
                        category="test-coverage",
                        severity="medium",
                        title="Axe color contrast violations are allowed",
                        description="The accessibility test suite currently tolerates contrast violations, so regressions may not fail CI.",
                        path=path,
                        line=index,
                        snippet=line,
                        recommendation="Remove the exception after contrast tokens are fixed; fail on future contrast regressions.",
                        wcag=("1.4.3",),
                    )
                )
    return findings


def tag_name_from_line(line: str) -> str | None:
    match = re.search(r"<\s*([a-zA-Z][\w:-]*)", line)
    return match.group(1).lower() if match else None


def check_svelte_interactive_roles() -> list[Finding]:
    findings: list[Finding] = []
    role_re = re.compile(r"role\s*=\s*['\"](?P<role>button|menuitem|option|link)['\"]")
    for path in iter_files(WEB_COMPONENT_ROOT, (".svelte",), SVELTE_FILE_SKIP_PARTS):
        lines = read_text(path).splitlines()
        for index, line in enumerate(lines, start=1):
            match = role_re.search(line)
            if not match:
                continue
            context = "\n".join(lines[max(0, index - 4) : min(len(lines), index + 4)])
            if "<" not in context:
                continue
            tag = tag_name_from_line(context) or tag_name_from_line(line) or "unknown"
            role = match.group("role")
            if tag in {"button", "a", "input", "select", "textarea"}:
                continue
            has_enter = "Enter" in context
            has_space = "' '" in context or '" "' in context or "Space" in context
            severity = "high" if role in {"button", "menuitem", "option"} and not (has_enter and has_space) else "medium"
            findings.append(
                finding(
                    id=f"web.interactive-role.{role}",
                    area="web",
                    category="keyboard-semantics",
                    severity=severity,
                    title=f"Custom {role} role used on a non-native element",
                    description="Custom interactive roles are easy to get wrong and often miss native keyboard, state, and screen-reader behavior.",
                    path=path,
                    line=index,
                    snippet=line,
                    recommendation="Use a native control where possible. If the custom role remains, support Enter and Space and expose the correct ARIA state.",
                    wcag=("2.1.1", "4.1.2"),
                )
            )
    return findings


def check_svelte_a11y_ignores() -> list[Finding]:
    findings: list[Finding] = []
    for path in iter_files(WEB_COMPONENT_ROOT, (".svelte",), SVELTE_FILE_SKIP_PARTS):
        for index, line in enumerate(read_text(path).splitlines(), start=1):
            if "svelte-ignore a11y" not in line:
                continue
            findings.append(
                finding(
                    id="web.svelte-ignore-a11y",
                    area="web",
                    category="lint-suppression",
                    severity="medium",
                    title="Svelte accessibility warning is suppressed",
                    description="Suppressed accessibility warnings hide deterministic compiler feedback from review and CI.",
                    path=path,
                    line=index,
                    snippet=line,
                    recommendation="Remove the suppression by using semantic HTML or document why the warning is intentionally safe.",
                )
            )
    return findings


def check_svelte_hardcoded_aria() -> list[Finding]:
    findings: list[Finding] = []
    aria_re = re.compile(r"\baria-(?:label|description)\s*=\s*\"([^\"{][^\"]*)\"")
    for path in iter_files(WEB_COMPONENT_ROOT, (".svelte",), SVELTE_FILE_SKIP_PARTS):
        for index, line in enumerate(read_text(path).splitlines(), start=1):
            if "$text(" in line or "aria-label={`" in line:
                continue
            match = aria_re.search(line)
            if not match:
                continue
            findings.append(
                finding(
                    id="web.hardcoded-aria-text",
                    area="web",
                    category="localization",
                    severity="medium",
                    title="Hardcoded accessible text is not localized",
                    description="Screen-reader-visible text should follow the same i18n path as visible UI text.",
                    path=path,
                    line=index,
                    snippet=line,
                    recommendation="Move the accessible text into i18n YAML and reference it with $text(...).",
                    wcag=("3.1.2", "4.1.2"),
                )
            )
    return findings


def check_svelte_dialogs() -> list[Finding]:
    findings: list[Finding] = []
    for path in iter_files(WEB_COMPONENT_ROOT, (".svelte",), SVELTE_FILE_SKIP_PARTS):
        text = read_text(path)
        lines = text.splitlines()
        if 'role="dialog"' not in text and "role='dialog'" not in text:
            continue
        file_has_focus_trap = "use:focusTrap" in text or "focusTrap" in text
        for index, line in enumerate(lines, start=1):
            if 'role="dialog"' not in line and "role='dialog'" not in line:
                continue
            tag_context = " ".join(lines[index - 1 : min(len(lines), index + 8)])
            missing_parts: list[str] = []
            if "aria-modal" not in tag_context:
                missing_parts.append("aria-modal")
            if "aria-labelledby" not in tag_context and "aria-label" not in tag_context:
                missing_parts.append("accessible name")
            if not file_has_focus_trap:
                missing_parts.append("focus trap")
            if not missing_parts:
                continue
            findings.append(
                finding(
                    id="web.dialog.incomplete-semantics",
                    area="web",
                    category="dialog",
                    severity="high",
                    title="Dialog may be missing required modal semantics",
                    description=f"The dialog appears to be missing: {', '.join(missing_parts)}.",
                    path=path,
                    line=index,
                    snippet=line,
                    recommendation="Give blocking dialogs aria-modal, an accessible name, Escape handling, focus trapping, and focus restoration.",
                    wcag=("2.4.3", "4.1.2"),
                )
            )
    return findings


def check_web_toggle_focus() -> list[Finding]:
    path = WEB_COMPONENT_ROOT / "Toggle.svelte"
    if not path.exists():
        return []
    text = read_text(path)
    findings: list[Finding] = []
    if re.search(r"input\s*\{[^}]*width:\s*0[^}]*height:\s*0", text, re.DOTALL) and "focus-visible" not in text:
        line = next((i for i, value in enumerate(text.splitlines(), start=1) if "width: 0" in value), 1)
        findings.append(
            finding(
                id="web.toggle.focus-visible",
                area="web",
                category="focus",
                severity="high",
                title="Toggle input has no visible focus indicator",
                description="The native checkbox is zero-sized and the visual slider does not expose a focus-visible style.",
                path=path,
                line=line,
                snippet=text.splitlines()[line - 1],
                recommendation="Keep the input focusable over the full control or style the slider when the input has :focus-visible.",
                wcag=("2.4.7",),
            )
        )
    return findings


def check_web_reduced_motion_coverage() -> list[Finding]:
    findings: list[Finding] = []
    css_motion_re = re.compile(r"\b(?:transition|animation):")
    for path in iter_files(WEB_COMPONENT_ROOT, (".svelte", ".css"), SVELTE_FILE_SKIP_PARTS):
        text = read_text(path)
        if "prefers-reduced-motion" in text:
            continue
        for index, line in enumerate(text.splitlines(), start=1):
            if css_motion_re.search(line):
                findings.append(
                    finding(
                        id="web.motion.no-reduced-motion",
                        area="web",
                        category="motion",
                        severity="low",
                        title="Motion style has no local reduced-motion override",
                        description="This file defines transitions or animations but does not reference prefers-reduced-motion.",
                        path=path,
                        line=index,
                        snippet=line,
                        recommendation="Add a reduced-motion override or rely on a documented global reduced-motion reset.",
                        wcag=("2.3.3",),
                    )
                )
                break
    return findings


def check_apple_dynamic_type() -> list[Finding]:
    findings: list[Finding] = []
    if APPLE_TYPOGRAPHY_TOKENS.exists():
        text = read_text(APPLE_TYPOGRAPHY_TOKENS)
        if "Font.custom" in text and "relativeTo:" not in text:
            for index, line in enumerate(text.splitlines(), start=1):
                if "Font.custom" not in line:
                    continue
                findings.append(
                    finding(
                        id="apple.dynamic-type.fixed-font-token",
                        area="apple",
                        category="dynamic-type",
                        severity="high",
                        title="Generated Swift font token uses a fixed size",
                        description="Fixed Font.custom sizes do not reliably honor user Dynamic Type settings.",
                        path=APPLE_TYPOGRAPHY_TOKENS,
                        line=index,
                        snippet=line,
                        recommendation="Generate Swift font tokens with scalable text styles or UIFontMetrics-backed wrappers.",
                        wcag=("1.4.4",),
                    )
                )
    for path in iter_files(APPLE_ROOT, (".swift",), SWIFT_FILE_SKIP_PARTS):
        text = read_text(path)
        if "Font.custom" not in text:
            continue
        for index, line in enumerate(text.splitlines(), start=1):
            if "Font.custom" not in line:
                continue
            findings.append(
                finding(
                    id="apple.dynamic-type.fixed-font-inline",
                    area="apple",
                    category="dynamic-type",
                    severity="medium",
                    title="Inline fixed custom font size",
                    description="Inline fixed custom fonts can bypass Dynamic Type and drift from generated typography tokens.",
                    path=path,
                    line=index,
                    snippet=line,
                    recommendation="Use generated scalable typography tokens or a Dynamic Type wrapper.",
                    wcag=("1.4.4",),
                )
            )
    return findings


def check_apple_hardcoded_accessibility_text() -> list[Finding]:
    findings: list[Finding] = []
    hardcoded_re = re.compile(r"\.accessibility(?:Label|Hint|Value)\(\s*\"([^\"]+)\"\s*\)")
    for path in iter_files(APPLE_ROOT, (".swift",), SWIFT_FILE_SKIP_PARTS):
        for index, line in enumerate(read_text(path).splitlines(), start=1):
            if not hardcoded_re.search(line):
                continue
            findings.append(
                finding(
                    id="apple.hardcoded-accessibility-text",
                    area="apple",
                    category="localization",
                    severity="medium",
                    title="Hardcoded Apple accessibility text",
                    description="Assistive text is user-visible and must go through AppStrings/localization.",
                    path=path,
                    line=index,
                    snippet=line,
                    recommendation="Add or reuse an AppStrings accessor and pass that value to the accessibility modifier.",
                    wcag=("3.1.2", "4.1.2"),
                )
            )
    return findings


def check_apple_hit_targets() -> list[Finding]:
    findings: list[Finding] = []
    frame_re = re.compile(r"\.frame\(\s*width:\s*(\d+(?:\.\d+)?),\s*height:\s*(\d+(?:\.\d+)?)")
    for path in iter_files(APPLE_ROOT, (".swift",), SWIFT_FILE_SKIP_PARTS):
        lines = read_text(path).splitlines()
        for index, line in enumerate(lines, start=1):
            match = frame_re.search(line)
            if not match:
                continue
            width = float(match.group(1))
            height = float(match.group(2))
            if width >= 44 or height >= 44:
                continue
            context = "\n".join(lines[max(0, index - 6) : min(len(lines), index + 6)])
            if not any(marker in context for marker in ("Button", "gesture", "accessibilityLabel", "contentShape")):
                continue
            findings.append(
                finding(
                    id="apple.hit-target.small-frame",
                    area="apple",
                    category="hit-target",
                    severity="medium",
                    title="Potentially small interactive hit target",
                    description=f"The interactive frame is {width:g}x{height:g}pt, below the typical 44x44pt minimum target.",
                    path=path,
                    line=index,
                    snippet=line,
                    recommendation="Expand the tappable frame or contentShape to at least 44x44pt without changing the visual icon size.",
                    wcag=("2.5.5",),
                )
            )
    return findings


def check_apple_native_controls() -> list[Finding]:
    findings: list[Finding] = []
    for path in iter_files(APPLE_ROOT, (".swift",), SWIFT_FILE_SKIP_PARTS):
        for index, line in enumerate(read_text(path).splitlines(), start=1):
            for control_name, pattern in NATIVE_APPLE_PATTERNS.items():
                if not pattern.search(line):
                    continue
                findings.append(
                    finding(
                        id=f"apple.native-control.{control_name}",
                        area="apple",
                        category="native-control",
                        severity="medium",
                        title="Default native product UI control is used",
                        description=f"{control_name} can inject native chrome and semantics that diverge from OpenMates product UI.",
                        path=path,
                        line=index,
                        snippet=line,
                        recommendation="Use OpenMates primitives for app-owned UI unless this is an OS-owned capability picker/dialog.",
                    )
                )
    return findings


def check_apple_reduced_motion() -> list[Finding]:
    findings: list[Finding] = []
    animation_re = re.compile(r"\bwithAnimation\b|\.animation\s*\(")
    for path in iter_files(APPLE_ROOT, (".swift",), SWIFT_FILE_SKIP_PARTS):
        text = read_text(path)
        if "accessibilityReduceMotion" in text or "reduceMotion" in text:
            continue
        for index, line in enumerate(text.splitlines(), start=1):
            if not animation_re.search(line):
                continue
            findings.append(
                finding(
                    id="apple.motion.no-reduced-motion",
                    area="apple",
                    category="motion",
                    severity="medium",
                    title="Animation does not appear to respect Reduce Motion",
                    description="This file animates state but does not reference accessibilityReduceMotion/reduceMotion.",
                    path=path,
                    line=index,
                    snippet=line,
                    recommendation="Gate nonessential animations through @Environment(\\.accessibilityReduceMotion).",
                    wcag=("2.3.3",),
                )
            )
            break
    return findings


def check_apple_hardcoded_colors() -> list[Finding]:
    findings: list[Finding] = []
    for path in iter_files(APPLE_ROOT, (".swift",), SWIFT_FILE_SKIP_PARTS):
        for index, line in enumerate(read_text(path).splitlines(), start=1):
            if "Color(hex:" not in line:
                continue
            findings.append(
                finding(
                    id="apple.color.hardcoded-hex",
                    area="apple",
                    category="contrast-token-parity",
                    severity="low",
                    title="Hardcoded Swift color bypasses generated tokens",
                    description="Hardcoded colors are harder to audit for contrast and web parity.",
                    path=path,
                    line=index,
                    snippet=line,
                    recommendation="Use generated color/gradient tokens where possible, or document why a literal color is required.",
                    wcag=("1.4.3", "1.4.11"),
                )
            )
    return findings


def check_testability_inventory() -> list[Finding]:
    web_ids, apple_ids = extract_static_test_ids()
    if not web_ids:
        return []
    ratio = len(apple_ids) / len(web_ids)
    if ratio >= 0.25:
        return []
    path = REPO_ROOT / "docs" / "architecture" / "apple" / "parity-matrix.md"
    return [
        finding(
            id="apple.testability.identifier-gap",
            area="apple",
            category="testability",
            severity="medium",
            title="Apple accessibility identifiers lag web test IDs",
            description=f"Static inventory found {len(apple_ids)} Apple identifiers versus {len(web_ids)} web test IDs ({ratio:.1%}).",
            path=path if path.exists() else APPLE_ROOT,
            line=1,
            snippet="Apple/web accessibility identifier inventory",
            recommendation="Add stable Apple accessibility identifiers aligned with equivalent web data-testid names for important flows.",
        )
    ]


def build_report() -> dict[str, object]:
    checks = [
        check_web_contrast_tokens,
        check_web_test_exceptions,
        check_svelte_interactive_roles,
        check_svelte_a11y_ignores,
        check_svelte_hardcoded_aria,
        check_svelte_dialogs,
        check_web_toggle_focus,
        check_web_reduced_motion_coverage,
        check_apple_dynamic_type,
        check_apple_hardcoded_accessibility_text,
        check_apple_hit_targets,
        check_apple_native_controls,
        check_apple_reduced_motion,
        check_apple_hardcoded_colors,
        check_testability_inventory,
    ]
    findings: list[Finding] = []
    for check in checks:
        findings.extend(check())
    findings = sorted_findings(findings)

    counts_by_severity = {severity: 0 for severity in FAIL_SEVERITIES}
    counts_by_area = {"web": 0, "apple": 0}
    counts_by_category: dict[str, int] = {}
    counts_by_rule: dict[str, dict[str, object]] = {}
    for item in findings:
        counts_by_severity[item.severity] += 1
        counts_by_area[item.area] = counts_by_area.get(item.area, 0) + 1
        counts_by_category[item.category] = counts_by_category.get(item.category, 0) + 1
        rule = counts_by_rule.setdefault(
            item.id,
            {
                "id": item.id,
                "area": item.area,
                "category": item.category,
                "severity": item.severity,
                "title": item.title,
                "count": 0,
                "example": f"{item.path}:{item.line}",
            },
        )
        rule["count"] = int(rule["count"]) + 1

    sorted_rules = sorted(
        counts_by_rule.values(),
        key=lambda item: (
            SEVERITY_ORDER[str(item["severity"])],
            -int(item["count"]),
            str(item["id"]),
        ),
    )

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "summary": {
            "total_findings": len(findings),
            "counts_by_severity": counts_by_severity,
            "counts_by_area": counts_by_area,
            "counts_by_category": dict(sorted(counts_by_category.items())),
            "counts_by_rule": sorted_rules,
        },
        "findings": [asdict(item) for item in findings],
    }


def top_findings(findings: list[dict[str, object]], limit: int = 30) -> list[dict[str, object]]:
    return findings[:limit]


def format_markdown(report: dict[str, object]) -> str:
    summary = report["summary"]  # type: ignore[index]
    findings = report["findings"]  # type: ignore[index]
    assert isinstance(summary, dict)
    assert isinstance(findings, list)

    lines = [
        "# Accessibility Audit Report",
        "",
        f"Generated: `{report['generated_at']}`",
        "",
        "## Summary",
        "",
        f"Total findings: **{summary['total_findings']}**",
        "",
        "| Severity | Count |",
        "| --- | ---: |",
    ]
    counts_by_severity = summary["counts_by_severity"]
    assert isinstance(counts_by_severity, dict)
    for severity in FAIL_SEVERITIES:
        lines.append(f"| {severity} | {counts_by_severity.get(severity, 0)} |")

    lines.extend(["", "| Area | Count |", "| --- | ---: |"])
    counts_by_area = summary["counts_by_area"]
    assert isinstance(counts_by_area, dict)
    for area, count in sorted(counts_by_area.items()):
        lines.append(f"| {area} | {count} |")

    lines.extend(["", "## Top Rule Groups", ""])
    counts_by_rule = summary["counts_by_rule"]
    assert isinstance(counts_by_rule, list)
    lines.extend(["| Severity | Rule | Count | Example |", "| --- | --- | ---: | --- |"])
    for item in counts_by_rule[:20]:
        assert isinstance(item, dict)
        lines.append(
            f"| {item['severity']} | `{item['id']}` · {item['title']} | {item['count']} | `{item['example']}` |"
        )

    lines.extend(["", "## Top Finding Examples", ""])
    seen_rule_ids: set[str] = set()
    representative_findings: list[dict[str, object]] = []
    for item in findings:
        assert isinstance(item, dict)
        rule_id = str(item["id"])
        if rule_id in seen_rule_ids:
            continue
        seen_rule_ids.add(rule_id)
        representative_findings.append(item)
        if len(representative_findings) >= 30:
            break
    for item in representative_findings:
        assert isinstance(item, dict)
        wcag = item.get("wcag") or []
        wcag_suffix = f" WCAG: {', '.join(wcag)}." if wcag else ""
        lines.extend(
            [
                f"### {str(item['severity']).upper()} · {item['title']}",
                "",
                f"File: `{item['path']}:{item['line']}`",
                "",
                f"{item['description']}{wcag_suffix}",
                "",
                f"Recommendation: {item['recommendation']}",
                "",
                "```text",
                str(item["snippet"]),
                "```",
                "",
            ]
        )
    if len(findings) > len(representative_findings):
        lines.append(f"_Showing one representative example per rule. See JSON for all {len(findings)} findings._")
        lines.append("")

    lines.extend(
        [
            "## Notes",
            "",
            "This is a deterministic static audit. It complements, but does not replace, browser-based axe scans, keyboard E2E tests, simulator verification, or manual assistive-technology testing.",
            "",
        ]
    )
    return "\n".join(lines)


def resolve_output(path: Path) -> Path:
    return path if path.is_absolute() else REPO_ROOT / path


def write_report(report: dict[str, object], json_output: Path, markdown_output: Path) -> None:
    json_output.parent.mkdir(parents=True, exist_ok=True)
    markdown_output.parent.mkdir(parents=True, exist_ok=True)
    json_output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    markdown_output.write_text(format_markdown(report), encoding="utf-8")


def should_fail(report: dict[str, object], fail_on: str | None) -> bool:
    if fail_on is None:
        return False
    if fail_on not in FAIL_SEVERITIES:
        raise ValueError(f"Unsupported severity: {fail_on}")
    summary = report["summary"]  # type: ignore[index]
    assert isinstance(summary, dict)
    counts_by_severity = summary["counts_by_severity"]
    assert isinstance(counts_by_severity, dict)
    threshold = SEVERITY_ORDER[fail_on]
    return any(
        SEVERITY_ORDER[severity] <= threshold and int(counts_by_severity.get(severity, 0)) > 0
        for severity in FAIL_SEVERITIES
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Run deterministic static accessibility checks.")
    parser.add_argument("--json-output", type=Path, default=DEFAULT_JSON_OUTPUT, help="Path for JSON output.")
    parser.add_argument("--markdown-output", type=Path, default=DEFAULT_MARKDOWN_OUTPUT, help="Path for Markdown output.")
    parser.add_argument(
        "--fail-on",
        choices=FAIL_SEVERITIES,
        default=None,
        help="Exit non-zero if findings at this severity or higher are present.",
    )
    args = parser.parse_args()

    report = build_report()
    json_output = resolve_output(args.json_output)
    markdown_output = resolve_output(args.markdown_output)
    write_report(report, json_output, markdown_output)

    summary = report["summary"]
    assert isinstance(summary, dict)
    print(f"Wrote {repo_path(json_output)}")
    print(f"Wrote {repo_path(markdown_output)}")
    print(f"Findings: {summary['total_findings']}")
    print(f"By severity: {json.dumps(summary['counts_by_severity'], sort_keys=True)}")

    if should_fail(report, args.fail_on):
        print(f"Failing because findings at severity {args.fail_on!r} or higher are present.")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
