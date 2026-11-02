"""Closed optional x64 release payload for the existing private CI preparation.

No supplied executable is run here. Only the fixed canonical Cargo producer may
mint the receipt. Consumers recheck source/recipe/tool/runtime identity and bytes.
"""

from __future__ import annotations
from contextlib import ExitStack
import fcntl
import gzip
import hashlib
import io
import json
import math
import os
from pathlib import Path
import platform
import re
import shutil
import stat
import struct
import subprocess
import tarfile
import tempfile

NATIVE = "frontend/packages/openmates-tui-native"
ARCHIVE = "native-cli.tar.gz"
DESTINATION = "test-results/native-prepared-release"
RECEIPT = "test-results/ci-native-cli.json"
BUILD_RECEIPT = "test-results/ci-native-release-build.json"
LIMIT = 256 * 1024**2
STREAM_LIMIT = LIMIT + 4 * 1024**2 + 3 * 10240
READ_LIMIT = 1024**2
CONTRACT = {
    "version": 3,
    "archive": "fixed-ustar-two-members-bounded-gzip-v1",
    "runtimePolicy": "unambiguous-system-cache-recursive-closure-v1",
    "toolDispatch": "verified-path-before-after-v1",
    "target": "x86_64-unknown-linux-gnu",
    "rust": "1.98.1",
    "profile": "release",
    "features": "manifest-defaults",
    "incremental": "0",
    "compilerPool": "normal-effective-cpu-up-to8",
    "command": [
        "cargo",
        "+1.98.1",
        "build",
        "--release",
        "--locked",
        "--offline",
        "--manifest-path",
        NATIVE + "/Cargo.toml",
        "--bin",
        "openmates",
        "--target-dir",
        NATIVE + "/target",
    ],
}
SCOPES = frozenset(
    ["cli-native-bounded-saved-read.spec.ts", "cli-rust-core-essential.spec.ts"]
)
SOURCE_ROOTS = (NATIVE, "packages/openmates-rust")
SOURCE_FILES = (
    "scripts/check_rust_cli_package.py",
    "scripts/sync_rust_cli_assets.py",
    "backend/tests/fixtures/encryption_compatibility/legacy_layouts.json",
    "frontend/apps/web_app/tests/cli-rust-core-essential.spec.ts",
    "frontend/apps/web_app/tests/helpers/native-prepared-release.cjs",
    "frontend/apps/web_app/tests/cli-native-bounded-saved-read.spec.ts",
)
CONTROL_FILES = (
    "scripts/ci_native_release.py",
    "scripts/ci_artifacts.py",
    "scripts/ci_preparation_transport.py",
    "scripts/ci_client_owned_lifecycle.py",
    "scripts/resource_budget.py",
    ".github/workflows/isolated-tests.yml",
)
# Closed Linux/glibc dependencies. Unknown dependency names cannot be promoted.
LIBRARIES = {
    name: "/lib/x86_64-linux-gnu/" + name
    for name in (
        "libc.so.6",
        "libgcc_s.so.1",
        "libm.so.6",
        "libpthread.so.0",
        "libdl.so.2",
        "librt.so.1",
        "ld-linux-x86-64.so.2",
    )
}
LOADER = "/lib64/ld-linux-x86-64.so.2"
LOADER_CACHE = Path("/etc/ld.so.cache")
CACHE_INSPECTOR = Path("/usr/sbin/ldconfig")
CACHE_LIMIT = 4 * 1024**2


# No candidate/loader execution: a fixed root-owned inspector lists cache bytes.
# Ambiguous ABI/hwcap entries are refused, even if the host could choose one.
def loader_environment():
    require(
        not any(
            v
            for k, v in os.environ.items()
            if k.startswith("LD_") or k in ("GLIBC_TUNABLES", "GLIBC_HWCAPS")
        ),
        "loader_environment",
    )
    require(not os.path.lexists("/etc/ld.so.preload"), "loader_preload")


def system_digest(path, maximum=LIMIT):
    actual = path.resolve(strict=True)
    for parent in (actual.parent, *actual.parent.parents):
        info = parent.stat()
        require(info.st_uid == 0 and not info.st_mode & 0o022, "system_owner")
    info = actual.stat()
    require(
        stat.S_ISREG(info.st_mode)
        and info.st_uid == 0
        and not info.st_mode & 0o022
        and 0 < info.st_size <= maximum,
        "system_file",
    )
    before = (
        info.st_dev,
        info.st_ino,
        info.st_size,
        info.st_mtime_ns,
        info.st_ctime_ns,
    )
    value = sha(actual)
    after = actual.stat()
    require(
        before
        == (
            after.st_dev,
            after.st_ino,
            after.st_size,
            after.st_mtime_ns,
            after.st_ctime_ns,
        ),
        "system_changed",
    )
    return value


def cache_entries(text):
    require(type(text) is str and len(text.encode()) <= 1024**2, "loader_cache_output")
    rows = {}
    for line in text.splitlines():
        if "=>" not in line:
            continue
        match = re.fullmatch(r"\s*([^\s/]+) \(([^)]+)\) => (/[^\s]+)\s*", line)
        require(match is not None, "loader_cache_format")
        name, abi, path = match.groups()
        rows.setdefault(name, []).append((abi, path))
    require(rows, "loader_cache_format")
    return rows


def loader_cache():
    loader_environment()
    cache_sha = system_digest(LOADER_CACHE, CACHE_LIMIT)
    inspector_sha = system_digest(CACHE_INSPECTOR)
    with tempfile.TemporaryFile() as output:
        subprocess.run(
            [str(CACHE_INSPECTOR), "-p", "-C", str(LOADER_CACHE)],
            stdout=output,
            stderr=subprocess.DEVNULL,
            check=True,
            timeout=10,
            env={"PATH": "/usr/bin:/bin", "LC_ALL": "C"},
        )
        output.seek(0)
        raw = output.read(1024**2 + 1)
    require(len(raw) <= 1024**2, "loader_cache_output")
    require(
        system_digest(LOADER_CACHE, CACHE_LIMIT) == cache_sha
        and system_digest(CACHE_INSPECTOR) == inspector_sha,
        "loader_cache_changed",
    )
    return {"sha256": cache_sha, "inspectorSha256": inspector_sha}, cache_entries(
        raw.decode("ascii")
    )


def cache_dependency(rows, name):
    entries = rows.get(name, [])
    # glibc x86-64 accepts exactly flag 0x303. ldconfig prints flag 0x003
    # as libc6 and 0x803 as libc6,x32: both are provably incompatible.
    # Only these two exact spellings may be skipped. Unknown/hwcap labels
    # remain refusals, including labels attached to an incompatible ABI.
    require(
        all(abi in ("libc6", "libc6,x32", "libc6,x86-64") for abi, _ in entries),
        "loader_cache_selection",
    )
    compatible = [entry for entry in entries if entry[0] == "libc6,x86-64"]
    require(len(compatible) == 1, "loader_cache_ambiguous")
    abi, path = compatible[0]
    require(
        path in ("/lib/x86_64-linux-gnu/" + name, "/usr/lib/x86_64-linux-gnu/" + name),
        "loader_cache_selection",
    )
    return Path(path)


CONTRACT.update(
    inputRoots=list(SOURCE_ROOTS),
    inputFiles=list(SOURCE_FILES),
    controlFiles=list(CONTROL_FILES),
)


class Refused(ValueError):
    pass


DIAGNOSTIC_PRIVATE = "test-results/native-release-diagnostic-private/receipt.json"
DIAGNOSTIC_PUBLIC = "test-results/ci-native-release-diagnostic.json"
DIAGNOSTIC_STAGES = frozenset(
    (
        "admission",
        "identity",
        "resources",
        "fetch",
        "package-inputs",
        "release",
        "input-recheck",
        "runtime",
        "package",
        "complete",
        "unclassified",
    )
)
DIAGNOSTIC_CODES = frozenset(
    (
        "isolated",
        "host",
        "harness",
        "changed_inputs",
        "producer",
        "identity",
        "digest",
        "runtime",
        "build",
        "cpu_admission",
        "resource_snapshot",
        "resource_output",
        "reservation_bound",
        "tool_path",
        "tool_dispatch_digest",
        "tool",
        "tool_closure",
        "tool_configuration",
        "source",
        "source_identity",
        "dirty_source",
        "manifest",
        "lock",
        "profile",
        "features",
        "loader_environment",
        "loader_preload",
        "loader_cache_format",
        "loader_cache_output",
        "loader_cache_changed",
        "loader_cache_ambiguous",
        "loader_cache_selection",
        "loader_redirection",
        "loader_self",
        "loader",
        "dependency",
        "system_owner",
        "system_file",
        "system_changed",
        "runtime_closure",
        "archive_destination",
        "archive_exists",
        "metadata",
        "io_error",
        "invalid",
        "timeout",
        "interrupted",
        "child_failed",
        "cleanup_unverified",
        "launch_failed",
        "lifecycle_failed",
        "diagnostic_unavailable",
        "unclassified",
    )
)


def diagnostic_identity(source, tree, harness, run=None):
    # Bad ambient/input strings never become diagnostic text.
    def clean(v):
        return v if type(v) is str and re.fullmatch("[a-f0-9]{40}", v) else None

    run = os.environ.get("GITHUB_RUN_ID", "") if run is None else run
    return {
        "sourceCommit": clean(source),
        "sourceTree": clean(tree),
        "harnessCommit": clean(harness),
        "runId": run
        if type(run) is str and re.fullmatch("[1-9][0-9]{0,20}", run)
        else None,
    }


def diagnostic_error(error):
    if type(error) is Refused and len(error.args) == 1 and type(error.args[0]) is str:
        code = error.args[0].removeprefix("native_release:")
        if code in DIAGNOSTIC_CODES:
            return code
    if isinstance(error, subprocess.TimeoutExpired):
        return "timeout"
    if isinstance(error, subprocess.CalledProcessError):
        return "child_failed"
    if isinstance(error, OSError):
        return "io_error"
    if isinstance(error, ValueError):
        return "invalid"
    return "unclassified"


def diagnostic_valid(value, expected):
    if type(value) is not dict or set(value) != {
        "schemaVersion",
        "kind",
        "identity",
        "status",
        "stage",
        "firstFailure",
        "cleanupVerified",
        "observedBeforeCleanup",
        "proofAccepted",
    }:
        return False
    if (
        value.get("schemaVersion") != 1
        or value.get("kind") != "native-release-preparation-diagnostic"
        or value.get("identity") != expected
    ):
        return False
    if type(value.get("status")) is not str or value["status"] not in (
        "incomplete",
        "passed",
        "failed",
    ):
        return False
    if type(value.get("stage")) is not str or value["stage"] not in DIAGNOSTIC_STAGES:
        return False
    if (
        any(
            type(value.get(k)) is not bool
            for k in ("cleanupVerified", "observedBeforeCleanup", "proofAccepted")
        )
        or value["proofAccepted"]
    ):
        return False
    first = value["firstFailure"]
    if first is not None:
        if type(first) is not dict or set(first) != {
            "stage",
            "code",
            "childExitCode",
            "recordedBeforeCleanup",
        }:
            return False
        if type(first["stage"]) is not str or first["stage"] not in DIAGNOSTIC_STAGES:
            return False
        if (
            type(first["code"]) is not str
            or first["code"] not in DIAGNOSTIC_CODES
            or type(first["recordedBeforeCleanup"]) is not bool
        ):
            return False
        code = first["childExitCode"]
        if code is not None and (type(code) is not int or not -64 <= code <= 255):
            return False
    return value["status"] != "passed" or (
        first is None and value["cleanupVerified"] is True
    )


def diagnostic_checkpoint(
    root,
    identity,
    stage,
    *,
    failure=None,
    child_code=None,
    before_cleanup=False,
    passed=False,
    cleanup=False,
):
    require(stage in DIAGNOSTIC_STAGES, "diagnostic_unavailable")
    directory = root / Path(DIAGNOSTIC_PRIVATE).parent
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    safe_directory(directory, root)
    path = root / DIAGNOSTIC_PRIVATE
    value = {
        "schemaVersion": 1,
        "kind": "native-release-preparation-diagnostic",
        "identity": identity,
        "status": "incomplete",
        "stage": stage,
        "firstFailure": None,
        "cleanupVerified": False,
        "observedBeforeCleanup": False,
        "proofAccepted": False,
    }
    if path.exists() or path.is_symlink():
        regular(path, maximum=8192, private=True)
        old = json.loads(path.read_bytes())
        require(diagnostic_valid(old, identity), "diagnostic_unavailable")
        value = old
    value.update(
        stage=stage,
        cleanupVerified=bool(cleanup),
        observedBeforeCleanup=value["observedBeforeCleanup"] or bool(before_cleanup),
    )
    if failure is not None and value["firstFailure"] is None:
        code = diagnostic_error(failure)
        child_code = (
            child_code if type(child_code) is int and -64 <= child_code <= 255 else None
        )
        value["firstFailure"] = {
            "stage": stage,
            "code": code,
            "childExitCode": child_code,
            "recordedBeforeCleanup": bool(before_cleanup),
        }
    value["status"] = (
        "failed"
        if value["firstFailure"] is not None
        else "passed"
        if passed
        else "incomplete"
    )
    require(diagnostic_valid(value, identity), "diagnostic_unavailable")
    raw = canonical(value)
    require(len(raw) <= 8192, "diagnostic_unavailable")
    fd, name = tempfile.mkstemp(prefix=".diagnostic-", dir=directory)
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "wb") as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        Path(name).replace(path)
    finally:
        if Path(name).exists():
            Path(name).unlink()
    return value


def publish_diagnostic(root, source, tree, harness):
    expected = diagnostic_identity(source, tree, harness)
    require(all(expected.values()), "diagnostic_unavailable")
    try:
        regular(root / DIAGNOSTIC_PRIVATE, maximum=8192, private=True)
        value = json.loads((root / DIAGNOSTIC_PRIVATE).read_bytes())
        require(diagnostic_valid(value, expected), "diagnostic_unavailable")
    except (OSError, ValueError, Refused):
        value = {
            "schemaVersion": 1,
            "kind": "native-release-preparation-diagnostic",
            "identity": expected,
            "status": "failed",
            "stage": "unclassified",
            "firstFailure": {
                "stage": "unclassified",
                "code": "diagnostic_unavailable",
                "childExitCode": None,
                "recordedBeforeCleanup": False,
            },
            "cleanupVerified": False,
            "observedBeforeCleanup": False,
            "proofAccepted": False,
        }
    tooling = Path(__file__).resolve().parent.parent
    path = tooling / DIAGNOSTIC_PUBLIC
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    safe_directory(path.parent, tooling)
    fd, name = tempfile.mkstemp(prefix=".native-public-", dir=path.parent)
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "wb") as stream:
            stream.write(canonical(value))
        Path(name).replace(path)
    finally:
        if Path(name).exists():
            Path(name).unlink()
    return value


def require(ok, code):
    if not ok:
        raise Refused("native_release:" + code)


def canonical(value):
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode()


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def sha(path):
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for b in iter(lambda: stream.read(1024**2), b""):
            h.update(b)
    return h.hexdigest()


def regular(path, *, maximum=LIMIT, private=False, cargo_output=False):
    info = path.lstat()
    require(
        stat.S_ISREG(info.st_mode)
        and (info.st_nlink >= 1 if cargo_output else info.st_nlink == 1)
        and info.st_size <= maximum,
        "file",
    )
    require(info.st_uid == os.getuid() and not info.st_mode & 0o022, "owner_mode")
    if private:
        require(not info.st_mode & 0o077, "private")
    return info


def git(root, *args):
    return subprocess.check_output(["/usr/bin/git", "-C", str(root), *args], timeout=30)


def cargo_configuration(root):
    # Cargo searches cwd ancestors and CARGO_HOME. Record absence too; configuration
    # drift must refuse promotion rather than silently changing compiler flags.
    folders = [
        ("cwd-" + str(i), p / ".cargo") for i, p in enumerate((root, *root.parents))
    ]
    folders.append(
        ("cargo-home", Path(os.environ.get("CARGO_HOME", str(Path.home() / ".cargo"))))
    )
    rows = {}
    for label, folder in folders:
        for name in ("config", "config.toml"):
            path = folder / name
            key = label + "/" + name
            require(not path.is_symlink(), "cargo_config")
            rows[key] = sha(path) if path.is_file() else None
    return rows


def safe_directory(path, root):
    require(
        root.is_absolute() and root.resolve() == root and path.is_relative_to(root),
        "destination",
    )
    for current in (path, *path.parents):
        info = current.lstat()
        require(
            stat.S_ISDIR(info.st_mode)
            and info.st_uid == os.getuid()
            and not info.st_mode & 0o022,
            "directory_owner_mode",
        )
        if current == root:
            return
    raise Refused("native_release:destination")


def source_identity(root, source, tree):
    require(
        re.fullmatch("[a-f0-9]{40}", source) and re.fullmatch("[a-f0-9]{40}", tree),
        "source",
    )
    require(
        git(root, "rev-parse", "HEAD").decode().strip() == source
        and git(root, "rev-parse", "HEAD^{tree}").decode().strip() == tree,
        "source",
    )
    paths = (
        git(
            root,
            "ls-tree",
            "-r",
            "--name-only",
            source,
            "--",
            *SOURCE_ROOTS,
            *SOURCE_FILES,
        )
        .decode()
        .splitlines()
    )
    require(
        all(p in paths for p in SOURCE_FILES)
        and all(
            r + "/Cargo.toml" in paths and r + "/Cargo.lock" in paths
            for r in SOURCE_ROOTS
        ),
        "closure",
    )
    require(
        not git(
            root,
            "status",
            "--porcelain",
            "--untracked-files=all",
            "--",
            *SOURCE_ROOTS,
            *SOURCE_FILES,
        ),
        "dirty_source",
    )
    require(len(paths) <= 20000, "closure_bound")
    result = {}
    for name in paths:
        path = root / name
        require(
            not path.is_symlink()
            and all(not p.is_symlink() for p in path.parents if p.is_relative_to(root)),
            "source_symlink",
        )
        regular(path)
        raw = git(root, "show", source + ":" + name)
        require(sha(path) == digest(raw), "dirty_source")
        result[name] = digest(raw)
    # The complete tree plus conservative compiler inputs closes assets/tests,
    # manifests/locks, both Rust crates, literal fixtures and package guards.
    return result


def elf(raw):
    require(len(raw) >= 64 and raw[:7] == b"\x7fELF\x02\x01\x01", "elf")
    require(
        struct.unpack_from("<H", raw, 16)[0] in (2, 3)
        and struct.unpack_from("<H", raw, 18)[0] == 62,
        "target",
    )


def dynamic_dependencies(binary):
    dynamic = subprocess.check_output(
        ["/usr/bin/readelf", "-d", str(binary)], timeout=10, text=True
    )
    require(len(dynamic) <= 1024**2, "dynamic_bound")
    tags = re.findall(r"\(([A-Z0-9_]+)\)", dynamic)
    require(
        not set(tags).intersection(
            {"RPATH", "RUNPATH", "FILTER", "AUXILIARY", "AUDIT", "DEPAUDIT", "CONFIG"}
        ),
        "loader_redirection",
    )
    require(not re.search(r"\(FLAGS_1\).*\bNODEFLIB\b", dynamic), "loader_redirection")
    names = re.findall(r"\(NEEDED\).*\[([^\]]+)\]", dynamic)
    require(
        len(names) == len(set(names)) and all(n in LIBRARIES for n in names),
        "dependency",
    )
    return names


def inspect_elf(path):
    with path.open("rb") as stream:
        elf(stream.read(64))


def runtime_identity(binary):
    require(platform.system() == "Linux" and platform.machine() == "x86_64", "host")
    inspect_elf(binary)
    # Inspect original candidate first; reject redirect tags before any cache use.
    pending = dynamic_dependencies(binary)
    require(pending, "dependency")
    headers = subprocess.check_output(
        ["/usr/bin/readelf", "-l", str(binary)], timeout=10, text=True
    )
    require(
        re.findall(r"Requesting program interpreter: ([^\]]+)\]", headers) == [LOADER],
        "loader",
    )
    cache, rows = loader_cache()
    dependencies = {}
    while pending:
        name = pending.pop()
        if name in dependencies:
            continue
        selected = cache_dependency(rows, name)
        before = system_digest(selected)
        if name == "ld-linux-x86-64.so.2":
            require(before == system_digest(Path(LOADER)), "loader_self")
        inspect_elf(selected)
        # Same redirect policy applies to EVERY transitive library, not basenames.
        children = dynamic_dependencies(selected)
        require(system_digest(selected) == before, "system_changed")
        dependencies[name] = {"path": str(selected), "sha256": before}
        pending.extend(children)
    require(
        system_digest(LOADER_CACHE, CACHE_LIMIT) == cache["sha256"],
        "loader_cache_changed",
    )
    loader_environment()
    return {
        "osRelease": system_digest(Path("/etc/os-release")),
        "loader": system_digest(Path(LOADER)),
        "loaderCache": cache,
        "dependencies": dict(sorted(dependencies.items())),
    }


def tool_identity():
    directory = Path.home() / ".rustup/toolchains/1.98.1-x86_64-unknown-linux-gnu/bin"
    result = {}
    for name in ("cargo", "rustc"):
        path = directory / name
        require(path.is_file(), "tool")
        text = subprocess.check_output(
            [str(path), "--version"], timeout=10, text=True
        ).strip()
        require(text.startswith(name + " 1.98.1 "), "tool")
        result[name] = {"sha256": sha(path), "version": text}
    host = subprocess.check_output(
        [str(directory / "rustc"), "-vV"], timeout=10, text=True
    )
    require("host: x86_64-unknown-linux-gnu\n" in host, "target")
    rustup = Path.home() / ".cargo/bin/rustup"
    require(rustup.is_file(), "tool")
    result["rustup"] = {
        "sha256": sha(rustup),
        "version": subprocess.check_output(
            [str(rustup), "--version"], timeout=10, text=True
        ).strip(),
    }
    for name in ("cc", "ld", "ar", "readelf", "python3", "git"):
        result[name] = {"sha256": sha(Path("/usr/bin") / name)}
    library = directory.parent / "lib"
    files = [p for p in library.iterdir() if p.is_file()]
    host = library / "rustlib/x86_64-unknown-linux-gnu"
    files.extend(
        p
        for d in (host / "lib", host / "bin")
        if d.exists()
        for p in d.rglob("*")
        if p.is_file()
    )
    require(
        files
        and len(files) <= 4096
        and sum(p.stat().st_size for p in files) <= 2 * 1024**3,
        "tool_closure",
    )
    result["hostCompilerLibraries"] = {
        str(p.relative_to(directory.parent)): sha(p) for p in sorted(files)
    }
    return result


def verify_dispatch(environment, tools):
    """Bind every PATH-resolved proxy/tool to the declared fixed executable.

    Rustup proxies may be symlinks OR hardlinks, but never merely matching names
    or version strings. This check runs before AND after every producer phase.
    """
    rustup = Path.home() / ".cargo/bin/rustup"
    resolved = {}
    for name in (
        "cargo",
        "rustc",
        "rustdoc",
        "rustup",
        "python3",
        "cc",
        "ld",
        "ar",
        "readelf",
        "git",
    ):
        selected = shutil.which(name, path=environment["PATH"])
        expected = (
            rustup
            if name in ("cargo", "rustc", "rustdoc", "rustup")
            else Path("/usr/bin") / name
        )
        require(
            selected is not None and os.path.samefile(selected, expected), "tool_path"
        )
        key = "rustup" if expected == rustup else name
        require(sha(Path(selected)) == tools[key]["sha256"], "tool_dispatch_digest")
        resolved[name] = str(Path(selected).absolute())
    directory = Path.home() / ".rustup/toolchains/1.98.1-x86_64-unknown-linux-gnu/bin"
    for name in ("cargo", "rustc"):
        require(sha(directory / name) == tools[name]["sha256"], "tool_dispatch_digest")
    return resolved


def identity(root, source, tree, harness):
    loader_environment()
    tooling = Path(__file__).resolve().parent.parent
    require(re.fullmatch("[a-f0-9]{40}", harness), "harness")
    require(git(tooling, "rev-parse", "HEAD").decode().strip() == harness, "harness")
    return {
        "sourceCommit": source,
        "sourceTree": tree,
        "harnessCommit": harness,
        "contract": CONTRACT,
        "inputs": source_identity(root, source, tree),
        "tools": tool_identity(),
        "cargoConfiguration": cargo_configuration(root),
        "recipe": {p: sha(tooling / p) for p in CONTROL_FILES},
    }


def package(root, output, source, tree, harness):
    diagnostic = diagnostic_identity(source, tree, harness)
    diagnostic_checkpoint(root, diagnostic, "package", before_cleanup=True)
    try:
        wanted = identity(root, source, tree, harness)
        receipt = root / BUILD_RECEIPT
        regular(receipt, maximum=4 * 1024**2, private=True)
        value = json.loads(receipt.read_text())
        require(
            value.get("status") == "passed" and value.get("cleanupVerified") is True,
            "producer",
        )
        require(value.get("identity") == wanted, "identity")
        binary = root / NATIVE / "target/release/openmates"
        regular(binary, cargo_output=True)
        require(
            sha(binary) == value.get("elfSha256")
            and binary.stat().st_size == value.get("elfBytes"),
            "digest",
        )
        require(runtime_identity(binary) == value.get("runtime"), "runtime")
        meta = canonical(value)
        require(len(meta) <= 4 * 1024**2, "metadata")
        require(output == root / "test-results/ci-preparation", "archive_destination")
        output.mkdir(parents=True, exist_ok=True)
        safe_directory(output, root)
        archive = output / ARCHIVE
        require(not archive.exists() and not archive.is_symlink(), "archive_exists")
        fd, name = tempfile.mkstemp(prefix=".native-cli-", suffix=".tmp", dir=output)
        temporary = Path(name)
        try:
            with os.fdopen(fd, "wb") as raw_archive:
                with tarfile.open(
                    fileobj=raw_archive, mode="w:gz", format=tarfile.USTAR_FORMAT
                ) as stream:
                    for member, raw, mode in [
                        ("native-cli/identity.json", meta, 0o600),
                        ("native-cli/openmates", binary.read_bytes(), 0o700),
                    ]:
                        info = tarfile.TarInfo(member)
                        info.size = len(raw)
                        info.mode = mode
                        info.uid = os.getuid()
                        info.gid = os.getgid()
                        stream.addfile(info, io.BytesIO(raw))
            temporary.replace(archive)
        except BaseException as error:
            try:
                diagnostic_checkpoint(
                    root,
                    diagnostic,
                    "package",
                    failure=error,
                    before_cleanup=True,
                    cleanup=True,
                )
            except BaseException:
                pass
            raise
        finally:
            if temporary.exists():
                temporary.unlink()

        result = {
            "path": ARCHIVE,
            "size": archive.stat().st_size,
            "sha256": sha(archive),
            "destination": DESTINATION,
            "identitySha256": digest(meta),
        }
        diagnostic_checkpoint(root, diagnostic, "complete", passed=True, cleanup=True)
        return result
    except BaseException as error:
        try:
            diagnostic_checkpoint(
                root, diagnostic, "package", failure=error, before_cleanup=True
            )
        except BaseException:
            pass
        raise


class _BoundedGzip:
    """Every allocation request is bounded BEFORE gzip/tar metadata parsing."""

    def __init__(self, stream):
        self.stream = gzip.GzipFile(fileobj=stream, mode="rb")
        self.total = 0

    def read(self, count):
        require(type(count) is int and 0 <= count <= READ_LIMIT, "read_bound")
        require(self.total + count <= STREAM_LIMIT, "decompression_bound")
        raw = self.stream.read(count)
        self.total += len(raw)
        return raw

    def exact(self, count):
        require(0 <= count <= READ_LIMIT, "read_bound")
        raw = self.read(count)
        require(len(raw) == count, "truncated")
        return raw

    def payload(self, count):
        # Caller validates member length before this method. Read in bounded
        # chunks, never allocate from an extension/header-provided length.
        result = bytearray()
        while count:
            raw = self.exact(min(count, READ_LIMIT))
            result.extend(raw)
            count -= len(raw)
        return bytes(result)


def _octal(raw):
    value = raw.rstrip(b"\0 ")
    require(bool(value) and all(c in b"01234567" for c in value), "tar_number")
    return int(value, 8)


def _member(header):
    require(len(header) == 512, "header")
    # No general TarFile parser: PAX/GNU extensions never consume a body.
    require(
        header[156:157] == b"0"
        and header[257:263] == b"ustar\0"
        and header[263:265] == b"00",
        "header_form",
    )
    require(not any(header[157:257]) and not any(header[345:512]), "header_form")
    require(not any(header[265:329]), "header_form")
    require(
        _octal(header[148:156]) == sum(header[:148]) + 8 * 32 + sum(header[156:]),
        "header_checksum",
    )
    require(_octal(header[136:148]) == 0, "header_time")
    _octal(header[108:116])
    _octal(header[116:124])
    name = header[:100].split(b"\0", 1)[0]
    require(header[len(name) : 100] == b"\0" * (100 - len(name)), "header_name")
    require(name in (b"native-cli/identity.json", b"native-cli/openmates"), "members")
    mode = _octal(header[100:108])
    size = _octal(header[124:136])
    limit = LIMIT if name.endswith(b"openmates") else 4 * 1024**2
    require(
        0 < size <= limit and mode == (0o700 if name.endswith(b"openmates") else 0o600),
        "member",
    )
    return name.decode("ascii"), size


def validate_payload(archive, item, wanted):
    require(
        isinstance(item, dict)
        and set(item) == {"path", "size", "sha256", "destination", "identitySha256"},
        "archive",
    )
    regular(archive)
    require(
        item.get("path") == ARCHIVE and item.get("destination") == DESTINATION,
        "archive",
    )
    require(
        type(item.get("size")) is int
        and archive.stat().st_size == item["size"]
        and sha(archive) == item.get("sha256"),
        "archive_digest",
    )
    rows = {}
    with archive.open("rb") as compressed:
        reader = _BoundedGzip(compressed)
        for _ in range(2):
            name, size = _member(reader.exact(512))
            require(name not in rows, "members")
            rows[name] = reader.payload(size)
            padding = (-size) % 512
            require(not any(reader.exact(padding)), "padding")
        require(
            set(rows) == {"native-cli/openmates", "native-cli/identity.json"}, "members"
        )
        require(reader.exact(1024) == b"\0" * 1024, "end_marker")
        # USTAR writer pads to a record boundary. Reject nonzero/trailing
        # members and bound aggregate decompression, including gzip members.
        while True:
            remaining = STREAM_LIMIT - reader.total
            require(remaining > 0, "decompression_bound")
            tail = reader.read(min(READ_LIMIT, remaining))
            if not tail:
                break
            require(not any(tail), "trailing_data")

    def unique(pairs):
        result = {}
        for key, value in pairs:
            require(key not in result, "duplicate_key")
            result[key] = value
        return result

    meta = json.loads(rows["native-cli/identity.json"], object_pairs_hook=unique)
    raw = rows["native-cli/openmates"]
    require(isinstance(meta, dict), "metadata")
    require(item.get("identitySha256") == digest(canonical(meta)), "identity_digest")
    require(
        set(meta)
        == {
            "status",
            "cleanupVerified",
            "identity",
            "elfSha256",
            "elfBytes",
            "runtime",
            "resources",
        },
        "metadata",
    )
    resources = meta.get("resources", {})
    require(
        isinstance(resources, dict)
        and set(resources) == {"compilerJobs", "snapshotSha256"}
        and type(resources["compilerJobs"]) is int
        and 1 <= resources["compilerJobs"] <= 8
        and isinstance(resources["snapshotSha256"], str)
        and re.fullmatch("[a-f0-9]{64}", resources["snapshotSha256"]),
        "resources",
    )
    require(
        meta.get("identity") == wanted
        and meta.get("status") == "passed"
        and meta.get("cleanupVerified") is True,
        "identity",
    )
    require(
        meta.get("elfSha256") == digest(raw) and meta.get("elfBytes") == len(raw),
        "digest",
    )
    elf(raw)
    return meta, raw


def restore(root, input_dir, item, source, tree, harness):
    require(
        input_dir == root / "test-results/ci-preparation-download", "archive_source"
    )
    safe_directory(input_dir, root)
    wanted = identity(root, source, tree, harness)
    meta, raw = validate_payload(input_dir / ARCHIVE, item, wanted)
    parent = root / "test-results"
    safe_directory(parent, root)
    destination = root / DESTINATION
    require(
        not destination.exists() and not destination.is_symlink(), "destination_exists"
    )
    destination.mkdir(mode=0o700)
    try:
        binary = destination / "openmates"
        fd = os.open(
            binary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o700
        )
        with os.fdopen(fd, "wb") as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        require(runtime_identity(binary) == meta.get("runtime"), "runtime")
        require(sha(binary) == meta["elfSha256"], "digest")
        record = {
            "status": "passed",
            "binary": DESTINATION + "/openmates",
            "elfSha256": meta["elfSha256"],
            "elfBytes": meta["elfBytes"],
            "identity": wanted,
            "runtime": meta["runtime"],
            "producerIdentitySha256": digest(canonical(meta)),
            "resources": meta["resources"],
        }
        receipt = root / RECEIPT
        require(not receipt.exists() and not receipt.is_symlink(), "receipt_exists")
        fd = os.open(
            receipt, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600
        )
        with os.fdopen(fd, "wb") as stream:
            stream.write(canonical(record) + b"\n")
            stream.flush()
            os.fsync(stream.fileno())
        return record
    except BaseException:
        # This function just created this private directory; no shared artifact
        # or unrelated target/source path is removed on refusal.
        shutil.rmtree(destination)
        raise


def source_eligible(root, source):
    # Eligibility only, never execution proof. Old registered subjects without
    # the source consumer keep their original preparation behavior.
    try:
        result = subprocess.run(
            [
                "/usr/bin/git",
                "-C",
                str(root),
                "cat-file",
                "-e",
                source
                + ":frontend/apps/web_app/tests/helpers/native-prepared-release.cjs",
            ],
            capture_output=True,
            timeout=5,
        )
        return result.returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


def compiler_jobs(snapshot):
    require(isinstance(snapshot, dict), "cpu_admission")
    affinity = snapshot.get("cpuAffinity")
    quota = snapshot.get("cpuQuota")
    require(type(affinity) is int and 1 <= affinity <= 4096, "cpu_admission")
    require(isinstance(snapshot.get("cgroup"), dict), "cpu_admission")
    cpu = snapshot["cgroup"].get("cpu", {})
    require(isinstance(cpu, dict), "cpu_admission")
    require(cpu.get("state") in ("limited", "unlimited"), "cpu_admission")
    require(
        quota is None
        if cpu["state"] == "unlimited"
        else type(quota) in (int, float) and math.isfinite(quota) and quota >= 1,
        "cpu_admission",
    )
    jobs = min(8, affinity, math.floor(quota) if quota is not None else affinity)
    require(jobs >= 1, "cpu_admission")
    return jobs


def resource_snapshot(value):
    def integer(v):
        return type(v) is int and 0 <= v <= 2**53 - 1

    def nullable(v):
        return v is None or integer(v)

    def finite(v):
        return type(v) in (int, float) and math.isfinite(v) and v > 0

    integers = [
        "schemaVersion",
        "cpuAffinity",
        "memoryAvailableBytes",
        "targetAllocatedBytes",
        "diskFreeBytes",
        "diskTotalBytes",
        "observedReservationBytes",
        "reservationFloorBytes",
        "reservationBytes",
        "compilerJobCapacity",
    ]
    require(
        type(value) is dict
        and set(value)
        == set(
            integers
            + ["cpuQuota", "cgroupMemoryMaxBytes", "cgroupMemoryCurrentBytes", "cgroup"]
        )
        and all(integer(value[k]) for k in integers),
        "resource_snapshot",
    )
    require(
        value["schemaVersion"] == 1
        and value["cpuAffinity"] >= 1
        and value["diskTotalBytes"] > 0
        and value["observedReservationBytes"]
        == 2 * value["targetAllocatedBytes"] + 2 * 1024**3
        and value["reservationFloorBytes"] == 6 * 1024**3
        and value["reservationBytes"]
        == max(value["observedReservationBytes"], value["reservationFloorBytes"])
        and value["reservationBytes"] <= 130 * 1024**3,
        "resource_snapshot",
    )
    require(
        nullable(value["cgroupMemoryMaxBytes"])
        and nullable(value["cgroupMemoryCurrentBytes"])
        and (value["cpuQuota"] is None or finite(value["cpuQuota"]))
        and type(value["cgroup"]) is dict
        and set(value["cgroup"]) == {"cpu", "memory"},
        "resource_snapshot",
    )
    for name in ("cpu", "memory"):
        v = value["cgroup"][name]
        memory = name == "memory"
        require(
            type(v) is dict
            and set(v) == {"constraints", "membership", "scope", "state", "version"}
            and v["version"] in (None, "v1", "v2")
            and v["membership"] in ("root", "nested", "unavailable")
            and v["scope"] == "visible-ancestors"
            and type(v["constraints"]) is list
            and len(v["constraints"]) <= 65,
            "resource_snapshot",
        )
        if memory:
            require(
                all(
                    type(x) is dict
                    and set(x) == {"currentBytes", "maxBytes"}
                    and nullable(x["maxBytes"])
                    and nullable(x["currentBytes"])
                    for x in v["constraints"]
                ),
                "resource_snapshot",
            )
            limits = [
                x["maxBytes"] for x in v["constraints"] if x["maxBytes"] is not None
            ]
        else:
            require(
                all(x is None or finite(x) for x in v["constraints"]),
                "resource_snapshot",
            )
            limits = [x for x in v["constraints"] if x is not None]
        require(
            v["state"]
            == (
                "limited"
                if limits
                else "unlimited"
                if v["constraints"]
                else "controller-unavailable"
            )
            and (
                v["version"] is not None
                or v["membership"] == "unavailable"
                and not v["constraints"]
            ),
            "resource_snapshot",
        )
    cpu = value["cgroup"]["cpu"]
    memory = value["cgroup"]["memory"]
    quotas = [x for x in cpu["constraints"] if x is not None]
    limits = [x["maxBytes"] for x in memory["constraints"] if x["maxBytes"] is not None]
    require(
        value["cpuQuota"] == (min(quotas) if quotas else None)
        and value["cgroupMemoryMaxBytes"] == (min(limits) if limits else None)
        and value["cgroupMemoryCurrentBytes"]
        == (
            memory["constraints"][0]["currentBytes"] if memory["constraints"] else None
        ),
        "resource_snapshot",
    )
    capacity = (
        0
        if cpu["state"] == "controller-unavailable"
        else min(
            8,
            math.floor(
                min(
                    value["cpuAffinity"],
                    value["cpuQuota"]
                    if value["cpuQuota"] is not None
                    else value["cpuAffinity"],
                )
            ),
        )
    )
    require(value["compilerJobCapacity"] == capacity, "resource_snapshot")
    return value


def resource_program(root):
    source = (
        root / "frontend/apps/web_app/tests/cli-rust-core-essential.spec.ts"
    ).read_text()
    require(len(source) <= 1024**2, "resource_source")
    matches = re.findall(
        r"const\s+NATIVE_RESOURCE_SNAPSHOT\s*=\s*String\.raw`([\s\S]+?)\n`;", source
    )
    require(len(matches) == 1, "resource_source")
    return matches[0] + "\n"


def build(root, source, tree, harness):
    require(
        os.environ.get("CI") == "true" and os.environ.get("GITHUB_ACTIONS") == "true",
        "isolated",
    )
    diagnostic = diagnostic_identity(source, tree, harness)
    stage = "admission"
    last = {}
    passed = False
    diagnostic_checkpoint(root, diagnostic, stage, before_cleanup=True)
    try:
        stage = "identity"
        diagnostic_checkpoint(root, diagnostic, stage, before_cleanup=True)
        before = identity(root, source, tree, harness)
        try:
            from scripts import resource_budget, ci_client_owned_lifecycle as lifecycle
        except ModuleNotFoundError:
            import resource_budget
            import ci_client_owned_lifecycle as lifecycle
        output = root / "test-results/native-release-build"
        output.mkdir(mode=0o700)
        native = root / NATIVE
        (native / "target").mkdir(exist_ok=True)
        env = {
            k: os.environ[k]
            for k in ["HOME", "CARGO_HOME", "RUSTUP_HOME"]
            if k in os.environ
        }
        env["PATH"] = str(Path.home() / ".cargo/bin") + ":/usr/bin:/bin"
        env["RUSTUP_HOME"] = str(Path.home() / ".rustup")
        env.update(
            CI="true",
            LANG="C.UTF-8",
            RUSTUP_TOOLCHAIN="1.98.1",
            CARGO_INCREMENTAL="0",
            CARGO_NET_OFFLINE="true",
            CARGO_TERM_COLOR="never",
        )
        steps = [
            (
                "resources",
                ["python3", "-I", "-c", resource_program(root), str(native / "target")],
                15,
            ),
            (
                "fetch",
                [
                    "cargo",
                    "+1.98.1",
                    "fetch",
                    "--locked",
                    "--manifest-path",
                    str(native / "Cargo.toml"),
                ],
                120,
            ),
            (
                "package-inputs",
                ["python3", str(root / "scripts/check_rust_cli_package.py")],
                30,
            ),
            (
                "release",
                [
                    x if not x.startswith(NATIVE + "/") else str(root / x)
                    for x in CONTRACT["command"]
                ],
                540,
            ),
        ]
        stage = "admission"
        diagnostic_checkpoint(root, diagnostic, stage, before_cleanup=True)
        with (native / "target/.native-prepared-release.lock").open("a+") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            with ExitStack() as admission:
                try:
                    admission.enter_context(
                        resource_budget.reserve(
                            root, 6 * 1024**3, operation="native-prepared-release"
                        )
                    )
                    for name, argv, timeout in steps:
                        stage = name
                        diagnostic_checkpoint(
                            root, diagnostic, stage, before_cleanup=True
                        )
                        folder = output / name
                        folder.mkdir(mode=0o700)
                        last = {}
                        step_env = {**env}
                        if name == "fetch":
                            step_env["CARGO_NET_OFFLINE"] = "false"
                        selected = verify_dispatch(step_env, before["tools"])
                        dispatch = list(argv)
                        dispatch[0] = (
                            selected[dispatch[0]]
                            if dispatch[0] in selected
                            else dispatch[0]
                        )

                        def observed(value):
                            reason = value.get("reason")
                            code = value.get("returncode")
                            failure = None
                            if reason == "exited" and code is not None and code != 0:
                                failure = Refused("child_failed")
                            elif reason in (
                                "timeout",
                                "interrupted",
                                "launch_failed",
                                "lifecycle_failed",
                                "cleanup_unverified",
                            ):
                                failure = Refused(reason)
                            diagnostic_checkpoint(
                                root,
                                diagnostic,
                                stage,
                                failure=failure,
                                child_code=code,
                                before_cleanup=True,
                            )

                        code = lifecycle.run_owned(
                            dispatch,
                            cwd=root,
                            env=step_env,
                            out=folder,
                            attempt=last,
                            timeout=timeout,
                            before_cleanup=observed,
                        )
                        verify_dispatch(step_env, before["tools"])
                        require(
                            code == 0
                            and last.get("cleanupVerified") is True
                            and last.get("cleanup", {}).get("groupEmpty") is True
                            and last.get("cleanup", {}).get("inspectionUnknown")
                            is False,
                            "build",
                        )
                        if name == "resources":
                            log = folder / "process.log"
                            require(log.stat().st_size <= 262144, "resource_output")
                            snapshot = resource_snapshot(json.loads(log.read_text()))
                            jobs = compiler_jobs(snapshot)
                            extra = snapshot["reservationBytes"] - 6 * 1024**3
                            if extra:
                                admission.enter_context(
                                    resource_budget.reserve(
                                        root,
                                        extra,
                                        operation="native-prepared-release-growth",
                                    )
                                )
                            env["CARGO_BUILD_JOBS"] = str(jobs)
                            resources = {
                                "compilerJobs": jobs,
                                "snapshotSha256": sha(log),
                            }
                    stage = "input-recheck"
                    diagnostic_checkpoint(root, diagnostic, stage, before_cleanup=True)
                    require(
                        identity(root, source, tree, harness) == before,
                        "changed_inputs",
                    )
                    binary = native / "target/release/openmates"
                    regular(binary, cargo_output=True)
                    stage = "runtime"
                    diagnostic_checkpoint(root, diagnostic, stage, before_cleanup=True)
                    runtime = runtime_identity(binary)
                except BaseException as error:
                    try:
                        diagnostic_checkpoint(
                            root,
                            diagnostic,
                            stage,
                            failure=error,
                            before_cleanup=True,
                            cleanup=last.get("cleanupVerified", False),
                        )
                    except BaseException:
                        pass
                    raise
        record = {
            "status": "passed",
            "cleanupVerified": True,
            "identity": before,
            "elfSha256": sha(binary),
            "elfBytes": binary.stat().st_size,
            "runtime": runtime,
            "resources": resources,
        }
        passed = True
        diagnostic_checkpoint(root, diagnostic, "complete", passed=True, cleanup=True)
    except BaseException as error:
        try:
            diagnostic_checkpoint(
                root,
                diagnostic,
                stage,
                failure=error,
                before_cleanup=True,
                cleanup=last.get("cleanupVerified", False),
            )
        except BaseException:
            pass
        raise
    finally:
        if not passed:
            record = {
                "status": "failed",
                "cleanupVerified": last.get("cleanupVerified", False),
            }
        receipt = root / BUILD_RECEIPT
        fd = os.open(
            receipt, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600
        )
        with os.fdopen(fd, "w") as stream:
            json.dump(record, stream, sort_keys=True)
