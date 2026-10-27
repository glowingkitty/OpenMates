"""Explicit lock preparation, never SDK/WASM conformance or release evidence.

Only immutable, tracked Rust sources are copied into the disposable Cargo root.
The checkout and the existing conformance lane remain locked and unchanged.
"""
from __future__ import annotations

import json
import math
import os
from pathlib import Path
import platform
import re
import shutil
import subprocess
import tempfile
import time
import tomllib

try:
    from scripts import ci_sdk_conformance as sdk
except ModuleNotFoundError:
    import ci_sdk_conformance as sdk

TARGET = "sdk-lockfiles"
BUDGET = 1200
ROOTS = ("packages/openmates-rust", "packages/openmates-session-bindings",
         "frontend/packages/openmates-tui-native", "packages/openmates-browser-bindings")
LOCKS = tuple(name + "/Cargo.lock" for name in ROOTS)
ORIGINAL_LOCKS = LOCKS[:3]
STAGES = ("sdk-lock", "session-lock", "native-lock", "browser-lock")
FAILURES = frozenset({"admission", "identity", "source", "deadline", "disk", "toolchain", "cargo", "outputs", "cleanup", "unclassified"})


def validate_targets(targets):
    sdk.require(targets == [TARGET], "admission")


def commands():
    return [["cargo", "+1.98.1", "update", "--manifest-path", root + "/Cargo.toml", "-p", "openmates-sdk"]
            if root != ROOTS[-1] else
            ["cargo", "+1.98.1", "generate-lockfile", "--manifest-path", root + "/Cargo.toml"]
            for root in ROOTS]


def owned(name):
    """Closed source scopes: never Cargo config, Git hooks or account state."""
    for root in ROOTS:
        if name.startswith(root + "/"):
            tail = Path(name[len(root) + 1:])
            return (tail.as_posix() in {"Cargo.toml", "Cargo.lock", "build.rs"}
                    or (tail.parts[0] in {"src", "tests", "fixtures", "examples", "assets"}
                        and tail.suffix in {".rs", ".json", ".txt", ".md", ".yaml", ".yml", ".toml"}))
    return False


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
                and all(name in rows for name in ORIGINAL_LOCKS), "source")
    return rows


def snapshot(root, expected):
    names = subprocess.check_output(["git", "ls-files", "-z", "--", *ROOTS], cwd=root, timeout=15).decode().split("\0")
    sdk.require({name for name in names if name and owned(name)} == set(expected), "source")
    others = subprocess.check_output(["git", "ls-files", "--others", "--exclude-standard", "-z", "--", *ROOTS], cwd=root, timeout=15).decode().split("\0")
    sdk.require(not any(name and owned(name) for name in others), "source")
    return {name: sdk.sha(sdk.regular(root / name)) for name in expected}


def lock_metadata(data):
    value = tomllib.loads(data.decode())
    sdk.require(type(value.get("version")) is int and value["version"] in {3, 4}
                and isinstance(value.get("package"), list) and value["package"], "outputs")
    sdk.require(all(row.get("source", "registry+https://github.com/rust-lang/crates.io-index")
                    == "registry+https://github.com/rust-lang/crates.io-index" for row in value["package"]), "outputs")
    return {"sha256": sdk.sha(data), "bytes": len(data)}


class LockCommands(sdk.Commands):
    def run(self, stage, command, **kwargs):
        try:
            return super().run(stage, command, **kwargs)
        finally:
            if self.steps and stage in STAGES:
                self.steps[-1]["command"]["tool"] = "cargo"


def validate_manifests(work):
    for root in ROOTS:
        manifest = work / root / "Cargo.toml"
        def visit(value):
            if isinstance(value, dict):
                sdk.require(not any(key in value for key in ("git", "registry", "registries", "patch", "replace")), "source")
                if "path" in value:
                    path = value["path"]
                    sdk.require(isinstance(path, str) and not Path(path).is_absolute(), "source")
                    resolved = (manifest.parent / path).resolve()
                    sdk.require(resolved in {work / name for name in ROOTS}, "source")
                for item in value.values():
                    visit(item)
            elif isinstance(value, list):
                for item in value:
                    visit(item)
        # Target/bin/example path fields point to source files rather than dependency roots.
        parsed = tomllib.loads(sdk.regular(manifest).decode())
        for section in ("dependencies", "dev-dependencies", "build-dependencies", "target", "patch", "replace"):
            if section in parsed:
                sdk.require(section not in {"patch", "replace"}, "source")
                visit(parsed[section])


def run(root, results, *, environ=None):
    ambient = os.environ if environ is None else environ
    output = root / "test-results"
    receipt = {"schemaVersion": 1, "runtime_profile": TARGET, "status": "failed", "code": "admission",
               "conformanceProof": False, "releaseProof": False, "publication": False,
               "services": {}, "cleanupVerified": False, "sourceHeld": False}
    runner = None
    private = None
    before = None
    source = tree = None
    artifact_dir = output / "sdk-lockfiles"
    phase = "admission"
    try:
        sdk.require(ambient.get("GITHUB_ACTIONS") == "true"
                    and ambient.get("RUNNER_ENVIRONMENT") == "github-hosted"
                    and ambient.get("OPENMATES_CI_ISOLATED") == "1"
                    and platform.machine() == "x86_64" and os.sys.platform == "linux", "admission")
        validate_targets(json.loads(ambient.get("CI_SPECS_JSON", "[]")))
        sdk.require(not any(ambient.get(key) for key in ("CI_CASE_TITLE", "CI_PREPARATION_KEY",
                    "CI_PREPARED_RUN_ID", "CI_RUNTIME_SEED", "CI_CAPACITY_CONFIGURATION")), "admission")
        phase = "identity"
        source = sdk.git(root, "rev-parse", "HEAD")
        tree = sdk.git(root, "rev-parse", "HEAD^{tree}")
        harness = ambient.get("CI_HARNESS_COMMIT", "")
        sdk.require(source == ambient.get("BUILD_COMMIT_SHA") and tree == ambient.get("CI_CANDIDATE_TREE")
                    and re.fullmatch(r"[0-9a-f]{40}", source) and re.fullmatch(r"[0-9a-f]{40}", harness)
                    and re.fullmatch(r"[0-9]+", ambient.get("GITHUB_RUN_ID", ""))
                    and sdk.git(Path(__file__).resolve().parent.parent, "rev-parse", "HEAD") == harness
                    and subprocess.run(["git", "symbolic-ref", "-q", "HEAD"], cwd=root, capture_output=True, timeout=15).returncode == 1,
                    "identity")
        phase = "deadline"
        start = float(ambient["CI_SDK_LOCKFILES_STARTED_MONOTONIC"])
        deadline = float(ambient["CI_SDK_LOCKFILES_DEADLINE_MONOTONIC"])
        sdk.require(math.isfinite(start) and math.isfinite(deadline)
                    and abs(deadline - start - BUDGET) < 0.000001 and start <= time.monotonic() < deadline, "deadline")
        phase = "source"
        before = source_inputs_from_git(root, source)
        sdk.require(snapshot(root, before) == before, "source")
        receipt.update(source_commit=source, source_tree=tree, harness_commit=harness,
                       run_id=ambient["GITHUB_RUN_ID"], inputs=before,
                       inputSetSha256=sdk.sha(json.dumps(before, sort_keys=True).encode()),
                       originalLocks={name: before.get(name) for name in LOCKS})
        phase = "disk"
        sdk.require(shutil.disk_usage(output).free >= sdk.RESERVE, "disk")
        sdk.require(not artifact_dir.exists(), "outputs")
        private = Path(tempfile.mkdtemp(prefix="sdk-lockfiles-", dir=Path(ambient["RUNNER_TEMP"])))
        os.chmod(private, 0o700)
        work = private / "source"
        work.mkdir(mode=0o700)
        for name, digest in before.items():
            data = sdk.regular(root / name)
            sdk.require(sdk.sha(data) == digest, "source")
            target = work / name
            target.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
            target.write_bytes(data)
        home = private / "home"
        home.mkdir(mode=0o700)
        temp = private / "tmp"
        temp.mkdir(mode=0o700)
        rustup = shutil.which("rustup")
        cargo = shutil.which("cargo")
        sdk.require(rustup and cargo, "toolchain")
        env = {"PATH": os.pathsep.join(dict.fromkeys([str(Path(rustup).parent), str(Path(cargo).parent), *os.defpath.split(os.pathsep)])),
               "HOME": str(home), "TMPDIR": str(temp), "LANG": "C.UTF-8", "CI": "true",
               "RUSTUP_HOME": ambient.get("RUSTUP_HOME", str(Path.home() / ".rustup")),
               "RUSTUP_TOOLCHAIN": "1.98.1", "CARGO_HOME": str(private / "cargo"),
               "CARGO_TARGET_DIR": str(private / "target"), "CARGO_NET_RETRY": "2", "CARGO_HTTP_TIMEOUT": "60"}
        validate_manifests(work)
        runner = LockCommands(work, private, env, deadline)
        phase = "toolchain"
        runner.run("rust-toolchain", ["rustup", "toolchain", "install", "1.98.1", "--profile", "minimal"], seconds=300)
        phase = "cargo"
        for stage, command in zip(STAGES, commands()):
            sdk.require(snapshot(root, before) == before, "source")
            runner.run(stage, command, seconds=180)
            sdk.require(snapshot(root, before) == before, "source")
        phase = "outputs"
        sdk.require(all(sdk.sha(sdk.regular(work / name)) == digest
                        for name, digest in before.items() if name not in LOCKS), "source")
        generated = {name: sdk.regular(work / name) for name in LOCKS}
        metadata = {name: lock_metadata(data) for name, data in generated.items()}
        sdk.require(snapshot(root, before) == before and sdk.git(root, "rev-parse", "HEAD") == source
                    and sdk.git(root, "rev-parse", "HEAD^{tree}") == tree, "source")
        receipt.update(generatedLocks=metadata, sourceHeld=True, status="passed", code=None)
        artifact_dir.mkdir(mode=0o700)
        for name, data in generated.items():
            target = artifact_dir / name
            target.parent.mkdir(parents=True, mode=0o700, exist_ok=True)
            target.write_bytes(data)
    except Exception as error:
        receipt.update(status="failed", code=phase if phase in FAILURES else "unclassified")
        # Arbitrary exception text and Cargo logs never enter the artifact receipt.
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
                    name = runner.steps[-1]["stage"]
                    sdk.require(name in {*STAGES, "rust-toolchain"}, "cargo")
                    raw = sdk.regular(private / (name + ".log"), sdk.MAX_LOG)
                    retained = Path(tempfile.mkdtemp(prefix="sdk-lockfiles-failure-", dir=private.parent))
                    (retained / "cargo.log").write_bytes(raw)
                    (retained / "cargo.log").chmod(0o600)
                    categories = {b"failed to select a version": "version_resolution", b"no matching package named": "package_missing",
                                  b"failed to download": "download", b"failed to get": "dependency_fetch",
                                  b"checksum": "checksum", b"failed to parse manifest": "manifest",
                                  b"No space left": "disk", b"timed out": "timeout"}
                    receipt["diagnostics"] = {"stage": name, "rawUpload": False,
                        "classification": next((value for pattern, value in categories.items() if pattern in raw), "unclassified"),
                        "privateRetained": {"bytes": len(raw), "sha256": sdk.sha(raw), "lifetime": "isolated-runner-only"}}
                except Exception:
                    receipt["diagnostics"] = {"classification": "diagnostic_unavailable", "rawUpload": False}
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
        try:
            sdk.write(output / "ci-sdk-lockfiles.json", receipt)
        except OSError:
            receipt.update(status="failed", code="outputs", receiptWriteFailed=True)
        finally:
            results.append({"suite": TARGET, "exit_code": 0 if receipt["status"] == "passed" else 1,
                            "failure_code": receipt["code"]})
    return receipt
