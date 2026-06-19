#!/usr/bin/env python3
"""
scripts/tests.py

Unified test control plane for OpenMates test debugging.
It wraps the existing GitHub Actions-backed runner, persists current test state,
records an append-only timeline, deterministically triages failures, and leases
the next failure group so parallel debugging sessions do not collide.

Architecture: docs/architecture/test-orchestration.md
"""

from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parent.parent
RESULTS_DIR = PROJECT_ROOT / "test-results"
STATE_FILE = RESULTS_DIR / "tests-state.json"
HISTORY_FILE = RESULTS_DIR / "tests-history.jsonl"
LEASES_FILE = RESULTS_DIR / "failed-test-leases.json"
TRIAGE_FILE = RESULTS_DIR / "test-failure-triage.json"
TEST_FILE_INDEX_FILE = RESULTS_DIR / "test-file-index.json"
RUNS_DIR = RESULTS_DIR / "runs"
LEASE_LOCK_FILE = Path("/tmp/openmates-failed-test-leases.lock")
SPEC_DIR = PROJECT_ROOT / "frontend" / "apps" / "web_app" / "tests"
RUN_TESTS_SCRIPT = PROJECT_ROOT / "scripts" / "run_tests.py"

PROBLEM_STATUSES = {"failed", "dispatch_error", "timeout", "result_unknown"}
LEASE_TTL_HOURS = 8
MAX_LINKED_FILES = 12

CATEGORY_PRIORITY = {
    "account_preflight": 10,
    "auth_signup": 20,
    "chat_sync_encryption": 30,
    "chat_send_receive": 40,
    "payments_billing": 50,
    "ai_response": 60,
    "embed_rendering": 70,
    "app_skill": 80,
    "cli_auth": 90,
    "provider_external": 100,
    "github_actions_wrapper": 110,
    "missing_element": 120,
    "timeout": 130,
    "unit_regression": 140,
    "test_infra": 150,
    "unknown": 999,
}

KEYWORD_LINKS = {
    "chat": [
        "frontend/packages/ui/src/components/ChatHistory.svelte",
        "frontend/packages/ui/src/components/ChatMessage.svelte",
        "frontend/packages/ui/src/components/enter_message/MessageInput.svelte",
    ],
    "send-message": [
        "frontend/packages/ui/src/components/enter_message/MessageInput.svelte",
    ],
    "message-assistant": [
        "frontend/packages/ui/src/components/ChatMessage.svelte",
        "frontend/packages/ui/src/components/ChatHistory.svelte",
    ],
    "chat-header": [
        "frontend/packages/ui/src/components/ChatHeader.svelte",
    ],
    "signup": [
        "frontend/apps/web_app/tests/helpers/signup-flow-helpers.ts",
    ],
    "login": [
        "frontend/apps/web_app/tests/helpers/signup-flow-helpers.ts",
    ],
    "embed": [
        "frontend/packages/ui/src/components/embeds/UnifiedEmbedPreview.svelte",
        "frontend/packages/ui/src/components/embeds/UnifiedEmbedFullscreen.svelte",
        "frontend/packages/ui/src/components/embeds/registry.ts",
    ],
    "application-preview": [
        "frontend/packages/ui/src/components/embeds/application/ApplicationPreview.svelte",
    ],
    "focus-mode": [
        "frontend/packages/ui/src/components/focus_modes/FocusModeBar.svelte",
    ],
    "reminder": [
        "backend/apps/reminders/",
    ],
    "api-key": [
        "frontend/apps/web_app/tests/api-keys-flow.spec.ts",
    ],
}

SOURCE_SCAN_ROOTS = (
    "frontend/apps/web_app/tests",
    "frontend/packages/ui/src",
    "frontend/packages/openmates-cli/src",
    "backend/apps",
    "backend/core",
    "backend/shared",
    "backend/tests",
    "scripts",
)

SOURCE_SCAN_SUFFIXES = {".svelte", ".ts", ".tsx", ".js", ".mjs", ".py", ".swift"}
_SOURCE_TEXT_CACHE: dict[str, str] | None = None


def utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_utc(value: str) -> datetime | None:
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def read_json(path: Path, default: Any) -> Any:
    if not path.is_file():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"Invalid JSON in {path}: {exc}") from exc


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=str(path.parent))
    tmp_path = Path(tmp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(data, handle, indent=2, sort_keys=True)
            handle.write("\n")
        tmp_path.replace(path)
    finally:
        tmp_path.unlink(missing_ok=True)


def append_jsonl(path: Path, records: list[dict[str, Any]]) -> None:
    if not records:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        for record in records:
            handle.write(json.dumps(record, sort_keys=True) + "\n")


def display_path(path: Path) -> str:
    try:
        return str(path.relative_to(PROJECT_ROOT))
    except ValueError:
        return str(path)


def run_archive_name(run_id: str) -> str:
    return run_id.replace(":", "").replace("-", "") + ".json"


def test_label(suite: str, test: dict[str, Any]) -> str:
    return str(test.get("file") or test.get("name") or "unknown")


def test_key(suite: str, test: dict[str, Any]) -> str:
    return f"{suite}::{test_label(suite, test)}"


def iter_tests(run_data: dict[str, Any]):
    for suite, suite_data in (run_data.get("suites") or {}).items():
        if not isinstance(suite_data, dict):
            continue
        for test in suite_data.get("tests") or []:
            if isinstance(test, dict):
                yield str(suite), test


def is_problem(status: str) -> bool:
    return status in PROBLEM_STATUSES


def summarize_current_tests(tests: dict[str, dict[str, Any]]) -> dict[str, int]:
    summary = {
        "total": 0,
        "passed": 0,
        "failed": 0,
        "dispatch_error": 0,
        "timeout": 0,
        "result_unknown": 0,
        "skipped": 0,
        "not_started": 0,
        "running": 0,
    }
    for test in tests.values():
        summary["total"] += 1
        status = str(test.get("status") or "unknown")
        if status in summary:
            summary[status] += 1
        else:
            summary["skipped"] += 1
    return summary


def record_run_result(run_data: dict[str, Any]) -> dict[str, Any]:
    """Persist normalized current state, run archive, and timeline events."""
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    RUNS_DIR.mkdir(parents=True, exist_ok=True)
    run_id = str(run_data.get("run_id") or utc_now())
    timestamp = utc_now()
    state = read_json(STATE_FILE, {})
    recorded_event_ids = set(state.get("recorded_event_ids") or [])
    tests = dict(state.get("tests") or {})
    events: list[dict[str, Any]] = []

    for suite, test in iter_tests(run_data):
        label = test_label(suite, test)
        key = test_key(suite, test)
        status = str(test.get("status") or "unknown")
        event = "failed" if is_problem(status) else status
        event_id = f"{run_id}:{key}:{event}"
        current = {
            "suite": suite,
            "test": label,
            "key": key,
            "status": status,
            "event": event,
            "run_id": run_id,
            "github_run_id": test.get("run_id"),
            "github_run_url": test.get("github_run_url"),
            "git_sha": run_data.get("git_sha"),
            "git_branch": run_data.get("git_branch"),
            "environment": run_data.get("environment"),
            "duration_seconds": test.get("duration_seconds", 0),
            "error": test.get("error"),
            "updated_at": timestamp,
        }
        tests[key] = current
        if event_id not in recorded_event_ids:
            events.append({**current, "timestamp": timestamp, "event_id": event_id})
            recorded_event_ids.add(event_id)

    normalized_state = {
        "latest_run_id": run_id,
        "latest_git_sha": run_data.get("git_sha"),
        "latest_git_branch": run_data.get("git_branch"),
        "environment": run_data.get("environment"),
        "updated_at": timestamp,
        "summary": summarize_current_tests(tests),
        "latest_run_summary": run_data.get("summary") or {},
        "tests": tests,
        "recorded_event_ids": sorted(recorded_event_ids)[-10000:],
    }
    write_json(STATE_FILE, normalized_state)
    write_json(RUNS_DIR / run_archive_name(run_id), run_data)
    append_jsonl(HISTORY_FILE, events)
    return normalized_state


def load_state() -> dict[str, Any]:
    state = read_json(STATE_FILE, {})
    daily_files = sorted(
        path for path in RESULTS_DIR.glob("daily-run-*.json")
        if re.fullmatch(r"daily-run-\d{4}-\d{2}-\d{2}\.json", path.name)
    )
    latest_daily = daily_files[-1] if daily_files else None
    current_test_count = len(state.get("tests") or {}) if state else 0
    daily_data = read_json(latest_daily, {}) if latest_daily else {}
    daily_test_count = sum(1 for _suite, _test in iter_tests(daily_data)) if daily_data else 0

    # First bootstrap should preserve the broad daily suite, not a later one-spec
    # rerun. After that, targeted runs merge into the existing broad state.
    if latest_daily and daily_test_count > current_test_count:
        state = record_run_result(daily_data)

    last_run = RESULTS_DIR / "last-run.json"
    if last_run.is_file():
        last_data = read_json(last_run, {})
        if last_data.get("run_id") and last_data.get("run_id") != state.get("latest_run_id"):
            state = record_run_result(last_data)
    if state:
        return state
    return {"summary": {}, "tests": {}, "updated_at": None}


def mark_running(suite: str, tests: list[str], command: list[str]) -> None:
    state = load_state()
    current_tests = dict(state.get("tests") or {})
    timestamp = utc_now()
    run_id = f"manual-{timestamp}"
    events = []
    for label in tests or [suite]:
        key = f"{suite}::{label}"
        record = {
            "suite": suite,
            "test": label,
            "key": key,
            "status": "running",
            "event": "started",
            "run_id": run_id,
            "command": " ".join(command),
            "updated_at": timestamp,
        }
        current_tests[key] = record
        events.append({**record, "timestamp": timestamp, "event_id": f"{run_id}:{key}:started"})
    state["tests"] = current_tests
    state["summary"] = summarize_current_tests(current_tests)
    state["updated_at"] = timestamp
    write_json(STATE_FILE, state)
    append_jsonl(HISTORY_FILE, events)


def normalize_text(value: str) -> str:
    value = re.sub(r"\x1b\[[0-9;]*m", "", value or "")
    value = re.sub(r"[0-9a-f]{8}-[0-9a-f-]{27,}", "<uuid>", value, flags=re.IGNORECASE)
    value = re.sub(r"\b\d+ms\b|\b\d+\.\d+s\b|\b\d{8,}\b", "<var>", value)
    return " ".join(value.split())


def classify_failure(test: dict[str, Any]) -> str:
    text = normalize_text(" ".join(str(test.get(key) or "") for key in ("suite", "test", "error"))).lower()
    if "reserved playwright account slot" in text or "preflight" in text:
        return "account_preflight"
    if "not authenticated" in text and "cli" in text:
        return "cli_auth"
    if re.search(r"\b(signup|register|login|passkey|auth)\b", text) or any(token in text for token in ("account-recovery", "backup-code", "recovery-key")):
        return "auth_signup"
    if any(token in text for token in ("client_decrypt", "decrypt", "no chat key", "encrypt", "sync")):
        return "chat_sync_encryption"
    if any(token in text for token in ("embed", "application-preview", "fullscreen", "mermaid", "image-authenticity")):
        return "embed_rendering"
    if any(token in text for token in ("chat", "recent-chats", "fork-conversation", "send-message", "message-assistant", "no new assistant message")):
        return "chat_send_receive"
    if any(token in text for token in ("stripe", "billing", "payment", "credits")):
        return "payments_billing"
    if any(token in text for token in ("ai-response", "model", "inference", "vision", "did not identify", "file-attachment", "pdf-flow")):
        return "ai_response"
    if any(token in text for token in ("focus-mode", "skill", "app_skill", "app-skill")):
        return "app_skill"
    if any(token in text for token in ("mailosaur", "oauth", "calendar", "provider", "quota", "external service")):
        return "provider_external"
    if "github actions conclusion" in text or "process completed with exit code" in text:
        return "github_actions_wrapper"
    if "timeout" in text or "timed out" in text:
        return "timeout"
    if "element(s) not found" in text or "tobevisible" in text or "locator:" in text:
        return "missing_element"
    if any(token in text for token in ("referenceerror", "assertionerror", "modulenotfounderror", "importerror", "typeerror")):
        return "unit_regression"
    if any(token in text for token in ("dispatch_error", "artifact", "workflow", "runner")):
        return "test_infra"
    return "unknown"


def short_reason(error: str) -> str:
    text = normalize_text(error)
    if not text:
        return "No error detail available"
    locator = re.search(r"Locator:\s*([^\n]+?)(?:Expected:|Timeout:|Error:|$)", text)
    if locator:
        return f"Locator failure: {locator.group(1).strip()[:160]}"
    for marker in ("Error:", "AssertionError", "ReferenceError", "RuntimeError", "ImportError"):
        index = text.find(marker)
        if index >= 0:
            return text[index:index + 220]
    return text[:220]


def root_signature(category: str, reason: str) -> str:
    basis = normalize_text(reason).lower()
    locator = re.search(r"(getbytestid\(['\"][^)]+|data-testid=\"[^\"]+|data-action=\"[^\"]+|locator\([^)]{1,120})", basis)
    if locator:
        basis = locator.group(1)
    return hashlib.sha1(f"{category}:{basis[:160]}".encode("utf-8")).hexdigest()[:10]


def source_text_cache() -> dict[str, str]:
    global _SOURCE_TEXT_CACHE
    if _SOURCE_TEXT_CACHE is not None:
        return _SOURCE_TEXT_CACHE
    cache: dict[str, str] = {}
    for root_name in SOURCE_SCAN_ROOTS:
        root = PROJECT_ROOT / root_name
        if not root.exists():
            continue
        if root.is_file():
            paths = [root]
        else:
            paths = [p for p in root.rglob("*") if p.is_file() and p.suffix in SOURCE_SCAN_SUFFIXES]
        for path in paths:
            if "__pycache__" in path.parts:
                continue
            try:
                cache[display_path(path)] = path.read_text(encoding="utf-8", errors="ignore")[:250000]
            except OSError:
                continue
    _SOURCE_TEXT_CACHE = cache
    return cache


def extract_tokens(text: str) -> set[str]:
    tokens: set[str] = set()
    patterns = [
        r"getByTestId\(['\"]([^'\"]+)['\"]\)",
        r"data-testid=[\"']([^\"']+)[\"']",
        r"data-action=[\"']([^\"']+)[\"']",
        r"\[data-testid=\\?[\"']([^\"'\]]+)",
        r"\[data-action=\\?[\"']([^\"'\]]+)",
    ]
    for pattern in patterns:
        tokens.update(match.group(1) for match in re.finditer(pattern, text))
    return tokens


def files_containing_tokens(tokens: set[str]) -> list[str]:
    if not tokens:
        return []
    matches: list[str] = []
    for rel_path, content in source_text_cache().items():
        for token in tokens:
            if token and token in content:
                matches.append(rel_path)
                break
    return sorted(set(matches))[:MAX_LINKED_FILES]


def extract_error_paths(text: str) -> list[str]:
    paths = []
    for match in re.finditer(r"(?:/home/runner/work/OpenMates/OpenMates/)?((?:frontend|backend|scripts|docs|apple)/[^\s:)]+)", text):
        candidate = match.group(1).rstrip(".,;'")
        if (PROJECT_ROOT / candidate).exists():
            paths.append(candidate)
    return sorted(set(paths))


def linked_files_for_failure(test: dict[str, Any]) -> list[str]:
    label = str(test.get("test") or test.get("file") or test.get("name") or "")
    error = str(test.get("error") or "")
    haystack = f"{label}\n{error}"
    linked: list[str] = []

    if label.endswith((".spec.ts", ".test.ts")):
        spec_path = SPEC_DIR / label
        if spec_path.is_file():
            linked.append(display_path(spec_path))
    elif label.startswith("tests/"):
        for prefix in ("backend", "."):
            path = PROJECT_ROOT / prefix / label
            if path.is_file():
                linked.append(display_path(path))

    linked.extend(extract_error_paths(haystack))
    lower = haystack.lower()
    for keyword, paths in KEYWORD_LINKS.items():
        if keyword in lower:
            linked.extend(path for path in paths if (PROJECT_ROOT / path).exists() or path.endswith("/"))
    linked.extend(files_containing_tokens(extract_tokens(haystack)))

    seen = set()
    result = []
    for path in linked:
        if path and path not in seen:
            seen.add(path)
            result.append(path)
        if len(result) >= MAX_LINKED_FILES:
            break
    return result


def load_history_events(days: int = 7) -> list[dict[str, Any]]:
    if not HISTORY_FILE.is_file():
        return []
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    events = []
    for line in HISTORY_FILE.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        event = json.loads(line)
        timestamp = parse_utc(str(event.get("timestamp") or ""))
        if timestamp is None or timestamp >= cutoff:
            events.append(event)
    return events


def recurrence_counts(days: int = 7) -> dict[str, int]:
    counts: dict[str, int] = {}
    for event in load_history_events(days=days):
        if event.get("event") == "failed":
            key = str(event.get("key") or f"{event.get('suite')}::{event.get('test')}")
            counts[key] = counts.get(key, 0) + 1
    return counts


def failed_entries_from_state(state: dict[str, Any]) -> list[dict[str, Any]]:
    entries = []
    for key, test in (state.get("tests") or {}).items():
        if is_problem(str(test.get("status") or "")):
            entries.append({**test, "key": key})
    return entries


def build_triage(days: int = 7) -> dict[str, Any]:
    state = load_state()
    failures = failed_entries_from_state(state)
    recurrence = recurrence_counts(days=days)
    group_sizes: dict[str, int] = {}
    staged_entries = []

    for failure in failures:
        category = classify_failure(failure)
        reason = short_reason(str(failure.get("error") or ""))
        group_id = f"{category}-{root_signature(category, reason)}"
        group_sizes[group_id] = group_sizes.get(group_id, 0) + 1
        staged_entries.append((failure, category, reason, group_id))

    entries = []
    for failure, category, reason, group_id in staged_entries:
        key = str(failure.get("key") or f"{failure.get('suite')}::{failure.get('test')}")
        group_count = group_sizes[group_id]
        recurrence_count = recurrence.get(key, 0)
        priority = CATEGORY_PRIORITY.get(category, CATEGORY_PRIORITY["unknown"])
        score = [priority, -group_count, -recurrence_count, str(failure.get("test") or "")]
        linked_files = linked_files_for_failure(failure)
        entries.append({
            "group_id": group_id,
            "category": category,
            "rank_score": score,
            "priority": priority,
            "group_size": group_count,
            "recurrences_7d": recurrence_count,
            "suite": failure.get("suite"),
            "test": failure.get("test"),
            "key": key,
            "status": failure.get("status"),
            "reason": reason,
            "error": failure.get("error"),
            "run_id": failure.get("run_id"),
            "github_run_id": failure.get("github_run_id"),
            "github_run_url": failure.get("github_run_url"),
            "linked_files": linked_files,
            "verification_command": verification_command(failure),
        })

    entries.sort(key=lambda entry: entry["rank_score"])
    for index, entry in enumerate(entries, start=1):
        entry["rank"] = index

    triage = {
        "run_id": state.get("latest_run_id"),
        "generated_at": utc_now(),
        "summary": state.get("summary") or {},
        "entries": entries,
        "groups": build_group_summary(entries),
    }
    write_json(TRIAGE_FILE, triage)
    write_json(TEST_FILE_INDEX_FILE, {
        "generated_at": triage["generated_at"],
        "tests": {entry["key"]: entry["linked_files"] for entry in entries},
    })
    return triage


def build_group_summary(entries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    groups: dict[str, dict[str, Any]] = {}
    for entry in entries:
        group = groups.setdefault(entry["group_id"], {
            "group_id": entry["group_id"],
            "category": entry["category"],
            "priority": entry["priority"],
            "reason": entry["reason"],
            "tests": [],
            "linked_files": [],
        })
        group["tests"].append(entry["test"])
        group["linked_files"].extend(entry.get("linked_files") or [])
    for group in groups.values():
        group["count"] = len(group["tests"])
        group["linked_files"] = sorted(set(group["linked_files"]))[:MAX_LINKED_FILES]
    return sorted(groups.values(), key=lambda group: (group["priority"], -group["count"], group["group_id"]))


def verification_command(failure: dict[str, Any]) -> str:
    suite = str(failure.get("suite") or "")
    label = str(failure.get("test") or "")
    if suite == "playwright" and label.endswith(".spec.ts"):
        return f"python3 scripts/tests.py run --spec {label}"
    if suite.startswith("pytest"):
        return "python3 scripts/tests.py run --suite pytest"
    if suite.startswith("vitest"):
        return "python3 scripts/tests.py run --suite vitest"
    if suite == "cli":
        return "python3 scripts/tests.py run --suite cli"
    return "python3 scripts/tests.py run --only-failed"


def lease_deadline() -> str:
    return (datetime.now(timezone.utc) + timedelta(hours=LEASE_TTL_HOURS)).strftime("%Y-%m-%dT%H:%M:%SZ")


def active_group_ids(leases: list[dict[str, Any]]) -> set[str]:
    now = datetime.now(timezone.utc)
    active = set()
    for lease in leases:
        if lease.get("status") != "active":
            continue
        expires_at = parse_utc(str(lease.get("expires_at") or ""))
        if expires_at is None or expires_at > now:
            active.add(str(lease.get("group_id")))
    return active


def with_lease_lock(callback):
    LEASE_LOCK_FILE.parent.mkdir(parents=True, exist_ok=True)
    with LEASE_LOCK_FILE.open("w", encoding="utf-8") as lock_handle:
        fcntl.flock(lock_handle, fcntl.LOCK_EX)
        return callback()


def load_leases() -> dict[str, Any]:
    return read_json(LEASES_FILE, {"leases": []})


def claim_next(session_id: str, worker_id: str = "", days: int = 7) -> dict[str, Any] | None:
    def _claim() -> dict[str, Any] | None:
        triage = build_triage(days=days)
        leases_data = load_leases()
        leases = list(leases_data.get("leases") or [])
        active = active_group_ids(leases)
        for entry in triage.get("entries") or []:
            if entry["group_id"] in active:
                continue
            digest = hashlib.sha1(f"{entry['group_id']}:{session_id}:{utc_now()}".encode("utf-8")).hexdigest()[:8]
            lease_id = f"lease-{entry['group_id']}-{digest}"
            lease = {
                "lease_id": lease_id,
                "group_id": entry["group_id"],
                "status": "active",
                "session_id": session_id,
                "worker_id": worker_id,
                "leased_at": utc_now(),
                "expires_at": lease_deadline(),
                "entry": entry,
            }
            leases.append(lease)
            leases_data["leases"] = leases
            leases_data["updated_at"] = utc_now()
            write_json(LEASES_FILE, leases_data)
            return lease
        return None
    return with_lease_lock(_claim)


def update_lease(lease_id: str, status: str, **fields: Any) -> dict[str, Any]:
    def _update() -> dict[str, Any]:
        leases_data = load_leases()
        leases = list(leases_data.get("leases") or [])
        for lease in leases:
            if lease.get("lease_id") == lease_id:
                lease["status"] = status
                lease["updated_at"] = utc_now()
                lease.update(fields)
                leases_data["leases"] = leases
                leases_data["updated_at"] = utc_now()
                write_json(LEASES_FILE, leases_data)
                return lease
        raise RuntimeError(f"Unknown lease id: {lease_id}")
    return with_lease_lock(_update)


def complete_lease(lease_id: str, commit: str = "") -> dict[str, Any]:
    return update_lease(lease_id, "completed", completed_at=utc_now(), commit=commit)


def release_lease(lease_id: str, reason: str = "") -> dict[str, Any]:
    return update_lease(lease_id, "released", released_at=utc_now(), release_reason=reason)


def print_status(state: dict[str, Any]) -> None:
    summary = state.get("summary") or {}
    print(f"Run: {state.get('latest_run_id') or 'none'}")
    print(f"Updated: {state.get('updated_at') or 'never'}")
    print(
        "Summary: "
        f"{summary.get('passed', 0)} passed, "
        f"{summary.get('failed', 0)} failed, "
        f"{summary.get('skipped', 0)} skipped, "
        f"{summary.get('not_started', 0)} not started"
    )
    running = [test for test in (state.get("tests") or {}).values() if test.get("status") == "running"]
    if running:
        print(f"Running: {len(running)}")
        for test in running[:10]:
            print(f"  - [{test.get('suite')}] {test.get('test')}")


def print_test_list(statuses: set[str]) -> None:
    state = load_state()
    rows = [test for test in (state.get("tests") or {}).values() if str(test.get("status")) in statuses]
    for test in sorted(rows, key=lambda item: (str(item.get("suite")), str(item.get("test")))):
        reason = short_reason(str(test.get("error") or "")) if test.get("error") else ""
        print(f"[{test.get('suite')}] {test.get('test')} — {test.get('status')}" + (f" — {reason}" if reason else ""))
    if not rows:
        print("No matching tests.")


def print_history(days: int) -> None:
    events = load_history_events(days=days)
    for event in events:
        reason = short_reason(str(event.get("error") or "")) if event.get("error") else ""
        print(
            f"{event.get('timestamp')} [{event.get('suite')}] {event.get('test')} "
            f"{event.get('event')} {event.get('run_id')}" + (f" — {reason}" if reason else "")
        )
    if not events:
        print(f"No history events in the last {days} day(s).")


def print_triage(triage: dict[str, Any], as_json: bool = False) -> None:
    if as_json:
        print(json.dumps(triage, indent=2, sort_keys=True))
        return
    entries = triage.get("entries") or []
    print(f"Run: {triage.get('run_id') or 'none'}")
    print(f"Failures: {len(entries)}")
    for entry in entries:
        print(f"#{entry['rank']} [{entry['category']}] {entry['test']} — {entry['reason']}")
        if entry.get("linked_files"):
            print("  files: " + ", ".join(entry["linked_files"][:5]))


def infer_run_suite_and_tests(args: list[str]) -> tuple[str, list[str]]:
    suite = "all"
    tests: list[str] = []
    for index, arg in enumerate(args):
        if arg == "--suite" and index + 1 < len(args):
            suite = args[index + 1]
        if arg == "--spec" and index + 1 < len(args):
            suite = "playwright"
            tests.append(args[index + 1])
    if "--only-failed" in args:
        tests = ["only-failed"]
    return suite, tests


def command_run(runner_args: list[str]) -> int:
    command = [sys.executable, str(RUN_TESTS_SCRIPT), *runner_args]
    suite, tests = infer_run_suite_and_tests(runner_args)
    mark_running(suite=suite, tests=tests, command=["python3", "scripts/run_tests.py", *runner_args])
    result = subprocess.run(command, cwd=PROJECT_ROOT)
    last_run = RESULTS_DIR / "last-run.json"
    if last_run.is_file():
        record_run_result(read_json(last_run, {}))
    return result.returncode


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="OpenMates unified test control plane")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("status", help="Show latest normalized test state")
    sub.add_parser("failed", help="List currently failed/problem tests")
    sub.add_parser("skipped", help="List currently skipped tests")

    history_parser = sub.add_parser("history", help="Show test event timeline")
    history_parser.add_argument("--days", type=int, default=7)

    triage_parser = sub.add_parser("triage", help="Classify and rank current failures")
    triage_parser.add_argument("--days", type=int, default=7)
    triage_parser.add_argument("--json", action="store_true")

    next_parser = sub.add_parser("next", help="Return or lease the next failure group")
    next_parser.add_argument("--lease", action="store_true")
    next_parser.add_argument("--session", default="manual")
    next_parser.add_argument("--worker", default="")
    next_parser.add_argument("--days", type=int, default=7)
    next_parser.add_argument("--json", action="store_true")

    complete_parser = sub.add_parser("complete", help="Mark a failure lease completed")
    complete_parser.add_argument("--lease", required=True)
    complete_parser.add_argument("--commit", default="")

    release_parser = sub.add_parser("release", help="Release a failure lease")
    release_parser.add_argument("--lease", required=True)
    release_parser.add_argument("--reason", default="")

    run_parser = sub.add_parser("run", help="Run tests through scripts/run_tests.py and record state")
    run_parser.add_argument("runner_args", nargs=argparse.REMAINDER)

    args = parser.parse_args(argv)
    if args.command == "status":
        print_status(load_state())
        return 0
    if args.command == "failed":
        print_test_list(PROBLEM_STATUSES)
        return 0
    if args.command == "skipped":
        print_test_list({"skipped", "not_started"})
        return 0
    if args.command == "history":
        print_history(args.days)
        return 0
    if args.command == "triage":
        print_triage(build_triage(days=args.days), as_json=args.json)
        return 0
    if args.command == "next":
        if args.lease:
            lease = claim_next(session_id=args.session, worker_id=args.worker, days=args.days)
            if lease is None:
                print("No unleased failed test groups.")
                return 1
            if args.json:
                print(json.dumps(lease, indent=2, sort_keys=True))
            else:
                entry = lease["entry"]
                print(f"LEASE: {lease['lease_id']}")
                print(f"NEXT: {entry['test']}")
                print(f"CATEGORY: {entry['category']}")
                print(f"REASON: {entry['reason']}")
                print(f"VERIFY: {entry['verification_command']}")
                if entry.get("linked_files"):
                    print("FILES: " + ", ".join(entry["linked_files"][:8]))
            return 0
        triage = build_triage(days=args.days)
        entry = (triage.get("entries") or [None])[0]
        print(json.dumps(entry, indent=2, sort_keys=True) if args.json else (entry or "No failed tests."))
        return 0 if entry else 1
    if args.command == "complete":
        print(json.dumps(complete_lease(args.lease, commit=args.commit), indent=2, sort_keys=True))
        return 0
    if args.command == "release":
        print(json.dumps(release_lease(args.lease, reason=args.reason), indent=2, sort_keys=True))
        return 0
    if args.command == "run":
        runner_args = list(args.runner_args)
        if runner_args and runner_args[0] == "--":
            runner_args = runner_args[1:]
        return command_run(runner_args)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
