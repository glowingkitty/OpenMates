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
BROWSER_SPEC = "rust-core-browser-session.spec.ts"
BROWSER_BUDGET = 1800
WASM_NAME = "openmates_browser_bindings.wasm"
WASM_PATH = "wasm32-unknown-unknown/release/" + WASM_NAME
BINDGEN_VERSION = "0.2.129"
PACKAGE_NAME = "openmates_browser"
PACKAGE_FILES = (PACKAGE_NAME + ".js", PACKAGE_NAME + "_bg.wasm", PACKAGE_NAME + ".d.ts", PACKAGE_NAME + "_bg.wasm.d.ts")
STAGES = ("rust-toolchain", "wasm-target", "wasm-build", "bindgen-install", "bindgen-version", "bindgen-package")
STAGE_SECONDS = (300, 300, 1800, 900, 30, 180)
DIAGNOSTIC_LIMIT = 128 * 1024
DIAGNOSTIC_ARTIFACT = "isolated-rust-wasm-private-diagnostics"
FAILURES = frozenset({"admission", "identity", "source", "deadline", "disk", "toolchain", "compile", "packaging", "outputs", "cleanup", "unclassified"})


def validate_targets(targets):
    sdk.require(targets == [TARGET], "admission")


def commands():
    return [["rustup", "toolchain", "install", "1.98.1", "--profile", "minimal"],
            ["rustup", "target", "add", "--toolchain", "1.98.1", "wasm32-unknown-unknown"],
            ["cargo", "+1.98.1", "build", "--locked", "--release", "--manifest-path",
             "packages/openmates-browser-bindings/Cargo.toml", "--target", "wasm32-unknown-unknown", "--lib"],
            ["cargo", "+1.98.1", "install", "wasm-bindgen-cli", "--version", "=" + BINDGEN_VERSION,
             "--locked", "--registry", "crates-io", "--root", ".ci-bindgen", "--target-dir", ".ci-bindgen-target", "--jobs", "2"],
            ["wasm-bindgen", "--version"],
            ["wasm-bindgen", ".ci-packaging/input.wasm", "--target", "web", "--out-dir", ".ci-packaging/pkg", "--out-name", PACKAGE_NAME]]


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


def locked_bindgen_version(work):
    lock = tomllib.loads(sdk.regular(work / ROOTS[-1] / "Cargo.lock").decode())
    versions = {row.get("version") for row in lock.get("package", []) if row.get("name") == "wasm-bindgen"}
    sdk.require(versions == {BINDGEN_VERSION}, "packaging")
    return BINDGEN_VERSION


def package_inventory(folder):
    """Same content inventory schema as build_rust_browser.py; no helper modules."""
    sdk.require(folder.resolve() == folder and folder.is_dir(), "outputs")
    names = {path.name for path in folder.iterdir()}
    sdk.require(set(PACKAGE_FILES[:3]) <= names <= set(PACKAGE_FILES), "outputs")
    rows, total = [], 0
    for name in sorted(names):
        path = folder / name
        raw = sdk.regular(path)
        sdk.require(path.stat().st_nlink == 1 and raw, "outputs")
        if name.endswith(".wasm"):
            sdk.require(raw[:8] == b"\0asm\x01\0\0\0", "outputs")
        else:
            raw.decode("utf-8", errors="strict")
        total += len(raw)
        sdk.require(total <= 128 * 1024**2, "outputs")
        rows.append({"path": name, "sha256": sdk.sha(raw), "rawBytes": len(raw)})
    return {"files": rows, "rawBytes": total,
            "inventorySha256": sdk.sha(json.dumps(rows, sort_keys=True, separators=(",", ":")).encode())}


def installed_bindgen_provenance(private, work):
    name = "wasm-bindgen-cli-" + BINDGEN_VERSION
    sources = list((private / "cargo/registry/src").glob("*/" + name))
    archives = list((private / "cargo/registry/cache").glob("*/" + name + ".crate"))
    sdk.require(len(sources) == len(archives) == 1, "packaging")
    package = tomllib.loads(sdk.regular(sources[0] / "Cargo.toml").decode())
    sdk.require(package.get("package", {}).get("name") == "wasm-bindgen-cli"
                and package["package"].get("version") == BINDGEN_VERSION, "packaging")
    checksum = json.loads(sdk.regular(sources[0] / ".cargo-checksum.json"))["package"]
    archive = sdk.regular(archives[0])
    sdk.require(isinstance(checksum, str) and re.fullmatch(r"[0-9a-f]{64}", checksum)
                and sdk.sha(archive) == checksum, "packaging")
    published_lock = sdk.regular(sources[0] / "Cargo.lock")
    locked = tomllib.loads(published_lock.decode())
    sdk.require(any(row.get("name") == "wasm-bindgen-cli" and row.get("version") == BINDGEN_VERSION
                    for row in locked.get("package", [])), "packaging")
    binary = work / ".ci-bindgen/bin/wasm-bindgen"
    identity = binary.lstat()
    executable = sdk.regular(binary)
    sdk.require(identity.st_mode & 0o111 and identity.st_nlink == 1
                and sdk.file_identity(identity) == sdk.file_identity(binary.lstat()), "packaging")
    return {"package": "wasm-bindgen-cli", "version": BINDGEN_VERSION, "registry": "crates.io",
            "url": "https://crates.io/crates/wasm-bindgen-cli/" + BINDGEN_VERSION,
            "crateSha256": checksum, "publishedCargoLockSha256": sdk.sha(published_lock),
            "binarySha256": sdk.sha(executable),
            "binaryIdentity": {"device": identity.st_dev, "inode": identity.st_ino, "bytes": identity.st_size,
                               "mtimeNs": identity.st_mtime_ns, "ctimeNs": identity.st_ctime_ns,
                               "mode": identity.st_mode, "uid": identity.st_uid, "links": identity.st_nlink}}


def produce_browser_package(runner, private, work, artifact, artifact_dir, receipt):
    """Execute the real installed bindgen producer and inventory its emitted bytes."""
    locked_bindgen_version(work)
    runner.run("bindgen-install", commands()[3], seconds=STAGE_SECONDS[3])
    provenance = installed_bindgen_provenance(private, work)
    runner.env["PATH"] = str(work / ".ci-bindgen/bin") + os.pathsep + runner.env["PATH"]
    version_log = runner.run("bindgen-version", commands()[4], seconds=STAGE_SECONDS[4])
    sdk.require(sdk.regular(version_log, 65536).decode().strip() == "wasm-bindgen " + BINDGEN_VERSION, "packaging")
    pending = work / ".ci-packaging"
    pending.mkdir(mode=0o700)
    generated = pending / "pkg"
    generated.mkdir(mode=0o700)
    raw = copy_compiled_wasm(artifact, pending / "input.wasm")
    sdk.require(raw["sha256"] == receipt["artifact"]["sha256"], "outputs")
    runner.run("bindgen-package", commands()[5], seconds=STAGE_SECONDS[5])
    sdk.require(all(row["command"]["executableSha256"] == provenance["binarySha256"] for row in runner.steps[-2:]), "packaging")
    sdk.require(installed_bindgen_provenance(private, work) == provenance, "packaging")
    inventory = package_inventory(generated)
    exported = artifact_dir / "package"
    exported.mkdir(mode=0o700)
    for row in inventory["files"]:
        data = sdk.regular(generated / row["path"])
        sdk.require(sdk.sha(data) == row["sha256"] and len(data) == row["rawBytes"], "outputs")
        with (exported / row["path"]).open("xb") as stream:
            os.fchmod(stream.fileno(), 0o600)
            stream.write(data)
    sdk.require(package_inventory(exported) == inventory and package_inventory(generated) == inventory, "outputs")
    manifest = {"schemaVersion": 1, "status": "passed", "source_commit": receipt["source_commit"],
                "source_tree": receipt["source_tree"], "harness_commit": receipt["harness_commit"], "run_id": receipt["run_id"],
                "inputs": receipt["inputs"], "inputSetSha256": receipt["inputSetSha256"], "locks": receipt["locks"],
                "target": "wasm32-unknown-unknown", "toolchain": "1.98.1", "inputWasmSha256": raw["sha256"],
                "wasmBindgenVersion": BINDGEN_VERSION, "toolSha256": provenance["binarySha256"],
                "toolProvenance": provenance, "inventory": inventory, "browserRuntimeProof": False,
                "requestedMode": receipt["requestedMode"], "requestedTargets": receipt["requestedTargets"]}
    sdk.write(artifact_dir / "package-manifest.json", manifest)
    return {"manifestSha256": sdk.sha(sdk.regular(artifact_dir / "package-manifest.json")),
            "inventorySha256": inventory["inventorySha256"], "toolProvenance": provenance}


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
                self.steps[-1]["command"]["tool"] = ("cargo" if stage in {"wasm-build", "bindgen-install"} else
                    "wasm-bindgen" if stage.startswith("bindgen-") else "rustup")


def run(root, results, *, environ=None, browser_e2e=False):
    ambient = os.environ if environ is None else environ
    output = root / "test-results"
    artifact_dir = output / TARGET
    receipt = {"schemaVersion": 1, "runtime_profile": "rust-browser-package-for-e2e" if browser_e2e else TARGET,
               "requestedMode": ambient.get("CI_TEST_MODE", TARGET),
               "requestedTargets": None, "status": "failed", "code": "admission",
               "compilationProof": False, "packagingProof": False, "browserRuntimeProof": False, "conformanceProof": False,
               "releaseProof": False, "publication": False, "services": {}, "cleanupVerified": False, "sourceHeld": False}
    runner = private = before = source = tree = None
    phase = "admission"
    try:
        sdk.require(ambient.get("GITHUB_ACTIONS") == "true"
                    and ambient.get("RUNNER_ENVIRONMENT") == "github-hosted"
                    and ambient.get("OPENMATES_CI_ISOLATED") == "1"
                    and platform.machine() == "x86_64" and os.sys.platform == "linux", "admission")
        receipt["requestedTargets"] = json.loads(ambient.get("CI_SPECS_JSON", "[]"))
        if browser_e2e:
            sdk.require(ambient.get("CI_TEST_MODE") == "e2e" and receipt["requestedTargets"] == [BROWSER_SPEC]
                        and not ambient.get("CI_CASE_TITLE") and not ambient.get("CI_CAPACITY_CONFIGURATION"), "admission")
        else:
            validate_targets(receipt["requestedTargets"])
            sdk.require(receipt["requestedMode"] == TARGET
                        and not any(ambient.get(key) for key in ("CI_CASE_TITLE", "CI_PREPARATION_KEY", "CI_PREPARED_RUN_ID",
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
        clock = "CI_BROWSER_PACKAGE" if browser_e2e else "CI_RUST_WASM"
        start, deadline = float(ambient[clock + "_STARTED_MONOTONIC"]), float(ambient[clock + "_DEADLINE_MONOTONIC"])
        budget = BROWSER_BUDGET if browser_e2e else BUDGET
        sdk.require(math.isfinite(start) and math.isfinite(deadline) and abs(deadline - start - budget) < 0.000001
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
        for stage, command, seconds in zip(STAGES[:3], commands()[:3], STAGE_SECONDS[:3]):
            phase = "compile" if stage == "wasm-build" else "toolchain"
            sdk.require(snapshot(root, before) == before, "source")
            runner.run(stage, command, seconds=seconds)
            sdk.require(snapshot(root, before) == before, "source")
        phase = "outputs"
        sdk.require(all(sdk.sha(sdk.regular(work / name)) == digest for name, digest in before.items()), "source")
        artifact_dir.mkdir(mode=0o700)
        metadata = copy_compiled_wasm(artifact, artifact_dir / WASM_NAME)
        receipt["artifact"] = metadata
        phase = "packaging"
        receipt["package"] = produce_browser_package(runner, private, work, artifact, artifact_dir, receipt)
        sdk.require(all(sdk.sha(sdk.regular(work / name)) == digest for name, digest in before.items()), "source")
        receipt.update(status="passed", code=None)
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
        receipt["compilationProof"] = receipt["packagingProof"] = receipt["status"] == "passed"
        try:
            sdk.write(output / "ci-rust-wasm.json", receipt)
        except OSError:
            receipt.update(status="failed", code="outputs", receiptWriteFailed=True, compilationProof=False, packagingProof=False)
        finally:
            results.append({"suite": TARGET, "exit_code": 0 if receipt["status"] == "passed" else 1,
                            "failure_code": receipt["code"]})
    return receipt


def prepare_browser_e2e_package(root, *, environ=None):
    """One exact E2E selector consumes the package built from its own checkout."""
    ambient = os.environ if environ is None else environ
    preparation_results = []
    receipt = run(root, preparation_results, environ=ambient, browser_e2e=True)
    sdk.require(receipt.get("status") == "passed" and all(receipt.get(key) is True for key in
                ("sourceHeld", "cleanupVerified", "compilationProof", "packagingProof")), "packaging")
    source, tree = sdk.git(root, "rev-parse", "HEAD"), sdk.git(root, "rev-parse", "HEAD^{tree}")
    expected = source_inputs_from_git(root, source)
    sdk.require(source == ambient.get("BUILD_COMMIT_SHA") and tree == ambient.get("CI_CANDIDATE_TREE")
                and snapshot(root, expected) == expected, "source")
    folder = root / "test-results" / TARGET
    manifest_bytes = sdk.regular(folder / "package-manifest.json")
    generated = {path.name: sdk.regular(path) for path in (folder / "package").iterdir()}
    sdk.require(wasm_metadata(sdk.regular(folder / WASM_NAME, 128 * 1024**2)) == receipt["artifact"], "outputs")
    try:
        from scripts.ci_results import valid_browser_package
    except ModuleNotFoundError:
        from ci_results import valid_browser_package
    job = {"source": source, "run_id": ambient["GITHUB_RUN_ID"], "mode": "e2e", "specs": json.dumps([BROWSER_SPEC])}
    sdk.require(valid_browser_package(manifest_bytes, generated, receipt, job, ambient["CI_HARNESS_COMMIT"], expected, tree), "outputs")
    return {"OPENMATES_BROWSER_PACKAGE_MANIFEST": str(folder / "package-manifest.json"),
            "OPENMATES_BROWSER_PACKAGE_MANIFEST_SHA256": sdk.sha(manifest_bytes), "OPENMATES_BROWSER_SOURCE_COMMIT": source}
