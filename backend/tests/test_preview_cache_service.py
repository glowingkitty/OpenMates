# backend/tests/test_preview_cache_service.py
#
# Unit coverage for the preview server's disk cache implementation.
# The cache intentionally avoids diskcache because that dependency stores values
# with pickle and has an unresolved unsafe-deserialization advisory.
#
# These tests cover the security-relevant replacement behavior: binary and JSON
# roundtrips, TTL expiry, and size-based least-recently-used eviction.

from __future__ import annotations

import importlib
from pathlib import Path
import sys
import time
import types


def _load_cache_module(monkeypatch, tmp_path):
    class _Settings:
        cache_dir = str(tmp_path / "global-cache")
        cache_max_size_mb = 1
        metadata_cache_max_size_mb = 1
        cache_max_size_bytes = 1024 * 1024
        metadata_cache_max_size_bytes = 1024 * 1024
        image_cache_ttl_seconds = 60
        favicon_cache_ttl_seconds = 60
        metadata_cache_ttl_seconds = 60

    config_module = types.ModuleType("backend.preview.app.config")
    config_module.settings = _Settings()
    monkeypatch.setitem(sys.modules, "backend.preview.app.config", config_module)

    for module_name in list(sys.modules):
        if module_name.startswith("backend.preview.app.services"):
            monkeypatch.delitem(sys.modules, module_name, raising=False)

    services_package = types.ModuleType("backend.preview.app.services")
    services_package.__path__ = []
    monkeypatch.setitem(sys.modules, "backend.preview.app.services", services_package)

    module_name = "backend.preview.app.services.cache_service"
    module_path = Path(__file__).parents[1] / "preview/app/services/cache_service.py"
    spec = importlib.util.spec_from_file_location(module_name, module_path)
    assert spec and spec.loader

    cache_service = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, module_name, cache_service)
    spec.loader.exec_module(cache_service)
    return cache_service


def test_sqlite_cache_round_trips_binary_and_json(monkeypatch, tmp_path):
    cache_module = _load_cache_module(monkeypatch, tmp_path)
    cache = cache_module._SqliteCache(str(tmp_path / "cache"), size_limit=1024)

    cache.set_binary("image", b"image-bytes", "image/png", ttl=60)
    cache.set_json("metadata", {"title": "OpenMates"}, ttl=60)

    assert cache.get_binary("image") == (b"image-bytes", "image/png")
    assert cache.get_json("metadata") == {"title": "OpenMates"}

    cache.close()


def test_sqlite_cache_expires_entries(monkeypatch, tmp_path):
    cache_module = _load_cache_module(monkeypatch, tmp_path)
    cache = cache_module._SqliteCache(str(tmp_path / "cache"), size_limit=1024)

    cache.set_binary("expired", b"value", "text/plain", ttl=-1)

    assert cache.get_binary("expired") is None
    assert cache.count() == 0

    cache.close()


def test_sqlite_cache_evicts_least_recently_used_entry(monkeypatch, tmp_path):
    cache_module = _load_cache_module(monkeypatch, tmp_path)
    cache = cache_module._SqliteCache(str(tmp_path / "cache"), size_limit=8)

    cache.set_binary("old", b"12345", "text/plain", ttl=60)
    time.sleep(0.01)
    cache.set_binary("new", b"67890", "text/plain", ttl=60)

    assert cache.get_binary("old") is None
    assert cache.get_binary("new") == (b"67890", "text/plain")
    assert cache.volume() <= 8

    cache.close()
