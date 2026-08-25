#!/usr/bin/env python3
"""Verify dev API and text-AI continuity during an object-storage outage.

The verifier uses the public dev health endpoint, the runtime verifier inside
the real API container, and the authenticated packaged CLI quick test. It
expects object storage to be unavailable without making required core checks
fail and emits only bounded, sanitized evidence.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from typing import Any
from urllib.request import urlopen


def _subject_commit() -> str:
    return subprocess.run(
        ["git", "rev-parse", "origin/dev"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def _public_health(api_url: str) -> dict[str, Any]:
    with urlopen(f"{api_url.rstrip('/')}/v1/health", timeout=15) as response:  # noqa: S310
        if response.status != 200:
            raise RuntimeError("public_health_not_200")
        payload = json.load(response)
    if payload.get("status") not in {"healthy", "degraded"}:
        raise RuntimeError("public_health_not_available")
    return {"http_status": 200, "status": payload.get("status")}


def _runtime_health() -> dict[str, Any]:
    completed = subprocess.run(
        [
            "docker",
            "exec",
            "api",
            "python",
            "-m",
            "backend.scripts.runtime_health_verifier",
            "--role",
            "core",
            "--json",
        ],
        check=False,
        capture_output=True,
        text=True,
        timeout=75,
    )
    try:
        payload = json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError("runtime_verifier_invalid_json") from exc
    checks = {check.get("id"): check for check in payload.get("checks", [])}
    storage = checks.get("core.object_storage") or {}
    chat = checks.get("core.chat_plumbing") or {}
    required_passed = payload.get("status") == "passed" and all(
        check.get("status") == "passed"
        for check in payload.get("checks", [])
        if check.get("required") is True
    )
    if not required_passed or completed.returncode != 0:
        raise RuntimeError("required_runtime_checks_failed")
    if storage.get("required") is not False or storage.get("status") != "failed" or storage.get("failure_class") != "storage_unavailable":
        raise RuntimeError("object_storage_outage_not_observed")
    if chat.get("status") != "passed":
        raise RuntimeError("chat_plumbing_failed")
    return {
        "status": payload.get("status"),
        "object_storage": {
            "status": storage.get("status"),
            "required": storage.get("required"),
            "failure_class": storage.get("failure_class"),
        },
        "chat_plumbing": {"status": chat.get("status")},
    }


def _parse_cli_json(stdout: str) -> dict[str, Any]:
    decoder = json.JSONDecoder()
    for index, character in enumerate(stdout):
        if character != "{":
            continue
        try:
            value, _ = decoder.raw_decode(stdout[index:])
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            return value
    raise RuntimeError("quick_test_invalid_json")


def _text_ai_quick_test(api_url: str, install_path: str) -> dict[str, Any]:
    completed = subprocess.run(
        [
            "openmates",
            "server",
            "test",
            "--quick",
            "--confirm-spend-credits",
            "--json",
            "--path",
            install_path,
            "--api-url",
            api_url,
        ],
        check=False,
        capture_output=True,
        text=True,
        timeout=180,
    )
    payload = _parse_cli_json(completed.stdout)
    quick_test = payload.get("quickTest") or {}
    checks = [
        {"id": check.get("id"), "status": check.get("status")}
        for check in quick_test.get("checks", [])
    ]
    if completed.returncode != 0 or quick_test.get("status") != "passed":
        raise RuntimeError("authenticated_text_ai_quick_test_failed")
    return {"status": "passed", "checks": checks}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--api-url", default="https://api.dev.openmates.org")
    parser.add_argument("--path", default=".")
    parser.add_argument("--skip-text-ai", action="store_true")
    args = parser.parse_args()

    evidence: dict[str, Any] = {"subject_commit": _subject_commit()}
    try:
        evidence["public_health"] = _public_health(args.api_url)
        evidence["runtime_health"] = _runtime_health()
        evidence["text_ai"] = (
            {"status": "skipped", "reason": "explicitly_skipped"}
            if args.skip_text_ai
            else _text_ai_quick_test(args.api_url, args.path)
        )
    except Exception as exc:
        evidence.update({"status": "failed", "failure_class": str(exc)})
        print(json.dumps(evidence, separators=(",", ":")))
        return 1
    evidence["status"] = "passed"
    print(json.dumps(evidence, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    sys.exit(main())
