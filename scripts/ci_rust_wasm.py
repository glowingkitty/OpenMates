"""Fixed Rust/WASM compilation gate; no browser runtime or SDK conformance proof."""
from __future__ import annotations

import json
import math
import os
from pathlib import Path
import platform
import re
import shutil
import stat
import subprocess
import tempfile
import time
import tomllib

try:
    from scripts import ci_sdk_conformance as sdk
    from scripts.ci_sdk_lockfiles import ROOTS, LOCKS, owned, snapshot, validate_manifests
except ModuleNotFoundError:
    import ci_sdk_conformance as sdk
    from ci_sdk_lockfiles import ROOTS, LOCKS, owned, snapshot, validate_manifests

TARGET = "rust-wasm"
BUDGET = 2700
WASM_NAME = "openmates_browser_bindings.wasm"
WASM_PATH = "wasm32-unknown-unknown/release/" + WASM_NAME
STAGES = ("rust-toolchain", "wasm-target", "wasm-build")
DIAGNOSTIC_LIMIT = 128 * 1024
DIAGNOSTIC_ARTIFACT = "isolated-rust-wasm-private-diagnostics"
FAILURES = frozenset({"admission", "identity", "source", "deadline", "disk", "toolchain", "compile", "outputs", "cleanup", "unclassified"})


def validate_targets(targets):
    sdk.require(targets == [TARGET], "admission")


def commands():
    return [["rustup", "toolchain", "install", "1.98.1", "--profile", "minimal"],
            ["rustup", "target", "add", "--toolchain", "1.98.1", "wasm32-unknown-unknown"],
            ["cargo", "+1.98.1", "build", "--locked", "--release", "--manifest-path",
             "packages/openmates-browser-bindings/Cargo.toml", "--target", "wasm32-unknown-unknown", "--lib"]]


def source_inputs_from_git(root, source):
    sdk.require(isinstance(source, str) and re.fullmatch(r"[0-9a-f]{40}", source), "identity")
    listing = subprocess.check_output(["git", "ls-tree", "-r", "-z", source, "--", *ROOTS], cwd=root, timeout=15)
    entries = []
    for raw in listing.split(b"\0"):
        if not raw:
            continue
        header, raw_name = raw.split(b"\t", 1)
        name = raw_name.decode()
        if not owned(name):
            continue
        mode, kind, oid = header.decode().split()
        sdk.require(mode in {"100644", "100755"} and kind == "blob", "source")
        entries.append((name, oid))
    sdk.require(0 < len(entries) <= 5000, "source")
    request = "".join(oid + "\n" for _, oid in entries).encode()
    sizes = subprocess.run(["git", "cat-file", "--batch-check"], cwd=root, input=request,
                           capture_output=True, check=True, timeout=30).stdout.splitlines()
    sdk.require(len(sizes) == len(entries), "source")
    total = 0
    for line, (_, oid) in zip(sizes, entries):
        actual, kind, size = line.decode().split()
        sdk.require(actual == oid and kind == "blob" and 0 <= int(size) <= 64 * 1024**2, "source")
        total += int(size)
    sdk.require(total <= 256 * 1024**2, "source")
    blobs = subprocess.run(["git", "cat-file", "--batch"], cwd=root, input=request,
                           capture_output=True, check=True, timeout=60).stdout
    sdk.require(len(blobs) <= total + len(entries) * 128, "source")
    offset, rows = 0, {}
    for name, oid in entries:
        end = blobs.index(b"\n", offset)
        actual, kind, size = blobs[offset:end].decode().split()
        sdk.require(actual == oid and kind == "blob", "source")
        start = end + 1
        offset = start + int(size) + 1
        sdk.require(offset <= len(blobs) and blobs[offset - 1:offset] == b"\n", "source")
        rows[name] = sdk.sha(blobs[start:offset - 1])
    sdk.require(offset == len(blobs), "source")
    sdk.require(all(root + "/Cargo.toml" in rows and root + "/src/lib.rs" in rows
                    for root in (ROOTS[0], ROOTS[1], ROOTS[3]))
                and ROOTS[2] + "/src/main.rs" in rows
                and all(name in rows for name in LOCKS), "source")
    return rows


def wasm_metadata(data):
    sdk.require(8 < len(data) <= 128 * 1024**2 and data[:8] == b"\0asm\x01\0\0\0", "outputs")
    return {"name": WASM_NAME, "format": "wasm-v1", "sha256": sdk.sha(data), "bytes": len(data)}


def copy_compiled_wasm(artifact, destination):
    """Cargo may hard-link its build outputs; export a fresh independent inode."""
    source = artifact.lstat()
    data = sdk.regular(artifact, 128 * 1024**2)
    metadata = wasm_metadata(data)
    sdk.require(destination.is_absolute() and destination.parent.resolve() == destination.parent, "outputs")
    fd = os.open(destination, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "wb") as stream:
        os.fchmod(stream.fileno(), 0o600)
        stream.write(data)
        stream.flush()
        copied = os.fstat(stream.fileno())
        sdk.require(stat.S_ISREG(copied.st_mode) and copied.st_uid == os.getuid() and copied.st_nlink == 1
                    and (copied.st_dev, copied.st_ino) != (source.st_dev, source.st_ino), "outputs")
    exported = sdk.regular(destination, 128 * 1024**2)
    sdk.require(wasm_metadata(exported) == metadata
                and sdk.file_identity(source) == sdk.file_identity(artifact.lstat())
                and sdk.file_identity(copied) == sdk.file_identity(destination.lstat()), "outputs")
    return metadata


def retain_failure_diagnostic(private, output, receipt, stage):
    """Keep only the failed stage's bounded tail; account/provider env is absent."""
    sdk.require(stage in STAGES, "compile")
    log = private / (stage + ".log")
    sdk.require(log.resolve() == log, "outputs")
    with os.fdopen(os.open(log, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK), "rb") as stream:
        info = os.fstat(stream.fileno())
        sdk.require(stat.S_ISREG(info.st_mode) and info.st_uid == os.getuid(), "outputs")
        stream.seek(max(0, info.st_size - DIAGNOSTIC_LIMIT))
        tail = stream.read(DIAGNOSTIC_LIMIT)
        sdk.require(sdk.file_identity(info) == sdk.file_identity(os.fstat(stream.fileno()))
                    == sdk.file_identity(log.lstat()), "outputs")
    identity = {"schemaVersion": 1, "source_commit": receipt["source_commit"], "source_tree": receipt["source_tree"],
                "harness_commit": receipt["harness_commit"], "run_id": receipt["run_id"], "stage": stage,
                "path": "cargo-tail.log", "bytes": len(tail), "originalBytes": info.st_size,
                "sha256": sdk.sha(tail), "truncated": info.st_size > len(tail)}
    target = output / "ci-rust-wasm-private"
    sdk.require(not target.exists(), "outputs")
    target.mkdir(mode=0o700)
    with (target / "cargo-tail.log").open("xb") as stream:
        os.fchmod(stream.fileno(), 0o600)
        stream.write(tail)
    sdk.write(target / "identity.json", identity)
    return {"artifactName": DIAGNOSTIC_ARTIFACT, "identity": identity,
            "identitySha256": sdk.sha(sdk.regular(target / "identity.json", 16384)), "publicRawUpload": False}


class WasmCommands(sdk.Commands):
    def run(self, stage, command, **kwargs):
        try:
            return super().run(stage, command, **kwargs)
        finally:
            if self.steps and stage in STAGES:
                self.steps[-1]["command"]["tool"] = "cargo" if stage == "wasm-build" else "rustup"


def run(root, results, *, environ=None):
    ambient = os.environ if environ is None else environ
    output = root / "test-results"
    artifact_dir = output / TARGET
    receipt = {"schemaVersion": 1, "runtime_profile": TARGET, "status": "failed", "code": "admission",
               "compilationProof": False, "browserRuntimeProof": False, "conformanceProof": False,
               "releaseProof": False, "publication": False, "services": {}, "cleanupVerified": False, "sourceHeld": False}
    runner = private = before = source = tree = None
    phase = "admission"
    try:
        sdk.require(ambient.get("GITHUB_ACTIONS") == "true"
                    and ambient.get("RUNNER_ENVIRONMENT") == "github-hosted"
                    and ambient.get("OPENMATES_CI_ISOLATED") == "1"
                    and platform.machine() == "x86_64" and os.sys.platform == "linux", "admission")
        validate_targets(json.loads(ambient.get("CI_SPECS_JSON", "[]")))
        sdk.require(not any(ambient.get(key) for key in ("CI_CASE_TITLE", "CI_PREPARATION_KEY", "CI_PREPARED_RUN_ID",
                    "CI_RUNTIME_SEED", "CI_CAPACITY_CONFIGURATION")), "admission")
        phase = "identity"
        source, tree = sdk.git(root, "rev-parse", "HEAD"), sdk.git(root, "rev-parse", "HEAD^{tree}")
        harness = ambient.get("CI_HARNESS_COMMIT", "")
        sdk.require(source == ambient.get("BUILD_COMMIT_SHA") and tree == ambient.get("CI_CANDIDATE_TREE")
                    and re.fullmatch(r"[0-9a-f]{40}", source) and re.fullmatch(r"[0-9a-f]{40}", harness)
                    and re.fullmatch(r"[0-9]+", ambient.get("GITHUB_RUN_ID", ""))
                    and sdk.git(Path(__file__).resolve().parent.parent, "rev-parse", "HEAD") == harness
                    and subprocess.run(["git", "symbolic-ref", "-q", "HEAD"], cwd=root, capture_output=True, timeout=15).returncode == 1,
                    "identity")
        phase = "deadline"
        start, deadline = float(ambient["CI_RUST_WASM_STARTED_MONOTONIC"]), float(ambient["CI_RUST_WASM_DEADLINE_MONOTONIC"])
        sdk.require(math.isfinite(start) and math.isfinite(deadline) and abs(deadline - start - BUDGET) < 0.000001
                    and start <= time.monotonic() < deadline, "deadline")
        phase = "source"
        before = source_inputs_from_git(root, source)
        sdk.require(snapshot(root, before) == before, "source")
        receipt.update(source_commit=source, source_tree=tree, harness_commit=harness, run_id=ambient["GITHUB_RUN_ID"],
                       inputs=before, inputSetSha256=sdk.sha(json.dumps(before, sort_keys=True).encode()),
                       locks={name: before[name] for name in LOCKS})
        phase = "disk"
        sdk.require(shutil.disk_usage(output).free >= sdk.RESERVE, "disk")
        sdk.require(not artifact_dir.exists(), "outputs")
        private = Path(tempfile.mkdtemp(prefix="rust-wasm-", dir=Path(ambient["RUNNER_TEMP"])))
        os.chmod(private, 0o700)
        work = private / "source"
        work.mkdir(mode=0o700)
        for name, digest in before.items():
            data = sdk.regular(root / name)
            sdk.require(sdk.sha(data) == digest, "source")
            target = work / name
            target.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
            target.write_bytes(data)
        for name in ("home", "tmp"):
            (private / name).mkdir(mode=0o700)
        validate_manifests(work)
        browser = tomllib.loads(sdk.regular(work / ROOTS[-1] / "Cargo.toml").decode())
        sdk.require(browser.get("package", {}).get("name") == "openmates-browser-bindings"
                    and browser.get("lib", {}).get("name", "openmates_browser_bindings") == "openmates_browser_bindings", "source")
        rustup, cargo = shutil.which("rustup"), shutil.which("cargo")
        sdk.require(rustup and cargo, "toolchain")
        env = {"PATH": os.pathsep.join(dict.fromkeys([str(Path(rustup).parent), str(Path(cargo).parent), *os.defpath.split(os.pathsep)])),
               "HOME": str(private / "home"), "TMPDIR": str(private / "tmp"), "LANG": "C.UTF-8", "CI": "true",
               "RUSTUP_HOME": ambient.get("RUSTUP_HOME", str(Path.home() / ".rustup")), "RUSTUP_TOOLCHAIN": "1.98.1",
               "CARGO_HOME": str(private / "cargo"), "CARGO_TARGET_DIR": str(private / "target"),
               "CARGO_BUILD_JOBS": "2", "CARGO_INCREMENTAL": "0", "CARGO_NET_RETRY": "2", "CARGO_HTTP_TIMEOUT": "60"}
        runner = WasmCommands(work, private, env, deadline)
        artifact = private / "target" / WASM_PATH
        sdk.require(not artifact.exists(), "outputs")
        for stage, command, seconds in zip(STAGES, commands(), (300, 300, 1800)):
            phase = "compile" if stage == "wasm-build" else "toolchain"
            sdk.require(snapshot(root, before) == before, "source")
            runner.run(stage, command, seconds=seconds)
            sdk.require(snapshot(root, before) == before, "source")
        phase = "outputs"
        sdk.require(all(sdk.sha(sdk.regular(work / name)) == digest for name, digest in before.items()), "source")
        artifact_dir.mkdir(mode=0o700)
        metadata = copy_compiled_wasm(artifact, artifact_dir / WASM_NAME)
        receipt.update(artifact=metadata, status="passed", code=None)
    except Exception as error:
        receipt.update(status="failed", code=phase if phase in FAILURES else "unclassified")
        if isinstance(error, sdk.Refused) and str(error) in FAILURES:
            receipt["code"] = str(error)
    finally:
        if before is not None:
            try:
                held = (snapshot(root, before) == before and sdk.git(root, "rev-parse", "HEAD") == source
                        and sdk.git(root, "rev-parse", "HEAD^{tree}") == tree)
            except Exception:
                held = False
            receipt["sourceHeld"] = held
            if not held:
                receipt.update(status="failed", code="source")
        receipt["steps"] = runner.steps if runner else []
        if private is not None:
            if receipt["status"] != "passed" and runner and runner.steps:
                try:
                    receipt["diagnostics"] = retain_failure_diagnostic(private, output, receipt, runner.steps[-1]["stage"])
                except Exception:
                    receipt["diagnostics"] = {"classification": "diagnostic_unavailable", "publicRawUpload": False}
            try:
                shutil.rmtree(private)
                receipt["cleanupVerified"] = not private.exists()
            except OSError:
                receipt.update(status="failed", code="cleanup")
        if not receipt["cleanupVerified"]:
            receipt["status"] = "failed"
        if receipt["status"] != "passed" and artifact_dir.exists():
            try:
                shutil.rmtree(artifact_dir)
            except OSError:
                receipt.update(status="failed", code="cleanup", cleanupVerified=False)
        receipt["compilationProof"] = receipt["status"] == "passed"
        try:
            sdk.write(output / "ci-rust-wasm.json", receipt)
        except OSError:
            receipt.update(status="failed", code="outputs", receiptWriteFailed=True, compilationProof=False)
        finally:
            results.append({"suite": TARGET, "exit_code": 0 if receipt["status"] == "passed" else 1,
                            "failure_code": receipt["code"]})
    return receipt
