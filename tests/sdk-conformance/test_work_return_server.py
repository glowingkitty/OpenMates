"""Pure encrypted request-oracle regressions; no sockets, SDKs or subprocesses."""

# contract-test-file: tooling
import base64
import hashlib
import json
from pathlib import Path
import unittest

from recovery_server import decrypt
from work_return_server import FAMILIES, WorkReturnPeer


class ReturnPeerTests(unittest.TestCase):
    def headers(self, peer, index=0):
        return {
            "Cookie": f"auth_refresh_token={peer.accounts[index]['cookie']}",
            "X-OpenMates-SDK": "rust",
        }

    def read(self, peer, headers):
        route = FAMILIES[peer.family]
        if peer.family == "tasks":
            route += "?limit=500&paginate=true"
        return peer.dispatch("GET", route, headers, None)

    def marker(self, family, row, master):
        if family == "workflows":
            self.assertEqual(row["enabled"], False)
            self.assertEqual(row["graph"]["nodes"], [])
            return decrypt(row["encrypted_slug"], master).decode()
        field = {"tasks": "task", "projects": "project", "plans": "plan"}[family]
        wrapped = (
            row["key_wrappers"][0]["encrypted_plan_key"]
            if family == "plans"
            else row[f"encrypted_{field}_key"]
        )
        key = decrypt(wrapped, master)
        return decrypt(
            row["encrypted_name" if family == "projects" else "encrypted_title"], key
        ).decode()

    def test_distinct_identity_reads_use_new_owner_and_key_all_four_families(self):
        for family in FAMILIES:
            with self.subTest(family=family):
                peer = WorkReturnPeer(family, "rust")
                old, new = peer.accounts
                self.assertNotEqual(old["owner"], new["owner"])
                self.assertNotEqual(old["key"], new["key"])
                self.assertNotEqual(old["session"], new["session"])
                self.assertEqual(self.read(peer, self.headers(peer))[0], 200)
                row = self.read(peer, self.headers(peer))[1][family][0]
                self.assertEqual(self.marker(family, row, old["key"]), old["marker"])
                self.assertNotIn(
                    old["marker"], json.dumps(row)
                ) if family != "workflows" else None
                self.assertEqual(
                    peer.dispatch("POST", "/__test/control", {}, {"op": "replace"}),
                    (200, {"replaced": True}),
                )
                status, auth = peer.dispatch(
                    "POST",
                    "/v1/auth/session",
                    self.headers(peer, 1),
                    {"session_id": new["session"]},
                )
                self.assertEqual(status, 200)
                self.assertEqual(auth["user"]["id"], new["owner"])
                status, body = self.read(peer, self.headers(peer, 1))
                self.assertEqual(status, 200)
                row = body[family][0]
                self.assertEqual(self.marker(family, row, new["key"]), new["marker"])
                self.assertNotIn(old["marker"], json.dumps(row))
                with self.assertRaises(Exception):
                    self.marker(family, row, old["key"])
                if family != "workflows":
                    self.assertEqual(
                        row["hashed_user_id"],
                        hashlib.sha256(new["owner"].encode()).hexdigest(),
                    )
                self.assertEqual(peer.status()["failure"], None)
                self.assertEqual(peer.status()["replacements"], 1)

    def test_old_cookie_foreign_identity_bearer_and_nonpersonal_routes_refused(self):
        for fault in ("old-cookie", "identity", "bearer", "team", "wrong-family"):
            peer = WorkReturnPeer("tasks", "rust")
            peer.dispatch("POST", "/__test/control", {}, {"op": "replace"})
            headers = self.headers(peer, 1)
            route = "/v1/user-tasks?limit=500&paginate=true"
            if fault == "old-cookie":
                headers = self.headers(peer)
            elif fault == "identity":
                headers["X-OpenMates-SDK"] = "npm"
            elif fault == "bearer":
                headers["Authorization"] = "Bearer synthetic"
            elif fault == "team":
                route += "&team_id=synthetic"
            else:
                route = "/v1/projects"
            self.assertEqual(peer.dispatch("GET", route, headers, None)[0], 500)
            self.assertEqual(peer.status()["reads"], 0)
            self.assertEqual(peer.status()["failure"], "work-return-protocol-assertion")

    def test_exact_logout_and_explicit_same_account_reimport(self):
        peer = WorkReturnPeer("projects", "rust")
        headers = self.headers(peer)
        self.assertEqual(
            peer.dispatch("POST", "/v1/auth/logout", headers, {}),
            (200, {"success": True}),
        )
        self.assertEqual(peer.status()["logouts"], 1)
        self.assertEqual(
            peer.dispatch(
                "POST",
                "/v1/auth/session",
                headers,
                {"session_id": peer.accounts[0]["session"]},
            )[0],
            200,
        )
        self.assertEqual(self.read(peer, headers)[0], 200)
        for method, body in (("GET", None), ("POST", {"extra": True})):
            bad = WorkReturnPeer("projects", "rust")
            self.assertEqual(
                bad.dispatch(method, "/v1/auth/logout", headers, body)[0], 500
            )
            self.assertEqual(bad.status()["logouts"], 0)

    def test_ready_sessions_are_explicit_and_status_is_sanitized(self):
        peer = WorkReturnPeer("tasks", "rust")
        for index in (0, 1):
            state = peer.session(index, "http://127.0.0.1:12345")
            self.assertEqual(
                base64.b64decode(state["master_key"]), peer.accounts[index]["key"]
            )
            self.assertEqual(state["active_team_id"], None)
            self.assertEqual(state["api_url"], "http://127.0.0.1:12345")
        public = json.dumps(peer.status())
        for account in peer.accounts:
            for value in (
                account["owner"],
                account["session"],
                account["cookie"],
                account["marker"],
            ):
                self.assertNotIn(value, public)
        # No original public work fixture/peer replacement or changes required.
        self.assertTrue((Path(__file__).parent / "session_work_server.py").is_file())


if __name__ == "__main__":
    unittest.main()
