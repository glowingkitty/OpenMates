"""Bounded, cached retrieval of source-bound GitHub test artifacts.

Results are downloaded once under the coordinator's lock. ZIP paths and expanded
sizes are checked before extraction, and the dev server retains 30 GiB free.
Credentials and private setup files are never valid returned evidence paths.
See docs/plans/isolated-github-tests/plan.yml.
"""

from __future__ import annotations

import json
import hashlib
import math
from datetime import datetime
import os
import re
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


def green_e2e_source_and_egress_verified(
    environment: dict, job: dict, *, expected_harness_commit: str | None = None,
) -> bool:
    """Require the exact source runtime for browser or supported API-only E2E."""
    if (environment.get("source_commit") != job["source"]
            or environment.get("shared_dev_https") != "rejected"
            or (job.get("mode") != "component" and not environment.get("services"))):
        return False
    selected = sorted(json.loads(job["specs"]))
    if (job.get("mode") == "e2e"
            and selected == ["storage-accountability-integration.spec.ts"]):
        services = environment["services"]
        expected = {"api", "core-worker", "cms", "cms-database", "cache", "vault"}
        if (environment.get("frontend") is not None
                or environment.get("shared_dev_dns") != "rejected"
                or set(services) != expected
                or any(service.get("running") is not True for service in services.values())):
            return False
        for name in ("api", "core-worker"):
            source = services[name].get("backend_source")
            if not isinstance(source, str) or Path(source).parts[-2:] != ("subject", "backend"):
                return False
        return True
    if job.get("mode") == "e2e" and selected in (
        ["storage-team-portability.spec.ts"], ["storage-archive-lifecycle.spec.ts"],
    ):
        services = environment["services"]
        expected = {"api", "core-worker", "cms", "cms-database", "cache", "vault",
                    "ai-worker", "runner-gateway", "object-storage"}
        harness = expected_harness_commit or job.get("preparation_harness_commit")
        if (environment.get("frontend") is not None
                or environment.get("shared_dev_dns") != "rejected"
                or environment.get("runner_environment") != "github-hosted"
                or job.get("run_id") is None or environment.get("run_id") is None
                or str(environment["run_id"]) != str(job["run_id"])
                or not harness or environment.get("harness_commit") != harness
                or not isinstance(services, dict) or set(services) != expected
                or any(not isinstance(service, dict) or service.get("running") is not True
                       for service in services.values())):
            return False
        mounts = [services[name].get("backend_source") for name in ("api", "core-worker", "ai-worker")]
        if (any(not isinstance(source, str) or not Path(source).is_absolute()
                or Path(source).parts[-2:] != ("subject", "backend") for source in mounts)
                or len(set(mounts)) != 1):
            return False
        capacity = environment.get("storage_capacity")
        isolation = environment.get("storage_isolation_proof")
        storage = environment.get("object_storage")
        if not all(isinstance(proof, dict) for proof in (capacity, isolation, storage)):
            return False
        slots = capacity.get("worker_slots")
        return (environment.get("provider_egress") == "rejected-internal-network"
                and capacity.get("provider_credentials") == "absent"
                and capacity.get("provider_network") == "internal"
                and capacity.get("fixture_mode") == "replay-only"
                and type(slots) is int and 1 <= slots <= 4
                and type(capacity.get("worker_replicas")) is int and capacity["worker_replicas"] == 1
                and isolation.get("source_bound") is True
                and isolation.get("read_only_bind") is True
                and isolation.get("vault_provider_namespace") == "disposable_only"
                and storage.get("endpoint") == "http://storage.ci.test:9000"
                and storage.get("provider") == "SeaweedFS"
                and storage.get("protocol_probe") == "authenticated-roundtrip-cors-presigned-and-private-access-passed")
    return (environment.get("frontend", {}).get("source_commit") == job["source"]
            and (job.get("mode") == "component" or bool(environment["services"])))


def timings(job: dict, runner_jobs: list[dict]) -> dict:
    """Record measured phases; missing timestamps stay unknown, never zero."""
    def timestamp(value):
        if not value:
            return None
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()
        except (TypeError, ValueError):
            return None

    phases = []
    starts, ends = [], []
    for runner in runner_jobs:
        start, end = timestamp(runner.get("started_at")), timestamp(runner.get("completed_at"))
        if start is not None:
            starts.append(start)
        if end is not None:
            ends.append(end)
        for step in runner.get("steps", []):
            start, end = timestamp(step.get("started_at")), timestamp(step.get("completed_at"))
            if start is not None and end is not None:
                phases.append({"job_id": runner["id"], "name": step["name"], "conclusion": step.get("conclusion"), "seconds": round(max(0, end - start), 3)})
    result = {"steps": phases}
    if starts and ends:
        result["github_job_wall_seconds"] = round(max(ends) - min(starts), 3)
    created, sent = job.get("created"), job.get("sent")
    if created is not None and sent is not None:
        ready = job.get("ready_at") or created
        result["coordinator_admission_seconds"] = round(max(0, sent - ready), 3)
        result["preparation_wait_seconds"] = round(max(0, ready - created), 3)
        if starts:
            result["dispatch_to_job_start_seconds"] = round(max(0, min(starts) - sent), 3)
        if ends:
            result["request_to_github_completion_seconds"] = round(max(0, max(ends) - created), 3)
    return result


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


def valid_backend_probe_receipt(report: dict, environment: dict, job: dict,
                                *, expected_harness_commit: str) -> bool:
    """Admit only isolated diagnostic health; this is never recovery E2E proof."""
    if not isinstance(report, dict) or not isinstance(environment, dict):
        return False
    results = report.get("results")
    services = environment.get("services")
    required = {"api", "ai-worker", "core-worker", "runner-gateway", "cms",
                "cms-database", "cache", "vault"}
    return (report.get("runtime_profile") == "backend-probe"
            and report.get("diagnostic_only") is True
            and report.get("recovery_e2e_verified") is False
            and report.get("latency_acceptance_verified") is False
            and isinstance(results, list) and len(results) == 1
            and isinstance(results[0], dict)
            and results[0].get("spec") == "backend-worker-broker-probe"
            and results[0].get("exit_code") == 0
            and results[0].get("status") == "passed"
            and environment.get("source_commit") == job["source"]
            and str(environment.get("run_id")) == str(job["run_id"])
            and environment.get("harness_commit") == expected_harness_commit
            and environment.get("runner_environment") == "github-hosted"
            and environment.get("shared_dev_dns") == "rejected"
            and environment.get("shared_dev_https") == "rejected"
            and environment.get("provider_egress") == "rejected-internal-network"
            and environment.get("frontend") is None
            and isinstance(services, dict) and required.issubset(services)
            and all(isinstance(services[name], dict)
                    and services[name].get("running") is True for name in required))



def valid_sdk_lockfiles_receipt(report, receipt, job, harness, *, expected_inputs, expected_tree, outputs):
    """Independently bind the preparation outputs; never credit conformance."""
    try:
        from scripts.ci_sdk_lockfiles import LOCKS, ORIGINAL_LOCKS, STAGES, commands, lock_metadata
    except ModuleNotFoundError:
        from ci_sdk_lockfiles import LOCKS, ORIGINAL_LOCKS, STAGES, commands, lock_metadata
    receipt_keys = {"schemaVersion", "runtime_profile", "status", "code", "conformanceProof", "releaseProof",
                    "publication", "services", "cleanupVerified", "sourceHeld", "source_commit", "source_tree",
                    "harness_commit", "run_id", "inputs", "inputSetSha256", "originalLocks", "generatedLocks", "steps"}
    if (not isinstance(receipt, dict) or set(receipt) != receipt_keys or job.get("mode") != "sdk-lockfiles"
            or json.loads(job["specs"]) != ["sdk-lockfiles"]
            or any(job.get(key) for key in ("preparation_id", "prepared_run_id", "runtime_seed", "capacity_configuration", "case_title"))
            or report.get("runtime_profile") != "sdk-lockfiles"
            or report.get("results") != [{"suite": "sdk-lockfiles", "exit_code": 0, "failure_code": None}]
            or receipt.get("schemaVersion") != 1 or receipt.get("status") != "passed" or receipt.get("code") is not None
            or receipt.get("runtime_profile") != "sdk-lockfiles"
            or receipt.get("source_commit") != job["source"] or receipt.get("source_tree") != expected_tree
            or receipt.get("harness_commit") != harness or str(receipt.get("run_id")) != str(job["run_id"])
            or receipt.get("conformanceProof") is not False or receipt.get("releaseProof") is not False
            or receipt.get("publication") is not False or receipt.get("services") != {}
            or receipt.get("cleanupVerified") is not True or receipt.get("sourceHeld") is not True
            or not expected_inputs or receipt.get("inputs") != expected_inputs
            or receipt.get("inputSetSha256") != hashlib.sha256(json.dumps(expected_inputs, sort_keys=True).encode()).hexdigest()
            or not all(name in expected_inputs for name in ORIGINAL_LOCKS) or LOCKS[-1] in expected_inputs
            or receipt.get("originalLocks") != {name: expected_inputs.get(name) for name in LOCKS}
            or set(outputs) != set(LOCKS)):
        return False
    try:
        metadata = {name: lock_metadata(data) for name, data in outputs.items()}
    except (ValueError, RuntimeError, TypeError):
        return False
    if receipt.get("generatedLocks") != metadata:
        return False
    steps = receipt.get("steps")
    expected_commands = [["rustup", "toolchain", "install", "1.98.1", "--profile", "minimal"], *commands()]
    if (not isinstance(steps, list) or len(steps) != 5
            or any(not isinstance(row, dict) for row in steps)
            or [row.get("stage") for row in steps] != ["rust-toolchain", *STAGES]):
        return False
    for index, (row, argv) in enumerate(zip(steps, expected_commands)):
        command = row.get("command")
        if (set(row) != {"stage", "status", "started", "returncode", "terminatedReturncode", "elapsedSeconds", "command"}
                or row.get("status") != "passed" or row.get("started") is not True
                or type(row.get("returncode")) is not int or row["returncode"] != 0
                or type(row.get("terminatedReturncode")) is not int or row["terminatedReturncode"] != 0
                or type(row.get("elapsedSeconds")) not in (int, float)
                or not math.isfinite(row["elapsedSeconds"]) or not 0 <= row["elapsedSeconds"] <= (306 if index == 0 else 186)
                or not isinstance(command, dict)
                or set(command) != {"tool", "argvSha256", "executableSha256", "executableBytes", "executableKind", "admission", "entryPackage"}
                or command.get("tool") != ("rustup" if index == 0 else "cargo")
                or command.get("admission") != "strict-owner-mode" or command.get("entryPackage") is not None
                or command.get("argvSha256") != hashlib.sha256(json.dumps(argv, separators=(",", ":")).encode()).hexdigest()
                or not isinstance(command.get("executableSha256"), str)
                or not re.fullmatch(r"[0-9a-f]{64}", command["executableSha256"])
                or type(command.get("executableBytes")) is not int or not 0 < command["executableBytes"] <= 256 * 1024**2
                or command.get("executableKind") not in {"elf", "script", "regular"}):
            return False
    return True


def valid_sdk_conformance_receipt(report: dict, sdk: dict, job: dict, harness: str, *, trust: dict, expected_inputs: dict) -> bool:
    """Require the exact reviewed plan, immutable candidate inputs and every stage."""
    try:
        from scripts.ci_sdk_conformance import LOCKS, LIBRARY_UNIT_MANIFESTS, library_unit_command
    except ModuleNotFoundError:
        from ci_sdk_conformance import LOCKS, LIBRARY_UNIT_MANIFESTS, library_unit_command
    if (json.loads(job["specs"]) != ["sdk-conformance"]
            or report.get("runtime_profile") != "sdk-conformance"
            or report.get("results") != [{"suite": "sdk-conformance", "exit_code": 0,
                                          "failed_stage": None, "failure_code": None}]
            or not isinstance(sdk, dict) or sdk.get("status") != "passed"
            or sdk.get("source_commit") != job["source"] or sdk.get("harness_commit") != harness
            or str(sdk.get("run_id")) != str(job["run_id"])
            or sdk.get("publication") is not False or sdk.get("services") != {}
            or any(sdk.get(key) is not True for key in ("cleanupVerified", "loadIdentityVerified", "sourceHeld"))
            or not expected_inputs or sdk.get("inputs") != expected_inputs
            or sdk.get("inputSetSha256") != hashlib.sha256(json.dumps(expected_inputs, sort_keys=True).encode()).hexdigest()
            or not all(name in expected_inputs for name in LOCKS)
            or sdk.get("locks") != {name: expected_inputs[name] for name in LOCKS}):
        return False
    stages = ["rust-toolchain", "python-environment", "node-dependencies", "python-dependencies", *LIBRARY_UNIT_MANIFESTS, "napi-build",
              "python-binding-build", "sdk-facade-build", "napi-load", "python-load", "real-conformance"]
    steps = sdk.get("steps")
    if (not isinstance(steps, list) or not all(isinstance(row, dict) for row in steps)
            or [row.get("stage") for row in steps] != stages
            or any(row.get("status") != "passed" or type(row.get("returncode")) is not int or row["returncode"] != 0
                   or row.get("terminatedReturncode") != 0
                   or type(row.get("elapsedSeconds")) not in (int, float)
                   or not math.isfinite(row["elapsedSeconds"]) or row["elapsedSeconds"] < 0 for row in steps)):
        return False
    for step in steps:
        if step["stage"] not in LIBRARY_UNIT_MANIFESTS:
            continue
        unit, command = step.get("unitTests"), step.get("command")
        expected_argv = hashlib.sha256(json.dumps(library_unit_command(step["stage"]), separators=(",", ":")).encode()).hexdigest()
        if (not isinstance(unit, dict) or type(unit.get("passed")) is not int or unit["passed"] <= 0
                or any(type(unit.get(key)) is not int or unit[key] != 0
                       for key in ("failed", "ignored", "measured", "filteredOut"))
                or step.get("started") is not True or not isinstance(command, dict)
                or command.get("tool") != "cargo" or command.get("admission") != "strict-owner-mode"
                or command.get("argvSha256") != expected_argv
                or not isinstance(command.get("executableSha256"), str)
                or not re.fullmatch(r"[0-9a-f]{64}", command["executableSha256"])):
            return False
    gate, artifacts, dist = sdk.get("gate"), sdk.get("artifacts"), sdk.get("dist")
    if not isinstance(gate, dict) or not isinstance(artifacts, dict) or not isinstance(dist, dict):
        return False
    plan = trust["plan"]
    rows, launches = gate.get("conformance"), gate.get("actualLaunches")
    expected_rows = [{"capability": row["capability"], "language": row["language"],
                      "fixtureSha256": row["fixtureSha256"], "vectors": row["vectors"], "status": "passed"} for row in plan]
    def digest(value):
        return isinstance(value, str) and re.fullmatch(r"[0-9a-f]{64}", value)
    return (gate.get("plan") == plan and rows == expected_rows
            and gate.get("matrixSha256") == trust["contracts"]["config/sdk-capabilities.json"]
            and gate.get("trustedProgramsSha256") == hashlib.sha256(json.dumps(trust["programs"], sort_keys=True).encode()).hexdigest()
            and gate.get("openGapCount") == len(trust["gaps"])
            and gate.get("releaseEligible") is (not trust["gaps"])
            and gate.get("realRunCount") == len(plan)
            and gate.get("vectorOutcomeCount") == sum(len(row["vectors"]) for row in plan)
            and isinstance(launches, list) and len(launches) == len(plan)
            and all(isinstance(value, dict) and value.get("capability") == row["capability"]
                    and value.get("language") == row["language"] and value.get("status") == "passed"
                    and digest(value.get("commandSha256")) for value, row in zip(launches, plan))
            and set(artifacts) == {"npm", "python"}
            and all(isinstance(value, dict) and value.get("elf") == "linux-x64"
                    and digest(value.get("sha256")) and type(value.get("nlink")) is int and value["nlink"] == 1
                    and all(type(value.get(key)) is int for key in ("device", "inode", "uid", "mode", "mtimeNs", "ctimeNs", "bytes"))
                    and value["bytes"] > 64 and not value["mode"] & 0o002 for value in artifacts.values())
            and "frontend/packages/openmates-cli/dist/sdk-entry.js" in dist
            and all(isinstance(name, str) and name.startswith("frontend/packages/openmates-cli/dist/")
                    and ".." not in Path(name).parts and digest(value) for name, value in dist.items()))


def valid_e2e_case_coverage(report: dict, job: dict) -> bool:
    """A filtered green run covers one case and cannot credit a whole spec."""
    selected_case = job.get("case_title") or ""
    expected_scope = "single-case" if selected_case else "full-spec"
    results = report.get("results")
    if (report.get("case_title", "") != selected_case
            or report.get("coverage_scope", "full-spec") != expected_scope):
        return False
    if not selected_case:
        return True
    if not (isinstance(results, list) and len(results) == 1
            and isinstance(results[0], dict)):
        return False
    item = results[0]
    stats = item.get("stats")
    return (item.get("case_title") == selected_case
            and item.get("reported_case_title") == selected_case
            and item.get("coverage_scope") == "single-case"
            and item.get("coverage_complete") is True
            and isinstance(stats, dict)
            and all(type(stats.get(name, 0)) is int and stats.get(name, 0) >= 0
                    for name in ("expected", "unexpected", "flaky", "skipped"))
            and sum(stats.get(name, 0) for name in ("expected", "unexpected", "flaky")) == 1
            and stats.get("skipped", 0) == 0)


def attach_cleanup(result: dict, job: dict, directory: Path) -> dict:
    """Expose run-bound teardown evidence, including cached historical receipts.

    A passing browser result alone cannot prove disposable accounts/databases
    were removed. Failed jobs retain absent/failed teardown as visible evidence
    instead of hiding their original assertion report.
    """
    if job.get("mode") not in ("e2e", "selfhost", "visual-smoke", "backend-probe"):
        return result
    if job.get("mode") == "visual-smoke" and job["state"] == "success":
        try:
            from scripts.ci_visual_smoke import verify_capture
        except ModuleNotFoundError:
            from ci_visual_smoke import verify_capture
        captures = list(directory.rglob("ci-visual-smoke/receipt.json"))
        if len(captures) != 1:
            raise RuntimeError("Expected exactly one visual-smoke capture receipt")
        result["visual_smoke"] = verify_capture(captures[0].parent, json.loads(job["specs"]))
    paths = list(directory.rglob("ci-cleanup.json"))
    cleanup = json.loads(paths[0].read_text()) if len(paths) == 1 else result.get("cleanup")
    valid = bool(cleanup and str(cleanup.get("run_id")) == str(job["run_id"])
                 and cleanup.get("harness_commit") == result.get("harness_commit")
                 and cleanup.get("containers_remaining") == 0
                 and cleanup.get("volumes_remaining") == 0
                 and cleanup.get("private_account_files_removed") is True
                 and not cleanup.get("errors"))
    result.update(cleanup=cleanup, cleanup_verified=valid)
    if job["state"] == "success" and not valid:
        label = "Backend diagnostic" if job.get("mode") == "backend-probe" else "E2E"
        raise RuntimeError(f"Green {label} lacks verified run-bound account/container/volume cleanup")
    return result


def attach_visual_evidence(result, directory):
    # Collect immutable delivery obligations on both green and failed retrievals.
    # Upload is an explicit separate command: it cannot change the test verdict.
    try:
        from scripts.codex_evidence import prepare
    except ModuleNotFoundError:
        from codex_evidence import prepare
    result["codex_evidence"] = str(prepare(directory, result))
    result["codex_evidence_command"] = f"python3 scripts/codex_evidence.py {directory} --upload"
    return result


def fetch(github, job: dict, root: Path) -> dict:
    """Reserve archive plus expanded bytes until extraction and receipt finish."""
    destination = root / "test-results/ci-runs" / job["id"]
    if (destination / "receipt.json").is_file():
        return _fetch_reserved(github, job, root)
    try:
        from scripts.resource_budget import reserve
    except ModuleNotFoundError:
        from resource_budget import reserve
    # Retrieval has always used the 30 GiB reserve; 85% gates new worktrees.
    with reserve(root, MAX_ARCHIVE + MAX_EXPANDED, min_free=RESERVE,
                 max_used_percent=100):
        return _fetch_reserved(github, job, root)


def _fetch_reserved(github, job: dict, root: Path) -> dict:
    destination = root / "test-results/ci-runs" / job["id"]
    receipt = destination / "receipt.json"
    if receipt.is_file():
        return attach_visual_evidence(attach_cleanup(json.loads(receipt.read_text()), job, destination), destination)
    if not job["run_id"] or job["state"] not in ("success", "failure", "cancelled"):
        raise RuntimeError("CI job has no terminal result yet")
    run = github.request(f"repos/{github.repo}/actions/runs/{job['run_id']}")
    runner_jobs = github.request(
        f"repos/{github.repo}/actions/runs/{job['run_id']}/jobs?per_page=100"
    )["jobs"]
    dedicated_capacity = bool(job.get("capacity_configuration") and
                              json.loads(job.get("specs", "[]")) == ["storage-capacity-target.spec.ts"])
    if dedicated_capacity:
        try:
            from scripts.ci_capacity_config import validate_configuration
        except ModuleNotFoundError:
            from ci_capacity_config import validate_configuration
        validate_configuration(json.loads(job["capacity_configuration"]), source=job["source"], target=True)
    def admitted_runner(entry):
        labels = set(entry.get("labels", []))
        if dedicated_capacity:
            return {"self-hosted", "Linux", "X64", "openmates-capacity"}.issubset(labels)
        return "ubuntu-latest" in labels and entry.get("runner_name", "").startswith("GitHub Actions")
    if not runner_jobs or any(not admitted_runner(entry) for entry in runner_jobs):
        raise RuntimeError(
            "Test evidence did not execute exclusively on admitted isolated runners"
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
        or shutil.disk_usage(root).free < RESERVE
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
        expected_harness_commit = job.get("preparation_harness_commit") or run["head_sha"]
        if report and (
            report.get("harness_commit") != expected_harness_commit
            or report.get("proof_profile", "") != job.get("proof_profile", "")
        ):
            raise RuntimeError(
                "CI harness or requested proof profile identity mismatch"
            )
        if job["state"] == "success" and job.get("mode") in ("component", "e2e", "visual-smoke"):
            if not green_e2e_source_and_egress_verified(
                    environment_data, job, expected_harness_commit=expected_harness_commit,
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
            if not valid_e2e_case_coverage(report, job):
                raise RuntimeError("Result case coverage differs from the requested filter")
            if job.get("mode") == "component" and (
                report.get("runtime_profile") != "component"
                or environment_data.get("frontend", {}).get("renderer")
                != "vite-dev"
            ):
                raise RuntimeError(
                    "Component proof lacks the GitHub-hosted Vite runtime evidence"
                )
        if job["state"] == "success" and job.get("mode") == "backend-probe":
            if not valid_backend_probe_receipt(
                    report, environment_data, job,
                    expected_harness_commit=expected_harness_commit):
                raise RuntimeError("Backend diagnostic lacks exact isolated health evidence")
        if job["state"] == "success" and job.get("mode") == "sdk-lockfiles":
            try:
                from scripts.ci_sdk_lockfiles import LOCKS, source_inputs_from_git
            except ModuleNotFoundError:
                from ci_sdk_lockfiles import LOCKS, source_inputs_from_git
            receipts = list(extracted.rglob("ci-sdk-lockfiles.json"))
            lock_receipt = json.loads(receipts[0].read_text()) if len(receipts) == 1 else {}
            roots = [path for path in extracted.rglob("sdk-lockfiles") if path.is_dir()]
            lock_outputs = {}
            if len(roots) == 1:
                inventory = {path.relative_to(roots[0]).as_posix(): path for path in roots[0].rglob("*") if path.is_file()}
                if set(inventory) == set(LOCKS):
                    lock_outputs = {name: path.read_bytes() for name, path in inventory.items()}
            expected_tree = subprocess.check_output(["git", "rev-parse", job["source"] + "^{tree}"], cwd=root, text=True, timeout=15).strip()
            if not valid_sdk_lockfiles_receipt(report, lock_receipt, job, expected_harness_commit,
                    expected_inputs=source_inputs_from_git(root, job["source"]), expected_tree=expected_tree,
                    outputs=lock_outputs):
                raise RuntimeError("SDK lock preparation lacks exact source/output/command/cleanup evidence")
        if job["state"] == "success" and job.get("mode") == "sdk-conformance":
            sdk_paths = list(extracted.rglob("ci-sdk-conformance.json"))
            sdk_data = json.loads(sdk_paths[0].read_text()) if len(sdk_paths) == 1 else {}
            try:
                from scripts.ci_sdk_conformance import load_trust, source_inputs_from_git
            except ModuleNotFoundError:
                from ci_sdk_conformance import load_trust, source_inputs_from_git
            if not valid_sdk_conformance_receipt(report, sdk_data, job, expected_harness_commit,
                    trust=load_trust(), expected_inputs=source_inputs_from_git(root, job["source"])):
                raise RuntimeError("Green SDK job lacks exact library/vector or cleanup evidence")
        if job["state"] == "success" and job.get("mode") == "artifact":
            if (report.get("runtime_profile") != "artifact"
                    or report.get("artifact_shared_dev_rejected") is not True
                    or sorted(item.get("spec", "") for item in report["results"])
                    != sorted(json.loads(job["specs"]))):
                raise RuntimeError("Artifact proof lacks exact inventory or isolated runtime evidence")
        result = {
            "id": job["id"],
            "source_commit": job["source"],
            "run_id": job["run_id"],
            "state": job["state"],
            "mode": job["mode"],
            "selected_specs": json.loads(job["specs"]),
            "selected_case_title": job.get("case_title") or "",
            "coverage_scope": "single-case" if job.get("case_title") else "full-spec",
            "harness_commit": expected_harness_commit,
            "runner_jobs": [
                {
                    "id": entry["id"],
                    "labels": entry["labels"],
                    "runner_name": entry["runner_name"],
                }
                for entry in runner_jobs
            ],
            "report": report,
            "timings": timings(job, runner_jobs),
            "preparation": {"request_id": job.get("preparation_id"), "run_id": job.get("prepared_run_id"), "key": job.get("preparation_key")},
            "environment": environment_data,
            "artifact_id": artifact["id"],
            "artifact_url": f"{job['url']}/artifacts/{artifact['id']}",
            "directory": str(destination),
        }
        attach_cleanup(result, job, extracted)
        (extracted / "receipt.json").write_text(json.dumps(result, indent=2))
        extracted.rename(destination)
    return attach_visual_evidence(result, destination)
