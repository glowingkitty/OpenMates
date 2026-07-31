"""
OpenMatesCloud overlay packaging guardrails.

The official cloud loads payment and accounting code through an explicit
OpenMatesCloud overlay. Self-host builds must fail closed: no overlay flag, no
cloud provider initialization, and no payment routes registered from core-only
runtime startup.
"""

from __future__ import annotations

import ast
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[2]
MAIN_PY = ROOT / "backend/core/api/main.py"
CELERY_CONFIG_PY = ROOT / "backend/core/api/app/tasks/celery_config.py"
BASE_TASK_PY = ROOT / "backend/core/api/app/tasks/base_task.py"
SDK_PY = ROOT / "backend/core/api/app/routes/sdk.py"
TEAMS_PY = ROOT / "backend/core/api/app/routes/teams.py"
DEV_COMPOSE_FILE = ROOT / "backend/core/docker-compose.yml"
SELFHOST_COMPOSE_FILES = (
    ROOT / "backend/core/docker-compose.selfhost.yml",
    ROOT / "frontend/packages/openmates-cli/templates/core/docker-compose.selfhost.yml",
)
CLOUD_OVERLAY_ENV = "OPENMATES_CLOUD_OVERLAY_ENABLED"
CLOUD_ROUTE_MODULES = {"credit_note", "creators", "invoice", "payments", "referrals"}
CLOUD_SERVICE_MODULES = {
    "backend.core.api.app.services.invoiceninja.invoiceninja",
    "backend.core.api.app.services.payment.payment_service",
    "backend.core.api.app.services.stripe_product_sync",
}


def _module_level_import_froms(tree: ast.AST) -> list[ast.ImportFrom]:
    return [node for node in getattr(tree, "body", []) if isinstance(node, ast.ImportFrom)]


def _load_compose(path: Path) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def _ancestor_if_tests(tree: ast.AST) -> dict[ast.AST, list[str]]:
    parent_map: dict[ast.AST, ast.AST] = {}
    for parent in ast.walk(tree):
        for child in ast.iter_child_nodes(parent):
            parent_map[child] = parent

    tests_by_node: dict[ast.AST, list[str]] = {}
    for node in ast.walk(tree):
        tests: list[str] = []
        current = parent_map.get(node)
        while current is not None:
            if isinstance(current, ast.If):
                tests.append(ast.unparse(current.test))
            current = parent_map.get(current)
        tests_by_node[node] = tests
    return tests_by_node


def _calls_guarded_by_cloud_billing(
    tree: ast.AST,
    predicate: callable[[ast.Call], bool],
) -> bool:
    ancestor_tests = _ancestor_if_tests(tree)
    matched = False
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and predicate(node):
            matched = True
            guarded = any("cloud_billing_enabled" in test for test in ancestor_tests[node])
            if not guarded:
                return False
    return matched


def test_cloud_billing_requires_explicit_openmatescloud_overlay(monkeypatch) -> None:
    monkeypatch.delenv(CLOUD_OVERLAY_ENV, raising=False)
    monkeypatch.setenv("SERVER_ENVIRONMENT", "development")
    monkeypatch.setenv("PRODUCTION_URL", "http://localhost:5173")
    monkeypatch.setenv("FRONTEND_URLS", "http://localhost:5173")

    from backend.core.api.app.utils import server_mode

    assert server_mode.is_payment_enabled() is True
    assert server_mode.is_openmates_cloud_overlay_enabled() is False
    assert server_mode.is_cloud_billing_enabled() is False

    monkeypatch.setenv(CLOUD_OVERLAY_ENV, "true")

    assert server_mode.is_openmates_cloud_overlay_enabled() is True
    assert server_mode.is_cloud_billing_enabled() is True


def test_dev_compose_does_not_enable_openmatescloud_overlay_by_default() -> None:
    compose = _load_compose(DEV_COMPOSE_FILE)

    for service_name in ("api", "task-worker"):
        environment = compose["services"][service_name]["environment"]
        assert environment[CLOUD_OVERLAY_ENV] == "${OPENMATES_CLOUD_OVERLAY_ENABLED:-false}"


def test_selfhost_compose_explicitly_disables_openmatescloud_overlay() -> None:
    for compose_path in SELFHOST_COMPOSE_FILES:
        compose = _load_compose(compose_path)
        services = compose["services"]

        assert "openmatescloud" not in {name.lower() for name in services}, compose_path
        for service_name in ("api", "task-worker", "task-scheduler"):
            environment = services[service_name]["environment"]
            assert environment[CLOUD_OVERLAY_ENV] == "false", f"{compose_path}:{service_name}"


def test_api_startup_payment_providers_are_guarded_by_cloud_billing() -> None:
    tree = ast.parse(MAIN_PY.read_text(encoding="utf-8"))

    assert _calls_guarded_by_cloud_billing(
        tree,
        lambda call: isinstance(call.func, ast.Attribute) and call.func.attr == "create_billing_services",
    )
    assert _calls_guarded_by_cloud_billing(
        tree,
        lambda call: isinstance(call.func, ast.Attribute) and call.func.attr == "initialize_billing_providers",
    )


def test_core_api_does_not_eager_import_cloud_billing_routes_or_services() -> None:
    tree = ast.parse(MAIN_PY.read_text(encoding="utf-8"))
    offenders: list[str] = []

    for node in _module_level_import_froms(tree):
        if node.module == "backend.core.api.app.routes":
            offenders.extend(alias.name for alias in node.names if alias.name in CLOUD_ROUTE_MODULES)
        if node.module in CLOUD_SERVICE_MODULES:
            offenders.append(node.module)

    assert offenders == []


def test_core_worker_bootstrap_does_not_eager_import_cloud_accounting_services() -> None:
    offenders: list[str] = []
    for path in (CELERY_CONFIG_PY, BASE_TASK_PY):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        offenders.extend(
            f"{path.name}:{node.module}"
            for node in _module_level_import_froms(tree)
            if node.module in CLOUD_SERVICE_MODULES
        )

    assert offenders == []


def test_core_api_delegates_billing_hooks_to_openmatescloud_overlay() -> None:
    source = MAIN_PY.read_text(encoding="utf-8")

    assert "openmatescloud.api.billing_overlay" in source
    assert "_load_openmatescloud_billing_overlay" in source
    assert "create_billing_services" in source
    assert "initialize_billing_providers" in source
    assert "register_billing_routes" in source


def test_payment_router_registration_is_guarded_by_cloud_billing() -> None:
    tree = ast.parse(MAIN_PY.read_text(encoding="utf-8"))

    assert _calls_guarded_by_cloud_billing(
        tree,
        lambda call: isinstance(call.func, ast.Attribute) and call.func.attr == "register_billing_routes",
    )


def test_create_app_has_no_stale_payment_enabled_local_guard() -> None:
    tree = ast.parse(MAIN_PY.read_text(encoding="utf-8"))
    create_app = next(
        node for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef) and node.name == "create_app"
    )

    stale_names = [node.lineno for node in ast.walk(create_app) if isinstance(node, ast.Name) and node.id == "payment_enabled"]

    assert stale_names == []


def test_sdk_payment_facade_requires_cloud_billing_before_payment_routes() -> None:
    source = SDK_PY.read_text(encoding="utf-8")

    assert "def _require_cloud_billing_enabled" in source
    assert "def _is_cloud_payment_sdk_path" in source
    assert source.index("_require_cloud_billing_enabled(request)") < source.index('payments_routes = _sdk_route_module("payments")')


def test_team_bank_transfer_payment_dependency_fails_closed() -> None:
    source = TEAMS_PY.read_text(encoding="utf-8")
    function_start = source.index("def get_payment_service")
    function_end = source.index("async def _current_user", function_start)
    function_source = source[function_start:function_end]

    assert "is_cloud_billing_enabled" in function_source
    assert "Feature not available on this server edition" in function_source
    assert 'getattr(request.app.state, "payment_service", None)' in function_source
