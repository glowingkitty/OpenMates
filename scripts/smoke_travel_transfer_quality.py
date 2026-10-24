#!/usr/bin/env python3
"""Offline saved-travel contract validation; live discovery smoke is unavailable.

No runtime or SDK is contacted. Without --fixture this reports an explicit skip
before reading credentials, creating keys, approving devices or making requests.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

SECRET_LEAK_MARKERS = (
    "SECRET__GEOAPIFY",
    "apiKey",
    "api_key",
    "access_token",
    "Authorization",
)

def _extract_data(payload: dict[str, Any]) -> dict[str, Any]:
    data = payload.get("data")
    return data if isinstance(data, dict) else payload

def _result_groups(data: dict[str, Any]) -> list[dict[str, Any]]:
    groups = data.get("results")
    if not isinstance(groups, list):
        raise AssertionError(f"Travel response did not include result groups: {json.dumps(data)[:900]}")
    return [group for group in groups if isinstance(group, dict)]

def _layovers(result: dict[str, Any]) -> list[dict[str, Any]]:
    layovers: list[dict[str, Any]] = []
    for leg in result.get("legs", []) or []:
        if not isinstance(leg, dict):
            continue
        for layover in leg.get("layovers", []) or []:
            if isinstance(layover, dict):
                layovers.append(layover)
    return layovers

def validate_travel_transfer_contract(payload: dict[str, Any], min_transfer_minutes: int) -> dict[str, Any]:
    serialized = json.dumps(payload)
    leaked = [marker for marker in SECRET_LEAK_MARKERS if marker in serialized]
    if leaked:
        raise AssertionError(f"Travel response leaked forbidden provider/auth markers: {leaked}")

    data = _extract_data(payload)
    groups = _result_groups(data)
    if not groups:
        raise AssertionError("Travel response included no result groups")
    first_group = groups[0]
    results = first_group.get("results")
    if not isinstance(results, list):
        raise AssertionError(f"Travel response group missing results: {first_group!r}")
    if not results:
        reason = first_group.get("no_result_reason") or first_group.get("error")
        if not isinstance(reason, str) or not reason:
            raise AssertionError(f"Empty travel response must explain no results: {first_group!r}")
        return {
            "status": "passed",
            "mode": "empty_with_reason",
            "reason": reason,
            "provider": data.get("provider"),
            "result_count": 0,
        }

    transfer_quality_count = 0
    optimized_count = 0
    amenity_layover_count = 0
    layover_count = 0
    for raw_result in results:
        if not isinstance(raw_result, dict):
            continue
        quality = raw_result.get("transfer_quality")
        if isinstance(quality, dict):
            if quality.get("min_transfer_minutes") != min_transfer_minutes:
                raise AssertionError(f"Unexpected min transfer metadata: {quality!r}")
            transfer_quality_count += 1
        optimization = raw_result.get("optimization")
        if isinstance(optimization, dict) and optimization.get("optimized_by") == "openmates":
            if optimization.get("badge") != "Optimized by OpenMates":
                raise AssertionError(f"Optimized result missing badge: {optimization!r}")
            optimized_count += 1
        for layover in _layovers(raw_result):
            layover_count += 1
            duration = layover.get("duration_minutes")
            if isinstance(duration, int) and duration < min_transfer_minutes:
                raise AssertionError(f"Result includes too-short transfer after filtering: {layover!r}")
            amenities = layover.get("amenities")
            if isinstance(amenities, dict):
                groups_value = amenities.get("groups")
                if not isinstance(groups_value, dict):
                    raise AssertionError(f"Transfer amenities missing groups: {amenities!r}")
                for key in ("food_drink", "shops", "toilets"):
                    if key not in groups_value:
                        raise AssertionError(f"Transfer amenities missing {key}: {amenities!r}")
                amenity_layover_count += 1

    if transfer_quality_count == 0:
        raise AssertionError("Travel results did not include transfer_quality metadata")

    return {
        "status": "passed",
        "mode": "results",
        "provider": data.get("provider"),
        "result_count": len(results),
        "transfer_quality_results": transfer_quality_count,
        "layover_count": layover_count,
        "amenity_layover_count": amenity_layover_count,
        "optimized_count": optimized_count,
    }

def run_rest_smoke(args: argparse.Namespace) -> dict[str, Any]:
    fixture = getattr(args, "fixture", None)
    if fixture is None:
        return {"status": "skipped", "mode": "capability_unavailable", "surface": "rest",
                "reason": "Connection discovery has no permitted provider. Live smoke is unavailable.",
                "runtime_target": None, "network_requests": 0}
    payload = Path(fixture).read_text(encoding="utf-8")
    return {**validate_travel_transfer_contract(json.loads(payload), args.min_transfer_minutes),
            "execution": "offline_saved_fixture", "surface": "rest", "runtime_target": None,
            "network_requests": 0}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fixture", type=Path, help="Validate a saved neutral response locally; never invokes a source.")
    parser.add_argument("--min-transfer-minutes", type=int, default=10)
    parser.add_argument("--json", action="store_true", dest="json_output")
    # Accept old invocation flags without reading credentials or selecting a runtime.
    for flag in ("--api", "--api-key", "--device-id", "--scenario"):
        parser.add_argument(flag, help=argparse.SUPPRESS)
    parser.add_argument("--create-api-key-from-cli-session", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args()
    summary = run_rest_smoke(args)
    if args.json_output:
        print(json.dumps(summary, indent=2))
    else:
        print(f"Travel contract {summary['status']}: {summary.get('reason', summary['mode'])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
