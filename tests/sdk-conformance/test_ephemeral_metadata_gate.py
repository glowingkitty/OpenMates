"""Pure receipt/schema checks, not an SDK/runtime or peer-execution proof."""

# contract-test-file: tooling
import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[2]
FILE = ROOT / "tests/sdk-conformance/runners/session-ephemeral-metadata-gate.py"
spec = importlib.util.spec_from_file_location("metadata_gate", FILE)
gate = importlib.util.module_from_spec(spec)
spec.loader.exec_module(gate)


class GateTests(unittest.TestCase):
    def setUp(self):
        self.raw = (ROOT / gate.FIXTURE).read_bytes()
        self.fixture = json.loads(self.raw)
        self.ids = [
            row["id"]
            for row in self.fixture["capabilities"][gate.CAPABILITY]["vectors"]
        ]
        self.lifecycles = {
            row["id"]: row["lifecycle"]
            for row in self.fixture["capabilities"][gate.CAPABILITY]["vectors"]
            if "lifecycle" in row
        }
        self.value = {
            "capability": gate.CAPABILITY,
            "language": "rust",
            "fixtureSha256": gate.FIXTURE_SHA256,
            "status": "passed",
            "results": [{"id": name, "status": "passed"} for name in self.ids],
        }
        for row in self.value["results"]:
            if row["id"] in self.lifecycles:
                row["lifecycle"] = self.lifecycles[row["id"]]["rust"]

    def test_fixture_schema_and_exact_no_key_bytes(self):
        import jsonschema

        jsonschema.Draft202012Validator(
            json.loads(
                (
                    ROOT
                    / "tests/sdk-conformance/schemas/session-ephemeral-metadata.schema.json"
                ).read_bytes()
            )
        ).validate(self.fixture)
        self.assertEqual(hashlib.sha256(self.raw).hexdigest(), gate.FIXTURE_SHA256)
        self.assertEqual(len(set(self.ids)), 29)

    def test_every_vector_and_language_is_mandatory(self):
        gate.validate_observed(self.value, "rust", self.ids, self.lifecycles)
        for mutate in (
            lambda v: v["results"].pop(),
            lambda v: v["results"].reverse(),
            lambda v: v.update(language="npm"),
            lambda v: v.update(status="partial"),
            lambda v: v["results"][0].update(status="skipped"),
            lambda v: v.update(physical_commit=True),
        ):
            value = copy.deepcopy(self.value)
            mutate(value)
            with self.assertRaises(ValueError):
                gate.validate_observed(value, "rust", self.ids, self.lifecycles)
        value = copy.deepcopy(self.value)
        value["results"][-1]["lifecycle"] = "promise-drop-proves-drain"
        with self.assertRaises(ValueError):
            gate.validate_observed(value, "rust", self.ids, self.lifecycles)

    def test_pending_input_has_no_master_or_owner_authority(self):
        suite = self.fixture["capabilities"][gate.CAPABILITY]
        self.assertEqual(set(suite["account"]), {"owner_id", "session_id", "cookie"})
        self.assertEqual(set(gate.COMMANDS), {"rust", "npm", "python"})
        modes = {row["mode"] for row in suite["vectors"]}
        self.assertTrue(
            {
                "owner_dto",
                "api_key",
                "denied",
                "expired",
                "changed_principal",
                "rotation_failure",
                "foreign_snapshot",
                "stale_snapshot",
                "cancel_before",
                "auth_cancel",
                "cancel_inflight",
            }
            <= modes
        )


if __name__ == "__main__":
    unittest.main()
