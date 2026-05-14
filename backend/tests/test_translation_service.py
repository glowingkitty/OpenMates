# backend/tests/test_translation_service.py
#
# Tests runtime translation loading behavior.
# Translation YAML remains the authoring source, but backend services should use
# generated locale JSON when available to avoid slow YAML parsing in Celery
# worker request paths. These tests keep that performance-sensitive preference
# explicit while preserving YAML fallback coverage.

from backend.core.api.app.services.translations import TranslationService


def _clear_translation_caches() -> None:
    TranslationService._class_translations_cache.clear()
    TranslationService._class_yaml_cache.clear()


def test_translation_service_prefers_generated_locale_json(tmp_path, monkeypatch):
    locales_dir = tmp_path / "locales"
    sources_dir = tmp_path / "sources"
    locales_dir.mkdir()
    sources_dir.mkdir()

    (locales_dir / "en.json").write_text(
        '{"app_skills": {"web": {"search": {"text": "Fast JSON description"}}}}',
        encoding="utf-8",
    )
    (sources_dir / "app_skills.yml").write_text(
        "web.search:\n  en: Slow YAML description\n",
        encoding="utf-8",
    )

    monkeypatch.setenv("TRANSLATIONS_DIR", str(locales_dir))
    monkeypatch.setenv("TRANSLATIONS_SOURCES_DIR", str(sources_dir))
    _clear_translation_caches()

    service = TranslationService()

    assert service.get_nested_translation("app_skills.web.search") == "Fast JSON description"
    assert TranslationService._class_yaml_cache == {}


def test_translation_service_warm_cache_loads_generated_locale_json(tmp_path, monkeypatch):
    locales_dir = tmp_path / "locales"
    sources_dir = tmp_path / "sources"
    locales_dir.mkdir()
    sources_dir.mkdir()

    (locales_dir / "en.json").write_text(
        '{"common": {"ok": {"text": "OK"}}}',
        encoding="utf-8",
    )

    monkeypatch.setenv("TRANSLATIONS_DIR", str(locales_dir))
    monkeypatch.setenv("TRANSLATIONS_SOURCES_DIR", str(sources_dir))
    _clear_translation_caches()

    service = TranslationService()
    service.warm_cache("en")

    assert TranslationService._class_translations_cache["en"]["common"]["ok"]["text"] == "OK"
    assert TranslationService._class_yaml_cache == {}


def test_translation_service_falls_back_to_yaml_when_generated_json_missing(tmp_path, monkeypatch):
    locales_dir = tmp_path / "locales"
    sources_dir = tmp_path / "sources"
    locales_dir.mkdir()
    sources_dir.mkdir()

    (sources_dir / "app_skills.yml").write_text(
        "web.search:\n  en: YAML fallback description\n",
        encoding="utf-8",
    )
    (sources_dir / "languages.json").write_text("{}", encoding="utf-8")

    # The service expects languages.json next to the real source tree, not the
    # temporary one, so use the repo default for language discovery and only
    # override the YAML sources/locales directories.
    monkeypatch.setenv("TRANSLATIONS_DIR", str(locales_dir))
    monkeypatch.setenv("TRANSLATIONS_SOURCES_DIR", str(sources_dir))
    monkeypatch.setenv("SERVER_ENVIRONMENT", "development")
    _clear_translation_caches()

    service = TranslationService()

    assert service.get_nested_translation("app_skills.web.search") == "YAML fallback description"
    assert "app_skills" in TranslationService._class_yaml_cache


def test_translation_service_requires_generated_json_outside_development(tmp_path, monkeypatch):
    locales_dir = tmp_path / "locales"
    sources_dir = tmp_path / "sources"
    locales_dir.mkdir()
    sources_dir.mkdir()

    (sources_dir / "app_skills.yml").write_text(
        "web.search:\n  en: Should not load from YAML in production\n",
        encoding="utf-8",
    )

    monkeypatch.setenv("TRANSLATIONS_DIR", str(locales_dir))
    monkeypatch.setenv("TRANSLATIONS_SOURCES_DIR", str(sources_dir))
    monkeypatch.setenv("SERVER_ENVIRONMENT", "production")
    _clear_translation_caches()

    service = TranslationService()

    try:
        service.get_translations("en")
    except RuntimeError as exc:
        assert "Generated locale JSON is required" in str(exc)
    else:
        raise AssertionError("Production runtime must fail when generated locale JSON is missing")

    assert TranslationService._class_yaml_cache == {}
