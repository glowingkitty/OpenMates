"""Offline family protocol invariants and local-deadline evidence distinction."""

# contract-test-file: tooling
import json
from pathlib import Path
import unittest
from api_key_embeds_family_peer import EmbedsFamilyPeer


class FamilyPeerTests(unittest.TestCase):
    def setUp(self):
        self.suite = json.loads(
            (
                Path(__file__).parent / "fixtures/sdk-api-key-embeds-family.json"
            ).read_text()
        )["capabilities"]["sdk.embeds.family"]

    def vector(self, id):
        return next(v for v in self.suite["vectors"] if v["id"] == id)

    def test_local_deadline_has_semantic408_without_received_http_evidence(self):
        for lang in ("rust", "npm", "python"):
            peer = EmbedsFamilyPeer(
                self.suite, self.vector("preview-local-deadline"), lang
            )
            self.assertEqual(len(peer.sequence()), 1)
            peer.requests = 1
            correct = {
                "ok": False,
                "error": "preview-timeout",
                "timeout_source": "local",
                "semantic_status": 408,
                "http_observed": False,
            }
            peer.check(correct)
            for patch in (
                {"http_observed": True},
                {"timeout_source": "http"},
                {"semantic_status": 504},
            ):
                with self.assertRaises(AssertionError):
                    peer.check({**correct, **patch})

    def test_confirmation_refusal_and_exact_mutation_bodies(self):
        for lang in ("rust", "npm", "python"):
            peer = EmbedsFamilyPeer(
                self.suite, self.vector("restore-unconfirmed"), lang
            )
            self.assertEqual(peer.sequence(), [])
            peer.check({"ok": False, "error": "invalid"})
            peer = EmbedsFamilyPeer(self.suite, self.vector("restore-confirmed"), lang)
            headers = {
                "authorization": "Bearer sk-api-embedOwnerA",
                "x-openmates-sdk": {"rust": "rust", "npm": "npm", "python": "pip"}[
                    lang
                ],
                "x-openmates-device-identity": self.suite["device_id"],
            }
            method, path = peer.sequence()[0]
            body = None if lang == "npm" else {}
            self.assertEqual(peer.dispatch(method, path, headers, body)[0], 200)
            self.assertEqual(peer.dispatch(method, path, headers, body)[0], 400)

    def test_cookie_and_team_override_are_never_credentials(self):
        for lang in ("rust", "npm", "python"):
            for cookie, query in ((True, False), (False, True)):
                peer = EmbedsFamilyPeer(self.suite, self.vector("preview-status"), lang)
                headers = {
                    "authorization": "Bearer sk-api-embedOwnerA",
                    "x-openmates-sdk": {"rust": "rust", "npm": "npm", "python": "pip"}[
                        lang
                    ],
                    "x-openmates-device-identity": self.suite["device_id"],
                }
                if cookie:
                    headers["cookie"] = "ambient=wrong"
                method, path = peer.sequence()[0]
                self.assertEqual(
                    peer.dispatch(
                        method,
                        path + ("?team_id=alternate" if query else ""),
                        headers,
                        None,
                    )[0],
                    400,
                )


if __name__ == "__main__":
    unittest.main()
