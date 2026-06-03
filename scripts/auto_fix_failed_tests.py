#!/usr/bin/env python3
"""
scripts/auto_fix_failed_tests.py

Sequential controller for unattended OpenCode fixes after daily test failures.
The script processes one root-cause group at a time, waits for OpenCode to exit,
runs verification itself, posts Discord summaries, and only then advances.
It runs by default from the daily runner and can be disabled with
E2E_AUTO_FIX_FAILED_TESTS=false.
"""

from __future__ import annotations

import argparse
import base64
import fcntl
import hashlib
import json
import os
import re
import subprocess
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parent.parent
RESULTS_DIR = PROJECT_ROOT / "test-results"
TMP_DIR = PROJECT_ROOT / "scripts" / ".tmp" / "auto-fix"
PROMPT_TEMPLATE = PROJECT_ROOT / "scripts" / "prompts" / "auto-fix-failed-test-group.md"
LOCKFILE = Path("/tmp/openmates-auto-fix-failed-tests.lock")
STATE_FILE = RESULTS_DIR / "auto-fix-state.json"
GH_BRANCH = "dev"

DEFAULT_TIMEOUT_SECONDS = 1800
DEFAULT_MAX_GROUPS = 999
DEFAULT_MAX_ATTEMPTS_PER_GROUP = 5
DEFAULT_MAX_CHANGED_FILES = 5
DEFAULT_MAX_DIFF_LINES = 200
MAX_FAILURES_PER_GROUP = 8
IGNORED_CHANGED_FILE_PREFIXES = ("test-results/", "logs/", "scripts/.tmp/")

RISKY_PATH_RE = re.compile(
    r"(^|/)(auth|payments?|billing|stripe|encryption|sync|websockets?|migrations?|privacy|legal)(/|$)",
    re.IGNORECASE,
)


@dataclass
class FixGroup:
    id: str
    suite: str
    tests: list[dict[str, Any]]
    verify_command: list[str]


def log(message: str) -> None:
    print(f"[auto-fix] {message}", flush=True)


def load_dotenv() -> None:
    env_path = PROJECT_ROOT / ".env"
    if not env_path.is_file():
        return
    for line in env_path.read_text(errors="replace").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def run_command(command: list[str], timeout: int | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        cwd=PROJECT_ROOT,
        env=build_env(),
        capture_output=True,
        text=True,
        timeout=timeout,
    )


def build_env() -> dict[str, str]:
    env = os.environ.copy()
    env["PATH"] = (
        "/home/superdev/.local/bin:/home/superdev/.npm-global/bin:"
        + env.get("PATH", "/usr/local/bin:/usr/bin:/bin")
    )
    return env


def env_value(name: str) -> str:
    return os.environ.get(name, "").strip()


def project_path_token(path: Path) -> str:
    encoded = base64.urlsafe_b64encode(str(path).encode("utf-8")).decode("ascii")
    return encoded.rstrip("=")


def build_opencode_session_url(opencode_session_id: str) -> str:
    base_url = env_value("OPENCODE_WEB_BASE_URL")
    if not base_url:
        return ""
    return f"{base_url.rstrip('/')}/{project_path_token(PROJECT_ROOT)}/session/{opencode_session_id}"


def extract_opencode_session_id(output: str) -> str:
    for line in output.splitlines():
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        session_id = event.get("sessionID") or event.get("session_id")
        if session_id:
            return str(session_id)
    return ""


def git_status_porcelain() -> list[str]:
    result = run_command(["git", "status", "--porcelain"], timeout=60)
    if result.returncode != 0:
        raise RuntimeError((result.stderr or result.stdout).strip()[:500])
    ignored_prefixes = (
        "?? test-results/",
        "?? logs/",
        "?? scripts/.tmp/",
        " M test-results/",
        " M logs/",
    )
    return [line for line in result.stdout.splitlines() if not line.startswith(ignored_prefixes)]


def log_dirty_worktree_context() -> None:
    dirty = git_status_porcelain()
    if dirty:
        log(f"Worktree has {len(dirty)} unrelated non-ignored change(s); continuing with session-scoped deploy.")


def load_failed_tests() -> tuple[str, list[dict[str, Any]]]:
    path = RESULTS_DIR / "last-failed-tests.json"
    if not path.is_file():
        raise FileNotFoundError(f"{path} not found")
    data = json.loads(path.read_text())
    tests = [t for t in data.get("tests", []) if t.get("status") == "failed"]
    return str(data.get("run_id", "unknown")), tests


def normalize_error(error: str) -> str:
    lines = [line.strip() for line in (error or "").splitlines() if line.strip()]
    interesting = []
    for line in lines:
        if line.startswith(("E   ", "Error:", "AssertionError", "RuntimeError", "ImportError", "AttributeError")):
            interesting.append(line)
        if len(interesting) >= 2:
            break
    basis = "\n".join(interesting or lines[:2])
    return re.sub(r"0x[0-9a-fA-F]+|\d+\.\d+s|\d+ms", "<var>", basis)[:500]


def group_failures(tests: list[dict[str, Any]]) -> list[FixGroup]:
    buckets: dict[str, list[dict[str, Any]]] = {}
    for test in tests:
        suite = str(test.get("suite") or "unknown")
        file_name = str(test.get("file") or test.get("name") or "unknown")
        if suite == "playwright":
            key = f"{suite}:{file_name}"
        else:
            key = f"{suite}:{normalize_error(str(test.get('error') or ''))}"
        buckets.setdefault(key, []).append(test)

    groups: list[FixGroup] = []
    for index, (key, grouped_tests) in enumerate(buckets.items(), start=1):
        digest = hashlib.sha1(key.encode("utf-8")).hexdigest()[:8]
        group_id = f"g{index:02d}-{digest}"
        suite = str(grouped_tests[0].get("suite") or "unknown")
        groups.append(
            FixGroup(
                id=group_id,
                suite=suite,
                tests=grouped_tests[:MAX_FAILURES_PER_GROUP],
                verify_command=verification_command(suite, grouped_tests),
            )
        )
    return groups


def verification_command(suite: str, tests: list[dict[str, Any]]) -> list[str]:
    if suite == "playwright":
        spec = str(tests[0].get("file") or tests[0].get("name") or "").strip()
        if spec.endswith(".spec.ts"):
            return [sys.executable, "scripts/run_tests.py", "--spec", spec]
        return [sys.executable, "scripts/run_tests.py", "--suite", "playwright", "--only-failed"]
    if suite.startswith("pytest"):
        return [sys.executable, "scripts/run_tests.py", "--suite", "pytest"]
    if suite.startswith("vitest"):
        return [sys.executable, "scripts/run_tests.py", "--suite", "vitest"]
    return [sys.executable, "scripts/run_tests.py", "--only-failed"]


def start_controller_session(group: FixGroup) -> str:
    result = run_command(
        [
            sys.executable,
            "scripts/sessions.py",
            "start",
            "--mode",
            "bug",
            "--task",
            f"auto-fix failed test group {group.id}",
        ],
        timeout=120,
    )
    if result.returncode != 0:
        raise RuntimeError((result.stderr or result.stdout).strip()[:1000])
    match = re.search(r"== SESSION\s+([a-z0-9]+)", result.stdout)
    if not match:
        raise RuntimeError(f"Could not parse session id from sessions.py output: {result.stdout[:1000]}")
    return match.group(1)


def render_prompt(
    group: FixGroup,
    run_id: str,
    session_id: str,
    summary_path: Path,
    attempt: int,
    max_attempts: int,
    previous_attempts: list[dict[str, Any]],
) -> str:
    template = PROMPT_TEMPLATE.read_text()
    failed_tests_json = json.dumps(group.tests, indent=2)
    previous_attempts_json = json.dumps(previous_attempts, indent=2)
    verify_command = " ".join(group.verify_command)
    replacements = {
        "{{SESSION_ID}}": session_id,
        "{{GROUP_ID}}": group.id,
        "{{RUN_ID}}": run_id,
        "{{ATTEMPT_NUMBER}}": str(attempt),
        "{{MAX_ATTEMPTS}}": str(max_attempts),
        "{{VERIFY_COMMAND}}": verify_command,
        "{{FAILED_TESTS_JSON}}": failed_tests_json,
        "{{PREVIOUS_ATTEMPTS_JSON}}": previous_attempts_json,
        "{{SUMMARY_PATH}}": str(summary_path.relative_to(PROJECT_ROOT)),
    }
    for token, value in replacements.items():
        template = template.replace(token, value)
    return template


def run_opencode(
    group: FixGroup,
    run_id: str,
    session_id: str,
    timeout: int,
    attempt: int,
    max_attempts: int,
    previous_attempts: list[dict[str, Any]],
) -> tuple[int, str, Path, str, str]:
    TMP_DIR.mkdir(parents=True, exist_ok=True)
    group_dir = TMP_DIR / group.id
    group_dir.mkdir(parents=True, exist_ok=True)
    summary_path = group_dir / f"summary-attempt-{attempt}.json"
    prompt_path = group_dir / f"prompt-attempt-{attempt}.md"
    prompt_path.write_text(
        render_prompt(group, run_id, session_id, summary_path, attempt, max_attempts, previous_attempts),
        encoding="utf-8",
    )
    message = f"Read {prompt_path.relative_to(PROJECT_ROOT)} in full and follow it exactly."
    result = run_command(
        [
            "opencode",
            "run",
            "--title",
            f"auto-fix failed tests {group.id} attempt {attempt}",
            "--format",
            "json",
            "--dangerously-skip-permissions",
            message,
        ],
        timeout=timeout,
    )
    output_path = group_dir / f"opencode-output-attempt-{attempt}.jsonl"
    combined_output = (result.stdout or "") + "\n" + (result.stderr or "")
    output_path.write_text(combined_output, encoding="utf-8")
    opencode_session_id = extract_opencode_session_id(combined_output)
    opencode_session_url = build_opencode_session_url(opencode_session_id) if opencode_session_id else ""
    if opencode_session_id:
        log(f"OpenCode chat for {group.id}: {opencode_session_url or opencode_session_id}")
    return (
        result.returncode,
        str(output_path.relative_to(PROJECT_ROOT)),
        summary_path,
        opencode_session_id,
        opencode_session_url,
    )


def load_summary(summary_path: Path, group: FixGroup, session_id: str) -> dict[str, Any]:
    if not summary_path.is_file():
        return {
            "status": "failed",
            "scope_classification": "requires_human_approval",
            "group_id": group.id,
            "session_id": session_id,
            "root_cause": "OpenCode did not write the required summary JSON.",
            "changes_applied": [],
            "changed_files": [],
            "verification_command": " ".join(group.verify_command),
            "verification_result": "not_run",
            "reason": "missing summary.json",
        }
    try:
        summary = json.loads(summary_path.read_text())
    except json.JSONDecodeError as exc:
        return {
            "status": "failed",
            "scope_classification": "requires_human_approval",
            "group_id": group.id,
            "session_id": session_id,
            "root_cause": "OpenCode wrote invalid summary JSON.",
            "changes_applied": [],
            "changed_files": [],
            "verification_command": " ".join(group.verify_command),
            "verification_result": "not_run",
            "reason": str(exc),
        }
    summary.setdefault("group_id", group.id)
    summary.setdefault("session_id", session_id)
    summary.setdefault("verification_command", " ".join(group.verify_command))
    return summary


def changed_files() -> list[str]:
    result = run_command(["git", "diff", "--name-only"], timeout=60)
    if result.returncode != 0:
        return []
    tracked = [line.strip() for line in result.stdout.splitlines() if line.strip()]
    untracked = run_command(["git", "ls-files", "--others", "--exclude-standard"], timeout=60)
    extra = [] if untracked.returncode != 0 else [line.strip() for line in untracked.stdout.splitlines() if line.strip()]
    ignored = ("test-results/", "logs/", "scripts/.tmp/")
    return sorted({path for path in tracked + extra if not path.startswith(ignored)})


def diff_line_count(files: list[str]) -> int:
    if not files:
        return 0
    result = run_command(["git", "diff", "--numstat", "--", *files], timeout=60)
    if result.returncode != 0:
        return 0
    total = 0
    for line in result.stdout.splitlines():
        parts = line.split("\t")
        if len(parts) < 3:
            continue
        for value in parts[:2]:
            if value.isdigit():
                total += int(value)
    return total


def normalize_summary_files(summary: dict[str, Any]) -> list[str]:
    files = summary.get("changed_files") or []
    if not isinstance(files, list):
        return []
    normalized = []
    for file_path in files:
        if not isinstance(file_path, str):
            continue
        clean_path = file_path.strip()
        if clean_path and not clean_path.startswith(("/", "..", *IGNORED_CHANGED_FILE_PREFIXES)):
            normalized.append(clean_path)
    return sorted(set(normalized))


def track_session_files(session_id: str, files: list[str]) -> None:
    for file_path in files:
        run_command(
            [sys.executable, "scripts/sessions.py", "track", "--session", session_id, "--file", file_path],
            timeout=60,
        )


def cumulative_changed_files(attempts: list[dict[str, Any]], summary: dict[str, Any]) -> list[str]:
    files: list[str] = []
    for attempt in attempts:
        attempt_files = attempt.get("changed_files", [])
        if isinstance(attempt_files, list):
            files.extend(path for path in attempt_files if isinstance(path, str))
    files.extend(normalize_summary_files(summary))
    return sorted(set(path for path in files if path and not path.startswith(IGNORED_CHANGED_FILE_PREFIXES)))


def classify_diff(summary: dict[str, Any], files: list[str], max_files: int, max_lines: int) -> tuple[bool, str]:
    lines = diff_line_count(files)
    if summary.get("scope_classification") == "requires_human_approval":
        return False, "agent marked fix as requiring human approval"
    if not files and summary.get("status") == "fixed":
        return False, "agent reported fixed but did not list changed files"
    if len(files) > max_files:
        return False, f"changed {len(files)} files, over limit {max_files}"
    if lines > max_lines:
        return False, f"diff has {lines} changed lines, over limit {max_lines}"
    risky = [path for path in files if RISKY_PATH_RE.search(path)]
    if risky:
        return False, f"changed risky path(s): {', '.join(risky[:5])}"
    return True, "minor diff within auto-fix limits"


def run_verification(group: FixGroup, timeout: int) -> tuple[str, int, str]:
    result = run_command(group.verify_command, timeout=timeout)
    output = ((result.stdout or "") + "\n" + (result.stderr or "")).strip()
    if len(output) > 2000:
        output = output[-2000:]
    status = "passed" if result.returncode == 0 else "failed"
    return status, result.returncode, output


def deploy(session_id: str, group: FixGroup, timeout: int) -> tuple[bool, str]:
    title = f"fix: auto-fix failed tests {group.id}"
    message = f"Sequential auto-fix for {len(group.tests)} failed test(s)."
    result = run_command(
        [
            sys.executable,
            "scripts/sessions.py",
            "deploy",
            "--session",
            session_id,
            "--title",
            title,
            "--message",
            message,
            "--end",
        ],
        timeout=timeout,
    )
    output = ((result.stdout or "") + "\n" + (result.stderr or "")).strip()
    match = re.search(r"\b[0-9a-f]{7,40}\b", output)
    commit = match.group(0)[:12] if match else ""
    return result.returncode == 0, commit or output[-500:]


def end_session(session_id: str) -> None:
    run_command([sys.executable, "scripts/sessions.py", "end", "--session", session_id], timeout=120)


def webhook_url() -> str:
    return os.environ.get("DISCORD_WEBHOOK_TEST_FIXES") or os.environ.get("DISCORD_WEBHOOK_DEV_NIGHTLY", "")


def post_discord(summary: dict[str, Any], color: int = 0x3B82F6) -> bool:
    url = webhook_url()
    if not url:
        log("No DISCORD_WEBHOOK_TEST_FIXES or DISCORD_WEBHOOK_DEV_NIGHTLY configured; skipping Discord.")
        return False
    fields = []
    for name, key in (
        ("Status", "status"),
        ("Scope", "scope_classification"),
        ("Verification", "verification_result"),
        ("Commit", "commit_sha"),
        ("OpenCode", "opencode_chat"),
    ):
        value = str(summary.get(key) or "none")[:1000]
        fields.append({"name": name, "value": value, "inline": True})
    description_parts = [
        f"Group `{summary.get('group_id', 'unknown')}`",
        "",
        "Root cause:",
        str(summary.get("root_cause") or "not provided")[:1200],
        "",
        "Changes:",
        "\n".join(f"- {item}" for item in (summary.get("changes_applied") or ["none"]))[:1200],
    ]
    if summary.get("reason"):
        description_parts.extend(["", "Reason:", str(summary["reason"])[:1000]])
    payload = {
        "username": "OpenMates Auto Test Fixer",
        "avatar_url": "https://openmates.org/favicon.png",
        "embeds": [
            {
                "title": "Sequential auto-fix test group summary",
                "description": "\n".join(description_parts)[:4000],
                "color": color,
                "fields": fields,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }
        ],
    }
    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json", "User-Agent": "OpenMates-AutoTestFixer/0.1"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            response.read()
        return True
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")[:300]
        log(f"Discord POST failed: HTTP {exc.code}: {body}")
    except Exception as exc:
        log(f"Discord POST failed: {exc}")
    return False


def save_state(state: dict[str, Any]) -> None:
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps(state, indent=2), encoding="utf-8")


def discord_smoke() -> int:
    summary = {
        "group_id": "discord-smoke",
        "status": "completed",
        "scope_classification": "minor",
        "verification_result": "not_run",
        "commit_sha": "none",
        "root_cause": "Smoke test only. No tests were debugged.",
        "changes_applied": ["Validated Discord summary posting for the future sequential auto-fix controller."],
    }
    return 0 if post_discord(summary) else 1


def compact_attempt_feedback(summary: dict[str, Any]) -> dict[str, Any]:
    return {
        "attempt": summary.get("attempt"),
        "status": summary.get("status"),
        "root_cause": summary.get("root_cause"),
        "changes_applied": summary.get("changes_applied", []),
        "changed_files": summary.get("changed_files", []),
        "verification_result": summary.get("verification_result"),
        "verification_output_tail": summary.get("verification_output_tail", ""),
        "reason": summary.get("reason", ""),
        "safety_check": summary.get("safety_check", ""),
        "opencode_chat": summary.get("opencode_chat", ""),
    }


def process_group(group: FixGroup, run_id: str, args: argparse.Namespace) -> dict[str, Any]:
    session_id = start_controller_session(group)
    summary: dict[str, Any] = {}
    attempts: list[dict[str, Any]] = []
    try:
        log(f"Processing {group.id}: {len(group.tests)} test(s) from suite {group.suite}")
        if args.dry_run:
            summary = {
                "status": "skipped",
                "scope_classification": "minor",
                "group_id": group.id,
                "session_id": session_id,
                "root_cause": "Dry run; OpenCode was not invoked.",
                "changes_applied": [],
                "changed_files": [],
                "verification_command": " ".join(group.verify_command),
                "verification_result": "not_run",
                "reason": "dry run",
            }
            post_discord(summary, color=0x94A3B8)
            return summary

        for attempt in range(1, args.max_attempts_per_group + 1):
            log(f"Attempt {attempt}/{args.max_attempts_per_group} for {group.id}")
            opencode_rc, output_path, summary_path, opencode_session_id, opencode_session_url = run_opencode(
                group,
                run_id,
                session_id,
                args.timeout_seconds,
                attempt,
                args.max_attempts_per_group,
                attempts,
            )
            summary = load_summary(summary_path, group, session_id)
            summary["attempt"] = attempt
            summary["attempts"] = attempts
            summary["opencode_exit_code"] = opencode_rc
            summary["opencode_output"] = output_path
            summary["opencode_session_id"] = opencode_session_id or "unknown"
            summary["opencode_session_url"] = opencode_session_url
            summary["opencode_chat"] = opencode_session_url or opencode_session_id or "unknown"
            summary_files = cumulative_changed_files(attempts, summary)
            summary["changed_files"] = summary_files
            track_session_files(session_id, summary_files)

            if opencode_rc != 0 and summary.get("status") == "fixed":
                summary["status"] = "failed"
                summary["scope_classification"] = "requires_human_approval"
                summary["reason"] = "opencode exited non-zero after reporting fixed"

            safe, safety_reason = classify_diff(summary, summary_files, args.max_changed_files, args.max_diff_lines)
            summary["safety_check"] = safety_reason
            if not safe or summary.get("status") in {"blocked", "failed", "skipped"}:
                if summary.get("status") == "fixed":
                    summary["status"] = "failed"
                summary.setdefault("reason", safety_reason)
                summary["verification_result"] = "not_run"
                summary["attempts"] = attempts + [compact_attempt_feedback(summary)]
                post_discord(summary, color=0xF59E0B)
                return summary

            verify_status, verify_rc, verify_output = run_verification(group, args.verify_timeout_seconds)
            summary["verification_result"] = verify_status
            summary["verification_exit_code"] = verify_rc
            summary["verification_output_tail"] = verify_output

            if verify_status == "passed":
                break

            summary["status"] = "retrying" if attempt < args.max_attempts_per_group else "failed"
            summary["reason"] = "controller verification failed"
            attempts.append(compact_attempt_feedback(summary))
            if attempt < args.max_attempts_per_group:
                log(f"Verification failed for {group.id}; retrying with failure output.")
                continue

            summary["reason"] = f"controller verification failed after {args.max_attempts_per_group} attempt(s)"
            summary["attempts"] = attempts
            post_discord(summary, color=0xEF4444)
            return summary

        if args.no_deploy:
            summary["commit_sha"] = "not deployed (--no-deploy)"
            summary["attempts"] = attempts + [compact_attempt_feedback(summary)]
            post_discord(summary, color=0x22C55E)
            return summary

        deploy_ok, deploy_detail = deploy(session_id, group, args.deploy_timeout_seconds)
        summary["commit_sha"] = deploy_detail if deploy_ok else "deploy failed"
        if not deploy_ok:
            summary["status"] = "failed"
            summary["reason"] = f"deploy failed: {deploy_detail}"
            summary["attempts"] = attempts + [compact_attempt_feedback(summary)]
            post_discord(summary, color=0xEF4444)
            return summary

        summary["status"] = "fixed"
        summary["session_closed_by_deploy"] = True
        summary["attempts"] = attempts + [compact_attempt_feedback(summary)]
        post_discord(summary, color=0x22C55E)
        return summary
    finally:
        if not summary.get("session_closed_by_deploy"):
            end_session(session_id)


def main() -> int:
    load_dotenv()

    parser = argparse.ArgumentParser(description="Sequential OpenCode failed-test auto-fixer")
    parser.add_argument("--from-daily-run", action="store_true", help="Run after daily tests; non-interactive")
    parser.add_argument("--max-groups", type=int, default=int(os.environ.get("AUTO_FIX_MAX_GROUPS_PER_RUN", DEFAULT_MAX_GROUPS)))
    parser.add_argument("--max-attempts-per-group", type=int, default=int(os.environ.get("AUTO_FIX_MAX_ATTEMPTS_PER_GROUP", DEFAULT_MAX_ATTEMPTS_PER_GROUP)))
    parser.add_argument("--timeout-seconds", type=int, default=int(os.environ.get("AUTO_FIX_OPENCODE_TIMEOUT_SECONDS", DEFAULT_TIMEOUT_SECONDS)))
    parser.add_argument("--verify-timeout-seconds", type=int, default=int(os.environ.get("AUTO_FIX_VERIFY_TIMEOUT_SECONDS", "3600")))
    parser.add_argument("--deploy-timeout-seconds", type=int, default=int(os.environ.get("AUTO_FIX_DEPLOY_TIMEOUT_SECONDS", "1800")))
    parser.add_argument("--max-changed-files", type=int, default=int(os.environ.get("AUTO_FIX_MAX_CHANGED_FILES", DEFAULT_MAX_CHANGED_FILES)))
    parser.add_argument("--max-diff-lines", type=int, default=int(os.environ.get("AUTO_FIX_MAX_DIFF_LINES", DEFAULT_MAX_DIFF_LINES)))
    parser.add_argument("--no-deploy", action="store_true", default=os.environ.get("AUTO_FIX_NO_DEPLOY", "").lower() in {"1", "true", "yes"})
    parser.add_argument("--dry-run", action="store_true", help="Build queue and post summaries without running OpenCode")
    parser.add_argument("--discord-smoke", action="store_true", help="Post a smoke message to the configured Discord webhook")
    args = parser.parse_args()

    if args.discord_smoke:
        return discord_smoke()

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    with open(LOCKFILE, "w") as lock_fd:
        try:
            fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            log("Another auto-fix run is already in progress; exiting.")
            return 0

        if not args.dry_run:
            log_dirty_worktree_context()

        run_id, tests = load_failed_tests()
        if not tests:
            log("No failed tests found; nothing to fix.")
            return 0

        groups = group_failures(tests)
        selected = groups[: max(0, args.max_groups)]
        state: dict[str, Any] = {
            "run_id": run_id,
            "started_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "total_failed_tests": len(tests),
            "total_groups": len(groups),
            "processed": [],
        }
        save_state(state)

        for group in selected:
            result = process_group(group, run_id, args)
            state["processed"].append(result)
            state["last_updated_at"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
            save_state(state)
            if result.get("status") in {"blocked", "failed"}:
                log(f"Finished {group.id} with {result.get('status')}; continuing to next independent group.")

        return 0


if __name__ == "__main__":
    sys.exit(main())
