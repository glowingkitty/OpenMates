"""Pure oracle and explicit real Python SDK offline fixtures; all network forbidden."""

# contract-test-file: tooling
import importlib.util
import json
import os
import sys
import unittest
from pathlib import Path
from urllib.parse import urlencode, urlsplit
from unittest.mock import patch

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location(
    "wiki_oracle", HERE / "api_key_wikipedia_peer.py"
)
M = importlib.util.module_from_spec(spec)
spec.loader.exec_module(M)
SUITE = json.loads((HERE / "fixtures/sdk-api-key-wikipedia.json").read_text())[
    "capabilities"
]["sdk.wikipedia"]


def headers(language="rust"):
    return {
        "Authorization": "Bearer " + SUITE["api_key"].split(".")[0],
        "X-OpenMates-Device-Identity": SUITE["device_id"],
        "X-OpenMates-SDK": {"rust": "rust", "npm": "npm", "python": "pip"}[language],
    }


def path(v, step, lang="rust"):
    language = v["language"] if v["language"] is not None else "en"
    if lang == "python":
        language = v.get("python_expected_language", language)
    q = {"language": language}
    if step["operation"] == "search":
        q["query"] = v["query"]
        if v["limit"] is not None:
            q["limit"] = v["limit"]
    else:
        q["title"] = step["expected_title"]
    return "/v1/wikipedia/" + step["operation"] + "?" + urlencode(q)


class WikipediaOracleTests(unittest.TestCase):
    def test_all_vectors_exact_order_query_headers_and_no_override(self):
        for language in ("rust", "npm", "python"):
            for v in SUITE["vectors"]:
                peer = M.WikipediaPeer(SUITE, v, language)
                for s in v["steps"]:
                    with self.subTest(language=language, vector=v["id"]):
                        self.assertEqual(
                            peer.dispatch(
                                "GET", path(v, s, language), headers(language), None
                            ),
                            (s["http_status"], s["response"]),
                        )
                        self.assertIsNone(peer.failure)
                self.assertEqual(peer.requests, v["expected_request_count"])

    def test_wrong_order_model_provider_cookie_and_setup_suffix_are_rejected(self):
        v = next(
            v
            for v in SUITE["vectors"]
            if v["operation"] == "article" and len(v["steps"]) == 2
        )
        for route in (
            path(v, v["steps"][1]),
            path(v, v["steps"][0]) + "&model=forced",
            path(v, v["steps"][0]) + "&provider=forced",
            "https://example.invalid" + path(v, v["steps"][0]),
        ):
            peer = M.WikipediaPeer(SUITE, v, "rust")
            self.assertEqual(peer.dispatch("GET", route, headers(), None)[0], 400)
        for addition in (
            {"Cookie": "private"},
            {"Authorization": SUITE["api_key"]},
            {"X-OpenMates-Anonymous-ID": "wrong"},
            {"X-OpenMates-Task-Owner": "wrong"},
        ):
            peer = M.WikipediaPeer(SUITE, v, "rust")
            self.assertEqual(
                peer.dispatch(
                    "GET", path(v, v["steps"][0]), {**headers(), **addition}, None
                )[0],
                400,
            )

    def test_no_retries_or_extra_learning(self):
        v = next(
            v
            for v in SUITE["vectors"]
            if v["id"] == "article-summary-failure-does-not-request-learning"
        )
        peer = M.WikipediaPeer(SUITE, v, "rust")
        peer.dispatch("GET", path(v, v["steps"][0]), headers(), None)
        self.assertEqual(
            peer.dispatch("GET", path(v, v["steps"][0]), headers(), None)[0], 400
        )

    def test_fixture_schema_and_known_language_divergence(self):
        import jsonschema

        doc = json.loads((HERE / "fixtures/sdk-api-key-wikipedia.json").read_text())
        schema = json.loads(
            (HERE / "schemas/sdk-api-key-wikipedia-fixture.schema.json").read_text()
        )
        jsonschema.Draft202012Validator.check_schema(schema)
        jsonschema.Draft202012Validator(schema).validate(doc)
        self.assertEqual(len({v["id"] for v in SUITE["vectors"]}), 27)
        v = next(
            v for v in SUITE["vectors"] if v["id"] == "search-empty-language-divergence"
        )
        self.assertNotEqual(
            path(v, v["steps"][0], "rust"), path(v, v["steps"][0], "python")
        )


class PythonSdkOfflineTests(unittest.TestCase):
    def test_actual_direct_python_sdk_27_vectors_no_sockets_or_session_bootstrap(self):
        root = Path(
            os.environ.get("OPENMATES_SDK_TEST_SOURCE_ROOT", str(HERE.parents[1]))
        ).resolve()
        assert (root / "packages/openmates-python/openmates/sdk.py").is_file()
        sys.path.insert(0, str(root / "packages/openmates-python"))
        from openmates import OpenMates, OpenMatesApiError, OpenMatesConfigError

        class Response:
            def __init__(self, status, value):
                self.status_code, self.value = status, value

            def json(self):
                return self.value

        total = 0
        for v in SUITE["vectors"]:
            with self.subTest(vector=v["id"]):
                peer = M.WikipediaPeer(SUITE, v, "python")

                def get(url, **kw):
                    nonlocal total
                    u = urlsplit(url)
                    self.assertEqual(u.scheme, "http")
                    self.assertEqual(u.netloc, "127.0.0.1:1")
                    total += 1
                    status, value = peer.dispatch(
                        "GET",
                        u.path + ("?" + u.query if u.query else ""),
                        kw["headers"],
                        None,
                    )
                    return Response(status, value)

                with (
                    patch("openmates.sdk.requests.get", get),
                    patch(
                        "openmates.sdk.requests.post",
                        side_effect=AssertionError("no session or inference POST"),
                    ),
                    patch(
                        "openmates.sdk.requests.request",
                        side_effect=AssertionError("unexpected transport"),
                    ),
                    patch(
                        "socket.socket", side_effect=AssertionError("network forbidden")
                    ),
                ):
                    client = OpenMates(
                        api_key=None if v["anonymous"] else SUITE["api_key"],
                        anonymous=v["anonymous"],
                        api_url="http://127.0.0.1:1",
                        device_id=SUITE["device_id"],
                    )
                    try:
                        options = {"language": v["language"]}
                        if v["operation"] == "search":
                            value = client.wikipedia.search(
                                v["query"], limit=v["limit"], **options
                            )
                        elif v["operation"] == "summary":
                            value = client.wikipedia.summary(v["title"], **options)
                        elif v["operation"] == "learning":
                            value = client.wikipedia.learning(v["title"], **options)
                        else:
                            value = client.wikipedia.article(v["title"], **options)
                        self.assertIsNone(v["expected_error"])
                        self.assertEqual(value, v["expected"])
                    except OpenMatesConfigError:
                        self.assertTrue(v["anonymous"])
                        self.assertEqual(v["expected_error"], "authentication")
                    except OpenMatesApiError as e:
                        n = e.status_code
                        code = {
                            401: "authentication",
                            403: "forbidden",
                            409: "conflict",
                        }.get(n) or (
                            "invalid"
                            if n in (400, 404, 410, 422)
                            else "offline"
                            if n == 429 or n >= 500
                            else "protocol"
                        )
                        self.assertEqual(code, v["expected_error"])
                self.assertIsNone(peer.failure)
                self.assertEqual(peer.requests, v["expected_request_count"])
        self.assertEqual(total, 29)


if __name__ == "__main__":
    unittest.main(verbosity=2)
