#!/usr/bin/env python3
"""Read proof recordings from canonical, already-fetched isolated CI receipts.

This adapter does not dispatch jobs or manufacture shared-dev attestations.
It checks the receipt against the extracted runner reports, binds original
recordings and timeline bytes, and leaves rendering and visual review to the
existing proof workflow. Historical artifact caches remain untouched.
"""
from __future__ import annotations

import base64
import hashlib
import json
from pathlib import Path
from typing import Any


class CIProofError(RuntimeError):
    """A fetched receipt cannot supply trustworthy proof input."""


def _read(path: Path) -> Any:
    return json.loads(path.read_text())


def _hash(path: Path) -> str:
    with path.open("rb") as handle:
        return hashlib.file_digest(handle, "sha256").hexdigest()


def _results(value: Any):
    if isinstance(value, dict):
        if "attachments" in value:
            yield value
        for child in value.values():
            yield from _results(child)
    elif isinstance(value, list):
        for child in value:
            yield from _results(child)


def receipt_sources(receipt_path: Path) -> list[dict[str, Any]]:
    """Validate a canonical CI extraction before exposing any proof recording."""
    root = receipt_path.parent.resolve()
    receipt = _read(receipt_path)
    report = _read(root / "test-results/ci-results.json")
    environment = _read(root / "test-results/ci-environment.json")
    source = receipt.get("source_commit")
    run_id = str(receipt.get("run_id", ""))
    harness = receipt.get("harness_commit")
    if receipt.get("state") != "success":
        return []
    if report != receipt.get("report") or environment != receipt.get("environment"):
        raise CIProofError("CI receipt differs from its extracted source reports")
    if not all(isinstance(v, str) and len(v) == 40 for v in (source, harness)):
        raise CIProofError("CI receipt lacks full source/harness identities")
    for identity in (report, environment):
        if (identity.get("source_commit") != source or str(identity.get("run_id")) != run_id
                or identity.get("harness_commit") != harness):
            raise CIProofError("CI source/run/harness identity mismatch")
    jobs = receipt.get("runner_jobs", [])
    if not jobs or any("ubuntu-latest" not in j.get("labels", [])
                       or not j.get("runner_name", "").startswith("GitHub Actions") for j in jobs):
        raise CIProofError("Proof requires exclusively GitHub-hosted runners")
    if (report.get("success") is not True or environment.get("runner_environment") != "github-hosted"
            or environment.get("shared_dev_https") != "rejected"
            or environment.get("frontend", {}).get("source_commit") != source):
        raise CIProofError("CI proof lacks successful isolated frontend evidence")
    profile = report.get("proof_profile")
    if profile not in ("web-phone", "web-laptop"):
        return []
    records = []
    for index, spec in enumerate(report.get("results", [])):
        stats = spec.get("stats", {})
        if (spec.get("exit_code") != 0 or spec.get("coverage_complete") is not True
                or not stats.get("expected") or any(stats.get(k, 0) for k in ("skipped", "unexpected", "flaky"))):
            raise CIProofError("CI proof requires complete passing, unskipped spec coverage")
        report_path = root / f"test-results/ci-spec-{index}.json"
        for result_index, result in enumerate(_results(_read(report_path))):
            attachments = result.get("attachments", [])
            timelines = [a for a in attachments if a.get("name") == "openmates-proof-timeline"]
            if not timelines:
                continue
            videos = [a for a in attachments if a.get("name") == "video"]
            if result.get("status") != "passed" or len(timelines) != 1 or len(videos) != 1:
                raise CIProofError("Proof timeline must belong to one passing recorded test")
            timeline_bytes = base64.b64decode(timelines[0].get("body", ""), validate=True)
            timeline = json.loads(timeline_bytes)
            if timeline.get("device") != profile:
                raise CIProofError("Proof timeline disagrees with requested runner profile")
            assertions = timeline.get("assertion_results", [])
            if not assertions or any(a.get("status") != "passed" for a in assertions):
                raise CIProofError("Proof timeline contains incomplete assertions")
            video_parts = str(videos[0].get("path", "")).split("/subject/", 1)
            if len(video_parts) != 2:
                raise CIProofError("Recording lacks canonical runner subject path")
            video = (root / video_parts[1]).resolve()
            if not video.is_relative_to(root) or not video.is_file():
                raise CIProofError("Recording is missing or escapes extracted CI artifact")
            cache = root / "proof-source-bindings" / f"{index}-{result_index}"
            identity = {"receipt_sha256": _hash(receipt_path), "report_sha256": _hash(report_path),
                        "artifact_sha256": _hash(video), "timeline_sha256": hashlib.sha256(timeline_bytes).hexdigest()}
            binding = cache / "binding.json"
            if binding.exists() and _read(binding) != identity:
                raise CIProofError("Previously bound CI proof input has changed")
            cache.mkdir(parents=True, exist_ok=True)
            timeline_path = cache / "timeline.json"
            if not binding.exists():
                timeline_path.write_bytes(timeline_bytes)
                binding.write_text(json.dumps(identity, sort_keys=True) + "\n")
            if not timeline_path.is_file() or _hash(timeline_path) != identity["timeline_sha256"]:
                raise CIProofError("Bound timeline hash changed")
            records.append({"run_id": f"{run_id}:{index}-{result_index}", "source_run_id": run_id,
                            "git_sha": source, "spec": spec["spec"], "status": "passed",
                            "source": "github_isolated", "isolation_verified": True,
                            "deployment_reference": source, "target": "github-isolated",
                            "artifact_path": str(video), "artifact_sha256": "sha256:" + identity["artifact_sha256"],
                            "proof_timeline_path": str(timeline_path), "proof_timeline_sha256": "sha256:" + identity["timeline_sha256"],
                            "proof_video_profile": profile, "ci_receipt_path": str(receipt_path),
                            "ci_receipt_sha256": identity["receipt_sha256"]})
    return records
