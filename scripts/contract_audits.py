#!/usr/bin/env python3
"""Deterministic codebase contract audits for OpenMates.

These checks encode project-specific architecture and quality rules that are
too repo-specific for generic linting. They are intentionally static and
deterministic: no AI, no network, no mutation. The weekly runner stores the
JSON output so an agent can process findings later.

Architecture context: docs/architecture/infrastructure/cronjobs.md
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable


REPO_ROOT = Path(__file__).resolve().parents[1]

SEVERITY_ORDER = {"critical": 4, "high": 3, "medium": 2, "low": 1, "info": 0}
MAX_FINDINGS_PER_RULE = 25
SKIP_DIR_NAMES = {
    ".git",
    ".svelte-kit",
    ".turbo",
    ".venv",
    "__pycache__",
    "build",
    "coverage",
    "dist",
    "node_modules",
    "test-results",
}

BACKEND_APP_SHARED_IMPORT_ALLOWLIST = {
    "backend.apps.base_app",
    "backend.apps.base_skill",
}

APP_SPECIFIC_SHARED_IMPORTS = {
    "backend.apps.ai.processing.skill_executor": "backend/shared/python_utils or BaseSkill helper",
    "backend.apps.ai.processing.external_result_sanitizer": "backend/shared/python_utils",
    "backend.apps.ai.processing.celery_helpers": "backend/shared/python_utils or app-agnostic worker helper",
}

ENCRYPTION_SYNC_ALLOWANCE_MARKERS = ("KEYS-04", "getKeySync acceptable")
ENCRYPTION_APPROVED_DIRECT_CHAT_KEY_DECRYPTORS = {
    "frontend/packages/ui/src/services/encryption/ChatKeyManager.ts",
    "frontend/packages/ui/src/services/encryption/MetadataEncryptor.ts",
    "frontend/packages/ui/src/services/chatMetadataCache.ts",
    "frontend/packages/ui/src/services/db/chatCrudOperations.ts",
}

SETTINGS_ALLOWED_INLINE_STYLE_SUBSTRINGS = (
    "--",
    "mask-image: var(",
    "-webkit-mask-image: var(",
)

EXPORT_IMPORT_REQUIRED_PATTERNS = {
    "manifest freshness": re.compile(r"manifest", re.IGNORECASE),
    "import cache update": re.compile(r"cache|indexed|save", re.IGNORECASE),
    "chat key creation": re.compile(r"chatKey|chat_key|encrypt.*key|decrypt.*key", re.IGNORECASE),
    "embed normalization": re.compile(r"embed.*normal|normal.*embed|code.*embed", re.IGNORECASE),
}


@dataclass(frozen=True)
class Finding:
    audit: str
    rule_id: str
    severity: str
    file: str
    line: int
    title: str
    evidence: str
    recommendation: str


def _iter_files(root: Path, suffixes: tuple[str, ...]) -> Iterable[Path]:
    if not root.exists():
        return
    for path in root.rglob("*"):
        if not path.is_file() or path.suffix not in suffixes:
            continue
        if any(part in SKIP_DIR_NAMES for part in path.parts):
            continue
        yield path


def _rel(path: Path) -> str:
    return path.relative_to(REPO_ROOT).as_posix()


def _read_lines(path: Path) -> list[str]:
    try:
        return path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return []


def _window(lines: list[str], index: int, before: int = 2) -> str:
    start = max(0, index - before)
    return " ".join(line.strip() for line in lines[start : index + 1])[:500]


def _add(
    findings: list[Finding],
    *,
    audit: str,
    rule_id: str,
    severity: str,
    file: str,
    line: int,
    title: str,
    evidence: str,
    recommendation: str,
) -> None:
    findings.append(
        Finding(
            audit=audit,
            rule_id=rule_id,
            severity=severity,
            file=file,
            line=line,
            title=title,
            evidence=evidence.strip()[:500],
            recommendation=recommendation,
        )
    )


def audit_architecture_boundaries() -> list[Finding]:
    """Find imports that cross app/skill boundaries instead of shared modules."""
    findings: list[Finding] = []
    import_pattern = re.compile(r"^\s*(?:from|import)\s+(backend\.apps\.[\w.]+)")
    app_root = REPO_ROOT / "backend" / "apps"

    for path in _iter_files(app_root, (".py",)):
        rel = _rel(path)
        parts = path.relative_to(app_root).parts
        if not parts:
            continue
        current_app = parts[0]
        in_skill = "skills" in parts
        in_provider = "providers" in parts

        for line_num, line in enumerate(_read_lines(path), 1):
            match = import_pattern.match(line)
            if not match:
                continue
            module = match.group(1).rstrip(".")
            imported_parts = module.split(".")
            if len(imported_parts) < 3:
                continue
            imported_app = imported_parts[2]

            if module in BACKEND_APP_SHARED_IMPORT_ALLOWLIST:
                continue
            if imported_app == current_app:
                continue

            if module in APP_SPECIFIC_SHARED_IMPORTS:
                _add(
                    findings,
                    audit="architecture-boundaries",
                    rule_id="ARCH-CROSS-APP-SHARED-HELPER",
                    severity="high" if in_skill or in_provider else "medium",
                    file=rel,
                    line=line_num,
                    title="App code imports shared helper from another app namespace",
                    evidence=line,
                    recommendation=f"Move or import this helper from {APP_SPECIFIC_SHARED_IMPORTS[module]} instead of {module}.",
                )
            elif in_skill or in_provider:
                _add(
                    findings,
                    audit="architecture-boundaries",
                    rule_id="ARCH-CROSS-APP-IMPORT",
                    severity="medium",
                    file=rel,
                    line=line_num,
                    title="Skill/provider imports another backend app directly",
                    evidence=line,
                    recommendation="Keep app skills isolated. Move reusable behavior to backend/shared, BaseSkill, or a shared provider wrapper.",
                )
    return findings


def audit_encryption_key_paths() -> list[Finding]:
    """Find high-risk chat key access and encryption path patterns."""
    findings: list[Finding] = []
    src_root = REPO_ROOT / "frontend" / "packages" / "ui" / "src"

    for path in _iter_files(src_root, (".ts", ".svelte")):
        rel = _rel(path)
        lines = _read_lines(path)
        for index, line in enumerate(lines):
            stripped = line.strip()
            if "getKeySync(" in stripped:
                context = _window(lines, index, 3)
                has_allowance = any(marker in context for marker in ENCRYPTION_SYNC_ALLOWANCE_MARKERS)
                severity = "low" if has_allowance else "high"
                title = "Synchronous chat key access is justified" if has_allowance else "Synchronous chat key access lacks an explicit allowance"
                _add(
                    findings,
                    audit="encryption-key-paths",
                    rule_id="ENC-GET-KEY-SYNC",
                    severity=severity,
                    file=rel,
                    line=index + 1,
                    title=title,
                    evidence=context,
                    recommendation="Prefer async chatKeyManager.getKey()/withKey for content decrypt paths. If sync access is safe, keep a nearby KEYS-04 justification.",
                )
            if "decryptChatKeyWithMasterKey" in stripped and rel not in ENCRYPTION_APPROVED_DIRECT_CHAT_KEY_DECRYPTORS:
                _add(
                    findings,
                    audit="encryption-key-paths",
                    rule_id="ENC-DIRECT-CHAT-KEY-DECRYPT",
                    severity="medium",
                    file=rel,
                    line=index + 1,
                    title="Direct chat key unwrap outside approved key-management modules",
                    evidence=stripped,
                    recommendation="Route chat key loading through ChatKeyManager or add this file to the approved key-management allowlist with architectural justification.",
                )
    return findings


def _tag_has_data_testid(tag_text: str) -> bool:
    return "data-testid" in tag_text


def _collect_tag(lines: list[str], start_index: int) -> tuple[str, int]:
    tag = lines[start_index].strip()
    index = start_index
    while ">" not in tag and index + 1 < len(lines):
        index += 1
        tag += " " + lines[index].strip()
    return tag, index


def audit_settings_ui_contract() -> list[Finding]:
    """Find deterministic settings UI contract violations."""
    findings: list[Finding] = []
    settings_root = REPO_ROOT / "frontend" / "packages" / "ui" / "src" / "components" / "settings"
    hardcoded_color = re.compile(r"#[0-9a-fA-F]{3,8}\b|\brgba?\(|\bhsla?\(")
    interactive_tag = re.compile(r"<\s*(button|input|select|textarea)\b")

    for path in _iter_files(settings_root, (".svelte",)):
        rel = _rel(path)
        lines = _read_lines(path)
        in_style_block = False
        for index, line in enumerate(lines):
            stripped = line.strip()
            if stripped.startswith("<style"):
                in_style_block = True
            if "</style>" in stripped:
                in_style_block = False

            if "style=" in stripped:
                allowed = any(fragment in stripped for fragment in SETTINGS_ALLOWED_INLINE_STYLE_SUBSTRINGS)
                if not allowed:
                    _add(
                        findings,
                        audit="settings-ui-contract",
                        rule_id="SETTINGS-INLINE-STYLE",
                        severity="medium",
                        file=rel,
                        line=index + 1,
                        title="Settings UI uses an inline style",
                        evidence=stripped,
                        recommendation="Use canonical settings/elements components or CSS classes/tokens instead of inline styles.",
                    )

            if hardcoded_color.search(stripped) and not stripped.startswith("//"):
                _add(
                    findings,
                    audit="settings-ui-contract",
                    rule_id="SETTINGS-HARDCODED-COLOR",
                    severity="medium" if in_style_block or "style=" in stripped else "low",
                    file=rel,
                    line=index + 1,
                    title="Settings UI contains a hardcoded color",
                    evidence=stripped,
                    recommendation="Use design-system CSS custom properties or canonical settings/elements components.",
                )

            if interactive_tag.search(stripped):
                tag_text, end_index = _collect_tag(lines, index)
                if not _tag_has_data_testid(tag_text):
                    _add(
                        findings,
                        audit="settings-ui-contract",
                        rule_id="SETTINGS-MISSING-TESTID",
                        severity="medium",
                        file=rel,
                        line=index + 1,
                        title="Settings interactive element lacks data-testid",
                        evidence=tag_text,
                        recommendation="Add a stable kebab-case data-testid for E2E and Apple parity mapping.",
                    )
                if end_index == index and "class=\"" in tag_text and "settings/elements" not in "\n".join(lines[:80]):
                    _add(
                        findings,
                        audit="settings-ui-contract",
                        rule_id="SETTINGS-ADHOC-CONTROL",
                        severity="low",
                        file=rel,
                        line=index + 1,
                        title="Settings UI may use an ad-hoc interactive control",
                        evidence=tag_text,
                        recommendation="Prefer canonical components from settings/elements for settings controls.",
                    )
    return findings


def _simple_yaml_provider_blocks(lines: list[str]) -> list[tuple[int, str, list[str]]]:
    blocks: list[tuple[int, str, list[str]]] = []
    provider_indent: int | None = None
    current_name = ""
    current_start = 0
    current_lines: list[str] = []
    in_providers = False

    for line_num, line in enumerate(lines, 1):
        stripped = line.strip()
        if stripped == "providers:":
            in_providers = True
            provider_indent = len(line) - len(line.lstrip())
            continue
        if not in_providers or provider_indent is None:
            continue
        indent = len(line) - len(line.lstrip())
        if stripped and indent <= provider_indent and not stripped.startswith("-"):
            break
        match = re.match(r"\s*-\s+id:\s*['\"]?([^'\"]+)['\"]?", line)
        if match:
            if current_name:
                blocks.append((current_start, current_name, current_lines))
            current_start = line_num
            current_name = match.group(1).strip()
            current_lines = [line]
        elif current_name:
            current_lines.append(line)
    if current_name:
        blocks.append((current_start, current_name, current_lines))
    return blocks


def audit_app_skill_contracts() -> list[Finding]:
    """Find deterministic app.yml/provider metadata contract drift."""
    findings: list[Finding] = []
    apps_root = REPO_ROOT / "backend" / "apps"

    for app_yml in _iter_files(apps_root, (".yml", ".yaml")):
        if app_yml.name != "app.yml":
            continue
        rel = _rel(app_yml)
        lines = _read_lines(app_yml)
        text = "\n".join(lines)
        app_dir = app_yml.parent
        app_id = app_dir.name

        if "skills:" in text and not (app_dir / "skills").exists():
            _add(
                findings,
                audit="app-skill-contracts",
                rule_id="APP-SKILLS-DIR-MISSING",
                severity="info",
                file=rel,
                line=1,
                title="app.yml declares skills but no skills directory exists",
                evidence="skills:",
                recommendation="Verify this is an intentionally metadata-only/planned app. If implemented, add the matching backend/apps/<app>/skills module.",
            )

        for start_line, provider_id, block_lines in _simple_yaml_provider_blocks(lines):
            block = "\n".join(block_lines)
            has_auth_metadata = any(key in block for key in ("no_api_key:", "api_key_vault_path:", "api_key_env_var:"))
            if not has_auth_metadata:
                _add(
                    findings,
                    audit="app-skill-contracts",
                    rule_id="APP-PROVIDER-AUTH-METADATA",
                    severity="medium",
                    file=rel,
                    line=start_line,
                    title="Provider metadata lacks explicit auth/no-auth declaration",
                    evidence=f"provider {provider_id}",
                    recommendation="Add no_api_key: true or the provider's vault/env API-key metadata.",
                )
            if "logo_svg:" in block:
                logo_match = re.search(r"logo_svg:\s*['\"]?([^'\"\n]+)", block)
                if logo_match:
                    logo = logo_match.group(1).strip()
                    logo_path = REPO_ROOT / "frontend" / "packages" / "ui" / "static" / "icons" / logo
                    if logo.endswith(".svg") and not logo_path.exists():
                        _add(
                            findings,
                            audit="app-skill-contracts",
                            rule_id="APP-PROVIDER-ICON-MISSING",
                            severity="high",
                            file=rel,
                            line=start_line,
                            title="Provider logo_svg does not resolve to a static icon",
                            evidence=f"provider {provider_id} logo_svg: {logo}",
                            recommendation="Add the SVG under frontend/packages/ui/static/icons or update provider metadata.",
                        )

        skill_files = list((app_dir / "skills").glob("*.py")) if (app_dir / "skills").exists() else []
        if skill_files and "skills:" not in text:
            _add(
                findings,
                audit="app-skill-contracts",
                rule_id="APP-YML-SKILLS-MISSING",
                severity="medium",
                file=rel,
                line=1,
                title="Skill files exist but app.yml has no skills metadata",
                evidence=f"{app_id}/skills contains {len(skill_files)} Python file(s)",
                recommendation="Add matching skill metadata in app.yml so settings, Apps, and tool generation stay in sync.",
            )
    return findings


def audit_export_import_contract() -> list[Finding]:
    """Check account export/import files for required invariant coverage."""
    findings: list[Finding] = []
    candidate_roots = [
        REPO_ROOT / "frontend" / "packages" / "openmates-cli" / "src",
        REPO_ROOT / "frontend" / "packages" / "ui" / "src",
        REPO_ROOT / "backend" / "core" / "api" / "app" / "routes",
    ]
    candidate_files: list[Path] = []
    for root in candidate_roots:
        for path in _iter_files(root, (".ts", ".svelte", ".py")):
            rel = _rel(path)
            lower = rel.lower()
            if any(term in lower for term in ("export", "import", "manifest", "backup")):
                candidate_files.append(path)

    combined_text = "\n".join(path.read_text(encoding="utf-8", errors="replace") for path in candidate_files if path.exists())
    for label, pattern in EXPORT_IMPORT_REQUIRED_PATTERNS.items():
        if not pattern.search(combined_text):
            _add(
                findings,
                audit="export-import-contract",
                rule_id="EXPORT-INVARIANT-MISSING",
                severity="high",
                file="frontend/packages/openmates-cli/src/cli.ts",
                line=1,
                title=f"Export/import invariant not visible in static scan: {label}",
                evidence=label,
                recommendation="Add explicit code or fixture coverage for this invariant in export/import paths.",
            )

    for path in candidate_files:
        rel = _rel(path)
        lines = _read_lines(path)
        for index, line in enumerate(lines):
            lower_line = line.lower()
            if "export" in lower_line and "secret" in lower_line and "exclude" not in lower_line and "redact" not in lower_line:
                _add(
                    findings,
                    audit="export-import-contract",
                    rule_id="EXPORT-SECRET-MENTION",
                    severity="medium",
                    file=rel,
                    line=index + 1,
                    title="Export path references secrets without an obvious exclusion/redaction marker",
                    evidence=line.strip(),
                    recommendation="Verify secret/key material is excluded from exports or add an explicit exclusion comment/check.",
                )
    return findings


AUDITS = {
    "architecture-boundaries": audit_architecture_boundaries,
    "encryption-key-paths": audit_encryption_key_paths,
    "settings-ui-contract": audit_settings_ui_contract,
    "app-skill-contracts": audit_app_skill_contracts,
    "export-import-contract": audit_export_import_contract,
}


def build_report(selected_audits: list[str] | None = None) -> dict:
    audit_names = selected_audits or list(AUDITS)
    findings: list[Finding] = []
    for audit_name in audit_names:
        audit_func = AUDITS.get(audit_name)
        if audit_func is None:
            raise ValueError(f"Unknown audit: {audit_name}")
        findings.extend(audit_func())

    findings_sorted_all = sorted(
        findings,
        key=lambda item: (-SEVERITY_ORDER[item.severity], item.audit, item.file, item.line, item.rule_id),
    )
    by_severity_all = Counter(item.severity for item in findings_sorted_all)
    by_audit_all = Counter(item.audit for item in findings_sorted_all)
    by_rule_all = Counter(item.rule_id for item in findings_sorted_all)
    by_audit_severity_all: dict[str, dict[str, int]] = {}
    for item in findings_sorted_all:
        audit_counts = by_audit_severity_all.setdefault(item.audit, {severity: 0 for severity in SEVERITY_ORDER})
        audit_counts[item.severity] += 1

    emitted: list[Finding] = []
    emitted_by_rule: Counter[str] = Counter()
    for finding in findings_sorted_all:
        if emitted_by_rule[finding.rule_id] >= MAX_FINDINGS_PER_RULE:
            continue
        emitted.append(finding)
        emitted_by_rule[finding.rule_id] += 1

    omitted_by_rule = {
        rule_id: count - emitted_by_rule.get(rule_id, 0)
        for rule_id, count in by_rule_all.items()
        if count > emitted_by_rule.get(rule_id, 0)
    }

    return {
        "job": "contract-audits",
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "summary": {
            "total_findings": len(findings_sorted_all),
            "emitted_findings": len(emitted),
            "max_findings_per_rule": MAX_FINDINGS_PER_RULE,
            "omitted_by_rule": omitted_by_rule,
            "counts_by_severity": {severity: by_severity_all.get(severity, 0) for severity in SEVERITY_ORDER},
            "counts_by_audit": dict(sorted(by_audit_all.items())),
            "counts_by_audit_severity": dict(sorted(by_audit_severity_all.items())),
            "counts_by_rule": dict(sorted(by_rule_all.items())),
        },
        "findings": [asdict(finding) for finding in emitted],
    }


def severity_at_or_above(severity: str, threshold: str) -> bool:
    return SEVERITY_ORDER[severity] >= SEVERITY_ORDER[threshold]


def should_fail(report: dict, threshold: str | None) -> bool:
    if threshold is None:
        return False
    return any(severity_at_or_above(item["severity"], threshold) for item in report.get("findings", []))
