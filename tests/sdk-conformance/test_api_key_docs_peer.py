"""Pure oracle controls: no sockets, SDK imports, subprocesses or account IO."""

# contract-test-file: tooling
import importlib.util
import json
import unittest
from pathlib import Path
from urllib.parse import quote, urlencode

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location(
    "docs_oracle", HERE / "api_key_docs_peer.py"
)
M = importlib.util.module_from_spec(spec)
spec.loader.exec_module(M)
SUITE = json.loads((HERE / "fixtures/sdk-api-key-docs.json").read_text())[
    "capabilities"
]["sdk.docs"]


def headers(language="rust"):
    return {
        "Authorization": "Bearer " + SUITE["api_key"].split(".")[0],
        "X-OpenMates-Device-Identity": SUITE["device_id"],
        "X-OpenMates-SDK": {"rust": "rust", "npm": "npm", "python": "pip"}[language],
    }


def path(v):
    if v["operation"] == "list":
        return "/v1/sdk/docs"
    if v["operation"] == "search":
        return "/v1/sdk/docs/search?" + urlencode({"q": v["query"]})
    return (
        "/v1/sdk/docs/"
        + quote(v["slug"], safe="")
        + ("/download" if v["operation"] == "download" else "")
    )


class DocsOracleTests(unittest.TestCase):
    def test_all_common_vectors_wire_shape_and_opaque_output(self):
        for language in ("rust", "npm", "python"):
            for v in SUITE["vectors"]:
                if v["anonymous"]:
                    continue
                with self.subTest(language=language, vector=v["id"]):
                    peer = M.DocsPeer(SUITE, v, language)
                    self.assertEqual(
                        peer.dispatch("GET", path(v), headers(language), None),
                        (v["http_status"], v["response"]),
                    )
                    self.assertIsNone(peer.failure)
                    self.assertEqual(peer.requests, 1)

    def test_owner_cookie_suffix_task_and_public_fallback_are_rejected(self):
        v = SUITE["vectors"][0]
        for change in (
            {"Authorization": "Bearer other"},
            {"Cookie": "session=private"},
            {"X-OpenMates-Anonymous-ID": "other"},
            {"X-OpenMates-Task-Owner": "other"},
            {"Authorization": SUITE["api_key"]},
            {"X-OpenMates-SDK": "cli"},
        ):
            peer = M.DocsPeer(SUITE, v, "rust")
            self.assertEqual(
                peer.dispatch("GET", path(v), {**headers(), **change}, None)[0], 400
            )
            self.assertIsNotNone(peer.failure)
        for route in (
            "/v1/docs",
            "/v1/sdk/session",
            "https://example.invalid/v1/sdk/docs",
            "/v1/sdk/docs?team_id=other",
        ):
            peer = M.DocsPeer(SUITE, v, "rust")
            self.assertEqual(peer.dispatch("GET", route, headers(), None)[0], 400)

    def test_retry_and_anonymous_transport_are_rejected(self):
        v = SUITE["vectors"][0]
        peer = M.DocsPeer(SUITE, v, "rust")
        peer.dispatch("GET", path(v), headers(), None)
        self.assertEqual(peer.dispatch("GET", path(v), headers(), None)[0], 400)
        v = next(v for v in SUITE["vectors"] if v["anonymous"])
        peer = M.DocsPeer(SUITE, v, "rust")
        self.assertEqual(peer.dispatch("GET", path(v), headers(), None)[0], 400)

    def test_single_encoded_slug_and_exact_query(self):
        v = next(v for v in SUITE["vectors"] if v["id"] == "show-slash-space")
        for route in (
            "/v1/sdk/docs/guide/first%20page",
            "/v1/sdk/docs/guide%2Ffirst%20page?extra=1",
        ):
            peer = M.DocsPeer(SUITE, v, "rust")
            self.assertEqual(peer.dispatch("GET", route, headers(), None)[0], 400)
        v = next(v for v in SUITE["vectors"] if v["id"] == "search-empty-query")
        peer = M.DocsPeer(SUITE, v, "rust")
        self.assertEqual(
            peer.dispatch("GET", "/v1/sdk/docs/search", headers(), None)[0], 400
        )

    def test_fixture_schema_and_ids(self):
        import jsonschema

        document = json.loads((HERE / "fixtures/sdk-api-key-docs.json").read_text())
        schema = json.loads(
            (HERE / "schemas/sdk-api-key-docs-fixture.schema.json").read_text()
        )
        jsonschema.Draft202012Validator.check_schema(schema)
        jsonschema.Draft202012Validator(schema).validate(document)
        self.assertEqual(len({v["id"] for v in SUITE["vectors"]}), 23)
        self.assertEqual(
            {v["operation"] for v in SUITE["vectors"]},
            {"list", "search", "show", "download"},
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)
