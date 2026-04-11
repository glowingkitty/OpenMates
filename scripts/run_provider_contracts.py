#!/usr/bin/env python3
"""
scripts/run_provider_contracts.py

Daily contract probe runner for every reverse-engineered / scraped provider.

Why this is separate from `scripts/run_tests.py --daily`:
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
     provider failed, writes `test-results/provider-contracts-broken.json`
     which the daily meeting agenda picks up as a Top-Priority item.

Exit code: 0 = all passed/skipped, 1 = at least one provider failed.

Usage:
  python3 scripts/run_provider_contracts.py
  python3 scripts/run_provider_contracts.py --provider doctolib   # single
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import date
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

from _nightly_report import write_nightly_report  # noqa: E402

REPORT_DIR = PROJECT_ROOT / "test-results"
CONTAINER = "app-ai-worker"
CONTAINER_TESTS_PATH = "/app/backend/tests/provider_contracts"
CONTAINER_REPORT_PATH = "/tmp/provider-contracts.json"


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
