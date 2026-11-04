"""Serialization and material-change helpers for dispatch state.

Observations are stored as plain JSON so queued work survives between hourly
runs even when a source does not return the item again. Material facts are the
subset of an observation whose change justifies a re-triage
(triage.no-repeat-dispatch); diffing them yields the recorded reason.
"""

from __future__ import annotations

from dataclasses import asdict
from typing import Any

from security_monitoring.models import AdvisoryItem, Asset, Observation

SEVERITY_RANK = {"unknown": 0, "low": 1, "medium": 2, "high": 3, "critical": 4}


def observation_to_record(observation: Observation) -> dict[str, Any]:
    return asdict(observation)


def observation_from_record(record: dict[str, Any]) -> Observation:
    advisory = dict(record["advisory"])
    advisory["aliases"] = tuple(advisory.get("aliases") or ())
    advisory["affected"] = tuple(advisory.get("affected") or ())
    advisory["keywords"] = tuple(advisory.get("keywords") or ())
    assets = tuple(Asset(**{**asset, "environments": tuple(asset.get("environments") or ())}) for asset in record["assets"])
    return Observation(
        identity=record["identity"],
        advisory=AdvisoryItem(**advisory),
        assets=assets,
        match_strength=record["match_strength"],
        disposition=record["disposition"],
        suppression_reason=record.get("suppression_reason"),
        material_fingerprint=record.get("material_fingerprint", ""),
    )


def material_facts(observation: Observation) -> dict[str, Any]:
    advisory = observation.advisory
    return {
        "advisory_id": advisory.advisory_id,
        "asset_identities": sorted({asset.identity for asset in observation.assets}),
        "environments": sorted({env for asset in observation.assets for env in asset.environments}),
        "severity": advisory.severity,
        "known_exploited": bool(advisory.known_exploited),
        "public_exploit": bool(advisory.public_exploit),
        "withdrawn": bool(advisory.withdrawn),
        "modified_at": advisory.modified_at,
    }


def material_change_reason(previous: dict[str, Any] | None, current: dict[str, Any]) -> str:
    """Human-readable, deterministic reason for a re-triage."""
    if not previous:
        return "new observation"
    reasons: list[str] = []
    if set(current.get("asset_identities", [])) - set(previous.get("asset_identities", [])):
        reasons.append("new affected asset version")
    if set(current.get("environments", [])) - set(previous.get("environments", [])):
        reasons.append("new affected environment")
    if SEVERITY_RANK.get(current.get("severity", "unknown"), 0) > SEVERITY_RANK.get(previous.get("severity", "unknown"), 0):
        reasons.append("severity increase")
    if current.get("known_exploited") and not previous.get("known_exploited"):
        reasons.append("first known exploitation")
    if current.get("public_exploit") and not previous.get("public_exploit"):
        reasons.append("public exploit")
    if current.get("withdrawn") and not previous.get("withdrawn"):
        reasons.append("advisory withdrawn")
    if not reasons and current.get("modified_at") != previous.get("modified_at"):
        reasons.append("changed advisory")
    return "; ".join(reasons) or "changed advisory"


def ledger_findings(observations: list[Observation]) -> list[dict[str, Any]]:
    """Structured findings for the existing security-reporting ledger (no prose, no links)."""
    findings: list[dict[str, Any]] = []
    for observation in observations:
        if observation.disposition not in {"triage", "digest_only"}:
            continue
        advisory = observation.advisory
        for asset in observation.assets:
            if asset.usage != "used":
                continue
            findings.append({
                "vuln_id": advisory.advisory_id,
                "aliases": list(advisory.aliases),
                "package": asset.name,
                "ecosystem": asset.ecosystem,
                "severity": advisory.severity,
                "current_version": asset.version or "unknown",
            })
    return findings


MATCH_RANK = {"exact_version": 0, "version_range": 1, "name_only": 2, "vendor_only": 3, "none": 4}


def triage_priority(observation: Observation) -> tuple[int, int, int, int]:
    """Sort key: known exploited, then severity, internet-facing exposure, match strength."""
    advisory = observation.advisory
    exposed = any(asset.exposure == "internet_facing" for asset in observation.assets)
    return (
        0 if advisory.known_exploited else 1,
        -SEVERITY_RANK.get(advisory.severity, 0),
        0 if exposed else 1,
        MATCH_RANK.get(observation.match_strength, 4),
    )


def is_urgent_candidate(observation: Observation) -> bool:
    advisory = observation.advisory
    return advisory.severity == "critical" or advisory.known_exploited
