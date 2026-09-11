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
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

SPEC = importlib.util.spec_from_file_location("smoke", Path(__file__).parents[1] / "signup_email_live_smoke.py")
smoke = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(smoke)


class CliProcessGuard(unittest.TestCase):
    def test_stops_at_code_prompt_and_removes_isolated_state(self):
        # Synthetic executable exercises process control only; no product API.
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            executable = root / "node_modules/openmates/cli"
            executable.parent.mkdir(parents=True)
            executable.write_text(f"#!{sys.executable}\nimport time\nprint('Email verification code: ', end='', flush=True)\ntime.sleep(30)\n")
            executable.chmod(0o755)
            installed = root / ".npm-global/bin/openmates"
            installed.parent.mkdir(parents=True)
            installed.symlink_to(executable)
            with patch.object(smoke.Path, "home", return_value=root), patch.object(smoke.subprocess, "Popen", wraps=subprocess.Popen) as launch:
                smoke.request_with_cli("dedicated@example.com", "unit")
            environment = launch.call_args.kwargs["env"]
            self.assertFalse(Path(environment["OPENMATES_STATE_DIR"]).exists())
            self.assertNotIn("OPENMATES_CLI_SIGNUP_EMAIL_CODE", environment)
            self.assertIn(smoke.API_URL, launch.call_args.args[0])


class LiveEmailGuards(unittest.TestCase):
    def setUp(self):
        host = patch.object(smoke.socket, "gethostname", return_value=smoke.DEV_HOSTNAME)
        host.start()
        self.addCleanup(host.stop)
        cli = patch.object(smoke, "request_with_cli")
        self.cli = cli.start()
        self.addCleanup(cli.stop)

    def test_github_is_rejected_before_any_probe(self):
        with patch.dict(smoke.os.environ, {"GITHUB_ACTIONS": "true"}):
            with self.assertRaisesRegex(smoke.ProbeError, "dev_host_only"):
                smoke.run_probe("run", Path("unused"), {})

    def test_signup_environment_cannot_reuse_engineering_login_or_code(self):
        with patch.dict(smoke.os.environ, {"OPENMATES_API_KEY": "private", "OPENMATES_PROFILE": "engineering", "OPENMATES_CLI_SIGNUP_EMAIL_CODE": "123456"}):
            env = smoke.cli_environment(Path("/tmp/isolated-unit-state"))
            self.assertEqual(env["OPENMATES_STATE_DIR"], "/tmp/isolated-unit-state")
            self.assertNotIn("OPENMATES_API_KEY", env)
            self.assertNotIn("OPENMATES_PROFILE", env)
            self.assertNotIn("OPENMATES_CLI_SIGNUP_EMAIL_CODE", env)

    def test_current_signup_subject_is_accepted(self):
        # email.this_is_your_email_code is the subject; the template heading differs.
        message = {"internalDate": "1000000", "payload": {"headers": [
            {"name": "To", "value": "dedicated+run@example.com"},
            {"name": "Subject", "value": "Your code: 123456"}]}}
        self.assertTrue(smoke.message_matches(message, "dedicated+run@example.com", 1000))

    def test_daily_local_health_failure_preserves_isolated_ci(self):
        launcher = Path(__file__).parents[1] / "run-tests-daily.sh"
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "scripts").mkdir()
            (root / "scripts/ci_dispatch.py").touch()
            binaries = root / "bin"
            binaries.mkdir()
            commands = {
                "git": '#!/bin/sh\nprintf "%s/.git\\n" "$TEST_ROOT"\n',
                "gh": '#!/bin/sh\nexit 99\n',
                "python3": '#!/bin/sh\ncase "$1" in *signup_email_live_smoke.py) exit 1;; esac\nprintf "%s\\n" "$@" > "$TEST_ROOT/isolated-args"\n',
            }
            for name, content in commands.items():
                executable = binaries / name
                executable.write_text(content)
                executable.chmod(0o755)
            env = {**os.environ, "PATH": str(binaries) + os.pathsep + os.environ["PATH"], "TEST_ROOT": str(root)}
            result = subprocess.run(["bash", str(launcher)], env=env, capture_output=True, text=True, timeout=10)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("--daily", (root / "isolated-args").read_text())
            self.assertIn("Dev-host signup email health failed", result.stderr)

    def test_alias_isolated_and_invalid_ids_rejected(self):
        self.assertEqual(smoke.make_alias("dedicated+old@example.com", "2026-09-09"), "dedicated+live-signup-2026-09-09@example.com")
        with self.assertRaises(smoke.ProbeError):
            smoke.make_alias("dedicated@example.com", "../unsafe")

    def test_inbox_requires_exact_recipient_freshness_and_template(self):
        message = {"internalDate": "1000000", "payload": {"headers": [
            {"name": "To", "value": "Test <dedicated+run@example.com>"},
            {"name": "Subject", "value": "Your code: 123456"}]}}
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

    def test_inbox_arrival_without_provider_observation_passes(self):
        env = {name: "configured" for name in smoke.GMAIL_SETTINGS}
        env["GMAIL_TEST_ADDRESS"] = "dedicated@example.com"
        message = {"internalDate": "1000000", "payload": {"headers": [
            {"name": "To", "value": "dedicated+live-signup-run@example.com"},
            {"name": "Subject", "value": "Your code: 123456"}]}}
        responses = [{"access_token": "private"}, {}, {"messages": [{"id": "one"}]}, message]
        with tempfile.TemporaryDirectory() as directory, patch.dict(smoke.os.environ, env, clear=True), patch.object(smoke.time, "time", return_value=1000), patch.object(smoke, "request_json", side_effect=responses):
            report = {}
            smoke.run_probe("run", Path(directory) / "receipt", report)
            self.assertEqual(report["inbox_arrival"], "observed")
            self.assertEqual(report["provider_acceptance"], "unavailable_missing_event_credentials")
            self.assertTrue(report["passed"])

    def test_read_only_observation_never_requests_signup(self):
        env = {name: "configured" for name in smoke.GMAIL_SETTINGS}
        env["GMAIL_TEST_ADDRESS"] = "dedicated@example.com"
        message = {"internalDate": "1001000", "payload": {"headers": [
            {"name": "To", "value": "dedicated+live-signup-run@example.com"},
            {"name": "Subject", "value": "Your code: 123456"}]}}
        responses = [{"access_token": "private"}, {}, {"messages": [{"id": "one"}]}, message]
        with tempfile.TemporaryDirectory() as directory, patch.dict(smoke.os.environ, env, clear=True), patch.object(smoke.time, "time", return_value=2000), patch.object(smoke, "request_json", side_effect=responses) as request:
            receipt = Path(directory) / "receipt"
            report = {}
            smoke.run_probe("run", receipt, report, observe_since=1000)
            self.assertTrue(report["passed"])
            self.assertFalse(receipt.exists())
            self.assertFalse(any(smoke.API_URL in call.args[0] for call in request.call_args_list))

    def test_provider_acceptance_with_inbox_timeout_is_not_pass(self):
        env = {name: "configured" for name in smoke.GMAIL_SETTINGS}
        env.update(GMAIL_TEST_ADDRESS="dedicated@example.com", BREVO_API_KEY="private")
        event = {"email": "dedicated+live-signup-run@example.com", "event": "requests", "messageId": "receipt", "date": "1970-01-01T00:16:40Z"}
        responses = [{"access_token": "private"}, {}, {"events": [event]}, {}]
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
