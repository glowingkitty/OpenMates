"""Fixed Rust/WASM compilation gate; no browser runtime or SDK conformance proof."""
from __future__ import annotations

from contextlib import ExitStack

import errno
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
# Independent official registry metadata, verified 2026-10-24 (not the archive
# being checked): https://index.crates.io/wa/sm/wasm-bindgen-cli and
# https://crates.io/api/v1/crates/wasm-bindgen-cli/0.2.129
BINDGEN_CRATE_PIN = ("0.2.129", "5fd044ed178958a277eeaf21f3d384287b0f4428d38c019141df01da9c03168c")
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


def detach_installed_bindgen(work, deadline, diagnostic=None):
    """Detach only the closed Cargo install/build hardlink set, before execution.

    Unknown links are never adopted. The provenance reader below still requires
    nlink==1; this preparation cannot make an arbitrary hardlink admissible.
    """
    def note(substage, **values):
        # Observation never authorizes a guard or replaces a filesystem failure.
        try:
            if diagnostic is not None:
                diagnostic.update(substage=substage, **values)
        except Exception:
            pass

    def observed(key, value):
        try:
            if diagnostic is not None:
                diagnostic[key] = value
        except Exception:
            pass
        return value

    note("detach-work")
    sdk.require(work.is_absolute() and work.resolve() == work, "packaging")
    binary = work / ".ci-bindgen/bin/wasm-bindgen"
    note("detach-stat")
    original = binary.lstat()
    note("detach-link-guard", detachOriginalLinks=min(original.st_nlink, 65536),
         binaryBytes=min(original.st_size, 64 * 1024**2 + 1),
         binaryRegular=stat.S_ISREG(original.st_mode), binaryOwner=original.st_uid == os.getuid(),
         binaryModeSafe=not bool(original.st_mode & 0o022), binaryExecutable=bool(original.st_mode & 0o111),
         binarySingleLink=original.st_nlink == 1, binarySizeWithinLimit=0 < original.st_size <= 64 * 1024**2)
    if original.st_nlink == 1:
        return
    sdk.require(original.st_nlink in {2, 3} and stat.S_ISREG(original.st_mode)
                and original.st_uid == os.getuid() and not original.st_mode & 0o022
                and original.st_mode & 0o111 and 0 < original.st_size <= 64 * 1024**2, "packaging")
    directories = [work, work / ".ci-bindgen", binary.parent,
                   work / ".ci-bindgen-target", work / ".ci-bindgen-target/release",
                   work / ".ci-bindgen-target/release/deps"]
    directory_ids = []
    for index, directory in enumerate(directories):
        note("detach-directory-stat", detachDirectoryIndex=index)
        before = directory.lstat()
        note("detach-directory-guard", detachDirectoryOwner=before.st_uid == os.getuid(),
             detachDirectoryModeSafe=not bool(before.st_mode & 0o022), detachDirectoryRegular=stat.S_ISDIR(before.st_mode))
        sdk.require(directory.resolve() == directory and stat.S_ISDIR(before.st_mode)
                    and before.st_uid == os.getuid() and not before.st_mode & 0o022, "packaging")
        directory_ids.append((before.st_dev, before.st_ino, before.st_mode, before.st_uid, before.st_gid))

    def current():
        note("detach-current-deadline")
        sdk.require(time.monotonic() < deadline, "deadline")
        for index, (directory, expected) in enumerate(zip(directories, directory_ids)):
            note("detach-current-directory", detachDirectoryIndex=index)
            now = directory.lstat()
            sdk.require(directory.resolve() == directory
                        and (now.st_dev, now.st_ino, now.st_mode, now.st_uid, now.st_gid) == expected, "packaging")

    current()
    with ExitStack() as candidate_handles:
        candidates = [work / ".ci-bindgen-target/release/wasm-bindgen"]
        note("detach-scan-open")
        with os.scandir(directories[-1]) as entries:
            for index, entry in enumerate(entries):
                note("detach-scan-bound", detachEntriesSeen=min(index + 1, 4097))
                sdk.require(index < 4096, "packaging")
                if re.fullmatch(r"wasm_bindgen-[0-9a-f]{16}", entry.name):
                    candidates.append(Path(entry.path))
                    note("detach-alias-bound", detachAliasCount=min(len(candidates), 3))
                    sdk.require(len(candidates) <= 2, "packaging")
        aliases = []
        candidate_records = []
        missing_candidates = []

        def missing_current(candidate, parent_fd, captured_parent):
            # Unlike source/link metadata, this directory is never mutated by
            # detachment. Its timestamps also fence create-then-remove races.
            sdk.require(candidate.parent.resolve() == candidate.parent
                        and sdk.file_identity(os.fstat(parent_fd)) == sdk.file_identity(captured_parent)
                        and sdk.file_identity(candidate.parent.lstat()) == sdk.file_identity(captured_parent), "packaging")
            try:
                os.stat(candidate.name, dir_fd=parent_fd, follow_symlinks=False)
            except FileNotFoundError as error:
                sdk.require(error.errno == errno.ENOENT, "packaging")
            else:
                sdk.require(False, "packaging")
            sdk.require(sdk.file_identity(os.fstat(parent_fd)) == sdk.file_identity(captured_parent)
                        and sdk.file_identity(candidate.parent.lstat()) == sdk.file_identity(captured_parent), "packaging")
        for index, candidate in enumerate(candidates):
            note("detach-alias-identity", detachAliasIndex=index)
            sdk.require(observed("detachAliasPathMatches", candidate.resolve() == candidate), "packaging")
            captured_parent = candidate.parent.lstat()
            try:
                candidate_before = candidate.lstat()
            except FileNotFoundError as error:
                # Only an initially absent entry is optional. Disappearance
                # after this observation or any other open failure still fails.
                sdk.require(error.errno == errno.ENOENT, "packaging")
                parent_fd = os.open(candidate.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
                candidate_handles.callback(os.close, parent_fd)
                missing_current(candidate, parent_fd, captured_parent)
                missing_candidates.append((candidate, parent_fd, captured_parent))
                continue
            candidate_fd = os.open(candidate, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
            candidate_handles.callback(os.close, candidate_fd)
            candidate_stat = os.fstat(candidate_fd)
            sdk.require(stat.S_ISREG(candidate_stat.st_mode) and candidate_stat.st_uid == os.getuid()
                        and not candidate_stat.st_mode & 0o022 and candidate_stat.st_mode & 0o111
                        and 0 < candidate_stat.st_size <= 64 * 1024**2
                        and sdk.file_identity(candidate_stat) == sdk.file_identity(candidate_before)
                        and sdk.file_identity(candidate_stat) == sdk.file_identity(candidate.lstat()), "packaging")
            same_inode = (candidate_stat.st_dev, candidate_stat.st_ino) == (original.st_dev, original.st_ino)
            observed("detachAliasIdentityMatches", sdk.file_identity(candidate_stat) == sdk.file_identity(original))
            if same_inode:
                sdk.require(sdk.file_identity(candidate_stat) == sdk.file_identity(original), "packaging")
                aliases.append(candidate)
            else:
                # A separate safe Cargo executable is not an alias; never modify it.
                sdk.require(candidate_stat.st_nlink == 1, "packaging")
            candidate_records.append((candidate, candidate_fd, candidate_stat, same_inode))

        def candidates_current(remaining=None):
            for candidate, parent_fd, captured_parent in missing_candidates:
                missing_current(candidate, parent_fd, captured_parent)
            for candidate, candidate_fd, captured, same_inode in candidate_records:
                expected = remaining if same_inode and remaining is not None else captured
                sdk.require(candidate.resolve() == candidate
                            and sdk.file_identity(os.fstat(candidate_fd)) == sdk.file_identity(expected)
                            and sdk.file_identity(candidate.lstat()) == sdk.file_identity(expected), "packaging")

        current()
        candidates_current()
        note("detach-link-count", detachAliasCount=min(len(aliases), 3))
        sdk.require(original.st_nlink == len(aliases) + 1, "packaging")
        for index, alias in enumerate(aliases):
            note("detach-alias-identity", detachAliasIndex=index)
            sdk.require(observed("detachAliasPathMatches", alias.resolve() == alias)
                        and observed("detachAliasIdentityMatches", sdk.file_identity(alias.lstat()) == sdk.file_identity(original)), "packaging")
        # Keep the source descriptor open through publication, so path replacement
        # cannot conceal source mutation or an unexpected surviving link.
        note("detach-source-open")
        source_fd = os.open(binary, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        temporary = binary.with_name(".wasm-bindgen-detached")
        copied = None
        directory_fd = None
        try:
            note("detach-source-identity")
            sdk.require(sdk.file_identity(os.fstat(source_fd)) == sdk.file_identity(original), "packaging")
            note("detach-source-read")
            data = sdk.regular(binary)
            digest = sdk.sha(data)
            current()
            note("detach-source-identity")
            sdk.require(sdk.file_identity(os.fstat(source_fd)) == sdk.file_identity(original), "packaging")
            note("detach-directory-open")
            directory_fd = os.open(binary.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
            note("detach-directory-identity")
            sdk.require((os.fstat(directory_fd).st_dev, os.fstat(directory_fd).st_ino) == directory_ids[2][:2], "packaging")
            note("detach-copy-open")
            fd = os.open(temporary.name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                         0o700, dir_fd=directory_fd)
            copied = os.fstat(fd)
            note("detach-copy-write")
            with os.fdopen(fd, "wb") as stream:
                os.fchmod(stream.fileno(), 0o700)
                stream.write(data)
                stream.flush()
                os.fsync(stream.fileno())
                copied = os.fstat(stream.fileno())
            note("detach-copy-identity")
            sdk.require(stat.S_ISREG(copied.st_mode) and copied.st_uid == os.getuid()
                        and copied.st_mode & 0o777 == 0o700 and copied.st_nlink == 1
                        and (copied.st_dev, copied.st_ino) != (original.st_dev, original.st_ino)
                        and copied.st_size == original.st_size, "packaging")
            note("detach-copy-read")
            sdk.require(sdk.sha(sdk.regular(temporary)) == digest
                        and sdk.file_identity(temporary.lstat()) == sdk.file_identity(copied), "packaging")
            current()
            candidates_current()
            note("detach-prepublish-identity")
            sdk.require(sdk.file_identity(binary.lstat()) == sdk.file_identity(original)
                        and sdk.file_identity(os.fstat(source_fd)) == sdk.file_identity(original), "packaging")
            for index, alias in enumerate(aliases):
                note("detach-prepublish-alias", detachAliasIndex=index)
                sdk.require(alias.resolve() == alias
                            and sdk.file_identity(alias.lstat()) == sdk.file_identity(original)
                            and sdk.sha(sdk.regular(alias)) == digest, "packaging")
            current()
            candidates_current()
            note("detach-prepublish-identity")
            sdk.require(sdk.file_identity(binary.lstat()) == sdk.file_identity(original)
                        and sdk.file_identity(os.fstat(source_fd)) == sdk.file_identity(original)
                        and sdk.file_identity(temporary.lstat()) == sdk.file_identity(copied), "packaging")
            for index, alias in enumerate(aliases):
                note("detach-prepublish-alias", detachAliasIndex=index)
                sdk.require(sdk.file_identity(alias.lstat()) == sdk.file_identity(original), "packaging")
            note("detach-publish")
            os.replace(temporary.name, binary.name, src_dir_fd=directory_fd, dst_dir_fd=directory_fd)
            note("detach-publish-fsync")
            os.fsync(directory_fd)
            current()
            note("detach-installed")
            installed = binary.lstat()
            sdk.require((installed.st_dev, installed.st_ino, installed.st_size, installed.st_mode,
                         installed.st_uid, installed.st_gid, installed.st_nlink, installed.st_mtime_ns)
                        == (copied.st_dev, copied.st_ino, copied.st_size, copied.st_mode,
                            copied.st_uid, copied.st_gid, 1, copied.st_mtime_ns)
                        and sdk.sha(sdk.regular(binary)) == digest, "packaging")
            note("detach-remaining")
            remaining = os.fstat(source_fd)
            sdk.require((remaining.st_dev, remaining.st_ino, remaining.st_size, remaining.st_mode,
                         remaining.st_uid, remaining.st_gid, remaining.st_nlink, remaining.st_mtime_ns)
                        == (original.st_dev, original.st_ino, original.st_size, original.st_mode,
                            original.st_uid, original.st_gid, original.st_nlink - 1, original.st_mtime_ns)
                        and remaining.st_ctime_ns >= original.st_ctime_ns, "packaging")
            candidates_current(remaining)
            for index, alias in enumerate(aliases):
                note("detach-final-alias", detachAliasIndex=index)
                sdk.require(sdk.file_identity(alias.lstat()) == sdk.file_identity(remaining)
                            and sdk.sha(sdk.regular(alias)) == digest, "packaging")
        finally:
            os.close(source_fd)
            if directory_fd is not None:
                try:
                    pending = os.stat(temporary.name, dir_fd=directory_fd, follow_symlinks=False)
                    if copied is not None and (pending.st_dev, pending.st_ino) == (copied.st_dev, copied.st_ino):
                        os.unlink(temporary.name, dir_fd=directory_fd)
                except FileNotFoundError:
                    pass
                finally:
                    os.close(directory_fd)


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


PROVENANCE_SUBSTAGES = frozenset({
    "detach-alias-bound", "detach-alias-identity", "detach-copy-identity", "detach-copy-open", "detach-copy-read", "detach-copy-write", "detach-current-deadline", "detach-current-directory", "detach-directory-guard", "detach-directory-identity", "detach-directory-open", "detach-directory-stat", "detach-final-alias", "detach-installed", "detach-link-count", "detach-link-guard", "detach-prepublish-alias", "detach-prepublish-identity", "detach-publish", "detach-publish-fsync", "detach-remaining", "detach-scan-bound", "detach-scan-open", "detach-source-identity", "detach-source-open", "detach-source-read", "detach-stat", "detach-work",
    "locked-version", "install", "source-discovery", "archive-discovery", "unique-count",
    "manifest-read", "manifest-identity", "registry-pin", "archive-read", "checksum-validation",
    "published-lock-read", "published-lock-root", "binary-stat", "binary-read", "binary-identity",
    "binary-detach", "before-version", "version-output", "package-output",
})
PROVENANCE_CODES = frozenset({"packaging", "unsafe_file", "changed_file", "deadline", "artifact_reserve",
                             "stage_deadline", "child_failed", "diagnostic_bound", "unclassified"})
PROVENANCE_BOOLEANS = (
    "manifestNameMatches", "manifestVersionMatches", "pinVersionMatches", "checksumWellFormed", "checksumMatches",
    "publishedLockRootMatches", "binaryRegular", "binaryOwner", "binaryModeSafe", "binarySizeWithinLimit",
    "binaryExecutable", "binarySingleLink", "binaryIdentityMatches",
)
PROVENANCE_CLASSES = frozenset({"Refused", "FileNotFoundError", "PermissionError", "OSError", "TOMLDecodeError",
                                "JSONDecodeError", "UnicodeDecodeError", "KeyError", "TypeError", "AttributeError", "ValueError", "other"})


DETACH_BOOLEANS = ("detachDirectoryOwner", "detachDirectoryModeSafe", "detachDirectoryRegular",
                   "detachAliasPathMatches", "detachAliasIdentityMatches")
DETACH_COUNTS = {"detachOriginalLinks": 65536, "detachDirectoryIndex": 5,
                 "detachEntriesSeen": 4097, "detachAliasCount": 3, "detachAliasIndex": 1}


def new_provenance_diagnostic():
    return {"substage": "locked-version", "sourceCount": None, "archiveCount": None,
            **{key: None for key in (*PROVENANCE_BOOLEANS, *DETACH_BOOLEANS, *DETACH_COUNTS)}, "binaryBytes": None,
            "beforeVersionFreeBytes": None, "beforeVersionMinimumFreeBytes": None, "minimumReserveBytes": None}


def closed_provenance_diagnostic(state, error):
    """A closed diagnostic only; never stringify exceptions, paths or private data."""
    sdk.require(type(state) is dict and set(state) == set(new_provenance_diagnostic()), "packaging")
    sdk.require(type(state["substage"]) is str and state["substage"] in PROVENANCE_SUBSTAGES, "packaging")
    for key in (*PROVENANCE_BOOLEANS, *DETACH_BOOLEANS):
        sdk.require(state[key] is None or type(state[key]) is bool, "packaging")
    for key, limit in (("sourceCount", 2), ("archiveCount", 2), ("binaryBytes", 64 * 1024**2 + 1),
                       ("beforeVersionFreeBytes", 2**63 - 1), ("beforeVersionMinimumFreeBytes", 2**63 - 1),
                       ("minimumReserveBytes", 2**63 - 1)):
        value = state[key]
        sdk.require(value is None or type(value) is int and 0 <= value <= limit, "packaging")
    for key, limit in DETACH_COUNTS.items():
        value = state[key]
        sdk.require(value is None or type(value) is int and 0 <= value <= limit, "packaging")
    classes = {sdk.Refused: "Refused", FileNotFoundError: "FileNotFoundError", PermissionError: "PermissionError",
               OSError: "OSError", tomllib.TOMLDecodeError: "TOMLDecodeError", json.JSONDecodeError: "JSONDecodeError",
               UnicodeDecodeError: "UnicodeDecodeError", KeyError: "KeyError", TypeError: "TypeError", AttributeError: "AttributeError", ValueError: "ValueError"}
    code = error.args[0] if type(error) is sdk.Refused and len(error.args) == 1 else None
    code = code if type(code) is str and code in PROVENANCE_CODES else "unclassified"
    return {**state, "exceptionClass": classes.get(type(error), "other"), "code": code}


def installed_bindgen_provenance(private, work, diagnostic=None):
    diagnostic = new_provenance_diagnostic() if diagnostic is None else diagnostic
    name = "wasm-bindgen-cli-" + BINDGEN_VERSION
    diagnostic["substage"] = "source-discovery"
    sources = list((private / "cargo/registry/src").glob("*/" + name))
    diagnostic["sourceCount"] = min(len(sources), 2)
    diagnostic["substage"] = "archive-discovery"
    archives = list((private / "cargo/registry/cache").glob("*/" + name + ".crate"))
    diagnostic["archiveCount"] = min(len(archives), 2)
    diagnostic["substage"] = "unique-count"
    sdk.require(len(sources) == len(archives) == 1, "packaging")
    diagnostic["substage"] = "manifest-read"
    package = tomllib.loads(sdk.regular(sources[0] / "Cargo.toml").decode())
    diagnostic["substage"] = "manifest-identity"
    metadata = package.get("package", {})
    name_matches = isinstance(metadata, dict) and metadata.get("name") == "wasm-bindgen-cli"
    diagnostic["manifestNameMatches"] = name_matches
    diagnostic["manifestVersionMatches"] = metadata.get("version") == BINDGEN_VERSION if name_matches else None
    sdk.require(package.get("package", {}).get("name") == "wasm-bindgen-cli"
                and package["package"].get("version") == BINDGEN_VERSION, "packaging")
    diagnostic["substage"] = "registry-pin"
    sdk.require(type(BINDGEN_CRATE_PIN) is tuple and len(BINDGEN_CRATE_PIN) == 2, "packaging")
    pinned_version, checksum = BINDGEN_CRATE_PIN
    version_matches = type(pinned_version) is str and pinned_version == BINDGEN_VERSION
    diagnostic["pinVersionMatches"] = version_matches
    well_formed = type(checksum) is str and re.fullmatch(r"[0-9a-f]{64}", checksum)
    diagnostic["checksumWellFormed"] = bool(well_formed)
    sdk.require(version_matches and well_formed, "packaging")
    diagnostic["substage"] = "archive-read"
    archive = sdk.regular(archives[0])
    diagnostic["substage"] = "checksum-validation"
    checksum_matches = sdk.sha(archive) == checksum if well_formed else None
    diagnostic["checksumMatches"] = checksum_matches
    sdk.require(well_formed and checksum_matches, "packaging")
    diagnostic["substage"] = "published-lock-read"
    published_lock = sdk.regular(sources[0] / "Cargo.lock")
    locked = tomllib.loads(published_lock.decode())
    diagnostic["substage"] = "published-lock-root"
    root_matches = any(row.get("name") == "wasm-bindgen-cli" and row.get("version") == BINDGEN_VERSION
                       for row in locked.get("package", []))
    diagnostic["publishedLockRootMatches"] = root_matches
    sdk.require(root_matches, "packaging")
    binary = work / ".ci-bindgen/bin/wasm-bindgen"
    diagnostic["substage"] = "binary-stat"
    identity = binary.lstat()
    diagnostic.update(binaryBytes=min(max(identity.st_size, 0), 64 * 1024**2 + 1),
                      binaryRegular=stat.S_ISREG(identity.st_mode), binaryOwner=identity.st_uid == os.getuid(),
                      binaryModeSafe=not bool(identity.st_mode & 0o002), binarySizeWithinLimit=identity.st_size <= 64 * 1024**2,
                      binaryExecutable=bool(identity.st_mode & 0o111), binarySingleLink=identity.st_nlink == 1)
    diagnostic["substage"] = "binary-read"
    executable = sdk.regular(binary)
    diagnostic["substage"] = "binary-identity"
    # Keep the original short-circuit: do not read an identity guard we never reached.
    identity_matches = None
    if identity.st_mode & 0o111 and identity.st_nlink == 1:
        identity_matches = sdk.file_identity(identity) == sdk.file_identity(binary.lstat())
    diagnostic["binaryIdentityMatches"] = identity_matches
    sdk.require(identity.st_mode & 0o111 and identity.st_nlink == 1
                and identity_matches, "packaging")
    return {"package": "wasm-bindgen-cli", "version": BINDGEN_VERSION, "registry": "crates.io",
            "url": "https://crates.io/crates/wasm-bindgen-cli/" + BINDGEN_VERSION,
            "crateSha256": checksum, "publishedCargoLockSha256": sdk.sha(published_lock),
            "binarySha256": sdk.sha(executable),
            "binaryIdentity": {"device": identity.st_dev, "inode": identity.st_ino, "bytes": identity.st_size,
                               "mtimeNs": identity.st_mtime_ns, "ctimeNs": identity.st_ctime_ns,
                               "mode": identity.st_mode, "uid": identity.st_uid, "links": identity.st_nlink}}


def produce_browser_package(runner, private, work, artifact, artifact_dir, receipt):
    """Execute the real installed bindgen producer and inventory its emitted bytes."""
    diagnostic = new_provenance_diagnostic()
    try:
        locked_bindgen_version(work)
        diagnostic["substage"] = "install"
        runner.run("bindgen-install", commands()[3], seconds=STAGE_SECONDS[3])
        diagnostic["substage"] = "binary-detach"
        detach_installed_bindgen(work, runner.deadline, diagnostic)
        provenance = installed_bindgen_provenance(private, work, diagnostic)
        runner.env["PATH"] = str(work / ".ci-bindgen/bin") + os.pathsep + runner.env["PATH"]
        diagnostic["substage"] = "before-version"
        runner.packaging_diagnostic = diagnostic
        version_log = runner.run("bindgen-version", commands()[4], seconds=STAGE_SECONDS[4])
        diagnostic["substage"] = "version-output"
        sdk.require(sdk.regular(version_log, 65536).decode().strip() == "wasm-bindgen " + BINDGEN_VERSION, "packaging")
        diagnostic["substage"] = "package-output"
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
    except Exception as error:
        try:
            receipt["packagingDiagnostic"] = closed_provenance_diagnostic(diagnostic, error)
        except Exception:
            pass  # Observation must not replace the producer's original failure.
        raise


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
        diagnostic = getattr(self, "packaging_diagnostic", None) if stage == "bindgen-version" else None
        if diagnostic is not None:
            try:
                diagnostic["beforeVersionFreeBytes"] = shutil.disk_usage(self.root).free
                diagnostic["minimumReserveBytes"] = sdk.RESERVE
            except Exception:
                pass
        try:
            return super().run(stage, command, **kwargs)
        finally:
            if diagnostic is not None:
                try:
                    diagnostic["beforeVersionMinimumFreeBytes"] = self.minimum_free
                except Exception:
                    pass
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
