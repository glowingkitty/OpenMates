"""Live skill progress: throttling, latest-wins, final frame, no-op, callback order, placeholder content."""
import asyncio
from typing import Any, Dict, List

import pytest
from toon_format import decode as toon_decode

from backend.apps import skill_progress as sp
from backend.apps.base_skill import BaseSkill
from backend.shared.app_packages import provider_dispatch as pd


class FakeEmbedService:
    def __init__(self, fail: bool = False) -> None:
        self.frames: List[Dict[str, Any]] = []
        self.fail = fail

    async def send_embed_data_to_client(self, **kwargs: Any) -> bool:
        if self.fail:
            raise RuntimeError("boom")
        self.frames.append({"embed_id": kwargs["embed_id"], "status": kwargs["status"],
                            "check_cache_status": kwargs["check_cache_status"],
                            "content": toon_decode(kwargs["content_toon"])})
        return True


class Clock:
    def __init__(self) -> None:
        self.now = 100.0

    def __call__(self) -> float:
        return self.now


def make_channel(service: FakeEmbedService, clock: Clock, targets=None) -> sp.SkillProgressChannel:
    targets = targets or [sp.ProgressTarget("e1", {"app_id": "events", "skill_id": "search",
                                                  "task_id": "t", "skill_task_id": "s",
                                                  "embed_ref": "r", "query": "jazz"})]
    return sp.SkillProgressChannel(embed_service=service, chat_id="c", message_id="m", user_id="u",
                                   user_id_hash="h", task_id="t", targets=targets, clock=clock)


def make_skill() -> BaseSkill:
    return BaseSkill.__new__(BaseSkill)


# contract-test: supporting surface=rest_api assertions=app-skills.progress.live-status
@pytest.mark.asyncio
async def test_no_context_is_silent_noop() -> None:
    await make_skill().publish_progress(sources_total=2, sources_done=1, result_count=3)


# contract-test: supporting surface=rest_api assertions=app-skills.progress.live-status
@pytest.mark.asyncio
async def test_open_channel_none_for_external_or_missing_placeholder() -> None:
    kwargs = dict(cache_service=object(), directus_service=None, encryption_service=object(),
                  chat_id="c", message_id="m", user_id="u", user_id_hash="h", task_id="t")
    placeholder = {"embed_id": "e1", "placeholder_content": {"app_id": "a"}}
    assert sp.open_progress_channel(placeholder=placeholder, external_request=True, **kwargs) is None
    assert sp.open_progress_channel(placeholder=None, **kwargs) is None
    assert sp.open_progress_channel(placeholder={"embed_id": "e1"}, **kwargs) is None


# contract-test: supporting surface=rest_api assertions=app-skills.progress.live-status
@pytest.mark.asyncio
async def test_throttle_latest_wins_and_final_frame() -> None:
    service, clock = FakeEmbedService(), Clock()
    channel = make_channel(service, clock)
    async with sp.skill_progress_scope(channel):
        skill = make_skill()
        await skill.publish_progress(sources_total=3, sources_done=0, result_count=0)  # sent
        clock.now += 0.1
        await skill.publish_progress(sources_total=3, sources_done=1, result_count=2)  # held
        await skill.publish_progress(sources_total=3, sources_done=2, result_count=5)  # held, latest wins
        assert len(service.frames) == 1
        await asyncio.sleep(0.5)  # trailing timer sends the latest state
        assert [f["content"]["progress"]["sources_done"] for f in service.frames] == [0, 2]
        clock.now += 1
        await skill.publish_progress(sources_total=3, sources_done=3, result_count=7)  # final, immediate
    progress = [f["content"]["progress"] for f in service.frames]
    assert progress[-1] == {"sources_total": 3, "sources_done": 3, "result_count": 7, "seq": 3}
    assert [p["seq"] for p in progress] == [1, 2, 3]


# contract-test: supporting surface=rest_api assertions=app-skills.progress.live-status
@pytest.mark.asyncio
async def test_identical_states_are_skipped_and_scope_exit_flushes() -> None:
    service, clock = FakeEmbedService(), Clock()
    channel = make_channel(service, clock)
    async with sp.skill_progress_scope(channel):
        await channel.publish(2, 0, 0)
        await channel.publish(2, 0, 0)
        clock.now += 0.1
        await channel.publish(2, 1, 4)  # held; flushed on scope exit
    assert [f["content"]["progress"]["sources_done"] for f in service.frames] == [0, 1]


# contract-test: supporting surface=rest_api assertions=app-skills.progress.live-status
@pytest.mark.asyncio
async def test_frames_keep_placeholder_content_and_reach_every_target() -> None:
    service, clock = FakeEmbedService(), Clock()
    targets = [sp.ProgressTarget("e1", {"app_id": "events", "query": "a", "task_id": "t", "skill_task_id": "s",
                                        "embed_ref": "r1"}),
               sp.ProgressTarget("e2", {"app_id": "events", "query": "b", "task_id": "t", "skill_task_id": "s",
                                        "embed_ref": "r2"})]
    channel = make_channel(service, clock, targets)
    await channel.publish(1, 1, 3)
    assert {f["embed_id"] for f in service.frames} == {"e1", "e2"}
    first = next(f for f in service.frames if f["embed_id"] == "e1")
    assert first["status"] == "processing" and first["check_cache_status"] is False
    assert first["content"]["query"] == "a" and first["content"]["embed_ref"] == "r1"
    assert first["content"]["task_id"] == "t" and first["content"]["skill_task_id"] == "s"
    assert first["content"]["progress"]["result_count"] == 3


# contract-test: supporting surface=rest_api assertions=app-skills.progress.live-status
@pytest.mark.asyncio
async def test_publish_failure_never_reaches_the_skill() -> None:
    channel = make_channel(FakeEmbedService(fail=True), Clock())
    async with sp.skill_progress_scope(channel):
        await make_skill().publish_progress(sources_total=1, sources_done=1, result_count=0)


# contract-test: supporting surface=rest_api assertions=app-skills.progress.live-status
def test_targets_from_multiple_placeholders() -> None:
    placeholder = {"multiple": True, "placeholders": [
        {"embed_id": "a", "placeholder_content": {"x": 1}}, {"embed_id": "b", "placeholder_content": {"x": 2}}]}
    assert [t.embed_id for t in sp.targets_from_placeholder(placeholder)] == ["a", "b"]


# contract-test: supporting surface=rest_api assertions=app-skills.progress.live-status
@pytest.mark.asyncio
async def test_on_provider_done_runs_per_provider_and_failure_is_contained(monkeypatch) -> None:
    async def fake_run_one(app_id, skill_id, provider_id, input_item, secrets_manager):
        await asyncio.sleep({"slow": 0.05, "fast": 0.0}[provider_id])
        return pd.InstalledProviderOutcome(provider_id, results=[{"title": provider_id}])

    monkeypatch.setattr(pd, "_run_one", fake_run_one)
    done: List[str] = []

    async def on_done(outcome: pd.InstalledProviderOutcome) -> None:
        done.append(outcome.provider_id)
        if outcome.provider_id == "fast":
            raise RuntimeError("callback broke")

    outcomes = await pd.run_installed_providers("app", "skill", ["slow", "fast"], {}, None, on_provider_done=on_done)
    assert done == ["fast", "slow"]
    assert [o.provider_id for o in outcomes] == ["slow", "fast"]
    assert all(o.error is None and len(o.results) == 1 for o in outcomes)


# contract-test: supporting surface=rest_api assertions=app-skills.progress.live-status
@pytest.mark.asyncio
async def test_skill_progress_aggregates_sources() -> None:
    calls: List[Dict[str, int]] = []

    class Skill:
        async def publish_progress(self, **kwargs: int) -> None:
            calls.append(kwargs)

    progress = sp.SkillProgress(Skill())
    await progress.add_sources(2)
    await progress.source_done(3)
    await progress.source_done(0)
    assert calls[-1] == {"sources_total": 2, "sources_done": 2, "result_count": 3}
