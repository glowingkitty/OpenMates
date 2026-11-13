"""Unit tests for the chat orchestration skills, gating, status hooks and context transform.

The job layer (``chat_orchestration_jobs``) is replaced by an in-memory fake so
these tests only cover the skill/hook logic; the real stack is covered by E2E.
"""

import importlib
import inspect
import json
import sys
import types
from dataclasses import dataclass
from types import SimpleNamespace
from typing import Dict, List, Optional

import pytest

try:
    importlib.import_module("backend.shared.python_utils.chat_orchestration_jobs")
except ImportError:  # job layer lands in a parallel lane; tests patch every function anyway
    stub = types.ModuleType("backend.shared.python_utils.chat_orchestration_jobs")

    class _StubError(Exception):
        def __init__(self, code: str):
            super().__init__(code)
            self.code = code

    @dataclass
    class _StubOutcome:
        job_id: str
        state: str
        result: Optional[dict] = None
        error_code: Optional[str] = None

    stub.OrchestrationError = _StubError
    stub.JobOutcome = _StubOutcome
    stub.event_message_id = lambda *a: "evt-" + "-".join(a)
    sys.modules["backend.shared.python_utils.chat_orchestration_jobs"] = stub
    import backend.shared.python_utils as _pkg
    _pkg.chat_orchestration_jobs = stub

from backend.apps.ai.processing import chat_orchestration_hooks as hooks  # noqa: E402
from backend.apps.openmates.skills import chat_orchestration_skills as skills  # noqa: E402
from backend.apps.ai.utils.llm_utils import _transform_message_history_for_llm  # noqa: E402
from backend.shared.python_utils import chat_orchestration_safety as safety  # noqa: E402

jobs = skills.jobs
USER, CHAT = "user-1", "creator-chat"


class FakeRedis:
    def __init__(self):
        self.store: Dict[str, str] = {}

    async def set(self, key, value, nx=False, ex=None):
        if nx and key in self.store:
            return None
        self.store[key] = value
        return True


class FakeCache:
    """Active-task marker plus the plain get/set and Redis client the safety layer uses."""

    def __init__(self, active: Optional[str] = None):
        self.active = active
        self.values: Dict[str, object] = {}
        self._redis = FakeRedis()

    async def get_active_ai_task(self, chat_id: str):
        return self.active

    async def get(self, key):
        return self.values.get(key)

    async def set(self, key, value, ttl=None):
        self.values[key] = value
        return True

    @property
    async def client(self):
        return self._redis


class FakeJobs:
    """Records calls and returns configured values."""

    def __init__(self):
        self.creators: Dict[str, Optional[str]] = {}
        self.depth = 0
        self.unfinished = 0
        self.user_active = False
        self.spawned: List[dict] = []
        self.enqueued: List[dict] = []
        self.events: List[dict] = []
        self.states: List[tuple] = []
        self.spawn_error: Optional[str] = None
        self.outcome_state = "done"
        self.outcome_result: Optional[dict] = None

    async def get_creator_chat_id(self, *, cache_service, chat_id):
        return self.creators.get(chat_id)

    async def creator_chain_depth(self, *, cache_service, chat_id):
        return self.depth

    async def count_unfinished_spawned(self, *, cache_service, encryption_service, user_id, creator_chat_id,
                                       directus_service=None):
        return self.unfinished

    async def record_main_chat_spawn(self, *, user_id, creator_chat_id, creator_message_id, spawned_chat_ids):
        if self.spawn_error:
            raise jobs.OrchestrationError(self.spawn_error)

    async def link_spawned_chat(self, **kwargs):
        self.spawned.append(kwargs)

    async def set_spawn_state(self, **kwargs):
        self.states.append((kwargs["spawned_chat_id"], kwargs["state"]))

    async def enqueue_job(self, **kwargs):
        self.enqueued.append(kwargs)
        return jobs.JobOutcome(
            job_id="j1", state=self.outcome_state, result=self.outcome_result,
            error_code="device_offline" if self.outcome_state == "expired" else None,
        )

    async def emit_creator_event(self, **kwargs):
        self.events.append(kwargs)
        return jobs.JobOutcome(job_id="e1", state="done", result=None, error_code=None)

    async def is_user_active(self, *, cache_service, spawned_chat_id):
        return self.user_active

    async def list_spawned(self, **kwargs):
        return self.spawned_list

    spawned_list: List[dict] = []


@pytest.fixture
def fake(monkeypatch):
    f = FakeJobs()
    f.spawned_list = []
    for name in dir(FakeJobs):
        if name.startswith("_") or name in {"spawned_list"}:
            continue
        attr = getattr(f, name)
        if callable(attr):
            monkeypatch.setattr(jobs, name, attr, raising=False)
    monkeypatch.setattr(jobs, "event_message_id", lambda *a: "evt-" + "-".join(a), raising=False)
    return f


# contract-test: supporting surface=rest_api assertions=chat-orchestration.spawn.main-chat-is-normal,chat-orchestration.spawn.eligibility-and-limits
def test_fake_job_layer_matches_real_signatures():
    """Explicitly typed fakes take exactly the real keyword-only parameters, so a missing argument fails here.

    Regression: the start-chat skill called count_unfinished_spawned without encryption_service; the old fake
    did not take that argument, so unit tests passed and the real skill raised a TypeError on dev.
    """
    for name in dir(FakeJobs):
        fake_fn = getattr(FakeJobs, name)
        if name.startswith("_") or not callable(fake_fn):
            continue
        fake_params = list(inspect.signature(fake_fn).parameters.values())[1:]  # drop self
        if any(p.kind is inspect.Parameter.VAR_KEYWORD for p in fake_params):
            continue
        real = inspect.signature(getattr(jobs, name)).parameters.values()
        empty = inspect.Parameter.empty
        assert {p.name for p in fake_params if p.default is empty} == {p.name for p in real if p.default is empty}, name
        assert {p.name for p in fake_params} <= {p.name for p in real}, name


def make(cls):
    return cls(app=None, app_id="openmates", skill_id="x", skill_name="x", skill_description="x")


async def turn(cache, chat_id=CHAT, message_id="m-user", origin="user", hop=0, sender=None):
    """Record why a turn runs, as the message handler or the interpretation dispatcher does."""
    await safety.record_turn_origin(cache_service=cache, user_id=USER, chat_id=chat_id, message_id=message_id,
                                    origin=origin, hop=hop, sender_chat_id=sender)


async def run(cls, cache=None, origin="user", **kw):
    """Run a skill in a turn of the given origin (None: no recorded origin)."""
    cache = cache or FakeCache()
    chat_id = kw.pop("chat_id", CHAT)
    kw.setdefault("message_id", "m-user")
    if origin is not None and chat_id and chat_id != "incognito" and kw["message_id"]:
        await turn(cache, chat_id=chat_id, message_id=kw["message_id"], origin=origin)
    return await make(cls).execute(cache_service=cache, encryption_service=None,
                                   user_id=kw.pop("user_id", USER), chat_id=chat_id, **kw)


# contract-test: supporting surface=rest_api assertions=chat-orchestration.spawn.main-chat-is-normal,chat-orchestration.privacy.device-executed,chat-orchestration.spawn.unified-kind
@pytest.mark.asyncio
async def test_start_chat_happy_path_and_payload(fake):
    r = await run(skills.StartChatSkill, title="Kitchen quotes", brief="Collect quotes", message_id="m1")
    assert r.success and r.status == "started" and r.chat_id
    job = fake.enqueued[0]
    assert job["kind"] == "start_chat"
    assert job["payload"]["creator_chat_id"] == CHAT and job["payload"]["brief"] == "Collect quotes"
    assert job["payload"]["event_message_id"].startswith("evt-")
    assert fake.states == [(r.chat_id, "starting")]


# contract-test: supporting surface=rest_api assertions=chat-orchestration.privacy.device-executed
@pytest.mark.asyncio
async def test_start_chat_queued_when_device_does_not_answer(fake):
    fake.outcome_state = "pending"
    r = await run(skills.StartChatSkill, title="T", brief="B")
    assert r.success and r.status == "queued"


# contract-test: supporting surface=rest_api assertions=chat-orchestration.spawn.eligibility-and-limits
@pytest.mark.asyncio
@pytest.mark.parametrize("kw", [{"user_id": None}, {"chat_id": "incognito"}, {"chat_id": None}])
async def test_start_chat_not_eligible(fake, kw):
    r = await run(skills.StartChatSkill, title="T", brief="B", **kw)
    assert not r.success and r.error_code == "not_eligible" and not fake.enqueued


# contract-test: supporting surface=rest_api assertions=chat-orchestration.spawn.eligibility-and-limits
@pytest.mark.asyncio
async def test_start_chat_limits(fake):
    fake.depth = 3
    assert (await run(skills.StartChatSkill, title="T", brief="B")).error_code == "chain_too_deep"
    fake.depth, fake.unfinished = 0, 20
    assert (await run(skills.StartChatSkill, title="T", brief="B")).error_code == "spawn_limit_reached"
    fake.unfinished, fake.spawn_error = 0, "spawn_limit_reached"
    assert (await run(skills.StartChatSkill, title="T", brief="B")).error_code == "spawn_limit_reached"
    assert not fake.enqueued


# contract-test: supporting surface=rest_api assertions=chat-orchestration.skills.list-read-send
@pytest.mark.asyncio
async def test_read_refuses_foreign_chat(fake):
    fake.creators["other"] = "some-other-chat"
    r = await run(skills.ReadSpawnedChatSkill, spawned_chat_id="other")
    assert r.error_code == "not_spawned_by_this_chat" and not fake.enqueued
    r = await run(skills.ReadSpawnedChatSkill, spawned_chat_id="unlinked")
    assert r.error_code == "not_spawned_by_this_chat"


# contract-test: supporting surface=rest_api assertions=chat-orchestration.skills.list-read-send,chat-orchestration.privacy.device-executed
@pytest.mark.asyncio
async def test_read_returns_messages_clamped_and_labelled_untrusted(fake):
    fake.creators["c1"] = CHAT
    fake.outcome_result = {"messages": [{"role": "assistant", "content": "hi", "created_at": 1}]}
    r = await run(skills.ReadSpawnedChatSkill, spawned_chat_id="c1", limit=500)
    assert r.success and r.messages and "untrusted" in r.note
    assert fake.enqueued[0]["payload"]["limit"] == 20


# contract-test: supporting surface=rest_api assertions=chat-orchestration.privacy.device-executed
@pytest.mark.asyncio
async def test_read_device_offline_is_tool_error(fake):
    fake.creators["c1"] = CHAT
    fake.outcome_state = "expired"
    r = await run(skills.ReadSpawnedChatSkill, spawned_chat_id="c1")
    assert not r.success and r.error_code == "device_offline"


# contract-test: supporting surface=rest_api assertions=chat-orchestration.skills.list-read-send,chat-orchestration.user-awareness.no-talking-over
@pytest.mark.asyncio
async def test_send_ownership_and_user_active(fake):
    assert (await run(skills.SendToSpawnedChatSkill, spawned_chat_id="x", text="hi")).error_code == "not_spawned_by_this_chat"
    fake.creators["c1"] = CHAT
    fake.user_active = True
    assert (await run(skills.SendToSpawnedChatSkill, spawned_chat_id="c1", text="hi")).error_code == "user_active"
    fake.user_active = False
    r = await run(skills.SendToSpawnedChatSkill, cache=FakeCache(active="task-1"), spawned_chat_id="c1", text="hi")
    assert r.error_code == "user_active" and not fake.enqueued
    r = await run(skills.SendToSpawnedChatSkill, spawned_chat_id="c1", text="hi")
    assert r.success and fake.enqueued[0]["kind"] == "send_message"


# contract-test: supporting surface=rest_api assertions=chat-orchestration.report.creator-skill
@pytest.mark.asyncio
async def test_report_requires_creator(fake):
    r = await run(skills.ReportToCreatorSkill, text="done")
    assert r.error_code == "no_creator" and not fake.events
    fake.creators[CHAT] = "parent"
    r = await run(skills.ReportToCreatorSkill, text="x" * 5000, message_id="m9")
    assert r.success
    ev = fake.events[0]
    assert ev["action"] == "report" and ev["creator_chat_id"] == "parent" and len(ev["text"]) == 2000


def _request(creator=None, **kw):
    return SimpleNamespace(creator_chat_id=creator, chat_id=CHAT, user_id=USER,
                           is_incognito=kw.get("incognito", False), is_anonymous=False)


# contract-test: supporting surface=rest_api assertions=chat-orchestration.report.creator-skill
@pytest.mark.asyncio
async def test_gating_report_only_with_creator(fake):
    added, text = await hooks.orchestration_skill_additions(
        cache_service=FakeCache(), encryption_service=None, request_data=_request("parent"))
    assert hooks.REPORT_SKILL in added and "report-to-creator" in text
    added, text = await hooks.orchestration_skill_additions(
        cache_service=FakeCache(), encryption_service=None, request_data=_request(None))
    assert added == set() and text is None


# contract-test: supporting surface=rest_api assertions=chat-orchestration.skills.list-read-send
@pytest.mark.asyncio
async def test_gating_exposes_list_read_send_when_chat_has_spawned(fake):
    fake.spawned_list = [{"chat_id": "c1"}]
    added, _ = await hooks.orchestration_skill_additions(
        cache_service=FakeCache(), encryption_service=None, request_data=_request(None))
    assert set(hooks.SPAWNED_CHAT_SKILLS) <= added and hooks.REPORT_SKILL not in added
    added, _ = await hooks.orchestration_skill_additions(
        cache_service=FakeCache(), encryption_service=None, request_data=_request("p", incognito=True))
    assert added == set()


# contract-test: supporting surface=rest_api assertions=chat-orchestration.skills.answer-own-questions-here
@pytest.mark.asyncio
async def test_creator_instruction_keeps_the_users_own_questions_here(fake):
    fake.spawned_list = [{"chat_id": "c1"}]
    _, text = await hooks.orchestration_skill_additions(
        cache_service=FakeCache(), encryption_service=None, request_data=_request(None))
    assert "Answer the user's own new questions yourself, here in this chat" in text
    assert "only when the user explicitly asks" in text


# contract-test: supporting surface=rest_api assertions=chat-orchestration.status.automatic
@pytest.mark.asyncio
async def test_status_hooks_only_for_linked_chats(fake):
    kw = dict(cache_service=FakeCache(), encryption_service=None)
    await hooks.record_spawned_chat_finished(request_data=_request(None), message_id="a1", **kw)
    await hooks.record_spawned_chat_waiting(request_data=_request(None), message_id="a1", **kw)
    await hooks.record_spawned_chat_failed(request_data=_request(None), **kw)
    assert not fake.events and not fake.states
    await hooks.record_spawned_chat_finished(request_data=_request("parent"), message_id="a1", **kw)
    await hooks.record_spawned_chat_waiting(request_data=_request("parent"), message_id="a2", **kw)
    await hooks.record_spawned_chat_failed(request_data=_request("parent"), **kw)
    assert [(e["action"], e["discriminator"]) for e in fake.events] == [("finished", "a1"), ("waiting_for_user", "a2")]
    assert [s[1] for s in fake.states] == ["finished", "waiting_for_user", "failed"]


# contract-test: supporting surface=rest_api assertions=chat-orchestration.events.context-for-creator
def test_context_transform_turns_events_into_text():
    event = {"type": "chat_orchestration", "action": "report", "chat_id": "c1", "title": "Kitchen quotes", "text": "Found 3"}
    out = _transform_message_history_for_llm([
        {"role": "user", "content": "hello"},
        {"role": "system", "content": json.dumps(event)},
    ])
    assert out[0]["content"] == "hello"
    assert out[1]["role"] == "system"
    assert "[Spawned chat event] Report from chat 'Kitchen quotes' (chat_id c1): Found 3" in out[1]["content"]
    assert "untrusted" in out[1]["content"]


# contract-test: supporting surface=rest_api assertions=chat-orchestration.billing.separate-main-chats
def test_spawned_request_has_no_ancestry_so_billing_uses_own_chat_id():
    """A spawned main chat is a normal chat: its request carries no root/parent ancestry."""
    from backend.apps.ai.skills.ask_skill import AskSkillRequest
    fields = AskSkillRequest.model_fields
    assert fields["root_chat_id"].default is None
    assert "parent_chat_id" not in fields or fields["parent_chat_id"].default is None
    assert hooks.APP_ID == "openmates"


# --- Cross-chat write safety (Marco 2026-11-13: chats never message each other without a good reason) ---

WRITES = [
    (skills.StartChatSkill, {"title": "T", "brief": "B"}),
    (skills.SendToSpawnedChatSkill, {"spawned_chat_id": "c1", "text": "hi"}),
    (skills.ReportToCreatorSkill, {"text": "done"}),
]


# contract-test: supporting surface=rest_api assertions=chat-orchestration.safety.user-requested-writes-only
@pytest.mark.asyncio
@pytest.mark.parametrize("origin", ["automatic", None])
async def test_automatic_or_unknown_turns_never_write_to_another_chat(fake, origin):
    fake.creators.update({"c1": CHAT, CHAT: "parent"})
    for cls, kw in WRITES:
        r = await run(cls, origin=origin, message_id="evt-1", **kw)
        assert not r.success and r.error_code == "not_user_requested", cls
    assert not fake.enqueued and not fake.events


# contract-test: supporting surface=rest_api assertions=chat-orchestration.safety.user-requested-writes-only
@pytest.mark.asyncio
async def test_creator_sent_brief_may_delegate_until_the_relay_limit(fake):
    cache = FakeCache()
    await turn(cache, message_id="brief", origin="creator", hop=1, sender="parent")
    r = await run(skills.StartChatSkill, cache=cache, origin=None, message_id="brief", title="T", brief="B")
    assert r.success and fake.enqueued[0]["payload"]["origin_hop"] == 1
    await turn(cache, message_id="deep", origin="creator", hop=safety.MAX_RELAY_HOPS, sender="parent")
    r = await run(skills.StartChatSkill, cache=cache, origin=None, message_id="deep", title="T", brief="B")
    assert r.error_code == "relay_limit_reached" and len(fake.enqueued) == 1


# contract-test: supporting surface=rest_api assertions=chat-orchestration.safety.loop-limits
@pytest.mark.asyncio
async def test_ping_pong_between_two_chats_is_stopped(fake):
    """A -> B -> A without user input: the bounce back is refused, a new user message allows it again."""
    cache = FakeCache()
    fake.creators.update({"c1": CHAT})
    assert (await run(skills.SendToSpawnedChatSkill, cache=cache, spawned_chat_id="c1", text="go")).success
    # B (c1) works on the creator-sent message and reports back to A.
    await turn(cache, chat_id="c1", message_id="m-b", origin="creator", hop=1, sender=CHAT)
    fake.creators["c1"] = CHAT
    r = await make(skills.ReportToCreatorSkill).execute(
        text="result", cache_service=cache, encryption_service=None, user_id=USER, chat_id="c1", message_id="m-b")
    assert r.success
    # A's automatic interpreting turn tries to write back: refused.
    await turn(cache, message_id="evt-report", origin="automatic")
    r = await run(skills.SendToSpawnedChatSkill, cache=cache, origin=None, message_id="evt-report",
                  spawned_chat_id="c1", text="again")
    assert r.error_code == "not_user_requested"
    # Even a relayed (non-user) turn in A may not bounce straight back to B.
    await turn(cache, message_id="relay", origin="creator", hop=1, sender="grandparent")
    r = await run(skills.SendToSpawnedChatSkill, cache=cache, origin=None, message_id="relay",
                  spawned_chat_id="c1", text="again")
    assert r.error_code == "ping_pong"
    assert [job["kind"] for job in fake.enqueued] == ["send_message"]
    # The user asks in A for a follow-up: allowed.
    r = await run(skills.SendToSpawnedChatSkill, cache=cache, message_id="m-user-2",
                  spawned_chat_id="c1", text="also check Asia")
    assert r.success and [job["kind"] for job in fake.enqueued] == ["send_message", "send_message"]


# contract-test: supporting surface=rest_api assertions=chat-orchestration.safety.loop-limits,chat-orchestration.report.creator-skill
@pytest.mark.asyncio
async def test_several_reports_work_and_an_identical_repeat_is_dropped(fake):
    cache = FakeCache()
    fake.creators.update({"c1": CHAT, "c2": CHAT})
    for chat_id in ("c1", "c2"):
        await turn(cache, chat_id=chat_id, message_id=f"m-{chat_id}", origin="creator", hop=1, sender=CHAT)
    async def report(chat_id, text):
        return await make(skills.ReportToCreatorSkill).execute(
            text=text, cache_service=cache, encryption_service=None, user_id=USER, chat_id=chat_id,
            message_id=f"m-{chat_id}")
    assert (await report("c1", "first half")).success
    assert (await report("c1", "second half")).success
    assert (await report("c2", "other result")).success
    repeated = await report("c1", "first half")
    assert repeated.success and repeated.status == "already_reported"
    reports = [e for e in fake.events if e["action"] == "report"]
    assert [e["text"] for e in reports] == ["first half", "second half", "other result"]
    assert len({e["discriminator"] for e in reports}) == 3  # two reports in one turn stay two events


# contract-test: supporting surface=rest_api assertions=chat-orchestration.safety.visible-both-sides
@pytest.mark.asyncio
async def test_send_and_report_leave_a_visible_event_in_both_chats(fake):
    fake.creators.update({"c1": CHAT})
    assert (await run(skills.SendToSpawnedChatSkill, spawned_chat_id="c1", text="also Asia")).success
    sent = fake.events[-1]
    assert (sent["action"], sent["creator_chat_id"], sent["spawned_chat_id"], sent["text"]) == \
        ("sent", CHAT, "c1", "also Asia")
    fake.creators[CHAT] = "parent"
    assert (await run(skills.ReportToCreatorSkill, text="done")).success
    report, reported = fake.events[-2:]
    assert (report["action"], report["creator_chat_id"], report["spawned_chat_id"]) == ("report", "parent", CHAT)
    # Stored in the reporting chat itself; it links to the creator chat.
    assert (reported["action"], reported["creator_chat_id"], reported["spawned_chat_id"]) == \
        ("reported", CHAT, "parent")


# contract-test: supporting surface=rest_api assertions=chat-orchestration.safety.user-requested-writes-only
@pytest.mark.asyncio
async def test_pipeline_hides_write_skills_from_non_user_turns(fake):
    cache = FakeCache()
    request = SimpleNamespace(chat_id=CHAT, user_id=USER, message_id="evt-9", is_incognito=False)
    await turn(cache, message_id="evt-9", origin="automatic")
    blocked, note = await hooks.orchestration_blocked_skills(cache_service=cache, request_data=request)
    assert blocked == set(hooks.WRITE_SKILLS) and "not started by a message the user sent" in note
    await turn(cache, message_id="evt-9", origin="user")
    assert await hooks.orchestration_blocked_skills(cache_service=cache, request_data=request) == (set(), None)


# contract-test: supporting surface=rest_api assertions=chat-orchestration.safety.user-requested-writes-only
@pytest.mark.asyncio
async def test_message_origin_creator_sent_vs_user_typed(fake, monkeypatch):
    cache = FakeCache()
    async def is_creator_sent(*, cache_service, user_id, spawned_chat_id, job_id):
        return job_id == "job-1"
    async def get_job_record(*, cache_service, user_id, job_id):
        return {"creator_chat_id": "parent", "origin_hop": 1}
    monkeypatch.setattr(jobs, "is_creator_sent", is_creator_sent, raising=False)
    monkeypatch.setattr(jobs, "get_job_record", get_job_record, raising=False)
    sent = await safety.record_message_origin(cache_service=cache, user_id=USER, chat_id="c1",
                                              message_id="m1", job_id="job-1")
    typed = await safety.record_message_origin(cache_service=cache, user_id=USER, chat_id="c1",
                                               message_id="m2", job_id=None)
    assert sent == {"origin": "creator", "hop": 2, "sender_chat_id": "parent"}
    assert typed["origin"] == "user"
