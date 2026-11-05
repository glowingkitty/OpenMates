"""Independent closed synthetic version-content protocol. No listener on import."""

from copy import deepcopy
import json
from api_key_embeds_family_peer import EmbedsFamilyPeer

CAPABILITY = "sdk.embeds.version-content"


class VersionContentPeer:
    server = EmbedsFamilyPeer.server

    def __init__(self, suite, vector, language):
        assert language in ("rust", "npm", "python", "cli")
        self.suite, self.vector, self.language = suite, vector, language
        self.requests = 0
        self.failure = None

    def sequence(self):
        v = self.vector
        e = v["embed_id"]
        response = v["response"]
        seq = [("GET", f"/v1/sdk/embeds/{e}/versions/{v['version']}")]
        rows = response.get("rows")
        invalid = (
            v["http_status"] >= 400
            or response.get("embed_id") != e
            or response.get("version_number") != v["version"]
            or isinstance(response.get("content"), str)
            or not isinstance(rows, list)
            or not 1 <= len(rows) <= 10000
            or rows[-1].get("version_number") != v["version"]
            or any(
                type(row.get("version_number")) is not int
                or not 1 <= row["version_number"] <= v["version"]
                for row in rows
            )
        )
        if invalid:
            return seq
        seq.append(("GET", f"/v1/sdk/embeds/{e}"))
        shown = v["shown"] or self.suite["shown"]
        if shown["embed"].get("embed_id") != e:
            return seq
        return seq + [("POST", "/v1/sdk/session")]

    def dispatch(self, method, path, headers, body):
        index = self.requests
        self.requests += 1
        try:
            s = self.suite
            v = self.vector
            h = {k.lower(): value for k, value in headers.items()}
            setup = s["api_key"]
            assert (method, path) == self.sequence()[index], (
                "exact route/order/no retry"
            )
            assert h.get("authorization") == "Bearer " + setup.split(".", 1)[0]
            assert (
                h.get("x-openmates-sdk")
                == {"rust": "rust", "npm": "npm", "python": "pip", "cli": "cli"}[
                    self.language
                ]
            )
            assert h.get("x-openmates-device-identity") == s["device_id"]
            assert not set(h).intersection(
                {
                    "cookie",
                    "x-session-id",
                    "x-openmates-anonymous-id",
                    "x-openmates-task-owner",
                    "x-openmates-task-actor",
                }
            )
            assert setup.split(".", 1)[1] not in json.dumps([h, path, body]), (
                "setup suffix stays local"
            )
            if path == "/v1/sdk/session":
                assert body == {
                    "sdk_name": h["x-openmates-sdk"],
                    "device_identity": s["device_id"],
                }
                return 200, deepcopy(v["session"] or s["session"])
            assert body is None
            if path.endswith("/versions/" + str(v["version"])):
                return v["http_status"], deepcopy(v["response"])
            return 200, deepcopy(v["shown"] or s["shown"])
        except Exception:
            self.failure = "version-content protocol refused"
            return 400, {"detail": "synthetic version refusal"}

    def check(self, observed):
        assert self.failure is None and self.requests == len(self.sequence())
        v = self.vector
        assert observed == (
            {"ok": False, "error": v["expected_error"]}
            if v["expected_error"]
            else {"ok": True, "value": v["expected"]}
        )
