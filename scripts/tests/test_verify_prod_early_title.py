"""Tooling test: the post-deploy early-title check reads prod state and logs correctly."""

import importlib.util
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "verify_prod_early_title.py"
spec = importlib.util.spec_from_file_location("verify_prod_early_title", SCRIPT)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)

ACTIVE = '{"protocol_epoch": 1, "sends_paused": false, "legacy_in_flight": 0}'
API_LOGS = (
    "INFO [RecoveryCutover] activated protocol epoch 1\n"
    'INFO Chat recovery protocol phase completed {"recovery_phase": "enqueue_inference"}\n'
)
WORKER_LOGS = "INFO Early chat metadata ready model=example-model\n"


def by_name(result):
    return {check["check"]: check["passed"] for check in result["checks"]}


# contract-test: tooling
def test_release_with_cutover_and_early_title_passes() -> None:
    result = module.evaluate(ACTIVE, API_LOGS, WORKER_LOGS)
    assert result["passed"] is True


# contract-test: tooling
def test_epoch_zero_server_fails_every_recovery_check() -> None:
    result = module.evaluate('{"protocol_epoch": 0, "sends_paused": false, "legacy_in_flight": 0}',
                             "INFO started\n", "")
    assert result["passed"] is False
    assert by_name(result) == {"cutover_state": False, "cutover_logged": False,
                               "recovery_enqueue": False, "early_title": False}


# contract-test: tooling
def test_paused_sends_or_unreadable_state_fail_the_state_check() -> None:
    paused = module.evaluate('{"protocol_epoch": 1, "sends_paused": true}', API_LOGS, WORKER_LOGS)
    unreadable = module.evaluate("Traceback: boom", API_LOGS, WORKER_LOGS)
    assert by_name(paused)["cutover_state"] is False
    assert by_name(unreadable)["cutover_state"] is False


# contract-test: tooling
def test_unavailable_early_title_attempts_do_not_count() -> None:
    result = module.evaluate(ACTIVE, API_LOGS, "INFO Early chat metadata attempt unavailable model=x kind=Timeout\n")
    assert by_name(result)["early_title"] is False


# contract-test: tooling
def test_remote_commands_are_read_only_and_quote_the_time() -> None:
    commands = module.remote_commands("2026-11-20T10:00:00Z; rm -rf /")
    assert commands["api_logs"].startswith("docker logs api --since '")
    assert commands["worker_logs"].startswith("docker logs app-ai-worker --since '")
    assert commands["state"].startswith("docker exec api python -c ")
    assert all("rm -rf" not in command.split("'")[0] for command in commands.values())
