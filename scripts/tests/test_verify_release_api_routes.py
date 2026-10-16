# contract-test-file: tooling
"""Release registration gates distinguish a missing route from runtime health."""

import importlib.util
from pathlib import Path
import json
import subprocess
import sys
import tempfile
import unittest


spec = importlib.util.spec_from_file_location(
    "release_routes", Path(__file__).resolve().parents[1] / "verify_release_api_routes.py"
)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class ReleaseRouteTests(unittest.TestCase):
    def test_healthy_api_with_old_schema_blocks_new_frontend_dependency(self):
        schema = {"paths": {"/health": {"get": {}}}}
        required = [("POST", "/v1/auth/password-v2/challenge")]
        self.assertEqual(module.missing_routes(schema, required), required)

    def test_path_with_wrong_method_does_not_satisfy_dependency(self):
        path = "/v1/auth/password-v2/challenge"
        self.assertEqual(module.missing_routes({"paths": {path: {"get": {}}}}, [("POST", path)]), [("POST", path)])
        self.assertEqual(module.missing_routes({"paths": {path: {"post": {}}}}, [("POST", path)]), [])

    def test_invalid_schema_cannot_be_treated_as_ready(self):
        with self.assertRaises(ValueError):
            module.missing_routes({}, [("POST", "/required")])

    def test_operator_snapshot_cli_blocks_old_or_unreadable_live_schema(self):
        with tempfile.TemporaryDirectory() as directory:
            snapshot = Path(directory) / "live.json"
            command = [sys.executable, str(Path(module.__file__)), "--schema-file",
                       str(snapshot), "--require", "POST", "/required"]
            snapshot.write_text(json.dumps({"paths": {"/health": {"get": {}}}}))
            self.assertEqual(subprocess.run(command, capture_output=True).returncode, 1)
            snapshot.write_text("invalid JSON")
            result = subprocess.run(command, capture_output=True, text=True)
            self.assertEqual(result.returncode, 1)
            self.assertNotIn("invalid JSON", result.stderr)
            snapshot.write_text(json.dumps({"paths": {"/required": {"post": {}}}}))
            self.assertEqual(subprocess.run(command, capture_output=True).returncode, 0)


if __name__ == "__main__":
    unittest.main()
