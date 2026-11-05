"""Pure oracle/fixture counterexamples; no peer start or SDK execution."""

# contract-test-file: tooling
import importlib.util
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
# Private source-only overlay retains unchanged independent protocol dependencies.
if "/logs/rust-migration-proposals/" in str(ROOT):
    W = Path(str(ROOT).split("/logs/rust-migration-proposals/", 1)[0])
    sys.path.insert(0, str(W / "tests/sdk-conformance"))
else:
    sys.path.insert(0, str(HERE))
spec = importlib.util.spec_from_file_location(
    "workflow_peer_pure", HERE / "session_workflow_files_peer.py"
)
M = importlib.util.module_from_spec(spec)
spec.loader.exec_module(M)


class PeerContractTests(unittest.TestCase):
    def setUp(self):
        self.raw = (HERE / "fixtures/workflow-file-sync.json").read_bytes()
        self.s = json.loads(self.raw)["capabilities"][M.CAPABILITY]

    def test_complete_mirrored_fixture_and_schema(self):
        import jsonschema

        jsonschema.validate(
            json.loads(self.raw),
            json.loads((HERE / "schemas/workflow-file-sync.schema.json").read_text()),
        )
        self.assertEqual(len({v["id"] for v in self.s["vectors"]}), 23)
        self.assertEqual(
            self.raw,
            (
                ROOT / "packages/openmates-rust/tests/fixtures/workflow-file-sync.json"
            ).read_bytes(),
        )

    def test_constructor_opens_no_listener(self):
        with patch.object(
            M.ThreadingHTTPServer,
            "__init__",
            side_effect=AssertionError("no IO at construction"),
        ):
            peer = M.WorkflowFilesPeer(self.s, self.s["vectors"][0], "rust")
            self.assertIsNone(peer.server)

    def test_self_echo_passed_row_without_actual_metadata_commit_is_rejected(self):
        peer = M.WorkflowFilesPeer(self.s, self.s["vectors"][0], "rust")
        observed = {
            "ok": True,
            "value": [{"project_id": self.s["project_id"], "status": "saved"}],
        }
        peer.saved = {"remote_file_status": "saved"}
        with self.assertRaises(AssertionError):
            peer.check(observed)

    def test_replacement_preserves_absent_final_newline(self):
        self.assertEqual(
            M.replacement("x.workflow.yml", "old", "new\n"),
            "--- a/x.workflow.yml\n+++ b/x.workflow.yml\n@@ -1,1 +1,1 @@\n-old\n\\ No newline at end of file\n+new\n",
        )


if __name__ == "__main__":
    unittest.main()
