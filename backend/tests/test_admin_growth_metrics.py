# contract-test-file: tooling
# Aggregate growth counts for the daily meeting (POST /v1/admin/debug/growth-metrics).
# Pure counting rules only: exclusions, windows, gift cards, refunds, first purchase.
# The route itself is proven over REST against the dev API (admin key, 401 without it).

from datetime import datetime, timedelta, timezone
import hashlib

import pytest

pytest.importorskip("redis.asyncio")

from backend.core.api.app.routes.admin_growth_metrics import (
    compute_growth_metrics,
    configured_test_account_hashes,
    email_hash,
    parse_moment,
)

NOW = datetime(2026, 11, 13, 10, 0, tzinfo=timezone.utc)
SINCE = NOW - timedelta(days=1)


def _user(uid, *, started, online=None, completed=True, admin=False, email=None):
    return {"id": uid, "is_admin": admin, "signup_completed": completed,
            "signup_started_at": started.isoformat() if started else None,
            "last_online_timestamp": str(int(online.timestamp())) if online else None,
            "hashed_email": email_hash(email) if email else "h-" + uid}


def _invoice(uid, when, **extra):
    return {"user_id_hash": hashlib.sha256(uid.encode()).hexdigest(), "date": when.isoformat(),
            "is_gift_card": False, "refund_status": "none", "has_chargeback": False, **extra}


def test_counts_leave_out_admin_test_and_own_accounts_and_their_purchases():
    users = [
        _user("uid-new", started=NOW - timedelta(hours=3), online=NOW - timedelta(hours=1)),
        _user("uid-lastweek", started=NOW - timedelta(days=3), online=NOW - timedelta(days=2)),
        _user("uid-prevweek", started=NOW - timedelta(days=10), online=NOW - timedelta(days=9)),
        _user("uid-abandoned", started=NOW - timedelta(hours=2), completed=False),
        _user("uid-admin", started=NOW - timedelta(hours=2), online=NOW, admin=True),
        _user("uid-founder", started=NOW - timedelta(hours=2), online=NOW, email="Founder@Example.org"),
    ]
    invoices = [
        _invoice("uid-new", NOW - timedelta(hours=2)),
        _invoice("uid-lastweek", NOW - timedelta(days=20)),  # paid before: not a new paying user
        _invoice("uid-lastweek", NOW - timedelta(hours=5)),
        _invoice("uid-prevweek", NOW - timedelta(days=9), refund_status="full"),
        _invoice("uid-prevweek", NOW - timedelta(days=8), is_gift_card=True),
        _invoice("uid-admin", NOW - timedelta(hours=1)),
        _invoice("uid-founder", NOW - timedelta(hours=1)),
    ]
    m = compute_growth_metrics(users, invoices, now=NOW, since=SINCE,
                               excluded_email_hashes={email_hash("founder@example.org")})
    assert m["total_users"] == 3
    assert m["excluded_accounts"] == 2
    assert m["paying_users_total"] == 3  # refunded invoice still made prevweek a payer once
    assert m["active_users"] == {"last_24_hours": 1, "last_7_days": 2}
    since, week, before = (m["periods"][k] for k in ("since_last_meeting", "last_7_days", "previous_7_days"))
    assert since == {"signups_completed": 1, "signups_started": 2, "new_paying_users": 1, "credit_purchases": 2}
    assert week["signups_completed"] == 2 and week["new_paying_users"] == 1
    assert before == {"signups_completed": 1, "signups_started": 1, "new_paying_users": 1, "credit_purchases": 0}
    text = repr(m)
    assert "uid-" not in text and email_hash("founder@example.org") not in text  # counts only, no ids or hashes


def test_previous_since_window_has_the_same_length():
    users = [_user("a", started=SINCE - timedelta(hours=12)), _user("b", started=SINCE - timedelta(hours=30))]
    m = compute_growth_metrics(users, [], now=NOW, since=SINCE, excluded_email_hashes=set())
    assert m["periods"]["since_last_meeting_previous"]["signups_completed"] == 1


def test_configured_test_accounts_and_time_formats():
    env = {"OPENMATES_TEST_ACCOUNT_5_EMAIL": "t5@example.org", "OPENMATES_TEST_ACCOUNT_5_PASSWORD": "x",
           "OTHER_EMAIL": "o@example.org"}
    assert configured_test_account_hashes(env) == {email_hash("t5@example.org")}
    assert parse_moment("1763028000") == datetime.fromtimestamp(1763028000, tz=timezone.utc)
    assert parse_moment("2026-11-13T09:00:00Z") == datetime(2026, 11, 13, 9, tzinfo=timezone.utc)
    assert parse_moment("garbage") is None and parse_moment(None) is None
