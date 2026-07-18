"""Python SDK Teams contract tests.

Purpose: verify the pip SDK exposes Teams V1 parity over the shared REST API.
Security: monkeypatches requests; no API keys or team ciphertext leave tests.
Run: python3 -m pytest packages/openmates-python/tests/test_teams.py.
"""

import pytest

from openmates import OpenMates, OpenMatesConfigError


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
        if method == "DELETE" and url.endswith("/v1/teams/team-1"):
            return FakeResponse({"success": True})
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
        if method == "POST" and url.endswith("/v1/teams/team-1/billing/credits"):
            return FakeResponse({"billing": {"credits": 2}})
        if method == "GET" and url.endswith("/v1/teams/team-1/billing/usage?member_user_id=user-1"):
            return FakeResponse({"usage": [{"credits": 1}]})
        if method == "GET" and url.endswith("/v1/teams/team-1/memories"):
            return FakeResponse({"memories": [{"id": "memory-1"}]})
        if method == "POST" and url.endswith("/v1/chats/chat-1/move"):
            return FakeResponse({"success": True})
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
    assert client.teams.delete("team-1")["success"] is True
    assert client.teams.invite("team-1", {"invite_id": "invite-1"})["invite_id"] == "invite-1"
    assert client.teams.accept_invite("invite-1")["status"] == "pending_access_approval"
    assert client.teams.decline_invite("invite-1")["success"] is True
    assert client.teams.access_requests("team-1", status="pending")[0]["id"] == "request-1"
    assert client.teams.approve_access("team-1", "request-1")["role"] == "member"
    assert client.teams.reject_access("team-1", "request-1")["success"] is True
    assert client.teams.remove_member("team-1", "user-1")["success"] is True
    assert client.teams.billing("team-1")["credits"] == 1
    assert client.teams.add_credits("team-1", {"credits": 1})["credits"] == 2
    assert client.teams.usage("team-1", member_user_id="user-1")[0]["credits"] == 1
    assert client.teams.memories("team-1")[0]["id"] == "memory-1"
    assert client.teams.move("chat", "chat-1", "team-1")["success"] is True
    assert client.teams.export("team-1")["export_id"] == "export-1"
    assert client.teams.import_team({"destination_team_id": "team-2", "artifact": {}})["imported"] is True

    assert [entry["method"] for entry in requests_seen] == [
        "GET", "GET", "POST", "PATCH", "DELETE", "POST", "POST", "POST",
        "GET", "POST", "POST", "POST", "GET", "POST", "GET", "GET",
        "POST", "POST", "POST",
    ]


def test_pip_sdk_team_connected_accounts_are_disabled():
    client = OpenMates(api_key="x")
    with pytest.raises(OpenMatesConfigError, match="Team connected accounts are not supported yet"):
        client.connected_accounts.import_account(payload="OMCA1.disabled", passcode="x", team_id="team-1")
