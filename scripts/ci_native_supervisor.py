#!/usr/bin/env python3
"""Fixed privileged supervisor for one disposable GitHub-hosted ARM build UID.

Invoked by trusted parent only. No accounts/privileges are changed by unit tests.
Candidate programs never share the parent's UID, capability files or writable
compiler tree. All compile commands and credential-free child env are closed.
"""

from __future__ import annotations
import argparse
import ctypes
import hashlib
import json
import math
import os
from pathlib import Path
import pwd
import re
import resource
import shutil
import signal
import stat
import subprocess
import tempfile
import time

TRIPLE = "aarch64-unknown-linux-gnu"
VERSION = "1.98.1"
CLI = "frontend/packages/openmates-tui-native"
SDK = "packages/openmates-rust"
STAGES = (
    "rustc-version",
    "cargo-version",
    "cli-package-list",
    "sdk-package-list",
    "native-build",
)
LIMITS = (30, 30, 120, 120, 2100)
RESERVE = 2 * 1024**3
MAX_LOG = 32 * 1024**2
MAX_BINARY = 128 * 1024**2
MAX_PROCESSES = 8192


class Refused(RuntimeError):
    pass


def require(value, code):
    if not value:
        raise Refused(code)


def sha(data):
    return hashlib.sha256(data).hexdigest()


def identity(info):
    return [
        getattr(info, name)
        for name in (
            "st_dev",
            "st_ino",
            "st_mode",
            "st_uid",
            "st_gid",
            "st_nlink",
            "st_size",
            "st_mtime_ns",
            "st_ctime_ns",
        )
    ]


def write(path, value, mode=0o644):
    with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as handle:
        os.fchmod(handle.fileno(), mode)
        handle.write((json.dumps(value, sort_keys=True) + "\n").encode())
        handle.flush()
        os.fsync(handle.fileno())
        temporary = handle.name
    os.replace(temporary, path)


def read(path, limit=4 * 1024**2, *, owner=0):
    with os.fdopen(
        os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK), "rb"
    ) as handle:
        before = os.fstat(handle.fileno())
        require(
            stat.S_ISREG(before.st_mode)
            and before.st_uid == owner
            and not before.st_mode & 0o022
            and before.st_size <= limit,
            "file",
        )
        data = handle.read(limit + 1)
        require(
            len(data) <= limit
            and identity(before)
            == identity(os.fstat(handle.fileno()))
            == identity(path.lstat()),
            "file-held",
        )
        return data


def protect_tree(path):
    """No links are followed while transferring files to immutable root ownership."""
    count = 0
    for parent, directories, files in os.walk(path, followlinks=False):
        current = Path(parent)
        require(not current.is_symlink(), "protected-link")
        for name in directories + files:
            child = current / name
            info = child.lstat()
            count += 1
            require(
                count <= 50000
                and (stat.S_ISDIR(info.st_mode) or stat.S_ISREG(info.st_mode)),
                "protected-type",
            )
            os.chown(child, 0, 0, follow_symlinks=False)
            os.chmod(
                child,
                0o555 if stat.S_ISDIR(info.st_mode) or info.st_mode & 0o111 else 0o444,
                follow_symlinks=False,
            )
        os.chown(current, 0, 0)
        os.chmod(current, 0o555)


def protected_snapshot(sandbox):
    rows = {}
    for name in ("source", "rustup"):
        base = sandbox / name
        for parent, directories, files in os.walk(base, followlinks=False):
            for child in [
                Path(parent),
                *(Path(parent) / item for item in directories + files),
            ]:
                info = child.lstat()
                require(
                    info.st_uid == 0
                    and not info.st_mode & 0o222
                    and (stat.S_ISREG(info.st_mode) or stat.S_ISDIR(info.st_mode)),
                    "immutable-tree",
                )
                rows[str(child.relative_to(sandbox))] = identity(info)
                require(len(rows) <= 50000, "tree-bound")
    return rows


def process_uid_ids(status):
    rows = [line for line in status.splitlines() if line.startswith("Uid:")]
    require(len(rows) == 1, "process-uid")
    values = rows[0].split()[1:]
    require(
        len(values) == 4 and all(value.isdecimal() for value in values), "process-uid"
    )
    return {int(value) for value in values}


def owned_processes(uid, proc=Path("/proc")):
    require(type(uid) is int and 100 <= uid < 60000, "build-uid")
    result = []
    entries = list(proc.iterdir())
    require(len(entries) <= MAX_PROCESSES, "process-bound")
    for entry in entries:
        if not entry.name.isdecimal():
            continue
        try:
            with (entry / "status").open("rb") as handle:
                raw = handle.read(65537)
            require(len(raw) <= 65536, "process-bound")
            if uid in process_uid_ids(raw.decode()):
                result.append(int(entry.name))
        except FileNotFoundError:
            pass
    return sorted(result)


def reap():
    for _ in range(512):
        try:
            if os.waitpid(-1, os.WNOHANG)[0] == 0:
                return
        except ChildProcessError:
            return


def stop_uid(
    uid,
    *,
    clock=time.monotonic,
    sleep=time.sleep,
    observe=owned_processes,
    kill=os.kill,
):
    """UID membership survives setsid; root subreaper owns detached descendants."""
    deadline = clock() + 10
    seen = False
    while True:
        reap()
        processes = observe(uid)
        if not processes:
            return {"empty": True, "unexpectedDescendants": seen}
        seen = True
        require(clock() < deadline, "uid-not-empty")
        for pid in processes:
            try:
                kill(pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
        sleep(0.05)


def require_no_escape(cleanup):
    require(
        cleanup == {"empty": True, "unexpectedDescendants": False}, "escaped-descendant"
    )


def commands(sandbox):
    toolbin = sandbox / "rustup/toolchains" / (VERSION + "-" + TRIPLE) / "bin"
    cargo, rustc = str(toolbin / "cargo"), str(toolbin / "rustc")
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
            for root in (CLI, SDK)
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


def tool_identity(path, sandbox):
    require(path.is_relative_to(sandbox / "rustup/toolchains"), "compiler-path")
    info = path.lstat()
    require(
        stat.S_ISREG(info.st_mode)
        and info.st_uid == 0
        and info.st_mode & 0o111
        and not info.st_mode & 0o222,
        "compiler-writable",
    )
    for parent in path.parents:
        if parent == Path("/tmp"):
            break
        mode = parent.lstat()
        require(
            stat.S_ISDIR(mode.st_mode)
            and mode.st_uid == 0
            and not mode.st_mode & 0o022,
            "compiler-parent",
        )
    data = read(path, 256 * 1024**2)
    require(
        data[:7] == b"\x7fELF\x02\x01\x01"
        and int.from_bytes(data[18:20], "little") == 183,
        "compiler-elf",
    )
    return {
        "path": str(path),
        "sha256": sha(data),
        "bytes": len(data),
        "identity": identity(info),
        "owner": "root-readonly",
    }


def caller(sandbox):
    require(
        os.geteuid() == 0
        and re.fullmatch(r"/tmp/openmates-native-dev-[0-9a-f]{32}", str(sandbox)),
        "root-sandbox",
    )
    require(not sandbox.is_symlink() and sandbox.resolve() == sandbox, "sandbox-link")
    uid = int(os.environ.get("SUDO_UID", "0"))
    require(1000 <= uid < 60000, "parent-uid")
    tmp = Path("/tmp").lstat()
    require(
        tmp.st_uid == 0 and stat.S_ISDIR(tmp.st_mode) and tmp.st_mode & stat.S_ISVTX,
        "sticky-parent",
    )
    program = Path(__file__).resolve(strict=True)
    for path in [program, *program.parents]:
        info = path.lstat()
        require(
            info.st_uid in {0, uid}
            and not info.st_mode & 0o002
            and (stat.S_ISREG(info.st_mode) or stat.S_ISDIR(info.st_mode)),
            "trusted-supervisor",
        )
    return uid


def state(sandbox):
    parent = caller(sandbox)
    value = json.loads(read(sandbox / "state.json"))
    require(
        value["parentUid"] == parent
        and value["sandboxIdentity"] == identity(sandbox.lstat())[:2],
        "sandbox-held",
    )
    return value


def prepare(sandbox, deadline):
    parent = caller(sandbox)
    info = sandbox.lstat()
    require(
        info.st_uid == parent and stat.S_IMODE(info.st_mode) == 0o700, "sandbox-owner"
    )
    require(
        math.isfinite(deadline)
        and time.monotonic() < deadline <= time.monotonic() + 2700,
        "deadline",
    )
    username = "omci" + sandbox.name[-12:]
    account = None
    uid_admitted = False
    try:
        pwd.getpwnam(username)
    except KeyError:
        pass
    else:
        raise Refused("build-account-exists")
    try:
        # Source is verified/copied by parent; no candidate code has run.
        protect_tree(sandbox / "source")
        protect_tree(sandbox / "rustup")
        os.chown(sandbox, 0, 0)
        os.chmod(sandbox, 0o711)
        subprocess.run(
            [
                "/usr/sbin/useradd",
                "--system",
                "--user-group",
                "--no-create-home",
                "--home-dir",
                "/nonexistent",
                "--shell",
                "/usr/sbin/nologin",
                username,
            ],
            check=True,
            env={"PATH": os.defpath},
            timeout=30,
        )
        account = pwd.getpwnam(username)
        require(
            account.pw_uid != parent
            and 100 <= account.pw_uid < 1000
            and account.pw_gid > 0,
            "build-account",
        )
        require(not owned_processes(account.pw_uid), "uid-already-active")
        uid_admitted = True
        metadata = {
            "schemaVersion": 1,
            "parentUid": parent,
            "uid": account.pw_uid,
            "gid": account.pw_gid,
            "username": username,
            "deadline": deadline,
            "sandboxIdentity": identity(sandbox.lstat())[:2],
            "finished": False,
            "stages": [],
            "protected": protected_snapshot(sandbox),
        }
        for name in ("home", "tmp", "cargo", "target"):
            path = sandbox / name
            path.mkdir(mode=0o700)
            os.chown(path, account.pw_uid, account.pw_gid)
        (sandbox / "proof").mkdir(mode=0o755)
        (sandbox / "export").mkdir(mode=0o755)
        metadata["tools"] = {
            name: tool_identity(
                sandbox / "rustup/toolchains" / (VERSION + "-" + TRIPLE) / "bin" / name,
                sandbox,
            )
            for name in ("cargo", "rustc")
        }
        write(sandbox / "state.json", metadata, 0o600)
    except Exception:
        # A partial prepare may have created a UID. Never strand that identity or
        # equate a failed chmod/copy with successful account cleanup.
        if account is None:
            try:
                account = pwd.getpwnam(username)
            except KeyError:
                pass
        if account is not None:
            require(
                100 <= account.pw_uid < 1000
                and account.pw_dir == "/nonexistent"
                and account.pw_shell == "/usr/sbin/nologin",
                "build-account-cleanup",
            )
            if uid_admitted:
                stop_uid(account.pw_uid)
            subprocess.run(
                ["/usr/sbin/userdel", username],
                check=True,
                env={"PATH": os.defpath},
                timeout=30,
            )
            require(not owned_processes(account.pw_uid), "uid-not-empty")
        shutil.rmtree(sandbox)
        raise


def run_stage(sandbox, stage):
    value = state(sandbox)
    require(
        not value["finished"] and stage == STAGES[len(value["stages"])], "stage-order"
    )
    require(protected_snapshot(sandbox) == value["protected"], "immutable-held")
    uid, gid = value["uid"], value["gid"]
    require_no_escape(stop_uid(uid))
    index = STAGES.index(stage)
    command = commands(sandbox)[index]
    tool = "rustc" if index == 0 else "cargo"
    require(
        tool_identity(Path(command[0]), sandbox) == value["tools"][tool],
        "compiler-replaced",
    )
    env = {
        "PATH": str(Path(command[0]).parent) + os.pathsep + os.defpath,
        "HOME": str(sandbox / "home"),
        "TMPDIR": str(sandbox / "tmp"),
        "LANG": "C.UTF-8",
        "CI": "true",
        "RUSTUP_HOME": str(sandbox / "rustup"),
        "RUSTUP_TOOLCHAIN": VERSION,
        "CARGO_HOME": str(sandbox / "cargo"),
        "CARGO_TARGET_DIR": str(sandbox / "target"),
        "RUSTC": str(
            sandbox / "rustup/toolchains" / (VERSION + "-" + TRIPLE) / "bin/rustc"
        ),
        "CARGO_NET_RETRY": "2",
        "CARGO_HTTP_TIMEOUT": "60",
    }
    # No setuid binary or file capability can restore privilege in descendants.
    launch = [
        "/usr/bin/setpriv",
        "--reuid",
        str(uid),
        "--regid",
        str(gid),
        "--clear-groups",
        "--no-new-privs",
        "--bounding-set=-all",
        "--inh-caps=-all",
        "--ambient-caps=-all",
        "--",
        *command,
    ]
    started = time.monotonic()
    child = None
    passed = False
    cleanup = None
    failure = None
    try:
        resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
        resource.setrlimit(resource.RLIMIT_NPROC, (256, 256))
        resource.setrlimit(resource.RLIMIT_NOFILE, (1024, 1024))
        # Become the parent of escaped orphan descendants, including setsid.
        require(
            ctypes.CDLL(None, use_errno=True).prctl(36, 1, 0, 0, 0) == 0, "subreaper"
        )
        child = subprocess.Popen(
            launch,
            cwd=sandbox / "source",
            env=env,
            stdin=subprocess.DEVNULL,
            start_new_session=True,
        )
        while child.poll() is None:
            require(
                time.monotonic() < min(value["deadline"], started + LIMITS[index]),
                "deadline",
            )
            require(shutil.disk_usage(sandbox).free >= RESERVE, "disk")
            require(len(owned_processes(uid)) <= 256, "process-bound")
            time.sleep(0.25)
        require(child.returncode == 0, "child-failed")
        cleanup = stop_uid(uid)
        require_no_escape(cleanup)
        require(
            protected_snapshot(sandbox) == value["protected"]
            and tool_identity(Path(command[0]), sandbox) == value["tools"][tool],
            "compiler-held",
        )
        passed = True
    except Exception as error:
        failure = str(error) if isinstance(error, Refused) else "supervisor"
    finally:
        if child is not None and child.poll() is None:
            try:
                os.kill(child.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            child.wait(timeout=10)
        final_cleanup = stop_uid(uid)
        cleanup = cleanup or final_cleanup
        if final_cleanup["unexpectedDescendants"]:
            passed = False
            failure = "escaped-descendant"
        record = {
            "stage": stage,
            "passed": passed,
            "failure": failure,
            "uidEmpty": final_cleanup["empty"],
            "unexpectedDescendants": cleanup["unexpectedDescendants"],
            "noNewPrivileges": True,
            "capabilitiesDropped": True,
            "tool": value["tools"][tool],
            "argv": command,
            "argvSha256": sha(json.dumps(command, separators=(",", ":")).encode()),
            "elapsedSeconds": round(time.monotonic() - started, 3),
        }
        write(sandbox / "proof" / (stage + ".json"), record)
        value["stages"].append(record)
        write(sandbox / "state.json", value, 0o600)
    require(passed, failure or "stage-failed")


def finish(sandbox):
    value = state(sandbox)
    cleanup = stop_uid(value["uid"])
    require_no_escape(cleanup)
    require(
        [row["stage"] for row in value["stages"]] == list(STAGES)
        and all(row["passed"] for row in value["stages"]),
        "stages-incomplete",
    )
    require(protected_snapshot(sandbox) == value["protected"], "immutable-held")
    # Open every component without following links. No build-UID process remains.
    descriptors = []
    try:
        descriptor = os.open(sandbox, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        descriptors.append(descriptor)
        for component in ("target", TRIPLE, "release"):
            descriptor = os.open(
                component,
                os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
                dir_fd=descriptor,
            )
            descriptors.append(descriptor)
        fd = os.open(
            "openmates", os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=descriptor
        )
        with os.fdopen(fd, "rb") as handle:
            before = os.fstat(handle.fileno())
            require(
                stat.S_ISREG(before.st_mode)
                and before.st_uid == value["uid"]
                and 64 <= before.st_size <= MAX_BINARY,
                "artifact",
            )
            os.fchown(handle.fileno(), 0, 0)
            os.fchmod(handle.fileno(), 0o444)
            sealed = os.fstat(handle.fileno())
            data = handle.read(MAX_BINARY + 1)
            require(
                len(data) == sealed.st_size
                and identity(sealed) == identity(os.fstat(handle.fileno())),
                "artifact-held",
            )
        require(not owned_processes(value["uid"]), "uid-not-empty")
        # The independent inode is created only after UID-wide emptiness proof.
        destination = sandbox / "export/openmates"
        with destination.open("xb") as output:
            os.fchmod(output.fileno(), 0o444)
            output.write(data)
            output.flush()
            os.fsync(output.fileno())
            exported = os.fstat(output.fileno())
            require(
                exported.st_nlink == 1 and exported.st_ino != sealed.st_ino,
                "export-inode",
            )
        proof = {
            "schemaVersion": 2,
            "uidEmptyBeforeExport": True,
            "unexpectedDescendants": False,
            "sourceRootReadonly": True,
            "toolchainRootReadonly": True,
            "compilerIdentityHeld": True,
            "noNewPrivileges": True,
            "capabilitiesDropped": True,
            "buildUid": value["uid"],
            "binarySha256": sha(data),
            "binaryBytes": len(data),
            "stages": value["stages"],
            "tools": value["tools"],
        }
        write(sandbox / "proof/final.json", proof)
        value["finished"] = True
        write(sandbox / "state.json", value, 0o600)
    finally:
        for fd in descriptors:
            os.close(fd)


def remove(sandbox):
    value = state(sandbox)
    cleanup = stop_uid(value["uid"])
    require(cleanup["empty"], "uid-not-empty")
    subprocess.run(
        ["/usr/sbin/userdel", value["username"]],
        check=True,
        env={"PATH": os.defpath},
        timeout=30,
    )
    require(not owned_processes(value["uid"]), "uid-not-empty")
    shutil.rmtree(sandbox)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=("prepare", "stage", "finish", "remove"))
    parser.add_argument("--sandbox", type=Path, required=True)
    parser.add_argument("--stage", choices=STAGES)
    parser.add_argument("--deadline", type=float)
    args = parser.parse_args()
    try:
        if args.action == "prepare":
            require(args.deadline is not None and args.stage is None, "arguments")
            prepare(args.sandbox, args.deadline)
        elif args.action == "stage":
            require(args.stage is not None and args.deadline is None, "arguments")
            run_stage(args.sandbox, args.stage)
        elif args.action == "finish":
            require(args.stage is None and args.deadline is None, "arguments")
            finish(args.sandbox)
        else:
            require(args.stage is None and args.deadline is None, "arguments")
            remove(args.sandbox)
    except Exception as error:
        print(
            "native-supervisor: "
            + (str(error) if isinstance(error, Refused) else "failed"),
            flush=True,
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
