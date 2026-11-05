"""Pure startup receipt/admission controls; no actual SDK worker is executed."""

# contract-test-file: tooling
from pathlib import Path
import copy
import importlib.util
import json
import unittest

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location(
    "fixed_startup_gate",
    ROOT / "tests/sdk-conformance/runners/session-initial-startup-sync-gate.py",
)
GATE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(GATE)


class StartupGateTests(unittest.TestCase):
    def setUp(self):
        self.fixture = ROOT / GATE.FIXTURE
        self.ids = [
            row["id"]
            for row in json.loads(self.fixture.read_bytes())["capabilities"][
                GATE.CAPABILITY
            ]["vectors"]
        ]
        self.receipt = {
            "capability": GATE.CAPABILITY,
            "language": "rust",
            "fixtureSha256": GATE.FIXTURE_SHA256,
            "status": "passed",
            "results": [{"id": identity, "status": "passed"} for identity in self.ids],
        }

    def test_exact_actual_receipt_is_preserved_and_mutations_refuse(self):
        self.assertIs(
            GATE.validate_observed(self.receipt, "rust", self.ids), self.receipt
        )
        for mode in [
            "missing",
            "duplicate",
            "reordered",
            "failed",
            "aggregate",
            "hash",
            "language",
            "capability",
            "extra",
        ]:
            value = copy.deepcopy(self.receipt)
            if mode == "missing":
                value["results"].pop()
            elif mode == "duplicate":
                value["results"][-1] = value["results"][0]
            elif mode == "reordered":
                value["results"].reverse()
            elif mode == "failed":
                value["results"][0]["status"] = "failed"
            elif mode == "aggregate":
                del value["results"]
            elif mode == "hash":
                value["fixtureSha256"] = "0" * 64
            elif mode == "language":
                value["language"] = "python"
            elif mode == "capability":
                value["capability"] = "other"
            else:
                value["rawTrace"] = "not-admissible"
            with self.subTest(mode=mode), self.assertRaises(ValueError):
                GATE.validate_observed(value, "rust", self.ids)

    def test_fixed_fixture_and_capability_cannot_select_another_command(self):
        for fixture, capability, language in [
            (self.fixture, "other", "rust"),
            (self.fixture, GATE.CAPABILITY, "other"),
            (ROOT / "unknown-fixture", GATE.CAPABILITY, "rust"),
        ]:
            with self.assertRaises(ValueError):
                GATE.execute(fixture, capability, language, ROOT)
        self.assertEqual(GATE.fixture_bytes(self.fixture), self.fixture.read_bytes())

    def test_actual_runner_must_exit_successfully_and_owner_must_remain_live(self):
        original = GATE.utility
        calls = []

        class Utility:
            status = 0
            document = staticmethod(json.loads)

            def run_owned(self, command, root, **kwargs):
                calls.append((command, root, kwargs))
                return self.status, json.dumps(self_outer.receipt).encode()

        self_outer = self
        GATE.utility = lambda root: Utility()
        try:
            self.assertEqual(
                GATE.execute(self.fixture, GATE.CAPABILITY, "rust", ROOT), self.receipt
            )
            self.assertEqual(
                calls[0][0],
                [
                    *GATE.COMMANDS["rust"],
                    "--fixture",
                    str(self.fixture),
                    "--capability",
                    GATE.CAPABILITY,
                ],
            )
            self.assertEqual(calls[0][1], ROOT)
            self.assertTrue(callable(calls[0][2]["cancelled"]))
            Utility.status = 7
            with self.assertRaises(ValueError):
                GATE.execute(self.fixture, GATE.CAPABILITY, "rust", ROOT)
            Utility.status = 0
            GATE.OWNER_CANCELLED = True
            with self.assertRaises(ValueError):
                GATE.execute(self.fixture, GATE.CAPABILITY, "rust", ROOT)
        finally:
            GATE.utility = original
            GATE.OWNER_CANCELLED = False


if __name__ == "__main__":
    unittest.main()
