"""Pure maintained Python facade checks; no native/product runtime proof."""

# contract-test-file: tooling
import asyncio
import pytest
from openmates import SessionClient


def client(native):
    value = SessionClient.__new__(SessionClient)
    value._essential_epoch = 0
    value._native = native
    return value


# contract-test: supporting surface=sdks.pip assertions=sdk.surface.semantic-parity,auth.session.isolation
def test_apps_list_uses_fixed_native_output_and_synchronous_final_release():
    async def scenario():
        calls = []

        class Output:
            def release_json(self):
                calls.append("release")
                return '[{"id":"fixture-app"}]'

            def discard(self):
                calls.append("discard")

        class Operation:
            async def run(self):
                return Output()

            def cancel(self):
                calls.append("cancel")

        class Native:
            def apps_inventory_open(self):
                return Operation()

            def list(self, _):
                pytest.fail("legacy Apps list must not run")

        assert await client(Native()).list("apps") == [{"id": "fixture-app"}]
        assert calls == ["release", "discard"]

    asyncio.run(scenario())


# contract-test: supporting surface=sdks.pip assertions=sdk.surface.semantic-parity,auth.session.isolation
def test_cancel_apps_list_retires_only_original_operation_and_drains_native_result():
    async def scenario():
        entered = asyncio.Event()
        release = asyncio.Event()
        discarded = asyncio.Event()
        calls = []

        class Output:
            def release_json(self):
                pytest.fail("cancelled output allocated")

            def discard(self):
                discarded.set()

        class Operation:
            async def run(self):
                entered.set()
                await release.wait()
                return Output()

            def cancel(self):
                calls.append("only-B")
                release.set()

        class Native:
            def apps_inventory_open(self):
                return Operation()

        pending = asyncio.create_task(client(Native()).list("apps"))
        await entered.wait()
        pending.cancel()
        with pytest.raises(asyncio.CancelledError):
            await pending
        await asyncio.wait_for(discarded.wait(), 1)
        assert calls == ["only-B"]

    asyncio.run(scenario())
