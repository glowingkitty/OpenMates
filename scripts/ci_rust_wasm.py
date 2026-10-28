"""Fixed Rust/WASM package and real DedicatedWorker gate; no application/SDK proof."""
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
    from scripts import ci_wasm_worker as worker
    from scripts.ci_sdk_lockfiles import ROOTS, LOCKS, owned, snapshot, validate_manifests
except ModuleNotFoundError:
    import ci_sdk_conformance as sdk
    import ci_wasm_worker as worker
    from ci_sdk_lockfiles import ROOTS, LOCKS, owned, snapshot, validate_manifests

TARGET = "rust-wasm"
BUDGET = 2700
BROWSER_SPEC = "rust-core-browser-session.spec.ts"
BROWSER_PASSWORD_SPEC = "rust-core-browser-password-entry.spec.ts"
PRODUCTION_BROWSER_SPEC = "rust-core-production-saved-session.spec.ts"
PRODUCTION_BROWSER_PLATFORM_SPEC = "rust-core-production-platform.spec.ts"
PRODUCTION_BROWSER_LOCAL_CURSOR_SPEC = "rust-core-production-local-cursor.spec.ts"
PRODUCTION_BROWSER_SAVED_PAGING_SPEC = "rust-core-production-saved-paging.spec.ts"
PRODUCTION_BROWSER_ORDINARY_LOGIN_SPEC = "rust-core-ordinary-login-retention.spec.ts"
PRODUCTION_BROWSER_SPECS = frozenset({PRODUCTION_BROWSER_SPEC, PRODUCTION_BROWSER_PLATFORM_SPEC,
                                      PRODUCTION_BROWSER_LOCAL_CURSOR_SPEC, PRODUCTION_BROWSER_SAVED_PAGING_SPEC, PRODUCTION_BROWSER_ORDINARY_LOGIN_SPEC})
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
# wasm-bindgen 0.2.129 writes inline_js verbatim under a crate identifier.
# Official producer: cli-support/src/lib.rs (inline_js_module_name, Output::emit),
# macro-support/src/hash.rs (unique_crate_identifier). The suffix is only a name.
SNIPPET_PATH = r"snippets/openmates-browser-bindings-[0-9a-f]{16}/inline0\.js"
SNIPPET_SOURCE = "packages/openmates-browser-bindings/src/browser_crypto.rs"
SNIPPET_SOURCE_SHA256 = "735598f81f8e4272f432cb1cedcd64f5f63bb651599282d172d0a7dbebc6d928"
SNIPPET_BYTES = (b"\nexport function settlePrimitive(operation, settle) {\n"
                 b"  return operation.then(value => { settle(value, true); }, () => { settle(undefined, false); });\n}\n")


# Exact current recovery module only. Physical output does not grant arbitrary
# SDK imports: the finite namespace graph below must independently match.
SDK_SNIPPET_PATH = r"snippets/openmates-sdk-[0-9a-f]{16}/inline0\.js"
SDK_SNIPPET_SOURCE = "packages/openmates-rust/src/platform/browser_recovery_port.rs"
SDK_SNIPPET_SOURCE_SHA256 = "fa3c9c6125b6a57ee1d2e98a800b034dbc8dc740da897e769c9780e775305fe3"
SDK_SNIPPET_BODY_SHA256 = "f896283208ee2696872509a87d5256ec362ca8479ab24f410c6428322d5b3cbb"
SDK_SNIPPET_BODY_BYTES = 3365
SDK_PACKAGE_SOURCE = "packages/openmates-rust/Cargo.toml"
SDK_PACKAGE_SOURCE_SHA256 = "adaf5d2b56d67875f101a4705db5538fd871f5146372be5721377c6b7c7582af"
# Exact second reviewed Cargo preimage: only serde_json float_roundtrip added.
SDK_FLOAT_PACKAGE_SOURCE_SHA256 = "cb7ab7ea51f6998304d921b238f8602a40fe342759e849f1e51caeef9d3a0f0f"


SDK_FUNCTIONS = frozenset({"recoveryCapture", "recoveryListen", "recoveryUnlisten", "recoveryClose", "recoveryDefer", "recoveryRequest", "recoveryCancel", "recoveryStop", "recoveryRead"})


def recovery_sdk_output(files, inputs, diagnostic=None):
    """Validate exact module, finite producer header and every namespace use.

    This returns a guard view only: files emitted/exported retain original bytes.
    Numeric namespace order is a finite supported producer permutation, not a
    claim that a generated root was observed. Other producer forms stay refused.
    """
    if not isinstance(files, dict) or not isinstance(inputs, dict):
        return None
    names = [name for name in files if type(name) is str and re.fullmatch(SDK_SNIPPET_PATH, name)]
    source = inputs.get(SDK_SNIPPET_SOURCE)
    if source is None and not names:
        return files
    source_match = (source == SDK_SNIPPET_SOURCE_SHA256 and len(names) == 1
                    and inputs.get(SDK_PACKAGE_SOURCE) in {SDK_PACKAGE_SOURCE_SHA256, SDK_FLOAT_PACKAGE_SOURCE_SHA256})
    _package_note(diagnostic, "package-source", packageSdkSourceMatch=source_match)
    if not source_match:
        return None
    name = names[0]
    body = files[name]
    body_match = (type(body) is bytes and len(body) == SDK_SNIPPET_BODY_BYTES
                  and sdk.sha(body) == SDK_SNIPPET_BODY_SHA256)
    _package_note(diagnostic, "package-body", packageSdkBodyMatch=body_match)
    if not body_match:
        return None
    javascript = files.get(PACKAGE_FILES[0])
    if type(javascript) is not bytes:
        return None
    headers = [(index, ('import * as import' + str(index) + ' from "./' + name + '"\n').encode()) for index in (1, 2)]
    matched = [(index, header) for index, header in headers if javascript.count(header) == 1]
    singleton = len(matched) == 1
    _package_note(diagnostic, "package-import-header", packageSdkImportSingleton=singleton)
    if not singleton:
        return None
    index, header = matched[0]
    javascript = javascript.replace(header, b"", 1)
    try:
        text = javascript.decode("utf-8", errors="strict")
    except UnicodeError:
        return None
    namespace = "import" + str(index)
    token = r"(?<![A-Za-z0-9_$])" + namespace + r"(?![A-Za-z0-9_$])"
    # Namespace tokens may only be fixed SDK function access or the exact
    # matching module-map value. No computed access, alias or different map key.
    approved = []
    for match in re.finditer(token + r"\.(?:" + "|".join(sorted(SDK_FUNCTIONS)) + r")(?![A-Za-z0-9_$])", text):
        approved.append((match.start(), match.start() + len(namespace)))
    mapping = re.compile(r"[\"']" + re.escape("./" + name) + r"[\"']\s*:\s*(" + token + r")")
    for match in mapping.finditer(text):
        approved.append(match.span(1))
    actual = [match.span() for match in re.finditer(token, text)]
    uses_closed = bool(actual) and sorted(actual) == sorted(approved)
    _package_note(diagnostic, "package-dependencies", packageSdkNamespaceUsesClosed=uses_closed)
    if not uses_closed:
        return None
    crypto = [key for key in files if re.fullmatch(SNIPPET_PATH, key)]
    if index == 1 and len(crypto) == 1:
        # Additional namespace2 form is admitted only with the independently
        # verified namespace1 SDK. Feed the original crypto guard its exact old
        # header spelling; original executable files are never modified.
        alternate = ('import * as import2 from "./' + crypto[0] + '"\n').encode()
        if javascript.count(alternate) == 1:
            javascript = javascript.replace(alternate, package_import_headers(crypto[0])[1], 1)
    result = {key: data for key, data in files.items() if key != name}
    result[PACKAGE_FILES[0]] = javascript
    return result


def package_names(names):
    """Closed base plus at most one exact crypto and one exact SDK module."""
    if not isinstance(names, (set, dict)) or any(type(name) is not str for name in names):
        return False
    extras = set(names) - set(PACKAGE_FILES)
    crypto = {name for name in extras if re.fullmatch(SNIPPET_PATH, name)}
    dormant = {name for name in extras if re.fullmatch(SDK_SNIPPET_PATH, name)}
    return (set(PACKAGE_FILES[:3]) <= set(names) and len(crypto) <= 1
            and len(dormant) <= 1 and extras == crypto | dormant)


# Explicit ECMAScript WhiteSpace and LineTerminator sets (including BOM).
MODULE_SPACE = "\t\v\f \u00a0\ufeff\u1680\u2000\u2001\u2002\u2003\u2004\u2005\u2006\u2007\u2008\u2009\u200a\u202f\u205f\u3000\n\r\u2028\u2029"
MODULE_LINES = "\n\r\u2028\u2029"


def module_dependency_reason(javascript):
    """Finite diagnostic for the unchanged conservative dependency predicate.

    Scan raw text, including strings/comments/regex/templates: discarding those
    regions could hide an executable token. Every dynamic/static import has the
    literal reserved token import; every external export has FromClause, whose
    literal from token is followed by ECMAScript trivia and a StringLiteral.
    Reject harmless lookalikes rather than attempt general JS lexical parsing.
    """
    if not isinstance(javascript, bytes) or not 0 < len(javascript) <= 64 * 1024**2:
        return 1
    try:
        text = javascript.decode("utf-8", errors="strict")
    except UnicodeError:
        return 2
    # Escaped contextual/reserved words are outside the reviewed glue grammar.
    # This intentionally also refuses harmless Unicode escapes inside literals.
    if "\\u" in text:
        return 3
    spent, budget = 0, len(text) * 8 + 128
    for token in re.finditer(r"(?<![A-Za-z0-9_$])(?:import|from)(?![A-Za-z0-9_$])", text):
        if token.group() == "import":
            end = token.start() + len("import.meta.url")
            if (not text.startswith("import.meta.url", token.start())
                    or end < len(text) and (text[end].isalnum() or text[end] in "_$\\.")):
                return 4
            continue
        cursor = token.end()
        while cursor < len(text):
            before = cursor
            if text[cursor] in MODULE_SPACE:
                cursor += 1
            elif text.startswith("/*", cursor):
                end = text.find("*/", cursor + 2)
                if end < 0:
                    return 5
                cursor = end + 2
            elif text.startswith("//", cursor):
                cursor += 2
                while cursor < len(text) and text[cursor] not in MODULE_LINES:
                    cursor += 1
            else:
                break
            spent += cursor - before
            if spent > budget:
                return 6
        if cursor < len(text) and text[cursor] in "'\"":
            return 7
    return 0

# Closed ordinal vocabulary. No token text, offsets, paths or source are emitted.
# 0=closed, 1=input bounds/type, 2=UTF8, 3=Unicode escape, 4=import token,
# 5=unterminated from-comment, 6=linear trivia budget, 7=quoted from source.
DEPENDENCY_REASON_CODES = frozenset(range(8))


def closed_module_dependencies(javascript):
    return module_dependency_reason(javascript) == 0


def _package_note(diagnostic, substage, **values):
    # Observation never authorizes a guard or replaces its original exception.
    try:
        if diagnostic is not None:
            diagnostic.update(substage=substage, **values)
    except Exception:
        pass


def package_import_headers(name):
    # Official 0.2.129 generate_esm_cjs_imports emits a namespace import when
    # attempt_direct_import maps a bare externref signature straight into WASM.
    # There is exactly one closed external module/function, so its index is 1.
    return (("import { settlePrimitive } from './" + name + "';\n").encode(),
            ('import * as import1 from "./' + name + '"\n').encode())


def package_modules(files, inputs, diagnostic=None):
    """Bind the sole module to reviewed source, exact bytes and its ESM import."""
    names_match = package_names(files)
    _package_note(diagnostic, "package-names", packageNamesMatch=names_match)
    if not names_match or not isinstance(inputs, dict):
        return False
    # Only the exact reviewed recovery SDK graph can reach the original crypto guard.
    files = recovery_sdk_output(files, inputs, diagnostic)
    if files is None:
        return False
    snippets = set(files) - set(PACKAGE_FILES)
    source = inputs.get(SNIPPET_SOURCE)
    source_match = not ((source is not None and (source != SNIPPET_SOURCE_SHA256 or len(snippets) != 1))
                        or snippets and source != SNIPPET_SOURCE_SHA256)
    _package_note(diagnostic, "package-source", packageSourceMatch=bool(source_match), packageSnippetCount=min(len(snippets), 2))
    if not source_match:
        return False
    javascript = files[PACKAGE_FILES[0]]
    _package_note(diagnostic, "package-main-format")
    if not isinstance(javascript, bytes):
        return False
    if snippets:
        name = next(iter(snippets))
        body_match = files[name] == SNIPPET_BYTES
        _package_note(diagnostic, "package-body", packageSnippetBodyMatch=body_match)
        if not body_match:
            return False
        headers = package_import_headers(name)
        counts = [javascript.count(header) for header in headers]
        singleton = sum(counts) == 1
        _package_note(diagnostic, "package-import-header", packageNamedImportCount=min(counts[0], 2),
                      packageDirectImportCount=min(counts[1], 2), packageImportSingleton=singleton)
        if not singleton:
            return False
        javascript = javascript.replace(headers[counts.index(1)], b"", 1)
    reason = module_dependency_reason(javascript)
    closed = reason == 0
    _package_note(diagnostic, "package-dependencies", packageDependenciesClosed=closed,
                  packageDependencyRefusalKind=reason)
    return closed



STAGES = ("rust-toolchain", "wasm-target", "wasm-build", "bindgen-install", "bindgen-version", "bindgen-package")
STAGE_SECONDS = (300, 300, 1800, 900, 30, 180)
ALL_STAGES = (*STAGES, *worker.STAGES)
DIAGNOSTIC_LIMIT = 128 * 1024
DIAGNOSTIC_ARTIFACT = "isolated-rust-wasm-private-diagnostics"
FAILURES = frozenset({"admission", "identity", "source", "deadline", "disk", "toolchain", "compile", "packaging", "outputs", "cleanup", "worker", "unclassified"})


def production_browser_e2e_targets(targets):
    """Closed nonempty, deduplicated subset of the five reviewed production specs (at most two per job)."""
    return (type(targets) is list and 1 <= len(targets) <= 2
            and all(type(name) is str and name in PRODUCTION_BROWSER_SPECS for name in targets)
            and len(set(targets)) == len(targets))


def browser_e2e_targets(targets):
    """Legacy singleton selectors or the exact closed production subset."""
    return targets in ([BROWSER_SPEC], [BROWSER_PASSWORD_SPEC]) or production_browser_e2e_targets(targets)


def validate_targets(targets):
    sdk.require(targets == [TARGET], "admission")


# Pinned producer supports debug-name removal; executable/API features stay intact.
# https://github.com/wasm-bindgen/wasm-bindgen/blob/0.2.129/crates/cli/src/wasm_bindgen.rs
def commands():
    return [["rustup", "toolchain", "install", "1.98.1", "--profile", "minimal"],
            ["rustup", "target", "add", "--toolchain", "1.98.1", "wasm32-unknown-unknown"],
            ["cargo", "+1.98.1", "build", "--locked", "--release", "--manifest-path",
             "packages/openmates-browser-bindings/Cargo.toml", "--target", "wasm32-unknown-unknown", "--lib"],
            ["cargo", "+1.98.1", "install", "wasm-bindgen-cli", "--version", "=" + BINDGEN_VERSION,
             "--locked", "--registry", "crates-io", "--root", ".ci-bindgen", "--target-dir", ".ci-bindgen-target", "--jobs", "2"],
            ["wasm-bindgen", "--version"],
            ["wasm-bindgen", ".ci-packaging/input.wasm", "--target", "web", "--remove-name-section", "--out-dir", ".ci-packaging/pkg", "--out-name", PACKAGE_NAME]]


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


def detach_installed_bindgen(work, deadline, diagnostic=None, *, binary_name="wasm-bindgen"):
    """Detach only the closed Cargo install/build hardlink set, before execution.

    Unknown links are never adopted. The provenance reader below still requires
    nlink==1; this preparation cannot make an arbitrary hardlink admissible.
    """
    sdk.require(binary_name in {"wasm-bindgen", "wasm-bindgen-test-runner"}, "packaging")
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
    binary = work / ".ci-bindgen/bin" / binary_name
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
        candidates = [work / ".ci-bindgen-target/release" / binary_name]
        note("detach-scan-open")
        with os.scandir(directories[-1]) as entries:
            for index, entry in enumerate(entries):
                note("detach-scan-bound", detachEntriesSeen=min(index + 1, 4097))
                sdk.require(index < 4096, "packaging")
                if re.fullmatch(binary_name.replace("-", "_") + r"-[0-9a-f]{16}", entry.name):
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
        temporary = binary.with_name("." + binary_name + "-detached")
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


def package_inventory(folder, inputs=None, diagnostic=None):
    """Bounded closed tree; preserve the existing recursive inventory schema."""
    directories, names = [], set()

    def scan(directory, allowed, limit):
        _package_note(diagnostic, "package-directory-stat", packageDirectoryIndex=min(len(directories), 3))
        before = directory.lstat()
        canonical = directory.resolve() == directory
        _package_note(diagnostic, "package-directory-policy", packageDirectoryCanonical=canonical,
                      packageDirectoryRegular=stat.S_ISDIR(before.st_mode),
                      packageDirectoryOwner=before.st_uid == os.getuid(),
                      packageDirectoryModeSafe=not bool(before.st_mode & 0o022))
        sdk.require(canonical and stat.S_ISDIR(before.st_mode)
                    and before.st_uid == os.getuid() and not before.st_mode & 0o022, "outputs")
        directories.append((directory, sdk.file_identity(before)))
        entries = []
        with os.scandir(directory) as listing:
            for entry in listing:
                _package_note(diagnostic, "package-entry-count", packageEntriesSeen=min(len(entries) + 1, 6))
                sdk.require(len(entries) < limit, "outputs")
                matches = bool(allowed(entry.name))
                _package_note(diagnostic, "package-entry-name", packageEntryNameMatches=matches)
                sdk.require(matches, "outputs")
                entries.append(Path(entry.path))
        return entries

    for path in scan(folder, lambda name: name in {*PACKAGE_FILES, "snippets"}, 5):
        if path.name == "snippets":
            crates = scan(path, lambda name: bool(re.fullmatch(r"openmates-browser-bindings-[0-9a-f]{16}", name)
                                                 or re.fullmatch(r"openmates-sdk-[0-9a-f]{16}", name)), 2)
            _package_note(diagnostic, "package-crate-count")
            sdk.require(1 <= len(crates) <= 2, "outputs")
            for crate in crates:
                children = scan(crate, lambda name: name == "inline0.js", 1)
                _package_note(diagnostic, "package-inline-count")
                sdk.require(len(children) == 1, "outputs")
                names.add(children[0].relative_to(folder).as_posix())
        else:
            names.add(path.name)
    matches = package_names(names)
    _package_note(diagnostic, "package-names", packageNamesMatch=matches)
    sdk.require(matches, "outputs")
    rows, total, files = [], 0, {}
    for index, name in enumerate(sorted(names)):
        path = folder / name
        _package_note(diagnostic, "package-file-stat", packageFileIndex=min(index, 5))
        info = path.lstat()
        _package_note(diagnostic, "package-file-read", packageFileRegular=stat.S_ISREG(info.st_mode),
                      packageFileOwner=info.st_uid == os.getuid(), packageFileModeSafe=not bool(info.st_mode & 0o022),
                      packageFileSingleLink=info.st_nlink == 1, packageFileBytes=min(max(info.st_size, 0), 64 * 1024**2 + 1),
                      packageFileIsSnippet=bool(re.fullmatch(SNIPPET_PATH, name) or re.fullmatch(SDK_SNIPPET_PATH, name)))
        raw = sdk.regular(path)
        info = path.lstat()
        _package_note(diagnostic, "package-file-policy")
        sdk.require(info.st_nlink == 1 and not info.st_mode & 0o022 and raw, "outputs")
        _package_note(diagnostic, "package-file-format")
        if name.endswith(".wasm"):
            sdk.require(raw[:8] == b"\0asm\x01\0\0\0", "outputs")
        else:
            raw.decode("utf-8", errors="strict")
        total += len(raw)
        _package_note(diagnostic, "package-byte-bound")
        sdk.require(total <= 128 * 1024**2, "outputs")
        rows.append({"path": name, "sha256": sdk.sha(raw), "rawBytes": len(raw)})
        files[name] = raw
    sdk.require(package_modules(files, {} if inputs is None else inputs, diagnostic), "outputs")
    for directory, identity in directories:
        _package_note(diagnostic, "package-directory-stable")
        sdk.require(directory.resolve() == directory and sdk.file_identity(directory.lstat()) == identity, "outputs")
    return {"files": rows, "rawBytes": total,
            "inventorySha256": sdk.sha(json.dumps(rows, sort_keys=True, separators=(",", ":")).encode())}


PROVENANCE_SUBSTAGES = frozenset({
    "detach-alias-bound", "detach-alias-identity", "detach-copy-identity", "detach-copy-open", "detach-copy-read", "detach-copy-write", "detach-current-deadline", "detach-current-directory", "detach-directory-guard", "detach-directory-identity", "detach-directory-open", "detach-directory-stat", "detach-final-alias", "detach-installed", "detach-link-count", "detach-link-guard", "detach-prepublish-alias", "detach-prepublish-identity", "detach-publish", "detach-publish-fsync", "detach-remaining", "detach-scan-bound", "detach-scan-open", "detach-source-identity", "detach-source-open", "detach-source-read", "detach-stat", "detach-work",
    "locked-version", "install", "source-discovery", "archive-discovery", "unique-count",
    "manifest-read", "manifest-identity", "registry-pin", "archive-read", "checksum-validation",
    "published-lock-read", "published-lock-root", "binary-stat", "binary-read", "binary-identity",
    "binary-detach", "before-version", "version-output", "package-output",
    "package-directory-stat", "package-directory-policy", "package-entry-count", "package-entry-name",
    "package-crate-count", "package-inline-count", "package-names", "package-file-stat", "package-file-read",
    "package-file-policy", "package-file-format", "package-byte-bound", "package-source", "package-main-format",
    "package-body", "package-import-header", "package-dependencies", "package-directory-stable",
    "package-export-read", "package-export-write", "package-manifest-write",
})
PROVENANCE_CODES = frozenset({"outputs", "packaging", "unsafe_file", "changed_file", "deadline", "artifact_reserve",
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


PACKAGE_BOOLEANS = ("packageDirectoryCanonical", "packageDirectoryRegular", "packageDirectoryOwner", "packageDirectoryModeSafe",
                    "packageEntryNameMatches", "packageFileRegular", "packageFileOwner", "packageFileModeSafe",
                    "packageFileSingleLink", "packageFileIsSnippet", "packageNamesMatch", "packageSourceMatch",
                    "packageSnippetBodyMatch", "packageImportSingleton", "packageDependenciesClosed", "packageSdkSourceMatch",
                    "packageSdkBodyMatch", "packageSdkImportSingleton", "packageSdkNamespaceUsesClosed")
PACKAGE_COUNTS = {"packageDirectoryIndex": 3, "packageEntriesSeen": 6, "packageFileIndex": 5,
                  "packageFileBytes": 64 * 1024**2 + 1, "packageSnippetCount": 2,
                  "packageNamedImportCount": 2, "packageDirectImportCount": 2, "packageDependencyRefusalKind": 7}


def new_provenance_diagnostic():
    return {"substage": "locked-version", "sourceCount": None, "archiveCount": None,
            **{key: None for key in (*PROVENANCE_BOOLEANS, *DETACH_BOOLEANS, *DETACH_COUNTS, *PACKAGE_BOOLEANS, *PACKAGE_COUNTS)}, "binaryBytes": None,
            "beforeVersionFreeBytes": None, "beforeVersionMinimumFreeBytes": None, "minimumReserveBytes": None}


def closed_provenance_diagnostic(state, error):
    """A closed diagnostic only; never stringify exceptions, paths or private data."""
    sdk.require(type(state) is dict and set(state) == set(new_provenance_diagnostic()), "packaging")
    sdk.require(type(state["substage"]) is str and state["substage"] in PROVENANCE_SUBSTAGES, "packaging")
    for key in (*PROVENANCE_BOOLEANS, *DETACH_BOOLEANS, *PACKAGE_BOOLEANS):
        sdk.require(state[key] is None or type(state[key]) is bool, "packaging")
    for key, limit in (("sourceCount", 2), ("archiveCount", 2), ("binaryBytes", 64 * 1024**2 + 1),
                       ("beforeVersionFreeBytes", 2**63 - 1), ("beforeVersionMinimumFreeBytes", 2**63 - 1),
                       ("minimumReserveBytes", 2**63 - 1)):
        value = state[key]
        sdk.require(value is None or type(value) is int and 0 <= value <= limit, "packaging")
    for key, limit in {**DETACH_COUNTS, **PACKAGE_COUNTS}.items():
        value = state[key]
        sdk.require(value is None or type(value) is int and 0 <= value <= limit, "packaging")
    classes = {sdk.Refused: "Refused", FileNotFoundError: "FileNotFoundError", PermissionError: "PermissionError",
               OSError: "OSError", tomllib.TOMLDecodeError: "TOMLDecodeError", json.JSONDecodeError: "JSONDecodeError",
               UnicodeDecodeError: "UnicodeDecodeError", KeyError: "KeyError", TypeError: "TypeError", AttributeError: "AttributeError", ValueError: "ValueError"}
    code = error.args[0] if type(error) is sdk.Refused and len(error.args) == 1 else None
    code = code if type(code) is str and code in PROVENANCE_CODES else "unclassified"
    return {**state, "exceptionClass": classes.get(type(error), "other"), "code": code}


def installed_bindgen_provenance(private, work, diagnostic=None, *, binary_name="wasm-bindgen"):
    sdk.require(binary_name in {"wasm-bindgen", "wasm-bindgen-test-runner"}, "packaging")
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
    binary = work / ".ci-bindgen/bin" / binary_name
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
        inventory = package_inventory(generated, receipt["inputs"], diagnostic)
        exported = artifact_dir / "package"
        exported.mkdir(mode=0o700)
        for row in inventory["files"]:
            _package_note(diagnostic, "package-export-read")
            data = sdk.regular(generated / row["path"])
            sdk.require(sdk.sha(data) == row["sha256"] and len(data) == row["rawBytes"], "outputs")
            _package_note(diagnostic, "package-export-write")
            destination = exported / row["path"]
            destination.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
            with destination.open("xb") as stream:
                os.fchmod(stream.fileno(), 0o600)
                stream.write(data)
        sdk.require(package_inventory(exported, receipt["inputs"], diagnostic) == inventory
                    and package_inventory(generated, receipt["inputs"], diagnostic) == inventory, "outputs")
        manifest = {"schemaVersion": 1, "status": "passed", "source_commit": receipt["source_commit"],
                    "source_tree": receipt["source_tree"], "harness_commit": receipt["harness_commit"], "run_id": receipt["run_id"],
                    "inputs": receipt["inputs"], "inputSetSha256": receipt["inputSetSha256"], "locks": receipt["locks"],
                    "target": "wasm32-unknown-unknown", "toolchain": "1.98.1", "inputWasmSha256": raw["sha256"],
                    "wasmBindgenVersion": BINDGEN_VERSION, "toolSha256": provenance["binarySha256"],
                    "toolProvenance": provenance, "inventory": inventory, "browserRuntimeProof": False,
                    "requestedMode": receipt["requestedMode"], "requestedTargets": receipt["requestedTargets"]}
        _package_note(diagnostic, "package-manifest-write")
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
    sdk.require(stage in ALL_STAGES, "compile")
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
            if self.steps and stage in ALL_STAGES:
                self.steps[-1]["command"]["tool"] = ("cargo" if stage in {"wasm-build", "bindgen-install", "worker-test-build"} else
                    "node" if stage in {"worker-chromium-install", "worker-dedicated-tests"} else
                    "wasm-bindgen-test-runner" if stage == "worker-runner-version" else
                    "wasm-bindgen" if stage.startswith("bindgen-") else "rustup")


def run(root, results, *, environ=None, browser_e2e=False, node=None, verify_node=None):
    ambient = os.environ if environ is None else environ
    output = root / "test-results"
    artifact_dir = output / TARGET
    receipt = {"schemaVersion": 1, "runtime_profile": "rust-browser-package-for-e2e" if browser_e2e else TARGET,
               "requestedMode": ambient.get("CI_TEST_MODE", TARGET),
               "requestedTargets": None, "status": "failed", "code": "admission",
               "compilationProof": False, "packagingProof": False, "browserRuntimeProof": False, "conformanceProof": False,
               "releaseProof": False, "publication": False, "services": {}, "cleanupVerified": False, "sourceHeld": False, "workerProof": None}
    runner = private = before = source = tree = None
    phase = "admission"
    try:
        sdk.require(ambient.get("GITHUB_ACTIONS") == "true"
                    and ambient.get("RUNNER_ENVIRONMENT") == "github-hosted"
                    and ambient.get("OPENMATES_CI_ISOLATED") == "1"
                    and platform.machine() == "x86_64" and os.sys.platform == "linux", "admission")
        receipt["requestedTargets"] = json.loads(ambient.get("CI_SPECS_JSON", "[]"))
        if browser_e2e:
            sdk.require(ambient.get("CI_TEST_MODE") == "e2e" and browser_e2e_targets(receipt["requestedTargets"])
                        and not ambient.get("CI_CASE_TITLE") and not ambient.get("CI_CAPACITY_CONFIGURATION"), "admission")
        else:
            validate_targets(receipt["requestedTargets"])
            sdk.require(type(node) is str and Path(node).is_absolute() and callable(verify_node), "identity")
            verify_node()
            # Hold controller bytes before any candidate Cargo execution.
            controller_bytes = sdk.regular(Path(worker.__file__).with_suffix(".mjs"), 256*1024)
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
        if not browser_e2e:
            phase = "worker"
            receipt["workerProof"] = worker.execute(runner, private, work, node, verify_node, before,
                detach_installed_bindgen, installed_bindgen_provenance, controller_bytes)
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
    """Each reviewed singleton E2E selector consumes its exact-source package."""
    ambient = os.environ if environ is None else environ
    requested = json.loads(ambient.get("CI_SPECS_JSON", "[]"))
    sdk.require(browser_e2e_targets(requested), "admission")
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
    inventory = package_inventory(folder / "package", expected)
    generated = {row["path"]: sdk.regular(folder / "package" / row["path"]) for row in inventory["files"]}
    sdk.require(wasm_metadata(sdk.regular(folder / WASM_NAME, 128 * 1024**2)) == receipt["artifact"], "outputs")
    try:
        from scripts.ci_results import valid_browser_package
    except ModuleNotFoundError:
        from ci_results import valid_browser_package
    job = {"source": source, "run_id": ambient["GITHUB_RUN_ID"], "mode": "e2e", "specs": json.dumps(requested)}
    sdk.require(valid_browser_package(manifest_bytes, generated, receipt, job, ambient["CI_HARNESS_COMMIT"], expected, tree), "outputs")
    return {"OPENMATES_BROWSER_PACKAGE_MANIFEST": str(folder / "package-manifest.json"),
            "OPENMATES_BROWSER_PACKAGE_MANIFEST_SHA256": sdk.sha(manifest_bytes), "OPENMATES_BROWSER_SOURCE_COMMIT": source}
