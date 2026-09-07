"""Bounded, cached retrieval of source-bound GitHub test artifacts.

Results are downloaded once under the coordinator's lock. ZIP paths and expanded
sizes are checked before extraction, and the dev server retains 30 GiB free.
Credentials and private setup files are never valid returned evidence paths.
See docs/plans/isolated-github-tests/plan.yml.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import selectors
import shutil
import stat
import subprocess
import tempfile
import time
import zipfile

RESERVE = 30 * 1024**3
MAX_ARCHIVE = 256 * 1024**2
MAX_EXPANDED = 512 * 1024**2
DOWNLOAD_SECONDS = 60


def download(command, root, output):
    """Drain both pipes with a wall-clock deadline and bounded retained output."""
    child = subprocess.Popen(
        command, cwd=root, stdout=subprocess.PIPE, stderr=subprocess.PIPE
    )
    try:
        with selectors.DefaultSelector() as streams:
            streams.register(child.stdout, selectors.EVENT_READ, True)
            streams.register(child.stderr, selectors.EVENT_READ, False)
            deadline = time.monotonic() + DOWNLOAD_SECONDS
            size = 0
            while streams.get_map():
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise RuntimeError("CI artifact download timed out")
                for key, _ in streams.select(remaining):
                    chunk = os.read(key.fd, 65536)
                    if not chunk:
                        streams.unregister(key.fileobj)
                    elif key.data:
                        size += len(chunk)
                        if size > MAX_ARCHIVE:
                            raise RuntimeError("CI artifact download exceeded limit")
                        output.write(chunk)
                    # Discard stderr: credentials and server response bodies are not evidence.
            if child.wait(timeout=max(0.1, deadline - time.monotonic())):
                raise RuntimeError("GitHub artifact download failed")
    finally:
        if child.poll() is None:
            child.kill()
            child.wait()
        child.stdout.close()
        child.stderr.close()


def extract(archive: Path, destination: Path):
    with zipfile.ZipFile(archive) as bundle:
        members = bundle.infolist()
        if len(members) > 10000 or sum(m.file_size for m in members) > MAX_EXPANDED:
            raise RuntimeError("CI artifact exceeds bounded extraction size")
        for member in members:
            path = Path(member.filename)
            if (
                path.is_absolute()
                or ".." in path.parts
                or stat.S_ISLNK(member.external_attr >> 16)
            ):
                raise RuntimeError("Unsafe CI artifact path")
            if (
                "ci-private" in path.parts
                or ".auth" in path.parts
                or path.name.startswith(".env")
            ):
                raise RuntimeError(
                    "Private setup state must not be returned as test evidence"
                )
        bundle.extractall(destination)


def fetch(github, job: dict, root: Path) -> dict:
    destination = root / "test-results/ci-runs" / job["id"]
    receipt = destination / "receipt.json"
    if receipt.is_file():
        return json.loads(receipt.read_text())
    if not job["run_id"] or job["state"] not in ("success", "failure", "cancelled"):
        raise RuntimeError("CI job has no terminal result yet")
    run = github.request(f"repos/{github.repo}/actions/runs/{job['run_id']}")
    runner_jobs = github.request(
        f"repos/{github.repo}/actions/runs/{job['run_id']}/jobs?per_page=100"
    )["jobs"]
    if not runner_jobs or any(
        "ubuntu-latest" not in entry.get("labels", [])
        or not entry.get("runner_name", "").startswith("GitHub Actions")
        for entry in runner_jobs
    ):
        raise RuntimeError(
            "Test evidence did not execute exclusively on GitHub-hosted runners"
        )
    artifacts = github.request(
        f"repos/{github.repo}/actions/runs/{job['run_id']}/artifacts?per_page=100"
    )["artifacts"]
    matches = [
        a
        for a in artifacts
        if a["name"] == "isolated-test-results" and not a["expired"]
    ]
    if len(matches) != 1:
        raise RuntimeError("Expected one unexpired isolated result artifact")
    artifact = matches[0]
    if (
        artifact["size_in_bytes"] > MAX_ARCHIVE
        or shutil.disk_usage(root).free < RESERVE + MAX_ARCHIVE + MAX_EXPANDED
    ):
        raise RuntimeError(
            "Artifact retrieval would exceed size limit or 30 GiB reserve"
        )
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(
        dir=destination.parent, prefix="download-"
    ) as temporary:
        archive = Path(temporary) / "artifact.zip"
        command = [
            "gh",
            "api",
            f"repos/{github.repo}/actions/artifacts/{artifact['id']}/zip",
        ]
        with archive.open("wb") as output:
            download(command, root, output)
        extracted = Path(temporary) / "results"
        extracted.mkdir()
        extract(archive, extracted)
        candidates = list(extracted.rglob("ci-results.json"))
        environment = list(extracted.rglob("ci-environment.json"))
        report = json.loads(candidates[0].read_text()) if len(candidates) == 1 else None
        environment_data = (
            json.loads(environment[0].read_text()) if len(environment) == 1 else {}
        )
        identity = report or environment_data
        if identity.get("source_commit") != job["source"] or str(
            identity.get("run_id")
        ) != str(job["run_id"]):
            raise RuntimeError("CI artifact source/run identity mismatch")
        if job["state"] == "success" and (
            not report or report.get("success") is not True or not report.get("results")
        ):
            raise RuntimeError(
                "Green GitHub job lacks passing source-bound test evidence"
            )
        if report and (
            report.get("harness_commit") != run["head_sha"]
            or report.get("proof_profile", "") != job.get("proof_profile", "")
        ):
            raise RuntimeError(
                "CI harness or requested proof profile identity mismatch"
            )
        if job["state"] == "success" and job.get("mode") == "e2e":
            if (
                environment_data.get("source_commit") != job["source"]
                or environment_data.get("frontend", {}).get("source_commit")
                != job["source"]
                or environment_data.get("shared_dev_https") != "rejected"
                or not environment_data.get("services")
            ):
                raise RuntimeError(
                    "Green E2E lacks runner-local source and egress evidence"
                )
            expected_specs = sorted(json.loads(job["specs"]))
            if (
                sorted(result.get("spec", "") for result in report["results"])
                != expected_specs
            ):
                raise RuntimeError(
                    "Result does not cover the exact requested spec inventory"
                )
        result = {
            "id": job["id"],
            "source_commit": job["source"],
            "run_id": job["run_id"],
            "state": job["state"],
            "harness_commit": run["head_sha"],
            "runner_jobs": [
                {
                    "id": entry["id"],
                    "labels": entry["labels"],
                    "runner_name": entry["runner_name"],
                }
                for entry in runner_jobs
            ],
            "report": report,
            "environment": environment_data,
            "artifact_id": artifact["id"],
            "artifact_url": f"{job['url']}/artifacts/{artifact['id']}",
            "directory": str(destination),
        }
        (extracted / "receipt.json").write_text(json.dumps(result, indent=2))
        extracted.rename(destination)
    return result
