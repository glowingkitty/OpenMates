"""Contracts for signed, encrypted host reports and deterministic SSH intrusion signals.

Keys and certificates are generated per test session with ssh-keygen and openssl
in temporary directories; nothing listens on a socket and no real network
address is used (documentation ranges and placeholder ULA addresses only).
"""

# contract-test-file: infrastructure
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import importlib.machinery
import importlib.util
import json
from pathlib import Path
import shutil
import subprocess
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from security_monitoring import host_collector as collector
from security_monitoring import host_reports
from security_monitoring.models import HOST_REPORT_FIELDS, HostReport

REPO_ROOT = Path(__file__).resolve().parents[2]
REPORTER_PATH = REPO_ROOT / "deployment" / "host_reporter" / "openmates-host-reporter"
DOC_SOURCE_ADDRESS = "198.51.100.23"
UNKNOWN_FP = "SHA256:unknownunknownunknownunknownunknownunknown00"
KNOWN_FP = "SHA256:knownknownknownknownknownknownknownknown0000"

pytestmark = pytest.mark.skipif(
    not (shutil.which("ssh-keygen") and shutil.which("openssl")), reason="ssh-keygen and openssl are required"
)


def _load_reporter():
    loader = importlib.machinery.SourceFileLoader("openmates_host_reporter", str(REPORTER_PATH))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


reporter = _load_reporter()


def _host_key(directory: Path, name: str) -> Path:
    key = directory / name
    subprocess.run(["ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-C", name, "-f", str(key)], check=True)
    return key


def _contents(**overrides) -> dict:
    contents = {name: {} for name in HOST_REPORT_FIELDS}
    contents.update(
        os_release={"id": "ubuntu", "version_id": "24.04", "codename": "noble"},
        running_kernel="6.8.0-100-generic",
        package_versions={"openssh-server": {"version": "1:9.6p1-3ubuntu13.5", "source": "openssh", "source_version": "1:9.6p1-3ubuntu13.5"}},
        successful_ssh_logins=[],
    )
    contents.update(overrides)
    return contents


@pytest.fixture(scope="module")
def collector_material(tmp_path_factory):
    """One collector recipient key/cert and TLS cert for the module (RSA keygen is slow)."""
    state = tmp_path_factory.mktemp("collector-state")
    paths = collector.CollectorPaths(state)
    collector.init_collector(paths, "fd00::10")
    return paths


@pytest.fixture
def paths(collector_material, tmp_path) -> collector.CollectorPaths:
    state = tmp_path / "state"
    (state / "collector").mkdir(parents=True)
    for name in ("collector.key", "collector.crt", "tls.key", "tls.crt"):
        shutil.copy2(collector_material.collector_dir / name, state / "collector" / name)
    return collector.CollectorPaths(state)


def _sealed(paths, key: Path, role: str = "core", contents: dict | None = None, generated_at: str | None = None) -> bytes:
    report = reporter.build_report(role, reporter.key_fingerprint(key), contents or _contents(), generated_at)
    return reporter.seal(report, key, paths.cert)


# Host report coverage: security-monitoring.host-reports.private-push
# contract-test: infrastructure
def test_signed_encrypted_report_is_accepted_and_stored_privately(paths, tmp_path) -> None:
    key = _host_key(tmp_path, "core-key")
    collector.register_host(paths, "core", key.with_suffix(".pub").read_text())
    body = _sealed(paths, key)

    accepted = collector.accept_report(body, paths)

    latest = paths.hosts_dir / "core" / "latest.json"
    assert accepted["host_role"] == "core"
    assert latest.stat().st_mode & 0o777 == 0o600
    stored = json.loads(latest.read_text())
    assert set(stored["contents"]) == set(HOST_REPORT_FIELDS)
    loaded = host_reports.load_latest(paths.hosts_dir)
    assert loaded["core"] is not None and loaded["upload"] is None
    assert host_reports.ssh_context(loaded["core"])["package_versions"]["openssh-server"] == "1:9.6p1-3ubuntu13.5"
    assert b"BEGIN" not in body  # the signature is inside the CMS envelope, not readable on the wire

    collector.accept_report(_sealed(paths, key), paths)
    assert (paths.hosts_dir / "core" / "previous.json").exists()


# Host report coverage: security-monitoring.host-reports.private-push
# contract-test: infrastructure
def test_report_from_unknown_signer_is_rejected_and_counted(paths, tmp_path) -> None:
    registered = _host_key(tmp_path, "registered")
    stranger = _host_key(tmp_path, "stranger")
    collector.register_host(paths, "core", registered.with_suffix(".pub").read_text())

    with pytest.raises(collector.Rejection) as rejected:
        collector.accept_report(_sealed(paths, stranger), paths)

    assert rejected.value.reason == "unknown_signer"
    assert not (paths.hosts_dir / "core" / "latest.json").exists()
    assert collector.rejection_summary(paths)["counts"] == {"unknown_signer": 1}


# Host report coverage: security-monitoring.host-reports.private-push
# contract-test: infrastructure
def test_report_signed_by_another_role_is_rejected(paths, tmp_path) -> None:
    key = _host_key(tmp_path, "upload-key")
    collector.register_host(paths, "upload", key.with_suffix(".pub").read_text())

    with pytest.raises(collector.Rejection) as rejected:
        collector.accept_report(_sealed(paths, key, role="core"), paths)

    assert rejected.value.reason == "role_mismatch"


# Host report coverage: security-monitoring.host-reports.private-push
# contract-test: infrastructure
def test_report_with_field_outside_allowlist_is_rejected(paths, tmp_path) -> None:
    key = _host_key(tmp_path, "core-key")
    collector.register_host(paths, "core", key.with_suffix(".pub").read_text())
    contents = _contents(environment_variables={"SECRET": "<placeholder>"})

    with pytest.raises(collector.Rejection) as rejected:
        collector.accept_report(_sealed(paths, key, contents=contents), paths)

    assert rejected.value.reason == "field_not_allowlisted"
    assert not (paths.hosts_dir / "core").exists()


# Host report coverage: security-monitoring.host-reports.private-push
# contract-test: infrastructure
def test_replayed_and_stale_reports_are_rejected(paths, tmp_path) -> None:
    key = _host_key(tmp_path, "core-key")
    collector.register_host(paths, "core", key.with_suffix(".pub").read_text())
    body = _sealed(paths, key)
    collector.accept_report(body, paths)

    with pytest.raises(collector.Rejection) as replayed:
        collector.accept_report(body, paths)
    assert replayed.value.reason == "replayed"

    old = (datetime.now(timezone.utc) - timedelta(hours=49)).strftime("%Y-%m-%dT%H:%M:%SZ")
    with pytest.raises(collector.Rejection) as stale:
        collector.accept_report(_sealed(paths, key, generated_at=old), paths)
    assert stale.value.reason == "stale"


# Host report coverage: security-monitoring.host-reports.private-push
# contract-test: infrastructure
def test_role_without_report_for_37_hours_is_stale() -> None:
    now = datetime(2026, 11, 4, 12, 0, tzinfo=timezone.utc)
    reports = {
        "core": HostReport("core", "SHA256:core", "2026-11-02T23:00:00Z", _contents()),
        "upload": HostReport("upload", "SHA256:upload", "2026-11-04T06:00:00Z", _contents()),
        "preview": None,
    }

    assert host_reports.stale_roles(reports, now) == ["core", "preview"]


# Host report coverage: security-monitoring.host-reports.private-push
# contract-test: infrastructure
def test_collector_refuses_public_loopback_and_unspecified_binds(tmp_path, monkeypatch) -> None:
    for unsafe in ("0.0.0.0:18000", "[::]:18000", "127.0.0.1:18000", f"{DOC_SOURCE_ADDRESS}:18000", "192.0.2.10:18000"):
        with pytest.raises(collector.CollectorConfigError):
            collector.parse_bind(unsafe)
    assert collector.parse_bind("[fd00::10]:18000") == ("fd00::10", 18000)

    monkeypatch.delenv(collector.BIND_ENV, raising=False)
    with pytest.raises(collector.CollectorConfigError, match="not configured"):
        collector.configured_bind(collector.CollectorPaths(tmp_path / "state"), tmp_path)
    with pytest.raises(reporter.ReporterError):
        reporter.validate_collector_url("http://[fd00::10]:18000/v1/host-report")


# SSH intrusion coverage: security-monitoring.ssh.vulnerability-and-intrusion
# contract-test: infrastructure
def test_unknown_key_login_and_new_authorized_key_raise_address_free_signals() -> None:
    authorized = {
        "root": {
            "files": {"/root/.ssh/authorized_keys": "b" * 64},
            "keys": [
                {"fingerprint": KNOWN_FP, "type": "ED25519", "file": "/root/.ssh/authorized_keys"},
                {"fingerprint": UNKNOWN_FP, "type": "ED25519", "file": "/root/.ssh/authorized_keys"},
            ],
        }
    }
    login = {"timestamp": "2026-11-04T10:00:00Z", "user": "root", "method": "publickey", "key_type": "ED25519",
             "fingerprint": UNKNOWN_FP, "source_address": DOC_SOURCE_ADDRESS}
    previous = HostReport("upload", "SHA256:upload", "2026-11-03T10:00:00Z", _contents(ssh_config_checksums={"/etc/ssh/sshd_config": "a" * 64}))
    current = HostReport("upload", "SHA256:upload", "2026-11-04T10:00:00Z", _contents(
        authorized_key_fingerprints=authorized,
        successful_ssh_logins=[login, dict(login, timestamp="2026-11-04T11:00:00Z")],
        ssh_config_checksums={"/etc/ssh/sshd_config": "c" * 64},
    ))

    signals = host_reports.intrusion_signals(previous, current, {"upload": {KNOWN_FP}})

    kinds = sorted(signal["kind"] for signal in signals)
    assert kinds == ["new_authorized_key", "ssh_config_changed", "unknown_key_login"]
    assert all(DOC_SOURCE_ADDRESS not in signal["safe_detail"] for signal in signals)
    assert all(DOC_SOURCE_ADDRESS not in json.dumps(signal) for signal in signals)
    assert any(UNKNOWN_FP in s["safe_detail"] and "/root/.ssh/authorized_keys" in s["safe_detail"] for s in signals)
    again = host_reports.intrusion_signals(previous, current, {"upload": {KNOWN_FP}})
    assert [s["change_id"] for s in again] == [s["change_id"] for s in signals]
    assert host_reports.intrusion_signals(previous, current, {"upload": {KNOWN_FP, UNKNOWN_FP}})[0]["kind"] == "ssh_config_changed"


# SSH intrusion coverage: security-monitoring.ssh.vulnerability-and-intrusion
# contract-test: infrastructure
def test_new_account_sudoers_and_modified_package_file_signal_once(tmp_path) -> None:
    accounts = {"accounts": [{"name": "root", "uid": 0, "shell": "/bin/bash"}], "privileged_groups": {"sudo": []},
                "sudoers_checksums": {"/etc/sudoers": "a" * 64}}
    changed = {"accounts": accounts["accounts"] + [{"name": "intruder", "uid": 1001, "shell": "/bin/bash"}],
               "privileged_groups": {"sudo": ["intruder"]}, "sudoers_checksums": {"/etc/sudoers": "a" * 64, "/etc/sudoers.d/x": "d" * 64}}
    integrity = {"tool": "dpkg-verify", "changed_paths": ["/usr/sbin/sshd"], "missing_paths": []}
    previous = HostReport("core", "SHA256:core", "2026-11-03T10:00:00Z", _contents(local_accounts_and_sudoers=accounts))
    current = HostReport("core", "SHA256:core", "2026-11-04T10:00:00Z", _contents(local_accounts_and_sudoers=changed, package_file_integrity=integrity))

    signals = host_reports.intrusion_signals(previous, current, {"core": set()})
    details = sorted(signal["safe_detail"] for signal in signals)

    assert details == ["account intruder uid=1001", "added /etc/sudoers.d/x", "group sudo member intruder", "modified /usr/sbin/sshd"]
    assert host_reports.intrusion_signals(current, current, {"core": set()}) == []

    expected_path = tmp_path / "expected_ssh.json"
    _, seeded = host_reports.seed_expected_keys(expected_path, current)
    assert [signal["kind"] for signal in seeded] == ["baseline_seeded"]
    assert host_reports.seed_expected_keys(expected_path, current)[1] == []


# Content boundary coverage: security-monitoring.content.boundary
# contract-test: infrastructure
def test_reporter_parsers_keep_only_allowlisted_safe_fields() -> None:
    journal = json.dumps({
        "__REALTIME_TIMESTAMP": "1793700000000000",
        "MESSAGE": f"Accepted publickey for root from {DOC_SOURCE_ADDRESS} port 50022 ssh2: ED25519 {UNKNOWN_FP}",
    })
    logins = reporter.parse_logins([journal, json.dumps({"MESSAGE": "Failed password for root"})])
    assert logins == [{"timestamp": "2026-11-03T10:00:00Z", "user": "root", "method": "publickey", "key_type": "ED25519",
                       "fingerprint": UNKNOWN_FP, "source_address": DOC_SOURCE_ADDRESS}]

    ports = reporter.parse_listening(
        'LISTEN 0 4096 0.0.0.0:22 0.0.0.0:* users:(("sshd",pid=1,fd=3))\n'
        f"LISTEN 0 4096 {DOC_SOURCE_ADDRESS}:5432 0.0.0.0:*\n"
        "LISTEN 0 4096 [::1]:6379 [::]:*\n"
    )
    assert ports == [
        {"port": 22, "address_class": "any", "processes": ["sshd"]},
        {"port": 5432, "address_class": "specific", "processes": []},
        {"port": 6379, "address_class": "loopback", "processes": []},
    ]
    assert DOC_SOURCE_ADDRESS not in json.dumps(ports)
    keys = reporter.parse_fingerprints(f"256 {UNKNOWN_FP} operator@example.com (ED25519)\n")
    assert keys == [{"fingerprint": UNKNOWN_FP, "type": "ED25519"}]
    updates = reporter.parse_apt_simulation(
        "Inst openssh-server [1:9.6p1-3ubuntu13.5] (1:9.6p1-3ubuntu13.6 Ubuntu:24.04/noble-updates, Ubuntu:24.04/noble-security [amd64])\n"
        "Inst tzdata [2024a-1] (2024b-1 Ubuntu:24.04/noble-updates [all])\n"
    )
    assert [u["package"] for u in updates] == ["openssh-server"]
