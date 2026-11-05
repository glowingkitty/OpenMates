"""Browse accepts assistant dispatch context without weakening its public contract."""

import pytest
from pydantic import ValidationError

from backend.apps.ai.processing.skill_executor import get_skill_timeout


# contract-test: supporting surface=rest_api assertions=web-browse.cost-accounting
def test_compute_display_rate_preserves_fractional_credits_without_dispatch_double_charge():
    from pathlib import Path
    import yaml
    from backend.shared.python_schemas.app_metadata_schemas import AppPricing
    from backend.shared.python_utils.billing_utils import calculate_total_credits

    config = yaml.safe_load(
        (Path(__file__).parents[1] / "apps/web/app.yml").read_text()
    )
    skill = next(item for item in config["skills"] if item["id"] == "browse")
    pricing = AppPricing.model_validate(skill["pricing"]).model_dump(exclude_none=True)
    assert pricing == {"per_minute": 5.52}
    # Dispatch has no measured duration. Browse alone settles resource seconds
    # and internal model usage, so metadata must not add a second flat charge.
    assert calculate_total_credits(pricing_config=pricing, units_processed=1) == 0


# contract-test: supporting surface=cli assertions=web-browse.dispatch-and-routing
@pytest.mark.parametrize("timeout_seconds", [10, 180, 600])
# contract-test: supporting surface=cli assertions=web-browse.dispatch-and-routing
def test_browse_timeout_accepts_real_assistant_dispatch_context(timeout_seconds):
    arguments = {
        "task": "Read the public example page",
        "start_url": "https://example.com/",
        "timeout_seconds": timeout_seconds,
        "_same_turn_batch_id": "batch",
        "_placeholder_embed_ids": ["embed"],
        "_user_vault_key_id": "private-vault-reference",
        "_file_path_index": {},
    }
    assert get_skill_timeout("web", "browse", arguments) == timeout_seconds + 120


# contract-test: supporting surface=cli assertions=web-browse.dispatch-and-routing
def test_browse_timeout_keeps_public_validation():
    for invalid in ({"timeout_seconds": 601}, {"arbitrary_browser_code": "forbidden"}):
        with pytest.raises(ValidationError):
            get_skill_timeout("web", "browse", {"task": "Read example", **invalid})


# contract-test: supporting surface=gui.web assertions=web-browse.embed-and-observation,web-browse.dispatch-and-routing
@pytest.mark.asyncio
async def test_processing_embed_can_watch_admitted_session_before_browser_dispatch(
    monkeypatch,
):
    from types import SimpleNamespace
    from backend.apps.web.skills.browse_skill import BrowseSkill
    from backend.shared.python_schemas.web_browse import BrowseJob
    from backend.core.api.app.services import (
        directus,
        embed_service,
        web_browse_service,
    )
    from backend.shared.python_utils import web_browse_dispatch

    events = []
    job = BrowseJob(session_id="session", run_id="run", task_id="job")

    class Service:
        def __init__(self, **kwargs):
            self.store = SimpleNamespace(db=object())

        async def run(self, request, **kwargs):
            assert kwargs["prepare_only"] is True
            events.append("admitted")
            return job

    class Embeds:
        def __init__(self, **kwargs):
            pass

        async def create_processing_embed_placeholder(self, **kwargs):
            assert kwargs["metadata"]["session_id"] == "session"
            assert kwargs["metadata"]["run_id"] == "run"
            assert kwargs["embed_id"] == "placeholder"
            assert kwargs["user_vault_key_id"] == "owner-vault"
            assert kwargs["skill_task_id"] == "original-skill-task"
            events.append("encrypted-viewer-placeholder")

    async def dispatch(value, **kwargs):
        assert value == job
        assert kwargs["embed_id"] == "placeholder"
        events.append("dispatch")
        return value

    monkeypatch.setattr(directus, "DirectusService", lambda **kwargs: object())
    monkeypatch.setattr(web_browse_service, "BrowseService", Service)
    monkeypatch.setattr(embed_service, "EmbedService", Embeds)
    monkeypatch.setattr(web_browse_dispatch, "dispatch_browser_job", dispatch)
    await BrowseSkill.execute(
        SimpleNamespace(app=object(), celery_producer=object()),
        task="Read the public page",
        start_url="https://example.com/",
        secrets_manager=object(),
        cache_service=object(),
        encryption_service=object(),
        user_id="owner",
        chat_id="chat",
        message_id="message",
        user_vault_key_id="owner-vault",
        placeholder_embed_ids=["placeholder"],
        skill_task_id="original-skill-task",
    )
    assert events == ["admitted", "encrypted-viewer-placeholder", "dispatch"]
