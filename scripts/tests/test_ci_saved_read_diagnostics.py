# contract-test-file: tooling
"""Inert tests of the actual closed projector AST; no controller/SDK/peer execution.

Load only its literal reviewed vocabularies and pure projector, so importing this
unit cannot start a controller or require any external account/runtime context.
"""

import ast
import copy
import json
from pathlib import Path
import unittest

PARSER = Path(__file__).resolve().parents[1] / "ci_sdk_conformance.py"
NAMES = {
    "VECTOR_DIAGNOSTIC_CAPABILITY",
    "VECTOR_DIAGNOSTIC_PHASES",
    "VECTOR_DIAGNOSTIC_CODES",
    "SAVED_READ_DIAGNOSTIC_CAPABILITY",
    "SAVED_READ_DIAGNOSTIC_PHASES",
    "SAVED_READ_DIAGNOSTIC_CODES",
    "MAX_VECTOR_DIAGNOSTIC_BYTES",
}


def projector():
    tree = ast.parse(PARSER.read_text())
    nodes = [
        node
        for node in tree.body
        if (
            isinstance(node, ast.Assign)
            and any(
                isinstance(target, ast.Name) and target.id in NAMES
                for target in node.targets
            )
        )
        or (
            isinstance(node, ast.FunctionDef)
            and node.name == "project_vector_diagnostic"
        )
    ]
    scope = {"json": json}
    exec(compile(ast.Module(body=nodes, type_ignores=[]), str(PARSER), "exec"), scope)
    return scope


class SavedReadDiagnosticTests(unittest.TestCase):
    def setUp(self):
        self.scope = projector()
        self.project = self.scope["project_vector_diagnostic"]
        self.expected = {
            "capability": "session.saved-chat-read.v1",
            "language": "rust",
            "vectors": ["default-30-from-65", "explicit-30-from-65"],
        }
        self.value = {
            "vectorId": "default-30-from-65",
            "phase": "bounded_read",
            "errorCode": "protocol",
        }

    def test_all_reviewed_saved_read_phases_and_codes_project_exactly(self):
        for phase in self.scope["SAVED_READ_DIAGNOSTIC_PHASES"]:
            for code in self.scope["SAVED_READ_DIAGNOSTIC_CODES"]:
                value = {**self.value, "phase": phase, "errorCode": code}
                self.assertEqual(
                    self.project(value, self.expected, [value["vectorId"]]), value
                )

    def test_known_but_nonfailed_or_foreign_vector_refuses(self):
        for failed in [[], ["explicit-30-from-65"], ["unknown"]]:
            self.assertIsNone(self.project(self.value, self.expected, failed))
        self.assertIsNone(
            self.project(
                {**self.value, "vectorId": "private-owner-id"},
                self.expected,
                ["private-owner-id"],
            )
        )

    def test_messages_extra_fields_missing_fields_wrong_types_and_oversize_refuse(self):
        invalid = [
            {**self.value, "message": "NEVER_EXPORT"},
            {**self.value, "phase": "private-path"},
            {**self.value, "errorCode": "private-token"},
            [self.value],
            None,
        ]
        for key in self.value:
            altered = copy.deepcopy(self.value)
            del altered[key]
            invalid.append(altered)
            invalid.append({**self.value, key: {"private": "NEVER_EXPORT"}})
            invalid.append({**self.value, key: "x" * 161})
        for value in invalid:
            self.assertIsNone(
                self.project(value, self.expected, [self.value["vectorId"]])
            )

    def test_other_languages_and_capabilities_never_receive_saved_read_projection(self):
        for language in ["npm", "python", "pip", None]:
            self.assertIsNone(
                self.project(
                    self.value,
                    {**self.expected, "language": language},
                    [self.value["vectorId"]],
                )
            )
        for capability in [
            "session.foreground-completion-recovery.v1",
            "session.message-window.v1",
            None,
        ]:
            self.assertIsNone(
                self.project(
                    self.value,
                    {**self.expected, "capability": capability},
                    [self.value["vectorId"]],
                )
            )

    def test_monitor_contract_keeps_original_phases_and_refuses_saved_only_phases(self):
        expected = {**self.expected, "capability": "session.chat-change-monitor.v1"}
        value = {**self.value, "phase": "stage"}
        self.assertEqual(self.project(value, expected, [value["vectorId"]]), value)
        self.assertIsNone(self.project(self.value, expected, [self.value["vectorId"]]))
        self.assertIsNone(self.project(value, self.expected, [value["vectorId"]]))

    def test_projection_constructs_new_closed_object_and_cannot_credit_success(self):
        result = self.project(self.value, self.expected, [self.value["vectorId"]])
        self.assertEqual(set(result), {"vectorId", "phase", "errorCode"})
        self.assertIsNot(result, self.value)
        self.assertNotIn("status", result)
        self.assertNotIn("message", result)


if __name__ == "__main__":
    unittest.main()
