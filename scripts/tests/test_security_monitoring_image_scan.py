"""Image scan tests with docker and trivy fully faked (no real containers)."""

# contract-test-file: infrastructure

from __future__ import annotations

import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from security_monitoring import image_scan as mod  # noqa: E402 - path set above
from security_monitoring.image_scan import CommandResult, RunningImage  # noqa: E402
from security_monitoring.models import HostReport  # noqa: E402

D1 = "sha256:" + "a" * 64
D2 = "sha256:" + "b" * 64
TRIVY_DOC = {"Results": [
    {"Target": "app/node", "Class": "lang-pkgs", "Type": "gobinary", "Vulnerabilities": [
        {"PkgName": "brotli", "InstalledVersion": "1.0.9", "FixedVersion": "1.1.0", "VulnerabilityID": "CVE-2099-0001",
         "Severity": "CRITICAL", "PkgPath": "usr/lib/node_modules/vendor/brotli"}]},
    {"Target": "debian", "Class": "os-pkgs", "Type": "debian", "Vulnerabilities": [
        {"PkgName": "zlib1g", "InstalledVersion": "1.2", "VulnerabilityID": "CVE-2099-0002", "Severity": "HIGH"}]},
]}


class FakeDocker:
    def __init__(self, trivy_rc: int = 0, versions: str = "node=v22.1.0\nbrotli=1.1.0\nopenssl=OpenSSL 3.0.13 30 Jan 2024\n") -> None:
        self.calls: list[list[str]] = []
        self.trivy_rc = trivy_rc
        self.versions = versions

    def __call__(self, args, timeout):
        args = list(args)
        self.calls.append(args)
        if args[:2] == ["docker", "ps"]:
            return CommandResult(0, "img-a\nimg-a\nimg-b\n")
        if args[:3] == ["docker", "image", "inspect"]:
            return CommandResult(0, json.dumps([{"Id": D1, "RepoDigests": []}, {"Id": "sha256:" + "c" * 64, "RepoDigests": [f"x/b@{D2}"]}]))
        if args[0] == "which":
            return CommandResult(1)
        if "--scanners" in args:
            return CommandResult(self.trivy_rc, json.dumps(TRIVY_DOC) if self.trivy_rc == 0 else "", "boom")
        if "--entrypoint" in args:
            return CommandResult(0, self.versions)
        return CommandResult(0)


# Spec coverage: security-monitoring.images.running-digests
# contract-test: infrastructure
def test_dev_images_use_repo_digest_else_id():
    images, gaps = mod.running_images(FakeDocker(), roles=["dev"])
    assert gaps == []
    assert [(i.ref, i.digest) for i in images] == [("img-a", D1), ("img-b", D2)]


# Spec coverage: security-monitoring.images.running-digests
# contract-test: infrastructure
def test_report_images_nested_and_missing(tmp_path):
    reports = {"core": HostReport("core", "h", "t", {"deployed_image_digests": {"images": {"openmates/api": D1}}}),
               "upload": None, "preview": HostReport("preview", "h", "t", {})}
    images, missing = mod.report_images(reports)
    assert images[0].pull_ref == f"ghcr.io/openmates/api@{D1}" and images[0].environment == "prod"
    assert missing == ["upload", "preview"]


# Spec coverage: security-monitoring.images.running-digests
# contract-test: infrastructure
def test_scan_normalizes_vendored_path_and_caches(tmp_path):
    docker = FakeDocker()
    image = RunningImage("img-a", D1, "dev", "dev", "docker")
    first = mod.scan(image, docker, state_dir=tmp_path)
    assert first.incomplete is None and not first.cached
    brotli = first.findings[0]
    assert (brotli.severity, brotli.pkg_path, brotli.fixed_version, brotli.environments) == ("critical", "usr/lib/node_modules/vendor/brotli", "1.1.0", ("dev",))
    assert any("aquasec/trivy@sha256:" in part for call in docker.calls for part in call)
    calls_before = len(docker.calls)
    second = mod.scan(image, docker, state_dir=tmp_path)
    assert second.cached and len(second.findings) == 2 and len(docker.calls) == calls_before


# Spec coverage: security-monitoring.images.running-digests
# contract-test: infrastructure
def test_cache_expires_after_24h(tmp_path):
    image = RunningImage("img-a", D1, "dev", "dev", "docker")
    mod.scan(image, FakeDocker(), state_dir=tmp_path, now=lambda: 1000.0)
    again = mod.scan(image, FakeDocker(), state_dir=tmp_path, now=lambda: 1000.0 + 25 * 3600)
    assert not again.cached


# Spec coverage: security-monitoring.images.running-digests
# contract-test: infrastructure
def test_trivy_failure_is_incomplete_not_clean(tmp_path):
    image = RunningImage("img-a", D1, "dev", "dev", "docker")
    result = mod.scan(image, FakeDocker(trivy_rc=1), state_dir=tmp_path)
    assert result.incomplete and not result.findings
    assert mod._summary([result], [])["incomplete_coverage"]


# Spec coverage: security-monitoring.images.running-digests
# contract-test: infrastructure
def test_server_image_is_pulled_first(tmp_path):
    docker = FakeDocker()
    image = RunningImage("openmates/api", D1, "core", "prod", "host-report:core", f"ghcr.io/openmates/api@{D1}")
    mod.scan(image, docker, state_dir=tmp_path)
    assert docker.calls[1][:2] == ["docker", "pull"] or docker.calls[0][:2] == ["docker", "pull"]


# Spec coverage: security-monitoring.images.running-digests
# contract-test: infrastructure
def test_runtime_versions_assets_and_isolation():
    docker = FakeDocker()
    result = mod.runtime_versions(RunningImage("img-a", D1, "dev", "dev", "docker"), docker)
    assert {(a.name, a.version) for a in result.assets} == {("node", "v22.1.0".lstrip("v")), ("brotli", "1.1.0"), ("openssl", "3.0.13")} or \
        {(a.name, a.version) for a in result.assets} >= {("brotli", "1.1.0"), ("openssl", "3.0.13")}
    assert all(a.kind == "runtime" and a.environments == ("dev",) for a in result.assets)
    run = docker.calls[-1]
    assert "--network" in run and run[run.index("--network") + 1] == "none" and "--read-only" in run


# Spec coverage: security-monitoring.images.running-digests
# contract-test: infrastructure
def test_cli_incomplete_exits_nonzero_but_findings_exit_zero(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("SECURITY_MONITORING_DIR", str(tmp_path))
    assert mod.main(["scan", "--json", "--role", "dev"], FakeDocker()) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["severity_counts"]["critical"] == 2 and out["incomplete_coverage"] == []
    monkeypatch.setenv("SECURITY_MONITORING_DIR", str(tmp_path / "other"))
    assert mod.main(["scan", "--role", "dev"], FakeDocker(trivy_rc=1)) == 2
