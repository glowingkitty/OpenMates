"""Independent synthetic embed family protocol/crypto oracle; never product IO."""

# contract-test-file: tooling
from copy import deepcopy
import base64
import hashlib
import json
import time
from urllib.parse import urlsplit, parse_qs
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

CAPABILITY = "sdk.embeds.family"


class EmbedsFamilyPeer:
    def __init__(self, suite, vector, language):
        self.suite, self.vector, self.language = suite, vector, language
        self.requests = 0
        self.failure = None

    def sequence(self):
        v = self.vector
        op = v["operation"]
        e = v["embed_id"]
        p = v["project_id"]
        session = v["session_id"]
        if op == "restore_version":
            return (
                []
                if not v.get("confirmed")
                else [("POST", f"/v1/sdk/embeds/{e}/versions/{v['version']}/restore")]
            )
        if op == "preview_start":
            return [("POST", f"/v1/applications/{e}/preview/start")] + (
                [("GET", f"/v1/applications/preview/{session}")]
                if v.get("wait") and not v.get("local_timeout")
                else []
            )
        if op.startswith("preview_"):
            return [
                (
                    "GET" if op == "preview_status" else "POST",
                    f"/v1/applications/preview/{session}"
                    + (
                        ""
                        if op == "preview_status"
                        else "/" + op.removeprefix("preview_")
                    ),
                )
            ]
        if op == "share":
            return [("GET", f"/v1/sdk/embeds/{e}"), ("POST", "/v1/sdk/session")]
        if op == "add_to_project":
            first = (
                [("POST", "/v1/sdk/session"), ("GET", f"/v1/projects/{p}")]
                if self.language == "npm"
                else [("GET", f"/v1/projects/{p}"), ("POST", "/v1/sdk/session")]
            )
            return first + [("POST", f"/v1/projects/{p}/items")]
        if op == "remove_from_project":
            return [("DELETE", f"/v1/projects/{p}/items?item_type=embed&target_id={e}")]
        raise AssertionError("unknown family operation")

    def dispatch(self, method, path, headers, body):
        index = self.requests
        self.requests += 1
        try:
            v = self.vector
            h = {k.lower(): v for k, v in headers.items()}
            setup = self.suite["api_keys"][v["owner"]]
            assert h.get("authorization") == "Bearer " + setup.split(".", 1)[0], (
                "explicit owner bearer"
            )
            assert h.get("x-openmates-device-identity") == self.suite["device_id"]
            assert (
                h.get("x-openmates-sdk")
                == {"rust": "rust", "npm": "npm", "python": "pip"}[self.language]
            )
            assert not set(h).intersection(
                {
                    "cookie",
                    "x-session-id",
                    "x-openmates-anonymous-id",
                    "x-openmates-task-owner",
                    "x-openmates-task-actor",
                }
            ), "ambient or alternate authority"
            assert setup.split(".", 1)[1] not in json.dumps([h, path, body]), (
                "setup suffix leak"
            )
            seq = self.sequence()
            assert index < len(seq) and (method, path) == seq[index], (
                "exact routes/order/no replay"
            )
            if path == "/v1/sdk/session":
                assert body == {
                    "sdk_name": {"rust": "rust", "npm": "npm", "python": "pip"}[
                        self.language
                    ],
                    "device_identity": self.suite["device_id"],
                }
                return 200, self.suite["session"]
            if v["operation"] == "share":
                assert body is None
                shown = deepcopy(self.suite["shown"])
                if v.get("wrong_hash"):
                    shown["embed_keys"][0]["hashed_embed_id"] = "mismatched-embed-hash"
                return 200, shown
            if v["operation"] == "add_to_project" and method == "GET":
                assert body is None
                return 200, self.suite["project"]
            if v["operation"] == "add_to_project":
                assert set(body) == {
                    "project_item_id",
                    "folder_id",
                    "item_type",
                    "target_id",
                    "target_id_encrypted",
                    "encrypted_display_name",
                    "encrypted_note",
                    "encrypted_metadata",
                    "created_at",
                    "updated_at",
                    "position",
                }
                assert (
                    body["item_type"] == "embed"
                    and body["target_id"] == v["embed_id"]
                    and body["folder_id"] == v.get("folder")
                )
                import uuid

                assert (
                    str(uuid.UUID(body["project_item_id"])) == body["project_item_id"]
                )
                assert (
                    body["created_at"] == body["updated_at"] == body["position"]
                    and abs(body["created_at"] - time.time()) < 60
                )
                key = base64.b64decode(self.suite["project_key_base64"])

                def decrypt(field):
                    raw = base64.b64decode(body[field])
                    assert raw[:2] == b"OM", "canonical encrypted text envelope"
                    fingerprint = 0x811C9DC5
                    for byte in key:
                        fingerprint = ((fingerprint ^ byte) * 0x01000193) & 0xFFFFFFFF
                    assert raw[2:6] == fingerprint.to_bytes(4, "big"), (
                        "key fingerprint binding"
                    )
                    return AESGCM(key).decrypt(raw[6:18], raw[18:], None).decode()

                assert (
                    decrypt("target_id_encrypted") == v["embed_id"]
                    and decrypt("encrypted_display_name") == v["embed_id"]
                    and decrypt("encrypted_note") == ""
                )
                assert json.loads(decrypt("encrypted_metadata")) == {
                    "storage": "save_only_in_openmates",
                    "source": "sdk_add_to_project",
                }
                return 200, {"item": v["response"]}
            if v["operation"] == "preview_start" and index == 0:
                assert body == {
                    "chat_id": v["chat_id"],
                    **{k: value for k, value in v.get("options", {}).items() if value},
                }, "exact preview context"
                return v["status"], (
                    {"session_id": v["session_id"], "status": "starting"}
                    if v.get("wait")
                    else v["response"]
                )
            expected_body = {} if method == "POST" else None
            if v["operation"] == "restore_version" and self.language == "npm":
                expected_body = None
            assert body == expected_body, (
                "exact maintained empty-body semantics/no hidden fields"
            )
            return v["status"], v["response"]
        except Exception as error:
            self.failure = type(error).__name__ + ": " + str(error)
            return 400, {"detail": "synthetic embed family refusal"}

    def check(self, observed):
        assert self.failure is None, self.failure
        assert self.requests == len(self.sequence()), "missing/replayed requests"
        v = self.vector
        if v["expected_error"]:
            assert (
                observed["ok"] is False and observed["error"] == v["expected_error"]
            ), "typed refusal"
            if v.get("local_timeout"):
                assert (
                    observed["timeout_source"] == "local"
                    and observed["semantic_status"] == 408
                    and observed["http_observed"] is False
                ), "local deadline provenance, not server evidence"
        elif v["operation"] == "share":
            assert observed["ok"] is True
            url = urlsplit(observed["value"]["url"])
            assert (
                url.scheme == "http"
                and url.hostname == "127.0.0.1"
                and url.port is None
                and url.path == "/share/embed/" + v["embed_id"]
                and not url.query
            )
            assert url.fragment.startswith("key=")

            def decrypt(blob, key):
                raw = base64.urlsafe_b64decode(blob + "=" * (-len(blob) % 4))
                return AESGCM(key).decrypt(raw[:12], raw[12:], None).decode()

            derived = hashlib.pbkdf2_hmac(
                "sha256", v["embed_id"].encode(), b"openmates-share-v1", 100000, 32
            )
            data = parse_qs(decrypt(url.fragment[4:], derived), keep_blank_values=True)
            assert set(data) == {
                "embed_encryption_key",
                "generated_at",
                "duration_seconds",
                "pwd",
            }
            assert (
                data["duration_seconds"] == [str(v["expires"])]
                and abs(int(data["generated_at"][0]) - time.time()) < 60
            )
            actual = data["embed_encryption_key"][0]
            if v["password"]:
                derived = hashlib.pbkdf2_hmac(
                    "sha256",
                    v["password"].encode(),
                    ("openmates-pwd-" + v["embed_id"]).encode(),
                    100000,
                    32,
                )
                actual = decrypt(actual, derived)
            assert (
                data["pwd"] == ["1" if v["password"] else "0"]
                and actual == self.suite["embed_key_base64"]
            ), "exact share crypto format"
        else:
            assert observed == {"ok": True, "value": v["response"]}, (
                "complete family output"
            )

    def server(self):
        peer = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *_args):
                pass

            def handle_request(self):
                self.connection.settimeout(2)
                try:
                    length = int(self.headers.get("Content-Length", "0"))
                    assert 0 <= length <= 65536
                    raw = self.rfile.read(length)
                    body = json.loads(raw) if raw else None
                    status, response = peer.dispatch(
                        self.command, self.path, dict(self.headers), body
                    )
                except Exception:
                    peer.failure = "invalid bounded JSON request"
                    status, response = (
                        400,
                        {"detail": "synthetic embeds protocol refusal"},
                    )
                data = json.dumps(
                    response, separators=(",", ":"), ensure_ascii=False
                ).encode()
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.send_header("Connection", "close")
                self.end_headers()
                self.wfile.write(data)

            do_GET = handle_request
            do_POST = handle_request
            do_PATCH = handle_request
            do_DELETE = handle_request

        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        server.daemon_threads = True
        server.block_on_close = False
        return server
