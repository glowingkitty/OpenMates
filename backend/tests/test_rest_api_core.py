# backend/tests/test_rest_api_core.py
#
# Integration tests for core REST API endpoints:
#   - Health check (/v1/health)
#   - Server info (/v1/server)
#   - App metadata (/v1/apps/*)
#   - API key management (/v1/settings/api-keys)
#   - Billing overview (/v1/settings/billing)
#   - Usage summaries, details, and export (/v1/settings/usage/*)
#   - Invalid API key (401)
#
# Execution:
#   /OpenMates/.venv/bin/python3 -m pytest -s backend/tests/test_rest_api_core.py

import httpx
import pytest

from backend.tests.conftest import API_BASE_URL, log_response


@pytest.mark.integration
def test_health_endpoint():
    """Test the public health endpoint (v1)."""
    with httpx.Client(
        base_url=API_BASE_URL, event_hooks={"response": [log_response]}
    ) as client:
        response = client.get("/v1/health")
        assert response.status_code == 200, f"Health check failed: {response.text}"
        data = response.json()
        assert "status" in data
        assert data["status"] in ["healthy", "degraded", "unhealthy"]
        assert "providers" in data
        assert "apps" in data


@pytest.mark.integration
def test_server_info_endpoint():
    """Test the public server info endpoint (v1)."""
    with httpx.Client(
        base_url=API_BASE_URL, event_hooks={"response": [log_response]}
    ) as client:
        response = client.get("/v1/server")
        assert response.status_code == 200, f"Server info failed: {response.text}"
        data = response.json()
        assert "domain" in data
        assert "self_hosted" in data
        assert "edition" in data
        assert "dev.openmates.org" in data["domain"]


@pytest.mark.integration
def test_apps_metadata_authenticated(api_client):
    """Test the apps metadata endpoint with authentication."""
    response = api_client.get("/v1/apps/metadata")
    assert response.status_code == 200, f"Apps metadata failed: {response.text}"
    data = response.json()
    if isinstance(data, dict) and "apps" in data:
        apps = data["apps"]
        assert "ai" in apps
        assert "web" in apps
    else:
        assert isinstance(data, list)
        app_ids = [app["id"] for app in data]
        assert "ai" in app_ids
        assert "web" in app_ids


@pytest.mark.integration
def test_specific_app_metadata(api_client):
    """Test metadata for a specific app (ai)."""
    response = api_client.get("/v1/apps/ai/metadata")
    assert response.status_code == 200, f"App metadata failed: {response.text}"
    data = response.json()
    assert data["id"] == "ai"
    assert "skills" in data

    skill_ids = [skill["id"] for skill in data["skills"]]
    assert "ask" in skill_ids


@pytest.mark.integration
def test_specific_skill_metadata(api_client):
    """Test metadata for a specific skill (ai/ask)."""
    response = api_client.get("/v1/apps/ai/skills/ask")
    assert response.status_code == 200, f"Skill metadata failed: {response.text}"
    data = response.json()
    assert data["id"] == "ask"
    assert "providers" in data


@pytest.mark.integration
def test_api_keys_list_authenticated(api_client):
    """Test listing API keys for the current user."""
    response = api_client.get("/v1/settings/api-keys")
    assert response.status_code == 200, f"API keys list failed: {response.text}"
    data = response.json()
    if isinstance(data, dict) and "api_keys" in data:
        keys = data["api_keys"]
    else:
        assert isinstance(data, list)
        keys = data
    assert len(keys) > 0


@pytest.mark.integration
def test_billing_overview_authenticated(api_client):
    """Test the billing overview endpoint (v1/settings/billing)."""
    response = api_client.get("/v1/settings/billing")
    assert response.status_code == 200, f"Billing overview failed: {response.text}"
    data = response.json()
    assert "payment_tier" in data
    assert "invoices" in data
    assert "auto_topup_enabled" in data


@pytest.mark.integration
def test_usage_summary_authenticated(api_client):
    """Test the usage summary endpoint."""
    response = api_client.get("/v1/settings/usage/summaries?type=apps")
    assert response.status_code == 200, f"Usage summary failed: {response.text}"
    data = response.json()
    assert "summaries" in data


@pytest.mark.integration
def test_usage_summaries_authenticated(api_client):
    """Test the usage summaries endpoint (v1/settings/usage/summaries)."""
    response = api_client.get("/v1/settings/usage/summaries?type=apps&months=1")
    assert response.status_code == 200, f"Usage summaries failed: {response.text}"
    data = response.json()
    assert "summaries" in data
    assert "type" in data
    assert data["type"] == "apps"


@pytest.mark.integration
def test_usage_details_authenticated(api_client):
    """Test the usage details endpoint (v1/settings/usage/details)."""
    summary_resp = api_client.get("/v1/settings/usage/summaries?type=apps")
    assert summary_resp.status_code == 200
    summaries = summary_resp.json().get("summaries", [])

    if not summaries:
        pytest.skip("No usage summaries found to test details")

    identifier = summaries[0]["app_id"]
    year_month = summaries[0]["year_month"]

    response = api_client.get(
        f"/v1/settings/usage/details?type=app&identifier={identifier}"
        f"&year_month={year_month}&limit=10"
    )
    assert response.status_code == 200, f"Usage details failed: {response.text}"
    data = response.json()
    assert "entries" in data
    assert isinstance(data["entries"], list)


@pytest.mark.integration
def test_usage_export_authenticated(api_client):
    """Test the usage export endpoint (v1/settings/usage/export)."""
    response = api_client.get("/v1/settings/usage/export?months=1")
    assert response.status_code == 200, f"Usage export failed: {response.text}"
    assert "text/csv" in response.headers["Content-Type"]
    assert "attachment" in response.headers["Content-Disposition"]
    assert (
        "usage-export" in response.headers["Content-Disposition"]
        or "usage_export" in response.headers["Content-Disposition"]
    )


@pytest.mark.integration
def test_invalid_api_key():
    """Test that an invalid API key returns 401."""
    headers = {"Authorization": "Bearer sk-api-invalid-key"}
    with httpx.Client(
        base_url=API_BASE_URL,
        headers=headers,
        event_hooks={"response": [log_response]},
    ) as client:
        response = client.get("/v1/settings/billing")
        assert response.status_code == 401
