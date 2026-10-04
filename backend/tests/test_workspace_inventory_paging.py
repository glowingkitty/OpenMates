"""Injected keyset/route tests without CMS, API startup or shared module stubs.

Compile the actual list functions and helpers, as other isolated backend tests
already do, so mocked imports cannot affect unrelated tests in the same run.
"""
from __future__ import annotations

import ast
import hashlib
import re
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import UUID

ROOT = Path(__file__).resolve().parents[2]


def load_functions(relative: str, names: set[str]) -> dict:
    tree = ast.parse((ROOT / relative).read_text())
    nodes = [ast.ImportFrom(module="__future__", names=[ast.alias(name="annotations")], level=0)]
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name in names:
            node.decorator_list = []
            nodes.append(node)
        elif isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id in names for t in node.targets):
            nodes.append(node)
        elif isinstance(node, ast.ClassDef):
            for method in node.body:
                if isinstance(method, ast.AsyncFunctionDef) and method.name in names:
                    method.decorator_list = []
                    nodes.append(method)
    namespace = dict(hashlib=hashlib, re=re, UUID=UUID, Query=lambda **_: None, Depends=lambda _: None,
                     get_user_task_service=lambda: None, get_workflow_task_projection_service=lambda: None,
                     get_user_plan_service=lambda: None)
    exec(compile(ast.fix_missing_locations(ast.Module(body=nodes, type_ignores=[])), relative, "exec"), namespace)
    return namespace


def repository(kind: str, get_items: AsyncMock) -> SimpleNamespace:
    helpers = {"hash_id", "SHA256_HEX_RE", "_coerce_hashes", "is_sha256_hex", f"USER_{kind.upper()}_FIELDS", f"list_{kind}s"}
    if kind == "task":
        helpers |= {"derive_task_short_id", "_with_short_id", "_coerce_blind_hashes", "_coerce_priority", "EXTERNAL_CHAT_PROVIDERS"}
    namespace = load_functions(f"backend/core/api/app/services/directus/user_{kind}_methods.py", helpers)
    value = SimpleNamespace(directus_service=SimpleNamespace(get_items=get_items), list_plan_key_wrappers=AsyncMock(return_value=[]))
    value.list_items = lambda *args, **kwargs: namespace[f"list_{kind}s"](value, *args, **kwargs)
    return value


def route(kind: str) -> dict:
    names = {f"list_user_{kind}s", "_unwrap_query_default", "_query_list_values"}
    namespace = load_functions(f"backend/core/api/app/routes/user_{kind}s.py", names)
    namespace["_current_user"] = AsyncMock(return_value=SimpleNamespace(id="owner"))
    namespace[f"_handle_{kind}_error"] = lambda error: (_ for _ in ()).throw(error)
    async def threadpool(function, *args):
        return function(*args)
    namespace["run_in_threadpool"] = threadpool
    return namespace


class TestWorkspaceInventoryPaging(unittest.IsolatedAsyncioTestCase):
    # contract-test: supporting surface=rest_api assertions=apple-workspaces.offline-complete,apple-workspaces.isolation
    async def test_keyset_lookahead_keeps_owner_filters_and_stable_order(self):
        for kind in ["task", "plan"]:
            rows = [{f"{kind}_id": f"id-{n}", "key_wrappers": []} for n in range(3)]
            get_items = AsyncMock(return_value=rows)
            methods = repository(kind, get_items)
            result = await methods.list_items("owner", paginate=True, cursor="id-0", limit=2, chat_id="chat", status="todo")
            self.assertEqual(len(result), 3)
            params = get_items.await_args.kwargs["params"]
            self.assertTrue(get_items.await_args.kwargs["raise_on_error"])
            self.assertEqual(params["sort"], f"{kind}_id")
            self.assertEqual(params["limit"], 3)
            owner = hashlib.sha256(b"owner").hexdigest()
            if kind == "task":
                terms = params["filter"]["_and"]
                self.assertIn({"hashed_user_id": {"_eq": owner}}, terms)
                self.assertIn({"hashed_team_id": {"_null": True}}, terms)
                self.assertIn({"task_id": {"_gt": "id-0"}}, terms)
                self.assertIn({"status": {"_eq": "todo"}}, terms)
                self.assertIn({"hashed_primary_chat_id": {"_eq": hashlib.sha256(b"chat").hexdigest()}}, terms)
            else:
                self.assertEqual(params["filter[hashed_user_id][_eq]"], owner)
                self.assertTrue(params["filter[hashed_team_id][_null]"])
                self.assertEqual(params["filter[plan_id][_gt]"], "id-0")
                self.assertEqual(params["filter[status][_eq]"], "todo")
                self.assertEqual(params["filter[hashed_primary_chat_id][_eq]"], hashlib.sha256(b"chat").hexdigest())

    # contract-test: supporting surface=rest_api assertions=apple-workspaces.offline-complete,apple-workspaces.isolation
    async def test_team_pages_preserve_explicit_team_and_maximum_limit(self):
        for kind in ["task", "plan"]:
            get_items = AsyncMock(return_value=[])
            await repository(kind, get_items).list_items("owner", team_id="team", paginate=True, limit=500)
            params = get_items.await_args.kwargs["params"]
            self.assertEqual(params["limit"], 501)
            team_hash = hashlib.sha256(b"team").hexdigest()
            if kind == "task":
                self.assertEqual(params["filter"], {"hashed_team_id": {"_eq": team_hash}})
            else:
                self.assertEqual(params["filter[hashed_team_id][_eq]"], team_hash)
                self.assertNotIn("filter[hashed_user_id][_eq]", params)

    # contract-test: supporting surface=rest_api assertions=apple-workspaces.offline-complete
    async def test_project_filtered_page_scans_bounded_chunks_across_gaps(self):
        project_hash = hashlib.sha256(b"project").hexdigest()
        for kind in ["task", "plan"]:
            def row(n, match=False):
                return {f"{kind}_id": f"id-{n}", "linked_project_hashes": [project_hash] if match else [], "key_wrappers": []}
            calls = []
            batches = [[row(1), row(2, True), row(3)], [row(4), row(5, True), row(6, True)]]
            async def get_items(_collection, *, params, no_cache, raise_on_error):
                import copy
                calls.append(copy.deepcopy(params))
                return batches[len(calls) - 1]
            result = await repository(kind, AsyncMock(side_effect=get_items)).list_items("owner", paginate=True, limit=2, project_id="project")
            self.assertEqual([v[f"{kind}_id"] for v in result], ["id-2", "id-5", "id-6"])
            self.assertTrue(all(call["limit"] == 3 for call in calls))
            self.assertEqual(len(calls), 2)
            if kind == "task":
                self.assertIn({"task_id": {"_gt": "id-3"}}, calls[1]["filter"]["_and"])
            else:
                self.assertEqual(calls[1]["filter[plan_id][_gt]"], "id-3")

    # contract-test: supporting surface=rest_api assertions=apple-workspaces.offline-complete,apple-workspaces.isolation
    async def test_routes_return_cursor_completeness_and_projections_only_once(self):
        for kind in ["task", "plan"]:
            namespace = route(kind)
            service = SimpleNamespace(**{f"list_{kind}s": AsyncMock(side_effect=[
                [{f"{kind}_id": "a"}, {f"{kind}_id": "b"}, {f"{kind}_id": "c"}], [{f"{kind}_id": "c"}]
            ])}, task_methods=SimpleNamespace(eligible_external_ai=AsyncMock(return_value=True)))
            projection_calls = []
            projection = SimpleNamespace(model_dump=lambda **_: {"task_id": "workflow-projection", "source": "workflow_run"})
            def list_projections(user):
                projection_calls.append(user)
                return [projection]
            kwargs = {"service": service, "paginate": True, "limit": 2}
            if kind == "task": kwargs["workflow_projection_service"] = SimpleNamespace(list_projections=list_projections)
            first = await namespace[f"list_user_{kind}s"](SimpleNamespace(), SimpleNamespace(), **kwargs)
            self.assertFalse(first["complete"])
            self.assertEqual(first["next_cursor"], "b")
            second = await namespace[f"list_user_{kind}s"](SimpleNamespace(), SimpleNamespace(), cursor="b", **kwargs)
            self.assertTrue(second["complete"])
            self.assertIsNone(second["next_cursor"])
            self.assertEqual([v[f"{kind}_id"] for v in second[f"{kind}s"]], ["c"])
            if kind == "task": self.assertEqual(projection_calls, ["owner"])

    # contract-test: supporting surface=rest_api assertions=apple-workspaces.isolation
    async def test_team_route_requires_role_before_read_and_excludes_personal_projections(self):
        for kind in ["task", "plan"]:
            namespace = route(kind)
            require_role = AsyncMock(side_effect=PermissionError("forbidden"))
            request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(directus_service=SimpleNamespace(team=SimpleNamespace(require_team_role=require_role)))))
            service = SimpleNamespace(**{f"list_{kind}s": AsyncMock(return_value=[])}, task_methods=SimpleNamespace(eligible_external_ai=AsyncMock(return_value=True)))
            projection_service = SimpleNamespace(list_projections=lambda _: self.fail("Personal projections leaked into team page"))
            kwargs = {"service": service, "team_id": "team", "paginate": True}
            if kind == "task": kwargs["workflow_projection_service"] = projection_service
            with self.assertRaises(PermissionError): await namespace[f"list_user_{kind}s"](request, SimpleNamespace(), **kwargs)
            getattr(service, f"list_{kind}s").assert_not_awaited()
            require_role.side_effect = None
            result = await namespace[f"list_user_{kind}s"](request, SimpleNamespace(), **kwargs)
            self.assertEqual(result[f"{kind}s"], [])
            self.assertTrue(result["complete"])

    # contract-test: supporting surface=rest_api assertions=apple-workspaces.isolation
    async def test_failed_database_shape_cannot_claim_complete_empty_inventory(self):
        for kind in ["task", "plan"]:
            with self.assertRaises(RuntimeError):
                await repository(kind, AsyncMock(return_value={"error": "unavailable"})).list_items("owner", paginate=True)

    # contract-test: supporting surface=rest_api assertions=apple-workspaces.offline-complete
    async def test_legacy_shape_and_invalid_paging_are_explicit(self):
        for kind in ["task", "plan"]:
            namespace = route(kind)
            service = SimpleNamespace(**{f"list_{kind}s": AsyncMock(return_value=[])}, task_methods=SimpleNamespace(eligible_external_ai=AsyncMock(return_value=True)))
            kwargs = {"service": service}
            if kind == "task": kwargs["workflow_projection_service"] = SimpleNamespace(list_projections=lambda _: [])
            result = await namespace[f"list_user_{kind}s"](SimpleNamespace(), SimpleNamespace(), **kwargs)
            self.assertNotIn("complete", result)
            self.assertNotIn("next_cursor", result)
            self.assertNotIn("paginate", getattr(service, f"list_{kind}s").await_args.kwargs)
            for bad in [dict(cursor="a"), dict(paginate=True, limit=501), dict(paginate=True, cursor="")]:
                with self.assertRaises(ValueError): await namespace[f"list_user_{kind}s"](SimpleNamespace(), SimpleNamespace(), **kwargs, **bad)


class TestPlanChildInventoryPaging(unittest.IsolatedAsyncioTestCase):
    KINDS = {"criteria": "user_plan_acceptance_criteria", "verifications": "user_plan_verifications",
             "assumptions": "user_plan_assumptions", "reference_patterns": "user_plan_reference_patterns"}
    IDS = [f"00000000-0000-4000-8000-{n:012d}" for n in range(1, 4)]

    def method(self, kind, get_items):
        namespace = load_functions("backend/core/api/app/services/directus/user_plan_methods.py",
            {"_list_child_collection", f"list_{kind}", "CRITERION_FIELDS", "VERIFICATION_FIELDS", "ASSUMPTION_FIELDS", "REFERENCE_PATTERN_FIELDS"})
        value = SimpleNamespace(directus_service=SimpleNamespace(get_items=get_items))
        value._list_child_collection = lambda *args, **kwargs: namespace["_list_child_collection"](value, *args, **kwargs)
        return lambda *args, **kwargs: namespace[f"list_{kind}"](value, *args, **kwargs)

    def endpoint(self, kind):
        namespace = load_functions("backend/core/api/app/routes/user_plans.py", {"_read_plan_children", f"list_plan_{kind}"})
        namespace["_current_user"] = AsyncMock(return_value=SimpleNamespace(id="owner"))
        namespace["_handle_plan_error"] = lambda error: (_ for _ in ()).throw(error)
        return namespace

    # contract-test: supporting surface=rest_api assertions=apple-workspaces.offline-complete,apple-workspaces.isolation
    async def test_child_keyset_uses_unique_row_id_and_never_drops_parent_filter(self):
        for kind, collection in self.KINDS.items():
            rows = [{"id": key, "plan_id": "parent", "encrypted_text": "cipher"} for key in self.IDS]
            database = AsyncMock(return_value=rows)
            method = self.method(kind, database)
            self.assertEqual(await method("parent", paginate=True, limit=500, cursor=self.IDS[0]), rows)
            call = database.await_args
            self.assertEqual(call.args[0], collection)
            self.assertEqual(call.kwargs["params"]["filter[plan_id][_eq]"], "parent")
            self.assertEqual(call.kwargs["params"]["filter[id][_gt]"], self.IDS[0])
            self.assertEqual(call.kwargs["params"]["sort"], "id")
            self.assertEqual(call.kwargs["params"]["limit"], 501)
            self.assertTrue(call.kwargs["raise_on_error"])
            await method("parent")
            self.assertEqual(database.await_args.kwargs["params"]["sort"], "created_at")
            self.assertNotIn("limit", database.await_args.kwargs["params"])
            self.assertNotIn("raise_on_error", database.await_args.kwargs)
            database.return_value = {"error": "unavailable"}
            with self.assertRaises(RuntimeError): await method("parent", paginate=True)

    # contract-test: supporting surface=rest_api assertions=apple-workspaces.offline-complete,apple-workspaces.isolation
    async def test_child_route_completes_only_after_last_page_in_exact_team_context(self):
        for kind in self.KINDS:
            namespace = self.endpoint(kind)
            rows = [{"id": key, "plan_id": "parent"} for key in self.IDS]
            read = AsyncMock(side_effect=[rows, rows[2:]])
            service = SimpleNamespace(ensure_plan_owner=AsyncMock(), get_plan=AsyncMock(),
                                      plan_methods=SimpleNamespace(**{f"list_{kind}": read}))
            guard = AsyncMock()
            request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(directus_service=SimpleNamespace(team=SimpleNamespace(require_team_role=guard)))))
            endpoint = namespace[f"list_plan_{kind}"]
            first = await endpoint(request, None, "parent", service=service, team_id="team", paginate=True, limit=2)
            self.assertFalse(first["complete"])
            self.assertEqual(first["next_cursor"], self.IDS[1])
            second = await endpoint(request, None, "parent", service=service, team_id="team", paginate=True, limit=2, cursor=first["next_cursor"])
            self.assertEqual(second, {kind: rows[2:], "next_cursor": None, "complete": True})
            service.ensure_plan_owner.assert_not_awaited()
            service.get_plan.assert_awaited_with("parent", "owner", team_id="team")
            guard.assert_awaited_with("team", "owner", {"owner", "admin", "member", "viewer"})
            read.assert_awaited_with("parent", paginate=True, limit=2, cursor=self.IDS[1])

    # contract-test: supporting surface=rest_api assertions=apple-workspaces.isolation
    async def test_child_guards_block_anonymous_foreign_team_and_cross_plan_before_read(self):
        for kind in self.KINDS:
            namespace = self.endpoint(kind)
            endpoint = namespace[f"list_plan_{kind}"]
            read = AsyncMock(return_value=[])
            service = SimpleNamespace(ensure_plan_owner=AsyncMock(), get_plan=AsyncMock(),
                                      plan_methods=SimpleNamespace(**{f"list_{kind}": read}))
            guard = AsyncMock()
            request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(directus_service=SimpleNamespace(team=SimpleNamespace(require_team_role=guard)))))
            namespace["_current_user"].side_effect = PermissionError("unauthorized")
            with self.assertRaises(PermissionError): await endpoint(request, None, "parent", service=service, paginate=True)
            read.assert_not_awaited(); service.ensure_plan_owner.assert_not_awaited()
            namespace["_current_user"].side_effect = None
            guard.side_effect = PermissionError("foreign team")
            with self.assertRaises(PermissionError): await endpoint(request, None, "parent", service=service, paginate=True, team_id="foreign")
            read.assert_not_awaited(); service.get_plan.assert_not_awaited()
            guard.side_effect = None
            service.get_plan.side_effect = LookupError("parent outside this team")
            with self.assertRaises(LookupError): await endpoint(request, None, "outside", service=service, paginate=True, team_id="team")
            read.assert_not_awaited()
            service.ensure_plan_owner.side_effect = LookupError("other owner")
            with self.assertRaises(LookupError): await endpoint(request, None, "other", service=service, paginate=True)
            read.assert_not_awaited()

    # contract-test: supporting surface=rest_api assertions=apple-workspaces.offline-complete,apple-workspaces.isolation
    async def test_child_legacy_shape_and_invalid_paging_preserve_guards(self):
        for kind in self.KINDS:
            namespace = self.endpoint(kind)
            endpoint = namespace[f"list_plan_{kind}"]
            read = AsyncMock(return_value=[])
            service = SimpleNamespace(ensure_plan_owner=AsyncMock(), plan_methods=SimpleNamespace(**{f"list_{kind}": read}))
            self.assertEqual(await endpoint(None, None, "parent", service=service), {kind: []})
            read.assert_awaited_once_with("parent")
            service.ensure_plan_owner.assert_awaited_once_with("parent", "owner")
            read.reset_mock()
            for kwargs in [dict(cursor=self.IDS[0]), dict(paginate=True, limit=501), dict(paginate=True, limit=0), dict(paginate=True, cursor="not-a-uuid")]:
                with self.assertRaises(ValueError): await endpoint(None, None, "parent", service=service, **kwargs)
            read.assert_not_awaited()

    def test_plan_route_query_defaults_are_imported_at_module_load(self):
        tree = ast.parse((ROOT / "backend/core/api/app/routes/user_plans.py").read_text())
        fastapi_names = {alias.name for node in tree.body if isinstance(node, ast.ImportFrom) and node.module == "fastapi" for alias in node.names}
        self.assertIn("Query", fastapi_names)


if __name__ == "__main__":
    unittest.main()
