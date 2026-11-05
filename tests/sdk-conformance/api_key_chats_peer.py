"""Independent synthetic API-key chat read peer. No listener on import.

The peer serves only the routes a vector declares, in order, plus at most one
lazy `/v1/sdk/session` exchange, and checks the credential boundary on every
request: bearer component only, SDK name, device identity, no cookie/session.
"""

from copy import deepcopy
import json
from urllib.parse import parse_qsl, urlsplit

from api_key_embeds_family_peer import EmbedsFamilyPeer

CAPABILITY = "sdk.chats"
SDK_HEADER = {"rust": "rust", "npm": "npm", "python": "pip"}


class ChatsPeer:
    server = EmbedsFamilyPeer.server

    def __init__(self, suite, vector, language):
        assert language in SDK_HEADER
        self.suite, self.vector, self.language = suite, vector, language
        self.routes = 0
        self.sessions = 0
        self.failure = None

    def _route(self, method, raw_path):
        split = urlsplit(raw_path)
        route = self.vector["routes"][self.routes]
        assert (method, split.path) == (route["method"], route["path"]), "exact route/order/no retry"
        query = dict(parse_qsl(split.query, keep_blank_values=True))
        if "query" in route:
            # npm omits an unset offset; the server default is 0.
            query.setdefault("offset", "0")
            assert query == route["query"], "exact pagination"
        else:
            assert not split.query
        self.routes += 1
        return route["status"], deepcopy(route["response"])

    def dispatch(self, method, path, headers, body):
        try:
            s = self.suite
            h = {k.lower(): value for k, value in headers.items()}
            bearer, suffix = s["api_key"].split(".", 1)
            assert h.get("authorization") == "Bearer " + bearer
            assert h.get("x-openmates-sdk") == SDK_HEADER[self.language]
            assert h.get("x-openmates-device-identity") == s["device_id"]
            assert not set(h).intersection({"cookie", "x-session-id", "x-openmates-anonymous-id"})
            assert suffix not in json.dumps([h, path, body]), "setup suffix stays local"
            if urlsplit(path).path == "/v1/sdk/session":
                assert method == "POST" and self.vector["session"] and self.sessions == 0
                assert body == {"sdk_name": SDK_HEADER[self.language], "device_identity": s["device_id"]}
                self.sessions += 1
                return 200, deepcopy(s["session"])
            assert body is None
            return self._route(method, path)
        except Exception:
            self.failure = self.failure or "chat protocol refused"
            return 400, {"detail": "synthetic chat refusal"}

    def check(self, observed):
        v = self.vector
        assert self.failure is None, self.failure
        assert self.routes == len(v["routes"]), "every declared route served"
        assert self.sessions == (1 if v["session"] else 0), "single lazy key session"
        if v["expected_error"]:
            assert observed == {"ok": False, "error": v["expected_error"]}, observed
        else:
            assert observed.get("ok") is True, observed
            assert project(v["operation"], observed["value"]) == v["expected"]


def _chat(row):
    return {key: row.get(key) for key in ("id", "title", "chat_summary", "category", "slug")}


def project(operation, value):
    """Language-neutral view; field names shared by all three SDK outputs."""
    if operation in ("list", "search"):
        return [_chat(row) for row in value]
    embeds = value.get("embeds")
    return {
        "chat": _chat(value["chat"]),
        "messages": [
            {key: message.get(key) for key in ("message_id", "role", "content", "category")}
            for message in value.get("messages", [])
        ],
        "embeds": None
        if embeds is None
        else [{key: embed.get(key) for key in ("embed_id", "type", "content")} for embed in embeds],
    }
