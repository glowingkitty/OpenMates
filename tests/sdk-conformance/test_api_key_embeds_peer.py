"""Pure offline oracle checks. No account, product endpoint or dependency installs."""

# contract-test-file: tooling
import json
from pathlib import Path
import unittest
from api_key_embeds_peer import EmbedsPeer


class EmbedsPeerTests(unittest.TestCase):
    def setUp(self):
        self.suite = json.loads(
            (Path(__file__).parent / "fixtures/sdk-api-key-embeds.json").read_text()
        )["capabilities"]["sdk.embeds"]
        self.vector = self.suite["vectors"][0]

    def headers(self, language):
        return {
            "Authorization": "Bearer sk-api-embedOwnerA",
            "X-OpenMates-Device-Identity": self.suite["device_id"],
            "X-OpenMates-SDK": {"rust": "rust", "npm": "npm", "python": "pip"}[
                language
            ],
        }

    def test_all_language_identities_preserve_complete_opaque_response(self):
        for language in ("rust", "npm", "python"):
            peer = EmbedsPeer(self.suite, self.vector, language)
            self.assertEqual(
                peer.dispatch(
                    "GET", "/v1/sdk/embeds/embed-a", self.headers(language), None
                ),
                (200, self.vector["response"]),
            )
            self.assertIsNone(peer.failure)

    def test_owner_suffix_ambient_auth_scope_mutation_and_retry_refusals(self):
        for language in ("rust", "npm", "python"):
            headers = self.headers(language)
            cases = [
                ("POST", "/v1/sdk/embeds/embed-a", headers, {}),
                (
                    "GET",
                    "/v1/sdk/embeds/embed-a",
                    {**headers, "Authorization": "Bearer sk-api-embedOwnerB"},
                    None,
                ),
                ("GET", "/v1/sdk/embeds/embed-a?team_id=x", headers, None),
                (
                    "GET",
                    "/v1/sdk/embeds/embed-a",
                    {
                        **headers,
                        "Authorization": "Bearer sk-api-embedOwnerA.localSetupSuffix",
                    },
                    None,
                ),
                (
                    "GET",
                    "/v1/sdk/embeds/embed-a",
                    {**headers, "Cookie": "session=ambient"},
                    None,
                ),
                ("POST", "/v1/sdk/session", headers, {}),
            ]
            for case in cases:
                peer = EmbedsPeer(self.suite, self.vector, language)
                self.assertEqual(peer.dispatch(*case)[0], 400)
                self.assertIsNotNone(peer.failure)
            peer = EmbedsPeer(self.suite, self.vector, language)
            peer.dispatch("GET", "/v1/sdk/embeds/embed-a", headers, None)
            self.assertEqual(
                peer.dispatch("GET", "/v1/sdk/embeds/embed-a", headers, None)[0], 400
            )


if __name__ == "__main__":
    unittest.main()
