"""One private Linux/AArch64 CLI compilation artifact; no runtime/release proof.

Runner/target/toolchain/commands are closed constants. Tickets reuse the existing
candidate bucket, presigner, expiry, URL validation and bounded HTTPS transport.
"""

from __future__ import annotations

import datetime as dt
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
import tempfile
import time
import tomllib
import uuid

try:
    from scripts import ci_sdk_conformance as sdk, ci_preparation_transport as transport
    from scripts import (
        check_rust_cli_package as package,
        sync_rust_cli_assets as assets,
    )
    from scripts import ci_native_supervisor as supervisor
except ModuleNotFoundError:
    import ci_sdk_conformance as sdk
    import ci_preparation_transport as transport
    import check_rust_cli_package as package
    import sync_rust_cli_assets as assets
    import ci_native_supervisor as supervisor

TARGET = "rust-native-dev"
RUNNER = "ubuntu-24.04-arm"
TRIPLE = "aarch64-unknown-linux-gnu"
VERSION = "1.98.1"
BUDGET = 2700
MAX_BINARY = 128 * 1024**2
MAX_RECEIPT = 4 * 1024**2
CLI = "frontend/packages/openmates-tui-native"
SDK = "packages/openmates-rust"
ROOTS = (CLI, SDK)
OBJECTS = ("build.json", "openmates")
TICKET_DIR = Path("logs/ci-coordinator/native-dev")
PREFIX = "candidates/native-dev/v2"
STAGES = (
    "rust-toolchain",
    "isolation-prepare",
    *supervisor.STAGES,
    "isolation-finish",
    "isolation-remove",
)
SECONDS = (300, 120, *(seconds + 15 for seconds in supervisor.LIMITS), 120, 90)
FAILURES = frozenset(
    {
        "admission",
        "identity",
        "source",
        "deadline",
        "disk",
        "toolchain",
        "package",
        "compile",
        "outputs",
        "transport",
        "cleanup",
        "unclassified",
    }
)
# Catalog validation reads these snapshots as data, never executes legacy code.
CATALOG = (
    "cli.ts",
    "server.ts",
    "benchmark.ts",
    "privacyCommands.ts",
    "generated/appSkills.ts",
    "generatedFiles.ts",
    "tasksCli.ts",
    "taskActivityHistory.ts",
    "taskMutationDelivery.ts",
    "taskActivityDelivery.ts",
    "taskDelivery.ts",
    "codexConnection.ts",
    "storage.ts",
    "plansCli.ts",
)
EXTRA = frozenset(
    {
        *assets.FILES.values(),
        "config/cli-command-catalog.json",
        "frontend/packages/workflowFile.ts",
        *("frontend/packages/openmates-cli/src/" + name for name in CATALOG),
    }
)


def validate_targets(targets):
    sdk.require(targets == [TARGET], "admission")


def validate_request(
    specs,
    *,
    preparation=None,
    runtime_seed=None,
    capacity=None,
    case_title="",
    proof_profile="",
):
    validate_targets(specs)
    sdk.require(
        not any((preparation, runtime_seed, capacity, case_title, proof_profile)),
        "admission",
    )


def owned(name):
    if name in EXTRA:
        return True
    for root in ROOTS:
        if name.startswith(root + "/"):
            tail = Path(name[len(root) + 1 :])
            return (
                tail.as_posix()
                in {"Cargo.toml", "Cargo.lock", "README.md", "LICENSE", "NOTICE"}
                or (
                    tail.parts[0] in {"src", "tests", "examples"}
                    and tail.suffix in {".rs", ".json", ".txt", ".md", ".toml"}
                )
                or tail.parts[0] == "assets"
            ) and not any(part.startswith(".") for part in tail.parts)
    return False


def source_inputs_from_git(root, source):
    sdk.require(
        isinstance(source, str) and re.fullmatch(r"[0-9a-f]{40}", source), "identity"
    )
    listing = subprocess.check_output(
        ["git", "ls-tree", "-r", "-z", source, "--", *ROOTS, *sorted(EXTRA)],
        cwd=root,
        timeout=15,
    )
    rows = {}
    for raw in listing.split(b"\0"):
        if not raw:
            continue
        header, raw_name = raw.split(b"\t", 1)
        name = raw_name.decode()
        sdk.require(name not in {root + "/build.rs" for root in ROOTS}, "source")
        if not owned(name):
            continue
        mode, kind, oid = header.decode().split()
        sdk.require(mode in {"100644", "100755"} and kind == "blob", "source")
        rows[name] = oid
    sdk.require(0 < len(rows) <= 5000, "source")
    # Batch reads bound both individual blobs and the complete source closure.
    request = "".join(oid + "\n" for oid in rows.values()).encode()
    metadata = subprocess.run(
        ["git", "cat-file", "--batch-check"],
        cwd=root,
        input=request,
        capture_output=True,
        check=True,
        timeout=30,
    ).stdout.splitlines()
    sdk.require(len(metadata) == len(rows), "source")
    total = 0
    for row, oid in zip(metadata, rows.values()):
        actual, kind, size = row.decode().split()
        sdk.require(
            actual == oid and kind == "blob" and 0 <= int(size) <= 64 * 1024**2,
            "source",
        )
        total += int(size)
    sdk.require(total <= 256 * 1024**2, "source")
    blobs = subprocess.run(
        ["git", "cat-file", "--batch"],
        cwd=root,
        input=request,
        capture_output=True,
        check=True,
        timeout=60,
    ).stdout
    sdk.require(len(blobs) <= total + len(rows) * 128, "source")
    offset, result = 0, {}
    for name, oid in rows.items():
        end = blobs.index(b"\n", offset)
        actual, kind, size = blobs[offset:end].decode().split()
        sdk.require(actual == oid and kind == "blob", "source")
        start = end + 1
        offset = start + int(size) + 1
        sdk.require(
            offset <= len(blobs) and blobs[offset - 1 : offset] == b"\n", "source"
        )
        result[name] = sdk.sha(blobs[start : offset - 1])
    sdk.require(
        offset == len(blobs)
        and EXTRA.issubset(result)
        and all(
            root + "/Cargo.toml" in result and root + "/Cargo.lock" in result
            for root in ROOTS
        )
        and CLI + "/src/main.rs" in result
        and SDK + "/src/lib.rs" in result,
        "source",
    )
    return result


def snapshot(root, expected):
    tracked = (
        subprocess.check_output(
            ["git", "ls-files", "-z", "--", *ROOTS, *sorted(EXTRA)],
            cwd=root,
            timeout=15,
        )
        .decode()
        .split("\0")
    )
    others = (
        subprocess.check_output(
            [
                "git",
                "ls-files",
                "--others",
                "--exclude-standard",
                "-z",
                "--",
                *ROOTS,
                *sorted(EXTRA),
            ],
            cwd=root,
            timeout=15,
        )
        .decode()
        .split("\0")
    )
    sdk.require(
        {name for name in tracked if name and owned(name)} == set(expected)
        and not any(name and owned(name) for name in others),
        "source",
    )
    return {name: sdk.sha(sdk.regular(root / name)) for name in expected}


def validate_manifests(work):
    for root in ROOTS:
        manifest = work / root / "Cargo.toml"
        value = tomllib.loads(sdk.regular(manifest).decode())
        sdk.require(
            not any(key in value for key in ("patch", "replace", "workspace"))
            and not value.get("package", {}).get("build"),
            "source",
        )

        def visit(item):
            if isinstance(item, dict):
                sdk.require(
                    not any(
                        key in item
                        for key in ("git", "registry", "registries", "patch", "replace")
                    ),
                    "source",
                )
                if "path" in item:
                    path = item["path"]
                    sdk.require(
                        isinstance(path, str)
                        and not Path(path).is_absolute()
                        and (manifest.parent / path).resolve()
                        in {work / name for name in ROOTS},
                        "source",
                    )
                for child in item.values():
                    visit(child)
            elif isinstance(item, list):
                for child in item:
                    visit(child)

        for section in (
            "dependencies",
            "dev-dependencies",
            "build-dependencies",
            "target",
        ):
            visit(value.get(section, {}))
        lock = tomllib.loads(sdk.regular(work / root / "Cargo.lock").decode())
        sdk.require(
            lock.get("version") in {3, 4}
            and lock.get("package")
            and all(
                row.get(
                    "source", "registry+https://github.com/rust-lang/crates.io-index"
                )
                == "registry+https://github.com/rust-lang/crates.io-index"
                for row in lock["package"]
            ),
            "source",
        )
    cli = tomllib.loads(sdk.regular(work / CLI / "Cargo.toml").decode())
    lib = tomllib.loads(sdk.regular(work / SDK / "Cargo.toml").decode())
    package.validate_metadata(cli, lib)
    sdk.require(
        all(value["package"].get("rust-version") == VERSION for value in (cli, lib)),
        "source",
    )
    assets.synchronize(work, check=True)
    package.audit_catalog_sources(work)


def elf_metadata(data):
    sdk.require(
        64 <= len(data) <= MAX_BINARY
        and data[:7] == b"\x7fELF\x02\x01\x01"
        and struct.unpack_from("<H", data, 16)[0] in {2, 3}
        and struct.unpack_from("<H", data, 18)[0] == 183,
        "outputs",
    )
    phoff = struct.unpack_from("<Q", data, 32)[0]
    phsize, phnum = struct.unpack_from("<HH", data, 54)
    sdk.require(
        phsize == 56
        and 0 < phnum <= 128
        and phoff >= 64
        and phoff + phsize * phnum <= len(data),
        "outputs",
    )
    interpreters = []
    for index in range(phnum):
        offset = phoff + index * phsize
        kind = struct.unpack_from("<I", data, offset)[0]
        if kind == 3:
            start, size = (
                struct.unpack_from("<Q", data, offset + 8)[0],
                struct.unpack_from("<Q", data, offset + 32)[0],
            )
            sdk.require(1 < size <= 256 and start + size <= len(data), "outputs")
            interpreters.append(data[start : start + size])
    sdk.require(interpreters == [b"/lib/ld-linux-aarch64.so.1\0"], "outputs")
    return {
        "name": "openmates",
        "bytes": len(data),
        "sha256": sdk.sha(data),
        "elf": "elf64-little-aarch64",
        "target": TRIPLE,
        "dynamicLoader": "/lib/ld-linux-aarch64.so.1",
    }


def _object_keys(job):
    validate_targets(json.loads(job["specs"]))
    sdk.require(
        job["mode"] == TARGET
        and re.fullmatch(r"[0-9a-f]{64}", job["id"])
        and re.fullmatch(r"[0-9a-f]{40}", job["source"])
        and re.fullmatch(r"ci-[0-9a-f]{32}", job.get("token", "")),
        "transport",
    )
    return {
        name: f"{PREFIX}/{job['source']}/{job['id']}/{job['token']}/{name}"
        for name in OBJECTS
    }


def validate_ticket(ticket, job, *, producer=False, now=None):
    keys = _object_keys(job)
    sdk.require(
        isinstance(ticket, dict)
        and set(ticket)
        == {"schemaVersion", "job", "token", "source", "expires", "objects"}
        and ticket["schemaVersion"] == 1
        and ticket["job"] == job["id"]
        and ticket["token"] == job["token"]
        and re.fullmatch(r"ci-[0-9a-f]{32}", ticket["token"])
        and ticket["source"] == job["source"]
        and transport._parse_expiry(ticket["expires"]) > transport._utc_now(now)
        and set(ticket["objects"]) == set(OBJECTS),
        "transport",
    )
    for name, key in keys.items():
        item = ticket["objects"][name]
        sdk.require(
            isinstance(item, dict)
            and set(item) == ({"put_url", "get_url"} if producer else {"get_url"}),
            "transport",
        )
        for value in item.values():
            transport._validate_url(
                value, expected_path=f"/{transport.BUCKET_NAME}/{key}"
            )
    return ticket


def dispatch_ticket(root, job, *, signer=None, now=None):
    now = transport._utc_now(now)
    keys = _object_keys(job)
    directory = root.resolve() / TICKET_DIR / job["id"]
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    sdk.require(
        not directory.is_symlink()
        and directory.resolve() == directory
        and directory.stat().st_uid == os.getuid(),
        "transport",
    )
    directory.chmod(0o700)
    path = directory / (job["token"] + ".json")
    with transport._TicketLock(directory / (job["token"] + ".lock")):
        if path.exists():
            ticket = json.loads(sdk.regular(path, 32768))
            validate_ticket(ticket, job, producer=True, now=now + dt.timedelta(hours=1))
        else:
            signed = (signer or transport._presign_objects)(
                keys, transport.EXPIRES_SECONDS
            )
            ticket = {
                "schemaVersion": 1,
                "job": job["id"],
                "token": job["token"],
                "source": job["source"],
                "expires": (
                    now + dt.timedelta(seconds=transport.EXPIRES_SECONDS)
                ).isoformat(),
                "objects": signed,
            }
            validate_ticket(ticket, job, producer=True, now=now)
            transport._write_ticket(path, ticket)
    return json.dumps(ticket, separators=(",", ":"))


def event_ticket(ambient):
    path = Path(ambient["GITHUB_EVENT_PATH"]).resolve(strict=True)
    with os.fdopen(
        os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK), "rb"
    ) as stream:
        info = os.fstat(stream.fileno())
        sdk.require(
            stat.S_ISREG(info.st_mode)
            and info.st_uid == os.getuid()
            and info.st_nlink == 1,
            "transport",
        )
        os.fchmod(stream.fileno(), 0o600)
    # Protect the original event containing all presigned capabilities before the
    # build UID exists. Different UID/no-new-privileges also excludes /proc access.
    event = json.loads(sdk.regular(path, 1024**2))
    inputs = event.get("inputs", {})
    ticket = json.loads(inputs.get("native_dev_transport", "{}"))
    job = {
        "id": inputs.get("dispatch_token", ""),
        "source": inputs.get("source_commit", ""),
        "specs": inputs.get("specs_json", "[]"),
        "mode": inputs.get("mode", ""),
        "token": inputs.get("dispatch_token", ""),
    }
    # Bind both full queue identity and the independently generated dispatch token.
    job["id"] = ticket.get("job", "")
    sdk.require(
        inputs.get("mode") == TARGET
        and inputs.get("source_commit") == ambient.get("BUILD_COMMIT_SHA"),
        "transport",
    )
    validate_ticket(ticket, job, producer=True)
    for item in ticket["objects"].values():
        for url in item.values():
            print("::add-mask::" + url, flush=True)
    return ticket, job


def _commands(cargo, rustc):
    # Kept as a pure recipe helper for receipt validation and fixtures.
    return [
        [rustc, "--version", "--verbose"],
        [cargo, "--version"],
        *[
            [
                cargo,
                "package",
                "--manifest-path",
                root + "/Cargo.toml",
                "--list",
                "--locked",
                "--offline",
                "--allow-dirty",
                "--quiet",
            ]
            for root in ROOTS
        ],
        [
            cargo,
            "build",
            "--locked",
            "--release",
            "--manifest-path",
            CLI + "/Cargo.toml",
            "--target",
            TRIPLE,
            "--bin",
            "openmates",
            "--jobs",
            "2",
        ],
    ]


def supervisor_command(action, sandbox, *, stage=None, deadline=None):
    sdk.require(action in {"prepare", "stage", "finish", "remove"}, "admission")
    command = [
        "/usr/bin/sudo",
        "-n",
        "/usr/bin/python3",
        "-I",
        "-S",
        str(Path(supervisor.__file__).resolve()),
        action,
        "--sandbox",
        str(sandbox),
    ]
    if stage is not None:
        sdk.require(stage in supervisor.STAGES and action == "stage", "admission")
        command += ["--stage", stage]
    if deadline is not None:
        sdk.require(action == "prepare" and math.isfinite(deadline), "admission")
        command += ["--deadline", str(deadline)]
    return command


def root_file(path, limit):
    # Separate strict reader for root-sealed supervisor outputs. The general
    # current-UID data reader and supplier rules remain unchanged.
    sdk.require(path.is_absolute() and path.resolve() == path, "outputs")
    return supervisor.read(path, limit, owner=0)


class NativeCommands(sdk.Commands):
    def run(self, stage, command, **kwargs):
        try:
            return super().run(stage, command, **kwargs)
        finally:
            if self.steps:
                self.steps[-1]["argv"] = list(command)
                self.steps[-1]["command"]["tool"] = (
                    "rustup" if stage == "rust-toolchain" else "native-supervisor"
                )


def run(root, results, *, environ=None):
    ambient = os.environ if environ is None else environ
    output = root / "test-results"
    receipt = {
        "schemaVersion": 2,
        "runtime_profile": TARGET,
        "status": "failed",
        "code": "admission",
        "compileProof": False,
        "runtimeProof": False,
        "performanceProof": False,
        "conformanceProof": False,
        "releaseProof": False,
        "publication": False,
        "services": {},
        "cleanupVerified": False,
        "sourceHeld": False,
    }
    before = runner = private = sandbox = None
    isolated = False
    source = tree = None
    phase = "admission"
    export = None
    try:
        sdk.require(
            ambient.get("GITHUB_ACTIONS") == "true"
            and ambient.get("RUNNER_ENVIRONMENT") == "github-hosted"
            and ambient.get("OPENMATES_CI_ISOLATED") == "1"
            and ambient.get("RUNNER_ARCH") == "ARM64"
            and platform.machine() == "aarch64"
            and os.sys.platform == "linux",
            "admission",
        )
        validate_request(
            json.loads(ambient.get("CI_SPECS_JSON", "[]")),
            preparation=ambient.get("CI_PREPARATION_KEY"),
            runtime_seed=ambient.get("CI_RUNTIME_SEED"),
            capacity=ambient.get("CI_CAPACITY_CONFIGURATION"),
            case_title=ambient.get("CI_CASE_TITLE"),
            proof_profile=ambient.get("PLAYWRIGHT_PROOF_VIDEO_PROFILE"),
        )
        sdk.require(not ambient.get("CI_PREPARED_RUN_ID"), "admission")
        phase = "identity"
        source, tree = (
            sdk.git(root, "rev-parse", "HEAD"),
            sdk.git(root, "rev-parse", "HEAD^{tree}"),
        )
        harness = ambient.get("CI_HARNESS_COMMIT", "")
        sdk.require(
            source == ambient.get("BUILD_COMMIT_SHA")
            and tree == ambient.get("CI_CANDIDATE_TREE")
            and re.fullmatch(r"[0-9a-f]{40}", harness)
            and re.fullmatch(r"[0-9]+", ambient.get("GITHUB_RUN_ID", ""))
            and sdk.git(Path(__file__).resolve().parent.parent, "rev-parse", "HEAD")
            == harness
            and subprocess.run(
                ["git", "symbolic-ref", "-q", "HEAD"],
                cwd=root,
                capture_output=True,
                timeout=15,
            ).returncode
            == 1,
            "identity",
        )
        ticket, job = event_ticket(ambient)
        phase = "deadline"
        started, deadline = (
            float(ambient["CI_NATIVE_DEV_STARTED_MONOTONIC"]),
            float(ambient["CI_NATIVE_DEV_DEADLINE_MONOTONIC"]),
        )
        sdk.require(
            math.isfinite(started)
            and math.isfinite(deadline)
            and abs(deadline - started - BUDGET) < 0.000001
            and started <= time.monotonic() < deadline,
            "deadline",
        )
        phase = "source"
        before = source_inputs_from_git(root, source)
        sdk.require(snapshot(root, before) == before, "source")
        receipt.update(
            source_commit=source,
            source_tree=tree,
            harness_commit=harness,
            run_id=ambient["GITHUB_RUN_ID"],
            job=job["id"],
            dispatchToken=job["token"],
            inputs=before,
            inputSetSha256=sdk.sha(json.dumps(before, sort_keys=True).encode()),
            locks={
                name + "/Cargo.lock": before[name + "/Cargo.lock"] for name in ROOTS
            },
            runner=RUNNER,
            target=TRIPLE,
            toolchain=VERSION,
        )
        phase = "disk"
        sdk.require(
            shutil.disk_usage(output).free >= sdk.RESERVE
            and shutil.disk_usage("/tmp").free >= sdk.RESERVE,
            "disk",
        )
        private = Path(
            tempfile.mkdtemp(
                prefix="native-dev-parent-", dir=Path(ambient["RUNNER_TEMP"])
            )
        )
        private.chmod(0o700)
        # The sticky, root-owned /tmp parent prevents build UID rename attacks.
        tmp_info = Path("/tmp").lstat()
        sdk.require(
            stat.S_ISDIR(tmp_info.st_mode)
            and tmp_info.st_uid == 0
            and tmp_info.st_mode & stat.S_ISVTX,
            "admission",
        )
        sandbox = Path("/tmp/openmates-native-dev-" + uuid.uuid4().hex)
        sandbox.mkdir(mode=0o700)
        work = sandbox / "source"
        work.mkdir(mode=0o700)
        for name, digest in before.items():
            data = sdk.regular(root / name)
            sdk.require(sdk.sha(data) == digest, "source")
            destination = work / name
            destination.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            destination.write_bytes(data)
        home, temp = private / "home", private / "tmp"
        home.mkdir(mode=0o700)
        temp.mkdir(mode=0o700)
        rustup = shutil.which("rustup")
        sdk.require(rustup, "toolchain")
        env = {
            "PATH": os.pathsep.join(
                [str(Path(rustup).parent), *os.defpath.split(os.pathsep)]
            ),
            "HOME": str(home),
            "TMPDIR": str(temp),
            "LANG": "C.UTF-8",
            "CI": "true",
            "RUSTUP_HOME": str(sandbox / "rustup"),
            "RUSTUP_TOOLCHAIN": VERSION,
            "CARGO_HOME": str(private / "cargo"),
        }
        validate_manifests(work)
        runner = NativeCommands(work, private, env, deadline)
        phase = "toolchain"
        runner.run(
            "rust-toolchain",
            [
                rustup,
                "toolchain",
                "install",
                VERSION,
                "--profile",
                "minimal",
                "--no-self-update",
            ],
            seconds=300,
        )
        # Privileged code is pinned by the exact harness, never loaded from source.
        receipt["supervisorSha256"] = sdk.sha(
            sdk.regular(Path(supervisor.__file__).resolve())
        )
        phase = "admission"
        runner.run(
            "isolation-prepare",
            supervisor_command("prepare", sandbox, deadline=deadline),
            seconds=120,
        )
        isolated = True
        # The root-owned source can no longer serve as the parent's cwd writer.
        runner.root = private
        for stage, seconds in zip(supervisor.STAGES, supervisor.LIMITS):
            phase = (
                "compile"
                if stage == "native-build"
                else "package"
                if "package-list" in stage
                else "toolchain"
            )
            sdk.require(snapshot(root, before) == before, "source")
            log = runner.run(
                stage,
                supervisor_command("stage", sandbox, stage=stage),
                seconds=seconds + 15,
            )
            proof = json.loads(
                root_file(sandbox / "proof" / (stage + ".json"), 1024**2)
            )
            sdk.require(
                proof.get("passed") is True
                and proof.get("uidEmpty") is True
                and proof.get("unexpectedDescendants") is False,
                "cleanup",
            )
            text = sdk.regular(log, sdk.MAX_LOG).decode()
            if stage == "rustc-version":
                sdk.require(
                    re.search(r"(?m)^release: 1\.98\.1$", text)
                    and re.search(r"(?m)^host: " + re.escape(TRIPLE) + r"$", text),
                    "toolchain",
                )
                receipt["rustcVersionSha256"] = sdk.sha(text.encode())
            elif stage == "cargo-version":
                sdk.require(
                    re.fullmatch(r"cargo 1\.98\.1 \([^\n]+\)\n", text), "toolchain"
                )
            elif "package-list" in stage:
                crate = CLI if stage == "cli-package-list" else SDK
                names = set(text.splitlines())
                sdk.require(
                    names
                    and names
                    <= {
                        name[len(crate) + 1 :]
                        for name in before
                        if name.startswith(crate + "/")
                    }
                    | {"Cargo.toml.orig", ".cargo_vcs_info.json"},
                    "package",
                )
                package.validate_inputs(work / crate, names)
                receipt.setdefault("packages", {})[crate] = sorted(names)
        phase = "cleanup"
        runner.run(
            "isolation-finish", supervisor_command("finish", sandbox), seconds=120
        )
        isolation = json.loads(root_file(sandbox / "proof/final.json", 4 * 1024**2))
        sdk.require(
            isolation.get("uidEmptyBeforeExport") is True
            and isolation.get("unexpectedDescendants") is False,
            "cleanup",
        )
        data = root_file(sandbox / "export/openmates", MAX_BINARY)
        sdk.require(
            sdk.sha(data) == isolation.get("binarySha256")
            and len(data) == isolation.get("binaryBytes"),
            "outputs",
        )
        receipt["isolation"] = isolation
        receipt["binary"] = elf_metadata(data)
        loader = Path(receipt["binary"]["dynamicLoader"]).resolve(strict=True)
        with sdk.admitted_command("native-loader", [str(loader)], env) as entry:
            os.lseek(entry.descriptor, 0, os.SEEK_SET)
            header = os.read(entry.descriptor, 64)
            sdk.require(
                len(header) == 64
                and header[:7] == b"\x7fELF\x02\x01\x01"
                and struct.unpack_from("<H", header, 18)[0] == 183
                and entry.metadata["executableBytes"] <= 16 * 1024**2,
                "outputs",
            )
            entry.held()
            receipt["buildLoader"] = {
                "path": str(loader),
                "sha256": entry.metadata["executableSha256"],
                "bytes": entry.metadata["executableBytes"],
            }
        runner.run(
            "isolation-remove", supervisor_command("remove", sandbox), seconds=90
        )
        sdk.require(not sandbox.exists(), "cleanup")
        isolated = False
        sandbox = None
        receipt["isolation"]["uidRemovedBeforeUpload"] = True
        validate_isolation(
            receipt["isolation"], receipt["binary"], receipt["supervisorSha256"]
        )
        receipt["cleanupVerified"] = True
        # All untrusted processes and their UID are gone before parent export.
        export = Path(
            tempfile.mkdtemp(
                prefix="native-dev-export-", dir=Path(ambient["RUNNER_TEMP"])
            )
        )
        export.chmod(0o700)
        with (export / "openmates").open("xb") as stream:
            os.fchmod(stream.fileno(), 0o600)
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
            sdk.require(os.fstat(stream.fileno()).st_nlink == 1, "outputs")
        receipt.update(status="passed", code=None, compileProof=True)
    except Exception:
        receipt.update(
            status="failed", code=phase if phase in FAILURES else "unclassified"
        )
    finally:
        if sandbox is not None:
            try:
                if isolated:
                    # Still use root UID-wide cleanup on failure; a process-group
                    # kill or rmtree is never accepted as this boundary.
                    cleanup_runner = NativeCommands(
                        private, private, runner.env, time.monotonic() + 90
                    )
                    cleanup_runner.run(
                        "isolation-remove",
                        supervisor_command("remove", sandbox),
                        seconds=85,
                    )
                else:
                    # No candidate code has run if root preparation never passed.
                    # A partial root prepare self-cleans its UID before failing.
                    if sandbox.exists() and sandbox.stat().st_uid == os.getuid():
                        shutil.rmtree(sandbox)
                receipt["cleanupVerified"] = not sandbox.exists()
            except Exception:
                receipt.update(status="failed", code="cleanup", cleanupVerified=False)
        if before is not None:
            try:
                receipt["sourceHeld"] = (
                    snapshot(root, before) == before
                    and sdk.git(root, "rev-parse", "HEAD") == source
                    and sdk.git(root, "rev-parse", "HEAD^{tree}") == tree
                )
            except Exception:
                receipt["sourceHeld"] = False
            if not receipt["sourceHeld"]:
                receipt.update(status="failed", code="source", compileProof=False)
        receipt["steps"] = runner.steps if runner else []
        if private is not None:
            try:
                shutil.rmtree(private)
            except OSError:
                receipt.update(status="failed", code="cleanup", cleanupVerified=False)
        if not receipt["cleanupVerified"]:
            receipt.update(status="failed", compileProof=False)
        if export is not None:
            try:
                if receipt["status"] == "passed":
                    sdk.write(export / "build.json", receipt)
                    for name in reversed(OBJECTS):
                        transport.put_file(
                            ticket["objects"][name]["put_url"],
                            export / name,
                            (export / name).stat().st_size,
                        )
            except Exception:
                receipt.update(status="failed", code="transport", compileProof=False)
            finally:
                shutil.rmtree(export)
        sdk.write(
            output / "ci-native-dev.json",
            {
                key: receipt[key]
                for key in (
                    "schemaVersion",
                    "runtime_profile",
                    "status",
                    "code",
                    "compileProof",
                    "runtimeProof",
                    "performanceProof",
                    "conformanceProof",
                    "releaseProof",
                    "publication",
                    "cleanupVerified",
                    "sourceHeld",
                )
            },
        )
        results.append(
            {
                "suite": TARGET,
                "exit_code": 0 if receipt["status"] == "passed" else 1,
                "failure_code": receipt["code"],
            }
        )
    return receipt


def validate_isolation(proof, binary_metadata, supervisor_sha):
    sdk.require(
        isinstance(proof, dict)
        and proof.get("schemaVersion") == 2
        and all(
            proof.get(key) is True
            for key in (
                "uidEmptyBeforeExport",
                "sourceRootReadonly",
                "toolchainRootReadonly",
                "compilerIdentityHeld",
                "noNewPrivileges",
                "capabilitiesDropped",
                "uidRemovedBeforeUpload",
            )
        )
        and proof.get("unexpectedDescendants") is False
        and type(proof.get("buildUid")) is int
        and 100 <= proof["buildUid"] < 1000
        and proof.get("binarySha256") == binary_metadata["sha256"]
        and proof.get("binaryBytes") == binary_metadata["bytes"],
        "outputs",
    )
    tools = proof.get("tools", {})
    sdk.require(set(tools) == {"rustc", "cargo"}, "outputs")
    for name, tool in tools.items():
        sdk.require(
            isinstance(tool, dict)
            and tool.get("owner") == "root-readonly"
            and Path(tool.get("path", "")).parts[-5:]
            == ("rustup", "toolchains", VERSION + "-" + TRIPLE, "bin", name)
            and re.fullmatch(r"[0-9a-f]{64}", tool.get("sha256", ""))
            and type(tool.get("bytes")) is int
            and 64 <= tool["bytes"] <= 256 * 1024**2,
            "outputs",
        )
        identity = tool.get("identity", [])
        sdk.require(
            isinstance(identity, list)
            and len(identity) == 9
            and all(type(item) is int for item in identity)
            and identity[3] == 0
            and stat.S_ISREG(identity[2])
            and identity[2] & 0o111
            and not identity[2] & 0o222
            and identity[6] == tool["bytes"],
            "outputs",
        )
    stages = proof.get("stages", [])
    sdk.require(
        [row.get("stage") for row in stages] == list(supervisor.STAGES), "outputs"
    )
    for index, row in enumerate(stages):
        expected = _commands(tools["cargo"]["path"], tools["rustc"]["path"])[index]
        sdk.require(
            row.get("passed") is True
            and row.get("failure") is None
            and row.get("uidEmpty") is True
            and row.get("unexpectedDescendants") is False
            and row.get("noNewPrivileges") is True
            and row.get("capabilitiesDropped") is True
            and row.get("tool") == tools["rustc" if index == 0 else "cargo"]
            and row.get("argv") == expected
            and row.get("argvSha256")
            == sdk.sha(json.dumps(expected, separators=(",", ":")).encode())
            and isinstance(row.get("elapsedSeconds"), (int, float))
            and 0 <= row["elapsedSeconds"] <= supervisor.LIMITS[index] + 15,
            "outputs",
        )
    sdk.require(re.fullmatch(r"[0-9a-f]{64}", supervisor_sha), "outputs")


def validate_result(
    receipt,
    job,
    harness,
    expected_tree,
    expected_inputs,
    binary,
    *,
    expected_supervisor,
):
    validate_targets(json.loads(job["specs"]))
    sdk.require(job.get("mode") == TARGET, "outputs")
    sdk.require(
        receipt.get("schemaVersion") == 2
        and receipt.get("runtime_profile") == TARGET
        and receipt.get("status") == "passed"
        and receipt.get("code") is None
        and receipt.get("source_commit") == job["source"]
        and receipt.get("source_tree") == expected_tree
        and receipt.get("harness_commit") == harness
        and str(receipt.get("run_id")) == str(job["run_id"])
        and receipt.get("job") == job["id"]
        and receipt.get("dispatchToken") == job["token"]
        and receipt.get("runner") == RUNNER
        and receipt.get("target") == TRIPLE
        and receipt.get("toolchain") == VERSION
        and receipt.get("inputs") == expected_inputs
        and receipt.get("inputSetSha256")
        == sdk.sha(json.dumps(expected_inputs, sort_keys=True).encode())
        and receipt.get("locks")
        == {
            root + "/Cargo.lock": expected_inputs[root + "/Cargo.lock"]
            for root in ROOTS
        }
        and receipt.get("binary") == elf_metadata(binary)
        and all(
            receipt.get(key) is True
            for key in ("sourceHeld", "cleanupVerified", "compileProof")
        )
        and all(
            receipt.get(key) is False
            for key in (
                "runtimeProof",
                "performanceProof",
                "conformanceProof",
                "releaseProof",
                "publication",
            )
        )
        and receipt.get("services") == {}
        and set(receipt.get("packages", {})) == set(ROOTS),
        "outputs",
    )
    sdk.require(receipt.get("supervisorSha256") == expected_supervisor, "outputs")
    validate_isolation(
        receipt.get("isolation"), receipt["binary"], receipt.get("supervisorSha256", "")
    )
    for crate, names in receipt["packages"].items():
        sdk.require(
            isinstance(names, list)
            and names == sorted(set(names))
            and all(
                isinstance(name, str)
                and not Path(name).is_absolute()
                and ".." not in Path(name).parts
                for name in names
            )
            and set(names)
            <= {
                name[len(crate) + 1 :]
                for name in expected_inputs
                if name.startswith(crate + "/")
            }
            | {"Cargo.toml.orig", ".cargo_vcs_info.json"},
            "outputs",
        )
    steps = receipt.get("steps")
    sdk.require(
        isinstance(steps, list) and [row.get("stage") for row in steps] == list(STAGES),
        "outputs",
    )
    for index, row in enumerate(steps):
        command, argv = row.get("command", {}), row.get("argv", [])
        sdk.require(
            isinstance(argv, list)
            and argv
            and all(isinstance(item, str) for item in argv),
            "outputs",
        )
        if index == 0:
            sdk.require(
                Path(argv[0]).name == "rustup"
                and argv[1:]
                == [
                    "toolchain",
                    "install",
                    VERSION,
                    "--profile",
                    "minimal",
                    "--no-self-update",
                ],
                "outputs",
            )
        else:
            sdk.require(
                argv[:5] == ["/usr/bin/sudo", "-n", "/usr/bin/python3", "-I", "-S"]
                and Path(argv[5]).name == "ci_native_supervisor.py"
                and argv[7] == "--sandbox"
                and re.fullmatch(r"/tmp/openmates-native-dev-[0-9a-f]{32}", argv[8]),
                "outputs",
            )
            if row["stage"] == "isolation-prepare":
                sdk.require(
                    argv[6] == "prepare"
                    and len(argv) == 11
                    and argv[9] == "--deadline",
                    "outputs",
                )
            elif row["stage"] == "isolation-finish":
                sdk.require(argv[6] == "finish" and len(argv) == 9, "outputs")
            elif row["stage"] == "isolation-remove":
                sdk.require(argv[6] == "remove" and len(argv) == 9, "outputs")
            else:
                sdk.require(
                    argv[6] == "stage"
                    and len(argv) == 11
                    and argv[9:] == ["--stage", row["stage"]],
                    "outputs",
                )
        sdk.require(
            row.get("status") == "passed"
            and row.get("started") is True
            and row.get("returncode") == 0
            and row.get("terminatedReturncode") == 0
            and isinstance(row.get("elapsedSeconds"), (int, float))
            and 0 <= row["elapsedSeconds"] <= SECONDS[index] + 4
            and command.get("executableKind") == "elf"
            and command.get("admission") == "strict-owner-mode"
            and command.get("tool") == ("rustup" if index == 0 else "native-supervisor")
            and command.get("argvSha256")
            == sdk.sha(json.dumps(argv, separators=(",", ":")).encode())
            and re.fullmatch(r"[0-9a-f]{64}", command.get("executableSha256", ""))
            and 0 < command.get("executableBytes", 0) <= 256 * 1024**2,
            "outputs",
        )
    loader = receipt.get("buildLoader", {})
    sdk.require(
        set(loader) == {"path", "sha256", "bytes"}
        and isinstance(loader["path"], str)
        and Path(loader["path"]).is_absolute()
        and re.fullmatch(r"[0-9a-f]{64}", loader["sha256"])
        and type(loader["bytes"]) is int
        and 64 <= loader["bytes"] <= 16 * 1024**2
        and re.fullmatch(r"[0-9a-f]{64}", receipt.get("rustcVersionSha256", "")),
        "outputs",
    )
    return True


def retrieve(root, job, harness, destination):
    ticket_path = root.resolve() / TICKET_DIR / job["id"] / (job["token"] + ".json")
    ticket = json.loads(sdk.regular(ticket_path, 32768))
    validate_ticket(ticket, job, producer=True)
    expected_tree = sdk.git(root, "rev-parse", job["source"] + "^{tree}")
    expected_inputs = source_inputs_from_git(root, job["source"])
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(
        prefix="native-result-", dir=destination.parent
    ) as temporary:
        path = Path(temporary)
        path.chmod(0o700)
        transport.get_file(
            ticket["objects"]["build.json"]["get_url"], path / "build.json", MAX_RECEIPT
        )
        receipt = json.loads(sdk.regular(path / "build.json", MAX_RECEIPT))
        metadata = receipt.get("binary", {})
        sdk.require(
            type(metadata.get("bytes")) is int
            and 64 <= metadata["bytes"] <= MAX_BINARY,
            "outputs",
        )
        transport.get_file(
            ticket["objects"]["openmates"]["get_url"],
            path / "openmates",
            MAX_BINARY,
            expected_size=metadata["bytes"],
        )
        validate_result(
            receipt,
            job,
            harness,
            expected_tree,
            expected_inputs,
            sdk.regular(path / "openmates", MAX_BINARY),
            expected_supervisor=sdk.sha(
                subprocess.check_output(
                    ["git", "show", harness + ":scripts/ci_native_supervisor.py"],
                    cwd=root,
                    timeout=15,
                )
            ),
        )
        result = {
            "request_id": job["id"],
            "source_commit": job["source"],
            "harness_commit": harness,
            "run_id": job["run_id"],
            "coverage_scope": "compilation-only",
            "directory": str(destination),
            "native_build": receipt,
            "private_artifact": {
                "path": "openmates",
                **metadata,
                "bucket": transport.BUCKET_NAME,
                "key": _object_keys(job)["openmates"],
            },
            "runtimeProof": False,
            "performanceProof": False,
            "conformanceProof": False,
            "releaseProof": False,
            "publication": False,
        }
        sdk.write(path / "receipt.json", result)
        path.rename(destination)
    return result
