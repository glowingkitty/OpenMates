#!/usr/bin/env python3
"""Isolated-CI-only packaged SDK v1/native same-vector check, no CLI fallback.

Run AFTER the normal locked native + npm builds and npm pack --ignore-scripts.
This does not install tools/dependencies, build locally, alter capability plans,
change default SDK imports, or accept the default-root breaking transition.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import platform
import re
import shutil
import stat
import subprocess
import sys
import tarfile
import tempfile

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT / "frontend/packages/openmates-cli"
FIXTURE = ROOT / "tests/sdk-conformance/fixtures/api-key-foundation.json"
DRIVER = ROOT / "tests/sdk-conformance/runners/api-key-foundation.py"
CONSUMER_SOURCE = "export {RustApiKeyClient} from 'openmates/sdk/v1';\nexport const resolvedEntrypoint = import.meta.resolve('openmates/sdk/v1');\n"


_PACKAGED_CHECK_DIAGNOSTICS = {
    'ci_environment': ('admission', 'check_ci.environment', 'isolated_ci_required'),
    'linux_platform': ('admission', 'check_ci.platform', 'linux_required'),
    'native_architecture': ('admission', 'native_name.architecture', 'architecture_unsupported'),
    'archive_path': ('archive', 'extract_sdk.path', 'unsafe_member'),
    'archive_duplicate': ('archive', 'extract_sdk.duplicate', 'duplicate_member'),
    'archive_regular': ('archive', 'extract_sdk.regular', 'nonregular_member'),
    'archive_extract': ('archive', 'extract_sdk.extract', 'member_unavailable'),
    'archive_assets': ('archive', 'extract_sdk.required', 'required_asset_missing'),
    'archive_exports': ('archive', 'extract_sdk.exports', 'entrypoint_mismatch'),
    'ambient_state': ('ambient', 'reject_ambient_state.profile', 'ambient_state_observed'),
    'cli_source': ('ambient', 'reject_ambient_state.cli', 'cli_source_observed'),
    'unexpected_execve': ('ambient', 'reject_ambient_state.execve', 'unexpected_executable'),
    'unexpected_execveat': ('ambient', 'reject_ambient_state.execveat', 'indirect_executable'),
    'vector_order': ('result', 'validate_result.order', 'vector_set_or_order'),
    'vector_adapter': ('result', 'validate_result.adapter', 'native_result_required'),
    'npm_tool': ('package', 'check_actual_built_package.npm', 'npm_missing'),
    'npm_pack': ('package', 'check_actual_built_package.pack', 'archive_creation_failed'),
    'npm_archive': ('package', 'check_actual_built_package.archive', 'archive_count_or_type'),
    'built_mode_argument': ('admission', 'main.built_mode', 'caller_archive_rejected'),
    'archive_argument': ('admission', 'main.archive', 'archive_required'),
    'checker_tools': ('admission', 'main.tools', 'node_or_strace_missing'),
    'native_asset': ('identity', 'main.native_asset', 'native_asset_missing'),
    'fixture_vectors': ('identity', 'main.fixture_vectors', 'maintained_vector_count'),
    'fixture_credentials': ('identity', 'main.fixture_credentials', 'fixture_credentials_missing'),
    'native_identity': ('identity', 'main.native_identity', 'native_hash_mismatch'),
    'barrel_identity': ('identity', 'main.barrel_identity', 'barrel_hash_mismatch'),
    'native_vectors': ('vectors', 'main.native_vectors', 'native_vector_process_failed'),
    'fixture_identity': ('result', 'main.fixture_identity', 'fixture_hash_mismatch'),
}


def _packaged_error(message: str, check: str) -> ValueError:
    """Keep the original exception/message; attach only a fixed checker tag."""
    error = ValueError(message)
    if isinstance(check, str) and check in _PACKAGED_CHECK_DIAGNOSTICS:
        error._packaged_sdk_check = check
    return error


def _packaged_failure_line(error: BaseException) -> str:
    """One finite line; the unchanged CI parent already retains its byte hash.

    No exception message, package/path/URL, native output or raw trace is read.
    A closed hash catalog can attribute this line without exporting raw stderr.
    """
    check = error.__dict__.get("_packaged_sdk_check") if type(error) is ValueError else None
    if isinstance(check, str) and check in _PACKAGED_CHECK_DIAGNOSTICS:
        phase, location, reason = _PACKAGED_CHECK_DIAGNOSTICS[check]
        category = "ValueError"
    else:
        check, phase, location = "unclassified", "unclassified", "checker"
        category, reason = "Exception", "unexpected_error"
        for kind, label, code in (
            (json.JSONDecodeError, "JSONDecodeError", "json_decode_error"),
            (subprocess.TimeoutExpired, "TimeoutExpired", "timeout"),
            (OSError, "OSError", "os_error"),
            (tarfile.TarError, "TarError", "archive_error"),
            (ValueError, "ValueError", "value_error"),
        ):
            if isinstance(error, kind):
                category, reason = label, code
                break
    line = (
        "packaged SDK v1 check refused: " + category
        + "; check=" + check + "; phase=" + phase
        + "; location=" + location + "; reason=" + reason
    )

    if check == "native_vectors" and type(error) is ValueError:
        context = error.__dict__.get("_native23_context")
        if _native23_valid_context(context):
            return line + _native23_failure_suffix(context)
    return line


_NATIVE23_SITES = ("runner_import", "arguments", "fixture", "peer_start", "adapter_launch", "adapter_return", "result_decode", "result_identity", "value_assertions", "wire_assertions", "peer_cleanup", "case_complete", "complete")
_NATIVE23_ERRORS = ("none", "assertion", "timeout", "json", "import", "os", "value", "other")
_NATIVE23_DETAILS = ("none", "node_module_missing", "node_export_missing", "node_dlopen", "node_syntax", "node_type", "node_reference", "sdk_invalid_argument", "sdk_forbidden", "sdk_cancelled", "sdk_native_failure", "adapter_unknown")
_NATIVE23_STATUSES = ("none", "zero", "one", "two", "not_executable", "missing_executable", "sig_abort", "sig_kill", "sig_segv", "sig_term", "other")


def _native23_status(code):
    if code is not None and type(code) is not int:
        return "other"
    return {None: "none", 0: "zero", 1: "one", 2: "two", 126: "not_executable", 127: "missing_executable", -6: "sig_abort", -9: "sig_kill", -11: "sig_segv", -15: "sig_term"}.get(code, "other")


def _native23_error(error):
    for kind, label in ((AssertionError, "assertion"), (subprocess.TimeoutExpired, "timeout"), (json.JSONDecodeError, "json"), (ImportError, "import"), (OSError, "os"), (ValueError, "value")):
        if isinstance(error, kind):
            return label
    return "other"


def _native23_node_detail(stderr):
    text = stderr[-65536:] if isinstance(stderr, str) else ""
    for marker, label in (("ERR_MODULE_NOT_FOUND", "node_module_missing"), ("ERR_PACKAGE_PATH_NOT_EXPORTED", "node_export_missing"), ("ERR_DLOPEN_FAILED", "node_dlopen"), ("SyntaxError:", "node_syntax"), ("TypeError:", "node_type"), ("ReferenceError:", "node_reference")):
        if marker in text:
            return label
    for code in ("invalid_argument", "forbidden", "cancelled", "native_failure"):
        if re.search(r"(?m)^\s*code: ['\"]" + code + r"['\"]", text):
            return "sdk_" + code
    return "adapter_unknown"


class _Native23Probe:
    """Best-effort fixed metadata only; never a source or success authority."""
    def __init__(self, path, fixture_hash, ids):
        self.path, self.ids = path, tuple(ids)
        self.value = {"schemaVersion": 1, "fixtureSha256": fixture_hash, "caseId": "none", "site": "runner_import", "error": "none", "adapterStatus": "none", "detail": "none"}

    def save(self):
        try:
            raw = (json.dumps(self.value, sort_keys=True) + "\n").encode()
            if len(raw) > 4096:
                return
            fd = os.open(self.path, os.O_WRONLY | os.O_CREAT | os.O_NOFOLLOW | os.O_NONBLOCK, 0o600)
            with os.fdopen(fd, "wb", closefd=True) as stream:
                info = os.fstat(stream.fileno())
                if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_nlink != 1 or info.st_mode & 0o077:
                    return
                stream.truncate(0)
                stream.write(raw)
        except (OSError, ValueError, TypeError):
            pass

    def mark(self, site, case=None):
        if self.value["error"] != "none" or site not in _NATIVE23_SITES or (case is not None and case not in self.ids):
            return
        if case is not None and case != self.value["caseId"]:
            self.value.update(adapterStatus="none", detail="none")
        self.value.update(site=site, caseId=case if case is not None else "none")
        self.save()

    def child(self, result):
        self.value.update(site="adapter_return", adapterStatus=_native23_status(result.returncode), detail=_native23_node_detail(result.stderr) if result.returncode else "none")
        self.save()

    def failed(self, error):
        if self.value["error"] == "none":
            self.value["error"] = _native23_error(error)
            self.save()


def _native23_probe_from_environment(root):
    """Only the existing isolated package consumer can enable private progress."""
    try:
        if any(os.environ.get(key) != value for key, value in {"CI": "true", "GITHUB_ACTIONS": "true", "OPENMATES_CI_ISOLATED": "1"}.items()):
            return None
        consumer = Path(os.environ.get("OPENMATES_SDK_V1_PACKAGE_CONSUMER", ""))
        if not consumer.is_absolute() or consumer.resolve() != consumer or consumer.name != "consumer":
            return None
        parent = consumer.parent
        info, current = parent.stat(), consumer.stat()
        if not parent.name.startswith("openmates-sdk-v1-package-") or info.st_uid != os.getuid() or info.st_mode & 0o077 or not stat.S_ISDIR(info.st_mode) or not stat.S_ISDIR(current.st_mode) or current.st_uid != os.getuid():
            return None
        path = root / "tests/sdk-conformance/fixtures/api-key-foundation.json"
        with os.fdopen(os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK), "rb") as stream:
            info = os.fstat(stream.fileno())
            if not stat.S_ISREG(info.st_mode) or info.st_size > 1024 * 1024:
                return None
            raw = stream.read(1024 * 1024 + 1)
        if len(raw) > 1024 * 1024:
            return None
        ids = [row["id"] for row in json.loads(raw)["capabilities"]["sdk.configuration"]["vectors"]]
        if len(ids) != 23 or len(set(ids)) != 23 or not all(isinstance(value, str) and re.fullmatch(r"[A-Za-z0-9_.-]{1,120}", value) for value in ids):
            return None
        return _Native23Probe(consumer / "native23-progress.json", sha(raw), ids)
    except (OSError, ValueError, TypeError, KeyError):
        return None


def _native23_launcher_error(stderr):
    text = stderr[-65536:] if isinstance(stderr, str) else ""
    for pattern, label in ((r"strace:[^\n]*(?:ptrace|PTRACE)[^\n]*(?:permitted|denied)", "strace_ptrace_denied"), (r"strace:[^\n]*(?:Cannot find|No such file|not found)", "strace_exec_missing"), (r"strace:[^\n]*(?:invalid|unrecognized)", "strace_option_refused"), (r"ModuleNotFoundError:|ImportError:", "python_import"), (r"PermissionError:", "python_permission"), (r"SyntaxError:", "python_syntax")):
        if re.search(pattern, text):
            return label
    return "launcher_unknown"


def _native23_context(process, consumer, fixture_bytes, vectors):
    context = {"probe": "missing", "case": "none", "site": "launch", "error": _native23_launcher_error(process.stderr), "status": "launcher_" + _native23_status(process.returncode)}
    path = consumer / "native23-progress.json"
    try:
        if path.is_symlink():
            raise ValueError("unsafe diagnostic")
        with os.fdopen(os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK), "rb") as stream:
            info = os.fstat(stream.fileno())
            if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_nlink != 1 or info.st_mode & 0o077 or info.st_size > 4096:
                raise ValueError("unsafe diagnostic")
            value = json.loads(stream.read(4097), object_pairs_hook=_native23_unique_fields)
        ids = [row["id"] for row in vectors]
        fields = {"schemaVersion", "fixtureSha256", "caseId", "site", "error", "adapterStatus", "detail"}
        if not isinstance(value, dict) or set(value) != fields or type(value["schemaVersion"]) is not int or value["schemaVersion"] != 1 or value["fixtureSha256"] != sha(fixture_bytes) or value["caseId"] not in ["none", *ids] or value["site"] not in _NATIVE23_SITES or value["error"] not in _NATIVE23_ERRORS or value["adapterStatus"] not in _NATIVE23_STATUSES or value["detail"] not in _NATIVE23_DETAILS:
            raise ValueError("unknown diagnostic")
        context.update(probe="runner", case="none" if value["caseId"] == "none" else "case_" + str(ids.index(value["caseId"])).zfill(2), site=value["site"], error=value["error"])
        if value["site"] == "adapter_return" and value["adapterStatus"] not in {"none", "zero"}:
            context["status"] = "adapter_" + value["adapterStatus"]
            if value["error"] == "assertion" and value["detail"] != "none":
                context["error"] = "assertion." + value["detail"]
    except FileNotFoundError:
        pass
    except (OSError, ValueError, TypeError, KeyError):
        context.update(probe="invalid", case="none", site="launch", error="invalid_progress")
    return context


def _native23_unique_fields(pairs):
    value = {}
    for key, item in pairs:
        if key in value:
            raise ValueError("duplicate diagnostic field")
        value[key] = item
    return value


def _native23_error_with_context(process, consumer, fixture_bytes, vectors):
    error = _packaged_error("packaged native same-vector execution failed", "native_vectors")
    try:
        error._native23_context = _native23_context(process, consumer, fixture_bytes, vectors)
    except Exception:
        # Diagnostic failure cannot replace the original refusal or its cleanup.
        pass
    return error


def _native23_valid_context(context):
    if not isinstance(context, dict) or set(context) != {"probe", "case", "site", "error", "status"}:
        return False
    allowed = {
        "probe": {"missing", "invalid", "runner"},
        "case": {"none", *("case_" + str(index).zfill(2) for index in range(23))},
        "site": {"launch", *_NATIVE23_SITES},
        "error": {"strace_ptrace_denied", "strace_exec_missing", "strace_option_refused", "python_import", "python_permission", "python_syntax", "launcher_unknown", "invalid_progress", *_NATIVE23_ERRORS, *("assertion." + value for value in _NATIVE23_DETAILS if value != "none")},
        "status": {scope + value for scope in ("launcher_", "adapter_") for value in _NATIVE23_STATUSES},
    }
    return all(isinstance(context[key], str) and context[key] in values for key, values in allowed.items())


def _native23_failure_suffix(context):
    return "; probe=" + context["probe"] + "; case=" + context["case"] + "; site=" + context["site"] + "; error=" + context["error"] + "; status=" + context["status"]


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def check_ci(environment: dict[str, str]) -> None:
    for key, expected in {"CI": "true", "GITHUB_ACTIONS": "true", "OPENMATES_CI_ISOLATED": "1"}.items():
        if environment.get(key) != expected:
            raise _packaged_error("packaged SDK runtime requires isolated GitHub CI", 'ci_environment')
    if sys.platform != "linux":
        raise _packaged_error("this syscall observation hook is Linux-only; Mac/Windows acceptance is separate", 'linux_platform')


def native_name() -> str:
    arch = {"x86_64": "x64", "amd64": "x64", "aarch64": "arm64", "arm64": "arm64"}.get(platform.machine().lower())
    if arch is None:
        raise _packaged_error("unsupported packaged native artifact platform", 'native_architecture')
    return "linux-" + arch + ".node"


def extract_sdk(archive: Path, destination: Path, native: str) -> None:
    """Only exact actual npm archive files; no symlink to source/dependencies."""
    with tarfile.open(archive, "r:gz") as handle:
        names: set[str] = set()
        for member in handle:
            path = PurePosixPath(member.name)
            if path.is_absolute() or ".." in path.parts or not path.parts or path.parts[0] != "package":
                raise _packaged_error("unsafe package archive", 'archive_path')
            if member.name in names:
                raise _packaged_error("duplicate package archive entry", 'archive_duplicate')
            names.add(member.name)
            # Do not extract unrelated CLI templates/fixtures/offline runtimes.
            selected = member.name == "package/package.json" or member.name.startswith("package/dist/") or member.name == "package/native/" + native
            if not selected or member.isdir():
                continue
            if not member.isfile() or member.issym() or member.islnk():
                raise _packaged_error("nonregular SDK package file", 'archive_regular')
            target = destination.joinpath(*path.parts[1:])
            target.parent.mkdir(parents=True, exist_ok=True)
            source = handle.extractfile(member)
            if source is None:
                raise _packaged_error("missing actual package file", 'archive_extract')
            with source, target.open("xb") as output:
                shutil.copyfileobj(source, output)
    required = [destination / "package.json", destination / "dist/sdk-session-v1-entry.js", destination / "dist/sdk-session-v1-entry.d.ts", destination / "native" / native]
    if not all(path.is_file() for path in required):
        raise _packaged_error("actual versioned SDK/native/declaration asset missing", 'archive_assets')
    manifest = json.loads(required[0].read_text())
    if manifest.get("name") != "openmates" or manifest.get("exports", {}).get("./sdk/v1", {}).get("default") != "./dist/sdk-session-v1-entry.js":
        raise _packaged_error("actual package must publish openmates/sdk/v1", 'archive_exports')


def reject_ambient_state(trace: Path, blocked: list[Path], sentinel: str, executables: set[Path] | None = None) -> None:
    """Observe actual Node+native addon file syscalls, never claim zero filesystem.

    Python peer coordinator is included too. Toolchain/package/workspace stay
    outside synthetic HOME/XDG; native/core/API access uses explicit fixture data.
    Raw trace is temporary private test data and never enters committed evidence.
    """
    with trace.open(errors="replace") as original:
        for line in original:
            if any(str(path) in line for path in blocked) or sentinel in line:
                raise _packaged_error("ambient CLI/auth-state access observed", 'ambient_state')
            if '/dist/cli.js' in line or '/src/cli.ts' in line:
                raise _packaged_error("CLI execution/source access observed", 'cli_source')
            if executables is not None:
                launch = re.search(r'\bexecve\("([^"\n]+)"', line)
                if launch and Path(launch.group(1)).resolve() not in executables:
                    raise _packaged_error("unexpected executable attempt; no CLI launcher permitted", 'unexpected_execve')
                if "execveat(" in line:
                    raise _packaged_error("unexpected indirect executable attempt", 'unexpected_execveat')


def validate_result(result: dict, vectors: list[dict]) -> list[str]:
    expected = [vector["id"] for vector in vectors]
    actual = result.get("results", [])
    if result.get("status") != "passed" or result.get("language") != "npm" or [row.get("id") for row in actual] != expected:
        raise _packaged_error("same maintained vector set/order required", 'vector_order')
    if any(row.get("status") != "passed" or row.get("adapter") != "actual-rust-api-key-library" for row in actual):
        raise _packaged_error("genuine native adapter result required", 'vector_adapter')
    return expected


def check_actual_built_package(output: Path) -> int:
    """Actual local archive creation, then SAME original packaged checker.

    No caller receipt/status/fixture/class is accepted as positive evidence.
    Existing CI must already build both facade and native assets.
    """
    check_ci(dict(os.environ))
    npm = shutil.which("npm")
    if npm is None:
        raise _packaged_error("existing npm required; no install or skip", 'npm_tool')
    with tempfile.TemporaryDirectory(prefix="openmates-sdk-v1-release-archive-") as temp:
        directory = Path(temp).resolve()
        pack_command = [npm, "pack", str(PACKAGE), "--ignore-scripts", "--json", "--pack-destination", str(directory)]
        packed = subprocess.run(pack_command, cwd=ROOT, capture_output=True, text=True, timeout=120)
        if packed.returncode != 0:
            raise _packaged_error("actual built-package archive creation failed", 'npm_pack')
        archives = list(directory.glob("*.tgz"))
        if len(archives) != 1 or archives[0].is_symlink() or not archives[0].is_file():
            raise _packaged_error("one actual regular archive required", 'npm_archive')
        # Re-enter only the archive branch of the SAME finite checker. The
        # actual native23 algorithms, deadlines, -s4096 and private trace stay
        # shared; built mode cannot return a caller's JSON or success bit.
        return main([str(archives[0]), "--output", str(output)])


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("tarball", type=Path, nargs="?", help="actual npm pack --ignore-scripts output, built in isolated CI")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--pack-built", action="store_true", help="create the actual local archive from already-built assets, then run the same fixed check")
    args = parser.parse_args(argv)
    check_ci(dict(os.environ))
    if args.pack_built:
        if args.tarball is not None:
            raise _packaged_error("fixed built-package mode does not accept a caller archive", 'built_mode_argument')
        return check_actual_built_package(args.output)
    if args.tarball is None:
        raise _packaged_error("actual archive or fixed built-package mode required", 'archive_argument')
    trace_tool, node = shutil.which("strace"), shutil.which("node")
    if trace_tool is None or node is None:
        raise _packaged_error("required existing Node/strace tool missing; no install or skip fallback", 'checker_tools')
    artifact = args.tarball.resolve(strict=True)
    original_native = PACKAGE / "native" / native_name()
    if not original_native.is_file():
        raise _packaged_error("original actual locked-build native artifact required", 'native_asset')
    fixture_bytes = FIXTURE.read_bytes()
    suite = json.loads(fixture_bytes)["capabilities"]["sdk.configuration"]
    if len(suite["vectors"]) != 23:
        raise _packaged_error("reviewed maintained23 vector set required", 'fixture_vectors')
    # All native calls receive the same explicit fixture API key/account/options.
    if not suite["account"].get("api_key"):
        raise _packaged_error("explicit maintained fixture credentials required", 'fixture_credentials')
    with tempfile.TemporaryDirectory(prefix="openmates-sdk-v1-package-") as temp:
        scratch = Path(temp).resolve()
        consumer = scratch / "consumer"
        package = consumer / "node_modules/openmates"
        package.mkdir(parents=True)
        extract_sdk(artifact, package, native_name())
        if sha((package / "native" / native_name()).read_bytes()) != sha(original_native.read_bytes()):
            raise _packaged_error("packaged native addon differs from actual built artifact", 'native_identity')
        if sha((package / "dist/sdk-session-v1-entry.js").read_bytes()) != sha((PACKAGE / "dist/sdk-session-v1-entry.js").read_bytes()):
            raise _packaged_error("packaged versioned barrel differs from actual built artifact", 'barrel_identity')
        (consumer / "package.json").write_text('{"private":true,"type":"module"}\n')
        (consumer / "consume.mjs").write_text(CONSUMER_SOURCE)
        # Poison synthetic ambient CLI stores, never copy a real account/profile.
        home, config, state, cache = [scratch / name for name in ["synthetic-home", "synthetic-xdg-config", "synthetic-xdg-state", "synthetic-xdg-cache"]]
        sentinel = "synthetic-ambient-credential-MUST-NOT-BE-USED"
        for directory in [home / ".openmates", config / "openmates", state / "openmates", cache / "openmates"]:
            directory.mkdir(parents=True)
            for name in ["session.json", "credentials.json", "config.json"]:
                (directory / name).write_text(json.dumps({"api_key": sentinel, "ws_token": sentinel, "master_key": sentinel}))
        environment = {key: value for key, value in os.environ.items() if not key.startswith("OPENMATES_") and key not in {"NODE_OPTIONS", "NODE_PATH", "PYTHONPATH"}}
        environment["PATH"] = str(Path(node).parent) + os.pathsep + str(Path(sys.executable).parent)
        environment.update({"OPENMATES_CI_ISOLATED": "1", "OPENMATES_SDK_V1_PACKAGE_CONSUMER": str(consumer), "HOME": str(home), "XDG_CONFIG_HOME": str(config), "XDG_STATE_HOME": str(state), "XDG_CACHE_HOME": str(cache), "OPENMATES_STATE_DIR": str(home / ".openmates"), "OPENMATES_API_KEY": sentinel, "PYTHONNOUSERSITE": "1", "PYTHONDONTWRITEBYTECODE": "1"})
        trace = scratch / "private-native-file-syscalls.trace"
        # Existing independent peer/vector/oracle algorithm is reused unchanged.
        command = [trace_tool, "-f", "-qq", "-s", "4096", "-e", "trace=%file", "-o", str(trace), sys.executable, str(DRIVER), "--language", "npm"]
        process = subprocess.run(command, cwd=ROOT, env=environment, capture_output=True, text=True, timeout=3000)
        # Never echo credentials, native diagnostics, subprocess stderr/raw trace.
        if process.returncode != 0:
            raise _native23_error_with_context(process, consumer, fixture_bytes, suite["vectors"])
        reject_ambient_state(trace, [home, config, state, cache], sentinel, {Path(node).resolve(), Path(sys.executable).resolve()})
        result = json.loads(process.stdout)
        ids = validate_result(result, suite["vectors"])
        if result.get("fixtureSha256") != sha(fixture_bytes):
            raise _packaged_error("actual maintained fixture hash mismatch", 'fixture_identity')
        receipt = {"status": "passed", "kind": "packaging-specific native npm check, NOT capability addition", "entrypoint": "openmates/sdk/v1", "artifactSha256": sha(artifact.read_bytes()), "nativeSha256": sha(original_native.read_bytes()), "fixtureSha256": sha(fixture_bytes), "vectorIds": ids, "nativeAdapter": "actual-rust-api-key-library", "ambientSyntheticCliStateAccess": False, "explicitFixtureCredentials": True, "rawTracePublished": False, "cliLauncherObserved": False, "limits": "Linux host only; same23 configuration vectors. Rust/Python plans unchanged; no universal filesystem/API parity/default-root transition acceptance."}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(receipt, indent=2) + "\n")
    print(json.dumps({"status": "passed", "entrypoint": "openmates/sdk/v1", "vectors": len(ids), "output": str(args.output)}))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (ValueError, OSError, subprocess.TimeoutExpired, json.JSONDecodeError, tarfile.TarError) as error:
        # Fixed safe error categories only, no underlying native/raw syscall data.
        print(_packaged_failure_line(error), file=sys.stderr)
        raise SystemExit(1)
