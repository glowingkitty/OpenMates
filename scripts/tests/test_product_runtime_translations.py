"""Tooling contracts for immutable dev runtime translation artifacts."""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
from pathlib import Path

import pytest

from scripts import product_runtime_translations as translations
from scripts import sessions

# contract-test-file: infrastructure


def _checkout(tmp_path: Path) -> Path:
    checkout = tmp_path / "checkout"
    ui = checkout / "frontend/packages/ui"
    (ui / "src/i18n/locales").mkdir(parents=True)
    (ui / "src/i18n/locales/en.json").write_text('{"stale": true}\n', encoding="utf-8")
    (ui / "src/i18n/languages.json").write_text(
        '{"languages":[{"code":"en"},{"code":"de"}]}\n', encoding="utf-8"
    )
    (ui / "scripts").mkdir()
    for name in ("build-translations.js", "validate-locales.js", "languages-config.js"):
        (ui / "scripts" / name).write_text("// fixture\n", encoding="utf-8")
    (ui / "package.json").write_text('{"type":"module"}\n', encoding="utf-8")
    (ui / "node_modules").mkdir()
    (checkout / "frontend/apps/web_app/src").mkdir(parents=True)
    return checkout


def test_source_commit_rejects_dirty_checkout(monkeypatch, tmp_path):
    monkeypatch.setattr(translations, "_git", lambda _checkout, *args: " M tracked.yml" if args[0] == "status" else "a" * 40)
    with pytest.raises(RuntimeError, match="dirty"):
        translations.source_commit(tmp_path)


def test_prepare_publishes_validated_commit_artifact_and_reuses_it(monkeypatch, tmp_path):
    checkout = _checkout(tmp_path)
    store = tmp_path / "artifacts"
    commit = "a" * 40
    monkeypatch.setattr(translations, "source_commit", lambda _checkout: commit)
    monkeypatch.setattr(translations, "_node24_executable", lambda: "node")
    calls = []

    def run(command, *, cwd, capture_output, text):
        calls.append(Path(command[-1]).name)
        if command[-1].endswith("build-translations.js"):
            locales = Path(cwd) / "src/i18n/locales"
            locales.mkdir()
            (locales / "en.json").write_text('{"email":{"completed":{"text":"Ready"}}}\n', encoding="utf-8")
            (locales / "de.json").write_text('{"email":{"completed":{"text":"Fertig"}}}\n', encoding="utf-8")
        return subprocess.CompletedProcess(command, 0, "", "")

    monkeypatch.setattr(translations.subprocess, "run", run)
    overlay = translations.prepare_artifact(checkout, store)
    assert overlay == store / commit / translations.OVERLAY_NAME
    assert calls == ["build-translations.js", "validate-locales.js"]
    assert translations.prepare_artifact(checkout, store) == overlay
    assert translations.selected_overlay(checkout, store) == overlay
    assert calls == ["build-translations.js", "validate-locales.js"]
    assert not any(path.name.startswith(f".{commit}.") for path in store.iterdir())
    artifact = json.loads(overlay.read_text(encoding="utf-8"))
    assert set(artifact["services"]) == translations.TRANSLATION_SERVICES
    assert all(config["volumes"] == [{
        "type": "bind", "source": str(store / commit / "locales"),
        "target": "/translations", "read_only": True,
    }] for config in artifact["services"].values())
    assert "stale" not in (store / commit / "locales/en.json").read_text(encoding="utf-8")


def test_generation_failure_preserves_previous_artifact(monkeypatch, tmp_path):
    checkout = _checkout(tmp_path)
    store = tmp_path / "artifacts"
    commit = "a" * 40
    monkeypatch.setattr(translations, "source_commit", lambda _checkout: commit)
    monkeypatch.setattr(translations, "_node24_executable", lambda: "node")

    def successful_run(command, *, cwd, capture_output, text):
        if command[-1].endswith("build-translations.js"):
            locales = Path(cwd) / "src/i18n/locales"
            locales.mkdir()
            (locales / "en.json").write_text('{"ok":{"text":"yes"}}\n', encoding="utf-8")
            (locales / "de.json").write_text('{"ok":{"text":"ja"}}\n', encoding="utf-8")
        return subprocess.CompletedProcess(command, 0, "", "")

    monkeypatch.setattr(translations.subprocess, "run", successful_run)
    original = translations.prepare_artifact(checkout, store)
    monkeypatch.setattr(translations, "source_commit", lambda _checkout: "b" * 40)
    monkeypatch.setattr(translations.subprocess, "run", lambda command, **_kwargs: subprocess.CompletedProcess(command, 1, "", "bad yaml"))
    with pytest.raises(RuntimeError, match="build-translations.js failed: bad yaml"):
        translations.prepare_artifact(checkout, store)
    assert original.is_file()
    assert not (store / ("b" * 40)).exists()
    assert not any(path.name.startswith("." + "b" * 40) for path in store.iterdir())


def test_source_change_during_generation_is_not_published(monkeypatch, tmp_path):
    checkout = _checkout(tmp_path)
    store = tmp_path / "artifacts"
    commits = iter(["a" * 40, "b" * 40])
    monkeypatch.setattr(translations, "source_commit", lambda _checkout: next(commits))
    monkeypatch.setattr(translations, "_node24_executable", lambda: "node")

    def run(command, *, cwd, capture_output, text):
        if command[-1].endswith("build-translations.js"):
            locales = Path(cwd) / "src/i18n/locales"
            locales.mkdir()
            (locales / "en.json").write_text("{}\n", encoding="utf-8")
            (locales / "de.json").write_text("{}\n", encoding="utf-8")
        return subprocess.CompletedProcess(command, 0, "", "")

    monkeypatch.setattr(translations.subprocess, "run", run)
    with pytest.raises(RuntimeError, match="source changed"):
        translations.prepare_artifact(checkout, store)
    assert not (store / ("a" * 40)).exists()
    assert list(store.iterdir()) == []


def test_corrupt_artifact_fails_closed(monkeypatch, tmp_path):
    checkout = _checkout(tmp_path)
    store = tmp_path / "artifacts"
    commit = "a" * 40
    monkeypatch.setattr(translations, "source_commit", lambda _checkout: commit)
    artifact = store / commit
    (artifact / "locales").mkdir(parents=True)
    (artifact / "locales/en.json").write_text("{}", encoding="utf-8")
    (artifact / "locales/de.json").write_text("{}", encoding="utf-8")
    (artifact / translations.MANIFEST_NAME).write_text(json.dumps({
        "commit": commit, "files": {"en.json": "0" * 64, "de.json": "0" * 64},
    }), encoding="utf-8")
    with pytest.raises(RuntimeError, match="hash mismatch"):
        translations.selected_overlay(checkout, store)


def test_self_consistent_truncated_artifact_is_rejected_on_reuse(monkeypatch, tmp_path):
    checkout = _checkout(tmp_path)
    store = tmp_path / "artifacts"
    commit = "a" * 40
    monkeypatch.setattr(translations, "source_commit", lambda _checkout: commit)
    artifact = store / commit
    locales = artifact / "locales"
    locales.mkdir(parents=True)
    (locales / "en.json").write_text('{"ok":{"text":"yes"}}\n', encoding="utf-8")
    (artifact / translations.MANIFEST_NAME).write_text(json.dumps({
        "commit": commit, "files": {"en.json": translations._sha256(locales / "en.json")},
    }), encoding="utf-8")
    (artifact / translations.OVERLAY_NAME).write_text(
        json.dumps(translations._overlay_content(locales)), encoding="utf-8"
    )
    with pytest.raises(RuntimeError, match="manifest source identity or files are invalid"):
        translations.selected_overlay(checkout, store)
    with pytest.raises(RuntimeError, match="manifest source identity or files are invalid"):
        translations.prepare_artifact(checkout, store)


def test_reuse_rejects_locale_with_non_string_text_even_when_hashes_match(monkeypatch, tmp_path):
    checkout = _checkout(tmp_path)
    store = tmp_path / "artifacts"
    commit = "a" * 40
    monkeypatch.setattr(translations, "source_commit", lambda _checkout: commit)
    artifact = store / commit
    locales = artifact / "locales"
    locales.mkdir(parents=True)
    (locales / "en.json").write_text('{"ok":{"text":{"invalid":true}}}\n', encoding="utf-8")
    (locales / "de.json").write_text('{"ok":{"text":"ja"}}\n', encoding="utf-8")
    (artifact / translations.MANIFEST_NAME).write_text(json.dumps({
        "commit": commit,
        "files": {name: translations._sha256(locales / name) for name in ("en.json", "de.json")},
    }), encoding="utf-8")
    (artifact / translations.OVERLAY_NAME).write_text(
        json.dumps(translations._overlay_content(locales)), encoding="utf-8"
    )
    with pytest.raises(RuntimeError, match="locale text is not a string"):
        translations.selected_overlay(checkout, store)


@pytest.mark.skipif(shutil.which("docker") is None, reason="Docker Compose is unavailable")
def test_compose_overlay_replaces_existing_translation_mount(tmp_path):
    old = tmp_path / "old"
    locales = tmp_path / "artifact/locales"
    old.mkdir()
    locales.mkdir(parents=True)
    base = tmp_path / "compose.json"
    base.write_text(json.dumps({"services": {
        service: {"image": "busybox", "volumes": [f"{old}:/translations"]}
        for service in translations.TRANSLATION_SERVICES
    }}), encoding="utf-8")
    overlay = tmp_path / "overlay.json"
    overlay.write_text(json.dumps(translations._overlay_content(locales)), encoding="utf-8")
    result = subprocess.run(
        ["docker", "compose", "-f", str(base), "-f", str(overlay), "config", "--format", "json"],
        capture_output=True, text=True, check=True,
    )
    services = json.loads(result.stdout)["services"]
    for service in translations.TRANSLATION_SERVICES:
        mounts = [volume for volume in services[service]["volumes"] if volume["target"] == "/translations"]
        assert len(mounts) == 1
        assert mounts[0]["source"] == str(locales)
        assert mounts[0]["read_only"] is True


@pytest.mark.skipif(shutil.which("docker") is None, reason="Docker Compose is unavailable")
def test_overlay_covers_all_rendered_product_compose_translation_consumers(tmp_path):
    """Compose extends can add consumers absent from literal TRANSLATIONS_DIR lines."""
    source = Path(__file__).resolve().parents[2] / "backend/core/docker-compose.yml"
    compose_file = tmp_path / "backend/core/docker-compose.yml"
    compose_file.parent.mkdir(parents=True)
    shutil.copy2(source, compose_file)
    env_file = tmp_path / ".env"
    env_file.write_text("", encoding="utf-8")
    command = ["docker", "compose", "--env-file", str(env_file), "-f", str(compose_file)]
    base = subprocess.run(
        [*command, "config", "--format", "json"],
        capture_output=True, text=True, check=True,
    )
    consumers = {
        name for name, config in json.loads(base.stdout)["services"].items()
        if config.get("environment", {}).get("TRANSLATIONS_DIR") == "/translations"
    }
    assert consumers == translations.TRANSLATION_SERVICES

    locales = tmp_path / "artifact/locales"
    locales.mkdir(parents=True)
    overlay = tmp_path / "artifact/overlay.json"
    overlay.write_text(json.dumps(translations._overlay_content(locales)), encoding="utf-8")
    rendered = subprocess.run(
        [*command, "-f", str(overlay), "config", "--format", "json"],
        capture_output=True, text=True, check=True,
    )
    services = json.loads(rendered.stdout)["services"]
    for service in consumers:
        mounts = [volume for volume in services[service]["volumes"] if volume["target"] == "/translations"]
        assert mounts == [{"type": "bind", "source": str(locales), "target": "/translations", "read_only": True}]


def test_managed_compose_selects_artifact_only_for_runtime_checkout(monkeypatch, tmp_path):
    checkout = _checkout(tmp_path)
    other = _checkout(tmp_path / "other")
    env = tmp_path / ".env"
    env.write_text("OPENMATES_DEPLOYMENT_MODE=self_host\n", encoding="utf-8")
    overlay = tmp_path / "artifact/docker-compose.translations.json"
    monkeypatch.setattr(sessions, "ENV_FILE", env)
    monkeypatch.setattr(sessions, "PRODUCT_RUNTIME_CHECKOUT", checkout)
    monkeypatch.setattr(sessions.product_runtime_translations, "selected_overlay", lambda _checkout, _store: overlay)
    assert str(overlay) not in sessions._docker_compose_command("config", checkout_root=checkout)
    token = sessions._PRODUCT_TRANSLATION_SELECTION_ALLOWED.set(True)
    try:
        command = sessions._docker_compose_command("config", checkout_root=checkout)
        assert str(overlay) not in sessions._docker_compose_command("config", checkout_root=other)
    finally:
        sessions._PRODUCT_TRANSLATION_SELECTION_ALLOWED.reset(token)
    assert command[-3:] == ["-f", str(overlay), "config"]


def test_restart_prepares_after_lease_and_recreates_stale_translation_consumers(monkeypatch, tmp_path):
    checkout = _checkout(tmp_path)
    events = []
    overlay = tmp_path / "artifact/docker-compose.translations.json"
    monkeypatch.setattr(sessions, "PRODUCT_RUNTIME_CHECKOUT", checkout)
    monkeypatch.setattr(sessions, "_docker_checkout_root", lambda _session: checkout)
    monkeypatch.setattr(sessions, "_ensure_product_runtime_checkout", lambda *, refresh: checkout)
    monkeypatch.setattr(sessions, "_current_git_sha", lambda _checkout: "a" * 40)
    monkeypatch.setattr(sessions, "available_docker_services", lambda _checkout: {"api", "workflow-worker"})
    monkeypatch.setattr(sessions, "request_docker_restart", lambda *_args: {"id": "op"})
    monkeypatch.setattr(sessions, "wait_for_docker_operation_admitted", lambda *_args, **_kwargs: events.append("admitted"))
    monkeypatch.setattr(sessions, "_persistent_coordination_enabled", lambda: True)
    monkeypatch.setattr(sessions, "wait_for_docker_test_leases", lambda *_args, **_kwargs: events.append("drained"))
    monkeypatch.setattr(sessions.product_runtime_translations, "prepare_artifact", lambda *_args: events.append("prepared") or overlay)
    monkeypatch.setattr(sessions, "_incoherent_docker_services", lambda *_args: set())
    monkeypatch.setattr(sessions, "_translation_mount_mismatches", lambda *_args: {"workflow-worker"})
    monkeypatch.setattr(sessions, "update_docker_operation", lambda _id, status, **_kwargs: {"id": "op", "status": status})
    monkeypatch.setattr(sessions, "_docker_compose_command", lambda *args, checkout_root: list(args))
    monkeypatch.setattr(sessions, "_run_cmd", lambda command, **_kwargs: (0, "tree\n", ""))
    monkeypatch.setattr(sessions, "_run_cmd_with_heartbeat", lambda command, **_kwargs: events.append(command) or (0, "", ""))
    monkeypatch.setattr(sessions, "wait_for_docker_services_healthy", lambda *_args, **_kwargs: {})
    monkeypatch.setattr(sessions, "_record_product_runtime_services", lambda *_args: None)
    sessions.cmd_docker_restart(argparse.Namespace(session="40fc", service=["api"], timeout=1, poll=1, health_timeout=1, build=False))
    assert events[:3] == ["admitted", "drained", "prepared"]
    assert ["up", "-d", "--no-deps", "--force-recreate", "api", "workflow-worker"] in events
