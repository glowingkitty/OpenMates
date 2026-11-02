"""Closed synthetic Cookie version peer. No listener on construction/import."""

from copy import deepcopy
from urllib.parse import urlsplit, parse_qs
from session_drafts_server import SessionDraftPeer

CAPABILITY = "session.embeds.version-content.v1"


class CookieVersionPeer(SessionDraftPeer):
    def __init__(self, suite, vector, identity):
        super().__init__(suite, vector, identity)
        self.embed_requests = []
        self.version_gets = 0

    def http(self, method, path, headers, body):
        self.headers(headers)
        self.counts["http"] += 1
        v = self.vector
        s = self.suite
        if method == "POST":
            assert path == "/v1/auth/session" and body == {
                "session_id": s["account"]["session_id"]
            }
            return 200, {
                "success": True,
                "ws_token": "synthetic-drafts-ws",
                "user": {"id": s["account"]["owner_id"]},
            }
        route = urlsplit(path)
        assert method == "GET" and body is None
        assert route.path == f"/v1/embeds/{v['embed_id']}/versions/{v['version']}"
        self.version_gets += 1
        query = parse_qs(route.query)
        assert query == (
            {"capability": ["bounded-v1"]} if self.version_gets == 1 else {}
        ), "boundedthenexactlegacyonly"
        if v["fallback409"] and self.version_gets == 1:
            return 409, {"detail": "synthetic legacy-only"}
        assert self.version_gets == (2 if v["fallback409"] else 1)
        return v["status"], deepcopy(
            v["response"] if v["status"] == 200 else {"detail": "synthetic refusal"}
        )

    def event(self, kind, payload):
        if kind == "native_client_lifecycle":
            assert (
                payload["client_type"] == self.identity
                and payload["interactive"] is False
            )
            self.counts["lifecycle"] += 1
            return []
        assert kind == "request_embed" and set(payload) == {"embed_id"}, (
            "noAI/jobs/sync/mutation"
        )
        embed = payload["embed_id"]
        assert embed in self.vector["heads"]
        assert embed not in self.embed_requests and len(self.embed_requests) < 8
        self.embed_requests.append(embed)
        return [
            (
                "send_embed_data",
                {"embed_id": embed, "payload": deepcopy(self.vector["heads"][embed])},
            )
        ]

    def check(self, observed):
        v = self.vector
        assert self.failure is None
        assert observed == (
            {"ok": False, "error": v["error"]}
            if v["error"]
            else {"ok": True, "value": v["expected"]}
        )
        early = (
            v["mode"] in ("noauth", "policy-denied", "team")
            or type(v["version"]) is not int
            or v["version"] < 1
            or len(v["embed_id"]) != 36
        )
        response = v["response"]
        invalid_response = (
            response.get("embed_id") != v["embed_id"]
            or response.get("version_number") != v["version"]
            or (
                not isinstance(response.get("content"), str)
                and (
                    not isinstance(response.get("rows"), list)
                    or response["rows"][-1]["version_number"] != v["version"]
                    or any(r["version_number"] > v["version"] for r in response["rows"])
                )
            )
        )
        encrypted = (
            not early
            and v["status"] == 200
            and not invalid_response
            and not isinstance(response.get("content"), str)
        )
        assert self.counts["http"] == (
            0 if early else 2 + int(v["fallback409"]) + int(encrypted)
        )
        assert self.counts["ws"] == int(encrypted) and self.counts["lifecycle"] == int(
            encrypted
        )
        assert len(self.embed_requests) == (len(v["heads"]) if encrypted else 0)
        assert self.counts["versions"] == self.counts["phase2"] == 0
