"""Bind dedicated capacity runs to successful, exact-source CI calibration."""

from __future__ import annotations

import io
import json
import os
from pathlib import Path, PurePosixPath
import re
import subprocess
import urllib.request
import urllib.parse
import zipfile

TARGET_SPEC = "storage-capacity-target.spec.ts"
CALIBRATION_SPEC = "storage-capacity-calibration.spec.ts"
MAX_ARCHIVE_BYTES = 2 * 1024**2
CALIBRATION_FILES = {
    "ci-capacity-calibration-private/receipt.json": "capacity-target-calibration.json",
    "ci-storage-capacity.json": "capacity-target-pilot-report.json",
    "ci-environment.json": "capacity-target-ci-environment.json",
}


class ArtifactRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, message, headers, url):
        parsed = urllib.parse.urlsplit(url)
        if parsed.scheme != "https" or parsed.username or parsed.password:
            raise RuntimeError("Unsafe capacity calibration artifact redirect")
        redirected = super().redirect_request(request, fp, code, message, headers, url)
        if redirected is not None:
            redirected.remove_header("Authorization")
        return redirected


def validate_configuration(value: dict, *, source: str, target: bool) -> dict:
    if (not isinstance(value, dict) or set(value) != {
            "source", "profile", "duration_seconds", "timeout_seconds", "calibration_run_id"}
            or value.get("source") != source or not re.fullmatch(r"[a-f0-9]{40}", source)
            or value.get("profile") not in {"accelerated", "burst", "sustained"}
            or type(value.get("duration_seconds")) is not int
            or not 1 <= value["duration_seconds"] <= 86400
            or type(value.get("timeout_seconds")) is not int
            or not 600 <= value["timeout_seconds"] <= 48 * 3600
            or type(value.get("calibration_run_id")) is not int
            or value["calibration_run_id"] < (1 if target else 0)):
        raise ValueError("Invalid source-bound capacity configuration")
    if not target and value["calibration_run_id"] != 0:
        raise ValueError("Pilot capacity configuration cannot borrow calibration admission")
    if value["profile"] == "sustained" and value["timeout_seconds"] < value["duration_seconds"] + 600:
        raise ValueError("Paced capacity timeout must include declared duration and cleanup")
    return value


def configuration_for_submission(queue, *, source: str, specs: list[str], mode: str,
                                 calibration_job: str, profile: str,
                                 duration_seconds: int, timeout_seconds: int) -> dict:
    if mode != "e2e" or len(specs) != 1 or specs[0] not in {
            TARGET_SPEC, CALIBRATION_SPEC, "storage-capacity-replay.spec.ts"}:
        raise ValueError("Capacity configuration requires one dedicated capacity E2E spec")
    target = specs == [TARGET_SPEC]
    run_id = 0
    if target:
        rows = queue.status(calibration_job)
        if (len(rows) != 1 or rows[0].get("state") != "success"
                or rows[0].get("source") != source or rows[0].get("mode") != "e2e"
                or json.loads(rows[0].get("specs", "[]")) != [CALIBRATION_SPEC]
                or type(rows[0].get("run_id")) is not int or rows[0]["run_id"] <= 0):
            raise ValueError("Target capacity requires a successful same-source calibration job")
        run_id = rows[0]["run_id"]
    elif calibration_job:
        raise ValueError("Pilot capacity cannot use a target calibration job")
    return validate_configuration({
        "source": source, "profile": profile, "duration_seconds": duration_seconds,
        "timeout_seconds": timeout_seconds, "calibration_run_id": run_id,
    }, source=source, target=target)


def calibration_bytes(archive: bytes) -> dict[str, bytes]:
    """Select only bounded calibration evidence; never extract private failures."""
    if len(archive) > MAX_ARCHIVE_BYTES:
        raise RuntimeError("Capacity calibration artifact exceeds download limit")
    found = {}
    with zipfile.ZipFile(io.BytesIO(archive)) as bundle:
        if len(bundle.infolist()) > 20:
            raise RuntimeError("Capacity calibration artifact has too many members")
        for member in bundle.infolist():
            path = PurePosixPath(member.filename)
            if path.is_absolute() or ".." in path.parts or (member.external_attr >> 16) & 0o170000 == 0o120000:
                raise RuntimeError("Unsafe capacity calibration artifact path")
            for suffix, destination in CALIBRATION_FILES.items():
                if member.filename == suffix or member.filename.endswith("/" + suffix):
                    if destination in found or member.file_size > 1_000_000:
                        raise RuntimeError("Capacity calibration evidence is duplicate or oversized")
                    content = bundle.read(member)
                    if not isinstance(json.loads(content), dict):
                        raise RuntimeError("Capacity calibration evidence must contain JSON objects")
                    found[destination] = content
    if set(found) != set(CALIBRATION_FILES.values()):
        raise RuntimeError("Capacity calibration artifact lacks required evidence")
    return found


def stage_configuration() -> None:
    event = json.loads(Path(os.environ["GITHUB_EVENT_PATH"]).read_text())
    inputs = event.get("inputs", {})
    encoded = inputs.get("capacity_configuration", "")
    if not encoded:
        if json.loads(inputs.get("specs_json", "[]")) == [TARGET_SPEC]:
            raise RuntimeError("Full target has no coordinator calibration configuration")
        return
    if len(encoded) > 32768:
        raise RuntimeError("Capacity configuration exceeds limit")
    source = subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()
    target = json.loads(inputs.get("specs_json", "[]")) == [TARGET_SPEC]
    value = validate_configuration(json.loads(encoded), source=source, target=target)
    if target:
        if os.environ.get("RUNNER_ENVIRONMENT") != "self-hosted":
            raise RuntimeError("Full capacity target requires its dedicated runner")
        repo = os.environ["GITHUB_REPOSITORY"]
        if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repo):
            raise RuntimeError("Invalid capacity repository identity")
        headers = {"Authorization": "Bearer " + os.environ["GH_TOKEN"],
                   "Accept": "application/vnd.github+json"}
        opener = urllib.request.build_opener(ArtifactRedirect())
        def read(endpoint, limit):
            # Never forward the repository token to the signed artifact host.
            request = urllib.request.Request("https://api.github.com/" + endpoint, headers=headers)
            with opener.open(request, timeout=60) as response:
                raw = response.read(limit + 1)
            if len(raw) > limit:
                raise RuntimeError("Capacity calibration response exceeds limit")
            return raw
        prefix = f"repos/{repo}/actions/runs/{value['calibration_run_id']}"
        run = json.loads(read(prefix, 1_000_000))
        if (run.get("conclusion") != "success" or run.get("event") != "workflow_dispatch"
                or run.get("path") != ".github/workflows/isolated-tests.yml"):
            raise RuntimeError("Capacity calibration run is not successful isolated CI")
        artifacts = json.loads(read(prefix + "/artifacts?per_page=100", 1_000_000))["artifacts"]
        matches = [item for item in artifacts if item.get("name") == "isolated-storage-private-diagnostics"
                   and not item.get("expired")]
        if len(matches) != 1 or matches[0].get("size_in_bytes", MAX_ARCHIVE_BYTES + 1) > MAX_ARCHIVE_BYTES:
            raise RuntimeError("Capacity calibration requires one bounded private artifact")
        files = calibration_bytes(read(f"repos/{repo}/actions/artifacts/{matches[0]['id']}/zip", MAX_ARCHIVE_BYTES))
        private = Path("test-results/ci-private")
        private.mkdir(parents=True, mode=0o700, exist_ok=True)
        for name, content in files.items():
            descriptor = os.open(private / name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
            with os.fdopen(descriptor, "wb") as output:
                output.write(content)
    values = {
        "CI_STORAGE_CAPACITY_PROFILE": value["profile"],
        "CI_STORAGE_CAPACITY_DURATION_SECONDS": value["duration_seconds"],
        "CI_STORAGE_CAPACITY_JOB_TIMEOUT_SECONDS": value["timeout_seconds"],
        "CI_STORAGE_CAPACITY_CALIBRATION_RUN_ID": value["calibration_run_id"],
        "OPENMATES_CI_CAPACITY_DEDICATED": "1" if target else "0",
    }
    with Path(os.environ["GITHUB_ENV"]).open("a") as output:
        for name, item in values.items():
            output.write(f"{name}={item}\n")


if __name__ == "__main__":
    stage_configuration()
