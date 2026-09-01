"""Regression guard for the web app update reload contract.

The web app no longer ships a PWA or writes CacheStorage entries.
Version updates must navigate immediately without clearing browser storage.
The legacy worker endpoint may only unregister old registrations.
"""

from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
WEB_APP_ROOT = PROJECT_ROOT / "frontend" / "apps" / "web_app"
UI_ROOT = PROJECT_ROOT / "frontend" / "packages" / "ui"


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


# contract-test: infrastructure
def test_app_updates_reload_without_browser_storage_cleanup() -> None:
    layout = read(WEB_APP_ROOT / "src" / "routes" / "+layout.svelte")
    chunk_error_handler = read(UI_ROOT / "src" / "utils" / "chunkErrorHandler.ts")

    assert "window.location.reload()" in layout
    assert "window.location.href = targetUrl" in layout
    assert "window.location.reload()" in chunk_error_handler

    update_sources = layout + chunk_error_handler
    assert "performCleanUpdate" not in update_sources
    assert "caches." not in update_sources
    assert "serviceWorker" not in update_sources
    assert not (UI_ROOT / "src" / "utils" / "cacheManager.ts").exists()


# contract-test: infrastructure
def test_legacy_worker_retirement_cannot_clear_caches_or_reload_clients() -> None:
    app_shell = read(WEB_APP_ROOT / "src" / "app.html")
    retirement_worker = read(WEB_APP_ROOT / "static" / "sw.js")
    vercel_config = read(WEB_APP_ROOT / "vercel.json")

    assert "serviceWorker" not in app_shell
    assert "caches." not in app_shell
    assert "self.registration.unregister()" in retirement_worker
    assert "caches." not in retirement_worker
    assert "client.navigate" not in retirement_worker
    assert "Clear-Site-Data" not in vercel_config
