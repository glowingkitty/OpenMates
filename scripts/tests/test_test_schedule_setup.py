"""Contract tests for the checked-in host test schedule installer."""

# contract-test-file: infrastructure

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from scripts import run_tests
from scripts.test_schedule_setup import (
    BEGIN,
    END,
    PROD_APP_SKILL_BERLIN_HOURS,
    PROD_FREE_HOURLY_BERLIN_HOURS,
    PROD_PAID_CHAT_BERLIN_HOURS,
    berlin_hours_as_utc_cron,
    managed_block,
    replace_managed_schedule,
)


def test_managed_schedule_contains_all_test_lanes() -> None:
    block = managed_block(Path("/srv/OpenMates"))
    assert "run-tests-daily.sh --detach" in block
    assert "daily_ci_notification.py --send" in block
    assert "# CI migration HOLD --hourly-dev" in block
    assert "# CI migration HOLD --prod-free-hourly" not in block
    assert "5 4,5,6,7,8,9,10,11,12,13,14,15,16,17,18,19,20,21,22 * * * " in block
    assert "scripts/prod_smoke_cron.py free-hourly'" in block
    assert "# CI migration HOLD --prod-paid-chat" not in block
    assert "# CI migration HOLD --prod-app-skill" not in block
    assert "10 5,6,11,12,17,18 * * * " in block and "scripts/prod_smoke_cron.py paid-chat'" in block
    assert "15 7,8 * * * " in block and "scripts/prod_smoke_cron.py app-skill'" in block
    assert "scripts/tests.py run" not in block
    assert "scripts/run_tests.py --prod" not in block
    # The host cron ignores CRON_TZ; a Berlin CRON_TZ line would only mislead (TASK-4996).
    assert "CRON_TZ=Europe/Berlin" not in block


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

def test_nightly_suite_runs_on_weekdays_only() -> None:
    block = managed_block(Path("/srv/OpenMates"))
    nightly = [line for line in block.splitlines() if "run-tests-daily.sh" in line]
    assert nightly and nightly[0].startswith("0 3 * * 1-5 ")


def test_berlin_hours_match_the_run_tests_gate() -> None:
    assert frozenset(PROD_PAID_CHAT_BERLIN_HOURS) == run_tests.PROD_PAID_CHAT_HOURS
    assert frozenset(PROD_APP_SKILL_BERLIN_HOURS) == run_tests.PROD_APP_SKILL_HOURS
    assert PROD_FREE_HOURLY_BERLIN_HOURS == range(
        run_tests.PROD_FREE_HOURLY_START_HOUR, run_tests.PROD_FREE_HOURLY_END_HOUR + 1
    )


def _suite_cron_line(suite: str) -> str:
    block = managed_block(Path("/srv/OpenMates"))
    return next(line for line in block.splitlines() if f"prod_smoke_cron.py {suite}'" in line)


@pytest.mark.parametrize(
    ("suite", "gate_kwargs", "berlin_hours"),
    [
        ("paid-chat", {"allowed_hours": run_tests.PROD_PAID_CHAT_HOURS}, PROD_PAID_CHAT_BERLIN_HOURS),
        ("app-skill", {"allowed_hours": run_tests.PROD_APP_SKILL_HOURS}, PROD_APP_SKILL_BERLIN_HOURS),
        (
            "free-hourly",
            {"hour_range": (run_tests.PROD_FREE_HOURLY_START_HOUR, run_tests.PROD_FREE_HOURLY_END_HOUR)},
            PROD_FREE_HOURLY_BERLIN_HOURS,
        ),
    ],
)
def test_utc_cron_runs_each_berlin_slot_exactly_once_all_year(monkeypatch, suite, gate_kwargs, berlin_hours) -> None:
    """Replay a full year of UTC cron firings (cron ignores CRON_TZ) through the real gate.

    Regression for TASK-4996: `10 7,13,19` fired at UTC, the gate saw Berlin
    08/14/20 and skipped every paid-chat run.
    """
    minute, hour_field = _suite_cron_line(suite).split()[:2]
    utc_hours = {int(hour) for hour in hour_field.split(",")}
    monkeypatch.setattr(run_tests, "_log", lambda _message: None)

    ran: dict[tuple, int] = {}
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    for step in range(366 * 24):
        fired_at = start + timedelta(hours=step, minutes=int(minute))
        if fired_at.hour not in utc_hours:
            continue
        berlin = fired_at.astimezone(run_tests.BERLIN_TZ)
        monkeypatch.setattr(run_tests, "_berlin_now", lambda berlin=berlin: berlin)
        if not run_tests._skip_outside_prod_schedule(force=False, mode_label=suite, **gate_kwargs):
            key = (berlin.date(), berlin.hour)
            ran[key] = ran.get(key, 0) + 1

    assert all(count == 1 for count in ran.values())
    for day_offset in range(365):
        day = (datetime(2026, 1, 1) + timedelta(days=day_offset)).date()
        missing = [hour for hour in berlin_hours if (day, hour) not in ran]
        # The spring-forward night has no 02:00 Berlin; no suite is scheduled then.
        assert not missing, f"{suite} misses Berlin {day} hours {missing}"


def test_berlin_hours_as_utc_cron_covers_both_offsets() -> None:
    assert berlin_hours_as_utc_cron([7, 13, 19]) == "5,6,11,12,17,18"
    assert berlin_hours_as_utc_cron([0]) == "22,23"
