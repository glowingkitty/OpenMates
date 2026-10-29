"""Pure probe admission/output tests: no runtime or kernel collection."""

# contract-test-file: tooling
import os
from pathlib import Path
import unittest
from unittest.mock import patch
from scripts import ci_client_memory_probe as probe
from scripts.ci_client_container_launch import Refused


class Probe(unittest.TestCase):
    def value(self, mode):
        return {
            "fixture": mode,
            "unit": "KiB",
            "rootThreadGroupPeakRssKiB": 1234,
            "wholeFixturePeakRssKiB": None if mode == "child" else 1234,
            "rssScope": "root-only-child-aggregate-unavailable"
            if mode == "child"
            else "one-known-thread-group",
            "acceptanceEligible": False,
        }

    def test_all_fixed_modes_have_exact_rss_scope(self):
        for mode in probe.MODES:
            probe.verify_fixture(mode, self.value(mode))

    def test_child_root_hwm_cannot_become_total(self):
        value = self.value("child")
        value["wholeFixturePeakRssKiB"] = 1234
        with self.assertRaises(Refused):
            probe.verify_fixture("child", value)

    def test_unknown_units_or_zero_are_not_measurements(self):
        for field, bad in [
            ("unit", "B"),
            ("rootThreadGroupPeakRssKiB", 0),
            ("acceptanceEligible", True),
        ]:
            value = self.value("leaf")
            value[field] = bad
            with self.assertRaises(Refused):
                probe.verify_fixture("leaf", value)

    def test_runner_refusal_precedes_all_context_and_process_work(self):
        with (
            patch(
                "ci_environment.require_runner", side_effect=RuntimeError("real guard")
            ) as guard,
            patch.object(Path, "read_text") as read,
            patch.object(probe.subprocess, "check_output") as run,
        ):
            with self.assertRaisesRegex(RuntimeError, "real guard"):
                probe.run("/unused")
            guard.assert_called_once()
            read.assert_not_called()
            run.assert_not_called()

    def test_nonexact_selector_cannot_read_context(self):
        with (
            patch("ci_environment.require_runner"),
            patch.dict(
                os.environ,
                {"CI_TEST_MODE": "artifact", "CI_SPECS_JSON": '["other.spec.ts"]'},
            ),
            patch.object(Path, "read_text") as read,
        ):
            with self.assertRaises(Refused):
                probe.run("/unused")
            read.assert_not_called()

    def test_artifact_exact_selector_stays_rejected_before_context(self):
        with (
            patch("ci_environment.require_runner"),
            patch.dict(
                os.environ,
                {
                    "CI_TEST_MODE": "artifact",
                    "CI_SPECS_JSON": '["cli-memory-readiness.spec.ts"]',
                },
            ),
            patch.object(Path, "read_text") as read,
        ):
            with self.assertRaises(Refused):
                probe.run("/unused")
            read.assert_not_called()

    def test_e2e_requires_exact_singleton_before_context(self):
        for specs in (
            "[]",
            '["other.spec.ts"]',
            '["cli-memory-readiness.spec.ts","other.spec.ts"]',
        ):
            with (
                self.subTest(specs=specs),
                patch("ci_environment.require_runner"),
                patch.dict(os.environ, {"CI_TEST_MODE": "e2e", "CI_SPECS_JSON": specs}),
                patch.object(Path, "read_text") as read,
            ):
                with self.assertRaises(Refused):
                    probe.run("/unused")
                read.assert_not_called()

    def test_exact_e2e_reaches_required_genuine_context_without_fabrication(self):
        with (
            patch("ci_environment.require_runner"),
            patch.dict(
                os.environ,
                {
                    "CI_TEST_MODE": "e2e",
                    "CI_SPECS_JSON": '["cli-memory-readiness.spec.ts"]',
                },
            ),
            patch.object(
                Path,
                "read_text",
                side_effect=RuntimeError("genuine environment context required"),
            ) as read,
            patch.object(probe.subprocess, "check_output") as process,
        ):
            with self.assertRaisesRegex(
                RuntimeError, "genuine environment context required"
            ):
                probe.run("/unused")
            read.assert_called_once()
            process.assert_not_called()


if __name__ == "__main__":
    unittest.main()
