#!/usr/bin/env python3
"""Build sanitized Apple workflow evidence bundles.

Purpose: give humans and OpenCode agents one deterministic Apple debug/parity input.
Architecture: orchestrates existing parity, contract, comparator, and remote-Mac wrappers.
Safety: defaults to Linux-safe static checks; remote Mac commands require explicit opt-in.
Evidence: writes JSON summaries under test-results/apple-evidence for later triage.
Privacy: command output is redacted/truncated before it is persisted.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_EVIDENCE_DIR = ROOT / "test-results" / "apple-evidence"
LATEST_SUMMARY = DEFAULT_EVIDENCE_DIR / "latest-summary.json"
DEFAULT_INVENTORY = ROOT / "test-results" / "apple-parity-inventory.json"
DEFAULT_CHAT_ARTIFACT_DIR = ROOT / "artifacts" / "chat-rendering-parity"
MAX_OUTPUT_CHARS = 20000

STATUS_PASSED = "passed"
STATUS_FAILED = "failed"
STATUS_SKIPPED = "skipped_with_reason"
STATUS_PLANNED = "planned"

SURFACE_UI_CONTRACTS = {
    "chat": ("message-input",),
    "settings": ("settings",),
    "embeds": ("embeds",),
    "all": ("message-input", "settings", "embeds"),
}

EMAIL_RE = re.compile(r"[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}", re.IGNORECASE)
IPV4_RE = re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b")
USER_PATH_RE = re.compile(r"/(?:Users|home)/[^\s:'\"]+")
SHARE_KEY_RE = re.compile(r"#key=[^\s&]+")
SECRET_ENV_RE = re.compile(r"OPENMATES_TEST_ACCOUNT(?:_\d+)?_(?:EMAIL|PASSWORD|OTP_KEY|API_KEY)=\S+")
LONG_HEX_RE = re.compile(r"\b[0-9A-Fa-f]{24,}\b")


@dataclass(frozen=True)
class EvidenceStep:
    name: str
    command: list[str]
    required: bool = True


@dataclass(frozen=True)
class StepResult:
    name: str
    status: str
    command: list[str]
    required: bool
    started_at: str
    completed_at: str
    exit_code: int | None = None
    reason: str = ""
    stdout: str = ""
    stderr: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "status": self.status,
            "command": sanitize_command(self.command),
            "required": self.required,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "exit_code": self.exit_code,
            "reason": self.reason,
            "stdout": truncate_output(sanitize_output(self.stdout)),
            "stderr": truncate_output(sanitize_output(self.stderr)),
        }


def utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def repo_path(path: Path) -> str:
    try:
        return path.relative_to(ROOT).as_posix()
    except ValueError:
        return str(path)


def truncate_output(value: str) -> str:
    if len(value) <= MAX_OUTPUT_CHARS:
        return value
    return value[-MAX_OUTPUT_CHARS:]


def sanitize_output(value: str) -> str:
    sanitized = EMAIL_RE.sub("<email>", value)
    sanitized = IPV4_RE.sub("<ip>", sanitized)
    sanitized = USER_PATH_RE.sub("/<private-path>", sanitized)
    sanitized = SHARE_KEY_RE.sub("#key=<redacted>", sanitized)
    sanitized = SECRET_ENV_RE.sub(lambda match: match.group(0).split("=", 1)[0] + "=<redacted>", sanitized)
    sanitized = LONG_HEX_RE.sub("<hex-id>", sanitized)
    return sanitized


def sanitize_command(command: list[str]) -> list[str]:
    return [sanitize_output(part) for part in command]


def git_subject_commit() -> str:
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        return "unknown"
    return result.stdout.strip() or "unknown"


def run_step(step: EvidenceStep) -> StepResult:
    started_at = utc_now()
    print(f"apple-evidence: running {step.name}: {' '.join(sanitize_command(step.command))}")
    result = subprocess.run(step.command, cwd=ROOT, capture_output=True, text=True, check=False)
    completed_at = utc_now()
    status = STATUS_PASSED if result.returncode == 0 else STATUS_FAILED
    return StepResult(
        name=step.name,
        status=status,
        command=step.command,
        required=step.required,
        started_at=started_at,
        completed_at=completed_at,
        exit_code=result.returncode,
        stdout=result.stdout,
        stderr=result.stderr,
    )


def planned_step(step: EvidenceStep) -> StepResult:
    timestamp = utc_now()
    return StepResult(
        name=step.name,
        status=STATUS_PLANNED,
        command=step.command,
        required=step.required,
        started_at=timestamp,
        completed_at=timestamp,
        reason="dry-run",
    )


def skipped_step(name: str, reason: str, *, required: bool = False) -> StepResult:
    timestamp = utc_now()
    return StepResult(
        name=name,
        status=STATUS_SKIPPED,
        command=[],
        required=required,
        started_at=timestamp,
        completed_at=timestamp,
        reason=reason,
    )


def chat_manifest_path(artifact_dir: Path, client: str, surface: str) -> Path:
    return artifact_dir / f"{client}-{surface}-manifest.json"


def add_chat_comparator_steps(steps: list[EvidenceStep], artifact_dir: Path, *, strict_order: bool, minimum_overlap: int) -> None:
    comparisons = (
        ("loaded-chats", False),
        ("opened-chats", True),
    )
    for surface, default_strict in comparisons:
        command = [
            sys.executable,
            "scripts/compare_chat_render_parity.py",
            "--web",
            repo_path(chat_manifest_path(artifact_dir, "web", surface)),
            "--apple",
            repo_path(chat_manifest_path(artifact_dir, "apple", surface)),
            "--minimum-overlap",
            str(minimum_overlap),
        ]
        if strict_order or default_strict:
            command.append("--strict-order")
        steps.append(EvidenceStep(f"chat-rendering-compare:{surface}", command))


def build_static_steps(args: argparse.Namespace) -> list[EvidenceStep]:
    steps = [
        EvidenceStep(
            "apple-parity-inventory",
            [sys.executable, "scripts/apple_parity_audit.py", "--output", repo_path(DEFAULT_INVENTORY)],
        ),
        EvidenceStep(
            "apple-parity-inventory-check",
            [sys.executable, "scripts/apple_parity_audit.py", "--check", "--output", repo_path(DEFAULT_INVENTORY)],
        ),
    ]

    if args.surface in ("chat", "all"):
        steps.append(EvidenceStep("apple-chat-parity-audit", [sys.executable, "scripts/apple_chat_parity_audit.py"]))

    for contract_surface in SURFACE_UI_CONTRACTS[args.surface]:
        steps.append(
            EvidenceStep(
                f"apple-ui-contracts:{contract_surface}",
                [sys.executable, "scripts/apple_ui_contracts.py", "audit", "--surface", contract_surface],
            )
        )

    if args.compare_chat_rendering:
        add_chat_comparator_steps(
            steps,
            args.chat_artifact_dir,
            strict_order=args.strict_order,
            minimum_overlap=args.minimum_overlap,
        )

    return steps


def build_remote_steps(args: argparse.Namespace) -> list[EvidenceStep]:
    if args.remote == "none":
        return []

    steps = [
        EvidenceStep("apple-remote-status", [sys.executable, "scripts/apple_remote.py", "status"]),
        EvidenceStep("apple-remote-doctor", [sys.executable, "scripts/apple_remote.py", "doctor"]),
    ]
    if args.sync_repo:
        steps.append(EvidenceStep("apple-remote-sync-repo", [sys.executable, "scripts/apple_remote.py", "sync-repo", "--branch", args.branch]))

    if args.remote == "build-ios":
        steps.append(EvidenceStep("apple-remote-build-ios", [sys.executable, "scripts/apple_remote.py", "build-ios", "--simulator", args.simulator]))
    elif args.remote == "test-ios":
        command = [sys.executable, "scripts/apple_remote.py", "test-ios", "--simulator", args.simulator]
        if args.only_testing:
            command.extend(["--only-testing", args.only_testing])
        steps.append(EvidenceStep("apple-remote-test-ios", command))
    elif args.remote == "startup-ios":
        command = [
            sys.executable,
            "scripts/apple_remote.py",
            "verify-ios-startup",
            "--simulator",
            args.simulator,
            "--duration",
            str(args.duration),
        ]
        if args.fresh_install:
            command.append("--fresh-install")
        steps.append(EvidenceStep("apple-remote-verify-ios-startup", command))
    return steps


def build_steps(args: argparse.Namespace) -> list[EvidenceStep]:
    return build_static_steps(args) + build_remote_steps(args)


def write_summary(args: argparse.Namespace, results: list[StepResult]) -> Path:
    output_dir = args.output_dir if args.output_dir.is_absolute() else ROOT / args.output_dir
    output_dir.mkdir(parents=True, exist_ok=True)
    timestamp = utc_now()
    failed_required = [result for result in results if result.required and result.status == STATUS_FAILED]
    planned_required = [result for result in results if result.required and result.status == STATUS_PLANNED]
    if failed_required:
        overall_status = STATUS_FAILED
    elif planned_required:
        overall_status = STATUS_PLANNED
    else:
        overall_status = STATUS_PASSED
    summary = {
        "schema_version": 1,
        "created_at": timestamp,
        "subject_commit": git_subject_commit(),
        "surface": args.surface,
        "remote": args.remote,
        "overall_status": overall_status,
        "artifact_dir": sanitize_output(repo_path(output_dir)),
        "privacy": {
            "sanitized": True,
            "redacts": ["emails", "ips", "home_paths", "share_keys", "test_account_env", "long_hex_ids"],
        },
        "steps": [result.as_dict() for result in results],
    }
    summary_path = output_dir / f"summary-{timestamp.replace(':', '-')}.json"
    serialized = json.dumps(summary, indent=2, sort_keys=True) + "\n"
    summary_path.write_text(serialized, encoding="utf-8")
    latest_path = output_dir / "latest-summary.json"
    latest_path.write_text(serialized, encoding="utf-8")
    if output_dir == DEFAULT_EVIDENCE_DIR:
        LATEST_SUMMARY.write_text(serialized, encoding="utf-8")
    return summary_path


def run_bundle(args: argparse.Namespace) -> int:
    steps = build_steps(args)
    results: list[StepResult] = []
    if args.remote == "none":
        results.append(skipped_step("apple-remote", "remote Mac checks not requested"))

    for step in steps:
        result = planned_step(step) if args.dry_run else run_step(step)
        results.append(result)
        if result.required and result.status == STATUS_FAILED and args.stop_on_failure:
            print(f"apple-evidence: {step.name} failed; stopping before later steps", file=sys.stderr)
            break

    summary_path = write_summary(args, results)
    print(f"apple-evidence: summary {sanitize_output(str(summary_path))}")
    if any(result.required and result.status == STATUS_FAILED for result in results):
        return 1
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Build a sanitized Apple debugging/parity evidence bundle")
    parser.add_argument("--surface", choices=["chat", "settings", "embeds", "all"], default="chat")
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_EVIDENCE_DIR)
    parser.add_argument("--dry-run", action="store_true", help="Write planned commands without executing them")
    parser.add_argument("--stop-on-failure", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--remote", choices=["none", "build-ios", "test-ios", "startup-ios"], default="none")
    parser.add_argument("--sync-repo", action="store_true", help="Run apple_remote.py sync-repo before remote build/test/startup")
    parser.add_argument("--branch", default="dev")
    parser.add_argument("--simulator", default="iPhone 17")
    parser.add_argument("--only-testing", help="Xcode only-testing selector for --remote test-ios")
    parser.add_argument("--duration", type=int, default=60, help="Startup verification duration in seconds")
    parser.add_argument("--fresh-install", action="store_true", help="Use a fresh simulator app container for startup checks")
    parser.add_argument("--compare-chat-rendering", action="store_true", help="Compare existing web and Apple chat-rendering manifests")
    parser.add_argument("--chat-artifact-dir", type=Path, default=DEFAULT_CHAT_ARTIFACT_DIR)
    parser.add_argument("--strict-order", action="store_true", help="Require strict loaded-chat ordering in chat manifest comparisons")
    parser.add_argument("--minimum-overlap", type=int, default=5)
    return parser


def validate_args(parser: argparse.ArgumentParser, args: argparse.Namespace) -> None:
    if args.remote == "test-ios" and not args.only_testing:
        parser.error("--remote test-ios requires --only-testing")
    if args.only_testing and args.remote != "test-ios":
        parser.error("--only-testing is only valid with --remote test-ios")
    if args.fresh_install and args.remote != "startup-ios":
        parser.error("--fresh-install is only valid with --remote startup-ios")
    if args.duration < 5 or args.duration > 300:
        parser.error("--duration must be between 5 and 300 seconds")
    if args.minimum_overlap < 1:
        parser.error("--minimum-overlap must be at least 1")


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    validate_args(parser, args)
    return run_bundle(args)


if __name__ == "__main__":
    raise SystemExit(main())
