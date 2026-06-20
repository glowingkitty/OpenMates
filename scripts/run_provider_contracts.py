#!/usr/bin/env python3
"""
scripts/run_provider_contracts.py

Daily contract probe runner for every reverse-engineered / scraped provider.

Why this is separate from `scripts/tests.py run --daily`:
  * These probes need Vault secrets (Webshare proxy credentials) and a non-
    datacenter IP to avoid anti-bot 403s — both are only available inside
    `app-ai-worker`, not in the GHA pytest runner.
  * They hit real third-party endpoints, so they must never run on every PR.

What it does:
  1. `docker exec app-ai-worker pytest -m provider_contract backend/tests/provider_contracts/`
     with `--json-report` pointing at /tmp inside the container.
  2. Copies the JSON report back to
     `test-results/provider-contracts-YYYY-MM-DD.json` on the host.
  3. Collapses the report into a short per-provider summary table and, if any
     provider failed, writes `test-results/provider-contracts-broken.json`,
     writes a nightly report for the daily meeting, and dispatches one admin
     email per day for the same broken-provider set.

Exit code: 0 = all passed/skipped, 1 = at least one provider failed.

Usage:
  python3 scripts/run_provider_contracts.py
  python3 scripts/run_provider_contracts.py --provider doctolib   # single
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import urllib.request
from datetime import date
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

from _nightly_report import write_nightly_report  # noqa: E402

REPORT_DIR = PROJECT_ROOT / "test-results"
CONTAINER = "app-ai-worker"
CONTAINER_TESTS_PATH = "/app/backend/tests/provider_contracts"
CONTAINER_REPORT_PATH = "/tmp/provider-contracts.json"
EMAIL_STATE_PATH = REPORT_DIR / "provider-contracts-email-state.json"
INTERNAL_API_URL = os.getenv("INTERNAL_API_URL", "http://localhost:8000")


def _run(cmd: list[str], **kwargs) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True, **kwargs)


def _run_probes(provider: str | None) -> tuple[int, dict]:
    """Invoke pytest inside the worker and return (exit_code, report_dict)."""
    REPORT_DIR.mkdir(parents=True, exist_ok=True)

    test_path = CONTAINER_TESTS_PATH
    if provider:
        test_path = f"{CONTAINER_TESTS_PATH}/test_{provider}_contract.py"

    pytest_cmd = [
        "docker", "exec", CONTAINER,
        "python", "-m", "pytest",
        test_path,
        "-m", "provider_contract",
        "-v", "--tb=short", "--color=no",
        f"--json-report-file={CONTAINER_REPORT_PATH}",
        "--json-report",
    ]
    print(f"[provider-contracts] {' '.join(pytest_cmd)}")
    result = _run(pytest_cmd)
    print(result.stdout)
    if result.stderr:
        print(result.stderr, file=sys.stderr)

    # Pull the report out of the container.
    copy = _run([
        "docker", "cp",
        f"{CONTAINER}:{CONTAINER_REPORT_PATH}",
        str(REPORT_DIR / "provider-contracts-raw.json"),
    ])
    if copy.returncode != 0:
        print(f"[provider-contracts] docker cp failed: {copy.stderr}", file=sys.stderr)
        return result.returncode, {}

    raw = (REPORT_DIR / "provider-contracts-raw.json").read_text()
    return result.returncode, json.loads(raw)


def _summarise(report: dict) -> dict:
    """Collapse the pytest-json-report into per-provider aggregate rows."""
    per_provider: dict[str, dict] = {}
    for test in report.get("tests", []):
        node = test.get("nodeid", "")
        # Example: backend/tests/provider_contracts/test_doctolib_contract.py::test_doctolib_listing_has_window_place
        try:
            filename = node.split("::")[0].rsplit("/", 1)[-1]
        except (IndexError, ValueError):
            continue
        provider = filename.removeprefix("test_").removesuffix("_contract.py")
        row = per_provider.setdefault(
            provider,
            {"provider": provider, "passed": 0, "failed": 0, "skipped": 0, "errors": []},
        )
        outcome = test.get("outcome", "")
        if outcome == "passed":
            row["passed"] += 1
        elif outcome in ("failed", "error"):
            row["failed"] += 1
            # Errors (setup failures) carry longrepr on 'setup', failures on 'call'.
            setup = test.get("setup") or {}
            call = test.get("call") or {}
            longrepr = str(call.get("longrepr") or setup.get("longrepr") or "")[:400]
            row["errors"].append({"test": node.split("::")[-1], "error": longrepr})
        elif outcome == "skipped":
            row["skipped"] += 1

    return per_provider


def _print_table(per_provider: dict) -> None:
    print()
    print(f"{'Provider':20s}  {'Pass':>5s}  {'Fail':>5s}  {'Skip':>5s}  Status")
    print("-" * 60)
    for row in sorted(per_provider.values(), key=lambda r: r["provider"]):
        if row["failed"]:
            status = "BROKEN"
        elif row["passed"] == 0 and row["skipped"]:
            status = "STUB"
        else:
            status = "ok"
        print(
            f"{row['provider']:20s}  {row['passed']:5d}  {row['failed']:5d}  "
            f"{row['skipped']:5d}  {status}"
        )
    print()


def _load_env_value(name: str) -> str:
    value = os.getenv(name, "")
    if value:
        return value
    env_path = PROJECT_ROOT / ".env"
    if not env_path.is_file():
        return ""
    for line in env_path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or not stripped.startswith(f"{name}="):
            continue
        return stripped.split("=", 1)[1].strip().strip('"').strip("'")
    return ""


def _broken_fingerprint(broken: list[dict]) -> str:
    return ",".join(sorted(str(row.get("provider", "")) for row in broken))


def _already_notified_today(today: str, broken: list[dict]) -> bool:
    if not EMAIL_STATE_PATH.exists():
        return False
    try:
        state = json.loads(EMAIL_STATE_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    return (
        state.get("date") == today
        and state.get("broken_fingerprint") == _broken_fingerprint(broken)
    )


def _write_email_state(today: str, broken: list[dict]) -> None:
    EMAIL_STATE_PATH.write_text(
        json.dumps(
            {
                "date": today,
                "broken_fingerprint": _broken_fingerprint(broken),
            },
            indent=2,
        ),
        encoding="utf-8",
    )


def _format_broken_provider_summary(broken: list[dict]) -> str:
    lines = [
        "Provider contract probes found broken reverse-engineered providers in the last daily run.",
        "",
    ]
    for row in broken:
        provider = row.get("provider", "unknown")
        failed = row.get("failed", 0)
        lines.append(f"- {provider}: {failed} failing probe(s)")
        for error in row.get("errors", [])[:3]:
            test = error.get("test", "unknown test")
            detail = str(error.get("error", "")).replace("\n", " ")[:220]
            lines.append(f"  {test}: {detail}")
    lines.append("")
    lines.append("Artifacts: test-results/provider-contracts-broken.json and logs/nightly-reports/provider-contracts.json")
    return "\n".join(lines)


def _notify_broken_providers(today: str, broken: list[dict]) -> str:
    """Dispatch one non-fatal admin email per day for the same broken set."""
    if os.getenv("PROVIDER_CONTRACT_EMAILS_DISABLED", "").lower() in {"1", "true", "yes"}:
        return "disabled"
    if _already_notified_today(today, broken):
        return "already_notified"

    internal_token = _load_env_value("INTERNAL_API_SHARED_TOKEN")
    if not internal_token:
        print(
            "[provider-contracts] NOTE: INTERNAL_API_SHARED_TOKEN not set; "
            "skipping provider health email notification.",
            file=sys.stderr,
        )
        return "missing_token"

    payload = {
        "job_type": "provider-contracts",
        "job_name": "Provider contract health check",
        "status": "failed",
        "context_summary": _format_broken_provider_summary(broken),
        "exit_code": 1,
    }

    try:
        request = urllib.request.Request(
            f"{INTERNAL_API_URL.rstrip('/')}/internal/dispatch-cron-session-email",
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "X-Internal-Service-Token": internal_token,
            },
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=10) as response:
            response.read()
        _write_email_state(today, broken)
        print("[provider-contracts] provider health email notification dispatched")
        return "dispatched"
    except Exception as exc:
        print(
            f"[provider-contracts] WARNING: provider health email notification failed: {exc}",
            file=sys.stderr,
        )
        return "error"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--provider",
        help="Run a single provider's contract test (e.g. 'doctolib')",
        default=None,
    )
    args = parser.parse_args()

    exit_code, report = _run_probes(args.provider)
    if not report:
        return exit_code or 1

    per_provider = _summarise(report)
    _print_table(per_provider)

    today = date.today().isoformat()
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    (REPORT_DIR / f"provider-contracts-{today}.json").write_text(
        json.dumps(
            {
                "date": today,
                "providers": list(per_provider.values()),
                "summary": report.get("summary", {}),
            },
            indent=2,
        )
    )

    broken = [r for r in per_provider.values() if r["failed"]]
    stubs = [r for r in per_provider.values() if not r["failed"] and r["passed"] == 0 and r["skipped"]]
    passing = [r for r in per_provider.values() if r["passed"] and not r["failed"]]
    broken_path = REPORT_DIR / "provider-contracts-broken.json"

    # Surface the result in the daily meeting agenda via logs/nightly-reports/.
    if broken:
        names = ", ".join(r["provider"] for r in broken)
        write_nightly_report(
            job="provider-contracts",
            status="error",
            summary=(
                f"{len(broken)} reverse-engineered provider(s) BROKEN: {names}. "
                f"{len(passing)} passing, {len(stubs)} TODO stubs."
            ),
            details={"broken": broken, "passing": [r["provider"] for r in passing], "stubs": [r["provider"] for r in stubs]},
        )
        broken_path.write_text(
            json.dumps({"date": today, "broken": broken}, indent=2)
        )
        print(
            f"[provider-contracts] {len(broken)} provider(s) BROKEN — "
            f"see {broken_path.relative_to(PROJECT_ROOT)}"
        )
        _notify_broken_providers(today, broken)
        return 1

    if broken_path.exists():
        broken_path.unlink()
    write_nightly_report(
        job="provider-contracts",
        status="ok" if passing else "warning",
        summary=(
            f"{len(passing)} reverse-engineered provider(s) passing contract probes; "
            f"{len(stubs)} TODO stubs waiting for implementation."
        ),
        details={"passing": [r["provider"] for r in passing], "stubs": [r["provider"] for r in stubs]},
    )
    print("[provider-contracts] all passing")
    return 0


if __name__ == "__main__":
    sys.exit(main())
