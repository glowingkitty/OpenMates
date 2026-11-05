# contract-test-file: tooling
"""Pure validation of the independent, source-derived native JSON contract.

This does not execute Rust, a product backend, account, packaging or benchmark.
"""

from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
import unittest

from jsonschema import Draft202012Validator

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"


class ChatsShowJsonContract(unittest.TestCase):
    def setUp(self):
        self.suite = json.loads((FIXTURES / "chats-show-json.json").read_text())
        self.schema = json.loads((FIXTURES / "chats-show-json.schema.json").read_text())
        Draft202012Validator.check_schema(self.schema)
        self.validator = Draft202012Validator(self.schema)

    # contract-test: supporting surface=cli assertions=cli.surface.semantic-parity
    def test_every_complete_source_derived_vector_matches_schema(self):
        for vector in self.suite["vectors"]:
            with self.subTest(vector=vector["id"]):
                self.validator.validate(vector["expected"])
                output, work = vector["expected"], vector["expected_work"]
                self.assertEqual(len(output["messages"]), work["messages_returned"])
                self.assertEqual(
                    "--all" in vector["flags"], work["full_history_fetch_allowed"]
                )
                self.assertEqual(
                    "has_more_before" in output, "--all" not in vector["flags"]
                )
                self.assertNotIn("messages", output["chat"])

    # contract-test: supporting surface=cli assertions=cli.surface.semantic-parity
    def test_default_requests_thirty_once_but_current_server_returns_twenty_with_exact_fields(
        self,
    ):
        vectors = {v["id"]: v["expected"] for v in self.suite["vectors"]}
        full, latest = (
            vectors["explicit-all-65"],
            vectors["default-request-30-single-window"],
        )
        self.assertEqual(len(full["messages"]), 65)
        self.assertEqual(len(latest["messages"]), 20)
        for vector in self.suite["vectors"]:
            if "--all" not in vector["flags"]:
                self.assertEqual(vector["expected_work"]["requested_limit"], 30)
                self.assertEqual(vector["expected_work"]["window_request_count"], 1)
                self.assertTrue(vector["expected_work"]["respect_compression_boundary"])
        self.assertEqual(latest["messages"], full["messages"][-20:])
        self.assertEqual(latest, vectors["json-raw-request-30-single-window"])
        self.assertEqual(
            latest["follow_up_suggestions"],
            ["Explore the saved result", "Continue with 雪"],
        )
        self.assertIn("[OM_PII_", latest["messages"][-2]["content"])
        self.assertEqual(
            latest["messages"][-2]["piiMappings"][0]["original"], "Synthetic Alice"
        )
        self.assertNotIn("piiMappings", latest["messages"][0])
        self.assertEqual(latest["messages"][-1]["piiMappings"], [])

    # contract-test: supporting surface=cli assertions=cli.surface.semantic-parity
    def test_pii_mapping_presence_retains_any_valid_source_json_parse_result(self):
        complete = self.suite["vectors"][0]["expected"]
        for mappings in [
            None,
            {},
            {"synthetic": "value"},
            42,
            "scalar",
            True,
            [],
            "\ud83d",
            {"lone": "\ud800"},
        ]:
            with self.subTest(mappings=mappings):
                output = deepcopy(complete)
                output["messages"][0]["piiMappings"] = mappings
                self.validator.validate(output)
                self.assertIn("piiMappings", output["messages"][0])
        output = deepcopy(complete)
        output["messages"][0].pop("piiMappings", None)
        self.validator.validate(output)
        self.assertNotIn("piiMappings", output["messages"][0])

    # contract-test: supporting surface=cli assertions=cli.surface.semantic-parity
    def test_active_focus_is_optional_nonempty_and_whitespace_is_not_trimmed(self):
        old = self.suite["vectors"][:4]
        for vector in old:
            self.assertNotIn("activeFocusId", vector["expected"]["chat"])
        for focus in ("synthetic-focus-雪", "   "):
            value = deepcopy(old[0]["expected"])
            value["chat"]["activeFocusId"] = focus
            self.validator.validate(value)
            self.assertEqual(value["chat"]["activeFocusId"], focus)
        for focus in (None, "", 0, False, [], {}):
            value = deepcopy(old[0]["expected"])
            value["chat"]["activeFocusId"] = focus
            self.assertTrue(list(self.validator.iter_errors(value)))

    # contract-test: supporting surface=cli assertions=cli.surface.semantic-parity
    def test_partial_legacy_shape_or_dropped_rich_fields_cannot_satisfy_contract(self):
        complete = self.suite["vectors"][0]["expected"]
        for location, key in [
            ("chat", key) for key in self.schema["properties"]["chat"]["required"]
        ]:
            value = deepcopy(complete)
            del value[location][key]
            self.assertTrue(list(self.validator.iter_errors(value)), key)
        for key in self.schema["properties"]["messages"]["items"]["required"]:
            value = deepcopy(complete)
            del value["messages"][0][key]
            self.assertTrue(list(self.validator.iter_errors(value)), key)
        legacy = {"id": complete["chat"]["id"], "title": "Synthetic", "messages": []}
        self.assertTrue(list(self.validator.iter_errors(legacy)))
        value = deepcopy(complete)
        value["chat"]["messages"] = value["messages"]
        self.assertTrue(list(self.validator.iter_errors(value)))


if __name__ == "__main__":
    unittest.main()
