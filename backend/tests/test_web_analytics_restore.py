# backend/tests/test_web_analytics_restore.py
#
# Regression coverage for encrypted web analytics backup restoration.
# Verifies that persistent Redis counters are not incremented again after
# an API-only restart, while the consumed encrypted backup is removed.

import asyncio
import json
import sys
from types import SimpleNamespace

try:
    import user_agents  # noqa: F401
except ModuleNotFoundError:
    sys.modules["user_agents"] = SimpleNamespace(parse=lambda _value: None)

from backend.core.api.app.services import web_analytics_service as analytics_module
from backend.core.api.app.services.web_analytics_service import WebAnalyticsService


class FakePipeline:
    def __init__(self):
        self.increments = []

    def hincrby(self, key, field, value):
        self.increments.append((key, field, value))
        return self

    def expire(self, key, ttl):
        self.expiry = (key, ttl)
        return self

    async def execute(self):
        return []


class FakeRedis:
    def __init__(self, *, key_exists=True):
        self.key_exists = key_exists
        self.pipeline_instance = FakePipeline()

    async def exists(self, key):
        return int(self.key_exists)

    def pipeline(self):
        return self.pipeline_instance


class FakeCache:
    def __init__(self, client):
        self._client = client

    @property
    async def client(self):
        return self._client


class FakeEncryptionService:
    async def decrypt(self, ciphertext, *, key_name):
        assert ciphertext == "vault:v1:test"
        return json.dumps(
            {
                "daily": {
                    "2026-08-05": {
                        "page_loads": 12,
                        "countries:DE": 7,
                    }
                }
            }
        )


def test_restore_skips_days_already_present_in_redis(tmp_path, monkeypatch):
    backup_path = tmp_path / "web_analytics_backup.json"
    backup_path.write_text(
        json.dumps({"encrypted": "vault:v1:test", "version": 1}),
        encoding="utf-8",
    )
    monkeypatch.setattr(analytics_module, "WEB_ANALYTICS_BACKUP_PATH", str(backup_path))

    redis = FakeRedis()
    service = WebAnalyticsService(FakeCache(redis))

    restored = asyncio.run(service.restore_from_disk(FakeEncryptionService()))

    assert restored == 0
    assert redis.pipeline_instance.increments == []
    assert not backup_path.exists()


def test_restore_populates_missing_redis_day(tmp_path, monkeypatch):
    backup_path = tmp_path / "web_analytics_backup.json"
    backup_path.write_text(
        json.dumps({"encrypted": "vault:v1:test", "version": 1}),
        encoding="utf-8",
    )
    monkeypatch.setattr(analytics_module, "WEB_ANALYTICS_BACKUP_PATH", str(backup_path))

    redis = FakeRedis(key_exists=False)
    service = WebAnalyticsService(FakeCache(redis))

    restored = asyncio.run(service.restore_from_disk(FakeEncryptionService()))

    daily_key = "web:analytics:daily:2026-08-05"
    assert restored == 1
    assert redis.pipeline_instance.increments == [
        (daily_key, "page_loads", 12),
        (daily_key, "countries:DE", 7),
    ]
    assert redis.pipeline_instance.expiry == (
        daily_key,
        analytics_module.WEB_ANALYTICS_REDIS_TTL,
    )
    assert not backup_path.exists()
