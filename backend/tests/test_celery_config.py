# backend/tests/test_celery_config.py
#
# Tests Celery worker boot helpers that are too small for integration tests.
# Worker process startup preloads process-local caches before any queued task can
# run, which prevents first-request latency spikes after worker restarts. These
# tests keep that boot-time contract explicit without starting a real worker.


def test_warm_translation_cache_preloads_english(monkeypatch):
    from backend.core.api.app.tasks import celery_config

    calls: list[str] = []

    class FakeTranslationService:
        def warm_cache(self, *languages: str) -> None:
            calls.extend(languages)

    monkeypatch.setattr(celery_config, "TranslationService", FakeTranslationService)

    celery_config.warm_translation_cache()

    assert calls == ["en"]


def test_custom_workflow_task_names_route_to_persistence_queue():
    from backend.core.api.app.tasks import celery_config

    assert celery_config.get_expected_queue_for_task("workflows.cleanup_expired_temporary") == "persistence"
    assert celery_config.get_expected_queue_for_task("workflows.run") == "persistence"
    assert celery_config.get_expected_queue_for_task("workflows.run_scheduled_trigger") == "persistence"
    assert celery_config.get_expected_queue_for_task("workflows.dispatch_event") == "persistence"
    assert celery_config.get_expected_queue_for_task("workflows.expire_assistant_proposals") == "persistence"
    assert celery_config.get_expected_queue_for_task("workflows.execute_assistant_countdown") == "persistence"
