# contract-test-file: tooling
"""Contracts for the E2B credit view: $100 daily budget, labelled balance estimate, runway push.

Scope: local ledger files and a fake Discord post; no E2B key or network.
Run: python3 -m pytest scripts/tests/test_e2b_credits.py
"""

from __future__ import annotations

import datetime as dt
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import agent_question  # noqa: E402 - scripts/ is added to sys.path above
import e2b_credits as credits  # noqa: E402 - scripts/ is added to sys.path above
import e2b_dev_capacity as cap  # noqa: E402 - scripts/ is added to sys.path above

TODAY = dt.date(2026, 11, 14)


@pytest.fixture(autouse=True)
def state(tmp_path: Path, monkeypatch) -> Path:
    monkeypatch.setattr(cap.host_load_guard, "state_dir", lambda: tmp_path)
    for name, _ in cap.ENV_OVERRIDES.values():
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(credits, "_today", lambda: TODAY)
    monkeypatch.setattr(agent_question, "webhook", lambda root: "https://example.org/hook")
    return tmp_path


def ledger(day: dt.date, usd: float) -> None:
    (cap.capacity_dir() / f"spend-{day.isoformat()}.json").write_text(
        json.dumps({"usd": usd, "runs": 1, "seconds": 60.0}))


# contract-test: tooling
def test_daily_budget_is_one_hundred_dollars_and_the_cap_stays_seventy_percent() -> None:
    config = cap.settings()
    assert config.daily_budget_usd == 100.0
    assert config.dev_share == 0.70


# contract-test: tooling
def test_without_a_console_balance_the_view_says_unknown_and_how_to_record_it() -> None:
    ledger(TODAY, 1.25)
    data = credits.summary()
    assert data["balance"]["status"] == "unknown"
    assert "set-balance" in data["balance"]["action"]
    text = credits.render(data)
    assert "$1.25 of the $100.00 daily budget" in text
    assert "Credit balance: unknown" in text and "console.e2b.dev" in text
    assert credits.check(post=lambda **_: pytest.fail("no warning without a balance")) is None


# contract-test: tooling
def test_balance_is_a_labelled_estimate_minus_dev_spend_since_the_reading() -> None:
    for offset in range(1, 8):
        ledger(TODAY - dt.timedelta(days=offset), 2.0)
    ledger(TODAY, 1.0)
    credits.set_balance(500.0)  # read in the console today, after $1.00 of today's spend
    ledger(TODAY, 3.0)  # $2.00 more spent after the reading
    balance = credits.summary()["balance"]
    assert balance["status"] == "estimate"
    assert "product E2B usage is not included" in balance["label"]
    assert balance["dev_spend_since_usd"] == pytest.approx(2.0)
    assert balance["estimated_remaining_usd"] == pytest.approx(498.0)
    assert balance["runway_days"] == pytest.approx(249.0)
    assert balance["review_due"] == "2026-11-28" and not balance["low_runway"]
    assert "ESTIMATE" in credits.render(credits.summary())


# contract-test: tooling
def test_low_runway_sends_one_feedback_needed_push_per_day() -> None:
    for offset in range(1, 8):
        ledger(TODAY - dt.timedelta(days=offset), 5.0)
    credits.set_balance(100.0, as_of=TODAY - dt.timedelta(days=2))  # minus $10 since -> $90, 18 days
    sent: list[str] = []

    def post(webhook_url: str, payload: dict) -> dict:
        sent.append(payload["content"])
        return {"id": "1"}

    message = credits.check(post=post, now=1_000_000.0)
    assert message and message.startswith("Feedback needed:")
    assert "about 18 more days" in message and "below the 30-day threshold" in message
    assert "set-balance" in message and "real balance is lower" in message
    assert credits.check(post=post, now=1_000_000.0 + 3600) is None
    assert credits.check(post=post, now=1_000_000.0 + 25 * 3600) is not None
    assert len(sent) == 2


# contract-test: tooling
def test_record_spend_checks_the_runway_and_a_failed_push_never_fails_the_run(monkeypatch, capsys) -> None:
    def broken() -> None:
        raise agent_question.QuestionError("Discord delivery was not confirmed")

    monkeypatch.setattr(credits, "check", broken)
    assert cap.record_spend(60, 8, 8192) > 0
    assert "low-runway warning not delivered" in capsys.readouterr().err


# contract-test: tooling
def test_capacity_status_includes_the_credit_view() -> None:
    assert cap.status()["credits"]["balance"]["status"] == "unknown"
