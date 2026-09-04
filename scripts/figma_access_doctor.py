#!/usr/bin/env python3
"""Diagnose Figma API access without exposing credentials.

This helper probes a small set of Figma read endpoints and prints only status
codes plus rate-limit headers. It exists because Figma-referenced UI work can
fall back to cached indexes and PNG exports when deep node reads are exhausted.
Never print response bodies, tokens, or private design JSON from this script.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.parse
from dataclasses import asdict, dataclass
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

try:
    from scripts.figma_paths import resolve_control_plane_root
except ModuleNotFoundError:
    from figma_paths import resolve_control_plane_root

REPO_ROOT = Path(__file__).resolve().parents[1]
CONTROL_PLANE_ROOT = resolve_control_plane_root(REPO_ROOT)
DEFAULT_FILE_KEY = "PzgE78TVxG0eWuEeO6o8ve"
DEFAULT_NODE_ID = "4944:31418"
FIGMA_API_BASE_URL = "https://api.figma.com/v1"
TOKEN_ENV_NAME = "FIGMA_ACCESS_TOKEN"
TOKEN_FILES = (
    CONTROL_PLANE_ROOT / ".env.figma.local",
    CONTROL_PLANE_ROOT / ".env",
)
REQUEST_TIMEOUT_SECONDS = 45
RATE_LIMIT_HEADERS = (
    "retry-after",
    "x-figma-plan-tier",
    "x-figma-rate-limit-type",
    "x-figma-upgrade-link",
)


class FigmaAccessDoctorError(RuntimeError):
    """Raised for actionable, secret-safe diagnosis failures."""


@dataclass(frozen=True)
class ProbeResult:
    name: str
    endpoint: str
    status: int | None
    retry_after: str | None
    plan_tier: str | None
    rate_limit_type: str | None
    upgrade_link: str | None
    error: str | None = None


def _read_env_value(path: Path, name: str) -> str | None:
    if not path.exists():
        return None
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        if key.strip() != name:
            continue
        return value.strip().strip("'\"") or None
    return None


def load_access_token() -> str:
    token = os.environ.get(TOKEN_ENV_NAME)
    if token:
        return token
    for path in TOKEN_FILES:
        token = _read_env_value(path, TOKEN_ENV_NAME)
        if token:
            return token
    raise FigmaAccessDoctorError(
        f"Missing {TOKEN_ENV_NAME}. Add it to .env.figma.local or the process environment."
    )


def _rate_limit_header(headers: object, name: str) -> str | None:
    getter = getattr(headers, "get", None)
    if not callable(getter):
        return None
    value = getter(name) or getter(name.title())
    return str(value) if value else None


def probe_endpoint(name: str, endpoint: str, access_token: str) -> ProbeResult:
    request = Request(
        f"{FIGMA_API_BASE_URL}{endpoint}",
        headers={"X-Figma-Token": access_token},
    )
    try:
        with urlopen(request, timeout=REQUEST_TIMEOUT_SECONDS) as response:
            headers = response.headers
            status = response.status
    except HTTPError as exc:
        headers = exc.headers
        status = exc.code
    except URLError as exc:
        return ProbeResult(
            name=name,
            endpoint=endpoint,
            status=None,
            retry_after=None,
            plan_tier=None,
            rate_limit_type=None,
            upgrade_link=None,
            error=f"request_failed: {exc.reason}",
        )

    return ProbeResult(
        name=name,
        endpoint=endpoint,
        status=status,
        retry_after=_rate_limit_header(headers, "retry-after"),
        plan_tier=_rate_limit_header(headers, "x-figma-plan-tier"),
        rate_limit_type=_rate_limit_header(headers, "x-figma-rate-limit-type"),
        upgrade_link=_rate_limit_header(headers, "x-figma-upgrade-link"),
    )


def build_probe_endpoints(file_key: str, node_id: str) -> list[tuple[str, str]]:
    encoded_file = urllib.parse.quote(file_key, safe="")
    encoded_node = urllib.parse.quote(node_id, safe="")
    image_query = urllib.parse.urlencode({"ids": node_id, "format": "png", "scale": "1"})
    return [
        ("file_outline", f"/files/{encoded_file}?depth=1"),
        ("node_json", f"/files/{encoded_file}/nodes?ids={encoded_node}"),
        ("image_export", f"/images/{encoded_file}?{image_query}"),
    ]


def diagnose(file_key: str, node_id: str, access_token: str) -> list[ProbeResult]:
    return [
        probe_endpoint(name, endpoint, access_token)
        for name, endpoint in build_probe_endpoints(file_key, node_id)
    ]


def _recommendations(results: list[ProbeResult]) -> list[str]:
    recommendations: list[str] = []
    rate_limited = [result for result in results if result.status == 429]
    if not rate_limited:
        recommendations.append("All probes completed without a Figma 429 rate-limit response.")
        return recommendations

    retry_values = [result.retry_after for result in rate_limited if result.retry_after]
    if retry_values:
        recommendations.append(f"Respect Retry-After before retrying deep node inspection: {', '.join(retry_values)} seconds.")
    if any(result.plan_tier == "starter" for result in rate_limited):
        recommendations.append("The requested file is being rate-limited in a Starter plan context; move it into the paid plan/team before expecting Pro limits.")
    if any(result.rate_limit_type == "low" for result in rate_limited):
        recommendations.append("The token is treated as View/Collab; use a Dev or Full seat for higher read limits.")
    if any(result.rate_limit_type == "high" for result in rate_limited):
        recommendations.append("The token is already treated as Dev/Full, so cache/batch requests and upgrade the file plan if it is still Starter.")
    return recommendations


def _print_text(results: list[ProbeResult]) -> None:
    print("Figma access doctor")
    for result in results:
        status = result.status if result.status is not None else "error"
        retry_after = result.retry_after or "none"
        plan = result.plan_tier or "unknown"
        limit_type = result.rate_limit_type or "unknown"
        upgrade = result.upgrade_link or "none"
        error = f" error={result.error}" if result.error else ""
        print(
            f"- {result.name}: http={status} plan={plan} "
            f"limit_type={limit_type} retry_after={retry_after} upgrade={upgrade}{error}"
        )
    for recommendation in _recommendations(results):
        print(f"recommendation: {recommendation}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--file-key", default=DEFAULT_FILE_KEY)
    parser.add_argument("--node-id", default=DEFAULT_NODE_ID)
    parser.add_argument("--json", action="store_true", dest="json_output")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        results = diagnose(args.file_key, args.node_id, load_access_token())
    except FigmaAccessDoctorError as exc:
        print(f"Figma access doctor error: {exc}", file=sys.stderr)
        return 2

    if args.json_output:
        print(json.dumps({"results": [asdict(result) for result in results], "recommendations": _recommendations(results)}, indent=2))
    else:
        _print_text(results)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
