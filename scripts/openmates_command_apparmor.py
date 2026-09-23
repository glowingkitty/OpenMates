#!/usr/bin/python3 -I
# Managed by OpenMates remote-command AppArmor installer.
"""Narrow root-owned AppArmor policy broker for the OpenMates CLI.

Installed by setup_remote_command_apparmor.py. Accepts bounded declarations on
stdin, never profile text, filenames, parser options, or executable arguments.
Profiles are immutable and cached by effective policy until reboot. In particular
release NEVER unloads a profile: removing one while a child still uses it would
remove that child's confinement. Normal repeated commands reuse the same profile.
"""

from __future__ import annotations

import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import stat
import subprocess
import sys

PROTOCOL_VERSION = 1
POLICY_VERSION = 1
STATE_ROOT = Path("/run/openmates-command-apparmor")
PARSER = "/usr/sbin/apparmor_parser"
MAX_REQUEST_BYTES = 256 * 1024
MAX_PROFILES_PER_USER = 256
MAX_LEASES_PER_USER = 1024
MAX_PATHS = 1024
MAX_GLOBS = 256
MAX_PROFILE_BYTES = 256 * 1024
HEX_DIGEST = re.compile(r"[a-f0-9]{64}\Z")
LEASE_ID = re.compile(r"[a-f0-9]{32}\Z")
EXECUTION_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,127}\Z")

# Deliberately owned by the privileged broker. A client cannot omit the minimum
# policy. Unit coverage checks parity with the shared product credential list.
PRIVATE_BASENAMES = (
    ".env", ".env.*", ".npmrc", ".pypirc", ".netrc", ".pgpass", ".my.cnf",
    ".git-credentials", "credentials", "credentials.json",
    "application_default_credentials.json", "id_rsa", "id_ed25519", "id_dsa",
    "id_ecdsa", "*.pem", "*.key", "*.p12", "*.pfx", "*.keystore", "*.kdbx",
    "*.credentials",
)
MANDATORY_PRIVATE = tuple(f"**/{name}" for name in PRIVATE_BASENAMES) + (
    "**/.ssh/**", "**/.aws/**", "**/.gnupg/**", "**/.config/gcloud/**",
    "**/.openmates/permissions.yml", "**/.git/config",
)
MANDATORY_READONLY = (
    "**/AGENTS.md", "**/CLAUDE.md", "**/.openmates/rules/**",
    "**/.claude/rules/**", "**/.agents/rules/**",
)


class PolicyError(ValueError):
    """A request cannot safely be represented or installed."""


def require_keys(value: object, keys: set[str]) -> dict:
    if not isinstance(value, dict) or set(value) != keys:
        raise PolicyError("Invalid request fields")
    return value


def validate_path(value: object, *, pattern: bool) -> str:
    if not isinstance(value, str) or not value or len(value) > 512:
        raise PolicyError("Invalid Project-relative path")
    if any(ord(c) < 32 or ord(c) == 127 for c in value) or "\\" in value:
        raise PolicyError("Invalid Project-relative path characters")
    if value.startswith(("!", "//")) or re.match(r"^[A-Za-z]:", value):
        raise PolicyError("Private rules must be additive Project-relative paths")
    if value.startswith("/"):
        if not pattern:
            raise PolicyError("Exact paths must be relative")
        value = value[1:]
    if value.endswith("/"):
        value = value[:-1]
    if not value or any(part in ("", ".", "..") for part in value.split("/")):
        raise PolicyError("Invalid Project-relative path segments")
    return value


def literal(character: str) -> str:
    # AppArmor is case-sensitive; private matching in the product deliberately
    # protects case variants. Generated bracket classes contain ASCII only.
    if character.isascii() and character.isalpha():
        return f"[{character.lower()}{character.upper()}]"
    if not character.isascii():
        # The kernel glob engine works on bytes; `?` is insufficient for UTF-8.
        # Widen non-ASCII private-name characters rather than under-protect a
        # Unicode case variant accepted by the shared case-insensitive matcher.
        return "*"
    if character in '*?[]{}^"@\\':
        return "\\" + character
    return character


def path_expression(value: str, *, pattern: bool) -> str:
    """Compile conservative Git-style deny patterns, with no policy injection.

    Git bracket classes are widened to `?`, never interpreted as literal text
    (which could under-protect a matching path). `**/` includes zero directories.
    A matched directory and descendants are protected even without a trailing /.
    """
    value = validate_path(value, pattern=pattern)
    if pattern and value.endswith("/**"):
        value = value[:-3]
    result = []
    index = 0
    while index < len(value):
        char = value[index]
        if pattern and value[index:index + 3] == "**/":
            result.append("{,**/}")
            index += 3
        elif pattern and char == "[":
            end = value.find("]", index + 2 if value[index:index + 2] in ("[!", "[^") else index + 1)
            if end < 0:
                result.append(literal(char))
                index += 1
            else:
                result.append("?")
                index = end + 1
        elif pattern and char in "*?":
            result.append(char)
            index += 1
        else:
            result.append(literal(char))
            index += 1
    return "/project/" + "".join(result) + "{,/**}"


def normalize_paths(values: object) -> list[dict]:
    if not isinstance(values, list) or len(values) > MAX_PATHS:
        raise PolicyError("Too many protected Project paths")
    paths = {}
    for item in values:
        require_keys(item, {"path", "kind"})
        if item["kind"] not in ("file", "directory"):
            raise PolicyError("Invalid path kind")
        path = validate_path(item["path"], pattern=False)
        paths[path] = {"path": path, "kind": item["kind"]}
    return [paths[key] for key in sorted(paths)]


def ancestor_expressions(value: str, *, pattern: bool) -> set[str]:
    """Prevent moving a parent directory to bypass an anchored child denial.

    Pure leading ** can move without changing which descendant matches. Other
    parents must remain in place, e.g. config/ for config/private.json. Directory
    write denial also prevents terminal creation/removal of those policy-bearing
    directories; ordinary source file edits and unrelated directories still work.
    """
    parts = validate_path(value, pattern=pattern).split("/")
    result = set()
    for length in range(1, len(parts)):
        prefix = parts[:length]
        if pattern and all(part == "**" for part in prefix):
            continue
        expression = path_expression("/".join(prefix), pattern=pattern)
        result.add(expression.removesuffix("{,/**}") + "/")
        # path_expression deliberately strips a trailing /** for privacy; for
        # ancestors we must deny descendant directory relocation as well.
        if pattern and prefix[-1] == "**":
            result.add(expression.removesuffix("{,/**}") + "/**/")
    return result


def normalize_prepare(request: object) -> dict:
    request = require_keys(request, {
        "protocol_version", "action", "execution_id", "project_root_digest",
        "private_policy_digest", "private_globs", "exact_private_aliases",
        "exact_readonly_paths",
    })
    if request["protocol_version"] != PROTOCOL_VERSION or request["action"] != "prepare":
        raise PolicyError("Unsupported broker protocol")
    if not isinstance(request["execution_id"], str) or not EXECUTION_ID.fullmatch(request["execution_id"]):
        raise PolicyError("Invalid execution identifier")
    for key in ("project_root_digest", "private_policy_digest"):
        if not isinstance(request[key], str) or not HEX_DIGEST.fullmatch(request[key]):
            raise PolicyError("Invalid policy digest")
    patterns = request["private_globs"]
    if not isinstance(patterns, list) or len(patterns) > MAX_GLOBS:
        raise PolicyError("Too many private patterns")
    patterns = sorted(set(validate_path(value, pattern=True) for value in patterns))
    return {
        "policy_version": POLICY_VERSION,
        "project_root_digest": request["project_root_digest"],
        "private_policy_digest": request["private_policy_digest"],
        "private_globs": patterns,
        "exact_private_aliases": normalize_paths(request["exact_private_aliases"]),
        "exact_readonly_paths": normalize_paths(request["exact_readonly_paths"]),
    }


def definition_digest(policy: dict) -> str:
    # Bind the generated enforcement too, so an updated broker cannot silently
    # reuse an older, weaker cached profile after its built-ins/rules change.
    encoded = json.dumps(policy, sort_keys=True, separators=(",", ":")).encode()
    encoded += b"\n" + render_profile("openmates-command.0." + "0" * 64, policy).encode()
    return hashlib.sha256(encoded).hexdigest()


def render_profile(name: str, policy: dict) -> str:
    if not re.fullmatch(r"openmates-command\.[0-9]+\.[a-f0-9]{64}", name):
        raise PolicyError("Invalid generated profile name")
    private = set(path_expression(value, pattern=True) for value in (*MANDATORY_PRIVATE, *policy["private_globs"]))
    private.update(path_expression(item["path"], pattern=False) for item in policy["exact_private_aliases"])
    readonly = set(path_expression(value, pattern=True) for value in MANDATORY_READONLY)
    readonly.update(path_expression(item["path"], pattern=False) for item in policy["exact_readonly_paths"])
    ancestors = set()
    for value in (*MANDATORY_PRIVATE, *MANDATORY_READONLY, *policy["private_globs"]):
        ancestors.update(ancestor_expressions(value, pattern=True))
    for item in (*policy["exact_private_aliases"], *policy["exact_readonly_paths"]):
        ancestors.update(ancestor_expressions(item["path"], pattern=False))
    lines = [
        "# Generated immutable OpenMates command policy; do not replace/unload while in use.",
        f"profile {name} flags=(mediate_deleted) {{",
        # Bubblewrap grants the visible filesystem/network namespace; AppArmor
        # adds live path denials. All executables inherit this enforced profile.
        "  /** rwkm,", "  /** ix,", "  network,", "  unix,", "  signal,",
        "  audit deny /** l,",  # no new hardlinks, including allowed aliases
        "  audit deny mount,", "  audit deny umount,", "  audit deny pivot_root,",
        "  audit deny userns,", "  audit deny change_profile,",
        "  audit deny capability,", "  audit deny ptrace,",
        # Credentials are not exposed via inherited handles or process memory.
        '  audit deny "/proc/**/mem" rwklmx,',
        '  audit deny "/proc/**/attr/**" wkl,',
        '  audit deny "/sys/**" wkl,',
        '  audit deny "/usr/libexec/openmates-command-apparmor" rwklmx,',
        '  audit deny "/usr/bin/sudo" x,',
    ]
    lines.extend(f'  audit deny "{path}" rwklmx,' for path in sorted(private))
    lines.extend(f'  audit deny "{path}" wkl,' for path in sorted(readonly))
    lines.extend(f'  audit deny "{path}" w,' for path in sorted(ancestors))
    lines.append("}\n")
    profile = "\n".join(lines)
    if len(profile.encode()) > MAX_PROFILE_BYTES:
        raise PolicyError("Compiled private policy is too large")
    return profile


def require_root_directory(path: Path) -> None:
    # /run is a host-controlled tree. Never follow links below it.
    for parent in reversed((path, *path.parents)):
        if not parent.exists():
            parent.mkdir(mode=0o700)
        metadata = parent.lstat()
        if not stat.S_ISDIR(metadata.st_mode) or metadata.st_uid != 0 or metadata.st_mode & 0o022:
            raise PolicyError("Broker state directory is not root controlled")


def write_private(path: Path, data: str) -> None:
    fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        handle.write(data)
        handle.flush()
        os.fsync(handle.fileno())


def read_private(path: Path) -> dict:
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    with os.fdopen(fd, "r", encoding="utf-8") as handle:
        metadata = os.fstat(handle.fileno())
        if not stat.S_ISREG(metadata.st_mode) or metadata.st_uid != 0 or metadata.st_mode & 0o077:
            raise PolicyError("Broker state file is not root controlled")
        return json.load(handle)


def profile_is_loaded(name: str) -> bool:
    try:
        lines = Path("/sys/kernel/security/apparmor/profiles").read_text().splitlines()
    except OSError as error:
        raise PolicyError("AppArmor profile state is unavailable") from error
    return f"{name} (enforce)" in lines


def prepare(request: dict, uid: int, directory: Path) -> dict:
    policy = normalize_prepare(request)
    digest = definition_digest(policy)
    name = f"openmates-command.{uid}.{digest}"
    profile = render_profile(name, policy)
    profile_file = directory / f"{digest}.profile"
    record = directory / f"{digest}.json"
    if record.exists() and (read_private(record) != {"definition_digest": digest, "profile_name": name}
                            or profile_file.read_text() != profile):
        raise PolicyError("Cached immutable AppArmor policy differs")
    if not record.exists():
        if len(list(directory.glob("*.profile"))) >= MAX_PROFILES_PER_USER:
            raise PolicyError("AppArmor policy cache is full; administrator maintenance is required")
        # Add, never replace. A partially installed matching profile is safe to
        # reuse only after its immutable source has been checked byte for byte.
        if profile_file.exists():
            if profile_file.read_text() != profile:
                raise PolicyError("Existing immutable AppArmor policy differs")
        else:
            write_private(profile_file, profile)
        if not profile_is_loaded(name):
            result = subprocess.run(
                [PARSER, "--add", "--skip-cache", str(profile_file)],
                capture_output=True, timeout=20, env={"PATH": "/usr/sbin:/usr/bin:/sbin:/bin", "LC_ALL": "C"},
            )
            if result.returncode != 0:
                raise PolicyError("AppArmor rejected the generated command policy")
        write_private(record, json.dumps({"definition_digest": digest, "profile_name": name}))
    if not profile_is_loaded(name):
        raise PolicyError("Cached AppArmor policy is missing or not enforced; run administrator setup")
    if len(list(directory.glob("*.lease"))) >= MAX_LEASES_PER_USER:
        raise PolicyError("Too many unreleased AppArmor command leases")
    lease = secrets.token_hex(16)
    write_private(directory / f"{lease}.lease", json.dumps({"definition_digest": digest}))
    return {"profile_name": name, "lease_id": lease, "definition_digest": digest,
            "private_policy_digest": policy["private_policy_digest"]}


def release(request: dict, directory: Path) -> dict:
    require_keys(request, {"protocol_version", "action", "lease_id", "definition_digest"})
    lease, digest = request["lease_id"], request["definition_digest"]
    if (request["protocol_version"] != PROTOCOL_VERSION or request["action"] != "release"
            or not isinstance(lease, str) or not LEASE_ID.fullmatch(lease)
            or not isinstance(digest, str) or not HEX_DIGEST.fullmatch(digest)):
        raise PolicyError("Invalid release request")
    path = directory / f"{lease}.lease"
    if path.exists():
        if read_private(path)["definition_digest"] != digest:
            raise PolicyError("Command lease does not match this policy")
        path.unlink()
    # No parser remove/replace operation is available through this broker.
    return {"released": False, "retained": True, "definition_digest": digest}


def caller_uid() -> int:
    if os.geteuid() != 0:
        raise PolicyError("The installed policy broker requires its scoped sudo grant")
    value = os.environ.get("SUDO_UID")
    if not value or not re.fullmatch(r"[0-9]{1,10}", value):
        raise PolicyError("The broker must run through the configured sudo grant")
    uid = int(value)
    if uid <= 0:
        raise PolicyError("A non-root source user is required")
    return uid


def main() -> int:
    try:
        if len(sys.argv) != 1:
            raise PolicyError("Broker takes no command-line arguments")
        uid = caller_uid()
        raw = sys.stdin.buffer.read(MAX_REQUEST_BYTES + 1)
        if len(raw) > MAX_REQUEST_BYTES:
            raise PolicyError("Policy request is too large")
        request = json.loads(raw)
        if not isinstance(request, dict):
            raise PolicyError("Invalid policy request")
        directory = STATE_ROOT / str(uid)
        require_root_directory(directory)
        lock = os.open(directory / "lock", os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
        with os.fdopen(lock, "w") as handle:
            fcntl.flock(handle, fcntl.LOCK_EX)
            if request.get("action") == "prepare":
                response = prepare(request, uid, directory)
            elif request.get("action") == "release":
                response = release(request, directory)
            else:
                raise PolicyError("Unsupported broker action")
        print(json.dumps(response, separators=(",", ":")))
        return 0
    except (PolicyError, OSError, ValueError, subprocess.TimeoutExpired) as error:
        print(json.dumps({"error": "confinement_unavailable", "message": str(error)}))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
