"""Python SDK Teams contract tests.

Purpose: verify the pip SDK exposes Teams V1 parity over the shared REST API.
Security: monkeypatches requests; no API keys or team ciphertext leave tests.
Run: python3 -m pytest packages/openmates-python/tests/test_teams.py.
"""

import json

import pytest

from openmates import OpenMates, OpenMatesConfigError
from openmates.sdk import (
    _is_team_ai_invocation,
    _create_api_key_material,
    _decrypt_aes_gcm_bytes,
    _decrypt_aes_gcm_text,
    _encrypt_aes_gcm_bytes,
    _encrypt_aes_gcm_text,
)


# contract-test: direct surface=sdks.pip assertions=billing.storage.weekly-quote,billing.storage.team-warning-expiry
def test_pip_sdk_reads_team_storage_and_notice_pages(monkeypatch):
    client = OpenMates(api_key="x")
    seen = []
    cursor = "a" * 64

    def fake_get(path):
        seen.append(path)
        if path == "/v1/teams/team-1/storage":
            return {"storage": {"total_bytes": 0, "weekly_cost_credits": 0, "billing_status": "disabled_pending_validation"}}
        if path == f"/v1/teams/team-1/storage/notice?limit=25&after_unit_id={cursor}":
            return {"episode_id": "episode-1", "units": [], "has_more": False}
        raise AssertionError(f"unexpected Team storage GET {path}")

    monkeypatch.setattr(client, "_get", fake_get)
    assert client.teams.storage("team-1")["weekly_cost_credits"] == 0
    assert client.teams.storage_notice("team-1", limit=25, after_unit_id=cursor)["episode_id"] == "episode-1"
    assert seen == ["/v1/teams/team-1/storage", f"/v1/teams/team-1/storage/notice?limit=25&after_unit_id={cursor}"]
    with pytest.raises(ValueError, match="limit"):
        client.teams.storage_notice("team-1", limit=101)


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
        if method == "POST" and url.endswith("/v1/teams/invites/invite-1/accept"):
            return FakeResponse({"status": "pending_access_approval"})
        if method == "POST" and url.endswith("/v1/teams/invites/invite-1/decline"):
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
    buyer_address = {"name": "Pip Team", "street_line_1": "Example Street 3", "postal_code": "10115", "city": "Berlin", "country": "DE"}
    assert client.teams.create_bank_transfer_order("team-1", 110000, email_encryption_key="email-key", buyer_address=buyer_address)["order_id"] == "bt_1"
    assert client.teams.bank_transfer_status("team-1", "bt_1")["status"] == "pending"
    assert client.teams.list_bank_transfer_orders("team-1")["orders"][0]["order_id"] == "bt_1"
    assert client.teams.usage("team-1", member_user_id="user-1")[0]["credits"] == 1
    assert client.teams.memories("team-1")[0]["id"] == "memory-1"
    assert client.teams.export("team-1")["export_id"] == "export-1"
    assert client.teams.import_team({"destination_team_id": "team-2", "artifact": {}})["imported"] is True

    # contract-test: direct surface=sdks.pip assertions=teams.billing.context-parity
    order = next(entry for entry in requests_seen if entry["url"].endswith("/v1/teams/team-1/billing/bank-transfer-orders"))
    assert order["json"] == {"credits_amount": 110000, "currency": "eur", "email_encryption_key": "email-key", "buyer_address": buyer_address}

    assert [entry["method"] for entry in requests_seen] == [
        "GET", "GET", "POST", "PATCH", "POST", "POST", "POST",
        "GET", "POST", "POST", "POST", "GET", "POST", "GET", "GET",
        "GET", "GET", "POST", "POST",
    ]


# contract-test: direct surface=sdks.pip assertions=teams.lifecycle.encrypted-profiled,teams.profile-image.safe-parity,teams.workspace.surface-parity,teams.name.transient-policy
def test_pip_sdk_team_profile_image_helpers_encrypt_generated_metadata(monkeypatch):
    master_key = bytes([11]) * 32
    api_key, material = _create_api_key_material("pip teams profile", master_key)
    bearer_api_key = api_key.partition(".")[0]
    assert bearer_api_key != api_key  # The local decryption secret must stay out of the Authorization header.
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
        assert headers["Authorization"] == f"Bearer {bearer_api_key}"
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
        assert headers["Authorization"] == f"Bearer {bearer_api_key}"
        assert headers["X-OpenMates-SDK"] == "pip"
        if url.endswith("/v1/sdk/session"):
            return FakeResponse({"key_wrapper": {"encrypted_key": material["encrypted_master_key"], "salt": material["salt"], "key_iv": material["key_iv"]}})
        if url.endswith("/v1/teams/name-approval"):
            assert json == {"name": "pip team"}
            return FakeResponse({"approval_token": "approved-pip-team", "expires_at": 1000})
        if url.endswith("/v1/teams"):
            stored_team = {"team_id": "team-1", **json}
            return FakeResponse({"team": stored_team})
        raise AssertionError(f"unexpected POST {url}")

    def fake_patch(url, *, json, headers, timeout):
        nonlocal stored_team
        requests_seen.append({"method": "PATCH", "url": url, "json": json})
        assert headers["Authorization"] == f"Bearer {bearer_api_key}"
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

    # contract-test: direct surface=sdks.pip assertions=teams.name.transient-policy
    assert requests_seen[0]["json"] == {"name": "pip team"}
    create_body = requests_seen[2]["json"]
    assert create_body["name_approval_token"] == "approved-pip-team"
    team_key = _decrypt_aes_gcm_bytes(create_body["encrypted_team_key"], master_key)
    assert team_key is not None
    create_profile = json.loads(_decrypt_aes_gcm_text(create_body["encrypted_profile_image_metadata"], team_key))
    assert create_profile["mode"] == "generated"
    assert create_profile["icon_name"] == "users"
    assert create_profile["background_color"] == "#112233"
    assert "name" not in create_body
    assert "profile" not in create_body

    update_body = requests_seen[4]["json"]
    update_profile = json.loads(_decrypt_aes_gcm_text(update_body["encrypted_profile_image_metadata"], team_key))
    assert update_profile["mode"] == "generated"
    assert update_profile["icon_name"] == "sparkles"
    assert update_profile["background_color"] == "#445566"
    assert "profile" not in update_body
    assert [(entry["method"], entry["url"].replace("https://api.openmates.org", "")) for entry in requests_seen] == [
        ("POST", "/v1/teams/name-approval"),
        ("POST", "/v1/sdk/session"),
        ("POST", "/v1/teams"),
        ("GET", "/v1/teams/team-1"),
        ("PATCH", "/v1/teams/team-1"),
        ("GET", "/v1/teams/team-1/profile-image"),
    ]


# contract-test: direct surface=sdks.pip assertions=teams.workspace.surface-parity
def test_pip_sdk_team_member_profiles_use_team_key_and_ciphertext(monkeypatch):
    master_key = bytes([19]) * 32
    team_key = bytes([23]) * 32
    encrypted_team_key = _encrypt_aes_gcm_bytes(team_key, master_key)
    encrypted_member_profile = _encrypt_aes_gcm_text(json.dumps({"display_name": "Alice", "avatar": "cat"}), team_key)
    client = OpenMates(api_key="x")
    requests_seen = []

    def fake_get(path):
        requests_seen.append(("GET", path))
        if path == "/v1/teams/team-1":
            return {"team": {"encrypted_team_key": encrypted_team_key}}
        if path == "/v1/teams/team-1/members":
            return {"members": [
                {"user_id": "user-1", "encrypted_member_profile": encrypted_member_profile},
                {"user_id": "user-2", "encrypted_member_profile": None},
            ]}
        if path == "/v1/teams/team-1/members/user-1":
            return {"member": {"user_id": "user-1", "encrypted_member_profile": encrypted_member_profile}}
        raise AssertionError(path)

    def fake_patch(path, payload):
        requests_seen.append(("PATCH", path, payload))
        assert path == "/v1/teams/team-1/members/me/profile"
        assert set(payload) == {"encrypted_member_profile"}
        assert _decrypt_aes_gcm_text(payload["encrypted_member_profile"], team_key) == json.dumps({"display_name": "Alice", "avatar": None})
        return {"member": {"user_id": "user-1", **payload}}

    monkeypatch.setattr(client, "_get_master_key", lambda: master_key)
    monkeypatch.setattr(client, "_get", fake_get)
    monkeypatch.setattr(client, "_patch", fake_patch)

    members = client.teams.list_members("team-1")
    assert members[0]["profile"] == {"display_name": "Alice", "avatar": "cat"}
    assert members[1]["profile"] is None
    assert client.teams.get_member("team-1", "user-1")["profile"]["display_name"] == "Alice"
    assert client.teams.update_own_member_profile("team-1", display_name=" Alice ")["profile"] == {"display_name": "Alice", "avatar": None}
    assert [entry[:2] for entry in requests_seen] == [
        ("GET", "/v1/teams/team-1"), ("GET", "/v1/teams/team-1/members"),
        ("GET", "/v1/teams/team-1"), ("GET", "/v1/teams/team-1/members/user-1"),
        ("GET", "/v1/teams/team-1"), ("PATCH", "/v1/teams/team-1/members/me/profile"),
    ]


# contract-test: direct surface=sdks.pip assertions=teams.workspace.surface-parity
def test_pip_sdk_team_member_profile_rejects_bad_ciphertext_and_missing_member(monkeypatch):
    master_key = bytes([29]) * 32
    team_key = bytes([31]) * 32
    client = OpenMates(api_key="x")
    monkeypatch.setattr(client, "_get_master_key", lambda: master_key)

    def fake_get(path):
        if path == "/v1/teams/team-1":
            return {"team": {"encrypted_team_key": _encrypt_aes_gcm_bytes(team_key, master_key)}}
        if path.endswith("/members/user-1"):
            return {"member": {"encrypted_member_profile": _encrypt_aes_gcm_text("secret", bytes([32]) * 32)}}
        raise AssertionError(path)

    monkeypatch.setattr(client, "_get", fake_get)
    with pytest.raises(OpenMatesConfigError, match="Failed to decrypt Team member profile"):
        client.teams.get_member("team-1", "user-1")

    monkeypatch.setattr(client, "_get", lambda path: {"team": {"encrypted_team_key": _encrypt_aes_gcm_bytes(team_key, master_key)}} if path == "/v1/teams/team-1" else {})
    with pytest.raises(OpenMatesConfigError, match="Team member response is missing member"):
        client.teams.get_member("team-1", "user-1")


# contract-test: direct surface=sdks.pip assertions=teams.chat.encrypted-until-invoked,teams.workspace.surface-parity
@pytest.mark.parametrize("message", [
    "private team note", "@Alice could you review this?", "email@openmates.org",
    "@openmates_fake is a handle", "@mate:unknown_person review this",
])
def test_pip_sdk_sends_ordinary_team_chat_as_ciphertext_without_inference(monkeypatch, message):
    master_key = bytes([13]) * 32
    team_key = bytes([17]) * 32
    api_key, material = _create_api_key_material("pip teams chat", master_key)
    encrypted_team_key = _encrypt_aes_gcm_bytes(team_key, master_key)
    requests_seen = []

    class FakeResponse:
        status_code = 200

        def __init__(self, payload):
            self._payload = payload

        def json(self):
            return self._payload

    def fake_get(url, *, headers, timeout):
        requests_seen.append({"method": "GET", "url": url})
        assert url.endswith("/v1/teams/team-1")
        return FakeResponse({"team": {"team_id": "team-1", "encrypted_team_key": encrypted_team_key}})

    def fake_post(url, *, json, headers, timeout):
        requests_seen.append({"method": "POST", "url": url, "json": json})
        if url.endswith("/v1/sdk/session"):
            return FakeResponse({
                "user": {"id": "user-1"},
                "key_wrapper": {
                    "encrypted_key": material["encrypted_master_key"],
                    "salt": material["salt"],
                    "key_iv": material["key_iv"],
                },
            })
        if url.endswith("/v1/sdk/chats"):
            assert json.get("message") is None
            assert json.get("team_ai_invocation") is None
            assert json["team_id"] == "team-1"
            assert json["team_member_mentions"] == ["user-2"]
            return FakeResponse({"persistent": True, "chat_id": json["chat_id"], "task_id": None, "ai_dispatched": False})
        raise AssertionError(f"unexpected POST {url}")

    monkeypatch.setattr("openmates.sdk.requests.get", fake_get)
    monkeypatch.setattr("openmates.sdk.requests.post", fake_post)

    client = OpenMates(api_key=api_key)
    result = client.chats.send(
        message,
        team_id="team-1",
        sender_name="Alice",
        history=[{"role": "user", "content": "Earlier private note", "sender_name": "Bob"}],
        title="Private team title",
        team_member_mentions=["user-2"],
    )
    assert result.raw["ai_dispatched"] is False
    payload = requests_seen[2]["json"]
    chat_key = _decrypt_aes_gcm_bytes(payload["encrypted_chat_key"], team_key)
    assert chat_key is not None
    assert _decrypt_aes_gcm_text(payload["encrypted_user_message"]["encrypted_content"], chat_key) == message
    assert _decrypt_aes_gcm_text(payload["encrypted_user_message"]["encrypted_sender_name"], chat_key) == "Alice"
    assert payload["inference_request"]["messages"] == []
    assert payload["history"] == []
    assert payload["title"] is None
    serialized = json.dumps(payload)
    assert message not in serialized
    assert "Earlier private note" not in serialized
    assert "Private team title" not in serialized


# contract-test: direct surface=sdks.pip assertions=teams.chat.encrypted-until-invoked,teams.chat.sender-identity-layout
def test_pip_sdk_known_mate_invokes_with_full_distinct_human_history(monkeypatch):
    master_key = bytes([13]) * 32
    team_key = bytes([17]) * 32
    api_key, material = _create_api_key_material("pip teams mate", master_key)
    encrypted_team_key = _encrypt_aes_gcm_bytes(team_key, master_key)
    captured = {}

    class FakeResponse:
        status_code = 200

        def __init__(self, payload):
            self._payload = payload

        def json(self):
            return self._payload

    def fake_get(url, *, headers, timeout):
        assert url.endswith("/v1/teams/team-1")
        return FakeResponse({"team": {"team_id": "team-1", "encrypted_team_key": encrypted_team_key}})

    def fake_post(url, *, json, headers, timeout):
        if url.endswith("/v1/sdk/session"):
            return FakeResponse({"user": {"id": "bob-id", "username": "Bob"}, "key_wrapper": {
                "encrypted_key": material["encrypted_master_key"],
                "salt": material["salt"], "key_iv": material["key_iv"],
            }})
        if url.endswith("/v1/sdk/chats"):
            captured.update(json)
            return FakeResponse({"task_id": "task-1"})
        raise AssertionError(f"unexpected POST {url}")

    class StopBeforeRecovery(Exception):
        pass

    monkeypatch.setattr("openmates.sdk.requests.get", fake_get)
    monkeypatch.setattr("openmates.sdk.requests.post", fake_post)
    client = OpenMates(api_key=api_key)
    monkeypatch.setattr(client.chats, "_poll_recovery_claim", lambda *_args, **_kwargs: (_ for _ in ()).throw(StopBeforeRecovery()))

    with pytest.raises(StopBeforeRecovery):
        client.chats.send(
            "@mate:software_development please compare our ideas",
            team_id="team-1", sender_name="Untrusted alias",
            history=[{"role": "user", "content": "I prefer design A", "sender_name": "Alice"}],
        )

    history = captured["team_ai_invocation"]["history"]
    assert [(item["sender_name"], item["content"]) for item in history] == [
        ("Alice", "I prefer design A"),
        ("Bob", "@mate:software_development please compare our ideas"),
    ]
    assert captured["inference_request"]["messages"] == history
    assert captured["history"] == []
    chat_key = _decrypt_aes_gcm_bytes(captured["encrypted_chat_key"], team_key)
    assert chat_key is not None
    assert _decrypt_aes_gcm_text(captured["encrypted_user_message"]["encrypted_sender_name"], chat_key) == "Bob"


# contract-test: supporting surface=sdks.pip assertions=teams.chat.encrypted-until-invoked
def test_pip_sdk_team_ai_trigger_accepts_only_explicit_known_mentions():
    assert _is_team_ai_invocation("@OpenMates summarize")
    assert _is_team_ai_invocation("@mate:software_development review")
    assert not _is_team_ai_invocation("@mate:onboarding_support review")
    assert not _is_team_ai_invocation("@Sophia review")
    assert not _is_team_ai_invocation("email@openmates.org")


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
