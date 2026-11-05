# contract-test-file: tooling
"""Inert closed progress projection; never builds or executes a product."""

import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

SCRIPTS = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location(
    "sdk_unit_progress_subject", SCRIPTS / "ci_sdk_conformance.py"
)
sdk = importlib.util.module_from_spec(spec)
spec.loader.exec_module(sdk)


def hashes(name):
    return {
        "fullSha256": sdk.sha(name.encode()),
        "leafSha256": sdk.sha(name.rsplit("::", 1)[-1].encode()),
    }


def expected(total=None, completed=(), slow=()):
    result = {
        "cargoCompilationFinishedObserved": False,
        "testBinaryObserved": False,
        "libtestStartObserved": total is not None,
    }
    if total is not None:
        result.update(
            reportedTotal=total,
            observedCompleted=len(completed),
            observedLongRunning=len(slow),
            countsConsistent=True,
            longRunningIdentifiers=[hashes(v) for v in slow],
            lastCompletedIdentifiers=[hashes(v) for v in completed],
        )
    return result


class UnitProgressTests(unittest.TestCase):
    def project(self, text, stage="sdk-library-units"):
        return sdk.rust_unit_progress_diagnostics(text.encode(), stage)

    def test_build_output_does_not_claim_libtest_started(self):
        self.assertEqual(self.project("Compiling crate\nprivate token\n"), expected())
        self.assertIsNone(self.project("running 5 tests\n", "napi-build"))

    def test_compile_finish_and_test_binary_flags_are_closed(self):
        observed = self.project(
            "    Finished `test` profile [unoptimized] target(s) in 1m 2.30s\n     Running unittests src/lib.rs (/private/token/test-binary)\n"
        )
        self.assertEqual(
            observed,
            {
                **expected(),
                "cargoCompilationFinishedObserved": True,
                "testBinaryObserved": True,
            },
        )
        self.assertNotIn("private", json.dumps(observed))
        self.assertNotIn("token", json.dumps(observed))

    def test_timeout_exports_only_numeric_progress_and_hashed_identifiers(self):
        observed = self.project(
            "running 4 tests\ntest private::first ... ok\ntest private::second ... FAILED\ntest private::third has been running for over 60 seconds\nhttps://private.example/token\n"
        )
        self.assertEqual(
            observed,
            expected(4, ("private::first", "private::second"), ("private::third",)),
        )
        self.assertNotIn("private", json.dumps(observed))
        self.assertNotIn("token", json.dumps(observed))

    def test_duplicate_warning_and_completed_test_are_not_double_counted(self):
        self.assertEqual(
            self.project(
                "running 2 tests\ntest held::one has been running for over 60 seconds\ntest held::one has been running for over 120 seconds\ntest held::one ... ok\ntest held::one ... ok\n"
            ),
            expected(2, ("held::one",)),
        )

    def test_latest_exact_run_header_resets_progress(self):
        self.assertEqual(
            self.project(
                "running 2 tests\ntest old::one ... ok\nrunning 1 test\ntest current::one has been running for over 60 seconds\n"
            ),
            expected(1, (), ("current::one",)),
        )

    def test_malformed_unbounded_and_unstarted_lines_supply_no_counts(self):
        for text in (
            "running 99999999 tests\n",
            "running -1 tests\n",
            "test foreign::one ... ok\n",
            "running 1000001 tests\n",
        ):
            with self.subTest(text=text):
                self.assertEqual(self.project(text), expected())

    def test_inconsistent_counts_refuse_completion_projection(self):
        self.assertEqual(
            self.project("running 1 test\ntest one ... ok\ntest two ... ok\n"),
            {**expected(), "libtestStartObserved": True, "countsConsistent": False},
        )

    def test_header_before_64k_tail_is_preserved_by_existing_bounded_log(self):
        text = (
            "running 2 tests\n"
            + "private warning\n" * 6000
            + "test held::one ... ok\ntest held::two has been running for over 60 seconds\n"
        )
        self.assertGreater(len(text), 65536)
        self.assertEqual(
            self.project(text), expected(2, ("held::one",), ("held::two",))
        )

    def test_identifier_grammar_length_and_combined_export_bound(self):
        text = "running 100 tests\n" + "".join(
            f"test held::done{i} ... ok\n" for i in range(25)
        )
        text += "".join(
            f"test held::slow{i} has been running for over 60 seconds\n"
            for i in range(12)
        )
        text += (
            "test "
            + "x" * 241
            + " ... ok\ntest private/path ... ok\ntest invalid:::name ... ok\n"
        )
        observed = self.project(text)
        self.assertEqual(observed["observedCompleted"], 25)
        self.assertEqual(observed["observedLongRunning"], 12)
        self.assertEqual(
            observed["lastCompletedIdentifiers"],
            [hashes(f"held::done{i}") for i in range(21, 25)],
        )
        self.assertEqual(
            len(observed["lastCompletedIdentifiers"])
            + len(observed["longRunningIdentifiers"]),
            16,
        )
        self.assertTrue(
            all(
                set(v) == {"fullSha256", "leafSha256"}
                and all(len(digest) == 64 for digest in v.values())
                for v in observed["longRunningIdentifiers"]
            )
        )

    def test_leaf_hash_correlates_same_static_function_without_raw_names(self):
        observed = self.project(
            "running 2 tests\ntest left::same_fn ... ok\ntest right::same_fn has been running for over 60 seconds\n"
        )
        done = observed["lastCompletedIdentifiers"][0]
        slow = observed["longRunningIdentifiers"][0]
        self.assertNotEqual(done["fullSha256"], slow["fullSha256"])
        self.assertEqual(done["leafSha256"], slow["leafSha256"])
        self.assertEqual(done["leafSha256"], sdk.sha(b"same_fn"))
        self.assertNotIn("same_fn", json.dumps(observed))

    def test_log_input_uses_existing_byte_bound(self):
        with patch.object(sdk, "MAX_LOG", 1):
            self.assertEqual(self.project("running 1 test\n"), expected())

    def test_existing_failure_retention_adds_progress_without_raw_upload(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            private = root / "private"
            private.mkdir(mode=0o700)
            raw = b"running 1 test\ntest private::held has been running for over 60 seconds\n"
            (private / "sdk-library-units.log").write_bytes(raw)
            observed = sdk.failure_diagnostics(
                private, root, "sdk-library-units", {}, []
            )
            self.assertEqual(
                observed["rustUnitProgress"], expected(1, (), ("private::held",))
            )
            self.assertFalse(observed["rawUpload"])
            self.assertEqual(observed["privateRetained"]["sha256"], sdk.sha(raw))
            self.assertNotIn("private::held", json.dumps(observed))
            self.assertEqual(observed["compiler"], [])


if __name__ == "__main__":
    unittest.main()
