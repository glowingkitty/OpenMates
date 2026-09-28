"""Contract tests for the checked-in host test schedule installer."""

# contract-test-file: infrastructure

from pathlib import Path

from scripts.test_schedule_setup import BEGIN, END, managed_block, replace_managed_schedule


def test_managed_schedule_contains_all_test_lanes() -> None:
    block = managed_block(Path("/srv/OpenMates"))
    assert "run-tests-daily.sh --detach" in block
    assert "daily_ci_notification.py --send" in block
    assert "# CI migration HOLD --hourly-dev" in block
    assert "# CI migration HOLD --prod-free-hourly" in block
    assert "# CI migration HOLD --prod-paid-chat" in block
    assert "# CI migration HOLD --prod-app-skill" in block
    assert "scripts/tests.py run" not in block
    assert "CRON_TZ=Europe/Berlin" in block


def test_replacement_removes_legacy_commands_and_is_idempotent() -> None:
    current = "\n".join([
        "1 * * * * keep-me",
        "0 8-18 * * * python3 scripts/run_tests.py --hourly-dev",
        BEGIN,
        "stale managed content",
        END,
    ])
    first = replace_managed_schedule(current, Path("/srv/OpenMates"))
    second = replace_managed_schedule(first, Path("/srv/OpenMates"))
    assert first == second
    assert "keep-me" in first
    assert "scripts/run_tests.py --hourly-dev" not in first


def test_replacement_can_target_the_canonical_checkout() -> None:
    canonical = Path("/srv/OpenMates")

    rendered = replace_managed_schedule("", canonical)

    assert f"{canonical}/scripts/run-tests-daily.sh" in rendered
    assert ".openmates-agent-worktrees" not in rendered
