"""A same-turn resume publishes the app card of its own batch.

Run 26 of the recipe-app proof (22 Nov): the resume attached the build's app
folder while restoring the batch results, after the stream had already passed
the publication point, so the last step's cards never appeared.
"""

from __future__ import annotations

import inspect
from types import SimpleNamespace

import pytest

from backend.apps.ai.processing import main_processor
from backend.apps.ai.tasks.same_turn_skill_barrier import _attach_project_command_outcomes


def _request() -> SimpleNamespace:
    return SimpleNamespace(
        active_project_focus={"project_id": "p-1"},
        project_focus_candidates=[{"project_id": "p-1", "name": "Recipe Manager"}],
        team_id=None, project_app_folders=None,
    )


def _build_row() -> dict:
    return {"status": "finished", "exit_code": 0, "command": "$ cd web-app && npm run build", "cwd": "web-app",
            "changed_files": [], "write_back": {"committed": ["web-app/dist/index.html"], "merged": []}}


# contract-test: supporting surface=rest_api assertions=code-run.cloud.project-preview
@pytest.mark.asyncio
async def test_resume_publishes_its_own_build_card_once(monkeypatch) -> None:
    request = _request()
    _attach_project_command_outcomes(request, [_build_row()])
    assert request.project_app_folders == ["web-app"]

    published: list[str] = []

    async def apps(**kwargs):
        published.append(f"app:{kwargs['folders']}")
        return ['{"type": "application", "embed_id": "a"}']

    from backend.apps.ai.processing import project_app_preview_card
    monkeypatch.setattr(project_app_preview_card, "publish_project_app_cards", apps)
    kwargs = dict(cache_service=None, directus_service=None, encryption_service=None,
                  user_vault_key_id="v", task_id="t", log_prefix="")
    references = await main_processor._command_outcome_references(request, **kwargs)
    # Only the app card: the files themselves are the reply's code embeds, never a change event.
    assert published == ["app:['web-app']"]
    assert len(references) == 1
    # Consumed: a later stream of the same reply does not publish them again.
    assert await main_processor._command_outcome_references(request, **kwargs) == []


# contract-test: supporting surface=rest_api assertions=code-run.cloud.project-preview
def test_same_turn_restore_is_followed_by_outcome_publication() -> None:
    source = inspect.getsource(main_processor.handle_main_processing)
    restore = source.index("await restore_ordered_tool_results(")
    assert source.index("_command_outcome_references(", restore) - restore < 600


# contract-test: supporting surface=rest_api assertions=code-run.cloud.commands
def test_test_run_card_shows_its_command_and_closes() -> None:
    # Run 26: a test run's "Run" card stayed "Processing…" with no command after the turn.
    from backend.apps.code.tasks.command_parent_embed import build_command_parent_content, test_run_parent_payload

    payload = {"parent_embed_id": "card-1", "target_embed_id": "code-embed",
               "test_run": {"test_command": {"argv": ["npx", "playwright", "test"], "cwd": "web-app"}}}
    parent = test_run_parent_payload(payload)
    assert parent is not None
    status, content = build_command_parent_content(
        parent, {"status": "finished", "exit_code": 0, "duration_seconds": 4.52}, guarded_output="1 passed (4.5s)\n")
    assert status == "finished"
    assert content["command"] == "$ cd web-app && npx playwright test"
    assert content["exit_code"] == 0 and content["duration_seconds"] == 4.5
    assert content["output_tail"] == "1 passed (4.5s)"
    assert content["embed_ids"] == []  # the result is the test result card, not a child of this card
    failed, failed_content = build_command_parent_content(parent, {"status": "failed", "exit_code": 1})
    assert failed == "error" and failed_content["exit_code"] == 1
    assert test_run_parent_payload({**payload, "parent_embed_id": None}) is None
