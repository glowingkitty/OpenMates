"""Accepted host reports: loading, staleness, SSH context and intrusion signals.

Reads what scripts/security_monitoring/host_collector.py stored under
logs/security-monitoring/hosts/<role>/{latest,previous}.json. Intrusion signals
are deterministic and never wait for AI triage. Each signal carries a stable
`change_id` so the notifier alerts once per change, and a `safe_detail` that
names only fingerprints, file paths or usernames, never login source addresses.

Contract: specifications/architecture/security-monitoring
(host-reports.private-push, ssh.vulnerability-and-intrusion, content.boundary).
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import sys
from typing import Any

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from security_monitoring.models import HOST_ROLES, HostReport

DEFAULT_MAX_AGE = timedelta(hours=36)
SIGNAL_KINDS: tuple[str, ...] = (
    "unknown_key_login",
    "new_authorized_key",
    "ssh_config_changed",
    "new_account_or_sudoers",
    "package_file_modified",
    "baseline_seeded",
)
SSH_LIBRARIES: tuple[str, ...] = ("openssh-server", "openssh-client", "openssh-sftp-server", "libssl3t64", "libssl3", "zlib1g", "libc6")


def _parse_time(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def report_from_record(record: Mapping[str, Any]) -> HostReport:
    return HostReport(
        host_role=str(record["host_role"]),
        host_id=str(record["host_id"]),
        generated_at=str(record["generated_at"]),
        contents=dict(record["contents"]),
    )


def _load(path: Path) -> HostReport | None:
    if not path.exists():
        return None
    return report_from_record(json.loads(path.read_text(encoding="utf-8")))


def load_latest(directory: Path) -> dict[str, HostReport | None]:
    """Latest accepted report per role (None when a role never reported)."""
    return {role: _load(directory / role / "latest.json") for role in HOST_ROLES}


def load_previous(directory: Path) -> dict[str, HostReport | None]:
    return {role: _load(directory / role / "previous.json") for role in HOST_ROLES}


def stale_roles(
    reports: Mapping[str, HostReport | None],
    now: datetime,
    max_age: timedelta = DEFAULT_MAX_AGE,
) -> list[str]:
    """Roles without an accepted report younger than `max_age` (default 36h)."""
    stale = []
    for role in HOST_ROLES:
        report = reports.get(role)
        if report is None or now - _parse_time(report.generated_at) > max_age:
            stale.append(role)
    return stale


def package_version(report: HostReport, name: str) -> str | None:
    """Installed binary package version; accepts the reporter's {version, source, ...} shape."""
    packages = report.contents.get("package_versions")
    if not isinstance(packages, dict) or "error" in packages:
        return None
    entry = packages.get(name)
    if isinstance(entry, dict):
        return entry.get("version")
    return entry if isinstance(entry, str) else None


def ssh_context(report: HostReport) -> dict[str, Any]:
    """Exact OpenSSH (and linked library) versions plus effective sshd settings for triage."""
    settings = report.contents.get("sshd_effective_settings")
    return {
        "host_role": report.host_role,
        "generated_at": report.generated_at,
        "running_kernel": report.contents.get("running_kernel"),
        "package_versions": {name: version for name in SSH_LIBRARIES if (version := package_version(report, name))},
        "sshd_effective_settings": settings if isinstance(settings, dict) else {"error": "unavailable"},
    }


def _change_id(role: str, kind: str, detail: str) -> str:
    return hashlib.sha256(f"{role}\x00{kind}\x00{detail}".encode()).hexdigest()


def _signal(role: str, kind: str, safe_detail: str, identity: str | None = None) -> dict[str, str]:
    return {"role": role, "kind": kind, "change_id": _change_id(role, kind, identity or safe_detail), "safe_detail": safe_detail}


def authorized_fingerprints(report: HostReport) -> dict[str, set[str]]:
    """username -> authorized key fingerprints."""
    users = report.contents.get("authorized_key_fingerprints")
    if not isinstance(users, dict) or "error" in users:
        return {}
    return {user: {key["fingerprint"] for key in data.get("keys", []) if key.get("fingerprint")} for user, data in users.items()}


def _key_file(report: HostReport, user: str, fp: str) -> str:
    users = report.contents.get("authorized_key_fingerprints", {})
    for key in users.get(user, {}).get("keys", []):
        if key.get("fingerprint") == fp:
            return str(key.get("file", ""))
    return ""


def _login_signals(role: str, current: HostReport, expected: set[str]) -> list[dict[str, str]]:
    logins = current.contents.get("successful_ssh_logins")
    if not isinstance(logins, list):
        return []
    signals: dict[str, dict[str, str]] = {}
    for login in logins:
        user = str(login.get("user", ""))
        fp = str(login.get("fingerprint", ""))
        if fp and fp in expected:
            continue
        credential = fp or f"{login.get('method', 'unknown')}-auth"
        # Only user and credential identity; the login source address is deliberately excluded.
        detail = f"user={user} credential={credential}"
        signals[detail] = _signal(role, "unknown_key_login", detail)
    return list(signals.values())


def _diff_checksums(role: str, kind: str, before: Any, after: Any) -> list[dict[str, str]]:
    if not isinstance(before, dict) or not isinstance(after, dict) or "error" in before or "error" in after:
        return []
    signals = []
    for path in sorted(set(before) | set(after)):
        if before.get(path) != after.get(path):
            state = "removed" if path not in after else "added" if path not in before else "changed"
            signals.append(_signal(role, kind, f"{state} {path}", f"{path}\x00{after.get(path, 'removed')}"))
    return signals


def _account_signals(role: str, previous: HostReport, current: HostReport) -> list[dict[str, str]]:
    before = previous.contents.get("local_accounts_and_sudoers")
    after = current.contents.get("local_accounts_and_sudoers")
    if not isinstance(before, dict) or not isinstance(after, dict) or "error" in before or "error" in after:
        return []
    signals = []
    known = {(a["name"], a["uid"]) for a in before.get("accounts", [])}
    for account in after.get("accounts", []):
        if (account["name"], account["uid"]) not in known:
            signals.append(_signal(role, "new_account_or_sudoers", f"account {account['name']} uid={account['uid']}"))
    old_groups = before.get("privileged_groups", {})
    for group, members in sorted(after.get("privileged_groups", {}).items()):
        for member in sorted(set(members) - set(old_groups.get(group, []))):
            signals.append(_signal(role, "new_account_or_sudoers", f"group {group} member {member}"))
    signals.extend(_diff_checksums(role, "new_account_or_sudoers", before.get("sudoers_checksums"), after.get("sudoers_checksums")))
    return signals


def _integrity_signals(role: str, previous: HostReport | None, current: HostReport) -> list[dict[str, str]]:
    after = current.contents.get("package_file_integrity")
    if not isinstance(after, dict) or "error" in after:
        return []
    before = previous.contents.get("package_file_integrity") if previous else None
    known: set[str] = set()
    if isinstance(before, dict) and "error" not in before:
        known = set(before.get("changed_paths", [])) | set(before.get("missing_paths", []))
    signals = []
    for label, key in (("modified", "changed_paths"), ("missing", "missing_paths")):
        for path in sorted(set(after.get(key, [])) - known):
            signals.append(_signal(role, "package_file_modified", f"{label} {path}"))
    return signals


def intrusion_signals(
    previous: HostReport | None,
    current: HostReport,
    expected_key_fingerprints: Mapping[str, set[str]],
) -> list[dict[str, str]]:
    """Deterministic SSH and host intrusion signals for one role.

    Login and authorized-key checks compare against the operator's expected
    fingerprints; configuration, account, sudoers and integrity checks compare
    against the previous accepted report (no previous report = baseline only,
    except package-file modifications, which are always reported once).
    """
    role = current.host_role
    expected = set(expected_key_fingerprints.get(role, set()))
    signals = _login_signals(role, current, expected)
    for user, fingerprints in sorted(authorized_fingerprints(current).items()):
        for fp in sorted(fingerprints - expected):
            path = _key_file(current, user, fp)
            signals.append(_signal(role, "new_authorized_key", f"user={user} fingerprint={fp} file={path}", f"{user}\x00{fp}"))
    if previous is not None:
        signals.extend(_diff_checksums(role, "ssh_config_changed", previous.contents.get("ssh_config_checksums"), current.contents.get("ssh_config_checksums")))
        signals.extend(_account_signals(role, previous, current))
    signals.extend(_integrity_signals(role, previous, current))
    return signals


def load_expected_keys(path: Path) -> dict[str, set[str]]:
    if not path.exists():
        return {}
    data = json.loads(path.read_text(encoding="utf-8"))
    return {role: set(values) for role, values in data.items() if role in HOST_ROLES}


def seed_expected_keys(path: Path, current: HostReport) -> tuple[dict[str, set[str]], list[dict[str, str]]]:
    """Seed the expected-key list for a role from its first accepted report.

    Returns the expected mapping and, when seeding happened, one `baseline_seeded`
    signal (stable change_id, so the operator is informed exactly once).
    """
    expected = load_expected_keys(path)
    role = current.host_role
    if role in expected:
        return expected, []
    seeded = set().union(*authorized_fingerprints(current).values()) if authorized_fingerprints(current) else set()
    expected[role] = seeded
    payload = {name: sorted(values) for name, values in sorted(expected.items())}
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.tmp")
    tmp.write_text(json.dumps(payload, indent=1) + "\n", encoding="utf-8")
    tmp.chmod(0o600)
    tmp.replace(path)
    detail = f"expected SSH keys seeded from first report ({len(seeded)} keys)"
    return expected, [_signal(role, "baseline_seeded", detail, "baseline")]


def evaluate_hosts(hosts_dir: Path, expected_path: Path) -> list[dict[str, str]]:
    """All current intrusion signals across roles, seeding expected keys where absent."""
    latest = load_latest(hosts_dir)
    previous = load_previous(hosts_dir)
    signals: list[dict[str, str]] = []
    for role in HOST_ROLES:
        current = latest[role]
        if current is None:
            continue
        expected, seeded = seed_expected_keys(expected_path, current)
        signals.extend(seeded)
        signals.extend(intrusion_signals(previous[role], current, expected))
    return signals
