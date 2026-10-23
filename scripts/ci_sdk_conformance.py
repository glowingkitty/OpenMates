"""Fixed SDK build/conformance lane for the existing isolated GitHub runner.

No backend, account provisioning, arbitrary shell command, release or publication.
Raw build/gate diagnostics remain private; public evidence has closed stage codes.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import platform
from pathlib import Path
import re
import shutil
import signal
import stat
import subprocess
import sys
import tempfile
import time
import tomllib

TARGET = "sdk-conformance"
BUDGET = 2700  # 45min from workflow start; leaves 15min of the 60min job for setup/upload.
RESERVE = 2 * 1024**3  # runner artifact/cleanup reserve, not the dev-host capacity floor
MAX_LOG = 32 * 1024**2
LOCKS = ("packages/openmates-rust/Cargo.lock", "packages/openmates-session-bindings/Cargo.lock",
         "frontend/packages/openmates-tui-native/Cargo.lock")
INPUTS = ("packages/openmates-rust", "packages/openmates-session-bindings", "packages/openmates-python",
          "frontend/packages/openmates-cli", "backend/apps", "tests/sdk-conformance", "config/sdk-capabilities.json",
          "config/sdk-capabilities.schema.json", "scripts/check_sdk_conformance.py", "scripts/build_sdk_native.py",
          "scripts/sdk_rust_inventory.py", "scripts/generate_sdk_app_skills.py", "scripts/generate_rust_sdk_apps.py",
          "pnpm-lock.yaml", "pnpm-workspace.yaml", "package.json", ".cargo", "rust-toolchain.toml",
          "frontend/packages/pairing-crypto", "frontend/packages/upload-privacy", "shared/config", *LOCKS)


class Refused(RuntimeError):
    pass


def require(value, code):
    if not value:
        raise Refused(code)


def validate_targets(targets):
    require(targets == [TARGET], "exact_sdk_target_required")


def sha(data):
    return hashlib.sha256(data).hexdigest()


def regular(path, limit=64 * 1024**2):
    require(path.is_absolute() and path.resolve() == path, "unsafe_file")
    with os.fdopen(os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK), "rb") as stream:
        before = os.fstat(stream.fileno())
        require(stat.S_ISREG(before.st_mode) and before.st_uid == os.getuid()
                and not before.st_mode & 0o002 and before.st_size <= limit, "unsafe_file")
        data = stream.read(limit + 1)
        def identity(value):
            return tuple(getattr(value, key) for key in ("st_dev", "st_ino", "st_mode", "st_uid", "st_gid",
                                                        "st_nlink", "st_size", "st_mtime_ns", "st_ctime_ns"))
        require(len(data) <= limit and identity(before) == identity(os.fstat(stream.fileno()))
                and identity(before) == identity(path.lstat()), "changed_file")
        return data



def load_trust():
    return json.loads(regular(Path(__file__).with_name("ci_sdk_conformance_trust.json"), 2 * 1024**2))


def verify_programs(root, trust):
    for name, digest in trust["programs"].items():
        require(sha(regular(root / name)) == digest, "reviewed_program_changed")
    for name, digest in trust["contracts"].items():
        require(sha(regular(root / name)) == digest, "reviewed_contract_changed")


def matrix_gaps(matrix):
    return [f"{row['id']} [{language}] {row['languages'][language]['status']}: "
            + "; ".join(row["languages"][language]["gaps"])
            for row in matrix["capabilities"] for language in ("rust", "npm", "python")
            if row["languages"][language]["status"] != "implemented"]


def execution_plan(root, matrix):
    rows = []
    for capability in matrix["capabilities"]:
        fixture = capability.get("fixture", matrix["fixture"])
        require(isinstance(fixture, str) and fixture.startswith("tests/sdk-conformance/")
                and ".." not in Path(fixture).parts, "gate_fixture")
        raw = regular(root / fixture)
        vectors = json.loads(raw)["capabilities"].get(capability["id"], {}).get("vectors", [])
        ids = [value.get("id", value.get("name")) for value in vectors]
        for language in ("rust", "npm", "python"):
            if capability["languages"][language]["conformance"]:
                require(ids and len(ids) == len(set(ids)) and all(isinstance(value, str)
                    and re.fullmatch(r"[A-Za-z0-9._:-]{1,160}", value) for value in ids), "gate_vectors")
                rows.append({"capability": capability["id"], "language": language, "fixture": fixture,
                             "fixtureSha256": sha(raw), "vectors": sorted(ids)})
    return rows


def source_inputs_from_git(root, source):
    """Reconstruct expected compiler-input hashes from immutable coordinator Git objects."""
    require(re.fullmatch(r"[0-9a-f]{40}", source), "source_identity")
    listing = subprocess.check_output(["git", "ls-tree", "-r", "-z", source, "--", *INPUTS], cwd=root, timeout=15)
    entries = []
    for raw in listing.split(b"\0"):
        if not raw:
            continue
        header, name = raw.split(b"\t", 1)
        mode, kind, oid = header.decode().split()
        require(mode in {"100644", "100755"} and kind == "blob", "source_tree_type")
        entries.append((name.decode(), oid))
    require(0 < len(entries) <= 20000, "source_tree_bound")
    request = "".join(oid + "\n" for _, oid in entries).encode()
    sizes = subprocess.run(["git", "cat-file", "--batch-check"], cwd=root, input=request,
                           capture_output=True, check=True, timeout=30).stdout.splitlines()
    require(len(sizes) == len(entries), "source_tree_metadata")
    total = 0
    for line, (_, oid) in zip(sizes, entries):
        actual, kind, size = line.decode().split()
        require(actual == oid and kind == "blob" and 0 <= int(size) <= 64 * 1024**2, "source_blob_bound")
        total += int(size)
    require(total <= 512 * 1024**2, "source_tree_byte_bound")
    blobs = subprocess.run(["git", "cat-file", "--batch"], cwd=root, input=request,
                           capture_output=True, check=True, timeout=60).stdout
    require(len(blobs) <= total + len(entries) * 128, "source_batch_bound")
    offset, rows = 0, {}
    for name, oid in entries:
        end = blobs.index(b"\n", offset)
        actual, kind, size = blobs[offset:end].decode().split()
        require(actual == oid and kind == "blob", "source_blob_identity")
        start = end + 1
        offset = start + int(size) + 1
        require(offset <= len(blobs) and blobs[offset - 1:offset] == b"\n", "source_blob_size")
        rows[name] = sha(blobs[start:offset - 1])
    require(offset == len(blobs), "source_batch_tail")
    return rows


def write(path, value):
    data = (json.dumps(value, sort_keys=True, indent=2) + "\n").encode()
    with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as stream:
        os.fchmod(stream.fileno(), 0o600)
        stream.write(data)
        temporary = stream.name
    os.replace(temporary, path)


def git(root, *args):
    return subprocess.check_output(["git", *args], cwd=root, timeout=15).decode().strip()


def snapshot(root):
    require(not git(root, "ls-files", "--others", "--exclude-standard", "--", *INPUTS), "untracked_source_input")
    names = subprocess.check_output(["git", "ls-files", "-z", "--", *INPUTS], cwd=root, timeout=15).decode().split("\0")
    rows = {name: sha(regular(root / name)) for name in names if name}
    require(all(name in rows for name in LOCKS) and "scripts/check_sdk_conformance.py" in rows, "source_inputs_missing")
    return rows


def artifact(path):
    data = regular(path, 256 * 1024**2)
    info = path.stat()
    require(info.st_nlink == 1 and len(data) > 64 and data[:4] == b"\x7fELF", "invalid_native_artifact")
    # GitHub-hosted lane explicitly uses Linux x64; do not accept the dev ARM64 binary.
    require(data[4:6] == b"\x02\x01" and int.from_bytes(data[18:20], "little") == 62, "native_architecture")
    return {"sha256": sha(data), "bytes": len(data), "device": info.st_dev, "inode": info.st_ino,
            "uid": info.st_uid, "mode": stat.S_IMODE(info.st_mode), "nlink": info.st_nlink,
            "mtimeNs": info.st_mtime_ns, "ctimeNs": info.st_ctime_ns, "elf": "linux-x64"}


def terminate(child):
    # Every stage owns a fresh process group; includes Cargo, gate and fixture peers.
    try:
        os.killpg(child.pid, signal.SIGTERM)
    except ProcessLookupError:
        pass
    try:
        child.wait(timeout=3)
    except subprocess.TimeoutExpired:
        pass
    try:
        os.killpg(child.pid, signal.SIGKILL)
    except ProcessLookupError:
        pass
    child.wait(timeout=3)


class Commands:
    def __init__(self, root, private, env, deadline):
        self.root, self.private, self.env, self.deadline = root, private, env, deadline
        self.steps = []
        self.minimum_free = shutil.disk_usage(root).free

    def check(self):
        require(time.monotonic() < self.deadline, "deadline")
        free = shutil.disk_usage(self.root).free
        self.minimum_free = min(self.minimum_free, free)
        require(free >= RESERVE, "artifact_reserve")

    def run(self, stage, command, *, seconds=900):
        self.check()
        began = time.monotonic()
        record = {"stage": stage, "status": "failed"}
        self.steps.append(record)
        with (self.private / (stage + ".log")).open("xb") as log:
            os.fchmod(log.fileno(), 0o600)
            child = subprocess.Popen(command, cwd=self.root, env=self.env, stdin=subprocess.DEVNULL,
                                     stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
            try:
                while child.poll() is None:
                    self.check()
                    require(time.monotonic() - began < seconds, "stage_deadline")
                    require(log.tell() <= MAX_LOG, "diagnostic_bound")
                    time.sleep(0.5)
                require(child.returncode == 0, "child_failed")
                require(log.tell() <= MAX_LOG, "diagnostic_bound")
                self.check()
                if stage == "binding-library-units":
                    log.flush()
                    text = regular(self.private / (stage + ".log"), MAX_LOG).decode("utf-8", errors="replace")
                    counts = re.findall(r"(?m)^test result: ok\. ([0-9]+) passed; ([0-9]+) failed; ([0-9]+) ignored;", text)
                    require(len(counts) == 1 and int(counts[0][0]) > 0 and int(counts[0][1]) == 0, "unit_test_evidence")
                    record["unitTests"] = dict(zip(("passed", "failed", "ignored"), map(int, counts[0])))
                record["status"] = "passed"
            finally:
                record["returncode"] = child.poll()
                terminate(child)
                record["terminatedReturncode"] = child.returncode
                record["elapsedSeconds"] = round(time.monotonic() - began, 3)
        return self.private / (stage + ".log")


def gate_receipt(root, report, *, trust):
    """Retain only complete reviewed matrix/fixture results, never raw output fields."""
    matrix_bytes = regular(root / "config/sdk-capabilities.json")
    matrix = json.loads(matrix_bytes)
    require(report.get("matrixSha256") == sha(matrix_bytes), "gate_matrix")
    require(sha(matrix_bytes) == trust["contracts"]["config/sdk-capabilities.json"], "gate_reviewed_matrix")
    expected = {}
    for capability in matrix["capabilities"]:
        name = capability["id"]
        require(re.fullmatch(r"[A-Za-z0-9._:-]{1,160}", name), "gate_identity")
        fixture = capability.get("fixture", matrix["fixture"])
        require(isinstance(fixture, str) and fixture.startswith("tests/sdk-conformance/")
                and ".." not in Path(fixture).parts, "gate_fixture")
        raw = regular(root / fixture)
        suite = json.loads(raw)["capabilities"].get(name, {})
        ids = [vector.get("id", vector.get("name")) for vector in suite.get("vectors", [])]
        for language in ("rust", "npm", "python"):
            if capability["languages"][language]["conformance"]:
                require(ids and all(isinstance(value, str) and re.fullmatch(r"[A-Za-z0-9._:-]{1,160}", value)
                                    for value in ids) and len(ids) == len(set(ids)), "gate_vectors")
                expected[(name, language)] = (sha(raw), set(ids))
    rows, seen = [], set()
    for result in report.get("conformance", []):
        key = (result.get("capability"), result.get("language"))
        require(key in expected and key not in seen, "gate_result_identity")
        fixture_hash, ids = expected[key]
        results = result.get("results")
        require(result.get("status") == "passed" and result.get("fixtureSha256") == fixture_hash
                and isinstance(results, list) and len(results) == len(ids)
                and all(isinstance(value, dict) and value.get("status") == "passed" for value in results)
                and {value.get("id") for value in results} == ids, "gate_result_vectors")
        seen.add(key)
        rows.append({"capability": key[0], "language": key[1], "fixtureSha256": fixture_hash,
                     "vectors": sorted(ids), "status": "passed"})
    gaps = report.get("openGaps")
    require(seen == set(expected) and bool(rows) and gaps == matrix_gaps(matrix)
            and report.get("releaseEligible") is (not gaps), "gate_incomplete")
    plan = execution_plan(root, matrix)
    require(plan == trust["plan"] and gaps == trust["gaps"]
            and report.get("trustedProgramsSha256") == sha(json.dumps(trust["programs"], sort_keys=True).encode()),
            "gate_reviewed_expectations")
    launches = report.get("actualLaunches")
    require(report.get("expectedPlan") == plan and isinstance(launches, list) and len(launches) == len(plan)
            and all(value.get("capability") == expected_row["capability"]
                    and value.get("language") == expected_row["language"] and value.get("status") == "passed"
                    and re.fullmatch(r"[0-9a-f]{64}", value.get("commandSha256", ""))
                    for value, expected_row in zip(launches, plan)), "gate_launches")
    return {"matrixSha256": sha(matrix_bytes), "status": "migration-gaps" if gaps else "synchronized",
            "openGapCount": len(gaps), "releaseEligible": not gaps,
            "conformance": rows, "plan": plan, "actualLaunches": launches,
            "trustedProgramsSha256": report.get("trustedProgramsSha256"), "realRunCount": len(rows),
            "vectorOutcomeCount": sum(len(row["vectors"]) for row in rows)}



def compiler_diagnostics(data, root, inputs):
    report = {"compiler": []}
    text = data[-65536:].decode("utf-8", errors="replace")
    codes = list(dict.fromkeys(re.findall(r"(?m)^error\[(E[0-9]{4})\]:", text)))[:16]
    locations = []
    for match in re.finditer(r"(?m)^\s*--> ([^\n]{1,512}):([0-9]{1,8}):([0-9]{1,8})\s*$", text):
        path, line, column = match.groups()
        candidates = [Path(path)] if Path(path).is_absolute() else [base / path for base in
            (root, root / "packages/openmates-session-bindings", root / "packages/openmates-rust")]
        for candidate in candidates:
            try:
                relative = candidate.resolve().relative_to(root).as_posix()
            except ValueError:
                continue
            location = {"path": relative, "line": int(line), "column": int(column)}
            if relative in inputs and location not in locations:
                locations.append(location)
    report["compiler"] = [{"kind": "rustc", "code": code, "locations": locations[:16]} for code in codes]
    for match in re.finditer(r"(?m)^([^\n]{1,512})\(([0-9]{1,8}),([0-9]{1,8})\): error (TS[0-9]{4,5}):", text):
        path, line, column, code = match.groups()
        for candidate in (root / path, root / "frontend/packages/openmates-cli" / path):
            try:
                relative = candidate.relative_to(root).as_posix()
            except ValueError:
                continue
            if relative in inputs and len(report["compiler"]) < 32:
                report["compiler"].append({"kind": "typescript", "code": code,
                    "locations": [{"path": relative, "line": int(line), "column": int(column)}]})
                break
    return report["compiler"]


def failure_diagnostics(private, root, stage, inputs, plan):
    """Retain raw bytes privately; export only closed codes and tracked locations."""
    report = {"category": "adapter_conformance" if stage == "real-conformance" else
              "native_load" if stage in {"napi-load", "python-load"} else
              "rust_compile_or_unit" if stage in {"binding-library-units", "napi-build", "python-binding-build"} else
              "typescript_compile" if stage == "sdk-facade-build" else "setup_or_fence",
              "compiler": [], "rawUpload": False}
    log = private / (stage + ".log")
    if log.exists():
        with os.fdopen(os.open(log, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK), "rb") as source:
            info = os.fstat(source.fileno())
            require(stat.S_ISREG(info.st_mode) and info.st_uid == os.getuid(), "diagnostic_file")
            data = source.read(MAX_LOG)
        directory = Path(tempfile.mkdtemp(prefix="failure-sdk-", dir=private.parent))
        destination = directory / (stage + ".log")
        with destination.open("xb") as output:
            os.fchmod(output.fileno(), 0o600)
            output.write(data)
        report["privateRetained"] = {"bytes": len(data), "sha256": sha(data),
                                     "truncated": info.st_size > len(data), "lifetime": "isolated-runner-only"}
        report["compiler"] = compiler_diagnostics(data, root, inputs)
        if stage in {"napi-load", "python-load"}:
            text = data[-65536:].decode("utf-8", errors="replace")
            names = {"ImportError": "import_error", "ModuleNotFoundError": "module_missing",
                     "AttributeError": "export_missing", "AssertionError": "load_identity_or_export_assertion",
                     "OSError": "os_loader_error", "RuntimeError": "runtime_loader_error"}
            found = re.findall(r"(?m)^(ImportError|ModuleNotFoundError|AttributeError|AssertionError|OSError|RuntimeError):", text)
            if found:
                report["loadError"] = names[found[-1]]
            elif "ERR_DLOPEN_FAILED" in text:
                report["loadError"] = "dynamic_library_load_failed"
            elif "MODULE_NOT_FOUND" in text:
                report["loadError"] = "module_missing"
    driver_file = private / "driver-failure.json"
    if driver_file.exists():
        driver = json.loads(regular(driver_file, 65536))
        allowed = {"driver_deadline", "driver_output_bound", "driver_failed", "driver_vector_result",
                   "driver_unclassified", "trusted_gate_validation_failed", "reviewed_program_changed", "reviewed_contract_changed",
                   "driver_contract", "driver_count", "driver_order", "trusted_generated_failed", "trusted_inventory_failed",
                   "trusted_matrix_failed", "trusted_adapters_failed"}
        report["driverCode"] = driver.get("code") if driver.get("code") in allowed else "unclassified"
        identity = driver.get("adapter")
        if isinstance(identity, dict):
            expected = next((row for row in plan if row["capability"] == identity.get("capability")
                             and row["language"] == identity.get("language")), None)
            if expected:
                report["adapter"] = {key: expected[key] for key in ("capability", "language", "fixtureSha256")}
                report["knownVectorIds"] = expected["vectors"]
                failed_ids = [value for value in driver.get("failedVectorIds", [])
                              if isinstance(value, str) and value in expected["vectors"]]
                report["failedVectorIds"] = sorted(set(failed_ids))
                report["vectorAttribution"] = "exact-known-ids" if failed_ids else "adapter-suite-only"
        for entry in driver.get("compiler", []):
            if not isinstance(entry, dict) or not isinstance(entry.get("code"), str):
                continue
            kind, code = entry.get("kind"), entry["code"]
            if not ((kind == "rustc" and re.fullmatch(r"E[0-9]{4}", code))
                    or (kind == "typescript" and re.fullmatch(r"TS[0-9]{4,5}", code))):
                continue
            locations = [{key: value[key] for key in ("path", "line", "column")}
                         for value in entry.get("locations", []) if isinstance(value, dict)
                         and value.get("path") in inputs and type(value.get("line")) is int
                         and type(value.get("column")) is int and 0 <= value["line"] < 100000000
                         and 0 <= value["column"] < 100000000][:16]
            if len(report["compiler"]) < 32:
                report["compiler"].append({"kind": kind, "code": code, "locations": locations})
        for stream in ("stdout", "stderr"):
            count, digest = driver.get(stream + "Bytes"), driver.get(stream + "Sha256")
            if (type(count) is int and 0 <= count <= 4 * 1024**2 + 65536
                    and isinstance(digest, str) and re.fullmatch(r"[0-9a-f]{64}", digest)):
                report[stream + "Bytes"] = count
                report[stream + "Sha256"] = digest
        returncode = driver.get("terminatedReturncode", driver.get("returncode"))
        if type(returncode) is int:
            report["driverReturncode"] = returncode
    return report


def run(root, results, node, *, verify_node, environ=None):
    ambient = os.environ if environ is None else environ
    output = root / "test-results"
    evidence = {"schemaVersion": 1, "status": "failed", "stage": "admission", "code": "unclassified",
                "runtime_profile": TARGET, "services": {}, "publication": False, "cleanupVerified": False}
    commands = None
    owned_private = None
    stage = "admission"
    try:
        require(ambient.get("GITHUB_ACTIONS") == "true" and ambient.get("RUNNER_ENVIRONMENT") == "github-hosted"
                and ambient.get("OPENMATES_CI_ISOLATED") == "1", "github_runner_required")
        require(sys.version_info[:2] == (3, 12) and callable(verify_node), "python_or_node_attestation")
        require(sys.platform == "linux" and platform.machine() == "x86_64", "runner_architecture")
        validate_targets(json.loads(ambient.get("CI_SPECS_JSON", "[]")))
        source = git(root, "rev-parse", "HEAD")
        require(source == ambient.get("BUILD_COMMIT_SHA") and re.fullmatch(r"[0-9a-f]{40}", source)
                and git(root, "rev-parse", "HEAD^{tree}") == ambient.get("CI_CANDIDATE_TREE")
                and subprocess.run(["git", "symbolic-ref", "-q", "HEAD"], cwd=root, capture_output=True).returncode == 1,
                "source_identity")
        start, deadline = float(ambient["CI_SDK_STARTED_MONOTONIC"]), float(ambient["CI_SDK_DEADLINE_MONOTONIC"])
        require(math.isfinite(start) and math.isfinite(deadline) and abs(deadline - start - BUDGET) < 0.000001
                and start <= time.monotonic() < deadline, "deadline_identity")
        trust = load_trust()
        verify_programs(root, trust)
        before = snapshot(root)
        require(before == source_inputs_from_git(root, source), "source_checkout_changed")
        evidence.update(source_commit=source, harness_commit=ambient.get("CI_HARNESS_COMMIT"),
                        run_id=ambient.get("GITHUB_RUN_ID"), inputs=before,
                        inputSetSha256=sha(json.dumps(before, sort_keys=True).encode()),
                        locks={name: before[name] for name in LOCKS})
        private_root = output / "ci-private"
        private_root.mkdir(mode=0o700, exist_ok=True)
        private_info = private_root.lstat()
        require(private_root.resolve() == private_root and stat.S_ISDIR(private_info.st_mode)
                and private_info.st_uid == os.getuid() and not private_info.st_mode & 0o077, "private_boundary")
        with tempfile.TemporaryDirectory(prefix="sdk-", dir=private_root) as temporary:
            private = Path(temporary)
            owned_private = private
            home = private / "home"
            home.mkdir(mode=0o700)
            temporary_files = private / "tmp"
            temporary_files.mkdir(mode=0o700)
            rustup, pnpm = shutil.which("rustup"), shutil.which("pnpm")
            require(rustup and pnpm, "setup_tools_missing")
            search_path = os.pathsep.join((str(Path(node).parent), str(Path(rustup).parent),
                                           str(Path(pnpm).parent), str(Path(sys.executable).parent), os.defpath))
            env = {"PATH": search_path, "TMPDIR": str(temporary_files),
                   "OPENMATES_STATE_DIR": str(home / "state"),
                   "HOME": str(home), "LANG": "C.UTF-8", "CI": "true", "GITHUB_ACTIONS": "true",
                   "OPENMATES_CI_ISOLATED": "1", "RUNNER_ENVIRONMENT": "github-hosted",
                   "PYTHONNOUSERSITE": "1", "PIP_DISABLE_PIP_VERSION_CHECK": "1",
                   "RUSTUP_HOME": ambient.get("RUSTUP_HOME", str(Path.home() / ".rustup")),
                   "RUSTUP_TOOLCHAIN": "1.98.1", "CARGO_HOME": str(private / "cargo"),
                   "CARGO_TARGET_DIR": str(private / "target"), "CARGO_BUILD_JOBS": "2",
                   "CARGO_INCREMENTAL": "0", "CARGO_PROFILE_DEV_DEBUG": "0", "CARGO_PROFILE_TEST_DEBUG": "0"}
            commands = Commands(root, private, env, deadline)
            def step(name, command, seconds=900):
                nonlocal stage
                stage = name
                if name in {"binding-library-units", "napi-build", "python-binding-build"}:
                    require(snapshot(root) == before, "source_changed")
                result = commands.run(name, command, seconds=seconds)
                if name in {"binding-library-units", "napi-build", "python-binding-build"}:
                    require(snapshot(root) == before, "source_changed")
                return result
            try:
                step("rust-toolchain", [rustup, "toolchain", "install", "1.98.1", "--profile", "minimal", "--component", "rustfmt"], 300)
                step("python-environment", [sys.executable, "-m", "venv", str(private / "venv")], 60)
                python = str(private / "venv/bin/python")
                env["PYO3_PYTHON"] = python
                env["OPENMATES_SDK_CONFORMANCE_PYTHON"] = python
                step("node-dependencies", [pnpm, "install", "--frozen-lockfile"], 300)
                dependencies = tomllib.loads(regular(root / "packages/openmates-python/pyproject.toml").decode())["project"]["dependencies"]
                require(isinstance(dependencies, list) and all(isinstance(value, str) and len(value) <= 256
                        and not value.startswith("-") and "\n" not in value for value in dependencies), "sdk_dependency_contract")
                step("python-dependencies", [python, "-m", "pip", "install", "jsonschema", "pytest", "pyyaml", *dependencies], 300)
                step("binding-library-units", ["cargo", "+1.98.1", "test", "--locked", "--manifest-path",
                                              "packages/openmates-session-bindings/Cargo.toml", "--lib"])
                node_artifact = root / "frontend/packages/openmates-cli/native/linux-x64.node"
                python_artifact = root / "packages/openmates-python/openmates/_native.abi3.so"
                require(not node_artifact.exists() and not python_artifact.exists(), "preexisting_native_artifact")
                verify_node()
                step("napi-build", [python, "scripts/build_sdk_native.py", "--language", "npm", "--debug"])
                node_before = artifact(node_artifact)
                shutil.copyfile(node_artifact, private / "napi-preserved.node")
                (private / "napi-preserved.node").chmod(0o600)
                require(artifact(private / "napi-preserved.node")["sha256"] == node_before["sha256"], "napi_preservation")
                step("python-binding-build", [python, "-m", "pip", "install", "-e", "packages/openmates-python"])
                # The editable source module must exist independently of the Cargo lib
                # that was overwritten by the Python feature build.
                python_before = artifact(python_artifact)
                shutil.copyfile(python_artifact, private / "python-preserved.so")
                (private / "python-preserved.so").chmod(0o600)
                require(artifact(private / "python-preserved.so")["sha256"] == python_before["sha256"], "python_preservation")
                step("sdk-facade-build", [pnpm, "--filter", "openmates", "build:sdk"], 300)
                dist = {str(path.relative_to(root)): sha(regular(path))
                        for path in sorted((root / "frontend/packages/openmates-cli/dist").rglob("*")) if path.is_file()}
                require("frontend/packages/openmates-cli/dist/sdk-entry.js" in dist, "sdk_dist_missing")
                verify_node()
                step("napi-load", [node, "-e", "const m=require(process.argv[1]);if(typeof m.privacy!=='function'||typeof m.taskOrder!=='function'||typeof m.NativeSessionClient?.prototype.chatMonitorOpen!=='function'||typeof m.NativeSessionClient?.prototype.completionRecoveryEnable!=='function')process.exit(1)", str(node_artifact)], 30)
                step("python-load", [python, "-c", "import pathlib,sys;import openmates._native as m;assert pathlib.Path(m.__file__).resolve()==pathlib.Path(sys.argv[1]);assert callable(m.privacy) and callable(m.task_order);assert callable(m.NativeSessionClient.chat_monitor_open) and callable(m.NativeSessionClient.completion_recovery_enable)", str(python_artifact)], 30)
                report = private / "gate.json"
                step("real-conformance", [python, str(Path(__file__).with_name("ci_sdk_conformance_exec.py")),
                                          str(root), str(report), str(deadline)], 1500)
                stage = "final-fences"
                verify_node()
                verify_programs(root, trust)
                require(before == snapshot(root) and source == git(root, "rev-parse", "HEAD"), "source_changed")
                require(node_before == artifact(node_artifact) and python_before == artifact(python_artifact), "artifact_changed")
                require(dist == {str(path.relative_to(root)): sha(regular(path))
                                 for path in sorted((root / "frontend/packages/openmates-cli/dist").rglob("*")) if path.is_file()}, "dist_changed")
                evidence.update(gate=gate_receipt(root, json.loads(regular(report, 16 * 1024**2)), trust=trust),
                                artifacts={"npm": node_before, "python": python_before}, dist=dist,
                                loadIdentityVerified=True, sourceHeld=True, status="passed", stage="complete", code=None)
            except Exception:
                try:
                    evidence["diagnostics"] = failure_diagnostics(private, root, stage, before, trust["plan"])
                except Exception:
                    evidence["diagnostics"] = {"category": "diagnostic_unavailable", "rawUpload": False}
                raise
        evidence["cleanupVerified"] = True
    except Exception as error:
        evidence.update(status="failed", stage=stage, code=str(error) if isinstance(error, Refused) else "unclassified")
        # TemporaryDirectory owns all homes/logs/caches and removes them on unwind.
        evidence["cleanupVerified"] = owned_private is None or not owned_private.exists()
    finally:
        if commands is not None:
            evidence.update(steps=commands.steps, minimumFreeBytes=commands.minimum_free)
        write(output / "ci-sdk-conformance.json", evidence)
    results.append({"suite": TARGET, "exit_code": 0 if evidence["status"] == "passed" else 1,
                    "failed_stage": None if evidence["status"] == "passed" else evidence["stage"],
                    "failure_code": evidence["code"]})
