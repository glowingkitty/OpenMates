#!/usr/bin/env python3
"""Validate app skill provider metadata contracts.

The audit checks provider references, provider YAML metadata, and frontend icon
paths with deterministic file graph rules. It is designed for hooks and skills
that add APIs, app skills, providers, or Apps examples.
Architecture context: docs/architecture/apps/app-skills.md
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml


REPO_ROOT = Path(__file__).resolve().parent.parent
APPS_ROOT = REPO_ROOT / "backend" / "apps"
PROVIDERS_ROOT = REPO_ROOT / "backend" / "providers"
UI_STATIC_ROOT = REPO_ROOT / "frontend" / "packages" / "ui" / "static"
PRIVACY_POLICY_PATH = REPO_ROOT / "shared" / "docs" / "privacy_policy.yml"
TRAINING_POLICY_PATH = REPO_ROOT / "shared" / "docs" / "provider_training_policies.yml"
LEGAL_LINKS_PATH = REPO_ROOT / "frontend" / "packages" / "ui" / "src" / "config" / "links.ts"
LEGAL_CONTENT_PATH = REPO_ROOT / "frontend" / "packages" / "ui" / "src" / "legal" / "buildLegalContent.ts"
LEGAL_I18N_PATH = REPO_ROOT / "frontend" / "packages" / "ui" / "src" / "i18n" / "sources" / "legal" / "privacy.yml"
GENERATED_TRAINING_PATH = REPO_ROOT / "frontend" / "packages" / "ui" / "src" / "legal" / "trainingPolicies.generated.ts"
VIRTUAL_PROVIDER_IDS = {"pretalx"}


@dataclass(frozen=True)
class AuditIssue:
    path: str
    message: str


def _git(args: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["git", *args], cwd=REPO_ROOT, capture_output=True, text=True, check=False)


def _staged_paths() -> list[Path]:
    result = _git(["diff", "--cached", "--name-only", "--diff-filter=ACMR"])
    return [REPO_ROOT / line.strip() for line in result.stdout.splitlines() if line.strip()]


def _load_yaml(path: Path) -> Any:
    try:
        return yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as exc:
        return {"__yaml_error__": str(exc)}


def _rel(path: Path) -> str:
    try:
        return str(path.relative_to(REPO_ROOT))
    except ValueError:
        return str(path)


def _privacy_provider(data: Any, provider_id: str) -> dict[str, Any] | None:
    if not isinstance(data, dict):
        return None
    groups = data.get("provider_groups")
    if not isinstance(groups, dict):
        return None
    for group in groups.values():
        if not isinstance(group, dict):
            continue
        providers = group.get("providers")
        if isinstance(providers, dict) and isinstance(providers.get(provider_id), dict):
            return providers[provider_id]
    return None


def provider_files() -> list[Path]:
    return sorted([*PROVIDERS_ROOT.glob("*.yml"), *PROVIDERS_ROOT.glob("*.yaml")])


def app_files() -> list[Path]:
    return sorted(APPS_ROOT.glob("*/app.yml"))


def load_provider_ids() -> dict[str, Path]:
    providers: dict[str, Path] = {}
    for path in provider_files():
        data = _load_yaml(path)
        if isinstance(data, dict) and "__yaml_error__" not in data:
            provider_id = str(data.get("provider_id") or path.stem).strip()
            if provider_id:
                providers[provider_id] = path
    return providers


def load_provider_names() -> dict[str, str]:
    names: dict[str, str] = {}
    for path in provider_files():
        data = _load_yaml(path)
        if isinstance(data, dict) and "__yaml_error__" not in data:
            provider_id = str(data.get("provider_id") or path.stem).strip()
            name = str(data.get("name") or "").strip().lower()
            if provider_id and name:
                names[name] = provider_id
    return names


def audit_provider_file(path: Path) -> list[AuditIssue]:
    issues: list[AuditIssue] = []
    data = _load_yaml(path)
    rel = _rel(path)
    if not isinstance(data, dict):
        return [AuditIssue(rel, "provider YAML must be a mapping")]
    if "__yaml_error__" in data:
        return [AuditIssue(rel, f"invalid provider YAML: {data['__yaml_error__']}")]

    provider_id = str(data.get("provider_id") or path.stem).strip()
    if not provider_id:
        issues.append(AuditIssue(rel, "missing provider_id"))
    elif provider_id != path.stem:
        issues.append(AuditIssue(rel, f"provider_id '{provider_id}' should match filename '{path.stem}'"))

    required_fields = ("name", "description") if provider_id == "openmates" else ("name", "description", "privacy_policy")
    for required in required_fields:
        if not str(data.get(required) or "").strip():
            issues.append(AuditIssue(rel, f"missing required provider metadata field: {required}"))

    logo = str(data.get("logo_svg") or f"icons/{path.stem}.svg").strip().replace("logos/", "icons/", 1)
    if logo:
        icon_path = UI_STATIC_ROOT / logo
        if not icon_path.is_file():
            issues.append(AuditIssue(rel, f"logo_svg points to missing frontend static asset: {logo}"))

    privacy_policy = str(data.get("privacy_policy") or "")
    if privacy_policy and not privacy_policy.startswith("https://"):
        issues.append(AuditIssue(rel, "privacy_policy must use https://"))

    if data.get("requires_training_disclosure"):
        training_data = _load_yaml(TRAINING_POLICY_PATH)
        training_providers = training_data.get("providers", {}) if isinstance(training_data, dict) else {}
        privacy_entry = _privacy_provider(_load_yaml(PRIVACY_POLICY_PATH), provider_id)
        links_text = LEGAL_LINKS_PATH.read_text(encoding="utf-8")
        legal_text = LEGAL_CONTENT_PATH.read_text(encoding="utf-8")
        i18n_data = _load_yaml(LEGAL_I18N_PATH)
        generated_text = GENERATED_TRAINING_PATH.read_text(encoding="utf-8")
        expected_i18n_key = f"providers.model_generation.{provider_id}.description"
        disclosure_surfaces = (
            (
                TRAINING_POLICY_PATH,
                isinstance(training_providers.get(provider_id), dict)
                and training_providers[provider_id].get("policy_url") == privacy_policy,
            ),
            (
                PRIVACY_POLICY_PATH,
                isinstance(privacy_entry, dict) and privacy_entry.get("privacy_policy") == privacy_policy,
            ),
            (
                LEGAL_LINKS_PATH,
                bool(re.search(rf"\b{re.escape(provider_id)}:\s*[\"']{re.escape(privacy_policy)}[\"']", links_text)),
            ),
            (LEGAL_CONTENT_PATH, f"providers.model_generation.{provider_id}" in legal_text),
            (LEGAL_I18N_PATH, isinstance(i18n_data, dict) and expected_i18n_key in i18n_data),
            (
                GENERATED_TRAINING_PATH,
                f'"id":"{provider_id}"' in generated_text and privacy_policy in generated_text,
            ),
        )
        for disclosure_path, present in disclosure_surfaces:
            if not present:
                issues.append(
                    AuditIssue(rel, f"training disclosure is missing from {_rel(disclosure_path)}")
                )

    return issues


def _iter_skill_providers(app_data: dict[str, Any]) -> list[dict[str, Any]]:
    providers: list[dict[str, Any]] = []
    for skill in app_data.get("skills") or []:
        if not isinstance(skill, dict):
            continue
        for provider in skill.get("providers") or []:
            if isinstance(provider, dict):
                providers.append(provider)
    return providers


def audit_app_file(path: Path, known_provider_ids: set[str], known_provider_names: set[str]) -> list[AuditIssue]:
    issues: list[AuditIssue] = []
    data = _load_yaml(path)
    rel = _rel(path)
    if not isinstance(data, dict):
        return [AuditIssue(rel, "app.yml must be a mapping")]
    if "__yaml_error__" in data:
        return [AuditIssue(rel, f"invalid app YAML: {data['__yaml_error__']}")]

    for provider in _iter_skill_providers(data):
        provider_id = str(provider.get("id") or "").strip()
        provider_name = str(provider.get("name") or provider_id or "<unnamed>")
        if not provider_id:
            if provider_name == "<unnamed>":
                issues.append(AuditIssue(rel, "provider entry is missing name or id"))
            continue
        if provider_id not in known_provider_ids and provider_id not in VIRTUAL_PROVIDER_IDS:
            issues.append(AuditIssue(rel, f"provider '{provider_name}' references missing backend/providers/{provider_id}.yml"))
        has_key = bool(provider.get("api_key_vault_path"))
        no_key = bool(provider.get("no_api_key"))
        if has_key == no_key and (has_key or no_key or bool(provider_id) or provider_name.lower() in known_provider_names):
            issues.append(AuditIssue(rel, f"provider '{provider_name}' must set exactly one of api_key_vault_path or no_api_key"))

    return issues


def audit_paths(paths: list[Path]) -> list[AuditIssue]:
    known_provider_ids = set(load_provider_ids())
    known_provider_names = set(load_provider_names())
    relevant_apps: set[Path] = set()
    relevant_providers: set[Path] = set()

    for path in paths:
        resolved = path.resolve()
        if resolved.name == "app.yml" and APPS_ROOT in resolved.parents:
            relevant_apps.add(resolved)
        elif PROVIDERS_ROOT in resolved.parents and resolved.suffix in {".yml", ".yaml"}:
            relevant_providers.add(resolved)

    issues: list[AuditIssue] = []
    for path in sorted(relevant_providers):
        issues.extend(audit_provider_file(path))
    for path in sorted(relevant_apps):
        issues.extend(audit_app_file(path, known_provider_ids, known_provider_names))
    return issues


def required_paths(app_ids: list[str], provider_ids: list[str]) -> tuple[list[Path], list[AuditIssue]]:
    paths: list[Path] = []
    issues: list[AuditIssue] = []
    for app_id in app_ids:
        path = APPS_ROOT / app_id / "app.yml"
        if path.is_file():
            paths.append(path)
        else:
            issues.append(AuditIssue(_rel(path), f"required app metadata is missing for '{app_id}'"))
    for provider_id in provider_ids:
        path = PROVIDERS_ROOT / f"{provider_id}.yml"
        if path.is_file():
            paths.append(path)
        else:
            issues.append(AuditIssue(_rel(path), f"required provider metadata is missing for '{provider_id}'"))
    return paths, issues


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Audit app/provider metadata contracts.")
    parser.add_argument("paths", nargs="*", help="Specific app/provider files to audit. Defaults to staged relevant files.")
    parser.add_argument("--all", action="store_true", help="Audit all app.yml and backend provider YAML files.")
    parser.add_argument("--require-app", action="append", default=[], help="Require and audit an app ID.")
    parser.add_argument("--require-provider", action="append", default=[], help="Require and audit a provider ID.")
    args = parser.parse_args(argv)

    if args.all:
        paths = [*app_files(), *provider_files()]
    elif args.paths:
        paths = [REPO_ROOT / path for path in args.paths]
    else:
        paths = _staged_paths()

    required, issues = required_paths(args.require_app, args.require_provider)
    paths.extend(required)
    issues.extend(audit_paths(paths))
    if issues:
        print("[app-provider-contracts] Issues found:", file=sys.stderr)
        for issue in issues[:80]:
            print(f"  - {issue.path}: {issue.message}", file=sys.stderr)
        if len(issues) > 80:
            print(f"  - ... {len(issues) - 80} more issue(s)", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
