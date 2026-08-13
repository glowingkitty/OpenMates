"""Python SDK Teams contract tests.

Purpose: verify the pip SDK exposes Teams V1 parity over the shared REST API.
Security: monkeypatches requests; no API keys or team ciphertext leave tests.
Run: python3 -m pytest packages/openmates-python/tests/test_teams.py.
"""

import json

import pytest

from openmates import OpenMates, OpenMatesConfigError
from openmates.sdk import _create_api_key_material, _decrypt_aes_gcm_bytes, _decrypt_aes_gcm_text


# contract-test: direct surface=sdks.pip assertions=teams.workspace.surface-parity
def test_pip_sdk_teams_methods_use_shared_teams_api(monkeypatch):
    requests_seen = []

    class FakeResponse:
        status_code = 200

        def __init__(self, payload):
            self._payload = payload

        def json(self):
            return self._payload

    def response_for(method, url, payload=None):
        requests_seen.append({"method": method, "url": url, "json": payload})
        if method == "GET" and url.endswith("/v1/teams"):
            return FakeResponse({"teams": [{"team_id": "team-1"}]})
        if method == "GET" and url.endswith("/v1/teams/team-1"):
            return FakeResponse({"team": {"team_id": "team-1"}})
        if method == "POST" and url.endswith("/v1/teams"):
            return FakeResponse({"team": {"team_id": "team-1", **(payload or {})}})
        if method == "PATCH" and url.endswith("/v1/teams/team-1"):
            return FakeResponse({"team": {"team_id": "team-1", **(payload or {})}})
        if method == "POST" and url.endswith("/v1/teams/team-1/invites"):
            return FakeResponse({"invite": {"invite_id": "invite-1"}})
        if method == "POST" and url.endswith("/v1/team-invites/invite-1/accept"):
            return FakeResponse({"status": "pending_access_approval"})
        if method == "POST" and url.endswith("/v1/team-invites/invite-1/decline"):
            return FakeResponse({"success": True})
        if method == "GET" and url.endswith("/v1/teams/team-1/access-requests?status=pending"):
            return FakeResponse({"access_requests": [{"id": "request-1"}]})
        if method == "POST" and url.endswith("/v1/teams/team-1/access-requests/request-1/approve"):
            return FakeResponse({"membership": {"role": "member"}})
        if method == "POST" and url.endswith("/v1/teams/team-1/access-requests/request-1/reject"):
            return FakeResponse({"success": True})
        if method == "POST" and url.endswith("/v1/teams/team-1/members/user-1/remove"):
            return FakeResponse({"success": True})
        if method == "GET" and url.endswith("/v1/teams/team-1/billing"):
            return FakeResponse({"billing": {"credits": 1}})
        if method == "POST" and url.endswith("/v1/teams/team-1/billing/bank-transfer-orders"):
            return FakeResponse({"order_id": "bt_1"})
        if method == "GET" and url.endswith("/v1/teams/team-1/billing/bank-transfer-orders/bt_1"):
            return FakeResponse({"order_id": "bt_1", "status": "pending"})
        if method == "GET" and url.endswith("/v1/teams/team-1/billing/bank-transfer-orders"):
            return FakeResponse({"orders": [{"order_id": "bt_1"}]})
        if method == "GET" and url.endswith("/v1/teams/team-1/billing/usage?member_user_id=user-1"):
            return FakeResponse({"usage": [{"credits": 1}]})
        if method == "GET" and url.endswith("/v1/teams/team-1/memories"):
            return FakeResponse({"memories": [{"id": "memory-1"}]})
        if method == "POST" and url.endswith("/v1/teams/team-1/export"):
            return FakeResponse({"export_id": "export-1"})
        if method == "POST" and url.endswith("/v1/teams/import"):
            return FakeResponse({"imported": True})
        raise AssertionError(f"unexpected request {method} {url}")

    def fake_get(url, *, headers, timeout):
        assert headers["X-OpenMates-SDK"] == "pip"
        return response_for("GET", url)

    def fake_post(url, *, json, headers, timeout):
        assert headers["X-OpenMates-SDK"] == "pip"
        return response_for("POST", url, json)

    def fake_patch(url, *, json, headers, timeout):
        assert headers["X-OpenMates-SDK"] == "pip"
        return response_for("PATCH", url, json)

    def fake_delete(url, *, json, headers, timeout):
        assert headers["X-OpenMates-SDK"] == "pip"
        return response_for("DELETE", url, json)

    monkeypatch.setattr("openmates.sdk.requests.get", fake_get)
    monkeypatch.setattr("openmates.sdk.requests.post", fake_post)
    monkeypatch.setattr("openmates.sdk.requests.patch", fake_patch)
    monkeypatch.setattr("openmates.sdk.requests.delete", fake_delete)

    client = OpenMates(api_key="x")
    assert client.teams.list()[0]["team_id"] == "team-1"
    assert client.teams.get("team-1")["team_id"] == "team-1"
    assert client.teams.create({"encrypted_name": "cipher"})["team_id"] == "team-1"
    assert client.teams.update("team-1", {"encrypted_name": "next"})["encrypted_name"] == "next"
    assert client.teams.invite("team-1", {"invite_id": "invite-1"})["invite_id"] == "invite-1"
    assert client.teams.accept_invite("invite-1")["status"] == "pending_access_approval"
    assert client.teams.decline_invite("invite-1")["success"] is True
    assert client.teams.access_requests("team-1", status="pending")[0]["id"] == "request-1"
    assert client.teams.approve_access("team-1", "request-1")["role"] == "member"
    assert client.teams.reject_access("team-1", "request-1")["success"] is True
    assert client.teams.remove_member("team-1", "user-1")["success"] is True
    assert client.teams.billing("team-1")["credits"] == 1
    assert client.teams.create_bank_transfer_order("team-1", 110000, email_encryption_key="email-key")["order_id"] == "bt_1"
    assert client.teams.bank_transfer_status("team-1", "bt_1")["status"] == "pending"
    assert client.teams.list_bank_transfer_orders("team-1")["orders"][0]["order_id"] == "bt_1"
    assert client.teams.usage("team-1", member_user_id="user-1")[0]["credits"] == 1
    assert client.teams.memories("team-1")[0]["id"] == "memory-1"
    assert client.teams.export("team-1")["export_id"] == "export-1"
    assert client.teams.import_team({"destination_team_id": "team-2", "artifact": {}})["imported"] is True

    assert [entry["method"] for entry in requests_seen] == [
        "GET", "GET", "POST", "PATCH", "POST", "POST", "POST",
        "GET", "POST", "POST", "POST", "GET", "POST", "GET", "GET",
        "GET", "GET", "POST", "POST",
    ]


# contract-test: direct surface=sdks.pip assertions=teams.lifecycle.encrypted-profiled,teams.profile-image.safe-parity,teams.workspace.surface-parity
def test_pip_sdk_team_profile_image_helpers_encrypt_generated_metadata(monkeypatch):
    master_key = bytes([11]) * 32
    api_key, material = _create_api_key_material("pip teams profile", master_key)
    requests_seen = []
    stored_team = None

    class FakeResponse:
        status_code = 200

        def __init__(self, payload=None, *, content=b"", headers=None):
            self._payload = payload or {}
            self.content = content
            self.headers = headers or {}

        def json(self):
            return self._payload

    def fake_get(url, *, headers, timeout):
        requests_seen.append({"method": "GET", "url": url})
        assert headers["Authorization"] == f"Bearer {api_key}"
        assert headers["X-OpenMates-SDK"] == "pip"
        if url.endswith("/v1/teams/team-1/profile-image"):
            return FakeResponse(content=b"\x89PNG", headers={"content-type": "image/png", "content-disposition": 'attachment; filename="team.png"'})
        if url.endswith("/v1/teams/team-1"):
            assert stored_team is not None
            return FakeResponse({"team": stored_team})
        raise AssertionError(f"unexpected GET {url}")

    def fake_post(url, *, json, headers, timeout):
        nonlocal stored_team
        requests_seen.append({"method": "POST", "url": url, "json": json})
        assert headers["Authorization"] == f"Bearer {api_key}"
        assert headers["X-OpenMates-SDK"] == "pip"
        if url.endswith("/v1/sdk/session"):
            return FakeResponse({"key_wrapper": {"encrypted_key": material["encrypted_master_key"], "salt": material["salt"], "key_iv": material["key_iv"]}})
        if url.endswith("/v1/teams"):
            stored_team = {"team_id": "team-1", **json}
            return FakeResponse({"team": stored_team})
        raise AssertionError(f"unexpected POST {url}")

    def fake_patch(url, *, json, headers, timeout):
        nonlocal stored_team
        requests_seen.append({"method": "PATCH", "url": url, "json": json})
        assert headers["Authorization"] == f"Bearer {api_key}"
        assert headers["X-OpenMates-SDK"] == "pip"
        if url.endswith("/v1/teams/team-1"):
            stored_team = {**(stored_team or {}), **json}
            return FakeResponse({"team": stored_team})
        raise AssertionError(f"unexpected PATCH {url}")

    monkeypatch.setattr("openmates.sdk.requests.get", fake_get)
    monkeypatch.setattr("openmates.sdk.requests.post", fake_post)
    monkeypatch.setattr("openmates.sdk.requests.patch", fake_patch)

    client = OpenMates(api_key=api_key)
    created = client.teams.create_plain({
        "team_id": "team-1",
        "name": "Pip Team",
        "profile": {"icon_name": "users", "background_color": "#112233"},
        "created_at": 100,
    })
    updated = client.teams.update_generated_profile_image("team-1", icon_name="sparkles", background_color="#445566")
    image = client.teams.get_profile_image("team-1")

    assert created["profile_image_metadata"]["background_color"] == "#112233"
    assert updated["profile_image_metadata"]["icon_name"] == "sparkles"
    assert image["content_type"] == "image/png"
    assert image["filename"] == "team.png"
    assert image["data"] == b"\x89PNG"

    create_body = requests_seen[1]["json"]
    team_key = _decrypt_aes_gcm_bytes(create_body["encrypted_team_key"], master_key)
    assert team_key is not None
    create_profile = json.loads(_decrypt_aes_gcm_text(create_body["encrypted_profile_image_metadata"], team_key))
    assert create_profile["mode"] == "generated"
    assert create_profile["icon_name"] == "users"
    assert create_profile["background_color"] == "#112233"
    assert "name" not in create_body
    assert "profile" not in create_body

    update_body = requests_seen[3]["json"]
    update_profile = json.loads(_decrypt_aes_gcm_text(update_body["encrypted_profile_image_metadata"], team_key))
    assert update_profile["mode"] == "generated"
    assert update_profile["icon_name"] == "sparkles"
    assert update_profile["background_color"] == "#445566"
    assert "profile" not in update_body
    assert [(entry["method"], entry["url"].replace("https://api.openmates.org", "")) for entry in requests_seen] == [
        ("POST", "/v1/sdk/session"),
        ("POST", "/v1/teams"),
        ("GET", "/v1/teams/team-1"),
        ("PATCH", "/v1/teams/team-1"),
        ("GET", "/v1/teams/team-1/profile-image"),
    ]


# contract-test: direct surface=sdks.pip assertions=teams.workspace.surface-parity
def test_pip_sdk_team_connected_accounts_are_disabled():
    client = OpenMates(api_key="x")
    with pytest.raises(OpenMatesConfigError, match="Team connected accounts are not supported yet"):
        client.connected_accounts.import_account(payload="OMCA1.disabled", passcode="x", team_id="team-1")


# contract-test: direct surface=sdks.pip assertions=teams.workspace.surface-parity
def test_pip_sdk_teams_do_not_expose_direct_credit_grants_or_destructive_methods():
    client = OpenMates(api_key="x")

    assert not hasattr(client.teams, "add_credits")
    assert not hasattr(client.teams, "delete")
    assert not hasattr(client.teams, "move")
