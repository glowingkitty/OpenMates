# backend/tests/test_status_service_v2.py
# Unit tests for the v2 status service (rewritten status page).
#
# Tests cover: config definitions, database queries (daily status, response times,
# intra-day checks, incidents, uptime percentage), and API endpoints.
#
# Architecture: docs/architecture/infrastructure/status-page.md
# Run: python -m pytest backend/tests/test_status_service_v2.py -v

from __future__ import annotations

import importlib
import os
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
import pytest_asyncio

from backend.status.app.config import (
    SERVICE_GROUPS,
    categorize_test,
    get_all_service_ids,
)

from backend.status.app.database import (
    init_db,
    get_daily_service_status,
    get_response_time_series_hourly,
    get_intraday_checks,
    get_incidents,
    compute_uptime_pct,
)


@pytest.fixture
def tmp_db():
    """Create a temporary SQLite database for testing."""
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    yield path
    os.unlink(path)


# ── Config Tests ──────────────────────────────────────────────────────


class TestConfig:
    def test_service_groups_has_all_expected_groups(self):
        group_names = [name for name, _ in SERVICE_GROUPS]
        assert "Core Platform" in group_names
        assert "AI Providers" in group_names
        assert "Search & Data" in group_names
        assert "Image & Media" in group_names
        assert "Events & Health" in group_names
        assert "Travel" in group_names
        assert "Payment" in group_names
        assert "Email & Moderation" in group_names
        assert len(group_names) == 8

    def test_all_service_ids_not_empty(self):
        ids = get_all_service_ids()
        assert len(ids) > 20  # We have 30+ services

    def test_categorize_test_matches(self):
        assert categorize_test("chat-flow") == "Chat"
        assert categorize_test("buy-credits-flow") == "Payment"
        assert categorize_test("signup-flow") == "Signup"
        assert categorize_test("a11y-keyboard-nav") == "Accessibility"
        assert categorize_test("reminder-email") == "Reminders"
        assert categorize_test("cli-skills-pdf") == "Skills"

    def test_categorize_test_uncategorized(self):
        assert categorize_test("unknown-random-test") is None
        assert categorize_test("") is None

    def test_no_duplicate_service_ids(self):
        seen: set[str] = set()
        for _, components in SERVICE_GROUPS:
            for comp in components:
                for sid in comp.service_ids:
                    assert sid not in seen, f"Duplicate service_id: {sid}"
                    seen.add(sid)


# ── Database Tests ────────────────────────────────────────────────────


class TestDatabase:
    @pytest.mark.asyncio
    async def test_get_daily_service_status_fills_gaps(self, tmp_db):
        await init_db(tmp_db)
        now = datetime.now(timezone.utc)
        five_days_ago = (now - timedelta(days=5)).isoformat()

        import aiosqlite

        async with aiosqlite.connect(tmp_db) as db:
            await db.execute(
                "INSERT INTO status_events (environment, group_name, service_id, service_name, new_status, created_at) VALUES (?, ?, ?, ?, ?, ?)",
                ("prod", "test_group", "test_svc", "Test", "degraded", five_days_ago),
            )
            await db.execute(
                "INSERT INTO service_status (environment, group_name, service_id, service_name, status, last_check_at) VALUES (?, ?, ?, ?, ?, ?)",
                ("prod", "test_group", "test_svc", "Test", "operational", now.isoformat()),
            )
            await db.commit()

        result = await get_daily_service_status(
            tmp_db, environment="prod", service_id="test_svc", days=90
        )
        assert len(result) == 90
        # Each entry should have date and status
        assert all("date" in entry and "status" in entry for entry in result)

    @pytest.mark.asyncio
    async def test_get_daily_service_status_worst_status_per_day(self, tmp_db):
        await init_db(tmp_db)
        now = datetime.now(timezone.utc)
        today = now.strftime("%Y-%m-%d")

        import aiosqlite

        async with aiosqlite.connect(tmp_db) as db:
            # Two events today: operational then down
            await db.execute(
                "INSERT INTO status_events (environment, group_name, service_id, service_name, new_status, created_at) VALUES (?, ?, ?, ?, ?, ?)",
                ("prod", "g", "svc", "S", "operational", f"{today}T08:00:00"),
            )
            await db.execute(
                "INSERT INTO status_events (environment, group_name, service_id, service_name, new_status, created_at) VALUES (?, ?, ?, ?, ?, ?)",
                ("prod", "g", "svc", "S", "down", f"{today}T10:00:00"),
            )
            await db.execute(
                "INSERT INTO service_status (environment, group_name, service_id, service_name, status, last_check_at) VALUES (?, ?, ?, ?, ?, ?)",
                ("prod", "g", "svc", "S", "down", now.isoformat()),
            )
            await db.commit()

        result = await get_daily_service_status(
            tmp_db, environment="prod", service_id="svc", days=1
        )
        assert len(result) == 1
        assert result[0]["status"] == "down"  # worst status wins

    @pytest.mark.asyncio
    async def test_get_response_time_series_hourly(self, tmp_db):
        await init_db(tmp_db)
        now = datetime.now(timezone.utc)

        import aiosqlite

        async with aiosqlite.connect(tmp_db) as db:
            # Insert several response time samples in the same hour
            for i in range(5):
                ts = (now - timedelta(minutes=i * 10)).isoformat()
                await db.execute(
                    "INSERT INTO response_times (environment, service_id, response_time_ms, checked_at) VALUES (?, ?, ?, ?)",
                    ("prod", "anthropic", 40.0 + i * 5, ts),
                )
            await db.commit()

        result = await get_response_time_series_hourly(
            tmp_db, environment="prod", service_id="anthropic", hours=24
        )
        assert len(result) >= 1
        assert "avg_ms" in result[0]
        assert "timestamp" in result[0]

    @pytest.mark.asyncio
    async def test_get_intraday_checks(self, tmp_db):
        await init_db(tmp_db)
        now = datetime.now(timezone.utc)
        today = now.strftime("%Y-%m-%d")

        import aiosqlite

        async with aiosqlite.connect(tmp_db) as db:
            # Insert response time samples for today
            for hour in [8, 12, 16, 20]:
                ts = f"{today}T{hour:02d}:05:00"
                await db.execute(
                    "INSERT INTO response_times (environment, service_id, response_time_ms, checked_at) VALUES (?, ?, ?, ?)",
                    ("prod", "openai", 50.0 + hour, ts),
                )
            await db.commit()

        result = await get_intraday_checks(
            tmp_db, environment="prod", service_id="openai", date=today
        )
        assert len(result) == 4
        assert all("time" in check and "status" in check for check in result)

    @pytest.mark.asyncio
    async def test_get_incidents_groups_events(self, tmp_db):
        await init_db(tmp_db)
        now = datetime.now(timezone.utc)
        two_days_ago = now - timedelta(days=2)

        import aiosqlite

        async with aiosqlite.connect(tmp_db) as db:
            # Down event
            await db.execute(
                "INSERT INTO status_events (environment, group_name, service_id, service_name, new_status, created_at) VALUES (?, ?, ?, ?, ?, ?)",
                ("prod", "AI Providers", "groq", "Groq", "down", two_days_ago.isoformat()),
            )
            # Resolution event
            resolved = (two_days_ago + timedelta(hours=2)).isoformat()
            await db.execute(
                "INSERT INTO status_events (environment, group_name, service_id, service_name, new_status, created_at) VALUES (?, ?, ?, ?, ?, ?)",
                ("prod", "AI Providers", "groq", "Groq", "operational", resolved),
            )
            await db.commit()

        incidents = await get_incidents(tmp_db, environment="prod", since_days=14)
        assert len(incidents) == 1
        assert incidents[0]["component"] == "Groq"
        assert incidents[0]["severity"] == "down"
        assert incidents[0]["resolved_at"] is not None
        assert incidents[0]["duration_minutes"] is not None
        assert len(incidents[0]["updates"]) == 2

    @pytest.mark.asyncio
    async def test_get_incidents_open_incident(self, tmp_db):
        await init_db(tmp_db)
        now = datetime.now(timezone.utc)
        one_hour_ago = (now - timedelta(hours=1)).isoformat()

        import aiosqlite

        async with aiosqlite.connect(tmp_db) as db:
            await db.execute(
                "INSERT INTO status_events (environment, group_name, service_id, service_name, new_status, created_at) VALUES (?, ?, ?, ?, ?, ?)",
                ("prod", "Payment", "stripe", "Stripe", "degraded", one_hour_ago),
            )
            await db.commit()

        incidents = await get_incidents(tmp_db, environment="prod", since_days=14)
        assert len(incidents) == 1
        assert incidents[0]["resolved_at"] is None
        assert incidents[0]["duration_minutes"] is not None  # Should be ~60

    @pytest.mark.asyncio
    async def test_compute_uptime_pct_all_operational(self, tmp_db):
        await init_db(tmp_db)

        import aiosqlite

        async with aiosqlite.connect(tmp_db) as db:
            await db.execute(
                "INSERT INTO service_status (environment, group_name, service_id, service_name, status, last_check_at) VALUES (?, ?, ?, ?, ?, ?)",
                ("prod", "g", "svc", "S", "operational", datetime.now(timezone.utc).isoformat()),
            )
            await db.commit()

        pct = await compute_uptime_pct(
            tmp_db, environment="prod", service_id="svc", days=90
        )
        assert pct == 100.0

    @pytest.mark.asyncio
    async def test_compute_uptime_pct_with_downtime(self, tmp_db):
        await init_db(tmp_db)
        now = datetime.now(timezone.utc)

        import aiosqlite

        async with aiosqlite.connect(tmp_db) as db:
            # Service is currently down
            await db.execute(
                "INSERT INTO service_status (environment, group_name, service_id, service_name, status, last_check_at) VALUES (?, ?, ?, ?, ?, ?)",
                ("prod", "g", "svc", "S", "down", now.isoformat()),
            )
            # Had a down event 10 days ago
            await db.execute(
                "INSERT INTO status_events (environment, group_name, service_id, service_name, new_status, created_at) VALUES (?, ?, ?, ?, ?, ?)",
                ("prod", "g", "svc", "S", "down", (now - timedelta(days=10)).isoformat()),
            )
            await db.commit()

        pct = await compute_uptime_pct(
            tmp_db, environment="prod", service_id="svc", days=90
        )
        # Should be less than 100 since today is "down"
        assert pct < 100.0


# ── API Tests ─────────────────────────────────────────────────────────

# The status service uses relative imports (from app.config import ...) and runs
# standalone, so we need to add its directory to sys.path to import main.py.
_status_dir = str(Path(__file__).resolve().parent.parent / "status")
if _status_dir not in sys.path:
    sys.path.insert(0, _status_dir)

import main as status_main  # noqa: E402

# Reload to ensure we get a fresh module reference
importlib.reload(status_main)
_status_app = status_main.app


class TestAPI:
    @pytest_asyncio.fixture
    async def api_db(self, tmp_db):
        """Initialize DB for API tests."""
        await init_db(tmp_db)
        return tmp_db

    @pytest.mark.asyncio
    async def test_status_v2_returns_all_groups(self, api_db):
        from httpx import ASGITransport, AsyncClient

        original_db = status_main.DB_PATH
        original_load = status_main._load_test_results
        try:
            status_main.DB_PATH = api_db
            status_main._load_test_results = lambda: {
                "total": 0,
                "passed": 0,
                "failed": 0,
                "last_run": None,
                "categories": [],
            }
            transport = ASGITransport(app=_status_app)
            async with AsyncClient(
                transport=transport, base_url="http://test"
            ) as client:
                resp = await client.get("/api/status?env=dev")
        finally:
            status_main.DB_PATH = original_db
            status_main._load_test_results = original_load

        assert resp.status_code == 200
        data = resp.json()
        group_names = [g["name"] for g in data["groups"]]
        assert len(group_names) == 8
        assert "Core Platform" in group_names
        assert "AI Providers" in group_names

    @pytest.mark.asyncio
    async def test_status_v2_response_structure(self, api_db):
        from httpx import ASGITransport, AsyncClient

        original_db = status_main.DB_PATH
        original_load = status_main._load_test_results
        try:
            status_main.DB_PATH = api_db
            status_main._load_test_results = lambda: {
                "total": 2,
                "passed": 1,
                "failed": 1,
                "last_run": "2026-03-25T10:00:00Z",
                "categories": [
                    {
                        "name": "Chat",
                        "total": 2,
                        "passed": 1,
                        "failed": 1,
                        "specs": [],
                    }
                ],
            }
            transport = ASGITransport(app=_status_app)
            async with AsyncClient(
                transport=transport, base_url="http://test"
            ) as client:
                resp = await client.get("/api/status?env=dev")
        finally:
            status_main.DB_PATH = original_db
            status_main._load_test_results = original_load

        assert resp.status_code == 200
        data = resp.json()
        assert "status" in data
        assert "last_updated" in data
        assert "uptime_pct" in data
        assert "groups" in data
        assert "tests" in data
        assert "incidents" in data

    @pytest.mark.asyncio
    async def test_status_v2_intraday_service(self, api_db):
        from httpx import ASGITransport, AsyncClient

        import aiosqlite

        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        # Insert a response time sample so the intraday endpoint returns data
        async with aiosqlite.connect(api_db) as db:
            await db.execute(
                "INSERT INTO response_times (environment, service_id, response_time_ms, checked_at) VALUES (?, ?, ?, ?)",
                ("dev", "openai", 55.0, f"{today}T12:00:00"),
            )
            await db.commit()

        original_db = status_main.DB_PATH
        try:
            status_main.DB_PATH = api_db
            transport = ASGITransport(app=_status_app)
            async with AsyncClient(
                transport=transport, base_url="http://test"
            ) as client:
                resp = await client.get(
                    f"/api/status/intraday?env=dev&date={today}&type=service&id=openai"
                )
        finally:
            status_main.DB_PATH = original_db

        assert resp.status_code == 200
        data = resp.json()
        assert data["type"] == "service"
        assert data["id"] == "openai"
        assert "checks" in data
        assert len(data["checks"]) >= 1

    @pytest.mark.asyncio
    async def test_status_v2_intraday_test(self, api_db):
        from httpx import ASGITransport, AsyncClient

        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")

        original_db = status_main.DB_PATH
        original_load = status_main._load_test_intraday
        try:
            status_main.DB_PATH = api_db
            status_main._load_test_intraday = lambda spec, date: []
            transport = ASGITransport(app=_status_app)
            async with AsyncClient(
                transport=transport, base_url="http://test"
            ) as client:
                resp = await client.get(
                    f"/api/status/intraday?env=dev&date={today}&type=test&id=chat-flow"
                )
        finally:
            status_main.DB_PATH = original_db
            status_main._load_test_intraday = original_load

        assert resp.status_code == 200
        data = resp.json()
        assert data["type"] == "test"
        assert data["id"] == "chat-flow"
        assert "runs" in data

    @pytest.mark.asyncio
    async def test_status_v2_intraday_invalid_type(self, api_db):
        from httpx import ASGITransport, AsyncClient

        original_db = status_main.DB_PATH
        try:
            status_main.DB_PATH = api_db
            transport = ASGITransport(app=_status_app)
            async with AsyncClient(
                transport=transport, base_url="http://test"
            ) as client:
                resp = await client.get(
                    "/api/status/intraday?date=2026-03-25&type=invalid&id=test"
                )
        finally:
            status_main.DB_PATH = original_db

        assert resp.status_code == 400
