"""Contracts for the daily running-image report: KEV findings, Node runtime gaps, incomplete coverage.

Scan results are built in memory; no docker, trivy or network is used.
"""

# contract-test-file: infrastructure
from __future__ import annotations

from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from security_monitoring import image_report, image_scan  # noqa: E402 - path set above
from security_monitoring.models import Asset  # noqa: E402

DIGEST = "sha256:" + "ab" * 32
NODE_INDEX = [{"version": "v22.21.0", "security": True}, {"version": "v22.22.0", "security": False},
              {"version": "v24.22.3", "security": True}]


def _results():
    finding = image_scan.Finding(package="libbrotli1", installed_version="1.1.0-2+b7", fixed_version="1.1.0-2+b8",
                                 vuln_id="CVE-2026-0042", severity="critical", pkg_path=None, image="example-api",
                                 environments=("dev",), pkg_type="debian")
    vendored = image_scan.Finding(package="brace-expansion", installed_version="2.0.1", fixed_version="2.0.2",
                                  vuln_id="CVE-2026-0043", severity="high", pkg_path="usr/local/lib/node_modules/npm/node_modules/brace-expansion/package.json",
                                  image="example-api", environments=("dev",), pkg_type="node-pkg")
    ok = image_scan.ScanResult("example-api", DIGEST, "dev", ("dev",), [finding, vendored])
    broken = image_scan.ScanResult("example-logs", "sha256:" + "cd" * 32, "dev", ("dev",), incomplete="trivy exit 1")
    return [ok, broken]


def _runtimes():
    node = Asset(kind="runtime", ecosystem="tool", name="node", version="22.20.0", environments=("dev",), exposure="internal", source_file=f"image:example-api@{DIGEST}")
    return [image_scan.RuntimeResult("example-api", DIGEST, ("dev",), [node]),
            image_scan.RuntimeResult("example-logs", "sha256:" + "cd" * 32, ("dev",), incomplete="no sh in image (exit 127)")]


# Spec coverage: security-monitoring.images.running-digests
# contract-test: infrastructure
def test_kev_finding_is_urgent_old_node_is_fix_soon_and_gaps_stay_incomplete():
    summary, incidents = image_report.build_report([object(), object()], ["core: no image digests reported"], _results(), _runtimes(),
                                                   {"CVE-2026-0042"}, NODE_INDEX)
    urgent = [v for v in incidents.values() if v["outcome"] == "urgent"]
    assert len(urgent) == 1 and "CISA KEV" in urgent[0]["details"]["evidence_summary"]
    node = [v for v in incidents.values() if v["outcome"] == "affected_fix_soon"]
    # 22.21.0 is the newest security release on the 22 line; 22.22.0 is not a security release.
    assert len(node) == 1 and "22.21.0" in node[0]["details"]["evidence_summary"]
    assert summary["lines"] == [f"example-api@{'ab' * 6} (dev): 1 critical, 1 high, 2 of them fixable"]
    incomplete = "\n".join(summary["incomplete"])
    assert "core: no image digests reported" in incomplete and "example-logs: trivy exit 1" in incomplete and "no sh in image" in incomplete


# Spec coverage: security-monitoring.images.running-digests
# contract-test: infrastructure
def test_node_gap_only_for_newer_security_release_on_same_major():
    assert image_report.node_security_gap("22.20.0", NODE_INDEX) == "22.21.0"
    assert image_report.node_security_gap("22.21.0", NODE_INDEX) is None
    assert image_report.node_security_gap("24.22.3", NODE_INDEX) is None
