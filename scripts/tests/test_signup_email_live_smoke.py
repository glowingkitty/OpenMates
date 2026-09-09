"""Focused engineering-tooling guards for the live signup email health probe.

No network, product account, CLI session or provider is touched by these units.
Checks isolation, exact evidence correlation and redacted failure boundaries.
Live evidence comes only from the separately authorized scheduled workflow.
See docs/architecture/signup-email-live-smoke.md.
"""
# contract-test-file: tooling

import importlib.util
import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

SPEC = importlib.util.spec_from_file_location("smoke", Path(__file__).parents[1] / "signup_email_live_smoke.py")
smoke = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(smoke)


class LiveEmailGuards(unittest.TestCase):
    def test_daily_health_dispatch_failure_preserves_isolated_ci(self):
        launcher = Path(__file__).parents[1] / "run-tests-daily.sh"
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "scripts").mkdir()
            (root / "scripts/ci_dispatch.py").touch()
            binaries = root / "bin"
            binaries.mkdir()
            commands = {
                "git": '#!/bin/sh\nprintf "%s/.git\\n" "$TEST_ROOT"\n',
                "gh": '#!/bin/sh\nexit 1\n',
                "python3": '#!/bin/sh\nprintf "%s\\n" "$@" > "$TEST_ROOT/isolated-args"\n',
            }
            for name, content in commands.items():
                executable = binaries / name
                executable.write_text(content)
                executable.chmod(0o755)
            env = {**os.environ, "PATH": str(binaries) + os.pathsep + os.environ["PATH"], "TEST_ROOT": str(root)}
            result = subprocess.run(["bash", str(launcher)], env=env, capture_output=True, text=True, timeout=10)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("--daily", (root / "isolated-args").read_text())
            report = smoke.json.loads((root / "logs/nightly-reports/signup-email-live-dispatch.json").read_text())
            self.assertEqual(report, {"dispatch": "failed", "verification": "not_run"})

    def test_alias_isolated_and_invalid_ids_rejected(self):
        self.assertEqual(smoke.make_alias("dedicated+old@example.com", "2026-09-09"), "dedicated+live-signup-2026-09-09@example.com")
        with self.assertRaises(smoke.ProbeError):
            smoke.make_alias("dedicated@example.com", "../unsafe")

    def test_inbox_requires_exact_recipient_freshness_and_template(self):
        message = {"internalDate": "1000000", "payload": {"headers": [
            {"name": "To", "value": "Test <dedicated+run@example.com>"},
            {"name": "Subject", "value": "Confirm your email address - OpenMates"}]}}
        self.assertTrue(smoke.message_matches(message, "dedicated+run@example.com", 1000))
        self.assertFalse(smoke.message_matches(message, "dedicated@example.com", 1000))
        self.assertFalse(smoke.message_matches(message, "dedicated+run@example.com", 2000))
        message["payload"]["headers"][1]["value"] = "Account already exists"
        self.assertFalse(smoke.message_matches(message, "dedicated+run@example.com", 1000))

    def test_provider_requires_correlated_request_receipt(self):
        event = {"email": "test@example.com", "event": "requests", "messageId": "receipt", "date": "1970-01-01T00:16:40Z"}
        self.assertTrue(smoke.acceptance_matches(event, "test@example.com", 1000))
        self.assertFalse(smoke.acceptance_matches(event, "other@example.com", 1000))
        self.assertFalse(smoke.acceptance_matches(event, "test@example.com", 2000))
        event["messageId"] = "unknown"
        self.assertFalse(smoke.acceptance_matches(event, "test@example.com", 1000))

    def test_missing_configuration_does_not_send(self):
        with patch.dict(smoke.os.environ, {}, clear=True), patch.object(smoke, "request_json") as request:
            report = {}
            smoke.run_probe("run", Path("unused"), report)
            request.assert_not_called()
            self.assertIn("missing:", report["configuration"])

    def test_duplicate_receipt_prevents_signup(self):
        env = {name: "configured" for name in smoke.GMAIL_SETTINGS}
        env["GMAIL_TEST_ADDRESS"] = "dedicated@example.com"
        with tempfile.TemporaryDirectory() as directory, patch.dict(smoke.os.environ, env, clear=True), patch.object(smoke, "request_json", side_effect=[{"access_token": "private"}, {}]) as request:
            receipt = Path(directory) / "receipt"
            receipt.touch()
            with self.assertRaisesRegex(smoke.ProbeError, "duplicate_send_prevented"):
                smoke.run_probe("run", receipt, {})
            self.assertEqual(request.call_count, 2)

    def test_inbox_arrival_without_provider_observation_is_not_pass(self):
        env = {name: "configured" for name in smoke.GMAIL_SETTINGS}
        env["GMAIL_TEST_ADDRESS"] = "dedicated@example.com"
        message = {"internalDate": "1000000", "payload": {"headers": [
            {"name": "To", "value": "dedicated+live-signup-run@example.com"},
            {"name": "Subject", "value": smoke.SUBJECT}]}}
        responses = [{"access_token": "private"}, {}, {"success": True}, {"messages": [{"id": "one"}]}, message]
        with tempfile.TemporaryDirectory() as directory, patch.dict(smoke.os.environ, env, clear=True), patch.object(smoke.time, "time", return_value=1000), patch.object(smoke, "request_json", side_effect=responses):
            report = {}
            smoke.run_probe("run", Path(directory) / "receipt", report)
            self.assertEqual(report["inbox_arrival"], "observed")
            self.assertEqual(report["provider_acceptance"], "unavailable_missing_event_credentials")
            self.assertFalse(report["passed"])

    def test_provider_acceptance_with_inbox_timeout_is_not_pass(self):
        env = {name: "configured" for name in smoke.GMAIL_SETTINGS}
        env.update(GMAIL_TEST_ADDRESS="dedicated@example.com", BREVO_API_KEY="private")
        event = {"email": "dedicated+live-signup-run@example.com", "event": "requests", "messageId": "receipt", "date": "1970-01-01T00:16:40Z"}
        responses = [{"access_token": "private"}, {}, {"success": True}, {"events": [event]}, {}]
        with tempfile.TemporaryDirectory() as directory, patch.dict(smoke.os.environ, env, clear=True), patch.object(smoke.time, "time", return_value=1000), patch.object(smoke.time, "monotonic", side_effect=[0, 0, 121]), patch.object(smoke.time, "sleep"), patch.object(smoke, "request_json", side_effect=responses):
            report = {}
            smoke.run_probe("run", Path(directory) / "receipt", report)
            self.assertEqual(report["provider_acceptance"], "observed")
            self.assertEqual(report["inbox_arrival"], "timeout")
            self.assertFalse(report["passed"])

    def test_http_error_redacts_private_url_and_body(self):
        error = smoke.HTTPError("https://example.com/private-recipient", 401, "private token", {}, None)
        with patch.object(smoke, "urlopen", side_effect=error):
            with self.assertRaisesRegex(smoke.ProbeError, "^http_401$"):
                smoke.request_json("https://example.com")


if __name__ == "__main__":
    unittest.main()
