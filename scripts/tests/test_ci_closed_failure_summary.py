# contract-test-file: tooling
"""Inert privacy and wiring proof for closed migration CI failure observations.

Only stdlib doubles and the actual main footer AST execute in these tests.
No runner, account, subprocess, network, filesystem report or product is started.
The saved report payload and exit/error behavior remain the original authority.
Hostile values must not invoke conversion, equality, hashing or iteration hooks.
"""

import ast
import builtins
import contextlib
import copy
import importlib.util
import io
import json
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch

SCRIPTS = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("closed_summary_under_test", SCRIPTS / "ci_closed_failure_summary.py")
summary = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(summary)


def failed(suite="sdk-conformance", **fields):
    return {"suite": suite, "exit_code": 1, "failed_stage": "sdk-library-units",
            "failure_code": "child_failed", **fields}


class Trap:
    def __str__(self):
        raise AssertionError("private conversion")

    __repr__ = __str__

    def __eq__(self, other):
        raise AssertionError("private comparison")

    def __hash__(self):
        return hash("suite")

    def __iter__(self):
        raise AssertionError("private iteration")


class ClosedSummaryTests(unittest.TestCase):
    def test_exact_three_producers_and_no_proof(self):
        rows = [failed(), failed("rust-wasm", failure_code="compile"),
                failed("rust-native-dev", failure_code="transport")]
        value = json.loads(summary.failure_summary(rows))
        self.assertEqual(value, {
            "kind": "migration-ci-failure-summary", "observation": True,
            "proofAccepted": False, "truncated": False,
            "failures": [
                {"suite": "sdk-conformance", "failed_stage": "sdk-library-units", "failure_code": "child_failed"},
                {"suite": "rust-wasm", "failed_stage": "unclassified", "failure_code": "compile"},
                {"suite": "rust-native-dev", "failed_stage": "unclassified", "failure_code": "transport"},
            ],
        })

    def test_no_success_or_unrelated_suite_diagnostics(self):
        for rows in [[], [failed(exit_code=0)], [failed("pytest")], [failed("rust-native")]]:
            self.assertIsNone(summary.failure_summary(rows))

    def test_unknown_large_candidate_strings_and_private_extra_fields_never_escape(self):
        secret = "private-token/path/https://secret.invalid/\n::error::" * 10000
        row = failed(failed_stage=secret, failure_code=secret, stderr=Trap(), owner=secret)
        value = summary.failure_summary([row])
        self.assertNotIn("private-token", value)
        self.assertNotIn("error::", value)
        self.assertEqual(json.loads(value)["failures"], [
            {"suite": "sdk-conformance", "failed_stage": "unclassified", "failure_code": "unclassified"},
        ])

    def test_codes_are_closed_per_suite_and_stage_not_inferred(self):
        value = json.loads(summary.failure_summary([
            failed("rust-wasm", failure_code="child_failed"),
            failed("rust-native-dev", failure_code="packaging"),
            failed(failed_stage="wasm-build", failure_code="compile"),
        ]))
        self.assertTrue(all(r["failure_code"] == "unclassified" for r in value["failures"]))
        self.assertTrue(all(r["failed_stage"] == "unclassified" for r in value["failures"]))

    def test_exact_types_reject_subclasses_and_hook_objects_without_calling_hooks(self):
        class String(str):
            __eq__ = Trap.__eq__
            __hash__ = Trap.__hash__
        class Integer(int):
            def __le__(self, other):
                raise AssertionError("integer hook")
        class Rows(list):
            def __iter__(self):
                raise AssertionError("list hook")
        class Row(dict):
            def get(self, key, default=None):
                raise AssertionError("dict hook")
        for rows in [Trap(), Rows([failed()]), (failed(),), [Row(failed())],
                     [failed(suite=Trap())], [failed(suite=String("sdk-conformance"))],
                     [failed(exit_code=Integer(1))], [failed(exit_code=Trap())],
                     [failed(exit_code=True)], [failed(exit_code=1.0)]]:
            self.assertIsNone(summary.failure_summary(rows))
        for value in [Trap(), String("child_failed"), {}, [], None, True, 1]:
            result = json.loads(summary.failure_summary([failed(failure_code=value, failed_stage=value)]))
            self.assertEqual(result["failures"][0]["failure_code"], "unclassified")
            self.assertEqual(result["failures"][0]["failed_stage"], "unclassified")
        # A colliding non-string key must be refused before row.get("suite").
        self.assertIsNone(summary.failure_summary([{Trap(): "private"}]))

    def test_malformed_rows_and_exit_bounds(self):
        rows = [None, [], Trap(), {}, {"suite": "sdk-conformance"},
                failed(exit_code=-256), failed(exit_code=256), failed(exit_code=10**1000),
                failed(**{str(i): i for i in range(summary.MAX_ROW_KEYS)}),
                failed(**{"x" * 65: "private"})]
        self.assertIsNone(summary.failure_summary(rows))
        for code in [-255, -1, 1, 255]:
            self.assertIsNotNone(summary.failure_summary([failed(exit_code=code)]))

    def test_scan_output_and_json_byte_bounds(self):
        value = summary.failure_summary([failed()] * 100000)
        self.assertLessEqual(len(value.encode("ascii")), summary.MAX_JSON_BYTES)
        self.assertEqual(len(json.loads(value)["failures"]), summary.MAX_FAILURE_ROWS)
        self.assertTrue(json.loads(value)["truncated"])
        prefix = [failed(exit_code=0)] * summary.MAX_SCANNED_ROWS
        self.assertIsNone(summary.failure_summary(prefix + [Trap(), failed()]))
        value = json.loads(summary.failure_summary([failed()] + prefix))
        self.assertTrue(value["truncated"])
        self.assertEqual(len(value["failures"]), 1)
        with patch.object(summary, "MAX_JSON_BYTES", 1):
            self.assertIsNone(summary.failure_summary([failed()]))

    def test_pure_no_mutation_stdout_or_stderr(self):
        rows = [failed(), failed(exit_code=0), {"suite": "private", "error": "private-text"}]
        before = copy.deepcopy(rows)
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            summary.failure_summary(rows)
        self.assertEqual(rows, before)
        self.assertEqual((out.getvalue(), err.getvalue()), ("", ""))

    def test_vocabularies_are_finite_ascii_constants(self):
        for suite, (stages, codes) in summary._SUITES.items():
            self.assertLessEqual(len(codes), 100)
            for value in (suite, *stages, *codes):
                self.assertIs(type(value), str)
                self.assertLessEqual(len(value), summary.MAX_ENUM_LENGTH)
                self.assertTrue(all(char.isascii() and (char.isalnum() or char in "-_") for char in value))


class MainWiringTests(unittest.TestCase):
    @staticmethod
    def footer():
        tree = ast.parse((SCRIPTS / "ci_run_tests.py").read_text())
        main = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "main")
        start = next(i for i, n in enumerate(main.body)
                     if isinstance(n, ast.Expr) and isinstance(n.value, ast.Call)
                     and isinstance(n.value.func, ast.Attribute) and n.value.func.attr == "write_text"
                     and 'ci-results.json' in ast.unparse(n))
        return main.body[start:]

    def test_actual_main_ast_wires_only_after_report_before_unchanged_error_and_return(self):
        footer = self.footer()
        self.assertEqual([type(n) for n in footer], [ast.Expr, ast.Try, ast.If, ast.Return])
        self.assertIn('write_text(json.dumps(payload, indent=2))', ast.unparse(footer[0]))
        self.assertEqual(ast.unparse(footer[2]), 'if error:\n    print(error, file=sys.stderr)')
        self.assertEqual(ast.unparse(footer[3]), "return 0 if payload['success'] else 1")
        observe = footer[1]
        self.assertEqual(len(observe.handlers), 1)
        self.assertEqual(ast.unparse(observe.handlers[0].type), "Exception")
        self.assertEqual([type(n) for n in observe.handlers[0].body], [ast.Pass])
        self.assertEqual(ast.unparse(observe.body[0]), "from ci_closed_failure_summary import failure_summary")
        self.assertEqual(ast.unparse(observe.body[1]), "summary = failure_summary(results)")
        self.assertEqual(ast.unparse(observe.body[2]), 'if summary is not None:\n    print(summary)')

    def run_footer(self, rows, success, *, fault=None, error=None, report_fails=False):
        calls = []
        class Report:
            def __truediv__(self, name):
                self_test.assertEqual(name, "ci-results.json")
                return self
            def write_text(self, value):
                calls.append(("report", json.loads(value)))
                if report_fails:
                    raise OSError("synthetic report failure")
        self_test = self
        payload = {"success": success, "results": rows, "error": error}
        native_print = builtins.print
        def observed_print(value, **kwargs):
            if "file" not in kwargs:
                calls.append(("observation", json.loads(value)))
                if fault == "print":
                    raise OSError("private log write failure")
            return native_print(value, **kwargs)
        def project(value):
            if fault == "project":
                raise ValueError("private projection failure")
            return summary.failure_summary(value)
        native_import = builtins.__import__
        def inert_import(name, *args, **kwargs):
            if name == "ci_closed_failure_summary":
                if fault == "import":
                    raise ImportError("private import failure")
                return SimpleNamespace(failure_summary=project)
            return native_import(name, *args, **kwargs)
        fn = ast.FunctionDef(name="inert_main_footer", args=ast.arguments(
            posonlyargs=[], args=[], kwonlyargs=[], kw_defaults=[], defaults=[]),
            body=self.footer(), decorator_list=[])
        module = ast.fix_missing_locations(ast.Module(body=[fn], type_ignores=[]))
        namespace = {"RESULTS": Report(), "payload": payload, "results": rows, "error": error,
                     "json": json, "sys": SimpleNamespace(stderr=io.StringIO()), "print": observed_print}
        exec(compile(module, "<actual-main-footer>", "exec"), namespace)
        with patch("builtins.__import__", inert_import), contextlib.redirect_stdout(io.StringIO()):
            code = namespace["inert_main_footer"]()
        self.assertEqual(calls[0], ("report", payload))
        self.assertEqual(namespace["sys"].stderr.getvalue(), (error + "\n") if error else "")
        return code, calls

    def test_failed_observation_follows_report_without_acceptance_changes(self):
        code, calls = self.run_footer([failed()], False, error="original failure")
        self.assertEqual(code, 1)
        self.assertEqual([name for name, _ in calls], ["report", "observation"])
        self.assertFalse(calls[1][1]["proofAccepted"])

    def test_success_prints_nothing_and_observation_faults_preserve_exit_report_and_error(self):
        for fault in [None, "import", "project", "print"]:
            code, calls = self.run_footer([failed()], False, fault=fault, error="original failure")
            self.assertEqual(code, 1)
            self.assertEqual(calls[0][0], "report")
            code, calls = self.run_footer([failed(exit_code=0)], True, fault=fault)
            self.assertEqual(code, 0)
            self.assertEqual(len(calls), 1)

    def test_failed_report_still_raises_before_observation(self):
        with self.assertRaisesRegex(OSError, "synthetic report failure"):
            self.run_footer([failed()], False, report_fails=True)


if __name__ == "__main__":
    unittest.main()
