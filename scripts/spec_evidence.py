#!/usr/bin/env python3
"""
Record executable spec evidence without hand-editing YAML blocks.

The recorder updates a verification entry or a test phase evidence block with
command, run id, subject commit, status, and timestamp. It keeps the spec.yml
file as the single source of truth for implementation evidence.

Architecture: docs/contributing/guides/spec-driven-development.md
"""

from __future__ import annotations

import argparse
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml


REPO_ROOT = Path(__file__).resolve().parent.parent


def utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def current_git_sha() -> str:
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=REPO_ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(f"Could not resolve git commit: {result.stderr.strip()}")
    return result.stdout.strip()


def load_spec(path: Path) -> dict[str, Any]:
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(data, dict):
        raise RuntimeError(f"Spec must be a YAML mapping: {path}")
    return data


def evidence_payload(args: argparse.Namespace) -> dict[str, str]:
    return {
        "status": args.status,
        "command": args.command,
        "run_id": args.run_id,
        "subject_commit": args.subject_commit or current_git_sha(),
        "timestamp": args.timestamp or utc_now(),
    }


def record_verification(data: dict[str, Any], verification_id: str, payload: dict[str, str]) -> None:
    for verification in data.get("verifications") or []:
        if isinstance(verification, dict) and verification.get("id") == verification_id:
            verification["status"] = payload["status"]
            verification["evidence"] = payload
            return
    raise RuntimeError(f"Verification id not found: {verification_id}")


def record_test_phase(data: dict[str, Any], test_id: str, phase: str, payload: dict[str, str]) -> None:
    phase_key = f"{phase}_phase"
    if phase_key not in {"red_phase", "green_phase"}:
        raise RuntimeError("--phase must be red or green when --test-id is used")
    for test in data.get("tests") or []:
        if isinstance(test, dict) and test.get("id") == test_id:
            phase_data = test.setdefault(phase_key, {})
            if not isinstance(phase_data, dict):
                raise RuntimeError(f"{test_id}.{phase_key} must be a mapping")
            phase_data["evidence"] = payload
            return
    raise RuntimeError(f"Test id not found: {test_id}")


def write_spec(path: Path, data: dict[str, Any]) -> None:
    path.write_text(yaml.safe_dump(data, sort_keys=False, allow_unicode=False, width=120), encoding="utf-8")


def display_path(path: Path) -> str:
    try:
        return str(path.relative_to(REPO_ROOT))
    except ValueError:
        return str(path)


def record(args: argparse.Namespace) -> None:
    spec_path = args.spec if args.spec.is_absolute() else REPO_ROOT / args.spec
    data = load_spec(spec_path)
    payload = evidence_payload(args)
    if args.verification_id:
        record_verification(data, args.verification_id, payload)
    elif args.test_id:
        record_test_phase(data, args.test_id, args.phase, payload)
    else:
        raise RuntimeError("Provide --verification-id or --test-id")
    write_spec(spec_path, data)
    print(f"Recorded {payload['status']} evidence in {display_path(spec_path)}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Record evidence in an executable spec.yml")
    sub = parser.add_subparsers(dest="command_name", required=True)
    record_parser = sub.add_parser("record")
    record_parser.add_argument("spec", type=Path)
    record_parser.add_argument("--verification-id", default="")
    record_parser.add_argument("--test-id", default="")
    record_parser.add_argument("--phase", choices=("red", "green"), default="green")
    record_parser.add_argument("--status", required=True)
    record_parser.add_argument("--run-id", required=True)
    record_parser.add_argument("--command", required=True)
    record_parser.add_argument("--subject-commit", default="")
    record_parser.add_argument("--timestamp", default="")
    args = parser.parse_args(argv)
    try:
        if args.command_name == "record":
            record(args)
    except RuntimeError as exc:
        print(f"error: {exc}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
