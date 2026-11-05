"""Pure new-facade DTO tests; no native import, filesystem effect or SDK IO."""

# contract-test-file: tooling
import ast
import json
from pathlib import Path
from types import SimpleNamespace
import unittest


class SessionClientError(Exception):
    def __init__(self, code, message):
        self.code = code
        super().__init__(message)


def load():
    path = Path(__file__).resolve().parents[1] / "openmates/session_facades.py"
    tree = ast.parse(path.read_text())
    node = next(
        n
        for n in tree.body
        if isinstance(n, ast.ClassDef) and n.name == "SessionProjects"
    )
    method = next(
        n
        for n in node.body
        if isinstance(n, ast.AsyncFunctionDef) and n.name == "sync_workflow_files"
    )
    cls = ast.ClassDef(
        name="OnlyNewProjects", bases=[], keywords=[], body=[method], decorator_list=[]
    )
    module = ast.Module(
        body=[
            ast.ImportFrom(
                module="__future__", names=[ast.alias(name="annotations")], level=0
            ),
            cls,
        ],
        type_ignores=[],
    )
    namespace = {"json": json, "SessionClientError": SessionClientError}
    exec(compile(ast.fix_missing_locations(module), str(path), "exec"), namespace)
    return namespace["OnlyNewProjects"]


class WorkflowFileFacadeTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.calls = []

        async def native(*args):
            self.calls.append(args)
            return '[{"project_id":"actual","status":"pending"}]'

        def prepared(operation, prepare):
            args = prepare()
            return operation(*args)

        self.api = load()()
        self.api._client = SimpleNamespace(
            _native=SimpleNamespace(projects_sync_workflow_files=native),
            _prepared_call=prepared,
        )

    async def test_named_operation_preserves_explicit_scope_and_exact_intent(self):
        rows = await self.api.sync_workflow_files(
            "workflow",
            "version",
            options={
                "approved_paths": ["folder/a.workflow.yml"],
                "source_chat": "chat",
            },
            filters={"personal": True},
        )
        self.assertEqual(rows, [{"project_id": "actual", "status": "pending"}])
        value, filters = map(json.loads, self.calls[0])
        self.assertEqual(
            value,
            {
                "workflow_id": "workflow",
                "expected_version": "version",
                "approved_paths": ["folder/a.workflow.yml"],
                "source_chat": "chat",
            },
        )
        self.assertEqual(filters, {"personal": True})

    async def test_unknown_options_cannot_replace_positional_identity_or_assert_authority(
        self,
    ):
        for value in [
            {"workflow_id": "foreign"},
            {"expected_version": "foreign"},
            {"authenticated": True},
            {"serialize": lambda: None},
        ]:
            with self.assertRaises(SessionClientError) as caught:
                await self.api.sync_workflow_files(
                    "original", "version", options=value, filters={"personal": True}
                )
            self.assertEqual(caught.exception.code, "invalid_argument")
        self.assertEqual(self.calls, [])

    async def test_missing_approval_remains_absent_not_implicit_yes(self):
        await self.api.sync_workflow_files(
            "workflow", "version", filters={"personal": True}
        )
        self.assertEqual(
            json.loads(self.calls[0][0]),
            {"workflow_id": "workflow", "expected_version": "version"},
        )

    async def test_custom_option_mapping_is_not_invoked(self):
        class Custom(dict):
            def items(self):
                raise AssertionError("caller callback")

        with self.assertRaises(SessionClientError):
            await self.api.sync_workflow_files(
                "workflow",
                "version",
                options=Custom(approved_paths=[]),
                filters={"personal": True},
            )
        self.assertEqual(self.calls, [])

    async def test_custom_path_list_is_not_iterated_for_approval_intent(self):
        class Custom(list):
            def __iter__(self):
                raise AssertionError("caller iterator")

        with self.assertRaises(SessionClientError):
            await self.api.sync_workflow_files(
                "workflow",
                "version",
                options={"approved_paths": Custom(["safe/a.workflow.yml"])},
                filters={"personal": True},
            )
        self.assertEqual(self.calls, [])


if __name__ == "__main__":
    unittest.main()
