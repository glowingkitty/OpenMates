"""Adapters and activation boundary for the dev-host production monitoring jobs."""

from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "deployment/status_server/agent"))
from status_agent.uptime import Observation, Outcome, Store  # noqa: E402 - shared with status image

SERVICES = {
    "reachability": "Production web reachability",
    "guest-chat": "Production guest API chat",
    "guest-web-send": "Production signed-out web chat",
    "paid-chat": "Production signed-in chat",
    "app-skill-web-search": "Production web search",
}
CHECKER_ERRORS = (
    "browser has been closed", "browser closed", "failed to launch", "executable doesn't exist",
    "host system is missing dependencies", "cannot find module", "err_module_not_found",
    "openmates_api_key is required", "api key required", "invalid api key",
    "returned empty output", "did not return json", "no such file or directory", "no tests found",
)


def enabled() -> bool:
    """Only the explicitly configured host can replace production notifications."""
    return os.getenv("OPENMATES_PROD_UPTIME_ENABLED") == "1"


def store_for(root: Path) -> Store:
    return Store(root / "logs" / "uptime" / "incidents.sqlite3")


def smoke_outcome(result: dict) -> Outcome:
    """Only executed product tests with structured results are service evidence."""
    if result.get("status") == "checker_error" or not result.get("executed"):
        return "checker"
    if any(error in result.get("error", "").lower() for error in CHECKER_ERRORS):
        return "checker"
    return "up" if result.get("status") == "passed" else "down"


def smoke_observations(results: list[dict], specs: list[tuple[str, str, str]],
                       checker_error: str, at: float) -> list[Observation]:
    by_key = {result.get("key"): result for result in results}
    observations = []
    for key, label, _ in specs:
        result = by_key.get(key, {})
        outcome = smoke_outcome(result)
        error = result.get("error") or (checker_error if outcome == "checker" else "")
        error = re.sub(r"(?i)(?:sk-api-|https://discord(?:app)?\.com/api/webhooks/)\S+", "[redacted]", error)
        observations.append(Observation(SERVICES.get(key, label), key, at, outcome, error, max_gap=3600))
    return observations


def parse_smoke_artifact(
    art_path: Path,
    specs: list[tuple[str, str, str]],
) -> list[dict]:
    """Parse per-spec results from a downloaded prod-smoke artifact.

    Returns one dict per spec in the order they ran:
        {"name": <human label>, "status": "passed"|"failed",
         "error": <error snippet or empty>, "passed": int, "failed": int}

    Empty/missing/unparseable JSON files mean playwright crashed before
    producing any test output (e.g. config load error) — treated as
    `failed` with an empty error so the caller falls back to the job-level
    log snippet for the actual cause.

    Returns an empty list when the artifact is missing entirely so the
    caller can fall back to the conclusion-based single-test path.
    """
    if not art_path or not art_path.is_dir():
        return []

    # The JSON files live under one of these locations depending on how the
    # artifact was unpacked. GitHub flattens uploaded directory contents in
    # some cases, so the artifact root itself is a valid candidate.
    candidates = [
        art_path,
        art_path / "test-results",
        art_path / f"prod-smoke-results-{art_path.name}" / "test-results",
    ]
    candidate_dirs = [c for c in candidates if c.is_dir()]
    if not candidate_dirs:
        return []

    out: list[dict] = []
    for spec_key, spec_label, spec_filename in specs:
        json_path = next(
            (candidate / f"{spec_key}.json" for candidate in candidate_dirs if (candidate / f"{spec_key}.json").is_file()),
            candidate_dirs[0] / f"{spec_key}.json",
        )
        if not json_path.is_file() or json_path.stat().st_size == 0:
            out.append({
                "key": spec_key,
                "filename": spec_filename,
                "name": spec_label,
                "status": "failed",
                "error": "",  # caller will substitute the job log snippet
                "passed": 0,
                "failed": 1,
            })
            continue

        # The file may have non-JSON prefix from the `list` reporter — find
        # the first `{` and try to parse from there.
        try:
            raw = json_path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            out.append({
                "name": spec_label, "status": "failed",
                "error": "", "passed": 0, "failed": 1,
            })
            continue

        data = None
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            brace = raw.find("{")
            if brace >= 0:
                try:
                    data = json.loads(raw[brace:])
                except json.JSONDecodeError:
                    data = None

        if not isinstance(data, dict):
            out.append({
                "key": spec_key,
                "filename": spec_filename,
                "name": spec_label, "status": "failed",
                "error": (raw.strip().splitlines()[-1][:300] if raw.strip() else ""),
                "passed": 0, "failed": 1,
            })
            continue

        # CLI verifier JSON: {status, scenarios: {name: {status, error?}}}
        if "scenarios" in data and data.get("status") in {"passed", "failed"}:
            scenarios = data.get("scenarios") if isinstance(data.get("scenarios"), dict) else {}
            failed_scenarios = [
                (name, value)
                for name, value in scenarios.items()
                if isinstance(value, dict) and value.get("status") != "passed"
            ]
            first_error = ""
            if failed_scenarios:
                scenario_name, scenario_data = failed_scenarios[0]
                first_error = str(scenario_data.get("error") or f"{scenario_name} failed")
            passed_count = sum(
                1
                for value in scenarios.values()
                if isinstance(value, dict) and value.get("status") == "passed"
            )
            failed_count = len(failed_scenarios)
            out.append({
                "key": spec_key,
                "filename": spec_filename,
                "name": spec_label,
                "status": "passed" if data.get("status") == "passed" else "failed",
                "executed": any(
                    isinstance(entry, dict) and bool(entry.get("duration_seconds"))
                    for entry in scenarios.values()
                ),
                "error": first_error,
                "passed": passed_count,
                "failed": failed_count,
            })
            continue

        # Playwright JSON: stats.expected = passed, stats.unexpected = failed
        stats = data.get("stats", {}) or {}
        expected = int(stats.get("expected", 0) or 0)
        unexpected = int(stats.get("unexpected", 0) or 0)

        # Pull the first failure message if available.
        first_error = ""

        def all_suites(suites):
            for nested in suites:
                yield nested
                yield from all_suites(nested.get("suites") or [])

        executed = False
        for suite in all_suites(data.get("suites") or []):
            for spec in suite.get("specs") or []:
                for test in spec.get("tests") or []:
                    for result in test.get("results") or []:
                        if result.get("status") not in {"passed", "failed", "timedOut"}:
                            continue
                        executed |= (result.get("duration") or 0) > 0
                        if not first_error and result.get("status") != "passed":
                            first_error = (result.get("error") or {}).get("message", "").strip()

        status = "passed" if unexpected == 0 and expected > 0 else "failed"
        out.append({
            "key": spec_key,
            "filename": spec_filename,
            "name": spec_label,
            "status": status,
            "executed": executed,
            "error": first_error,
            "passed": expected,
            "failed": unexpected,
        })

    return out
