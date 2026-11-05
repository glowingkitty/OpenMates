# contract-test-file: tooling
"""Inert exact four-title accounting; no browser/compiler/product invocation."""

from copy import deepcopy
import importlib.util
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location(
    "keyless_first_session_metadata", ROOT / "scripts/ci_metadata_rust_browser.py"
)
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)
TITLES = (
    "actual first normal session retains one original Worker through UI and startup",
    "actual revoked first normal session expires once without a Rust restore retry",
    "actual first normal auth queue preserves its original deadline without fallback",
    "actual missing cached Master reads normal Rust session DATA once without private admission",
)


def report():
    return {
        "suites": [
            {
                "specs": [
                    {
                        "title": title,
                        "tests": [
                            {
                                "status": "expected",
                                "results": [{"status": "passed", "retry": 0}],
                            }
                        ],
                    }
                    for title in TITLES
                ]
            }
        ]
    }


def actual_result(value, *, full_complete=True, exit_code=0):
    source = (ROOT / "scripts/ci_run_tests.py").read_text()
    start = source.index("                metadata_native_proof = None")
    end = source.index("                if web_search_capture is not None:", start)
    region = "\n".join(line[16:] for line in source[start:end].splitlines())
    context = dict(
        name=m.FIRST_SESSION_SPEC,
        report=value,
        selected_case_complete=full_complete,
        paired=False,
        results=[],
        account_evidence=[],
        result=SimpleNamespace(returncode=exit_code),
        case_title=None,
        reported_case_title=None,
        stats={"skipped": 0},
        executed=4,
    )
    with patch.dict(sys.modules, {"ci_metadata_rust_browser": m}):
        exec(compile(region, "actual-protected-result-region", "exec"), context)
    return context["results"][0]


class FirstSessionKeylessTests(unittest.TestCase):
    def test_exact_four_case_positive_requires_full_spec_and_process_success(self):
        self.assertEqual(m.FIRST_SESSION_REQUIRED_CASES, frozenset(TITLES))
        result = actual_result(report())
        self.assertEqual(result["exit_code"], 0)
        self.assertTrue(result["coverage_complete"])
        self.assertTrue(result["metadata_native_proof"]["complete"])
        self.assertEqual(result["metadata_native_proof"]["observedRequiredCases"], 4)
        for complete, code in [(False, 0), (True, 1), (False, 1)]:
            with self.subTest(complete=complete, code=code):
                self.assertNotEqual(
                    actual_result(report(), full_complete=complete, exit_code=code)[
                        "exit_code"
                    ],
                    0,
                )

    def test_old_three_alone_or_each_missing_case_refuses(self):
        for index in range(4):
            value = report()
            value["suites"][0]["specs"].pop(index)
            result = actual_result(value)
            self.assertFalse(result["metadata_native_proof"]["complete"])
            self.assertNotEqual(result["exit_code"], 0)

    def test_duplicate_empty_malformed_case_still_counts_and_refuses(self):
        for title in TITLES:
            for tests in (None, [], {}, "", [None]):
                value = report()
                duplicate = {"title": title}
                if tests is not None:
                    duplicate["tests"] = tests
                value["suites"].append({"specs": [duplicate]})
                with self.subTest(title=title, tests=tests):
                    self.assertNotEqual(actual_result(value)["exit_code"], 0)
            value = report()
            value["suites"].append(
                {
                    "suites": [
                        {
                            "specs": [
                                deepcopy(
                                    value["suites"][0]["specs"][TITLES.index(title)]
                                )
                            ]
                        }
                    ]
                }
            )
            self.assertNotEqual(actual_result(value)["exit_code"], 0)

    def test_explicit_integer_retry_zero_for_every_required_case(self):
        for index in range(4):
            for retry in (None, True, False, "0", 0.0, 1, -1):
                value = report()
                result = value["suites"][0]["specs"][index]["tests"][0]["results"][0]
                if retry is None:
                    result.pop("retry")
                else:
                    result["retry"] = retry
                with self.subTest(index=index, retry=retry):
                    self.assertNotEqual(actual_result(value)["exit_code"], 0)

    def test_failed_skipped_flaky_multiple_or_empty_observation_refuses(self):
        for index in range(4):
            for fault in (
                "failed",
                "skipped",
                "flaky",
                "unexpected",
                "multiple-results",
                "multiple-tests",
                "empty",
            ):
                value = report()
                test = value["suites"][0]["specs"][index]["tests"][0]
                if fault == "unexpected":
                    test["status"] = fault
                elif fault == "multiple-results":
                    test["results"].append(deepcopy(test["results"][0]))
                elif fault == "multiple-tests":
                    value["suites"][0]["specs"][index]["tests"].append(deepcopy(test))
                elif fault == "empty":
                    test["results"] = []
                else:
                    test["results"][0]["status"] = fault
                with self.subTest(index=index, fault=fault):
                    self.assertNotEqual(actual_result(value)["exit_code"], 0)

    def test_unknown_or_near_match_title_cannot_replace_keyless_case(self):
        for title in ("unknown", TITLES[-1] + " ", TITLES[-1].upper(), "", TITLES[0]):
            value = report()
            value["suites"][0]["specs"][-1]["title"] = title
            self.assertNotEqual(actual_result(value)["exit_code"], 0)
        # A failure elsewhere in the full spec cannot be hidden by the four
        # required positives; use the actual maintained coverage conjunction.
        value = report()
        value["suites"][0]["specs"].append(
            {
                "title": "other full-spec case",
                "tests": [
                    {
                        "status": "unexpected",
                        "results": [{"status": "failed", "retry": 0}],
                    }
                ],
            }
        )
        self.assertNotEqual(actual_result(value, full_complete=False)["exit_code"], 0)

    def test_exact_singleton_selector_is_unchanged(self):
        self.assertTrue(m.first_session_targets([m.FIRST_SESSION_SPEC]))
        for selection in (
            [],
            [m.FIRST_SESSION_SPEC] * 2,
            [m.FIRST_SESSION_SPEC, m.STARTUP_SPEC],
            ["other.spec.ts"],
            ["nested/" + m.FIRST_SESSION_SPEC],
            (m.FIRST_SESSION_SPEC,),
        ):
            self.assertFalse(m.first_session_targets(selection))

    def test_fixed_inputs_include_changed_runtime_paths_without_controller_authority(
        self,
    ):
        self.assertEqual(len(m.FIRST_SESSION_INPUTS), 17)
        changed_runtime = {
            "frontend/apps/web_app/src/lib/rustCore/firstSessionProvider.ts",
            "frontend/apps/web_app/tests/rust-core-first-session.spec.ts",
            "frontend/packages/ui/src/services/rustCore/protocol.ts",
            "frontend/packages/ui/src/services/rustCore/workerHost.ts",
            "frontend/packages/ui/src/services/rustCore/workerRuntime.ts",
        }
        self.assertTrue(changed_runtime <= m.FIRST_SESSION_INPUTS)
        self.assertFalse(
            any(
                name.startswith(("scripts/", ".github/"))
                for name in m.FIRST_SESSION_INPUTS
            )
        )


if __name__ == "__main__":
    unittest.main()
