# backend/tests/test_connected_account_setup.py
#
# Regression coverage for public connected-account setup metadata.
# Revolut Business requires a public server egress IP whitelist; this test keeps
# the endpoint from returning private/local addresses or user-specific data.
#
# Spec: docs/specs/finance-check-accounts-v1/spec.yml

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.core.api.app.routes import connected_account_setup


def _client() -> TestClient:
    app = FastAPI()
    app.include_router(connected_account_setup.router)
    return TestClient(app)


def test_revolut_server_egress_ip_uses_configured_public_ips(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(
        connected_account_setup.REVOLUT_BUSINESS_EGRESS_IP_ENV,
        "10.0.0.1,8.8.8.8;1.1.1.1,not-an-ip",
    )

    response = _client().get("/v1/connected-accounts/setup/revolut-business/server-egress-ip")

    assert response.status_code == 200
    payload = response.json()
    assert payload["provider_id"] == "revolut_business"
    assert payload["ip_addresses"] == ["1.1.1.1", "8.8.8.8"]
    assert payload["source"] == "configured"
    assert payload["revolut_field"] == "Production IP whitelist"


def test_revolut_server_egress_ip_detects_public_ip(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(connected_account_setup.REVOLUT_BUSINESS_EGRESS_IP_ENV, raising=False)

    async def fake_detect_public_egress_ip() -> str:
        return "8.8.4.4"

    monkeypatch.setattr(connected_account_setup, "_detect_public_egress_ip", fake_detect_public_egress_ip)

    response = _client().get("/v1/connected-accounts/setup/revolut-business/server-egress-ip")

    assert response.status_code == 200
    payload = response.json()
    assert payload["ip_addresses"] == ["8.8.4.4"]
    assert payload["source"] == "detected"


def test_parse_public_ip_list_rejects_private_and_reserved_addresses() -> None:
    assert connected_account_setup._parse_public_ip_list("127.0.0.1,192.168.0.3,172.16.0.1") == []
