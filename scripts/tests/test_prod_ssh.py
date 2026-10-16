# contract-test-file: tooling
"""Exercise the real expect handshake with a fake SSH; never contact a server."""

import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest


SCRIPT = Path(__file__).resolve().parents[1] / "prod-ssh.sh"


@unittest.skipUnless(shutil.which("expect"), "expect is required")
class ProdSshTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root / ".git").mkdir()
        (self.root / "key").touch()
        (self.root / ".env").write_text(
            "PROD_SSH_HOST=test.invalid\nPROD_SSH_USER=test\n"
            f"PROD_SSH_KEY='{self.root / 'key'}'\n"
            "PROD_SSH_PASSWORD='dummy-password-$literal'\n"
        )
        bin_dir = self.root / "bin"
        bin_dir.mkdir()
        git = bin_dir / "git"
        git.write_text('#!/bin/sh\nprintf "%s/.git\\n" "$TEST_ROOT"\n')
        git.chmod(0o700)
        ssh = bin_dir / "ssh"
        ssh.write_text(
            "#!/usr/bin/env python3\n"
            "import os, pathlib, sys\n"
            "root = pathlib.Path(os.environ['TEST_ROOT'])\n"
            "if '-O' in sys.argv:\n"
            "    sys.exit(0 if (root / 'active').exists() else 1)\n"
            "scenario = os.environ['TEST_SCENARIO']\n"
            "def prompt(text):\n"
            "    print(text, end='', flush=True)\n"
            "    value = sys.stdin.readline().strip()\n"
            "    with (root / 'submissions').open('a') as f:\n"
            "        f.write(value + '\\n')\n"
            "    return value\n"
            "if scenario in ('success', 'eof', 'repeat_password', 'repeat_otp', 'missing_master'):\n"
            "    assert prompt('Password:') == 'dummy-password-$literal'\n"
            "    if scenario == 'repeat_password':\n"
            "        prompt('Password:')\n"
            "        sys.exit(255)\n"
            "    assert prompt('Verification code:') == '123456'\n"
            "    if scenario == 'repeat_otp':\n"
            "        prompt('TOTP:')\n"
            "        sys.exit(255)\n"
            "    if scenario == 'eof':\n"
            "        print('private failure dummy-password-$literal 123456', flush=True)\n"
            "        sys.exit(255)\n"
            "    if scenario == 'success':\n"
            "        (root / 'active').touch()\n"
            "    sys.exit(0)\n"
            "print(scenario, flush=True)\n"
            "sys.exit(255)\n"
        )
        ssh.chmod(0o700)
        self.env = dict(os.environ, HOME=str(self.root), TEST_ROOT=str(self.root))
        self.env["PATH"] = f"{bin_dir}:{os.environ['PATH']}"

    def run_open(self, scenario):
        result = subprocess.run(
            ["bash", str(SCRIPT), "open"],
            input="123456\n",
            capture_output=True,
            text=True,
            timeout=10,
            env=dict(self.env, TEST_SCENARIO=scenario),
        )
        output = result.stdout + result.stderr
        self.assertNotIn("dummy-password-$literal", output)
        self.assertNotIn("123456", output)
        return result, output

    def test_success_requires_master_check(self):
        result, output = self.run_open("success")
        self.assertEqual(result.returncode, 0, output)
        self.assertIn("Master connection established", output)

    def test_unclassified_eof_reports_exit_and_prompt_count(self):
        result, output = self.run_open("eof")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("SSH exited with status 255 after 2 authentication prompt(s)", output)
        self.assertIn("Master connection was not established", output)
        self.assertNotIn("private failure", output)

    def test_repeated_prompts_do_not_resubmit_credentials(self):
        for scenario, expected_count in (("repeat_password", 1), ("repeat_otp", 2)):
            with self.subTest(scenario=scenario):
                (self.root / "submissions").unlink(missing_ok=True)
                result, output = self.run_open(scenario)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("SSH requested", output)
                lines = (self.root / "submissions").read_text().splitlines()
                self.assertEqual(len(lines), expected_count)

    def test_classified_errors_are_actionable(self):
        for error, expected in (
            ("Permission denied", "SSH denied authentication"),
            ("Host key verification failed", "SSH host-key verification failed"),
            ("Are you sure you want to continue connecting", "SSH needs host-key confirmation"),
            ("Connection refused", "SSH connection refused"),
            ("Could not resolve hostname", "SSH could not resolve"),
            ("Connection timed out", "SSH connection timed out"),
        ):
            with self.subTest(error=error):
                result, output = self.run_open(error)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn(expected, output)

    def test_successful_ssh_exit_without_master_fails(self):
        result, output = self.run_open("missing_master")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Failed to establish master connection", output)


if __name__ == "__main__":
    unittest.main()
