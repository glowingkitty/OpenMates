#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Generate OpenMates release-intelligence artifacts.

The primary output is an LLM-written natural-language summary for daily and
weekly communication planning. Deterministic git collection and release-status
checks remain in the artifact as grounding evidence so PR, release, newsletter,
and social workflows can audit every claim before users see it.
"""

from __future__ import annotations

import argparse
import importlib
import json
import os
import subprocess
import sys
import time
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from urllib import error, request

import yaml


REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

_feature_availability = importlib.import_module(
    "backend.core.api.app.services.feature_availability_service"
)
FeatureAvailabilityService = _feature_availability.FeatureAvailabilityService
PLATFORM_FEATURES = _feature_availability.PLATFORM_FEATURES
collect_feature_definitions_from_app_config = _feature_availability.collect_feature_definitions_from_app_config
DEFAULT_DAILY_DIR = REPO_ROOT / "docs" / "releases" / "daily"
DEFAULT_WEEKLY_DIR = REPO_ROOT / "docs" / "releases" / "weekly"
DEFAULT_MONTHLY_DIR = REPO_ROOT / "docs" / "releases" / "monthly"
DEFAULT_MAIN_REF = "origin/main"
DEFAULT_DEV_REF = "origin/dev"
DEFAULT_GEMINI_MODEL = "gemini-3-flash-preview"
DEFAULT_LLM_RETRIES = 2

SECTION_ORDER = [
    "features",
    "bug_fixes",
    "improvements",
    "docs",
    "tests",
    "infrastructure",
    "internal",
    "other",
]

SECTION_LABELS = {
    "features": "New features",
    "bug_fixes": "Bug fixes",
    "improvements": "Improvements",
    "docs": "Documentation",
    "tests": "Tests",
    "infrastructure": "Infrastructure",
    "internal": "Internal work",
    "other": "Other changes",
}

USER_FACING_PATH_HINTS = (
    "frontend/packages/ui/src/components/",
    "frontend/packages/ui/src/stores/",
    "frontend/apps/web_app/",
    "frontend/packages/openmates-cli/",
    "packages/openmates-python/",
    "backend/apps/",
    "backend/core/api/app/routes/",
    "apple/OpenMates/",
    "apple/OpenMatesWatch/",
    "apple/OpenMatesWatchExtension/",
)

INTERNAL_PATH_HINTS = (
    ".github/",
    ".agents/",
    ".claude/",
    "scripts/",
    "backend/tests/",
    "frontend/apps/web_app/tests/",
    "test-results/",
)

FEATURE_FLAG_PATH_HINTS = (
    "app.yml",
    "apps.yml",
    "feature_availability",
    "feature-flags",
    "feature_flags",
    "availability",
    "metadata",
)

FEATURE_PATH_MAP = {
    "app:workflows": (
        "backend/apps/workflows/",
    ),
    "platform:apple-watch": (
        "apple/OpenMatesWatch/",
        "apple/OpenMatesWatchExtension/",
        "apple/OpenMatesShared/",
        "apple/OpenMates/Sources/Core/Watch/",
        "apple/OpenMates/Sources/Features/Auth/ViewModels/PairLoginRuntime.swift",
        "apple/OpenMatesTests/Watch",
        "apple/OpenMatesUITests/Watch",
    ),
    "platform:ios": (
        "apple/OpenMates/",
        "apple/OpenMatesTests/",
        "apple/OpenMatesUITests/",
        "apple/OpenMatesShareExtension/",
        "apple/OpenMatesNotificationService/",
        "apple/OpenMatesShared/",
        "apple/OpenMates.xcodeproj/",
        "apple/project.yml",
    ),
    "platform:macos": (
        "apple/OpenMates/",
        "apple/OpenMatesTests/",
        "apple/OpenMatesUITests/",
        "apple/OpenMatesShareExtensionMacOS/",
        "apple/OpenMatesShared/",
        "apple/OpenMates.xcodeproj/",
        "apple/project.yml",
    ),
    "platform:plans": (
        "backend/core/api/app/routes/user_plans.py",
        "backend/core/api/app/services/user_plan",
        "frontend/packages/ui/src/services/userPlanService.ts",
    ),
    "platform:projects": (
        "backend/core/api/app/routes/projects.py",
        "frontend/packages/ui/src/components/projects/",
        "frontend/packages/ui/src/components/settings/SettingsProjects.svelte",
        "frontend/packages/ui/src/services/project",
    ),
    "platform:tasks": (
        "backend/core/api/app/routes/tasks_api.py",
        "backend/core/api/app/routes/user_tasks.py",
        "backend/core/api/app/services/user_task",
        "frontend/packages/ui/src/components/tasks/",
        "frontend/packages/ui/src/services/userTaskService.ts",
    ),
    "platform:teams": (
        "backend/core/api/app/routes/teams.py",
        "backend/core/api/app/services/team_",
        "backend/core/directus/schemas/teams.yml",
    ),
    "platform:workflows": (
        "backend/apps/workflows/",
        "backend/core/api/app/routes/workflows.py",
        "backend/core/api/app/services/workflow_",
        "frontend/apps/web_app/src/routes/workflows/",
        "frontend/apps/web_app/tests/workflows-",
        "frontend/packages/ui/src/stores/workflowWorkspaceStore.ts",
    ),
}

FEATURE_SUBJECT_HINTS = {
    "app:workflows": ("(workflows)", "workflow input", "workflows input", "workflow workspace", "workflows workspace"),
    "platform:plans": ("user plan", "user plans", "planning workspace"),
    "platform:projects": ("project workspace", "projects workspace", "project browser", "remote source"),
    "platform:tasks": ("task workspace", "tasks workspace", "task board", "user task", "user tasks"),
    "platform:teams": ("team workspace", "teams workspace", "team invite", "team member", "team billing"),
    "platform:workflows": ("(workflows)", "workflow input", "workflows input", "workflow workspace", "workflows workspace"),
}

READY_COMMUNICATION_STATUS = "ready_for_public_communication"
NOT_USER_FACING_COMMUNICATION_STATUS = "not_user_facing"
UNRELEASED_FEATURE_COMMUNICATION_STATUS = "unreleased_feature"
DEV_ONLY_COMMUNICATION_STATUS = "dev_only"
UNKNOWN_RELEASE_COMMUNICATION_STATUS = "unknown_release_status"

THEME_HINTS = {
    "chat": ("chat", "message", "composer", "activechat", "chathistory"),
    "apple": ("apple/", "ios", "watch", "testflight", "swift"),
    "cli_sdk": ("cli", "sdk", "openmates-cli", "openmates-python", "pypi", "npm"),
    "settings": ("settings", "preferences", "footer"),
    "self_hosting": ("self-host", "selfhost", "docker", "ghcr", "image publish"),
    "security": ("security", "vulnerability", "dependency", "dependabot"),
    "infrastructure": ("ci", "build", "vercel", "workflow", "runtime", "node"),
    "docs": ("docs/", "readme", "documentation"),
}


class NoAliasDumper(yaml.SafeDumper):
    def ignore_aliases(self, data: object) -> bool:
        return True


class ReleaseSummaryError(RuntimeError):
    """Raised when LLM summary generation fails."""


@dataclass(frozen=True)
class CommitChange:
    sha: str
    short_sha: str
    authored_at: str
    subject: str
    body: str
    changed_paths: list[str]
    in_main: bool
    in_dev: bool


def load_gemini_api_key() -> str | None:
    for name in ("GEMINI_API_KEY", "SECRET__GOOGLE_AI_STUDIO__API_KEY"):
        value = os.environ.get(name, "").strip()
        if value and value != "IMPORTED_TO_VAULT":
            return value

    env_path = REPO_ROOT / ".env"
    if env_path.exists():
        for line in env_path.read_text(encoding="utf-8").splitlines():
            stripped = line.strip()
            if not stripped or stripped.startswith("#") or "=" not in stripped:
                continue
            key, _, value = stripped.partition("=")
            if key.strip() in {"GEMINI_API_KEY", "SECRET__GOOGLE_AI_STUDIO__API_KEY"}:
                cleaned = value.strip().strip('"').strip("'")
                if cleaned and cleaned != "IMPORTED_TO_VAULT":
                    return cleaned
    return load_gemini_api_key_from_vault()


def read_dot_env() -> dict[str, str]:
    env_path = REPO_ROOT / ".env"
    values: dict[str, str] = {}
    if not env_path.exists():
        return values
    for line in env_path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, _, value = stripped.partition("=")
        values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def get_env(name: str, dot_env: dict[str, str] | None = None, default: str = "") -> str:
    value = os.environ.get(name, "").strip()
    if value:
        return value
    if dot_env is None:
        dot_env = read_dot_env()
    return dot_env.get(name, default).strip()


def load_gemini_api_key_from_vault() -> str | None:
    compose_file = REPO_ROOT / "backend" / "core" / "docker-compose.yml"
    env_file = REPO_ROOT / ".env"
    if not compose_file.exists():
        return None
    fetch_script = (
        "import asyncio\n"
        "from backend.core.api.app.utils.secrets_manager import SecretsManager\n"
        "from backend.apps.ai.llm_providers.google_client import _get_google_ai_studio_api_key\n"
        "async def main():\n"
        "    sm = SecretsManager()\n"
        "    await sm.initialize()\n"
        "    key = await _get_google_ai_studio_api_key(sm)\n"
        "    print(key or '', end='')\n"
        "asyncio.run(main())\n"
    )
    command = ["docker", "compose"]
    if env_file.exists():
        command.extend(["--env-file", str(env_file)])
    command.extend(["-f", str(compose_file), "exec", "-T", "api", "python3", "-c", fetch_script])
    try:
        result = subprocess.run(command, cwd=REPO_ROOT, text=True, capture_output=True, timeout=20, check=False)
    except (OSError, subprocess.TimeoutExpired):
        return None
    key = result.stdout.strip()
    return key or None


def release_summary_schema() -> dict[str, Any]:
    evidence = {
        "type": "object",
        "properties": {
            "commits": {"type": "array", "items": {"type": "string"}},
        },
        "required": ["commits"],
    }
    item = {
        "type": "object",
        "properties": {
            "text": {"type": "string"},
            "evidence": evidence,
            "release_status": {"type": "string"},
        },
        "required": ["text", "evidence", "release_status"],
    }
    recommendation = {
        "type": "object",
        "properties": {
            "text": {"type": "string"},
            "evidence": evidence,
            "reason": {"type": "string"},
        },
        "required": ["text", "evidence", "reason"],
    }
    video_item = {
        "type": "object",
        "properties": {
            "idea": {"type": "string"},
            "priority": {"type": "string"},
            "reason": {"type": "string"},
            "evidence": evidence,
        },
        "required": ["idea", "priority", "reason", "evidence"],
    }
    return {
        "type": "object",
        "properties": {
            "overview": {"type": "string"},
            "released_changes": {"type": "array", "items": item},
            "bug_fixes": {"type": "array", "items": item},
            "unreleased_progress": {"type": "array", "items": item},
            "internal_progress": {"type": "array", "items": item},
            "newsletter_recommendation": {
                "type": "object",
                "properties": {
                    "include": {"type": "array", "items": recommendation},
                    "exclude": {"type": "array", "items": recommendation},
                    "rationale": {"type": "string"},
                },
                "required": ["include", "exclude", "rationale"],
            },
            "social_video_recommendations": {"type": "array", "items": video_item},
            "quality_notes": {"type": "array", "items": {"type": "string"}},
        },
        "required": [
            "overview",
            "released_changes",
            "bug_fixes",
            "unreleased_progress",
            "internal_progress",
            "newsletter_recommendation",
            "social_video_recommendations",
            "quality_notes",
        ],
    }


def call_gemini_summary(*, api_key: str, model: str, system_prompt: str, user_message: str) -> dict[str, Any]:
    tool = {
        "function_declarations": [
            {
                "name": "return_release_summary",
                "description": "Return a source-grounded OpenMates release intelligence summary.",
                "parameters": release_summary_schema(),
            }
        ]
    }
    payload = {
        "system_instruction": {"parts": [{"text": system_prompt}]},
        "contents": [{"role": "user", "parts": [{"text": user_message}]}],
        "tools": [tool],
        "tool_config": {"function_calling_config": {"mode": "ANY"}},
        "generationConfig": {"temperature": 0.2, "maxOutputTokens": 8192},
    }
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key}"
    body = json.dumps(payload).encode("utf-8")
    req = request.Request(url, data=body, headers={"Content-Type": "application/json"}, method="POST")
    try:
        with request.urlopen(req, timeout=120) as response:
            response_payload = json.loads(response.read().decode("utf-8"))
    except error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:500]
        raise ReleaseSummaryError(f"Gemini API error {exc.code}: {detail}") from exc
    except (OSError, json.JSONDecodeError) as exc:
        raise ReleaseSummaryError(f"Gemini request failed: {exc}") from exc

    try:
        parts = response_payload.get("candidates", [])[0].get("content", {}).get("parts", [])
    except (IndexError, AttributeError) as exc:
        raise ReleaseSummaryError("Gemini response did not include candidates") from exc
    for part in parts:
        function_call = part.get("functionCall") if isinstance(part, dict) else None
        if function_call and function_call.get("name") == "return_release_summary":
            return function_call.get("args") or {}
    text_response = "\n".join(part.get("text", "") for part in parts if isinstance(part, dict)).strip()
    if text_response:
        try:
            return json.loads(text_response)
        except json.JSONDecodeError as exc:
            raise ReleaseSummaryError("Gemini response was not valid JSON and did not include a function call") from exc
    raise ReleaseSummaryError("Gemini response did not include a release summary")


def run_git(args: list[str], *, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
        check=check,
    )


def git_output(args: list[str], *, check: bool = True) -> str:
    result = run_git(args, check=check)
    return result.stdout.strip()


def ref_exists(ref: str) -> bool:
    result = run_git(["rev-parse", "--verify", "--quiet", ref], check=False)
    return result.returncode == 0


def is_ancestor(commit_sha: str, ref: str) -> bool:
    if not ref_exists(ref):
        return False
    result = run_git(["merge-base", "--is-ancestor", commit_sha, ref], check=False)
    return result.returncode == 0


def collect_commits(
    *,
    since: str | None,
    until: str | None,
    from_ref: str | None,
    to_ref: str,
    main_ref: str,
    dev_ref: str,
) -> list[CommitChange]:
    range_args = [f"{from_ref}..{to_ref}"] if from_ref else [to_ref]
    command = ["log", "--format=%x1e%H%x1f%h%x1f%aI%x1f%s%x1f%b"]
    if since:
        command.append(f"--since={since}")
    if until:
        command.append(f"--until={until}")
    command.extend(range_args)

    raw = git_output(command)
    if not raw:
        return []

    commits: list[CommitChange] = []
    for record in raw.split("\x1e"):
        record = record.strip()
        if not record:
            continue
        parts = record.split("\x1f", 4)
        if len(parts) < 5:
            continue
        sha, short_sha, authored_at, subject, body = parts
        paths_raw = git_output(["diff-tree", "--no-commit-id", "--name-only", "-r", sha], check=False)
        changed_paths = sorted(path for path in paths_raw.splitlines() if path.strip())
        commits.append(
            CommitChange(
                sha=sha,
                short_sha=short_sha,
                authored_at=authored_at,
                subject=subject.strip(),
                body=body.strip(),
                changed_paths=changed_paths,
                in_main=is_ancestor(sha, main_ref),
                in_dev=is_ancestor(sha, dev_ref),
            )
        )
    return commits


def classify_section(commit: CommitChange) -> str:
    subject = commit.subject.lower()
    paths = commit.changed_paths

    if subject.startswith("feat"):
        return "features"
    if subject.startswith("fix"):
        return "bug_fixes"
    if subject.startswith(("improve", "perf", "refactor")):
        return "improvements"
    if subject.startswith("docs") or (paths and all(path.startswith("docs/") or path.endswith(".md") for path in paths)):
        return "docs"
    if subject.startswith("test") or (paths and all("test" in path or path.startswith("test-results/") for path in paths)):
        return "tests"
    if subject.startswith(("ci", "build", "chore")) or any(path.startswith((".github/", "deployment/")) for path in paths):
        return "infrastructure"
    if any(path.startswith(INTERNAL_PATH_HINTS) for path in paths):
        return "internal"
    return "other"


def is_user_facing(commit: CommitChange, section: str) -> bool:
    if section in {"docs", "tests", "infrastructure", "internal"}:
        return False
    return any(path.startswith(USER_FACING_PATH_HINTS) for path in commit.changed_paths)


def release_status(commit: CommitChange, *, assume_released: bool) -> str:
    if assume_released:
        return "released_override"
    if commit.in_main:
        return "released_main"
    if commit.in_dev:
        return "dev_only"
    return "unknown"


def changed_feature_metadata(commit: CommitChange) -> bool:
    return any(any(hint in Path(path).name.lower() for hint in FEATURE_FLAG_PATH_HINTS) for path in commit.changed_paths)


def load_backend_config() -> dict[str, Any]:
    config_path = REPO_ROOT / "backend" / "config" / "backend_config.yml"
    if not config_path.exists():
        return {}
    payload = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
    if not isinstance(payload, dict):
        raise ValueError(f"Expected mapping in {config_path}")
    return payload


def release_availability_config() -> dict[str, Any]:
    """Return feature config for public release communication.

    Release summaries must fail closed: local dev opt-ins for default-disabled
    features should not make work-in-progress surfaces newsletter-ready.
    Explicit disabled overrides still matter because they can turn off default-on
    product areas.
    """

    overrides = (load_backend_config().get("feature_overrides") or {})
    return {"feature_overrides": {"disabled": overrides.get("disabled") or []}}


def load_feature_availability_service() -> FeatureAvailabilityService:
    definitions = list(PLATFORM_FEATURES)
    apps_dir = REPO_ROOT / "backend" / "apps"
    if apps_dir.exists():
        for app_yml_path in sorted(apps_dir.glob("*/app.yml")):
            raw_config = yaml.safe_load(app_yml_path.read_text(encoding="utf-8")) or {}
            if not isinstance(raw_config, dict):
                continue
            app_id = app_yml_path.parent.name
            definitions.extend(collect_feature_definitions_from_app_config(app_id, raw_config, source=str(app_yml_path.relative_to(REPO_ROOT))))
    return FeatureAvailabilityService(definitions, release_availability_config())


def related_feature_ids_for_paths(paths: list[str]) -> list[str]:
    feature_ids: set[str] = set()
    for path in paths:
        for feature_id, prefixes in FEATURE_PATH_MAP.items():
            if any(path.startswith(prefix) for prefix in prefixes):
                feature_ids.add(feature_id)
    return sorted(feature_ids)


def related_feature_ids_for_commit(commit: CommitChange) -> list[str]:
    feature_ids = set(related_feature_ids_for_paths(commit.changed_paths))
    subject = commit.subject.lower()
    for feature_id, hints in FEATURE_SUBJECT_HINTS.items():
        if any(hint in subject for hint in hints):
            feature_ids.add(feature_id)
    return sorted(feature_ids)


def feature_explanations(feature_ids: list[str], service: FeatureAvailabilityService) -> list[dict[str, Any]]:
    explanations: list[dict[str, Any]] = []
    for feature_id in feature_ids:
        explanation = service.explain(feature_id)
        explanations.append(
            {
                "id": explanation.id,
                "kind": explanation.kind,
                "default_enabled": explanation.default_enabled,
                "effective_enabled": explanation.effective_enabled,
                "override": explanation.override,
                "parent_id": explanation.parent_id,
                "source": explanation.source,
            }
        )
    return explanations


def disabled_feature_context(service: FeatureAvailabilityService) -> list[dict[str, Any]]:
    context: list[dict[str, Any]] = []
    for feature_id in service.list_disabled_feature_ids():
        explanation = service.explain(feature_id)
        context.append(
            {
                "id": explanation.id,
                "kind": explanation.kind,
                "default_enabled": explanation.default_enabled,
                "effective_enabled": explanation.effective_enabled,
                "override": explanation.override,
                "parent_id": explanation.parent_id,
                "source": explanation.source,
            }
        )
    return context


def communication_status_for_item(*, status: str, user_facing: bool, related_features: list[dict[str, Any]]) -> str:
    if not user_facing:
        return NOT_USER_FACING_COMMUNICATION_STATUS
    if status == "dev_only":
        return DEV_ONLY_COMMUNICATION_STATUS
    if status == "unknown":
        return UNKNOWN_RELEASE_COMMUNICATION_STATUS
    if any(feature.get("effective_enabled") is False for feature in related_features):
        return UNRELEASED_FEATURE_COMMUNICATION_STATUS
    return READY_COMMUNICATION_STATUS


def item_for_commit(commit: CommitChange, *, assume_released: bool, availability_service: FeatureAvailabilityService) -> dict[str, Any]:
    section = classify_section(commit)
    status = release_status(commit, assume_released=assume_released)
    user_facing = is_user_facing(commit, section)
    related_features = feature_explanations(related_feature_ids_for_commit(commit), availability_service)
    communication_status = communication_status_for_item(status=status, user_facing=user_facing, related_features=related_features)
    newsletter_ready = user_facing and status in {"released_main", "released_override"} and communication_status == READY_COMMUNICATION_STATUS
    rationale: list[str] = [f"classified as {SECTION_LABELS[section].lower()} from commit subject/path rules"]
    if user_facing:
        rationale.append("contains user-facing product paths")
    if related_features:
        rationale.append("matches feature availability gates: " + ", ".join(feature["id"] for feature in related_features))
    if status == "released_main":
        rationale.append("commit is reachable from main")
    elif status == "dev_only":
        rationale.append("commit is not reachable from main, so it is not newsletter-ready")
    elif status == "released_override":
        rationale.append("release readiness was explicitly overridden by --assume-released")
    else:
        rationale.append("main/dev reachability is unknown, so release communication fails closed")
    if communication_status == UNRELEASED_FEATURE_COMMUNICATION_STATUS:
        disabled_ids = [feature["id"] for feature in related_features if feature.get("effective_enabled") is False]
        rationale.append("related feature is disabled or unreleased, so it is not newsletter-ready: " + ", ".join(disabled_ids))

    return {
        "title": commit.subject,
        "section": section,
        "commits": [commit.short_sha],
        "authored_at": commit.authored_at,
        "changed_paths": commit.changed_paths,
        "release_status": status,
        "communication_status": communication_status,
        "newsletter_ready": newsletter_ready,
        "user_facing": user_facing,
        "related_features": related_features,
        "feature_metadata_changed": changed_feature_metadata(commit),
        "rationale": rationale,
    }


def commit_refs_from_artifact(artifact: dict[str, Any]) -> set[str]:
    refs: set[str] = set()
    for commit in (artifact.get("sources") or {}).get("commits") or []:
        if isinstance(commit, dict):
            if commit.get("short_sha"):
                refs.add(str(commit["short_sha"]))
            if commit.get("sha"):
                refs.add(str(commit["sha"]))
    for item in (artifact.get("marketing_candidates") or {}).get("newsletter") or []:
        for commit in item.get("commits") or []:
            refs.add(str(commit))
    return refs


def commit_refs_from_daily_artifacts(daily_artifacts: list[dict[str, Any]]) -> set[str]:
    refs: set[str] = set()
    for artifact in daily_artifacts:
        refs |= commit_refs_from_artifact(artifact)
        for item in iter_daily_items(artifact):
            for commit in item.get("commits") or []:
                refs.add(str(commit))
    return refs


def commit_refs_from_rollup_artifacts(artifacts: list[dict[str, Any]]) -> set[str]:
    refs: set[str] = set()
    def visit(value: Any) -> None:
        if isinstance(value, dict):
            for key, item in value.items():
                if key == "commits" and isinstance(item, list):
                    for commit in item:
                        refs.add(str(commit))
                else:
                    visit(item)
        elif isinstance(value, list):
            for item in value:
                visit(item)

    for artifact in artifacts:
        visit(artifact)
    return refs


def normalize_summary(raw_summary: dict[str, Any], known_commits: set[str], newsletter_include_commits: set[str] | None = None) -> dict[str, Any]:
    summary = raw_summary if isinstance(raw_summary, dict) else {}
    normalized: dict[str, Any] = {
        "overview": str(summary.get("overview") or ""),
        "released_changes": _normalize_summary_items(summary.get("released_changes"), known_commits),
        "bug_fixes": _normalize_summary_items(summary.get("bug_fixes"), known_commits),
        "unreleased_progress": _normalize_summary_items(summary.get("unreleased_progress"), known_commits),
        "internal_progress": _normalize_summary_items(summary.get("internal_progress"), known_commits),
        "newsletter_recommendation": _normalize_newsletter_recommendation(
            summary.get("newsletter_recommendation"),
            known_commits,
            newsletter_include_commits or known_commits,
        ),
        "social_video_recommendations": _normalize_video_items(summary.get("social_video_recommendations"), known_commits),
        "quality_notes": [str(item) for item in summary.get("quality_notes") or [] if str(item).strip()],
        "validation_warnings": [],
    }
    _collect_summary_warnings(normalized)
    return normalized


def _normalize_summary_items(value: Any, known_commits: set[str]) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for item in value or []:
        if not isinstance(item, dict):
            continue
        items.append(
            {
                "text": str(item.get("text") or "").strip(),
                "evidence": {"commits": _known_commit_list((item.get("evidence") or {}).get("commits"), known_commits)},
                "release_status": str(item.get("release_status") or "unknown"),
            }
        )
    return [item for item in items if item["text"]]


def _normalize_newsletter_recommendation(value: Any, known_commits: set[str], include_commits: set[str]) -> dict[str, Any]:
    recommendation = value if isinstance(value, dict) else {}
    include_items = _normalize_recommendation_items(recommendation.get("include"), include_commits)
    return {
        "include": [item for item in include_items if item.get("evidence", {}).get("commits")],
        "exclude": _normalize_recommendation_items(recommendation.get("exclude"), known_commits),
        "rationale": str(recommendation.get("rationale") or ""),
    }


def _normalize_recommendation_items(value: Any, known_commits: set[str]) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for item in value or []:
        if not isinstance(item, dict):
            continue
        items.append(
            {
                "text": str(item.get("text") or "").strip(),
                "evidence": {"commits": _known_commit_list((item.get("evidence") or {}).get("commits"), known_commits)},
                "reason": str(item.get("reason") or ""),
            }
        )
    return [item for item in items if item["text"]]


def _normalize_video_items(value: Any, known_commits: set[str]) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for item in value or []:
        if not isinstance(item, dict):
            continue
        items.append(
            {
                "idea": str(item.get("idea") or "").strip(),
                "priority": str(item.get("priority") or "medium"),
                "reason": str(item.get("reason") or ""),
                "evidence": {"commits": _known_commit_list((item.get("evidence") or {}).get("commits"), known_commits)},
            }
        )
    return [item for item in items if item["idea"]]


def _known_commit_list(value: Any, known_commits: set[str]) -> list[str]:
    commits: list[str] = []
    for commit in value or []:
        raw = str(commit).strip()
        if raw in known_commits and raw not in commits:
            commits.append(raw)
    return commits


def _collect_summary_warnings(summary: dict[str, Any]) -> None:
    warnings: list[str] = summary["validation_warnings"]
    for section in ("released_changes", "bug_fixes", "unreleased_progress", "internal_progress"):
        for item in summary.get(section) or []:
            if not item.get("evidence", {}).get("commits"):
                warnings.append(f"{section} item lacks known commit evidence: {item.get('text', '')[:120]}")
    for section in ("include", "exclude"):
        for item in summary.get("newsletter_recommendation", {}).get(section) or []:
            if not item.get("evidence", {}).get("commits"):
                warnings.append(f"newsletter {section} item lacks known commit evidence: {item.get('text', '')[:120]}")
    for item in summary.get("social_video_recommendations") or []:
        if not item.get("evidence", {}).get("commits"):
            warnings.append(f"social/video idea lacks known commit evidence: {item.get('idea', '')[:120]}")


def llm_system_prompt(cadence: str) -> str:
    weekly_detail_rule = "- For weekly summaries, be more extensive than daily summaries: include 6-10 released changes when evidence supports them, 6-10 bug fixes, 6-10 unreleased-progress bullets, and clear newsletter include/exclude rationale.\n" if cadence == "weekly" else ""
    return f"""You write OpenMates release intelligence summaries for {cadence} communication planning.

Rules:
- Write natural language analysis, not a commit dump.
- Use neutral authorship language. Do not write "the team", "we", "our team", or imply multiple people worked on OpenMates.
- Prefer phrases like "OpenMates added", "the project now", "this update", or passive voice when describing work.
- Group related commits into product-level themes.
- Every bullet must cite only commit IDs present in the input evidence.
- Newsletter include items must be released_main or released_override only.
- Newsletter include items must have communication_status ready_for_public_communication only.
- Disabled or unreleased features may appear only under unreleased_progress or newsletter exclusions.
- Treat every feature listed in feature_availability.disabled_features as unreleased unless an input item explicitly has communication_status ready_for_public_communication.
- Workflows, projects, tasks, plans, teams, iOS, macOS, and Apple Watch are unreleased if listed in disabled_features.
- Dev-only work may appear only under unreleased_progress or newsletter exclusions.
- Keep internal/testing/CI details concise unless they affect users.
- Suggest social/video ideas only when there is a concrete product story to show.
- Do not make privacy/security claims beyond the input evidence.
{weekly_detail_rule}
"""


def daily_llm_user_message(source: dict[str, Any]) -> str:
    return "Summarize these OpenMates changes from one day. Return the function-call JSON only.\n\n" + json.dumps(source, indent=2)


def weekly_llm_user_message(source: dict[str, Any]) -> str:
    return "Summarize these dated OpenMates daily summaries into one detailed weekly communication analysis. Preserve progression over dates, use neutral single-maintainer-safe wording, and keep disabled features out of released/newsletter include sections. Return the function-call JSON only.\n\n" + json.dumps(source, indent=2)


def monthly_llm_user_message(source: dict[str, Any]) -> str:
    return "Summarize these dated OpenMates weekly summaries into one monthly communication analysis. Preserve progression over weeks, use neutral single-maintainer-safe wording, and keep disabled features out of released/newsletter include sections. Return the function-call JSON only.\n\n" + json.dumps(source, indent=2)


def generate_llm_summary(
    *,
    cadence: str,
    source: dict[str, Any],
    known_commits: set[str],
    model: str,
    api_key: str | None,
    retries: int = DEFAULT_LLM_RETRIES,
) -> dict[str, Any]:
    if not api_key:
        raise ReleaseSummaryError("Gemini API key not found. Set GEMINI_API_KEY or SECRET__GOOGLE_AI_STUDIO__API_KEY.")
    if cadence == "daily":
        user_message = daily_llm_user_message(source)
    elif cadence == "weekly":
        user_message = weekly_llm_user_message(source)
    else:
        user_message = monthly_llm_user_message(source)
    last_error: ReleaseSummaryError | None = None
    for attempt in range(retries + 1):
        try:
            raw = call_gemini_summary(
                api_key=api_key,
                model=model,
                system_prompt=llm_system_prompt(cadence),
                user_message=user_message,
            )
            break
        except ReleaseSummaryError as exc:
            last_error = exc
            if attempt >= retries:
                raise
            time.sleep(2 * (attempt + 1))
    else:
        raise last_error or ReleaseSummaryError("Gemini summary generation failed")
    return normalize_summary(raw, known_commits, newsletter_include_commits_from_source(source))


def newsletter_include_commits_from_source(source: dict[str, Any]) -> set[str]:
    refs: set[str] = set()
    for item in (source.get("marketing_candidates") or {}).get("newsletter") or []:
        for commit in item.get("commits") or []:
            refs.add(str(commit))
    for daily in source.get("daily_summaries") or []:
        for item in (daily.get("marketing_candidates") or {}).get("newsletter") or []:
            for commit in item.get("commits") or []:
                refs.add(str(commit))
    return refs


def build_daily_llm_source(artifact: dict[str, Any]) -> dict[str, Any]:
    return {
        "date": artifact.get("date"),
        "range": artifact.get("range"),
        "summary": artifact.get("summary"),
        "feature_availability": artifact.get("feature_availability"),
        "sections": artifact.get("sections"),
        "unreleased_progress": artifact.get("unreleased_progress"),
        "marketing_candidates": artifact.get("marketing_candidates"),
        "sources": artifact.get("sources"),
    }


def build_weekly_llm_source(artifact: dict[str, Any], daily_artifacts: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "week_start": artifact.get("week_start"),
        "week_end": artifact.get("week_end"),
        "summary": artifact.get("summary"),
        "feature_availability": artifact.get("feature_availability"),
        "daily_summaries": [
            {
                "date": daily.get("date"),
                "llm_summary": daily.get("llm_summary"),
                "summary": daily.get("summary"),
                "feature_availability": daily.get("feature_availability"),
                "marketing_candidates": daily.get("marketing_candidates"),
                "unreleased_progress": daily.get("unreleased_progress"),
            }
            for daily in daily_artifacts
        ],
        "themes": artifact.get("themes"),
        "marketing_candidates": artifact.get("marketing_candidates"),
        "unreleased_progress": artifact.get("unreleased_progress"),
    }


def build_monthly_llm_source(artifact: dict[str, Any], weekly_artifacts: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "month_start": artifact.get("month_start"),
        "month_end": artifact.get("month_end"),
        "summary": artifact.get("summary"),
        "feature_availability": artifact.get("feature_availability"),
        "weekly_summaries": [
            {
                "week_start": weekly.get("week_start"),
                "week_end": weekly.get("week_end"),
                "llm_summary": weekly.get("llm_summary"),
                "summary": weekly.get("summary"),
                "marketing_candidates": weekly.get("marketing_candidates"),
                "unreleased_progress": weekly.get("unreleased_progress"),
            }
            for weekly in weekly_artifacts
        ],
        "themes": artifact.get("themes"),
        "marketing_candidates": artifact.get("marketing_candidates"),
        "unreleased_progress": artifact.get("unreleased_progress"),
    }


def build_daily_artifact(
    *,
    commits: list[CommitChange],
    report_date: date,
    since: str | None,
    until: str | None = None,
    from_ref: str | None,
    to_ref: str,
    assume_released: bool,
) -> dict[str, Any]:
    availability_service = load_feature_availability_service()
    disabled_features = disabled_feature_context(availability_service)
    sections: dict[str, list[dict[str, Any]]] = {section: [] for section in SECTION_ORDER}
    unreleased_dev_only: list[dict[str, Any]] = []
    unreleased_unknown: list[dict[str, Any]] = []
    feature_metadata: list[dict[str, Any]] = []
    newsletter_candidates: list[dict[str, Any]] = []
    social_candidates: list[dict[str, Any]] = []

    for commit in commits:
        item = item_for_commit(commit, assume_released=assume_released, availability_service=availability_service)
        sections[item["section"]].append(item)
        compact = {
            "title": item["title"],
            "commits": item["commits"],
            "section": item["section"],
            "release_status": item["release_status"],
            "communication_status": item["communication_status"],
            "related_features": item["related_features"],
        }
        if item["release_status"] == "dev_only":
            unreleased_dev_only.append(compact)
        elif item["release_status"] == "unknown":
            unreleased_unknown.append(compact)
        if item["feature_metadata_changed"]:
            feature_metadata.append(compact)
        if item["newsletter_ready"]:
            newsletter_candidates.append(compact)
        if item["user_facing"]:
            social_candidates.append({**compact, "newsletter_ready": item["newsletter_ready"]})

    section_counts = {section: len(items) for section, items in sections.items()}
    return {
        "schema_version": 1,
        "cadence": "daily",
        "date": report_date.isoformat(),
        "generated_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "range": {
            "since": since,
            "until": until,
            "from_ref": from_ref,
            "to_ref": to_ref,
            "assume_released": assume_released,
        },
        "summary": {
            "total_commits": len(commits),
            "section_counts": section_counts,
            "newsletter_ready_items": len(newsletter_candidates),
            "user_facing_items": len(social_candidates),
            "dev_only_items": len(unreleased_dev_only),
            "unknown_release_items": len(unreleased_unknown),
        },
        "feature_availability": {
            "disabled_features": disabled_features,
            "communication_rule": "Items related to these disabled features are unreleased_feature and must not appear in newsletter include recommendations.",
        },
        "sections": sections,
        "unreleased_progress": {
            "dev_only": unreleased_dev_only,
            "unknown_release_status": unreleased_unknown,
            "feature_metadata_changed": feature_metadata,
        },
        "marketing_candidates": {
            "newsletter": newsletter_candidates,
            "social_or_video": social_candidates,
        },
        "risks": {
            "communication": [
                "Do not use dev_only or unknown_release_status items in newsletters until they are reachable from main.",
                "Do not use unreleased_feature items in newsletters until their related feature availability gates are enabled.",
                "Review feature_metadata_changed items for disabled or partially released functionality before public communication.",
            ]
        },
        "sources": {
            "commits": [
                {
                    "sha": commit.sha,
                    "short_sha": commit.short_sha,
                    "authored_at": commit.authored_at,
                    "subject": commit.subject,
                    "in_main": commit.in_main,
                    "in_dev": commit.in_dev,
                    "changed_paths": commit.changed_paths,
                    "related_feature_ids": related_feature_ids_for_commit(commit),
                }
                for commit in commits
            ]
        },
    }


def dump_yaml(data: dict[str, Any]) -> str:
    return yaml.dump(data, Dumper=NoAliasDumper, sort_keys=False, allow_unicode=True, width=120)


def default_output_path(report_date: date) -> Path:
    return DEFAULT_DAILY_DIR / f"{report_date.isoformat()}.yml"


def default_weekly_output_path(week_start: date) -> Path:
    iso_year, iso_week, _ = week_start.isocalendar()
    return DEFAULT_WEEKLY_DIR / f"{iso_year}-W{iso_week:02d}.yml"


def default_monthly_output_path(month_start: date) -> Path:
    return DEFAULT_MONTHLY_DIR / f"{month_start:%Y-%m}.yml"


def write_artifact(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(dump_yaml(data), encoding="utf-8")


def parse_date(value: str) -> date:
    return date.fromisoformat(value)


def current_week_start(today: date | None = None) -> date:
    base = today or datetime.now(timezone.utc).date()
    return date.fromordinal(base.toordinal() - base.weekday())


def current_month_start(today: date | None = None) -> date:
    base = today or datetime.now(timezone.utc).date()
    return date(base.year, base.month, 1)


def month_end_for_start(month_start: date) -> date:
    if month_start.month == 12:
        next_month = date(month_start.year + 1, 1, 1)
    else:
        next_month = date(month_start.year, month_start.month + 1, 1)
    return next_month - timedelta(days=1)


def load_daily_artifacts(daily_dir: Path, start: date, end: date) -> list[dict[str, Any]]:
    artifacts: list[dict[str, Any]] = []
    if not daily_dir.exists():
        return artifacts
    for path in sorted(daily_dir.glob("*.yml")):
        try:
            payload = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        except yaml.YAMLError as exc:
            raise ValueError(f"Invalid YAML in {path}: {exc}") from exc
        if not isinstance(payload, dict) or payload.get("cadence") != "daily":
            continue
        raw_date = payload.get("date")
        if not raw_date:
            continue
        daily_date = parse_date(str(raw_date))
        if start <= daily_date <= end:
            payload["_source_file"] = str(path)
            artifacts.append(payload)
    return artifacts


def load_weekly_artifacts(weekly_dir: Path, start: date, end: date) -> list[dict[str, Any]]:
    artifacts: list[dict[str, Any]] = []
    if not weekly_dir.exists():
        return artifacts
    for path in sorted(weekly_dir.glob("*.yml")):
        try:
            payload = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        except yaml.YAMLError as exc:
            raise ValueError(f"Invalid YAML in {path}: {exc}") from exc
        if not isinstance(payload, dict) or payload.get("cadence") != "weekly":
            continue
        raw_week_start = payload.get("week_start")
        raw_week_end = payload.get("week_end")
        if not raw_week_start or not raw_week_end:
            continue
        week_start = parse_date(str(raw_week_start))
        week_end = parse_date(str(raw_week_end))
        if week_start <= end and week_end >= start:
            payload["_source_file"] = str(path)
            artifacts.append(payload)
    return artifacts


def disabled_features_from_daily_artifacts(daily_artifacts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_id: dict[str, dict[str, Any]] = {}
    for artifact in daily_artifacts:
        for feature in (artifact.get("feature_availability") or {}).get("disabled_features") or []:
            if isinstance(feature, dict) and feature.get("id"):
                by_id[str(feature["id"])] = dict(feature)
    return [by_id[feature_id] for feature_id in sorted(by_id)]


def disabled_features_from_rollup_artifacts(artifacts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_id: dict[str, dict[str, Any]] = {}
    for artifact in artifacts:
        for feature in (artifact.get("feature_availability") or {}).get("disabled_features") or []:
            if isinstance(feature, dict) and feature.get("id"):
                by_id[str(feature["id"])] = dict(feature)
    return [by_id[feature_id] for feature_id in sorted(by_id)]


def iter_daily_items(daily_artifact: dict[str, Any]) -> list[dict[str, Any]]:
    daily_date = str(daily_artifact.get("date") or "")
    items: list[dict[str, Any]] = []
    sections = daily_artifact.get("sections") or {}
    if not isinstance(sections, dict):
        return items
    for section in SECTION_ORDER:
        for item in sections.get(section) or []:
            if not isinstance(item, dict):
                continue
            items.append(
                {
                    "date": daily_date,
                    "title": item.get("title", ""),
                    "section": item.get("section") or section,
                    "commits": list(item.get("commits") or []),
                    "changed_paths": list(item.get("changed_paths") or []),
                    "release_status": item.get("release_status", "unknown"),
                    "communication_status": item.get("communication_status", "unknown"),
                    "newsletter_ready": bool(item.get("newsletter_ready")),
                    "user_facing": bool(item.get("user_facing")),
                    "related_features": list(item.get("related_features") or []),
                }
            )
    return items


def theme_for_item(item: dict[str, Any]) -> str:
    haystack = " ".join(
        [
            str(item.get("title") or ""),
            str(item.get("section") or ""),
            " ".join(str(path) for path in item.get("changed_paths") or []),
        ]
    ).lower()
    for theme, hints in THEME_HINTS.items():
        if any(hint in haystack for hint in hints):
            return theme
    return "product" if item.get("user_facing") else "other"


def compact_rollup_item(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "date": item.get("date"),
        "title": item.get("title"),
        "commits": item.get("commits") or [],
        "section": item.get("section"),
        "release_status": item.get("release_status"),
        "communication_status": item.get("communication_status"),
        "newsletter_ready": bool(item.get("newsletter_ready")),
        "user_facing": bool(item.get("user_facing")),
        "related_features": item.get("related_features") or [],
    }


def build_weekly_artifact(*, daily_artifacts: list[dict[str, Any]], week_start: date, week_end: date) -> dict[str, Any]:
    all_items: list[dict[str, Any]] = []
    daily_summaries: list[dict[str, Any]] = []
    source_files: list[str] = []
    for artifact in daily_artifacts:
        daily_items = iter_daily_items(artifact)
        all_items.extend(daily_items)
        if artifact.get("_source_file"):
            source_files.append(str(artifact["_source_file"]))
        daily_summaries.append(
            {
                "date": artifact.get("date"),
                "total_commits": (artifact.get("summary") or {}).get("total_commits", 0),
                "newsletter_ready_items": (artifact.get("summary") or {}).get("newsletter_ready_items", 0),
                "dev_only_items": (artifact.get("summary") or {}).get("dev_only_items", 0),
            }
        )

    theme_map: dict[str, list[dict[str, Any]]] = {}
    for item in all_items:
        theme_map.setdefault(theme_for_item(item), []).append(compact_rollup_item(item))

    themes = []
    for theme, items in sorted(theme_map.items(), key=lambda kv: (-len(kv[1]), kv[0])):
        newsletter_ready_count = sum(1 for item in items if item.get("newsletter_ready"))
        dev_only_count = sum(1 for item in items if item.get("release_status") == "dev_only")
        themes.append(
            {
                "theme": theme,
                "item_count": len(items),
                "newsletter_ready_count": newsletter_ready_count,
                "dev_only_count": dev_only_count,
                "source_items": sorted(items, key=lambda item: (str(item.get("date")), str(item.get("title")))),
            }
        )

    newsletter_items = [compact_rollup_item(item) for item in all_items if item.get("newsletter_ready")]
    dev_only_items = [compact_rollup_item(item) for item in all_items if item.get("release_status") == "dev_only"]
    unknown_items = [compact_rollup_item(item) for item in all_items if item.get("release_status") == "unknown"]
    disabled_features = disabled_features_from_daily_artifacts(daily_artifacts)

    return {
        "schema_version": 1,
        "cadence": "weekly",
        "week_start": week_start.isoformat(),
        "week_end": week_end.isoformat(),
        "generated_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "summary": {
            "daily_files": len(daily_artifacts),
            "total_items": len(all_items),
            "newsletter_ready_items": len(newsletter_items),
            "user_facing_items": sum(1 for item in all_items if item.get("user_facing")),
            "dev_only_items": len(dev_only_items),
            "unknown_release_items": len(unknown_items),
            "themes": len(themes),
        },
        "feature_availability": {
            "disabled_features": disabled_features,
            "communication_rule": "Items related to these disabled features are unreleased_feature and must not appear in newsletter include recommendations.",
        },
        "daily_summaries": daily_summaries,
        "themes": themes,
        "marketing_candidates": {
            "newsletter": sorted(newsletter_items, key=lambda item: (str(item.get("date")), str(item.get("title")))),
            "social_or_video": sorted(
                [compact_rollup_item(item) for item in all_items if item.get("user_facing")],
                key=lambda item: (str(item.get("date")), str(item.get("title"))),
            ),
        },
        "unreleased_progress": {
            "dev_only": sorted(dev_only_items, key=lambda item: (str(item.get("date")), str(item.get("title")))),
            "unknown_release_status": sorted(unknown_items, key=lambda item: (str(item.get("date")), str(item.get("title")))),
        },
        "risks": {
            "communication": [
                "Use weekly themes for PR/release/newsletter drafting; do not list every daily item one-by-one.",
                "Keep dev_only and unknown_release_status items out of public newsletters until released on main.",
            ]
        },
        "sources": {
            "daily_files": source_files,
        },
    }


def build_monthly_artifact(*, weekly_artifacts: list[dict[str, Any]], month_start: date, month_end: date) -> dict[str, Any]:
    all_theme_items: list[dict[str, Any]] = []
    weekly_summaries: list[dict[str, Any]] = []
    source_files: list[str] = []
    newsletter_items: list[dict[str, Any]] = []
    social_items: list[dict[str, Any]] = []
    dev_only_items: list[dict[str, Any]] = []
    unknown_items: list[dict[str, Any]] = []

    for artifact in weekly_artifacts:
        if artifact.get("_source_file"):
            source_files.append(str(artifact["_source_file"]))
        summary = artifact.get("summary") or {}
        weekly_summaries.append(
            {
                "week_start": artifact.get("week_start"),
                "week_end": artifact.get("week_end"),
                "total_items": summary.get("total_items", 0),
                "newsletter_ready_items": summary.get("newsletter_ready_items", 0),
                "dev_only_items": summary.get("dev_only_items", 0),
            }
        )
        for theme in artifact.get("themes") or []:
            if not isinstance(theme, dict):
                continue
            for item in theme.get("source_items") or []:
                if isinstance(item, dict):
                    all_theme_items.append({**item, "source_week_start": artifact.get("week_start"), "source_week_end": artifact.get("week_end")})
        newsletter_items.extend((artifact.get("marketing_candidates") or {}).get("newsletter") or [])
        social_items.extend((artifact.get("marketing_candidates") or {}).get("social_or_video") or [])
        dev_only_items.extend((artifact.get("unreleased_progress") or {}).get("dev_only") or [])
        unknown_items.extend((artifact.get("unreleased_progress") or {}).get("unknown_release_status") or [])

    theme_map: dict[str, list[dict[str, Any]]] = {}
    for item in all_theme_items:
        theme_map.setdefault(theme_for_item(item), []).append(compact_rollup_item(item))

    themes = []
    for theme, items in sorted(theme_map.items(), key=lambda kv: (-len(kv[1]), kv[0])):
        themes.append(
            {
                "theme": theme,
                "item_count": len(items),
                "newsletter_ready_count": sum(1 for item in items if item.get("newsletter_ready")),
                "dev_only_count": sum(1 for item in items if item.get("release_status") == "dev_only"),
                "source_items": sorted(items, key=lambda item: (str(item.get("date")), str(item.get("title"))))[:50],
            }
        )

    disabled_features = disabled_features_from_rollup_artifacts(weekly_artifacts)
    return {
        "schema_version": 1,
        "cadence": "monthly",
        "month_start": month_start.isoformat(),
        "month_end": month_end.isoformat(),
        "generated_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "summary": {
            "weekly_files": len(weekly_artifacts),
            "total_items": len(all_theme_items),
            "newsletter_ready_items": len(newsletter_items),
            "user_facing_items": sum(1 for item in all_theme_items if item.get("user_facing")),
            "dev_only_items": len(dev_only_items),
            "unknown_release_items": len(unknown_items),
            "themes": len(themes),
        },
        "feature_availability": {
            "disabled_features": disabled_features,
            "communication_rule": "Items related to these disabled features are unreleased_feature and must not appear in newsletter include recommendations.",
        },
        "weekly_summaries": weekly_summaries,
        "themes": themes,
        "marketing_candidates": {
            "newsletter": sorted(newsletter_items, key=lambda item: (str(item.get("date")), str(item.get("title"))))[:100],
            "social_or_video": sorted(social_items, key=lambda item: (str(item.get("date")), str(item.get("title"))))[:100],
        },
        "unreleased_progress": {
            "dev_only": sorted(dev_only_items, key=lambda item: (str(item.get("date")), str(item.get("title"))))[:100],
            "unknown_release_status": sorted(unknown_items, key=lambda item: (str(item.get("date")), str(item.get("title"))))[:100],
        },
        "risks": {
            "communication": [
                "Use monthly themes for release/newsletter/social planning; verify current feature availability before public communication.",
            ]
        },
        "sources": {
            "weekly_files": source_files,
        },
    }


def _summary_bullets(items: list[dict[str, Any]], *, text_key: str = "text", limit: int = 5) -> list[str]:
    bullets: list[str] = []
    for item in items[:limit]:
        text = str(item.get(text_key) or item.get("title") or "").strip()
        if not text:
            continue
        commits = (item.get("evidence") or {}).get("commits") or item.get("commits") or []
        suffix = f" ({', '.join(str(commit) for commit in commits[:3])})" if commits else ""
        bullets.append(f"- {text}{suffix}")
    return bullets or ["- None"]


def build_weekly_discord_payload(artifact: dict[str, Any]) -> dict[str, Any]:
    llm_summary = artifact.get("llm_summary") or {}
    summary = artifact.get("summary") or {}
    newsletter = llm_summary.get("newsletter_recommendation") or {}
    description_lines = [
        str(llm_summary.get("overview") or "Weekly release intelligence summary generated."),
        "",
        f"Items: {summary.get('total_items', 0)} | Newsletter-ready: {summary.get('newsletter_ready_items', 0)} | Dev-only: {summary.get('dev_only_items', 0)}",
        "",
        "Newsletter include:",
        *_summary_bullets(newsletter.get("include") or [], limit=5),
        "",
        "Newsletter exclude:",
        *_summary_bullets(newsletter.get("exclude") or [], limit=5),
    ]
    warnings = llm_summary.get("validation_warnings") or []
    if warnings:
        description_lines.extend(["", f"Validation warnings: {len(warnings)}"])
    return {
        "username": "OpenMates Release Intelligence",
        "avatar_url": "https://openmates.org/favicon.png",
        "embeds": [
            {
                "title": f"Weekly release intelligence: {artifact.get('week_start')} to {artifact.get('week_end')}",
                "description": "\n".join(description_lines)[:4000],
                "color": 0x7C3AED,
                "timestamp": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
            }
        ],
    }


def post_weekly_discord_summary(artifact: dict[str, Any], *, dry_run: bool = False) -> bool:
    dot_env = read_dot_env()
    webhook_url = get_env("DISCORD_WEBHOOK_RELEASE_INTELLIGENCE", dot_env) or get_env("DISCORD_WEBHOOK_DEV_NIGHTLY", dot_env)
    payload = build_weekly_discord_payload(artifact)
    if dry_run:
        print(json.dumps(payload, indent=2))
        return True
    if not webhook_url:
        print("DISCORD_WEBHOOK_RELEASE_INTELLIGENCE and DISCORD_WEBHOOK_DEV_NIGHTLY not set; skipping Discord.", file=sys.stderr)
        return False
    req = request.Request(
        webhook_url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json", "User-Agent": "OpenMates-ReleaseIntelligence/0.1"},
        method="POST",
    )
    try:
        with request.urlopen(req, timeout=30) as response:
            response.read()
        print("[release-intelligence] weekly Discord summary sent", file=sys.stderr)
        return True
    except error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:300]
        print(f"[release-intelligence] Discord failed HTTP {exc.code}: {detail}", file=sys.stderr)
    except OSError as exc:
        print(f"[release-intelligence] Discord failed: {exc}", file=sys.stderr)
    return False


def daily_command(args: argparse.Namespace) -> int:
    report_date = date.fromisoformat(args.date) if args.date else datetime.now(timezone.utc).date()
    commits = collect_commits(
        since=args.since,
        until=args.until,
        from_ref=args.from_ref,
        to_ref=args.to_ref,
        main_ref=args.main_ref,
        dev_ref=args.dev_ref,
    )
    artifact = build_daily_artifact(
        commits=commits,
        report_date=report_date,
        since=args.since,
        until=args.until,
        from_ref=args.from_ref,
        to_ref=args.to_ref,
        assume_released=args.assume_released,
    )
    if args.no_llm:
        artifact["llm_summary"] = {"status": "not_generated", "reason": "--no-llm was provided"}
    else:
        artifact["llm_summary"] = generate_llm_summary(
            cadence="daily",
            source=build_daily_llm_source(artifact),
            known_commits=commit_refs_from_artifact(artifact),
            model=args.model,
            api_key=load_gemini_api_key(),
            retries=args.llm_retries,
        )

    rendered = dump_yaml(artifact)
    if args.stdout or not args.write:
        print(rendered, end="")
    if args.write:
        output_path = Path(args.output).resolve() if args.output else default_output_path(report_date)
        write_artifact(output_path, artifact)
        print(f"[release-intelligence] wrote {output_path.relative_to(REPO_ROOT) if output_path.is_relative_to(REPO_ROOT) else output_path}", file=sys.stderr)
    return 0


def weekly_command(args: argparse.Namespace) -> int:
    week_start = parse_date(args.week_start) if args.week_start else current_week_start()
    week_end = parse_date(args.week_end) if args.week_end else date.fromordinal(week_start.toordinal() + 6)
    daily_dir = Path(args.daily_dir).resolve() if args.daily_dir else DEFAULT_DAILY_DIR
    daily_artifacts = load_daily_artifacts(daily_dir, week_start, week_end)
    artifact = build_weekly_artifact(daily_artifacts=daily_artifacts, week_start=week_start, week_end=week_end)
    if args.no_llm:
        artifact["llm_summary"] = {"status": "not_generated", "reason": "--no-llm was provided"}
    else:
        artifact["llm_summary"] = generate_llm_summary(
            cadence="weekly",
            source=build_weekly_llm_source(artifact, daily_artifacts),
            known_commits=commit_refs_from_daily_artifacts(daily_artifacts),
            model=args.model,
            api_key=load_gemini_api_key(),
            retries=args.llm_retries,
        )
    rendered = dump_yaml(artifact)
    if args.stdout or not args.write:
        print(rendered, end="")
    if args.write:
        output_path = Path(args.output).resolve() if args.output else default_weekly_output_path(week_start)
        write_artifact(output_path, artifact)
        print(f"[release-intelligence] wrote {output_path.relative_to(REPO_ROOT) if output_path.is_relative_to(REPO_ROOT) else output_path}", file=sys.stderr)
    if args.discord or args.discord_dry_run:
        post_weekly_discord_summary(artifact, dry_run=args.discord_dry_run)
    return 0


def monthly_command(args: argparse.Namespace) -> int:
    month_start = parse_date(args.month_start) if args.month_start else current_month_start()
    month_end = parse_date(args.month_end) if args.month_end else month_end_for_start(month_start)
    weekly_dir = Path(args.weekly_dir).resolve() if args.weekly_dir else DEFAULT_WEEKLY_DIR
    weekly_artifacts = load_weekly_artifacts(weekly_dir, month_start, month_end)
    artifact = build_monthly_artifact(weekly_artifacts=weekly_artifacts, month_start=month_start, month_end=month_end)
    if args.no_llm:
        artifact["llm_summary"] = {"status": "not_generated", "reason": "--no-llm was provided"}
    else:
        artifact["llm_summary"] = generate_llm_summary(
            cadence="monthly",
            source=build_monthly_llm_source(artifact, weekly_artifacts),
            known_commits=commit_refs_from_rollup_artifacts(weekly_artifacts),
            model=args.model,
            api_key=load_gemini_api_key(),
            retries=args.llm_retries,
        )
    rendered = dump_yaml(artifact)
    if args.stdout or not args.write:
        print(rendered, end="")
    if args.write:
        output_path = Path(args.output).resolve() if args.output else default_monthly_output_path(month_start)
        write_artifact(output_path, artifact)
        print(f"[release-intelligence] wrote {output_path.relative_to(REPO_ROOT) if output_path.is_relative_to(REPO_ROOT) else output_path}", file=sys.stderr)
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Generate OpenMates release-intelligence artifacts.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    daily = subparsers.add_parser("daily", help="Generate a deterministic daily changelog YAML artifact.")
    daily.add_argument("--since", default="24 hours ago", help="git log --since window for the selected ref range.")
    daily.add_argument("--until", default=None, help="Optional git log --until bound for the selected ref range.")
    daily.add_argument("--from-ref", default=None, help="Optional lower git range bound, e.g. origin/main.")
    daily.add_argument("--to-ref", default="HEAD", help="Upper git range bound; defaults to HEAD.")
    daily.add_argument("--main-ref", default=DEFAULT_MAIN_REF, help="Ref used to decide public release reachability.")
    daily.add_argument("--dev-ref", default=DEFAULT_DEV_REF, help="Ref used to decide dev reachability.")
    daily.add_argument("--date", default=None, help="Report date as YYYY-MM-DD; defaults to current UTC date.")
    daily.add_argument("--output", default=None, help="Output path. Defaults to docs/releases/daily/YYYY-MM-DD.yml with --write.")
    daily.add_argument("--write", action="store_true", help="Write the YAML artifact to disk.")
    daily.add_argument("--stdout", action="store_true", help="Print the YAML artifact to stdout.")
    daily.add_argument("--model", default=DEFAULT_GEMINI_MODEL, help="Gemini model used for natural-language summary generation.")
    daily.add_argument("--llm-retries", type=int, default=DEFAULT_LLM_RETRIES, help="Retry count for transient or malformed Gemini responses.")
    daily.add_argument("--no-llm", action="store_true", help="Skip Gemini and emit deterministic source data only.")
    daily.add_argument(
        "--assume-released",
        action="store_true",
        help="Explicit smoke-test override that treats user-facing commits as released even if not reachable from main.",
    )
    daily.set_defaults(func=daily_command)

    weekly = subparsers.add_parser("weekly", help="Generate a deterministic weekly rollup from daily YAML artifacts.")
    weekly.add_argument("--week-start", default=None, help="Week start date as YYYY-MM-DD. Defaults to current UTC Monday.")
    weekly.add_argument("--week-end", default=None, help="Week end date as YYYY-MM-DD. Defaults to week-start + 6 days.")
    weekly.add_argument("--daily-dir", default=None, help="Directory containing daily YYYY-MM-DD.yml artifacts.")
    weekly.add_argument("--output", default=None, help="Output path. Defaults to docs/releases/weekly/YYYY-Www.yml with --write.")
    weekly.add_argument("--write", action="store_true", help="Write the weekly YAML artifact to disk.")
    weekly.add_argument("--stdout", action="store_true", help="Print the weekly YAML artifact to stdout.")
    weekly.add_argument("--model", default=DEFAULT_GEMINI_MODEL, help="Gemini model used for natural-language summary generation.")
    weekly.add_argument("--llm-retries", type=int, default=DEFAULT_LLM_RETRIES, help="Retry count for transient or malformed Gemini responses.")
    weekly.add_argument("--no-llm", action="store_true", help="Skip Gemini and emit deterministic source data only.")
    weekly.add_argument("--discord", action="store_true", help="Post the generated weekly summary to Discord.")
    weekly.add_argument("--discord-dry-run", action="store_true", help="Print the Discord payload instead of sending it.")
    weekly.set_defaults(func=weekly_command)

    monthly = subparsers.add_parser("monthly", help="Generate a monthly rollup from weekly YAML artifacts.")
    monthly.add_argument("--month-start", default=None, help="Month start date as YYYY-MM-DD. Defaults to current UTC month start.")
    monthly.add_argument("--month-end", default=None, help="Month end date as YYYY-MM-DD. Defaults to the end of --month-start month.")
    monthly.add_argument("--weekly-dir", default=None, help="Directory containing weekly YAML artifacts.")
    monthly.add_argument("--output", default=None, help="Output path. Defaults to docs/releases/monthly/YYYY-MM.yml with --write.")
    monthly.add_argument("--write", action="store_true", help="Write the monthly YAML artifact to disk.")
    monthly.add_argument("--stdout", action="store_true", help="Print the monthly YAML artifact to stdout.")
    monthly.add_argument("--model", default=DEFAULT_GEMINI_MODEL, help="Gemini model used for natural-language summary generation.")
    monthly.add_argument("--llm-retries", type=int, default=DEFAULT_LLM_RETRIES, help="Retry count for transient or malformed Gemini responses.")
    monthly.add_argument("--no-llm", action="store_true", help="Skip Gemini and emit deterministic source data only.")
    monthly.set_defaults(func=monthly_command)
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    try:
        return args.func(args)
    except subprocess.CalledProcessError as exc:
        print(exc.stderr or exc.stdout or str(exc), file=sys.stderr)
        return exc.returncode or 1


if __name__ == "__main__":
    raise SystemExit(main())
