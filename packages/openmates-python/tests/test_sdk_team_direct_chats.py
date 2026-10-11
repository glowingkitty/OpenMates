"""Python SDK Team direct-chat account and transport contract tests.

Security: verifies immutable account-key recovery, participant-only envelopes,
and fail-closed handling of private chat keys without Team-key fallback.
"""

import base64
import hashlib

import pytest

from openmates import OpenMates, OpenMatesConfigError
from openmates.direct_chats import (
    DirectChatIdentity, generate_identity, open_direct_chat_key,
)
from openmates.sdk import OpenMatesApiError, _decrypt_aes_gcm_text


TEAM_ID = "team-123"
USER_ID = "sender-user"
OWN_HASH = hashlib.sha256(USER_ID.encode()).hexdigest()
RECIPIENT_HASH = "a" * 64
CHAT_ID = "11111111-1111-4111-8111-111111111111"
MASTER_KEY = bytes(range(32))


def _client():
    client = OpenMates(api_key="sk-api-test")
    client._sdk_session = {"user": {"id": USER_ID}}
    client._master_key = MASTER_KEY
    return client


def _record_from_request(payload):
    assert payload["version"] == 1
    assert payload["algorithm"] == "x25519-xsalsa20poly1305"
    encrypted = payload["encrypted_private_key"]
    combined = base64.b64encode(base64.urlsafe_b64decode(encrypted + "=" * (-len(encrypted) % 4))).decode()
    assert _decrypt_aes_gcm_text(combined, MASTER_KEY)
    return payload


# contract-test: supporting surface=sdks.pip assertions=sdk.surface.semantic-parity,teams.direct-chat.account-key-exchange
def test_member_chat_encryption_key_validates_canonical_directory_key(monkeypatch):
    client = _client()
    member = generate_identity()
    paths = []
    monkeypatch.setattr(client, "_get", lambda path: paths.append(path) or {
        "key_id": member.key_id, "public_key": member.public_key, "extra": "ignored",
    })
    assert client.teams.member_chat_encryption_key(TEAM_ID, RECIPIENT_HASH) == {
        "key_id": member.key_id, "public_key": member.public_key,
    }
    assert paths == [f"/v1/teams/{TEAM_ID}/members/{RECIPIENT_HASH}/chat-encryption-key"]
    monkeypatch.setattr(client, "_get", lambda path: {"key_id": "f" * 64, "public_key": member.public_key})
    with pytest.raises(OpenMatesConfigError, match="mismatch"):
        client.teams.member_chat_encryption_key(TEAM_ID, RECIPIENT_HASH)


# contract-test: supporting surface=sdks.pip assertions=sdk.surface.semantic-parity,teams.direct-chat.account-key-exchange
def test_member_chat_encryption_key_reports_missing_enrollment(monkeypatch):
    client = _client()
    def missing(_path):
        raise OpenMatesApiError(404, {"detail": "missing"})
    monkeypatch.setattr(client, "_get", missing)
    with pytest.raises(OpenMatesConfigError, match="Direct message pending"):
        client.teams.member_chat_encryption_key(TEAM_ID, RECIPIENT_HASH)


# contract-test: supporting surface=sdks.pip assertions=sdk.surface.semantic-parity,teams.direct-chat.account-key-exchange
def test_chat_identity_enrolls_and_recovers_its_encrypted_backup(monkeypatch):
    client = _client()
    writes = []

    def missing(path):
        assert path == "/v1/account/chat-encryption-key"
        raise OpenMatesApiError(404, {})

    def put(path, payload):
        assert path == "/v1/account/chat-encryption-key"
        writes.append(payload)
        return {"key": payload}

    monkeypatch.setattr(client, "_get", missing)
    monkeypatch.setattr(client, "_put", put)
    identity = client._chat_identity()
    assert len(writes) == 1
    _record_from_request(writes[0])
    assert writes[0]["public_key"] == identity.public_key
    assert writes[0]["key_id"] == identity.key_id
    assert identity.private_key not in str(writes[0])


# contract-test: supporting surface=sdks.pip assertions=sdk.surface.semantic-parity,teams.direct-chat.account-key-exchange
def test_chat_identity_enrolls_encrypted_backup_and_recovers_winner_on_race(monkeypatch):
    client = _client()
    winner = generate_identity()
    winner_record = None
    put_payloads = []

    def get(path):
        assert path == "/v1/account/chat-encryption-key"
        if winner_record is None:
            raise OpenMatesApiError(404, {})
        return {"key": winner_record}

    def put(path, payload):
        nonlocal winner_record
        assert path == "/v1/account/chat-encryption-key"
        put_payloads.append(payload)
        winner_record = {**payload, "key_id": winner.key_id, "public_key": winner.public_key}
        # Simulate an independently created, correctly encrypted winning backup.
        from openmates.sdk import _encrypt_aes_gcm_text
        combined = base64.b64decode(_encrypt_aes_gcm_text(winner.private_key, MASTER_KEY))
        winner_record["encrypted_private_key"] = base64.urlsafe_b64encode(combined).decode().rstrip("=")
        raise OpenMatesApiError(409, {})

    monkeypatch.setattr(client, "_get", get)
    monkeypatch.setattr(client, "_put", put)
    assert client._chat_identity() == winner
    assert len(put_payloads) == 1
    _record_from_request(put_payloads[0])


# contract-test: supporting surface=sdks.pip assertions=sdk.surface.semantic-parity,teams.direct-chat.account-key-exchange
def test_chat_identity_rejects_wrong_private_backup(monkeypatch):
    client = _client()
    one, two = generate_identity(), generate_identity()
    from openmates.sdk import _encrypt_aes_gcm_text
    encrypted = base64.urlsafe_b64encode(base64.b64decode(_encrypt_aes_gcm_text(two.private_key, MASTER_KEY))).decode().rstrip("=")
    monkeypatch.setattr(client, "_get", lambda path: {"key": {
        "version": 1, "algorithm": "x25519-xsalsa20poly1305", "key_id": one.key_id,
        "public_key": one.public_key, "encrypted_private_key": encrypted,
    }})
    with pytest.raises(OpenMatesConfigError, match="mismatch"):
        client._chat_identity()


# contract-test: supporting surface=sdks.pip assertions=sdk.surface.semantic-parity,teams.direct-chat.account-key-exchange
def test_open_direct_chat_seals_both_participants_and_decrypts_response(monkeypatch):
    client = _client()
    own, recipient = generate_identity(), generate_identity()
    monkeypatch.setattr(client, "_chat_identity", lambda: own)
    monkeypatch.setattr(client.teams, "member_chat_encryption_key", lambda team_id, hash_value: {
        "key_id": recipient.key_id, "public_key": recipient.public_key,
    })
    calls = []

    def post(path, payload):
        calls.append((path, payload))
        assert set(payload) == {"chat_id", "recipient_user_hash", "participant_key_envelopes", "encrypted_title"}
        assert payload["recipient_user_hash"] == RECIPIENT_HASH
        assert set(payload["participant_key_envelopes"]) == {OWN_HASH, RECIPIENT_HASH}
        own_envelope = payload["participant_key_envelopes"][OWN_HASH]
        recipient_envelope = payload["participant_key_envelopes"][RECIPIENT_HASH]
        own_key = open_direct_chat_key(own_envelope["encrypted_chat_key"], DirectChatIdentity(
            TEAM_ID, payload["chat_id"], OWN_HASH, own.key_id,
        ), own.private_key)
        peer_key = open_direct_chat_key(recipient_envelope["encrypted_chat_key"], DirectChatIdentity(
            TEAM_ID, payload["chat_id"], RECIPIENT_HASH, recipient.key_id,
        ), recipient.private_key)
        assert own_key == peer_key and own_key != MASTER_KEY
        assert _decrypt_aes_gcm_text(payload["encrypted_title"], own_key) == "Private Team message"
        return {"chat": {"id": payload["chat_id"], "team_id": TEAM_ID,
                         "chat_visibility": "direct", "participant_user_hashes": [OWN_HASH, RECIPIENT_HASH],
                         "encrypted_chat_key": own_envelope["encrypted_chat_key"],
                         "encrypted_title": payload["encrypted_title"]}}

    monkeypatch.setattr(client, "_post", post)
    chat = client.teams.open_direct_chat(TEAM_ID, RECIPIENT_HASH)
    assert chat["title"] == "Private Team message"
    assert calls[0][0] == f"/v1/teams/{TEAM_ID}/direct-chats"


# contract-test: supporting surface=sdks.pip assertions=sdk.surface.semantic-parity,teams.direct-chat.participant-isolation
def test_direct_chat_key_resolution_never_falls_back_to_master_or_team_key(monkeypatch):
    client = _client()
    own = generate_identity()
    monkeypatch.setattr(client, "_chat_identity", lambda: own)
    # A master-wrapped key on a direct chat must be rejected as an invalid OMDM1 envelope.
    chat = {"id": CHAT_ID, "team_id": TEAM_ID, "chat_visibility": "direct",
            "participant_user_hashes": [OWN_HASH, RECIPIENT_HASH],
            "encrypted_chat_key": "not-an-OMDM1-envelope"}
    with pytest.raises(OpenMatesConfigError, match="direct-chat envelope"):
        client._resolve_loaded_chat_key(chat)
    with pytest.raises(OpenMatesConfigError, match="participant binding"):
        client._resolve_loaded_chat_key({**chat, "participant_user_hashes": [RECIPIENT_HASH, "f" * 64]})


# contract-test: supporting surface=sdks.pip assertions=sdk.surface.semantic-parity,teams.direct-chat.participant-isolation
@pytest.mark.parametrize("wrong", [
    {"chat_visibility": "team"}, {"team_id": "another-team"}, {"id": CHAT_ID},
    {"participant_user_hashes": [OWN_HASH, "f" * 64]},
])
def test_open_direct_chat_rejects_mismatched_server_metadata_before_decrypt(monkeypatch, wrong):
    client = _client()
    own, recipient = generate_identity(), generate_identity()
    monkeypatch.setattr(client, "_chat_identity", lambda: own)
    monkeypatch.setattr(client.teams, "member_chat_encryption_key", lambda _team, _hash: {
        "key_id": recipient.key_id, "public_key": recipient.public_key,
    })

    def post(_path, payload):
        return {"chat": {"chat_visibility": "direct", "team_id": TEAM_ID,
                         "id": payload["chat_id"],
                         "participant_user_hashes": [OWN_HASH, RECIPIENT_HASH], **wrong}}

    monkeypatch.setattr(client, "_post", post)
    monkeypatch.setattr(client, "_decrypt_chat_metadata", lambda _chat: pytest.fail("Unexpected decrypt"))
    with pytest.raises(OpenMatesConfigError, match="mismatched metadata"):
        client.teams.open_direct_chat(TEAM_ID, RECIPIENT_HASH)
