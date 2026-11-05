#!/usr/bin/env python3
"""Guarded dev-only auto-fix launcher and path guard (autofix.guarded-dev-only).

Only an urgent verdict with an allowlisted fix class and permitted target paths
starts a separate fix chat. Its prompt is built solely from validated verdict
fields and inventory coordinates, never from fetched advisory text
(triage.untrusted-input). The chat follows .claude/skills/security-fix and must
run `autofix.py guard --session <id>` before `sessions.py deploy`; afterwards
the dispatcher re-checks the deployed commit's paths and runs the dev smoke
check deterministically. Reverting a deployed commit needs a human (there is
no sanctioned automatic revert path), so a failed smoke check raises an alert
that says the vulnerability is still open and a manual revert is required.

CLI:
  autofix.py guard --session <id>      (or --worktree <path> --base <rev>)
  autofix.py verify-commit <sha>
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import json
import os
from pathlib import Path
import re
import shlex
import subprocess
import sys
from typing import Any, Callable, Mapping, Sequence

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from security_monitoring.config import CREDENTIAL_READ_DENIES, Settings, canonical_root, is_forbidden_path  # noqa: E402 - path set above
from security_monitoring.models import Asset, TriageVerdict  # noqa: E402 - path set above

COMMIT_RE = re.compile(r"[0-9a-f]{7,40}")
SESSION_RE = re.compile(r"[A-Za-z0-9_-]{2,64}")
FIX_STATUSES = ("deployed", "mitigation_deployed", "refused", "failed")
REFUSAL_CODES = (
    "forbidden_path_required",
    "release_age_refused_no_mitigation",
    "ci_failed",
    "guard_failed",
    "not_reproducible",
    "other",
)
RELEASE_AGE_ECOSYSTEMS = ("npm", "PyPI", "crates.io")

FIX_ALLOWED_TOOLS: tuple[str, ...] = (
    "Read",
    "Grep",
    "Glob",
    "Edit",
    "Write",
    "Bash(cd:*)",
    "Bash(git status:*)",
    "Bash(git diff:*)",
    "Bash(git log:*)",
    "Bash(python3 scripts/sessions.py start:*)",
    "Bash(python3 scripts/sessions.py status:*)",
    "Bash(python3 scripts/sessions.py ci-source:*)",
    "Bash(python3 scripts/sessions.py deploy:*)",
    "Bash(python3 scripts/sessions.py wait-deploy:*)",
    "Bash(python3 scripts/ci_coordinator.py submit:*)",
    "Bash(python3 scripts/ci_coordinator.py wait:*)",
    "Bash(python3 scripts/ci_coordinator.py result:*)",
    "Bash(python3 scripts/security_monitoring/release_age.py:*)",
    "Bash(python3 scripts/security_monitoring/autofix.py guard:*)",
    "Bash(python3 scripts/heavy_slot.py run -- pnpm install:*)",
    "Bash(python3 scripts/heavy_slot.py run -- pnpm update:*)",
    "Bash(python3 scripts/heavy_slot.py run -- pip-compile:*)",
    "Bash(python3 scripts/heavy_slot.py run -- uv pip compile:*)",
    "Bash(python3 scripts/heavy_slot.py run -- uv lock:*)",
)
_FORBIDDEN_GLOBS = (
    "**/.claude/**", "**/.github/workflows/**", "**/deployment/**", "**/scripts/security_monitoring/**",
    "**/scripts/security_monitor.py", "**/CLAUDE.md", "**/.env*", "**/*secret*", "**/*vault*",
)
FIX_DISALLOWED_TOOLS: tuple[str, ...] = (
    "WebFetch",
    "WebSearch",
    "NotebookEdit",
    "Agent",
    "Task",
    "Bash(git push:*)",
    "Bash(git commit:*)",
    "Bash(git -C:*)",
    "Bash(git reset:*)",
    "Bash(git revert:*)",
    "Bash(git stash:*)",
    "Bash(curl:*)",
    "Bash(wget:*)",
    "Bash(ssh:*)",
    "Bash(scp:*)",
    "Bash(sudo:*)",
    "Bash(rm:*)",
    "Bash(env:*)",
    "Bash(printenv:*)",
    "Bash(gh:*)",
    "Bash(openmates:*)",
    "Bash(docker:*)",
    *(f"Edit({glob})" for glob in _FORBIDDEN_GLOBS),
    *(f"Write({glob})" for glob in _FORBIDDEN_GLOBS),
    *CREDENTIAL_READ_DENIES,
)

FIX_SYSTEM_PROMPT = (
    "You are the OpenMates guarded security fix step. Follow .claude/skills/security-fix/SKILL.md exactly. "
    "Work only in your own sessions.py workspace, publish only with sessions.py deploy to dev, never to "
    "production. Run the guard before deploy. Return only the JSON object required by the schema."
)


def fix_output_schema() -> dict[str, Any]:
    nullable = {"type": ["string", "null"], "maxLength": 200}
    return {
        "type": "object",
        "additionalProperties": False,
        "required": ["status", "session_id", "commit", "ci_run_id", "release_age_mode", "changed_files", "refusal_code"],
        "properties": {
            "status": {"type": "string", "enum": list(FIX_STATUSES)},
            "session_id": nullable,
            "commit": nullable,
            "ci_run_id": nullable,
            "release_age_mode": {"type": ["string", "null"], "enum": ["immediate", "emergency", "mitigate", None]},
            "changed_files": {"type": "array", "items": {"type": "string", "maxLength": 300}, "maxItems": 50},
            "refusal_code": {"type": ["string", "null"], "enum": [*REFUSAL_CODES, None]},
        },
    }


def fix_request(verdict: TriageVerdict, incident_id: str, assets: Sequence[Asset], advisory_ids: Sequence[str], *, known_exploited: bool) -> dict[str, Any]:
    """Structured fix input: validated verdict fields plus inventory coordinates only."""
    fix = verdict.proposed_fix
    if fix is None:
        raise ValueError("fix request requires a proposed fix")
    exposed = known_exploited or any(asset.exposure == "internet_facing" for asset in assets)
    ecosystems = sorted({asset.ecosystem for asset in assets if fix.package and asset.name.lower() == fix.package.lower()})
    return {
        "incident_id": incident_id,
        "advisory_ids": [item for item in advisory_ids if re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.:-]{2,80}", item)][:8],
        "observation_identity": verdict.observation_identity,
        "fix_class": fix.fix_class,
        "target_files": list(fix.target_files),
        "package": fix.package,
        "ecosystem": ecosystems[0] if ecosystems else None,
        "from_version": fix.from_version,
        "target_version": fix.target_version,
        "mitigation": fix.mitigation,
        "environments": list(verdict.environments_assessed),
        "urgent_reachable_exposed": bool(verdict.outcome == "urgent" and exposed),
        "release_age_required": bool(fix.fix_class == "dependency_bump" and ecosystems and ecosystems[0] in RELEASE_AGE_ECOSYSTEMS),
    }


def build_fix_prompt(request: Mapping[str, Any]) -> str:
    return (
        "Run the security-fix skill for this validated fix request. It is the complete input; do not fetch "
        "advisory pages.\nBEGIN_FIX_REQUEST_JSON\n"
        + json.dumps(request, sort_keys=True, indent=1)
        + "\nEND_FIX_REQUEST_JSON\n"
    )


def build_fix_command(settings: Settings) -> list[str]:
    command = [
        settings.claude_bin, "-p",
        "--output-format", "json",
        "--json-schema", json.dumps(fix_output_schema(), separators=(",", ":")),
        "--permission-mode", "default",
        "--setting-sources", "project",
        "--strict-mcp-config",
        "--no-session-persistence",
        "--max-budget-usd", f"{settings.fix_budget_usd:.2f}",
        "--append-system-prompt", FIX_SYSTEM_PROMPT,
        "--allowedTools", *FIX_ALLOWED_TOOLS,
        "--disallowedTools", *FIX_DISALLOWED_TOOLS,
    ]
    if settings.triage_model:
        command[2:2] = ["--model", settings.triage_model]
    return command


@dataclass(frozen=True)
class FixOutcome:
    status: str  # deployed | mitigation_deployed | refused | failed | guard_violation | smoke_failed | skipped
    reason: str | None = None
    commit: str | None = None
    session_id: str | None = None
    dev_deploy: str = "not_deployed"
    changed_files: tuple[str, ...] = ()
    forbidden_files: tuple[str, ...] = ()
    revert_required: bool = False

    def automatic_actions(self) -> dict[str, Any]:
        summary = {
            "deployed": "dependency fix deployed to dev",
            "mitigation_deployed": "mitigation deployed to dev; version bump scheduled once a qualifying release exists",
            "refused": f"automatic fix refused ({self.reason})",
            "failed": f"automatic fix failed ({self.reason})",
            "guard_violation": f"auto-fix guard violation ({self.reason}); manual review required",
            "smoke_failed": "dev smoke failed after the fix; manual revert required, vulnerability still open",
            "skipped": f"no automatic fix ({self.reason})",
        }[self.status]
        return {"summary": summary, "commit": self.commit, "dev_deploy": self.dev_deploy, "revert_required": self.revert_required}


Runner = Callable[..., subprocess.CompletedProcess]


def _parse_fix_output(stdout: str) -> dict[str, Any]:
    envelope = json.loads(stdout)
    if not isinstance(envelope, dict) or envelope.get("is_error"):
        raise ValueError("agent_reported_error")
    structured = envelope.get("structured_output")
    if structured is None and isinstance(envelope.get("result"), str):
        structured = json.loads(envelope["result"])
    if not isinstance(structured, dict) or structured.get("status") not in FIX_STATUSES:
        raise ValueError("invalid_fix_output")
    commit = structured.get("commit")
    if structured["status"] in {"deployed", "mitigation_deployed"} and not (isinstance(commit, str) and COMMIT_RE.fullmatch(commit)):
        raise ValueError("missing_commit")
    session = structured.get("session_id")
    if session is not None and not (isinstance(session, str) and SESSION_RE.fullmatch(session)):
        raise ValueError("invalid_session_id")
    if structured.get("refusal_code") not in (*REFUSAL_CODES, None):
        raise ValueError("invalid_refusal_code")
    return structured


def _checkout_status(root: Path, runner: Runner) -> str:
    result = runner(["git", "-C", str(root), "status", "--porcelain"], capture_output=True, text=True, check=False, timeout=60)
    return result.stdout if result.returncode == 0 else "unavailable"


def commit_changed_files(root: Path, commit: str, runner: Runner = subprocess.run) -> list[str]:
    result = runner(["git", "-C", str(root), "show", "--name-only", "--format=", commit], capture_output=True, text=True, check=False, timeout=60)
    if result.returncode != 0:
        raise ValueError("commit_not_found")
    return [line.strip() for line in result.stdout.splitlines() if line.strip()]


def run_dev_smoke(settings: Settings, runner: Runner = subprocess.run) -> bool:
    result = runner(shlex.split(settings.dev_smoke_command), cwd=str(settings.project_root), capture_output=True, text=True, check=False, timeout=45 * 60)
    return result.returncode == 0


def run_fix(*, settings: Settings, request: Mapping[str, Any], runner: Runner = subprocess.run, smoke: Callable[[Settings], bool] | None = None) -> FixOutcome:
    """Launch one fix chat, then verify the deployed commit and dev smoke deterministically."""
    forbidden_targets = [path for path in request.get("target_files", []) if is_forbidden_path(path)]
    if forbidden_targets:
        return FixOutcome("refused", "forbidden_target_path", forbidden_files=tuple(forbidden_targets))
    before = _checkout_status(settings.project_root, runner)
    try:
        completed = runner(
            build_fix_command(settings), input=build_fix_prompt(request), capture_output=True, text=True,
            cwd=str(settings.project_root), timeout=settings.fix_timeout_seconds, check=False,
            env={key: value for key, value in os.environ.items() if not key.startswith(("DISCORD_WEBHOOK", "SECURITY_REPORTING"))},
        )
    except subprocess.TimeoutExpired:
        return FixOutcome("failed", "timeout")
    except OSError:
        return FixOutcome("failed", "launch_failed")
    after = _checkout_status(settings.project_root, runner)
    if before != after:
        # Fail closed: the fix chat may only edit its own session worktree. Another
        # process may also have changed the checkout, so ask for review, not a revert.
        return FixOutcome("guard_violation", "canonical_checkout_changed_during_fix")
    if completed.returncode != 0:
        return FixOutcome("failed", "nonzero_exit")
    try:
        output = _parse_fix_output(completed.stdout or "")
    except json.JSONDecodeError:
        return FixOutcome("failed", "output_not_json")
    except ValueError as error:
        return FixOutcome("failed", str(error))
    if output["status"] in {"refused", "failed"}:
        return FixOutcome(output["status"], output.get("refusal_code") or "unspecified", session_id=output.get("session_id"))
    commit = output["commit"]
    try:
        changed = commit_changed_files(settings.project_root, commit, runner)
    except ValueError:
        return FixOutcome("failed", "commit_not_found", commit=commit, session_id=output.get("session_id"), dev_deploy="unknown")
    forbidden = tuple(path for path in changed if is_forbidden_path(path))
    if forbidden:
        return FixOutcome("guard_violation", "forbidden_path_in_deployed_commit", commit=commit, session_id=output.get("session_id"),
                          dev_deploy="deployed", changed_files=tuple(changed), forbidden_files=forbidden, revert_required=True)
    smoke_ok = (smoke or (lambda s: run_dev_smoke(s, runner)))(settings)
    if not smoke_ok:
        return FixOutcome("smoke_failed", "dev_smoke_failed", commit=commit, session_id=output.get("session_id"),
                          dev_deploy="deployed_smoke_failed", changed_files=tuple(changed), revert_required=True)
    return FixOutcome(output["status"], None, commit=commit, session_id=output.get("session_id"), dev_deploy="deployed", changed_files=tuple(changed))


# --- guard CLI ----------------------------------------------------------------
def session_worktree(session_id: str, root: Path, runner: Runner = subprocess.run) -> tuple[Path, str]:
    result = runner([sys.executable, str(root / "scripts" / "sessions.py"), "status", "--session", session_id, "--json"],
                    capture_output=True, text=True, check=False, timeout=60, cwd=str(root))
    if result.returncode != 0:
        raise ValueError("session_not_found")
    session = (json.loads(result.stdout).get("sessions") or {}).get(session_id) or {}
    worktree = session.get("worktree") or {}
    if not worktree.get("path") or not worktree.get("base_commit"):
        raise ValueError("session_worktree_unknown")
    return Path(worktree["path"]), str(worktree["base_commit"])


def worktree_changed_files(worktree: Path, base: str, runner: Runner = subprocess.run) -> list[str]:
    tracked = runner(["git", "-C", str(worktree), "diff", "--name-only", base], capture_output=True, text=True, check=False, timeout=60)
    untracked = runner(["git", "-C", str(worktree), "ls-files", "--others", "--exclude-standard"], capture_output=True, text=True, check=False, timeout=60)
    if tracked.returncode != 0 or untracked.returncode != 0:
        raise ValueError("diff_unavailable")
    return sorted({line.strip() for line in (tracked.stdout + "\n" + untracked.stdout).splitlines() if line.strip()})


def guard(changed: Sequence[str]) -> dict[str, Any]:
    forbidden = [path for path in changed if is_forbidden_path(path)]
    return {"ok": not forbidden and bool(changed), "changed_files": list(changed), "forbidden_files": forbidden,
            "reason": "forbidden_paths" if forbidden else (None if changed else "empty_diff")}


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    commands = parser.add_subparsers(dest="command", required=True)
    guard_parser = commands.add_parser("guard", help="refuse a fix workspace that touches forbidden paths")
    guard_parser.add_argument("--session")
    guard_parser.add_argument("--worktree", type=Path)
    guard_parser.add_argument("--base")
    verify = commands.add_parser("verify-commit", help="check a deployed commit's paths")
    verify.add_argument("commit")
    args = parser.parse_args(argv)
    root = canonical_root()
    try:
        if args.command == "guard":
            if args.session:
                worktree, base = session_worktree(args.session, root)
            elif args.worktree and args.base:
                worktree, base = args.worktree, args.base
            else:
                parser.error("guard needs --session or --worktree with --base")
            result = guard(worktree_changed_files(worktree, base))
        else:
            if not COMMIT_RE.fullmatch(args.commit):
                parser.error("commit must be a hex sha")
            result = guard(commit_changed_files(root, args.commit))
    except ValueError as error:
        result = {"ok": False, "reason": str(error), "changed_files": [], "forbidden_files": []}
    print(json.dumps(result, sort_keys=True))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
