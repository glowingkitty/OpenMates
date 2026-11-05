"""Independent synthetic saved-read/share oracle. Import/construction opens no IO."""

from copy import deepcopy
import base64
import hashlib
import time
from urllib.parse import parse_qs, urlsplit
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from session_drafts_server import SessionDraftPeer

CAPABILITY = "session.embeds.admitted-share-url.v1"


def unwrap(blob, password, salt):
    assert isinstance(blob, str) and len(blob) <= 16384
    raw = base64.urlsafe_b64decode(blob + "=" * (-len(blob) % 4))
    assert len(raw) >= 28
    key = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, 100000, 32)
    return AESGCM(key).decrypt(raw[:12], raw[12:], None)


class CookieSharePeer(SessionDraftPeer):
    def __init__(self, suite, vector, identity):
        super().__init__(suite, vector, identity)
        self.requests = []
        self.started = int(time.time())

    def http(self, method, path, headers, body):
        self.headers(headers)
        assert method == "POST" and path == "/v1/auth/session"
        assert body == {"session_id": self.suite["account"]["session_id"]}
        self.counts["http"] += 1
        owner = (
            self.suite["protocol"]["team_id"]
            if self.vector.get("mode") == "auth-owner-changed"
            else self.suite["account"]["owner_id"]
        )
        return 200, {
            "success": True,
            "ws_token": "synthetic-drafts-ws",
            "user": {"id": owner},
        }

    def event(self, kind, payload):
        if kind == "native_client_lifecycle":
            assert (
                payload["client_type"] == self.identity
                and payload["interactive"] is False
            )
            self.counts["lifecycle"] += 1
            return []
        assert kind == "request_embed" and payload == {
            "embed_id": self.suite["embed_id"]
        }, "no sync/jobs/mutation/key export"
        self.requests.append(payload["embed_id"])
        assert len(self.requests) == 1
        mode = self.vector.get("mode")
        if mode == "ws-denied":
            return [
                ("error", {"status": 403, "detail": "synthetic-private-server-text"})
            ]
        row = deepcopy(self.suite["head"])
        if mode == "foreign-owner":
            row["user_id"] = self.suite["protocol"]["team_id"]
        if mode == "team-row":
            row["team_id"] = self.suite["protocol"]["team_id"]
        if mode == "direct-row":
            row["chat_visibility"] = "direct"
        if mode == "truncated":
            row["embed_keys_has_more_after"] = True
        if mode == "bad-tag":
            row["content"] = "synthetic-not-ciphertext"
        if mode == "expired-wrapper":
            row["embed_keys"][0]["expires_at"] = 1
        # SessionDraftPeer supplies the single transport envelope around this row.
        return [("send_embed_data", row)]

    def check(self, observed):
        assert self.failure is None
        v, s = self.vector, self.suite
        error = v.get("error")
        if error:
            assert observed == {"ok": False, "error": error}, "typed refusal required"
        else:
            assert set(observed) == {"ok", "value"} and observed["ok"] is True
            url = urlsplit(observed["value"])
            assert (
                url.scheme == "http"
                and url.hostname == "127.0.0.1"
                and url.port is None
            )
            assert not url.username and not url.password and not url.query
            assert url.path == "/share/embed/" + s[
                "embed_id"
            ] and url.fragment.startswith("key=")
            fields = parse_qs(
                unwrap(url.fragment[4:], s["embed_id"], b"openmates-share-v1").decode(),
                strict_parsing=True,
            )
            assert set(fields) == {
                "embed_encryption_key",
                "generated_at",
                "duration_seconds",
                "pwd",
            }
            assert all(len(value) == 1 for value in fields.values())
            assert fields["duration_seconds"] == [str(v["expires"])]
            assert (
                self.started - 1
                <= int(fields["generated_at"][0])
                <= int(time.time()) + 1
            )
            assert fields["pwd"] == ["1" if v["password"] else "0"]
            key = fields["embed_encryption_key"][0]
            if v["password"]:
                key = unwrap(
                    key, v["password"], ("openmates-pwd-" + s["embed_id"]).encode()
                ).decode()
            assert base64.b64decode(key, validate=True).hex() == s["key_hex"]
        early = v.get("mode") in {"noauth", "policy-denied", "team", "paired-expired"}
        assert self.counts["http"] == (0 if early else 2), (
            "original validation and same real socket validation only"
        )
        assert (
            self.counts["ws"]
            == self.counts["lifecycle"]
            == len(self.requests)
            == (0 if early else 1)
        )
        assert self.counts["versions"] == self.counts["phase2"] == 0
