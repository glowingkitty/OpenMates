# contract-test-file: tooling
"""Verify daily statistics against real history in disposable Git repositories."""

import json
import os
import subprocess
import sys
import tempfile
import unittest
from datetime import date
from pathlib import Path
from zoneinfo import ZoneInfo

from scripts import git_daily_stats as stats


class DailyStatsTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.repo = Path(self.temporary.name)
        self.git("init", "-b", "dev")
        self.git("config", "user.name", "Fixture")
        self.git("config", "user.email", "fixture@example.invalid")
        self.git("config", "commit.gpgsign", "false")

    def git(self, *args, stamp=None):
        env = os.environ.copy()
        if stamp:
            env.update(GIT_COMMITTER_DATE=stamp, GIT_AUTHOR_DATE="2000-01-01T00:00:00Z")
        return subprocess.check_output(["git", "-C", str(self.repo), *args], env=env, stderr=subprocess.PIPE).decode().strip()

    def commit(self, stamp, files):
        for name, contents in files.items():
            (self.repo / name).write_bytes(contents.encode() if isinstance(contents, str) else contents)
        self.git("add", "--all")
        self.git("commit", "--allow-empty", "-m", "fixture", stamp=stamp)
        return self.git("rev-parse", "HEAD")

    def report(self, end="2026-09-25", days=2, scope="code", ref="HEAD"):
        return stats.collect_daily(self.repo, ref, days, date.fromisoformat(end), ZoneInfo("Europe/Berlin"), scope)

    def test_boundaries_committer_dates_scopes_zero_days_and_binary(self):
        self.commit("2026-09-23T21:59:59Z", {"source.py": "one\ntwo\n"})
        self.commit("2026-09-23T22:00:00Z", {"source.py": "one\nthree\nfour\n", "README.md": "docs\n", "binary.py": b"\x00binary"})
        self.commit("2026-09-24T22:00:00Z", {"source.py": "one\nthree\n"})
        self.commit("2026-09-25T22:00:00Z", {"outside.py": "excluded\n"})
        report = self.report(days=3)
        self.assertEqual([row["date"] for row in report["days"]], ["2026-09-23", "2026-09-24", "2026-09-25"])
        self.assertEqual([(row["added"], row["deleted"]) for row in report["days"]], [(2, 0), (2, 1), (0, 1)])
        self.assertEqual(report["totals"], {"commits": 3, "added": 4, "deleted": 2, "churn": 6, "net": 2, "binary_file_changes": 1})
        self.assertEqual(self.report(scope="all")["totals"]["added"], 3)
        empty = self.report(end="2026-10-01", days=2)
        self.assertEqual(len(empty["days"]), 2)
        self.assertEqual(empty["totals"], stats.empty_counts())

    def test_renames_and_unusual_filenames(self):
        old, new = "old\tfile.py", "new\nfile.py"
        self.commit("2026-09-23T22:00:00Z", {old: "one\ntwo\nthree\n"})
        self.git("mv", "--", old, new)
        self.commit("2026-09-24T12:00:00Z", {new: "one\ntwo\nthree\nfour\n"})
        self.git("mv", "--", new, "renamed.py")
        self.commit("2026-09-24T13:00:00Z", {})
        self.assertEqual(self.report()["totals"]["added"], 4)
        self.assertEqual(self.report()["totals"]["deleted"], 0)

    def test_merge_changes_are_counted_once(self):
        self.commit("2026-09-23T20:00:00Z", {"base.py": "base\n"})
        self.git("checkout", "-b", "fixture-side")
        self.commit("2026-09-23T22:00:00Z", {"side.py": "side\n"})
        self.git("checkout", "dev")
        self.commit("2026-09-24T00:00:00Z", {"main.py": "main\n"})
        self.git("merge", "--no-ff", "-m", "merge fixture", "fixture-side", stamp="2026-09-24T22:00:00Z")
        report = self.report()
        self.assertEqual(report["totals"]["commits"], 2)
        self.assertEqual([(row["added"], row["deleted"]) for row in report["days"]], [(1, 0), (1, 0)])

    def test_docs_only_commits_and_renames_across_the_code_scope(self):
        self.commit("2026-09-23T22:00:00Z", {"source.py": "one\ntwo\nthree\n"})
        self.commit("2026-09-24T12:00:00Z", {"README.md": "docs\n"})
        self.git("mv", "--", "source.py", "source.md")
        self.commit("2026-09-24T13:00:00Z", {})
        self.git("mv", "--", "source.md", "SOURCE.PY")
        self.commit("2026-09-25T00:00:00Z", {})
        totals = self.report()["totals"]
        self.assertEqual(totals["commits"], 4)
        self.assertEqual((totals["added"], totals["deleted"], totals["net"]), (6, 3, 3))

    def test_non_monotonic_timestamps_do_not_hide_recent_ancestors(self):
        self.commit("2026-09-24T00:00:00Z", {"first.py": "first\n"})
        self.commit("2026-09-22T00:00:00Z", {"old.py": "old\n"})
        self.commit("2026-09-25T00:00:00Z", {"last.py": "last\n"})
        self.assertEqual(self.report()["totals"]["added"], 2)
        self.assertEqual(self.report()["totals"]["commits"], 2)

    def test_dst_day_has_25_hours(self):
        self.commit("2026-10-24T21:59:59Z", {"before.py": "before\n"})
        self.commit("2026-10-24T22:00:00Z", {"first.py": "first\n"})
        self.commit("2026-10-25T22:59:59Z", {"last.py": "last\n"})
        self.commit("2026-10-25T23:00:00Z", {"after.py": "after\n"})
        self.assertEqual(self.report(end="2026-10-25", days=1)["totals"]["added"], 2)

    def test_cli_json_is_repeatable_and_validates_inputs(self):
        revision = self.commit("2026-09-24T00:00:00Z", {"source.py": "source\n"})
        command = [sys.executable, str(Path(stats.__file__)), "--repo", str(self.repo), "--ref", revision, "--end-date", "2026-09-25", "--days", "2", "--json"]
        first = subprocess.check_output(command)
        self.assertEqual(first, subprocess.check_output(command))
        self.assertEqual(json.loads(first)["revision"], revision)
        self.commit("2026-09-25T00:00:00Z", {"source.py": "new\ncontent\n"})
        self.assertEqual(first, subprocess.check_output(command))
        for extra in [("--days", "0"), ("--timezone", "invalid/timezone"), ("--end-date", "invalid"), ("--ref", "--invalid")]:
            result = subprocess.run([*command, *extra], capture_output=True)
            self.assertEqual(result.returncode, 2)
            self.assertNotIn(b"Traceback", result.stderr)

    def test_shallow_history_is_rejected(self):
        self.commit("2026-09-24T00:00:00Z", {"source.py": "source\n"})
        shallow = self.repo / "shallow"
        self.git("clone", "--depth", "1", self.repo.as_uri(), str(shallow))
        with self.assertRaisesRegex(ValueError, "shallow"):
            stats.collect_daily(shallow, "HEAD", 2, date(2026, 9, 25), ZoneInfo("Europe/Berlin"), "code")


if __name__ == "__main__":
    unittest.main()
