#!/usr/bin/env python3
"""Deterministic rendering contracts for security operator email reports."""

# contract-test-file: infrastructure

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
MODULE_PATH = ROOT / "scripts" / "security_digest.py"
FIXTURES = Path(__file__).with_name("fixtures") / "security-reporting"


def load_module():
    spec = importlib.util.spec_from_file_location("security_digest", MODULE_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def report(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


# contract-test: infrastructure
def test_renderer_returns_complete_escaped_bounded_operator_content():
    digest = load_module()
    data = report("digest-findings.json")
    data["open"] *= 4

    rendered = digest.render_security_report(data, detail_limit=2)

    assert rendered["subject"] == "[Security] development digest: 1 new, 4 open"
    assert "2026-09-05T08:30:00Z to 2026-09-06T08:30:00Z (UTC)" in rendered["text"]
    assert "Open: critical 0, high 4, medium 0, low 0, unknown 0 (4 total)" in rendered["text"]
    assert "3 additional open findings omitted" in rendered["text"]
    assert "coverage incomplete" in rendered["text"]
    assert "security_audit: unavailable" in rendered["text"]
    assert "&lt;unsafe-package&gt;" in rendered["html"]
    assert "javascript:alert" not in rendered["html"]
    assert "javascript:alert" not in rendered["text"]
    assert "raw agent" not in rendered["html"].lower()


# contract-test: infrastructure
def test_renderer_reports_clean_days_and_only_allowlisted_https_advisories():
    digest = load_module()
    rendered = digest.render_security_report(report("digest-clean.json"))

    assert "0 new, 0 open" in rendered["subject"]
    assert "No new findings were recorded in this window." in rendered["text"]
    assert digest.safe_advisory_link("GHSA-demo-0001") == "https://github.com/advisories/GHSA-demo-0001"
    assert digest.safe_advisory_link("CVE-2026-0002") == "https://nvd.nist.gov/vuln/detail/CVE-2026-0002"
    assert digest.safe_advisory_link("https://untrusted.example/advisory") is None
