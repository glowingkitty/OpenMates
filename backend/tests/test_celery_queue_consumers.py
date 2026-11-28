# contract-test-file: supporting surface=rest_api assertions=focus-modes.restoration
"""
Every Celery queue a task is routed to has a consuming worker in every runtime.

Production runs the packaged CLI self-host template. On 20 Nov 2026 the
focus-mode auto-confirm timer moved to the `app_ai_routing` queue, which only
the source Compose files consumed. In production the timer
was never picked up, so answers that activated a focus mode stayed empty
(TASK-7184). This guard parses the routing table and the worker commands, so a
queue without a consumer fails here instead of in production.
"""

import re
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
CELERY_CONFIG = ROOT / "backend/core/api/app/tasks/celery_config.py"
FOCUS_CONTINUATION = ROOT / "backend/shared/python_utils/focus_continuation_history.py"
COMPOSE_FILES = (
    ROOT / "backend/core/docker-compose.yml",
    ROOT / "backend/core/docker-compose.selfhost.yml",
    ROOT / "frontend/packages/openmates-cli/templates/core/docker-compose.selfhost.yml",
    ROOT / "frontend/packages/openmates-tui-native/assets/selfhost/core/docker-compose.selfhost.yml",
)
QUEUE_LIST = r"[a-z0-9_,]+"


def _routed_queues() -> set[str]:
    source = CELERY_CONFIG.read_text(encoding="utf-8")
    queues = set(re.findall(r"""['"]queue['"]\s*:\s*['"]([a-z0-9_]+)['"]""", source))
    explicit = re.search(r"_EXPLICIT_TASK_ROUTES = \{(.*?)\n\}", source, re.S)
    assert explicit is not None, "celery_config.py no longer defines _EXPLICIT_TASK_ROUTES"
    queues |= set(re.findall(r""":\s*"([a-z0-9_]+)",""", explicit.group(1)))
    timer = re.search(r'^FOCUS_TIMER_QUEUE = "([a-z0-9_]+)"', FOCUS_CONTINUATION.read_text(encoding="utf-8"), re.M)
    assert timer is not None, "FOCUS_TIMER_QUEUE is no longer a literal queue name"
    queues.add(timer.group(1))
    return queues


def _consumed_queues(compose_path: Path) -> set[str]:
    services = yaml.safe_load(compose_path.read_text(encoding="utf-8"))["services"]
    consumed: set[str] = set()
    for service in services.values():
        command = service.get("command") or ""
        if isinstance(command, list):
            command = " ".join(command)
        for queue_list in re.findall(rf"--queues=({QUEUE_LIST})", command):
            consumed |= set(queue_list.split(","))
    return consumed


# contract-test: supporting surface=rest_api assertions=focus-modes.restoration
def test_routing_table_includes_the_focus_timer_queue() -> None:
    assert "app_ai_routing" in _routed_queues()


# contract-test: supporting surface=rest_api assertions=focus-modes.restoration
@pytest.mark.parametrize("compose_path", COMPOSE_FILES, ids=lambda path: str(path.relative_to(ROOT)))
def test_every_routed_queue_has_a_worker(compose_path: Path) -> None:
    missing = sorted(_routed_queues() - _consumed_queues(compose_path))
    assert not missing, f"{compose_path.relative_to(ROOT)}: no worker consumes {missing}"


# contract-test: supporting surface=rest_api assertions=focus-modes.restoration
@pytest.mark.parametrize("compose_path", COMPOSE_FILES, ids=lambda path: str(path.relative_to(ROOT)))
def test_routing_worker_declares_its_queue(compose_path: Path) -> None:
    worker = yaml.safe_load(compose_path.read_text(encoding="utf-8"))["services"]["app-ai-routing-worker"]
    assert worker["environment"]["CELERY_QUEUES"] == "app_ai_routing"
    assert worker["environment"]["CELERY_METRICS_PORT"] == "9113"


# contract-test: supporting surface=rest_api assertions=focus-modes.restoration
def test_routing_worker_is_in_every_runtime_control_plane() -> None:
    for path in ("frontend/packages/openmates-cli/src/serverPlanning.ts", "scripts/prepare_release_candidate.py"):
        assert '"app-ai-routing-worker"' in (ROOT / path).read_text(encoding="utf-8"), path
