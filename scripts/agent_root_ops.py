#!/usr/bin/python3 -I
"""Privileged helper for a small, fixed set of root operations used by agents.

Installed once by the user (see ``agent-root-ops-setup.sh``) as a root-owned
copy at ``/usr/local/sbin/openmates-agent-root-ops`` and invoked through a
single sudoers rule. Agents can edit every file in the repository, so this
helper never executes repo-controlled code: it accepts only fixed verbs with
validated arguments, calls binaries by absolute path without a shell, and
scrubs the environment. The only repo content it ever reads is the dev
Caddyfile, and only when the caller names its exact sha256.

Verbs:
  systemctl <start|status|is-active> <unit>   (caddy.service, user@<uid>.service)
  systemctl restart|reload caddy.service
  caddy validate | reload | apply <sha256>
  apparmor status | reload <profile-name>

Installing or changing AppArmor profile content and building or installing
the Caddy binary or its DNS token stay manual steps.
"""

from __future__ import annotations

import dataclasses
import hashlib
import os
import pwd
import re
import shutil
import stat
import subprocess
import sys
import syslog
import tempfile
import time
from pathlib import Path
from typing import Callable, Optional, Sequence

SAFE_PATH = "/usr/sbin:/usr/bin:/sbin:/bin"
SYSLOG_IDENT = "openmates-agent-root-ops"
USERNAME_RE = re.compile(r"[a-z_][a-z0-9_-]{0,31}")
SHA256_RE = re.compile(r"[0-9a-f]{64}")
PROFILE_RE = re.compile(r"openmates[a-z0-9._-]{0,60}")
MAX_CADDYFILE_BYTES = 1024 * 1024
BACKUPS_TO_KEEP = 20
COMMAND_TIMEOUT_SECONDS = 60
DUMMY_DNS_TOKEN = "openmates-caddyfile-syntax-check-token"
EXIT_OK = 0
EXIT_FAILED = 1
EXIT_USAGE = 2

USAGE = """Allowed verbs:
  systemctl start|restart|reload|status|is-active caddy.service
  systemctl start|status|is-active user@<your-uid>.service
  caddy validate
  caddy reload
  caddy apply <sha256-of-dev-Caddyfile>
  apparmor status
  apparmor reload <openmates-profile-name>
"""

RunResult = tuple[int, str]
Runner = Callable[[Sequence[str], Optional[dict]], RunResult]


class OpsError(Exception):
    """A request was refused or an operation failed; message is user-facing."""


@dataclasses.dataclass(frozen=True)
class Context:
    """Filesystem locations and collaborators. main() only ever uses the defaults."""

    live_caddyfile: Path = Path("/etc/caddy/Caddyfile")
    backup_dir: Path = Path("/var/backups/openmates-caddy")
    apparmor_dir: Path = Path("/etc/apparmor.d")
    home_root: Path = Path("/home")
    systemctl: str = "/usr/bin/systemctl"
    caddy: str = "/usr/bin/caddy"
    apparmor_parser: str = "/usr/sbin/apparmor_parser"
    aa_status: str = "/usr/sbin/aa-status"
    runner: Optional[Runner] = None
    sudo_user: str = ""
    sudo_uid: int = -1
    require_root_owned: bool = True


def default_runner(args: Sequence[str], env: Optional[dict]) -> RunResult:
    """Run an argument list without a shell and return (exit code, output)."""
    full_env = {"PATH": SAFE_PATH}
    if env:
        full_env.update(env)
    try:
        done = subprocess.run(
            list(args), env=full_env, stdin=subprocess.DEVNULL, capture_output=True,
            text=True, timeout=COMMAND_TIMEOUT_SECONDS, check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        return 127, f"{args[0]}: {error}"
    return done.returncode, (done.stdout + done.stderr).strip()


def _run(ctx: Context, args: Sequence[str], env: Optional[dict] = None) -> RunResult:
    return (ctx.runner or default_runner)(args, env)


# ---------------------------------------------------------------- self check


def home_directories() -> set:
    """Return every home directory in the passwd database plus /home and /root."""
    homes = {"/home", "/root"}
    for entry in pwd.getpwall():
        if entry.pw_dir and entry.pw_dir != "/":
            homes.add(os.path.normpath(entry.pw_dir))
    return homes


def check_self_integrity(
    path: str,
    stat_fn: Callable[[str], os.stat_result] = os.lstat,
    homes: Optional[set] = None,
) -> None:
    """Raise OpsError unless ``path`` is root-owned, not group/world-writable
    (including every parent directory) and not located under a home directory."""
    real = os.path.abspath(path)
    for home in homes if homes is not None else home_directories():
        if real == home or real.startswith(home.rstrip("/") + "/"):
            raise OpsError(f"refusing to run from a home directory: {real}")
    current = real
    while True:
        info = stat_fn(current)
        if info.st_uid != 0:
            raise OpsError(f"{current} is not owned by root")
        if info.st_mode & (stat.S_IWGRP | stat.S_IWOTH):
            raise OpsError(f"{current} is group- or world-writable")
        parent = os.path.dirname(current)
        if parent == current:
            return
        current = parent


# ---------------------------------------------------------------- validation


def resolve_sudo_user(env: dict) -> tuple:
    """Return the invoking (non-root) user name and uid from SUDO_USER."""
    name = env.get("SUDO_USER", "")
    if not USERNAME_RE.fullmatch(name):
        raise OpsError("SUDO_USER is missing or invalid; run through sudo as a regular user")
    try:
        uid = pwd.getpwnam(name).pw_uid
    except KeyError as error:
        raise OpsError(f"unknown user {name}") from error
    if uid == 0:
        raise OpsError("the invoking user must not be root")
    return name, uid


def validate_unit(unit: str, uid: int) -> None:
    """Allow only caddy.service and the invoking user's user@<uid>.service."""
    if unit != "caddy.service" and unit != f"user@{uid}.service":
        raise OpsError(f"unit not allowed: {unit!r}")


def validate_profile_name(name: str) -> None:
    """Allow only OpenMates-managed AppArmor profile file names."""
    if not PROFILE_RE.fullmatch(name):
        raise OpsError(f"profile name not allowed: {name!r}")


# ------------------------------------------------------------------- systemctl


def _emit(result: RunResult) -> int:
    code, output = result
    if output:
        print(output)
    return EXIT_OK if code == 0 else EXIT_FAILED


def op_systemctl(ctx: Context, args: Sequence[str]) -> int:
    """systemctl <action> <unit> for allowlisted units only."""
    if len(args) != 2:
        raise OpsError("usage: systemctl <start|restart|status|is-active|reload> <unit>")
    action, unit = args
    validate_unit(unit, ctx.sudo_uid)
    if action in ("reload", "restart"):
        # Restarting user@<uid>.service ends every process of that user,
        # including all running agent chats, so it stays a manual step.
        if unit != "caddy.service":
            raise OpsError(f"{action} is only allowed for caddy.service")
    elif action not in ("start", "restart", "status", "is-active"):
        raise OpsError(f"systemctl action not allowed: {action!r}")
    cmd = [ctx.systemctl, action]
    if action == "status":
        cmd.append("--no-pager")
    cmd.append(unit)
    return _emit(_run(ctx, cmd))


# ----------------------------------------------------------------------- caddy


def _validation_env(content: bytes) -> dict:
    # The DNS token is only needed to load the config, never to validate syntax.
    if re.search(rb"^\s*dns\s+gandi(\s|$)", content, re.MULTILINE):
        return {"GANDI_BEARER_TOKEN": DUMMY_DNS_TOKEN}
    return {}


def _caddy_validate(ctx: Context, path: Path, content: bytes) -> RunResult:
    return _run(
        ctx,
        [ctx.caddy, "validate", "--config", str(path), "--adapter", "caddyfile"],
        _validation_env(content),
    )


def _read_live(ctx: Context) -> bytes:
    try:
        return ctx.live_caddyfile.read_bytes()
    except OSError as error:
        raise OpsError(f"cannot read live Caddyfile: {error}") from error


def caddy_validate_live(ctx: Context) -> int:
    """Validate the live Caddyfile."""
    return _emit(_caddy_validate(ctx, ctx.live_caddyfile, _read_live(ctx)))


def caddy_reload(ctx: Context) -> int:
    """Reload Caddy after the live config validates."""
    code, output = _caddy_validate(ctx, ctx.live_caddyfile, _read_live(ctx))
    if code != 0:
        print(output)
        raise OpsError("live Caddyfile does not validate; not reloading")
    return _emit(_run(ctx, [ctx.systemctl, "reload", "caddy.service"]))


def canonical_dev_caddyfile(ctx: Context) -> Path:
    """Path of the dev Caddyfile in the invoking user's canonical checkout."""
    return (ctx.home_root / ctx.sudo_user / "projects" / "OpenMates"
            / "deployment" / "dev_server" / "Caddyfile")


def read_dev_caddyfile(ctx: Context) -> bytes:
    """Read the canonical dev Caddyfile without following symlinks."""
    path = canonical_dev_caddyfile(ctx)
    current = ctx.home_root
    for part in path.relative_to(ctx.home_root).parts:
        current = current / part
        try:
            info = os.lstat(current)
        except OSError as error:
            raise OpsError(f"cannot stat {current}: {error}") from error
        if stat.S_ISLNK(info.st_mode):
            raise OpsError(f"refusing symlink in path: {current}")
    fd = -1
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC)
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode):
            raise OpsError("Caddyfile is not a regular file")
        if info.st_size > MAX_CADDYFILE_BYTES:
            raise OpsError("Caddyfile exceeds the 1 MiB size cap")
        with os.fdopen(fd, "rb") as handle:
            fd = -1
            return handle.read(MAX_CADDYFILE_BYTES + 1)
    except OSError as error:
        raise OpsError(f"cannot read {path}: {error}") from error
    finally:
        if fd >= 0:
            os.close(fd)


def _atomic_replace(target: Path, content: bytes, uid: int, gid: int, mode: int) -> None:
    descriptor, name = tempfile.mkstemp(prefix=f".{target.name}.", dir=target.parent)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.chown(name, uid, gid)
        os.chmod(name, mode)
        os.replace(name, target)
    except OSError:
        Path(name).unlink(missing_ok=True)
        raise


def _prune_backups(directory: Path) -> None:
    backups = sorted(p for p in directory.glob("Caddyfile.*") if p.is_file())
    for old in backups[:-BACKUPS_TO_KEEP]:
        old.unlink(missing_ok=True)


def caddy_apply(ctx: Context, expected_hash: str) -> int:
    """Install the hash-pinned dev Caddyfile, reload, and roll back on failure."""
    if not SHA256_RE.fullmatch(expected_hash):
        raise OpsError("caddy apply needs a lowercase hex sha256")
    content = read_dev_caddyfile(ctx)
    if len(content) > MAX_CADDYFILE_BYTES:
        raise OpsError("Caddyfile exceeds the 1 MiB size cap")
    actual = hashlib.sha256(content).hexdigest()
    if actual != expected_hash:
        raise OpsError(f"sha256 mismatch: Caddyfile is {actual}, expected {expected_hash}")

    with tempfile.TemporaryDirectory(prefix="openmates-caddy-") as scratch:
        copy = Path(scratch) / "Caddyfile"
        copy.write_bytes(content)
        code, output = _caddy_validate(ctx, copy, content)
    if code != 0:
        print(output)
        raise OpsError("Caddyfile validation failed; live config untouched")

    try:
        live_info = os.stat(ctx.live_caddyfile)
    except OSError as error:
        raise OpsError(f"cannot stat live Caddyfile: {error}") from error
    previous = _read_live(ctx)
    ctx.backup_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    backup = ctx.backup_dir / f"Caddyfile.{stamp}"
    shutil.copyfile(ctx.live_caddyfile, backup)
    os.chmod(backup, 0o600)
    _prune_backups(ctx.backup_dir)

    mode = stat.S_IMODE(live_info.st_mode)
    _atomic_replace(ctx.live_caddyfile, content, live_info.st_uid, live_info.st_gid, mode)
    code, output = _run(ctx, [ctx.systemctl, "reload", "caddy.service"])
    if code == 0:
        print(f"applied Caddyfile {actual}; backup at {backup}")
        return EXIT_OK
    print(output)
    _atomic_replace(ctx.live_caddyfile, previous, live_info.st_uid, live_info.st_gid, mode)
    code2, output2 = _run(ctx, [ctx.systemctl, "reload", "caddy.service"])
    print("reload failed; previous Caddyfile restored"
          + ("" if code2 == 0 else f" but second reload also failed: {output2}"))
    return EXIT_FAILED


def op_caddy(ctx: Context, args: Sequence[str]) -> int:
    """caddy validate | reload | apply <sha256>."""
    if list(args) == ["validate"]:
        return caddy_validate_live(ctx)
    if list(args) == ["reload"]:
        return caddy_reload(ctx)
    if len(args) == 2 and args[0] == "apply":
        return caddy_apply(ctx, args[1])
    raise OpsError("usage: caddy validate | reload | apply <sha256>")


# -------------------------------------------------------------------- apparmor


def op_apparmor(ctx: Context, args: Sequence[str]) -> int:
    """apparmor status | reload <profile-name> (existing root-owned profile only)."""
    if list(args) == ["status"]:
        return _emit(_run(ctx, [ctx.aa_status, "--json"]))
    if len(args) == 2 and args[0] == "reload":
        validate_profile_name(args[1])
        profile = ctx.apparmor_dir / args[1]
        try:
            info = os.lstat(profile)
        except OSError as error:
            raise OpsError(f"profile not found: {profile}") from error
        if not stat.S_ISREG(info.st_mode):
            raise OpsError("profile is not a regular file")
        if ctx.require_root_owned and info.st_uid != 0:
            raise OpsError("profile file is not root-owned")
        if info.st_mode & (stat.S_IWGRP | stat.S_IWOTH):
            raise OpsError("profile file is group- or world-writable")
        return _emit(_run(ctx, [ctx.apparmor_parser, "-r", str(profile)]))
    raise OpsError("usage: apparmor status | reload <profile-name>")


# ------------------------------------------------------------------------ main

VERBS = {"systemctl": op_systemctl, "caddy": op_caddy, "apparmor": op_apparmor}


def run(argv: Sequence[str], ctx: Context, log: Callable[[str], None]) -> int:
    """Dispatch one request; log the verb, args, caller and result."""
    if not argv or argv[0] not in VERBS:
        print(USAGE, file=sys.stderr)
        log(f"rejected args={list(argv)} user={ctx.sudo_user}")
        return EXIT_USAGE
    try:
        code = VERBS[argv[0]](ctx, list(argv[1:]))
        result = "ok" if code == 0 else f"failed({code})"
    except OpsError as error:
        print(f"refused: {error}", file=sys.stderr)
        code, result = EXIT_USAGE, f"refused: {error}"
    log(f"verb={argv[0]} args={list(argv[1:])} user={ctx.sudo_user} result={result}")
    return code


def main(argv: Sequence[str]) -> int:
    """Entry point: root-only, fixed paths, scrubbed environment."""
    if argv[:1] in (["-h"], ["--help"]):
        print(USAGE)
        return EXIT_OK
    if os.geteuid() != 0:
        print("must run as root through sudo (see agent-root-ops-setup.sh)", file=sys.stderr)
        return EXIT_USAGE
    try:
        check_self_integrity(os.path.realpath(__file__))
        user, uid = resolve_sudo_user(dict(os.environ))
    except OpsError as error:
        print(f"refused: {error}", file=sys.stderr)
        return EXIT_USAGE
    os.environ.clear()
    os.environ["PATH"] = SAFE_PATH
    syslog.openlog(SYSLOG_IDENT, syslog.LOG_PID, syslog.LOG_AUTH)
    ctx = Context(sudo_user=user, sudo_uid=uid)
    return run(argv, ctx, lambda message: syslog.syslog(syslog.LOG_NOTICE, message))


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
