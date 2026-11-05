# contract-test-file: tooling
# contract-test: supporting surface=sdks.pip assertions=sdk.library.explicit-headless,cli.surface.semantic-parity
import asyncio
import json
from types import SimpleNamespace
import pytest
from openmates import SessionClient, SessionClientError


def client(native):
    value = SessionClient.__new__(SessionClient)
    value._native, value._essential_epoch = native, 0
    return value


@pytest.mark.asyncio
async def test_direct_input_result_forwarding_and_sync_one_shot_release():
    calls = []
    expected = {
        "success": True,
        "data": {
            "files": [{"url": "https://files.example.invalid/private"}],
            "ordered": [3, 1, 2],
        },
    }

    async def prepare(*args):
        calls.append(args)

        def release():
            calls.append("release")
            return json.dumps(expected)

        return SimpleNamespace(
            release_json=release, discard=lambda: calls.append("discard")
        )

    c = client(SimpleNamespace(run_skill_prepare=prepare))
    assert await c.run_skill("web", "search", {"query": "synthetic"}) == expected
    assert calls == [("web", "search", '{"query": "synthetic"}'), "release", "discard"]


@pytest.mark.asyncio
async def test_direct_epoch_refusal_before_private_allocation():
    ticket, calls = asyncio.get_running_loop().create_future(), []
    entered = asyncio.Event()

    def prepare(*_):
        entered.set()
        return ticket

    c = client(SimpleNamespace(run_skill_prepare=prepare))
    work = asyncio.create_task(c.run_skill("web", "search", {}))
    await entered.wait()
    c._essential_epoch += 1
    ticket.set_result(
        SimpleNamespace(
            release_json=lambda: calls.append("private release"),
            discard=lambda: calls.append("discard"),
        )
    )
    with pytest.raises(SessionClientError) as error:
        await work
    assert error.value.code == "cancelled"
    assert calls == ["discard"]


@pytest.mark.asyncio
async def test_abandoned_host_ticket_discards_eventual_output_without_allocation():
    ticket, entered, discarded = (
        asyncio.get_running_loop().create_future(),
        asyncio.Event(),
        asyncio.Event(),
    )

    def prepare(*_):
        entered.set()
        return ticket

    c = client(SimpleNamespace(run_skill_prepare=prepare))
    work = asyncio.create_task(c.run_skill("web", "search", {}))
    await entered.wait()
    work.cancel()
    with pytest.raises(asyncio.CancelledError):
        await work

    def forbidden():
        raise AssertionError("abandoned private allocation")

    ticket.set_result(SimpleNamespace(release_json=forbidden, discard=discarded.set))
    await asyncio.wait_for(discarded.wait(), 1)


@pytest.mark.asyncio
async def test_native_finish_denial_is_normalized_and_discarded():
    calls = []

    def release():
        raise RuntimeError(
            '{"code":"cancelled","message":"The operation was cancelled."}'
        )

    async def prepare(*_):
        return SimpleNamespace(
            release_json=release, discard=lambda: calls.append("discard")
        )

    c = client(SimpleNamespace(run_skill_prepare=prepare))
    with pytest.raises(SessionClientError) as error:
        await c.run_skill("web", "search", {})
    assert error.value.code == "cancelled"
    assert calls == ["discard"]


@pytest.mark.asyncio
async def test_input_and_startup_private_failures_are_fixed_errors():
    calls = []

    def prepare(*_):
        calls.append("start")
        raise RuntimeError("synthetic-private-server-diagnostic")

    c = client(SimpleNamespace(run_skill_prepare=prepare))
    with pytest.raises(SessionClientError) as error:
        await c.run_skill("web", "search", {"bad": object()})
    assert error.value.code == "invalid_argument" and not calls
    with pytest.raises(SessionClientError) as error:
        await c.run_skill("web", "search", {})
    assert error.value.code == "native_failure" and "synthetic-private" not in str(
        error.value
    )


# contract-test: supporting surface=sdks.pip assertions=auth.session.isolation,sdk.encryption.local-only
@pytest.mark.asyncio
async def test_actual_stdlib_dict_items_hook_cancels_before_native_prepare():
    calls = []

    def forbidden(*_):
        calls.append("start")
        raise AssertionError("retired original call reached native prepare")

    c = client(SimpleNamespace(cancel=lambda: calls.append("cancel"), run_skill_prepare=forbidden))

    class Input(dict):
        def items(self):
            calls.append("stdlib-items")
            c.cancel()
            return super().items()

    with pytest.raises(SessionClientError) as error:
        await c.run_skill("web", "search", Input(query="synthetic"))
    assert error.value.code == "cancelled"
    assert calls == ["stdlib-items", "cancel"]
    assert c._essential_epoch == 1


# contract-test: supporting surface=sdks.pip assertions=auth.session.isolation,sdk.encryption.local-only
@pytest.mark.asyncio
async def test_scheduled_encoder_hook_cancel_is_checked_inside_actual_native_callable():
    calls = []

    def forbidden(*_):
        calls.append("start")
        raise AssertionError("scheduled original call reached native prepare")

    c = client(SimpleNamespace(cancel=lambda: calls.append("cancel"), run_skill_prepare=forbidden))

    class Input(dict):
        def items(self):
            calls.append("stdlib-items")
            asyncio.get_running_loop().call_soon(c.cancel)
            return super().items()

    with pytest.raises(SessionClientError) as error:
        await c.run_skill("web", "search", Input(query="synthetic"))
    assert error.value.code == "cancelled"
    assert calls == ["stdlib-items", "cancel"]
    assert c._essential_epoch == 1
