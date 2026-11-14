#!/usr/bin/env python3
"""E2B credit balance, daily dev spend and runway for developing OpenMates.

The balance is an ESTIMATE. E2B has no API or documented console endpoint that returns the
remaining credit balance (checked 2026-11-14: the public OpenAPI spec, e2b-dev/infra
`spec/openapi.yml`, has no billing, credit or cost route; docs.e2b.dev/billing points only
to the console's usage and billing tabs). So the number shown here is the balance last read
in the E2B console (recorded with `set-balance`) minus the dev E2B spend this host has
recorded since then (the `e2b_dev_capacity` ledger, priced at E2B's published rates).
Product usage of E2B (users' code runs, browse sessions, spec-driven test runs) draws on the
same credits and is NOT in that ledger, so the real balance is lower than the estimate.
Read the real balance at https://console.e2b.dev/?tab=billing at every 14-day review and
record it with `set-balance`.

Low-runway warning: when the estimated balance covers fewer than RUNWAY_WARN_DAYS days at the
current dev spend (average of the last complete days, up to 7), one "Feedback needed" Discord
push goes out through the agent-question webhook, at most once per WARN_INTERVAL_SECONDS.
It is checked after every finished dev sandbox (`e2b_dev_capacity.record_spend`) and by
`check`.

Standard library only (imported by heavy_slot.py under the system python).

Usage:
  python3 scripts/e2b_credits.py                 # balance estimate, daily spend, runway
  python3 scripts/e2b_credits.py --json
  python3 scripts/e2b_credits.py set-balance 412.50 [--as-of 2026-11-14]
  python3 scripts/e2b_credits.py check           # send the warning now if runway is low
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import e2b_dev_capacity  # noqa: E402 - sibling module; path set up above for direct-file loading

RUNWAY_WARN_DAYS = 30
REVIEW_INTERVAL_DAYS = 14
AVERAGE_WINDOW_DAYS = 7
WARN_INTERVAL_SECONDS = 24 * 3600
CONSOLE_BILLING_URL = "https://console.e2b.dev/?tab=billing"
ESTIMATE_LABEL = ("estimate: console balance recorded with set-balance minus the dev E2B spend "
                  "recorded since; product E2B usage is not included, so the real balance is lower")


def _today() -> dt.date:
    return dt.datetime.now(dt.timezone.utc).date()


def balance_file() -> Path:
    return e2b_dev_capacity.capacity_dir() / "credits.json"


def warning_file() -> Path:
    return e2b_dev_capacity.capacity_dir() / "credits-warning.json"


def day_spend(day: dt.date) -> dict:
    path = e2b_dev_capacity.capacity_dir() / f"spend-{day.isoformat()}.json"
    if not path.exists():
        return {"usd": 0.0, "runs": 0, "seconds": 0.0}
    return json.loads(path.read_text())


def ledger_days() -> list[dt.date]:
    days = []
    for path in e2b_dev_capacity.capacity_dir().glob("spend-*.json"):
        try:
            days.append(dt.date.fromisoformat(path.stem.removeprefix("spend-")))
        except ValueError:
            continue
    return sorted(days)


def set_balance(usd: float, as_of: dt.date | None = None) -> dict:
    """Record the balance read in the E2B console; spend already in today's ledger is excluded."""
    if usd < 0:
        raise SystemExit("e2b_credits: the balance cannot be negative")
    day = as_of or _today()
    record = {"balance_usd": round(usd, 2), "as_of": day.isoformat(),
              "ledger_usd_at_record": day_spend(day)["usd"] if day == _today() else 0.0,
              "recorded_at": time.time()}
    balance_file().write_text(json.dumps(record))
    return record


def recorded_balance() -> dict | None:
    if not balance_file().exists():
        return None
    try:
        return json.loads(balance_file().read_text())
    except json.JSONDecodeError as exc:
        raise SystemExit(f"e2b_credits: unreadable {balance_file()}: {exc}") from exc


def average_daily_usd(today: dt.date | None = None) -> tuple[float, int]:
    """(average dev spend per day, number of complete days it covers).

    Uses the last complete days (yesterday back, up to AVERAGE_WINDOW_DAYS) since the first
    ledger day; with no complete day yet, today's spend so far (a lower bound)."""
    today = today or _today()
    days = ledger_days()
    if not days:
        return 0.0, 0
    window = [today - dt.timedelta(days=offset) for offset in range(1, AVERAGE_WINDOW_DAYS + 1)]
    complete = [day for day in window if day >= days[0]]
    if not complete:
        return day_spend(today)["usd"], 0
    return sum(day_spend(day)["usd"] for day in complete) / len(complete), len(complete)


def summary(today: dt.date | None = None) -> dict:
    today = today or _today()
    config = e2b_dev_capacity.settings()
    average, covered = average_daily_usd(today)
    result = {
        "daily_budget_usd": config.daily_budget_usd,
        "dev_share": config.dev_share,
        "spent_today_usd": round(day_spend(today)["usd"], 4),
        "last_days": [{"day": (today - dt.timedelta(days=offset)).isoformat(),
                       "usd": round(day_spend(today - dt.timedelta(days=offset))["usd"], 4)}
                      for offset in range(AVERAGE_WINDOW_DAYS)],
        "average_daily_dev_usd": round(average, 4),
        "average_covers_complete_days": covered,
        "balance": None,
        "real_balance": f"not readable by API; check {CONSOLE_BILLING_URL}",
    }
    record = recorded_balance()
    if record is None:
        result["balance"] = {"status": "unknown",
                             "action": "read the balance in the E2B console and run "
                                       "`python3 scripts/e2b_credits.py set-balance <usd>`"}
        return result
    as_of = dt.date.fromisoformat(record["as_of"])
    spent = sum(day_spend(day)["usd"] for day in ledger_days() if as_of <= day <= today)
    spent = max(0.0, spent - float(record.get("ledger_usd_at_record", 0.0)))
    remaining = record["balance_usd"] - spent
    runway = None if average <= 0 else remaining / average
    review_due = as_of + dt.timedelta(days=REVIEW_INTERVAL_DAYS)
    result["balance"] = {
        "status": "estimate",
        "label": ESTIMATE_LABEL,
        "console_balance_usd": record["balance_usd"],
        "console_balance_as_of": record["as_of"],
        "dev_spend_since_usd": round(spent, 4),
        "estimated_remaining_usd": round(remaining, 2),
        "runway_days": None if runway is None else round(runway, 1),
        "low_runway": runway is not None and runway < RUNWAY_WARN_DAYS,
        "review_due": review_due.isoformat(),
        "review_overdue": today > review_due,
    }
    return result


def render(data: dict) -> str:
    lines = [f"E2B dev spend today: ${data['spent_today_usd']:.2f} of the ${data['daily_budget_usd']:.2f} "
             f"daily budget (dev cap {data['dev_share']:.0%} of the concurrency limit)",
             f"Average dev spend: ${data['average_daily_dev_usd']:.2f}/day "
             + (f"(last {data['average_covers_complete_days']} complete day"
                   f"{'s' if data['average_covers_complete_days'] != 1 else ''})"
                if data["average_covers_complete_days"] else "(today so far; no complete day yet)"),
             "Last days: " + ", ".join(f"{row['day'][5:]} ${row['usd']:.2f}" for row in data["last_days"])]
    balance = data["balance"]
    if balance["status"] == "unknown":
        lines.append("Credit balance: unknown. E2B has no balance API; " + balance["action"] + ".")
    else:
        runway = ("no dev spend yet" if balance["runway_days"] is None
                  else f"about {balance['runway_days']:.0f} days at the current dev spend")
        lines += [f"Credit balance (ESTIMATE): ${balance['estimated_remaining_usd']:.2f} = console "
                  f"${balance['console_balance_usd']:.2f} on {balance['console_balance_as_of']} minus "
                  f"${balance['dev_spend_since_usd']:.2f} dev spend since. Product E2B usage is not "
                  "included, so the real balance is lower.",
                  f"Runway: {runway}" + (f" (below {RUNWAY_WARN_DAYS} days)" if balance["low_runway"] else ""),
                  f"Next review: {balance['review_due']}" + (" (OVERDUE)" if balance["review_overdue"] else "")]
    lines.append(f"Real balance: {CONSOLE_BILLING_URL}")
    return "\n".join(lines)


def warning_message(data: dict) -> str:
    balance = data["balance"]
    return (f"Feedback needed: E2B credits for developing OpenMates last about "
            f"{balance['runway_days']:.0f} more days at the current dev spend "
            f"(${data['average_daily_dev_usd']:.2f}/day), below the {RUNWAY_WARN_DAYS}-day threshold. "
            f"Estimated balance ${balance['estimated_remaining_usd']:.2f} (console "
            f"${balance['console_balance_usd']:.2f} on {balance['console_balance_as_of']} minus "
            f"${balance['dev_spend_since_usd']:.2f} dev spend since; product E2B usage is not included, "
            f"so the real balance is lower). Daily dev budget ${data['daily_budget_usd']:.2f}, cap "
            f"{data['dev_share']:.0%}. Please check the real balance at {CONSOLE_BILLING_URL}, top up "
            "or lower the budget, then record it: python3 scripts/e2b_credits.py set-balance <usd>")


def check(post=None, now: float | None = None, today: dt.date | None = None) -> str | None:
    """Send the low-runway push when due; returns the sent message, else None.

    Raises agent_question.QuestionError when the push is due but cannot be delivered."""
    now = time.time() if now is None else now
    data = summary(today)
    if not (data["balance"] or {}).get("low_runway"):
        return None
    if warning_file().exists():
        last = json.loads(warning_file().read_text())
        if now - float(last.get("ts", 0)) < WARN_INTERVAL_SECONDS:
            return None
    # Imported here: only a due warning needs Discord delivery (keeps heavy_slot imports light).
    import agent_question
    import discord_webhook
    from pending_work_gate import canonical_root

    message = warning_message(data)
    agent_question.deliver(agent_question.webhook(canonical_root()), message,
                           post or discord_webhook.post_message)
    warning_file().write_text(json.dumps({"ts": now, "runway_days": data["balance"]["runway_days"],
                                          "estimated_remaining_usd": data["balance"]["estimated_remaining_usd"]}))
    return message


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--json", action="store_true")
    sub = parser.add_subparsers(dest="command")
    balance = sub.add_parser("set-balance", help="record the balance read in the E2B console")
    balance.add_argument("usd", type=float)
    balance.add_argument("--as-of", type=dt.date.fromisoformat)
    sub.add_parser("check", help="send the low-runway push now if it is due")
    args = parser.parse_args(argv)
    if args.command == "set-balance":
        set_balance(args.usd, args.as_of)
    elif args.command == "check":
        import agent_question

        try:
            sent = check()
        except agent_question.QuestionError as error:
            print(f"e2b_credits: low-runway warning not delivered: {error}", file=sys.stderr)
            return 1
        print("Low-runway warning sent." if sent else "No warning due.")
    data = summary()
    print(json.dumps(data, indent=2) if args.json else render(data))
    return 0


if __name__ == "__main__":
    sys.exit(main())
