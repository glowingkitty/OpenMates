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


def valid_selfhost_result(report, job, root, expected_harness_commit):
    try:
        from scripts.ci_selfhost_contract import RECIPE, identity, validate_result
    except ModuleNotFoundError:
        from ci_selfhost_contract import RECIPE, identity, validate_result
    import hashlib

    try:
        tree = subprocess.check_output(
            ["git", "rev-parse", job["source"] + "^{tree}"],
            cwd=root,
            text=True,
            timeout=15,
        ).strip()
        recipe = subprocess.check_output(
            ["git", "show", job["source"] + ":" + RECIPE], cwd=root, timeout=15
        )
        expected = identity(
            job["source"],
            tree,
            hashlib.sha256(recipe).hexdigest(),
            expected_harness_commit,
        )
        return validate_result(report, job, expected)
    except (OSError, subprocess.SubprocessError, ValueError):
        return False


def green_e2e_source_and_egress_verified(
    environment: dict,
    job: dict,
    *,
    expected_harness_commit: str | None = None,
) -> bool:
    """Require the exact source runtime for browser or supported API-only E2E."""
    if (
        environment.get("source_commit") != job["source"]
        or environment.get("shared_dev_https") != "rejected"
        or (job.get("mode") != "component" and not environment.get("services"))
    ):
        return False
    selected = sorted(json.loads(job["specs"]))
    if job.get("mode") == "e2e" and selected == [
        "storage-accountability-integration.spec.ts"
    ]:
        services = environment["services"]
        expected = {"api", "core-worker", "cms", "cms-database", "cache", "vault"}
        if (
            environment.get("frontend") is not None
            or environment.get("shared_dev_dns") != "rejected"
            or set(services) != expected
            or any(service.get("running") is not True for service in services.values())
        ):
            return False
        for name in ("api", "core-worker"):
            source = services[name].get("backend_source")
            if not isinstance(source, str) or Path(source).parts[-2:] != (
                "subject",
                "backend",
            ):
                return False
        return True
    if job.get("mode") == "e2e" and selected in (
        ["storage-team-portability.spec.ts"],
        ["storage-archive-lifecycle.spec.ts"],
    ):
        services = environment["services"]
        expected = {
            "api",
            "core-worker",
            "cms",
            "cms-database",
            "cache",
            "vault",
            "ai-worker",
            "runner-gateway",
            "object-storage",
        }
        harness = expected_harness_commit or job.get("preparation_harness_commit")
        if (
            environment.get("frontend") is not None
            or environment.get("shared_dev_dns") != "rejected"
            or environment.get("runner_environment") != "github-hosted"
            or job.get("run_id") is None
            or environment.get("run_id") is None
            or str(environment["run_id"]) != str(job["run_id"])
            or not harness
            or environment.get("harness_commit") != harness
            or not isinstance(services, dict)
            or set(services) != expected
            or any(
                not isinstance(service, dict) or service.get("running") is not True
                for service in services.values()
            )
        ):
            return False
        mounts = [
            services[name].get("backend_source")
            for name in ("api", "core-worker", "ai-worker")
        ]
        if (
            any(
                not isinstance(source, str)
                or not Path(source).is_absolute()
                or Path(source).parts[-2:] != ("subject", "backend")
                for source in mounts
            )
            or len(set(mounts)) != 1
        ):
            return False
        capacity = environment.get("storage_capacity")
        isolation = environment.get("storage_isolation_proof")
        storage = environment.get("object_storage")
        if not all(isinstance(proof, dict) for proof in (capacity, isolation, storage)):
            return False
        slots = capacity.get("worker_slots")
        return (
            environment.get("provider_egress") == "rejected-internal-network"
            and capacity.get("provider_credentials") == "absent"
            and capacity.get("provider_network") == "internal"
            and capacity.get("fixture_mode") == "replay-only"
            and type(slots) is int
            and 1 <= slots <= 4
            and type(capacity.get("worker_replicas")) is int
            and capacity["worker_replicas"] == 1
            and isolation.get("source_bound") is True
            and isolation.get("read_only_bind") is True
            and isolation.get("vault_provider_namespace") == "disposable_only"
            and storage.get("endpoint") == "http://storage.ci.test:9000"
            and storage.get("provider") == "SeaweedFS"
            and storage.get("protocol_probe")
            == "authenticated-roundtrip-cors-presigned-and-private-access-passed"
        )
    return environment.get("frontend", {}).get("source_commit") == job["source"] and (
        job.get("mode") == "component" or bool(environment["services"])
    )


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
        start, end = (
            timestamp(runner.get("started_at")),
            timestamp(runner.get("completed_at")),
        )
        if start is not None:
            starts.append(start)
        if end is not None:
            ends.append(end)
        for step in runner.get("steps", []):
            start, end = (
                timestamp(step.get("started_at")),
                timestamp(step.get("completed_at")),
            )
            if start is not None and end is not None:
                phases.append(
                    {
                        "job_id": runner["id"],
                        "name": step["name"],
                        "conclusion": step.get("conclusion"),
                        "seconds": round(max(0, end - start), 3),
                    }
                )
    result = {"steps": phases}
    if starts and ends:
        result["github_job_wall_seconds"] = round(max(ends) - min(starts), 3)
    created, sent = job.get("created"), job.get("sent")
    if created is not None and sent is not None:
        ready = job.get("ready_at") or created
        result["coordinator_admission_seconds"] = round(max(0, sent - ready), 3)
        result["preparation_wait_seconds"] = round(max(0, ready - created), 3)
        if starts:
            result["dispatch_to_job_start_seconds"] = round(
                max(0, min(starts) - sent), 3
            )
        if ends:
            result["request_to_github_completion_seconds"] = round(
                max(0, max(ends) - created), 3
            )
    return result


def download(command, root, output, *, limit=None):
    """Drain both pipes with a wall-clock deadline and bounded retained output."""
    if limit is None:
        limit = MAX_ARCHIVE
    if type(limit) is not int or not 0 < limit <= MAX_ARCHIVE:
        raise ValueError("Invalid bounded CI artifact download limit")
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
                        if size > limit:
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
        # Only a newly created tree may be normalized: never chmod caller-owned
        # existing paths or allow extraction through their links. The private
        # root excludes other users while ZIP-created children inherit umask.
        parent = destination.parent
        if (
            not destination.is_absolute()
            or parent.resolve() != parent
            or not parent.is_dir()
            or parent.stat().st_uid != os.getuid()
            or parent.stat().st_mode & 0o022
        ):
            raise RuntimeError("Unsafe CI artifact extraction parent")
        try:
            destination.mkdir(mode=0o700)
        except FileExistsError:
            raise RuntimeError(
                "CI artifact extraction requires a fresh destination"
            ) from None
        bundle.extractall(destination)
        for directory, directories, files in os.walk(destination, followlinks=False):
            for path in [
                Path(directory),
                *(Path(directory) / name for name in directories + files),
            ]:
                descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
                try:
                    info = os.fstat(descriptor)
                    if (
                        info.st_uid != os.getuid()
                        or not (
                            stat.S_ISDIR(info.st_mode) or stat.S_ISREG(info.st_mode)
                        )
                        or stat.S_ISREG(info.st_mode)
                        and info.st_nlink != 1
                    ):
                        raise RuntimeError("Unsafe extracted CI artifact entry")
                    os.fchmod(
                        descriptor, 0o700 if stat.S_ISDIR(info.st_mode) else 0o600
                    )
                    held = path.lstat()
                    if (held.st_dev, held.st_ino) != (info.st_dev, info.st_ino):
                        raise RuntimeError("Changed extracted CI artifact entry")
                finally:
                    os.close(descriptor)


def valid_backend_probe_receipt(
    report: dict, environment: dict, job: dict, *, expected_harness_commit: str
) -> bool:
    """Admit only isolated diagnostic health; this is never recovery E2E proof."""
    if not isinstance(report, dict) or not isinstance(environment, dict):
        return False
    results = report.get("results")
    services = environment.get("services")
    required = {
        "api",
        "ai-worker",
        "core-worker",
        "runner-gateway",
        "cms",
        "cms-database",
        "cache",
        "vault",
    }
    return (
        report.get("runtime_profile") == "backend-probe"
        and report.get("diagnostic_only") is True
        and report.get("recovery_e2e_verified") is False
        and report.get("latency_acceptance_verified") is False
        and isinstance(results, list)
        and len(results) == 1
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
        and isinstance(services, dict)
        and required.issubset(services)
        and all(
            isinstance(services[name], dict) and services[name].get("running") is True
            for name in required
        )
    )


def valid_rust_wasm_diagnostic(
    descriptor, identity_bytes, tail, job, harness, expected_tree
):
    """Validate the optional private tail without exposing its text in receipts."""
    try:
        from scripts.ci_rust_wasm import (
            DIAGNOSTIC_ARTIFACT,
            DIAGNOSTIC_LIMIT,
            ALL_STAGES as STAGES,
        )
    except ModuleNotFoundError:
        from ci_rust_wasm import (
            DIAGNOSTIC_ARTIFACT,
            DIAGNOSTIC_LIMIT,
            ALL_STAGES as STAGES,
        )
    if (
        not isinstance(descriptor, dict)
        or set(descriptor)
        != {"artifactName", "identity", "identitySha256", "publicRawUpload"}
        or descriptor.get("artifactName") != DIAGNOSTIC_ARTIFACT
        or descriptor.get("publicRawUpload") is not False
        or not isinstance(identity_bytes, bytes)
        or len(identity_bytes) > 16384
        or not isinstance(tail, bytes)
        or len(tail) > DIAGNOSTIC_LIMIT
        or descriptor.get("identitySha256")
        != hashlib.sha256(identity_bytes).hexdigest()
    ):
        return False
    try:
        identity = json.loads(identity_bytes)
    except (ValueError, UnicodeError):
        return False
    keys = {
        "schemaVersion",
        "source_commit",
        "source_tree",
        "harness_commit",
        "run_id",
        "stage",
        "path",
        "bytes",
        "originalBytes",
        "sha256",
        "truncated",
    }
    return (
        isinstance(identity, dict)
        and set(identity) == keys
        and descriptor.get("identity") == identity
        and identity.get("schemaVersion") == 1
        and identity.get("source_commit") == job["source"]
        and identity.get("source_tree") == expected_tree
        and identity.get("harness_commit") == harness
        and str(identity.get("run_id")) == str(job["run_id"])
        and identity.get("stage") in STAGES
        and identity.get("path") == "cargo-tail.log"
        and type(identity.get("bytes")) is int
        and identity["bytes"] == len(tail)
        and type(identity.get("originalBytes")) is int
        and len(tail) <= identity["originalBytes"] <= 2**63 - 1
        and identity["bytes"] == min(identity["originalBytes"], DIAGNOSTIC_LIMIT)
        and identity.get("truncated") is (identity["originalBytes"] > len(tail))
        and identity.get("sha256") == hashlib.sha256(tail).hexdigest()
    )


def fetch_rust_wasm_diagnostic(
    github, job, root, artifacts, descriptor, harness, expected_tree, destination
):
    """Use authenticated managed retrieval, strict ZIP inventory and private modes."""
    try:
        from scripts.ci_rust_wasm import DIAGNOSTIC_ARTIFACT, DIAGNOSTIC_LIMIT
    except ModuleNotFoundError:
        from ci_rust_wasm import DIAGNOSTIC_ARTIFACT, DIAGNOSTIC_LIMIT
    matches = [item for item in artifacts if item["name"] == DIAGNOSTIC_ARTIFACT]
    if not isinstance(descriptor, dict) or "identity" not in descriptor:
        if matches:
            raise RuntimeError("Unexpected Rust WASM private diagnostic artifact")
        return {"status": "not-captured", "publicRawUpload": False}
    if len(matches) != 1 or matches[0].get("expired"):
        return {
            "status": "unavailable",
            "reason": "missing-or-expired-private-artifact",
            "publicRawUpload": False,
        }
    artifact = matches[0]
    if not 0 < artifact.get("size_in_bytes", 0) <= 256 * 1024:
        raise RuntimeError("Rust WASM private diagnostic archive exceeds bound")
    with tempfile.TemporaryDirectory(
        dir=destination.parent, prefix="wasm-diagnostic-"
    ) as temporary:
        archive = Path(temporary) / "diagnostic.zip"
        with archive.open("wb") as stream:
            download(
                [
                    "gh",
                    "api",
                    f"repos/{github.repo}/actions/artifacts/{artifact['id']}/zip",
                ],
                root,
                stream,
                limit=256 * 1024,
            )
        with zipfile.ZipFile(archive) as bundle:
            entries = bundle.infolist()
            if (
                len(entries) != 2
                or {row.filename for row in entries}
                != {"identity.json", "cargo-tail.log"}
                or any(stat.S_ISLNK(row.external_attr >> 16) for row in entries)
                or any(
                    row.file_size
                    > (16384 if row.filename == "identity.json" else DIAGNOSTIC_LIMIT)
                    for row in entries
                )
            ):
                raise RuntimeError("Unsafe Rust WASM private diagnostic inventory")
            identity, tail = bundle.read("identity.json"), bundle.read("cargo-tail.log")
        if not valid_rust_wasm_diagnostic(
            descriptor, identity, tail, job, harness, expected_tree
        ):
            raise RuntimeError("Rust WASM private diagnostic identity/hash mismatch")
        destination.mkdir(mode=0o700)
        for name, data in (("identity.json", identity), ("cargo-tail.log", tail)):
            with (destination / name).open("xb") as stream:
                os.fchmod(stream.fileno(), 0o600)
                stream.write(data)
    return {
        "status": "verified",
        "artifact_id": artifact["id"],
        "artifact_name": DIAGNOSTIC_ARTIFACT,
        "path": "rust-wasm-private/cargo-tail.log",
        "bytes": len(tail),
        "sha256": hashlib.sha256(tail).hexdigest(),
        "truncated": descriptor["identity"]["truncated"],
        "publicRawUpload": False,
    }


def valid_browser_package(
    manifest_bytes, files, receipt, job, harness, expected_inputs, expected_tree
):
    """Independently validate the generated package and public tool provenance."""
    try:
        from scripts.ci_rust_wasm import (
            BINDGEN_VERSION,
            package_names,
            package_modules,
            metadata,
            closed_module_dependencies,
        )
    except ModuleNotFoundError:
        from ci_rust_wasm import (
            BINDGEN_VERSION,
            package_names,
            package_modules,
            metadata,
            closed_module_dependencies,
        )
    if (
        not isinstance(manifest_bytes, bytes)
        or len(manifest_bytes) > 2 * 1024**2
        or not isinstance(files, dict)
    ):
        return False
    try:
        manifest = json.loads(manifest_bytes)
    except (ValueError, UnicodeError):
        return False
    keys = {
        "schemaVersion",
        "status",
        "source_commit",
        "source_tree",
        "harness_commit",
        "run_id",
        "inputs",
        "inputSetSha256",
        "locks",
        "target",
        "toolchain",
        "inputWasmSha256",
        "wasmBindgenVersion",
        "toolSha256",
        "toolProvenance",
        "inventory",
        "browserRuntimeProof",
        "requestedMode",
        "requestedTargets",
    }
    metadata_profile = job.get("mode") == "e2e" and metadata.targets(
        json.loads(job["specs"])
    )
    if metadata_profile:
        keys.add("features")
    first_session_profile = job.get("mode") == "e2e" and metadata.first_session_targets(
        json.loads(job["specs"])
    )
    native_recovery_profile = job.get(
        "mode"
    ) == "e2e" and metadata.native_recovery_targets(json.loads(job["specs"]))
    activechat_profile = job.get("mode") == "e2e" and metadata.activechat_targets(
        json.loads(job["specs"])
    )
    new_chat_profile = job.get("mode") == "e2e" and metadata.new_chat_targets(
        json.loads(job["specs"])
    )
    package = receipt.get("package")
    if (
        not isinstance(manifest, dict)
        or set(manifest) != keys
        or manifest.get("schemaVersion") != 1
        or manifest.get("status") != "passed"
        or manifest.get("source_commit") != job["source"]
        or manifest.get("source_tree") != expected_tree
        or manifest.get("harness_commit") != harness
        or str(manifest.get("run_id")) != str(job["run_id"])
        or manifest.get("inputs") != expected_inputs
        or manifest.get("inputSetSha256") != receipt.get("inputSetSha256")
        or manifest.get("locks") != receipt.get("locks")
        or manifest.get("target") != "wasm32-unknown-unknown"
        or manifest.get("toolchain") != "1.98.1"
        or manifest.get("inputWasmSha256") != receipt.get("artifact", {}).get("sha256")
        or manifest.get("wasmBindgenVersion") != BINDGEN_VERSION
        or manifest.get("browserRuntimeProof") is not False
        or manifest.get("requestedMode") != job.get("mode")
        or manifest.get("requestedTargets") != json.loads(job["specs"])
        or not isinstance(package, dict)
        or set(package) != {"manifestSha256", "inventorySha256", "toolProvenance"}
        or package.get("manifestSha256") != hashlib.sha256(manifest_bytes).hexdigest()
        or (
            metadata_profile
            and (
                manifest.get("features") != [metadata.FEATURE]
                or not isinstance(expected_inputs, dict)
                or not metadata.EXTRA_INPUTS <= set(expected_inputs)
                or not metadata.package_modules(
                    files, expected_inputs, closed_module_dependencies
                )
            )
        )
        or (
            first_session_profile
            and (
                not isinstance(expected_inputs, dict)
                or not metadata.FIRST_SESSION_INPUTS <= set(expected_inputs)
            )
        )
        or (
            native_recovery_profile
            and (
                not isinstance(expected_inputs, dict)
                or not metadata.NATIVE_RECOVERY_INPUTS <= set(expected_inputs)
            )
        )
        or (
            activechat_profile
            and (
                not isinstance(expected_inputs, dict)
                or not metadata.ACTIVECHAT_INPUTS <= set(expected_inputs)
            )
        )
        or (
            new_chat_profile
            and (
                not isinstance(expected_inputs, dict)
                or not metadata.NEW_CHAT_INPUTS <= set(expected_inputs)
            )
        )
        or (
            not metadata_profile
            and (
                not package_names(files) or not package_modules(files, expected_inputs)
            )
        )
    ):
        return False
    provenance = manifest.get("toolProvenance")
    provenance_keys = {
        "package",
        "version",
        "registry",
        "url",
        "crateSha256",
        "publishedCargoLockSha256",
        "binarySha256",
        "binaryIdentity",
    }
    if (
        not isinstance(provenance, dict)
        or set(provenance) != provenance_keys
        or package.get("toolProvenance") != provenance
        or provenance.get("package") != "wasm-bindgen-cli"
        or provenance.get("version") != BINDGEN_VERSION
        or provenance.get("registry") != "crates.io"
        or provenance.get("url")
        != "https://crates.io/crates/wasm-bindgen-cli/" + BINDGEN_VERSION
        or any(
            not isinstance(provenance.get(key), str)
            or not re.fullmatch(r"[0-9a-f]{64}", provenance[key])
            for key in ("crateSha256", "publishedCargoLockSha256", "binarySha256")
        )
        or manifest.get("toolSha256") != provenance["binarySha256"]
    ):
        return False
    identity = provenance.get("binaryIdentity")
    if (
        not isinstance(identity, dict)
        or set(identity)
        != {"device", "inode", "bytes", "mtimeNs", "ctimeNs", "mode", "uid", "links"}
        or any(type(value) is not int or value < 0 for value in identity.values())
        or identity["links"] != 1
        or not 0 < identity["bytes"] <= 256 * 1024**2
        or not stat.S_ISREG(identity["mode"])
        or not identity["mode"] & 0o111
        or identity["mode"] & 0o002
    ):
        return False
    steps = receipt.get("steps", [])
    if (
        len(steps) not in {6, 10}
        or (
            len(steps) == 10
            and (
                job.get("mode") != "rust-wasm"
                or [row.get("stage") for row in steps[6:]]
                != [
                    "worker-test-build",
                    "worker-runner-version",
                    "worker-chromium-install",
                    "worker-dedicated-tests",
                ]
            )
        )
        or any(
            row.get("command", {}).get("executableSha256") != provenance["binarySha256"]
            or row["command"].get("executableBytes") != identity["bytes"]
            for row in steps[4:6]
        )
    ):
        return False
    rows, total = [], 0
    for name in sorted(files):
        data = files[name]
        if not isinstance(data, bytes) or not 0 < len(data) <= 64 * 1024**2:
            return False
        if name.endswith(".wasm"):
            if data[:8] != b"\0asm\x01\0\0\0":
                return False
        else:
            try:
                data.decode("utf-8", errors="strict")
            except UnicodeError:
                return False
        total += len(data)
        rows.append(
            {
                "path": name,
                "sha256": hashlib.sha256(data).hexdigest(),
                "rawBytes": len(data),
            }
        )
    inventory = {
        "files": rows,
        "rawBytes": total,
        "inventorySha256": hashlib.sha256(
            json.dumps(rows, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest(),
    }
    return (
        total <= 128 * 1024**2
        and manifest.get("inventory") == inventory
        and package.get("inventorySha256") == inventory["inventorySha256"]
    )


def _browser_package_job(job):
    try:
        from scripts.ci_rust_wasm import browser_e2e_targets
    except ModuleNotFoundError:
        from ci_rust_wasm import browser_e2e_targets
    try:
        return job.get("mode") == "e2e" and browser_e2e_targets(
            json.loads(job.get("specs", "[]"))
        )
    except (ValueError, TypeError):
        return False


def valid_rust_wasm_receipt(
    report,
    receipt,
    job,
    harness,
    *,
    expected_inputs,
    expected_tree,
    artifact,
    package_manifest=None,
    package_files=None,
):
    """Credit compiler evidence only within its actual completed run report."""
    browser_e2e = _browser_package_job(job)
    expected_mode = "e2e" if browser_e2e else "rust-wasm"
    if (
        not isinstance(report, dict)
        or report.get("runtime_profile") != expected_mode
        or (
            not browser_e2e
            and report.get("results")
            != [{"suite": "rust-wasm", "exit_code": 0, "failure_code": None}]
        )
    ):
        return False
    return valid_rust_wasm_compiler_receipt(
        receipt,
        job,
        harness,
        expected_inputs=expected_inputs,
        expected_tree=expected_tree,
        artifact=artifact,
        package_manifest=package_manifest,
        package_files=package_files,
    )


def valid_rust_wasm_compiler_receipt(
    receipt,
    job,
    harness,
    *,
    expected_inputs,
    expected_tree,
    artifact,
    package_manifest=None,
    package_files=None,
):
    """Validate only complete compiler/packager evidence; no downstream report exists yet."""
    try:
        from scripts.ci_rust_wasm import (
            LOCKS,
            STAGES,
            STAGE_SECONDS,
            commands,
            wasm_metadata,
            metadata,
        )
    except ModuleNotFoundError:
        from ci_rust_wasm import (
            LOCKS,
            STAGES,
            STAGE_SECONDS,
            commands,
            wasm_metadata,
            metadata,
        )
    try:
        from scripts import ci_wasm_worker as worker
    except ModuleNotFoundError:
        import ci_wasm_worker as worker
    browser_e2e = _browser_package_job(job)
    expected_mode = "e2e" if browser_e2e else "rust-wasm"
    expected_targets = json.loads(job["specs"]) if browser_e2e else ["rust-wasm"]
    expected_profile = "rust-browser-package-for-e2e" if browser_e2e else "rust-wasm"
    keys = {
        "schemaVersion",
        "runtime_profile",
        "status",
        "code",
        "compilationProof",
        "browserRuntimeProof",
        "conformanceProof",
        "releaseProof",
        "publication",
        "services",
        "cleanupVerified",
        "sourceHeld",
        "packagingProof",
        "package",
        "source_commit",
        "source_tree",
        "harness_commit",
        "run_id",
        "inputs",
        "inputSetSha256",
        "locks",
        "artifact",
        "steps",
        "requestedMode",
        "requestedTargets",
        "workerProof",
    }
    if (
        not isinstance(receipt, dict)
        or set(receipt) != keys
        or job.get("mode") != expected_mode
        or json.loads(job["specs"]) != expected_targets
        or receipt.get("requestedMode") != expected_mode
        or receipt.get("requestedTargets") != expected_targets
        or any(
            job.get(key)
            for key in (
                ("capacity_configuration", "case_title")
                if browser_e2e
                else (
                    "preparation_id",
                    "prepared_run_id",
                    "runtime_seed",
                    "capacity_configuration",
                    "case_title",
                )
            )
        )
        or receipt.get("schemaVersion") != 1
        or receipt.get("status") != "passed"
        or receipt.get("code") is not None
        or receipt.get("runtime_profile") != expected_profile
        or receipt.get("compilationProof") is not True
        or receipt.get("packagingProof") is not True
        or any(
            receipt.get(key) is not False
            for key in (
                "browserRuntimeProof",
                "conformanceProof",
                "releaseProof",
                "publication",
            )
        )
        or receipt.get("source_commit") != job["source"]
        or receipt.get("source_tree") != expected_tree
        or receipt.get("harness_commit") != harness
        or str(receipt.get("run_id")) != str(job["run_id"])
        or receipt.get("services") != {}
        or receipt.get("cleanupVerified") is not True
        or receipt.get("sourceHeld") is not True
        or not expected_inputs
        or receipt.get("inputs") != expected_inputs
        or receipt.get("inputSetSha256")
        != hashlib.sha256(
            json.dumps(expected_inputs, sort_keys=True).encode()
        ).hexdigest()
        or not all(name in expected_inputs for name in LOCKS)
        or receipt.get("locks") != {name: expected_inputs[name] for name in LOCKS}
    ):
        return False
    try:
        if receipt.get("artifact") != wasm_metadata(artifact):
            return False
    except (ValueError, RuntimeError, TypeError):
        return False
    proof = receipt.get("workerProof")
    if (browser_e2e and proof is not None) or (
        not browser_e2e and not worker.valid_proof(proof)
    ):
        return False
    stages = STAGES if browser_e2e else (*STAGES, *worker.STAGES)
    seconds = STAGE_SECONDS if browser_e2e else (*STAGE_SECONDS, *worker.SECONDS)
    argv_rows = (
        commands(metadata_profile=metadata.targets(expected_targets))
        if browser_e2e
        else [*commands(), *worker.commands()]
    )
    steps = receipt.get("steps")
    if (
        not isinstance(steps, list)
        or len(steps) != len(stages)
        or not all(isinstance(row, dict) for row in steps)
        or [row.get("stage") for row in steps] != list(stages)
    ):
        return False
    for index, (row, argv) in enumerate(zip(steps, argv_rows)):
        command = row.get("command")
        if (
            set(row)
            != {
                "stage",
                "status",
                "started",
                "returncode",
                "terminatedReturncode",
                "elapsedSeconds",
                "command",
            }
            or row.get("status") != "passed"
            or row.get("started") is not True
            or type(row.get("returncode")) is not int
            or row["returncode"] != 0
            or type(row.get("terminatedReturncode")) is not int
            or row["terminatedReturncode"] != 0
            or type(row.get("elapsedSeconds")) not in (int, float)
            or not math.isfinite(row["elapsedSeconds"])
            or not 0 <= row["elapsedSeconds"] <= seconds[index] + 6
            or not isinstance(command, dict)
            or set(command)
            != {
                "tool",
                "argvSha256",
                "executableSha256",
                "executableBytes",
                "executableKind",
                "admission",
                "entryPackage",
            }
            or command.get("tool")
            != (
                "cargo"
                if index in {2, 3, 6}
                else "wasm-bindgen"
                if index in {4, 5}
                else "wasm-bindgen-test-runner"
                if index == 7
                else "node"
                if index in {8, 9}
                else "rustup"
            )
            or command.get("admission") != "strict-owner-mode"
            or command.get("entryPackage") is not None
            or command.get("argvSha256")
            != hashlib.sha256(
                json.dumps(argv, separators=(",", ":")).encode()
            ).hexdigest()
            or not isinstance(command.get("executableSha256"), str)
            or not re.fullmatch(r"[0-9a-f]{64}", command["executableSha256"])
            or type(command.get("executableBytes")) is not int
            or not 0 < command["executableBytes"] <= 256 * 1024**2
            or command.get("executableKind") not in {"elf", "script", "regular"}
        ):
            return False
    if not browser_e2e:
        runner = proof["runnerProvenance"]
        executed = steps[7]["command"]
        package = receipt.get("package")
        producer = package.get("toolProvenance") if type(package) is dict else None
        shared = (
            "package",
            "version",
            "registry",
            "url",
            "crateSha256",
            "publishedCargoLockSha256",
        )
        if (
            runner["binarySha256"] != executed["executableSha256"]
            or runner["binaryIdentity"]["bytes"] != executed["executableBytes"]
            or type(producer) is not dict
            or any(
                type(producer.get(key)) is not str or producer[key] != runner[key]
                for key in shared
            )
        ):
            return False
    return valid_browser_package(
        package_manifest,
        package_files,
        receipt,
        job,
        harness,
        expected_inputs,
        expected_tree,
    )


def valid_sdk_lockfiles_receipt(
    report, receipt, job, harness, *, expected_inputs, expected_tree, outputs
):
    """Independently bind the preparation outputs; never credit conformance."""
    try:
        from scripts.ci_sdk_lockfiles import (
            LOCKS,
            ORIGINAL_LOCKS,
            STAGES,
            commands,
            lock_metadata,
        )
    except ModuleNotFoundError:
        from ci_sdk_lockfiles import (
            LOCKS,
            ORIGINAL_LOCKS,
            STAGES,
            commands,
            lock_metadata,
        )
    receipt_keys = {
        "schemaVersion",
        "runtime_profile",
        "status",
        "code",
        "conformanceProof",
        "releaseProof",
        "publication",
        "services",
        "cleanupVerified",
        "sourceHeld",
        "source_commit",
        "source_tree",
        "harness_commit",
        "run_id",
        "inputs",
        "inputSetSha256",
        "originalLocks",
        "generatedLocks",
        "steps",
    }
    if (
        not isinstance(receipt, dict)
        or set(receipt) != receipt_keys
        or job.get("mode") != "sdk-lockfiles"
        or json.loads(job["specs"]) != ["sdk-lockfiles"]
        or any(
            job.get(key)
            for key in (
                "preparation_id",
                "prepared_run_id",
                "runtime_seed",
                "capacity_configuration",
                "case_title",
            )
        )
        or report.get("runtime_profile") != "sdk-lockfiles"
        or report.get("results")
        != [{"suite": "sdk-lockfiles", "exit_code": 0, "failure_code": None}]
        or receipt.get("schemaVersion") != 1
        or receipt.get("status") != "passed"
        or receipt.get("code") is not None
        or receipt.get("runtime_profile") != "sdk-lockfiles"
        or receipt.get("source_commit") != job["source"]
        or receipt.get("source_tree") != expected_tree
        or receipt.get("harness_commit") != harness
        or str(receipt.get("run_id")) != str(job["run_id"])
        or receipt.get("conformanceProof") is not False
        or receipt.get("releaseProof") is not False
        or receipt.get("publication") is not False
        or receipt.get("services") != {}
        or receipt.get("cleanupVerified") is not True
        or receipt.get("sourceHeld") is not True
        or not expected_inputs
        or receipt.get("inputs") != expected_inputs
        or receipt.get("inputSetSha256")
        != hashlib.sha256(
            json.dumps(expected_inputs, sort_keys=True).encode()
        ).hexdigest()
        or not all(name in expected_inputs for name in ORIGINAL_LOCKS)
        or receipt.get("originalLocks")
        != {name: expected_inputs.get(name) for name in LOCKS}
        or set(outputs) != set(LOCKS)
    ):
        return False
    try:
        metadata = {name: lock_metadata(data) for name, data in outputs.items()}
    except (ValueError, RuntimeError, TypeError):
        return False
    if receipt.get("generatedLocks") != metadata:
        return False
    steps = receipt.get("steps")
    expected_commands = [
        ["rustup", "toolchain", "install", "1.98.1", "--profile", "minimal"],
        *commands(),
    ]
    if (
        not isinstance(steps, list)
        or len(steps) != 5
        or any(not isinstance(row, dict) for row in steps)
        or [row.get("stage") for row in steps] != ["rust-toolchain", *STAGES]
    ):
        return False
    for index, (row, argv) in enumerate(zip(steps, expected_commands)):
        command = row.get("command")
        if (
            set(row)
            != {
                "stage",
                "status",
                "started",
                "returncode",
                "terminatedReturncode",
                "elapsedSeconds",
                "command",
            }
            or row.get("status") != "passed"
            or row.get("started") is not True
            or type(row.get("returncode")) is not int
            or row["returncode"] != 0
            or type(row.get("terminatedReturncode")) is not int
            or row["terminatedReturncode"] != 0
            or type(row.get("elapsedSeconds")) not in (int, float)
            or not math.isfinite(row["elapsedSeconds"])
            or not 0 <= row["elapsedSeconds"] <= (306 if index == 0 else 186)
            or not isinstance(command, dict)
            or set(command)
            != {
                "tool",
                "argvSha256",
                "executableSha256",
                "executableBytes",
                "executableKind",
                "admission",
                "entryPackage",
            }
            or command.get("tool") != ("rustup" if index == 0 else "cargo")
            or command.get("admission") != "strict-owner-mode"
            or command.get("entryPackage") is not None
            or command.get("argvSha256")
            != hashlib.sha256(
                json.dumps(argv, separators=(",", ":")).encode()
            ).hexdigest()
            or not isinstance(command.get("executableSha256"), str)
            or not re.fullmatch(r"[0-9a-f]{64}", command["executableSha256"])
            or type(command.get("executableBytes")) is not int
            or not 0 < command["executableBytes"] <= 256 * 1024**2
            or command.get("executableKind") not in {"elf", "script", "regular"}
        ):
            return False
    return True


def sdk_packaged_fixture_from_git(root: Path, source: str) -> bytes:
    """Read raw immutable JOB-source fixture, never current checkout/receipt data."""
    if not isinstance(source, str) or not re.fullmatch(r"[0-9a-f]{40}", source):
        raise RuntimeError("invalid SDK source identity")
    object_name = source + ":tests/sdk-conformance/fixtures/api-key-foundation.json"
    size = subprocess.check_output(
        ["git", "cat-file", "-s", object_name], cwd=root, text=True, timeout=15
    ).strip()
    if not re.fullmatch(r"[0-9]{1,12}", size) or not 0 < int(size) <= 64 * 1024**2:
        raise RuntimeError("SDK fixture source bound")
    raw = subprocess.check_output(
        ["git", "cat-file", "blob", object_name], cwd=root, timeout=15
    )
    if len(raw) != int(size):
        raise RuntimeError("SDK fixture source changed")
    return raw


def valid_sdk_conformance_receipt(
    report: dict,
    sdk: dict,
    job: dict,
    harness: str,
    *,
    trust: dict,
    expected_inputs: dict,
    expected_packaged_fixture: bytes,
) -> bool:
    """Require the exact reviewed plan, immutable candidate inputs and every stage."""
    try:
        from scripts.ci_sdk_conformance import (
            LOCKS,
            LIBRARY_UNIT_MANIFESTS,
            library_unit_command,
        )
    except ModuleNotFoundError:
        from ci_sdk_conformance import (
            LOCKS,
            LIBRARY_UNIT_MANIFESTS,
            library_unit_command,
        )
    if (
        json.loads(job["specs"]) != ["sdk-conformance"]
        or report.get("runtime_profile") != "sdk-conformance"
        or report.get("results")
        != [
            {
                "suite": "sdk-conformance",
                "exit_code": 0,
                "failed_stage": None,
                "failure_code": None,
            }
        ]
        or not isinstance(sdk, dict)
        or sdk.get("status") != "passed"
        or sdk.get("source_commit") != job["source"]
        or sdk.get("harness_commit") != harness
        or str(sdk.get("run_id")) != str(job["run_id"])
        or sdk.get("publication") is not False
        or sdk.get("services") != {}
        or any(
            sdk.get(key) is not True
            for key in ("cleanupVerified", "loadIdentityVerified", "sourceHeld")
        )
        or not expected_inputs
        or sdk.get("inputs") != expected_inputs
        or sdk.get("inputSetSha256")
        != hashlib.sha256(
            json.dumps(expected_inputs, sort_keys=True).encode()
        ).hexdigest()
        or not all(name in expected_inputs for name in LOCKS)
        or sdk.get("locks") != {name: expected_inputs[name] for name in LOCKS}
    ):
        return False
    stages = [
        "rust-toolchain",
        "python-environment",
        "node-dependencies",
        "python-dependencies",
        *LIBRARY_UNIT_MANIFESTS,
        "napi-build",
        "python-binding-build",
        "sdk-facade-build",
        "napi-load",
        "python-load",
        "real-conformance",
    ]
    steps = sdk.get("steps")
    if (
        not isinstance(steps, list)
        or not all(isinstance(row, dict) for row in steps)
        or [row.get("stage") for row in steps] != stages
        or any(
            row.get("status") != "passed"
            or type(row.get("returncode")) is not int
            or row["returncode"] != 0
            or row.get("terminatedReturncode") != 0
            or type(row.get("elapsedSeconds")) not in (int, float)
            or not math.isfinite(row["elapsedSeconds"])
            or row["elapsedSeconds"] < 0
            for row in steps
        )
    ):
        return False
    for step in steps:
        if step["stage"] not in LIBRARY_UNIT_MANIFESTS:
            continue
        unit, command = step.get("unitTests"), step.get("command")
        expected_argv = hashlib.sha256(
            json.dumps(
                library_unit_command(step["stage"]), separators=(",", ":")
            ).encode()
        ).hexdigest()
        if (
            not isinstance(unit, dict)
            or type(unit.get("passed")) is not int
            or unit["passed"] <= 0
            or any(
                type(unit.get(key)) is not int or unit[key] != 0
                for key in ("failed", "ignored", "measured", "filteredOut")
            )
            or step.get("started") is not True
            or not isinstance(command, dict)
            or command.get("tool") != "cargo"
            or command.get("admission") != "strict-owner-mode"
            or command.get("argvSha256") != expected_argv
            or not isinstance(command.get("executableSha256"), str)
            or not re.fullmatch(r"[0-9a-f]{64}", command["executableSha256"])
        ):
            return False
    gate, artifacts, dist = sdk.get("gate"), sdk.get("artifacts"), sdk.get("dist")
    if (
        not isinstance(gate, dict)
        or not isinstance(artifacts, dict)
        or not isinstance(dist, dict)
    ):
        return False
    plan = trust["plan"]
    rows, launches = gate.get("conformance"), gate.get("actualLaunches")
    expected_rows = [
        {
            "capability": row["capability"],
            "language": row["language"],
            "fixtureSha256": row["fixtureSha256"],
            "vectors": row["vectors"],
            "status": "passed",
        }
        for row in plan
    ]

    def digest(value):
        return isinstance(value, str) and re.fullmatch(r"[0-9a-f]{64}", value)

    packaged = gate.get("packagedSdkV1")
    if (
        not isinstance(packaged, dict)
        or packaged.get("status") != "passed"
        or packaged.get("entrypoint") != "openmates/sdk/v1"
        or packaged.get("fixtureSha256")
        != trust["contracts"].get(
            "tests/sdk-conformance/fixtures/api-key-foundation.json"
        )
        or type(packaged.get("vectorCount")) is not int
        or packaged["vectorCount"] != 23
        or not digest(packaged.get("artifactSha256"))
        or not digest(packaged.get("vectorIdsSha256"))
        or not isinstance(artifacts.get("npm"), dict)
        or packaged.get("nativeSha256") != artifacts["npm"].get("sha256")
        or packaged.get("ambientSyntheticCliStateAccess") is not False
        or packaged.get("cliLauncherObserved") is not False
        or packaged.get("explicitFixtureCredentials") is not True
    ):
        return False
    fixture_path = "tests/sdk-conformance/fixtures/api-key-foundation.json"
    if (
        not isinstance(expected_packaged_fixture, bytes)
        or len(expected_packaged_fixture) > 64 * 1024**2
        or hashlib.sha256(expected_packaged_fixture).hexdigest()
        != trust["contracts"].get(fixture_path)
        or hashlib.sha256(expected_packaged_fixture).hexdigest()
        != expected_inputs.get(fixture_path)
    ):
        return False
    try:
        ordered_ids = [
            row["id"]
            for row in json.loads(expected_packaged_fixture)["capabilities"][
                "sdk.configuration"
            ]["vectors"]
        ]
    except (KeyError, TypeError, ValueError):
        return False
    packaged_plan = [
        row
        for row in plan
        if row.get("capability") == "sdk.configuration" and row.get("language") == "npm"
    ]
    if (
        len(ordered_ids) != 23
        or any(
            not isinstance(value, str)
            or not re.fullmatch(r"[A-Za-z0-9._:-]{1,160}", value)
            for value in ordered_ids
        )
        or len(set(ordered_ids)) != 23
        or len(packaged_plan) != 1
        or packaged_plan[0].get("fixture") != fixture_path
        or packaged_plan[0].get("fixtureSha256") != trust["contracts"].get(fixture_path)
        or packaged_plan[0].get("vectors") != sorted(ordered_ids)
        or packaged.get("vectorIdsSha256")
        != hashlib.sha256(
            json.dumps(ordered_ids, separators=(",", ":")).encode()
        ).hexdigest()
    ):
        return False
    return (
        gate.get("plan") == plan
        and rows == expected_rows
        and gate.get("matrixSha256")
        == trust["contracts"]["config/sdk-capabilities.json"]
        and gate.get("trustedProgramsSha256")
        == hashlib.sha256(
            json.dumps(trust["programs"], sort_keys=True).encode()
        ).hexdigest()
        and gate.get("openGapCount") == len(trust["gaps"])
        and gate.get("releaseEligible") is (not trust["gaps"])
        and gate.get("realRunCount") == len(plan)
        and gate.get("vectorOutcomeCount") == sum(len(row["vectors"]) for row in plan)
        and isinstance(launches, list)
        and len(launches) == len(plan)
        and all(
            isinstance(value, dict)
            and value.get("capability") == row["capability"]
            and value.get("language") == row["language"]
            and value.get("status") == "passed"
            and digest(value.get("commandSha256"))
            for value, row in zip(launches, plan)
        )
        and set(artifacts) == {"npm", "python"}
        and all(
            isinstance(value, dict)
            and value.get("elf") == "linux-x64"
            and digest(value.get("sha256"))
            and type(value.get("nlink")) is int
            and value["nlink"] == 1
            and all(
                type(value.get(key)) is int
                for key in (
                    "device",
                    "inode",
                    "uid",
                    "mode",
                    "mtimeNs",
                    "ctimeNs",
                    "bytes",
                )
            )
            and value["bytes"] > 64
            and not value["mode"] & 0o002
            for value in artifacts.values()
        )
        and "frontend/packages/openmates-cli/dist/sdk-entry.js" in dist
        and all(
            isinstance(name, str)
            and name.startswith("frontend/packages/openmates-cli/dist/")
            and ".." not in Path(name).parts
            and digest(value)
            for name, value in dist.items()
        )
    )


def valid_e2e_case_coverage(report: dict, job: dict) -> bool:
    """A filtered green run covers one case and cannot credit a whole spec."""
    selected_case = job.get("case_title") or ""
    expected_scope = "single-case" if selected_case else "full-spec"
    results = report.get("results")
    if (
        report.get("case_title", "") != selected_case
        or report.get("coverage_scope", "full-spec") != expected_scope
    ):
        return False
    if not selected_case:
        return True
    if not (
        isinstance(results, list) and len(results) == 1 and isinstance(results[0], dict)
    ):
        return False
    item = results[0]
    stats = item.get("stats")
    return (
        item.get("case_title") == selected_case
        and item.get("reported_case_title") == selected_case
        and item.get("coverage_scope") == "single-case"
        and item.get("coverage_complete") is True
        and isinstance(stats, dict)
        and all(
            type(stats.get(name, 0)) is int and stats.get(name, 0) >= 0
            for name in ("expected", "unexpected", "flaky", "skipped")
        )
        and sum(stats.get(name, 0) for name in ("expected", "unexpected", "flaky")) == 1
        and stats.get("skipped", 0) == 0
    )


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
        result["visual_smoke"] = verify_capture(
            captures[0].parent, json.loads(job["specs"])
        )
    paths = list(directory.rglob("ci-cleanup.json"))
    cleanup = (
        json.loads(paths[0].read_text()) if len(paths) == 1 else result.get("cleanup")
    )
    valid = bool(
        cleanup
        and str(cleanup.get("run_id")) == str(job["run_id"])
        and cleanup.get("harness_commit") == result.get("harness_commit")
        and cleanup.get("containers_remaining") == 0
        and cleanup.get("volumes_remaining") == 0
        and cleanup.get("private_account_files_removed") is True
        and not cleanup.get("errors")
    )
    result.update(cleanup=cleanup, cleanup_verified=valid)
    if job["state"] == "success" and not valid:
        label = "Backend diagnostic" if job.get("mode") == "backend-probe" else "E2E"
        raise RuntimeError(
            f"Green {label} lacks verified run-bound account/container/volume cleanup"
        )
    return result


def attach_visual_evidence(result, directory):
    # Collect immutable delivery obligations on both green and failed retrievals.
    # Upload is an explicit separate command: it cannot change the test verdict.
    try:
        from scripts.codex_evidence import prepare
    except ModuleNotFoundError:
        from codex_evidence import prepare
    result["codex_evidence"] = str(prepare(directory, result))
    result["codex_evidence_command"] = (
        f"python3 scripts/codex_evidence.py {directory} --upload"
    )
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
    diagnostic_reserve = (
        260 * 1024**2
        if job.get("mode") == "rust-native-dev"
        else 512 * 1024
        if (job.get("mode") == "rust-wasm" or _browser_package_job(job))
        else 0
    )
    with reserve(
        root,
        MAX_ARCHIVE + MAX_EXPANDED + diagnostic_reserve,
        min_free=RESERVE,
        max_used_percent=100,
        operation=f"ci-result:{job['id']}",
    ):
        return _fetch_reserved(github, job, root)


def _fetch_reserved(github, job: dict, root: Path) -> dict:
    destination = root / "test-results/ci-runs" / job["id"]
    receipt = destination / "receipt.json"
    if receipt.is_file():
        cached = json.loads(receipt.read_text())
        if (
            job.get("state") == "success"
            and job.get("mode") == "selfhost"
            and json.loads(job["specs"]) != ["selfhost-smoke.spec.ts"]
        ):
            expected_harness = (
                job.get("preparation_harness_commit")
                or github.request(f"repos/{github.repo}/actions/runs/{job['run_id']}")[
                    "head_sha"
                ]
            )
            if cached.get(
                "coverage_scope"
            ) != "recipe-target" or not valid_selfhost_result(
                cached.get("report", {}), job, root, expected_harness
            ):
                raise RuntimeError(
                    "Cached self-host scope lacks exact complete recipe evidence"
                )
        if job.get("mode") == "rust-native-dev":
            try:
                from scripts import ci_native_dev as native
            except ModuleNotFoundError:
                import ci_native_dev as native
            expected_harness = github.request(
                f"repos/{github.repo}/actions/runs/{job['run_id']}"
            )["head_sha"]
            native.validate_result(
                cached["native_build"],
                job,
                expected_harness,
                native.sdk.git(root, "rev-parse", job["source"] + "^{tree}"),
                native.source_inputs_from_git(root, job["source"]),
                native.sdk.regular(destination / "openmates", native.MAX_BINARY),
                expected_supervisor=native.sdk.sha(
                    subprocess.check_output(
                        [
                            "git",
                            "show",
                            expected_harness + ":scripts/ci_native_supervisor.py",
                        ],
                        cwd=root,
                        timeout=15,
                    )
                ),
            )
            return cached
        return attach_visual_evidence(
            attach_cleanup(cached, job, destination), destination
        )
    if not job["run_id"] or job["state"] not in ("success", "failure", "cancelled"):
        raise RuntimeError("CI job has no terminal result yet")
    run = github.request(f"repos/{github.repo}/actions/runs/{job['run_id']}")
    runner_jobs = github.request(
        f"repos/{github.repo}/actions/runs/{job['run_id']}/jobs?per_page=100"
    )["jobs"]
    dedicated_capacity = bool(
        job.get("capacity_configuration")
        and json.loads(job.get("specs", "[]")) == ["storage-capacity-target.spec.ts"]
    )
    if dedicated_capacity:
        try:
            from scripts.ci_capacity_config import validate_configuration
        except ModuleNotFoundError:
            from ci_capacity_config import validate_configuration
        validate_configuration(
            json.loads(job["capacity_configuration"]), source=job["source"], target=True
        )

    def admitted_runner(entry):
        labels = set(entry.get("labels", []))
        if dedicated_capacity:
            return {"self-hosted", "Linux", "X64", "openmates-capacity"}.issubset(
                labels
            )
        if job.get("mode") == "rust-native-dev":
            return (
                "ubuntu-24.04-arm" in labels
                and "self-hosted" not in labels
                and entry.get("runner_name", "").startswith("GitHub Actions")
            )
        return "ubuntu-latest" in labels and entry.get("runner_name", "").startswith(
            "GitHub Actions"
        )

    if not runner_jobs or any(not admitted_runner(entry) for entry in runner_jobs):
        raise RuntimeError(
            "Test evidence did not execute exclusively on admitted isolated runners"
        )
    if job.get("mode") == "rust-native-dev" and job.get("state") == "success":
        try:
            from scripts.ci_native_dev import retrieve
        except ModuleNotFoundError:
            from ci_native_dev import retrieve
        return retrieve(root, job, run["head_sha"], destination)
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
        expected_harness_commit = (
            job.get("preparation_harness_commit") or run["head_sha"]
        )
        if report and (
            report.get("harness_commit") != expected_harness_commit
            or report.get("proof_profile", "") != job.get("proof_profile", "")
        ):
            raise RuntimeError(
                "CI harness or requested proof profile identity mismatch"
            )
        if (
            job["state"] == "success"
            and job.get("mode") == "selfhost"
            and json.loads(job["specs"]) != ["selfhost-smoke.spec.ts"]
        ):
            if not valid_selfhost_result(report, job, root, expected_harness_commit):
                raise RuntimeError(
                    "Self-host scope lacks exact complete recipe evidence"
                )
        if job["state"] == "success" and job.get("mode") in (
            "component",
            "e2e",
            "visual-smoke",
        ):
            if not green_e2e_source_and_egress_verified(
                environment_data,
                job,
                expected_harness_commit=expected_harness_commit,
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
                raise RuntimeError(
                    "Result case coverage differs from the requested filter"
                )
            if job.get("mode") == "component" and (
                report.get("runtime_profile") != "component"
                or environment_data.get("frontend", {}).get("renderer") != "vite-dev"
            ):
                raise RuntimeError(
                    "Component proof lacks the GitHub-hosted Vite runtime evidence"
                )
        if job["state"] == "success" and job.get("mode") == "backend-probe":
            if not valid_backend_probe_receipt(
                report,
                environment_data,
                job,
                expected_harness_commit=expected_harness_commit,
            ):
                raise RuntimeError(
                    "Backend diagnostic lacks exact isolated health evidence"
                )
        browser_package_verified = False
        browser_package_prefix = ""
        browser_package_job = _browser_package_job(job)
        wasm_receipts = (
            list(extracted.rglob("ci-rust-wasm.json")) if browser_package_job else []
        )
        e2e_wasm_receipt = (
            json.loads(wasm_receipts[0].read_text()) if len(wasm_receipts) == 1 else {}
        )
        if (job["state"] == "success" and job.get("mode") == "rust-wasm") or (
            browser_package_job
            and (
                job["state"] == "success" or e2e_wasm_receipt.get("status") == "passed"
            )
        ):
            try:
                from scripts.ci_rust_wasm import (
                    WASM_NAME,
                    BINDGEN_VERSION,
                    source_inputs_from_git,
                    package_inventory,
                    metadata,
                )
            except ModuleNotFoundError:
                from ci_rust_wasm import (
                    WASM_NAME,
                    BINDGEN_VERSION,
                    source_inputs_from_git,
                    package_inventory,
                    metadata,
                )
            receipts = list(extracted.rglob("ci-rust-wasm.json"))
            wasm_receipt = (
                json.loads(receipts[0].read_text()) if len(receipts) == 1 else {}
            )
            roots = [path for path in extracted.rglob("rust-wasm") if path.is_dir()]
            wasm, manifest_bytes, generated_files = b"", b"", {}
            if len(roots) == 1:
                try:
                    from scripts.ci_sdk_conformance import (
                        regular as sdk_regular_package_file,
                    )
                except ModuleNotFoundError:
                    from ci_sdk_conformance import regular as sdk_regular_package_file
                package_root = roots[0] / "package"
                package_listing = package_inventory(
                    package_root,
                    wasm_receipt.get("inputs", {}),
                    metadata_profile=metadata.targets(json.loads(job["specs"])),
                )
                allowed = {
                    WASM_NAME,
                    "package-manifest.json",
                    *("package/" + row["path"] for row in package_listing["files"]),
                }
                expected_directories = {package_root}
                for row in package_listing["files"]:
                    current = (package_root / row["path"]).parent
                    while current != package_root:
                        expected_directories.add(current)
                        current = current.parent
                inventory = {}
                for path in roots[0].rglob("*"):
                    if path in expected_directories:
                        continue
                    data = sdk_regular_package_file(path)
                    inventory[path.relative_to(roots[0]).as_posix()] = data
                if set(inventory) == allowed:
                    browser_package_prefix = roots[0].relative_to(extracted).as_posix()
                    wasm = inventory[WASM_NAME]
                    manifest_bytes = inventory["package-manifest.json"]
                    generated_files = {
                        name.removeprefix("package/"): data
                        for name, data in inventory.items()
                        if name.startswith("package/")
                    }

            expected_tree = subprocess.check_output(
                ["git", "rev-parse", job["source"] + "^{tree}"],
                cwd=root,
                text=True,
                timeout=15,
            ).strip()
            import tomllib

            browser_lock = subprocess.check_output(
                [
                    "git",
                    "show",
                    job["source"] + ":packages/openmates-browser-bindings/Cargo.lock",
                ],
                cwd=root,
                timeout=15,
            )
            locked_versions = {
                row.get("version")
                for row in tomllib.loads(browser_lock.decode()).get("package", [])
                if row.get("name") == "wasm-bindgen"
            }
            if locked_versions != {BINDGEN_VERSION}:
                raise RuntimeError(
                    "Rust browser package tool does not match immutable app lock"
                )
            if not valid_rust_wasm_receipt(
                report,
                wasm_receipt,
                job,
                expected_harness_commit,
                expected_inputs=source_inputs_from_git(
                    root,
                    job["source"],
                    metadata_profile=metadata.targets(json.loads(job["specs"])),
                    first_session_profile=metadata.first_session_targets(
                        json.loads(job["specs"])
                    ),
                    native_recovery_profile=metadata.native_recovery_targets(
                        json.loads(job["specs"])
                    ),
                    activechat_profile=metadata.activechat_targets(
                        json.loads(job["specs"])
                    ),
                    new_chat_profile=metadata.new_chat_targets(
                        json.loads(job["specs"])
                    ),
                ),
                expected_tree=expected_tree,
                artifact=wasm,
                package_manifest=manifest_bytes,
                package_files=generated_files,
            ):
                raise RuntimeError(
                    "Rust WASM compilation lacks exact locked source/output/command/cleanup evidence"
                )
            browser_package_verified = True
        if job["state"] == "success" and job.get("mode") == "sdk-lockfiles":
            try:
                from scripts.ci_sdk_lockfiles import LOCKS, source_inputs_from_git
            except ModuleNotFoundError:
                from ci_sdk_lockfiles import LOCKS, source_inputs_from_git
            receipts = list(extracted.rglob("ci-sdk-lockfiles.json"))
            lock_receipt = (
                json.loads(receipts[0].read_text()) if len(receipts) == 1 else {}
            )
            roots = [path for path in extracted.rglob("sdk-lockfiles") if path.is_dir()]
            lock_outputs = {}
            if len(roots) == 1:
                inventory = {
                    path.relative_to(roots[0]).as_posix(): path
                    for path in roots[0].rglob("*")
                    if path.is_file()
                }
                if set(inventory) == set(LOCKS):
                    lock_outputs = {
                        name: path.read_bytes() for name, path in inventory.items()
                    }
            expected_tree = subprocess.check_output(
                ["git", "rev-parse", job["source"] + "^{tree}"],
                cwd=root,
                text=True,
                timeout=15,
            ).strip()
            if not valid_sdk_lockfiles_receipt(
                report,
                lock_receipt,
                job,
                expected_harness_commit,
                expected_inputs=source_inputs_from_git(root, job["source"]),
                expected_tree=expected_tree,
                outputs=lock_outputs,
            ):
                raise RuntimeError(
                    "SDK lock preparation lacks exact source/output/command/cleanup evidence"
                )
        if job["state"] == "success" and job.get("mode") == "sdk-conformance":
            sdk_paths = list(extracted.rglob("ci-sdk-conformance.json"))
            sdk_data = (
                json.loads(sdk_paths[0].read_text()) if len(sdk_paths) == 1 else {}
            )
            try:
                from scripts.ci_sdk_conformance import (
                    load_trust_for_source,
                    source_inputs_from_git,
                )
            except ModuleNotFoundError:
                from ci_sdk_conformance import (
                    load_trust_for_source,
                    source_inputs_from_git,
                )
            if not valid_sdk_conformance_receipt(
                report,
                sdk_data,
                job,
                expected_harness_commit,
                trust=load_trust_for_source(
                    root, job["source"], harness=expected_harness_commit
                ),
                expected_inputs=source_inputs_from_git(root, job["source"]),
                expected_packaged_fixture=sdk_packaged_fixture_from_git(
                    root, job["source"]
                ),
            ):
                raise RuntimeError(
                    "Green SDK job lacks exact library/vector or cleanup evidence"
                )
        if job["state"] == "success" and job.get("mode") == "artifact":
            if (
                report.get("runtime_profile") != "artifact"
                or report.get("artifact_shared_dev_rejected") is not True
                or sorted(item.get("spec", "") for item in report["results"])
                != sorted(json.loads(job["specs"]))
            ):
                raise RuntimeError(
                    "Artifact proof lacks exact inventory or isolated runtime evidence"
                )
        private_diagnostics = None
        if job.get("mode") == "rust-wasm" or browser_package_job:
            receipts = list(extracted.rglob("ci-rust-wasm.json"))
            wasm_receipt = (
                json.loads(receipts[0].read_text()) if len(receipts) == 1 else {}
            )
            descriptor = wasm_receipt.get("diagnostics")
            if descriptor is not None and (
                wasm_receipt.get("status") != "failed"
                or wasm_receipt.get("compilationProof") is not False
                or job["state"] == "success"
            ):
                raise RuntimeError(
                    "Rust WASM diagnostic must not credit successful compilation"
                )
            expected_tree = subprocess.check_output(
                ["git", "rev-parse", job["source"] + "^{tree}"],
                cwd=root,
                text=True,
                timeout=15,
            ).strip()
            if descriptor is not None and (
                wasm_receipt.get("source_commit") != job["source"]
                or wasm_receipt.get("source_tree") != expected_tree
                or wasm_receipt.get("harness_commit") != expected_harness_commit
                or str(wasm_receipt.get("run_id")) != str(job["run_id"])
            ):
                raise RuntimeError(
                    "Rust WASM private diagnostic receipt identity mismatch"
                )
            private_diagnostics = fetch_rust_wasm_diagnostic(
                github,
                job,
                root,
                artifacts,
                descriptor,
                expected_harness_commit,
                expected_tree,
                extracted / "rust-wasm-private",
            )
        result = {
            "id": job["id"],
            "source_commit": job["source"],
            "run_id": job["run_id"],
            "state": job["state"],
            "mode": job["mode"],
            "selected_specs": json.loads(job["specs"]),
            "selected_case_title": job.get("case_title") or "",
            "coverage_scope": (
                "recipe-target"
                if job.get("mode") == "selfhost"
                and json.loads(job["specs"]) != ["selfhost-smoke.spec.ts"]
                else "single-case"
                if job.get("case_title")
                else "full-spec"
            ),
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
            "preparation": {
                "request_id": job.get("preparation_id"),
                "run_id": job.get("prepared_run_id"),
                "key": job.get("preparation_key"),
            },
            "environment": environment_data,
            "artifact_id": artifact["id"],
            "artifact_url": f"{job['url']}/artifacts/{artifact['id']}",
            "directory": str(destination),
        }
        if browser_package_verified:
            result["browser_package"] = {
                "status": "verified",
                "manifest": browser_package_prefix + "/package-manifest.json",
                "directory": browser_package_prefix + "/package",
                "manifestSha256": wasm_receipt["package"]["manifestSha256"],
                "inventorySha256": wasm_receipt["package"]["inventorySha256"],
                "source_commit": job["source"],
                "browserRuntimeProof": False,
            }
        if browser_package_verified and job.get("mode") == "rust-wasm":
            proof = wasm_receipt["workerProof"]
            result["dedicated_worker_tests"] = {
                "status": "verified",
                "workerRuntimeProof": True,
                "browserRuntimeProof": False,
                "context": "dedicated-worker",
                "passed": proof["passed"],
                "requiredTests": proof["requiredTests"],
                "testWasmSha256": proof["testWasmSha256"],
                "controllerSha256": proof["controllerSha256"],
                "playwright": proof["playwright"],
            }
        if private_diagnostics is not None:
            result["private_diagnostics"] = private_diagnostics
        attach_cleanup(result, job, extracted)
        (extracted / "receipt.json").write_text(json.dumps(result, indent=2))
        extracted.rename(destination)
    return attach_visual_evidence(result, destination)
