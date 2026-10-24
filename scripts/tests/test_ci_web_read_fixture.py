# contract-test-file: tooling
"""Verify opt-in fixture TLS and isolation without starting product services."""
import ipaddress
import ssl
import subprocess

import pytest

from scripts.ci_environment import compose_profile, web_read_fixture_selected
from scripts.ci_web_read_fixture import ADDRESS, HOSTNAME, HTML, PARAGRAPHS, prepare_tls


def test_read_fixture_is_absent_from_default_profiles():
    profile = compose_profile("a" * 40)
    assert "web-read-origin" not in profile["services"]
    assert "SSL_CERT_FILE" not in profile["services"]["api"]["environment"]
    assert "web-read-fixture" not in profile.get("networks", {})


def test_read_fixture_uses_real_public_address_guards_without_external_egress():
    profile = compose_profile("a" * 40, web_read_fixture=True)
    assert ipaddress.ip_address(ADDRESS).is_global
    assert profile["networks"]["default"]["internal"] is True
    assert profile["networks"]["web-read-fixture"]["internal"] is True
    api = profile["services"]["api"]
    assert api["networks"] == ["default", "web-read-fixture"]
    assert api["extra_hosts"][HOSTNAME] == ADDRESS
    assert api["environment"]["SSL_CERT_FILE"] == "/ci-web-read/ca.pem"
    assert "HTTPS_PROXY" not in api["environment"]
    fixture = profile["services"]["web-read-origin"]
    assert fixture["networks"] == {"web-read-fixture": {"ipv4_address": ADDRESS}}
    assert fixture["ports"] == ["127.0.0.1:8443:443"]
    assert all("docker.sock" not in str(volume) for volume in fixture["volumes"])
    for name, service in profile["services"].items():
        if name not in {"api", "web-read-origin"}:
            assert "web-read-fixture" not in service.get("networks", [])
            assert "SSL_CERT_FILE" not in service.get("environment", {})


def test_fixture_leaf_has_verified_hostname_and_disposable_ca(tmp_path):
    prepare_tls(tmp_path)
    assert not (tmp_path / "ca.key").exists()
    assert (tmp_path / "server.key").stat().st_mode & 0o777 == 0o600
    context = ssl.create_default_context(cafile=str(tmp_path / "ca.pem"))
    assert context.check_hostname and context.verify_mode == ssl.CERT_REQUIRED
    result = subprocess.run(["openssl", "verify", "-CAfile", str(tmp_path / "ca.pem"),
                             "-verify_hostname", HOSTNAME, str(tmp_path / "server.crt")],
                            check=True, capture_output=True, text=True)
    assert "OK" in result.stdout
    assert len(HTML) > 30000 and len(PARAGRAPHS) == 240
    assert b"PUBLIC ARTICLE END 7f531b" in HTML


def test_fixture_refuses_public_proxy_and_mixed_runtime_batches():
    with pytest.raises(ValueError, match="provider proxy"):
        compose_profile("a" * 40, web_read_fixture=True, public_provider=True)
    assert web_read_fixture_selected(["web-read-public-page.spec.ts"]) is True
    assert web_read_fixture_selected(["provider-boundary.spec.ts"]) is False
    with pytest.raises(ValueError, match="standalone batch"):
        web_read_fixture_selected(["web-read-public-page.spec.ts", "provider-boundary.spec.ts"])
