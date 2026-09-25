#!/usr/bin/env python3
"""Install the root-owned OpenMates remote-command AppArmor boundary."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import grp
import hashlib
import os
from pathlib import Path
import pwd
import re
import shutil
import stat
import subprocess
import tempfile
from typing import Callable


MANAGED_MARKER = "# Managed by OpenMates remote-command AppArmor installer."
BROKER_PREFIX = f"#!/usr/bin/python3 -I\n{MANAGED_MARKER}\n".encode()
USERNAME = re.compile(r"[a-z_][a-z0-9_-]{0,31}\Z")
MAX_BROKER_BYTES = 512 * 1024
MAX_BWRAP_BYTES = 16 * 1024 * 1024
MAX_MASK_SOURCE_BYTES = 64 * 1024
MAX_MASK_BINARY_BYTES = 2 * 1024 * 1024
MASK_SOURCE_MARKER = b"/* Managed by OpenMates remote-command AppArmor installer. */"


@dataclass(frozen=True)
class InstallPaths:
    broker_source: Path
    mask_source: Path
    bwrap_source: Path = Path("/usr/bin/bwrap")
    compiler: Path = Path("/usr/bin/cc")
    broker_target: Path = Path("/usr/libexec/openmates-command-apparmor")
    bwrap_target: Path = Path("/usr/libexec/openmates-bwrap")
    mask_target: Path = Path("/usr/libexec/openmates-git-config-mask.so")
    mask_manifest_target: Path = Path("/usr/libexec/openmates-git-config-mask.so.sha256")
    sudoers_target: Path = Path("/etc/sudoers.d/openmates-command-apparmor")
    profile_target: Path = Path("/etc/apparmor.d/openmates-command-bwrap")
    parser: Path = Path("/usr/sbin/apparmor_parser")
    visudo: Path = Path("/usr/sbin/visudo")
    trust_boundary: Path = Path("/")
    trusted_uid: int = 0
    trusted_gid: int = 0


@dataclass
class Replacement:
    target: Path
    backup: Path | None


CommandRunner = Callable[[list[str]], subprocess.CompletedProcess[str]]
CompilerRunner = Callable[[list[str], Path, dict[str, str]], subprocess.CompletedProcess[str]]


def default_paths() -> InstallPaths:
    return InstallPaths(
        broker_source=Path(__file__).with_name("openmates_command_apparmor.py"),
        mask_source=Path(__file__).with_name("openmates_git_config_mask.c"),
    )


def run_command(command: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(command, text=True, capture_output=True, check=False)


def run_compiler(
    command: list[str],
    cwd: Path,
    environment: dict[str, str],
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        cwd=cwd,
        env=environment,
        text=True,
        capture_output=True,
        check=False,
    )


def _trusted_components(path: Path, boundary: Path) -> list[Path]:
    resolved_boundary = boundary.absolute()
    absolute = path.absolute()
    try:
        relative = absolute.relative_to(resolved_boundary)
    except ValueError as exc:
        raise RuntimeError(f"Managed path is outside its trust boundary: {absolute}") from exc
    components = [resolved_boundary]
    current = resolved_boundary
    for part in relative.parts:
        current /= part
        components.append(current)
    return components


def _assert_trusted_directory(path: Path, paths: InstallPaths) -> None:
    for component in _trusted_components(path, paths.trust_boundary):
        metadata = os.lstat(component)
        if not stat.S_ISDIR(metadata.st_mode) or stat.S_ISLNK(metadata.st_mode):
            raise RuntimeError(f"Trusted directory is not a real directory: {component}")
        if metadata.st_uid != paths.trusted_uid or metadata.st_mode & 0o022:
            raise RuntimeError(f"Trusted directory has unsafe ownership or mode: {component}")


def _assert_fixed_executable(path: Path, paths: InstallPaths) -> None:
    _assert_trusted_directory(path.parent, paths)
    metadata = os.lstat(path)
    if not stat.S_ISREG(metadata.st_mode) or stat.S_ISLNK(metadata.st_mode):
        raise RuntimeError(f"Required executable is not a regular file: {path}")
    if metadata.st_uid != paths.trusted_uid or metadata.st_mode & 0o022 or not metadata.st_mode & 0o111:
        raise RuntimeError(f"Required executable has unsafe ownership or mode: {path}")


def _assert_fixed_compiler(path: Path, paths: InstallPaths) -> None:
    """Validate a fixed compiler path, including every root-owned symlink hop."""
    _assert_trusted_directory(path.parent, paths)
    current = path.absolute()
    visited: set[Path] = set()
    for _ in range(16):
        if current in visited:
            raise RuntimeError(f"Required compiler contains a symlink cycle: {path}")
        visited.add(current)
        _assert_trusted_directory(current.parent, paths)
        metadata = os.lstat(current)
        if metadata.st_uid != paths.trusted_uid:
            raise RuntimeError(f"Required compiler has unsafe ownership: {current}")
        if stat.S_ISLNK(metadata.st_mode):
            destination = Path(os.readlink(current))
            current = (current.parent / destination).absolute() if not destination.is_absolute() else destination
            continue
        if not stat.S_ISREG(metadata.st_mode) or metadata.st_mode & 0o022 or not metadata.st_mode & 0o111:
            raise RuntimeError(f"Required compiler has unsafe ownership or mode: {current}")
        return
    raise RuntimeError(f"Required compiler has too many symlink hops: {path}")


def _read_regular(path: Path, *, max_bytes: int, allowed_uids: set[int]) -> bytes:
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    try:
        metadata = os.fstat(descriptor)
        if not stat.S_ISREG(metadata.st_mode) or metadata.st_uid not in allowed_uids:
            raise RuntimeError(f"Install source has unsafe ownership or type: {path}")
        if metadata.st_size < 1 or metadata.st_size > max_bytes:
            raise RuntimeError(f"Install source has an invalid size: {path}")
        chunks: list[bytes] = []
        remaining = max_bytes + 1
        while remaining:
            chunk = os.read(descriptor, min(64 * 1024, remaining))
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
        content = b"".join(chunks)
        if len(content) > max_bytes:
            raise RuntimeError(f"Install source exceeds its size limit: {path}")
        return content
    finally:
        os.close(descriptor)


def _existing_bytes(target: Path, paths: InstallPaths) -> bytes | None:
    try:
        metadata = os.lstat(target)
    except FileNotFoundError:
        return None
    if (not stat.S_ISREG(metadata.st_mode) or stat.S_ISLNK(metadata.st_mode)
            or metadata.st_uid != paths.trusted_uid or metadata.st_mode & 0o022):
        raise RuntimeError(f"Refusing to replace an unsafe managed target: {target}")
    return target.read_bytes()


def _require_managed_existing(
    target: Path,
    paths: InstallPaths,
    *,
    binary_source: bytes | None = None,
    expected_content: bytes | None = None,
) -> None:
    existing = _existing_bytes(target, paths)
    if existing is None:
        return
    if binary_source is not None:
        if existing != binary_source:
            raise RuntimeError(f"Refusing to replace an unknown dedicated executable: {target}")
        return
    marker = (MANAGED_MARKER + "\n").encode()
    if marker not in existing[:512]:
        raise RuntimeError(f"Refusing to overwrite an unmanaged file: {target}")
    if expected_content is not None and existing != expected_content:
        raise RuntimeError(f"Refusing to change an existing managed user or policy: {target}")


def render_mask_manifest(binary: bytes) -> bytes:
    return (
        f"{MANAGED_MARKER}\n"
        f"sha256={hashlib.sha256(binary).hexdigest()}\n"
    ).encode()


def _require_managed_mask_existing(paths: InstallPaths) -> None:
    binary = _existing_bytes(paths.mask_target, paths)
    manifest = _existing_bytes(paths.mask_manifest_target, paths)
    if binary is None and manifest is None:
        return
    if binary is None or manifest is None:
        raise RuntimeError("Refusing to replace an incomplete Git config mask installation")
    if len(binary) > MAX_MASK_BINARY_BYTES:
        raise RuntimeError("Refusing to replace an oversized Git config mask library")
    if manifest != render_mask_manifest(binary):
        raise RuntimeError("Refusing to replace an unknown Git config mask library")


def render_sudoers(user: str) -> bytes:
    return (
        f"{MANAGED_MARKER}\n"
        f"{user} ALL=(root) NOPASSWD: /usr/libexec/openmates-command-apparmor \"\"\n"
    ).encode()


def render_bootstrap_profile(uid: int) -> bytes:
    return f"""{MANAGED_MARKER}
# This installer exclusively owns the fixed openmates-bwrap profile name.
# This profile is attached only to the dedicated OpenMates bubblewrap copy.
# Runtime profiles are generated by the privileged broker from bounded JSON.
abi <abi/4.0>,
include <tunables/global>

profile openmates-bwrap /usr/libexec/openmates-bwrap flags=(unconfined) {{
  userns,
  change_profile -> openmates-command.{uid}.[0-9a-f]*,
}}
""".encode()


def _stage(
    target: Path,
    content: bytes,
    mode: int,
    paths: InstallPaths,
    *,
    owner_gid: int | None = None,
) -> Path:
    descriptor, name = tempfile.mkstemp(prefix=f".{target.name}.stage-", dir=target.parent)
    staged = Path(name)
    try:
        os.fchmod(descriptor, mode)
        os.fchown(descriptor, paths.trusted_uid, paths.trusted_gid if owner_gid is None else owner_gid)
        with os.fdopen(descriptor, "wb", closefd=True) as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        return staged
    except Exception:
        try:
            os.close(descriptor)
        except OSError:
            pass
        staged.unlink(missing_ok=True)
        raise


def _check(command: list[str], runner: CommandRunner) -> None:
    result = runner(command)
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "validation failed").strip()
        raise RuntimeError(f"Command failed ({command[0]}): {detail[:1000]}")


def _compile_mask(
    source: bytes,
    paths: InstallPaths,
    runner: CompilerRunner,
) -> bytes:
    work_directory = Path(tempfile.mkdtemp(prefix=".openmates-mask-build-", dir=paths.mask_target.parent))
    source_path = work_directory / "openmates_git_config_mask.c"
    output_path = work_directory / "openmates-git-config-mask.so"
    try:
        os.chown(work_directory, paths.trusted_uid, paths.trusted_gid)
        os.chmod(work_directory, 0o700)
        descriptor = os.open(source_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        try:
            os.fchown(descriptor, paths.trusted_uid, paths.trusted_gid)
            with os.fdopen(descriptor, "wb", closefd=True) as handle:
                handle.write(source)
                handle.flush()
                os.fsync(handle.fileno())
        except Exception:
            try:
                os.close(descriptor)
            except OSError:
                pass
            raise
        command = [
            str(paths.compiler),
            "-shared",
            "-fPIC",
            "-O2",
            "-Wall",
            "-Wextra",
            "-Werror",
            str(source_path),
            "-o",
            str(output_path),
            "-ldl",
        ]
        environment = {
            "HOME": "/root",
            "LANG": "C",
            "LC_ALL": "C",
            "PATH": "/usr/bin:/bin",
            "TMPDIR": str(work_directory),
        }
        result = runner(command, work_directory, environment)
        if result.returncode != 0:
            detail = (result.stderr or result.stdout or "compilation failed").strip()
            raise RuntimeError(f"Git config mask compilation failed: {detail[:1000]}")
        return _read_regular(
            output_path,
            max_bytes=MAX_MASK_BINARY_BYTES,
            allowed_uids={paths.trusted_uid},
        )
    finally:
        shutil.rmtree(work_directory, ignore_errors=False)


def _replace(staged: Path, target: Path) -> Replacement:
    backup: Path | None = None
    if target.exists():
        descriptor, name = tempfile.mkstemp(prefix=f".{target.name}.backup-", dir=target.parent)
        os.close(descriptor)
        backup = Path(name)
        shutil.copy2(target, backup, follow_symlinks=False)
        metadata = os.lstat(target)
        os.chown(backup, metadata.st_uid, metadata.st_gid, follow_symlinks=False)
        os.chmod(backup, stat.S_IMODE(metadata.st_mode), follow_symlinks=False)
    os.replace(staged, target)
    directory = os.open(target.parent, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(directory)
    finally:
        os.close(directory)
    return Replacement(target=target, backup=backup)


def _rollback(replacements: list[Replacement]) -> None:
    errors: list[str] = []
    for replacement in reversed(replacements):
        try:
            if replacement.backup is None:
                replacement.target.unlink(missing_ok=True)
            else:
                os.replace(replacement.backup, replacement.target)
        except OSError as exc:
            errors.append(f"{replacement.target}: {exc}")
    if errors:
        raise RuntimeError("Installer rollback failed: " + "; ".join(errors))


def install(
    user: str,
    *,
    paths: InstallPaths | None = None,
    runner: CommandRunner = run_command,
    compiler_runner: CompilerRunner = run_compiler,
) -> None:
    paths = paths or default_paths()
    if os.geteuid() != 0 and paths.trusted_uid == 0:
        raise RuntimeError("This installer must run as root")
    if not USERNAME.fullmatch(user):
        raise RuntimeError("Invalid local user name")
    account = pwd.getpwnam(user)
    if account.pw_uid == 0:
        raise RuntimeError("The remote-command broker cannot be granted to root")
    group = grp.getgrgid(account.pw_gid)
    group_users = {entry.pw_name for entry in pwd.getpwall() if entry.pw_gid == account.pw_gid}
    group_users.update(group.gr_mem)
    if group_users - {user}:
        raise RuntimeError("The selected user's primary group is shared with another account")
    invoking_user = os.environ.get("SUDO_USER")
    if invoking_user and invoking_user != "root" and invoking_user != user:
        raise RuntimeError("--user must match the user who invoked sudo")

    for directory in {
        paths.broker_target.parent,
        paths.bwrap_target.parent,
        paths.mask_target.parent,
        paths.mask_manifest_target.parent,
        paths.sudoers_target.parent,
        paths.profile_target.parent,
    }:
        _assert_trusted_directory(directory, paths)
    for executable in (paths.bwrap_source, paths.parser, paths.visudo):
        _assert_fixed_executable(executable, paths)
    _assert_fixed_compiler(paths.compiler, paths)

    broker = _read_regular(
        paths.broker_source,
        max_bytes=MAX_BROKER_BYTES,
        allowed_uids={paths.trusted_uid, account.pw_uid},
    )
    if not broker.startswith(BROKER_PREFIX):
        raise RuntimeError("Broker source lacks the exact managed shebang and marker")
    mask_source = _read_regular(
        paths.mask_source,
        max_bytes=MAX_MASK_SOURCE_BYTES,
        allowed_uids={paths.trusted_uid, account.pw_uid},
    )
    if MASK_SOURCE_MARKER not in mask_source[:512]:
        raise RuntimeError("Git config mask source lacks the exact managed marker")
    bwrap = _read_regular(paths.bwrap_source, max_bytes=MAX_BWRAP_BYTES, allowed_uids={paths.trusted_uid})
    sudoers = render_sudoers(user)
    profile = render_bootstrap_profile(account.pw_uid)

    _require_managed_existing(paths.broker_target, paths)
    _require_managed_existing(paths.bwrap_target, paths, binary_source=bwrap)
    _require_managed_mask_existing(paths)
    _require_managed_existing(paths.sudoers_target, paths, expected_content=sudoers)
    _require_managed_existing(paths.profile_target, paths, expected_content=profile)
    mask_binary = _compile_mask(mask_source, paths, compiler_runner)
    mask_manifest = render_mask_manifest(mask_binary)

    stages: list[Path] = []
    replacements: list[Replacement] = []
    preserve_backups = False
    load_attempted = False
    try:
        staged_broker = _stage(paths.broker_target, broker, 0o755, paths)
        staged_bwrap = _stage(paths.bwrap_target, bwrap, 0o750, paths, owner_gid=account.pw_gid)
        staged_mask = _stage(paths.mask_target, mask_binary, 0o755, paths)
        staged_mask_manifest = _stage(paths.mask_manifest_target, mask_manifest, 0o644, paths)
        staged_sudoers = _stage(paths.sudoers_target, sudoers, 0o440, paths)
        staged_profile = _stage(paths.profile_target, profile, 0o644, paths)
        stages.extend([
            staged_broker,
            staged_bwrap,
            staged_mask,
            staged_mask_manifest,
            staged_sudoers,
            staged_profile,
        ])

        _check([str(paths.visudo), "-cf", str(staged_sudoers)], runner)
        _check([str(paths.parser), "-Q", "-T", "-K", str(staged_profile)], runner)

        for staged, target in (
            (staged_broker, paths.broker_target),
            (staged_bwrap, paths.bwrap_target),
            (staged_mask, paths.mask_target),
            (staged_mask_manifest, paths.mask_manifest_target),
            (staged_sudoers, paths.sudoers_target),
            (staged_profile, paths.profile_target),
        ):
            replacements.append(_replace(staged, target))

        load_attempted = True
        _check([str(paths.parser), "-r", "-T", "-K", str(paths.profile_target)], runner)
    except Exception as error:
        had_previous_profile = any(
            replacement.target == paths.profile_target and replacement.backup is not None
            for replacement in replacements
        )
        try:
            _rollback(replacements)
        except Exception as rollback_error:
            preserve_backups = True
            raise RuntimeError(f"{error}; {rollback_error}") from error
        if load_attempted and had_previous_profile:
            recovery = runner([str(paths.parser), "-r", "-T", "-K", str(paths.profile_target)])
            if recovery.returncode != 0:
                detail = (recovery.stderr or recovery.stdout or "kernel profile recovery failed").strip()
                raise RuntimeError(f"{error}; restored files but failed to restore the prior kernel profile: {detail[:1000]}") from error
        raise
    finally:
        for staged in stages:
            staged.unlink(missing_ok=True)
        for replacement in replacements:
            if replacement.backup is not None and not preserve_backups:
                replacement.backup.unlink(missing_ok=True)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--user", required=True, help="Existing non-root user allowed to invoke the broker")
    args = parser.parse_args()
    install(args.user)
    print("Installed the OpenMates remote-command AppArmor boundary.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
