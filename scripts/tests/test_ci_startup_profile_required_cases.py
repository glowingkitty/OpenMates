# contract-test-file: tooling
"""Pure required-case accounting. No browser/runtime acceptance."""

import importlib.util
from pathlib import Path
import unittest

path = Path(__file__).resolve().parents[1] / "ci_metadata_rust_browser.py"
spec = importlib.util.spec_from_file_location("startup_required_case_metadata", path)
metadata = importlib.util.module_from_spec(spec)
spec.loader.exec_module(metadata)
TITLES = (
    "actual Rust startup keeps first usable chat independent of expanded metadata",
    "actual Rust warm cached selection survives held startup beyond ordinary deadline",
    "actual prior profile cache stays usable during monitor auth and clears on real session revocation",
    "actual native cache version change clears an idle Rust selected view",
)


def report(titles, failed=None):
    return {
        "suites": [
            {
                "specs": [
                    {
                        "title": title,
                        "tests": [
                            {
                                "status": "expected",
                                "results": [
                                    {
                                        "status": "failed"
                                        if title == failed
                                        else "passed",
                                        "retry": 0,
                                    }
                                ],
                            }
                        ],
                    }
                    for title in titles
                ]
            }
        ]
    }


class RequiredStartupCases(unittest.TestCase):
    def test_original_two_and_original_fifteen_are_preserved(self):
        self.assertEqual(len(metadata.REQUIRED_CASES), 15)
        self.assertEqual(metadata.STARTUP_REQUIRED_CASES, frozenset(TITLES))
        self.assertFalse(
            metadata.startup_browser_case_proof(report(TITLES[:2]))["complete"]
        )

    def test_each_required_case_exactly_once_and_passed(self):
        self.assertTrue(metadata.startup_browser_case_proof(report(TITLES))["complete"])
        for title in TITLES:
            with self.subTest(title=title):
                self.assertFalse(
                    metadata.startup_browser_case_proof(
                        report([x for x in TITLES if x != title])
                    )["complete"]
                )
                self.assertFalse(
                    metadata.startup_browser_case_proof(report([*TITLES, title]))[
                        "complete"
                    ]
                )
                self.assertFalse(
                    metadata.startup_browser_case_proof(report(TITLES, failed=title))[
                        "complete"
                    ]
                )

    def test_skipped_and_unexecuted_case_refuse(self):
        for status in ("skipped", "interrupted", "timedOut"):
            value = report(TITLES)
            value["suites"][0]["specs"][-1]["tests"][0]["results"][0]["status"] = status
            self.assertFalse(metadata.startup_browser_case_proof(value)["complete"])
        value = report(TITLES)
        value["suites"][0]["specs"][-1]["tests"] = []
        self.assertFalse(metadata.startup_browser_case_proof(value)["complete"])

    def test_partial_retried_and_multiple_attempt_results_refuse(self):
        partials = [
            {},
            {"status": "expected", "results": []},
            {"status": "expected", "results": None},
            {"status": "expected", "results": [{}]},
            {"status": "expected", "results": [{"status": "passed", "retry": 1}]},
            {
                "status": "expected",
                "results": [{"status": "failed"}, {"status": "passed"}],
            },
            {
                "status": "expected",
                "results": [{"status": "passed"}, {"status": "passed"}],
            },
        ]
        for title in TITLES:
            for partial in partials:
                with self.subTest(title=title, partial=partial):
                    value = report(TITLES)
                    item = next(
                        item
                        for item in value["suites"][0]["specs"]
                        if item["title"] == title
                    )
                    item["tests"] = [partial]
                    self.assertFalse(
                        metadata.startup_browser_case_proof(value)["complete"]
                    )

    def test_each_duplicate_empty_or_malformed_spec_refuses(self):
        malformed = [
            {},
            {"tests": []},
            {"tests": None},
            {"tests": {}},
            {"tests": False},
            {"tests": 0},
            {"tests": "invalid"},
            {"tests": [None]},
            {"tests": [{}, {}]},
        ]
        for title in TITLES:
            for fields in malformed:
                with self.subTest(title=title, fields=fields):
                    value = report(TITLES)
                    value["suites"].append({"specs": [{"title": title, **fields}]})
                    self.assertFalse(
                        metadata.startup_browser_case_proof(value)["complete"]
                    )
                    value = report(TITLES)
                    specs = value["suites"][0]["specs"]
                    specs[TITLES.index(title)] = {"title": title, **fields}
                    proof = metadata.startup_browser_case_proof(value)
                    self.assertEqual(proof["observedRequiredCases"], 4)
                    self.assertFalse(proof["complete"])
            value = report(TITLES)
            tests = value["suites"][0]["specs"][TITLES.index(title)]["tests"]
            tests.append(tests[0].copy())
            self.assertFalse(metadata.startup_browser_case_proof(value)["complete"])

    def test_each_result_requires_explicit_integer_zero_retry(self):
        malformed = [None, False, True, 0.0, "0", [], {}, -1, 1]
        for title in TITLES:
            for retry in malformed:
                with self.subTest(title=title, retry=retry):
                    value = report(TITLES)
                    value["suites"][0]["specs"][TITLES.index(title)]["tests"][0][
                        "results"
                    ][0]["retry"] = retry
                    self.assertFalse(
                        metadata.startup_browser_case_proof(value)["complete"]
                    )
            value = report(TITLES)
            del value["suites"][0]["specs"][TITLES.index(title)]["tests"][0]["results"][
                0
            ]["retry"]
            self.assertFalse(metadata.startup_browser_case_proof(value)["complete"])

    def test_each_partial_multiple_retried_or_skipped_result_refuses(self):
        results_cases = [
            None,
            {},
            "passed",
            [],
            [None],
            [{}],
            [{"status": "passed"}],
            [{"status": "passed", "retry": 1}],
            [{"status": "failed", "retry": 0}],
            [{"status": "skipped", "retry": 0}],
            [{"status": "interrupted", "retry": 0}],
            [{"status": "timedOut", "retry": 0}],
            [{"status": "failed", "retry": 0}, {"status": "passed", "retry": 1}],
            [{"status": "passed", "retry": 0}, {"status": "passed", "retry": 0}],
        ]
        for title in TITLES:
            for results in results_cases:
                with self.subTest(title=title, results=results):
                    value = report(TITLES)
                    value["suites"][0]["specs"][TITLES.index(title)]["tests"][0][
                        "results"
                    ] = results
                    self.assertFalse(
                        metadata.startup_browser_case_proof(value)["complete"]
                    )
            value = report(TITLES)
            del value["suites"][0]["specs"][TITLES.index(title)]["tests"][0]["results"]
            self.assertFalse(metadata.startup_browser_case_proof(value)["complete"])
            value = report(TITLES)
            test = value["suites"][0]["specs"][TITLES.index(title)]["tests"][0]
            test["status"] = "skipped"
            self.assertFalse(metadata.startup_browser_case_proof(value)["complete"])


if __name__ == "__main__":
    unittest.main()
