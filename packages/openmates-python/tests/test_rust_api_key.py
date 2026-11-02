"""Pure facade doubles, not native or peer runtime evidence."""

# contract-test: supporting surface=sdks.pip assertions=sdk.library.explicit-headless,sdk.auth.credential-separation
import asyncio
import pytest
from openmates.rust_api_key import RustApiKeyClient, RustApiKeyClientError


def client(native):
    c = RustApiKeyClient.__new__(RustApiKeyClient)
    c._native = native
    c._inflight = set()
    return c


# contract-test: supporting surface=sdks.pip assertions=sdk.library.explicit-headless,sdk.auth.credential-separation
def test_original_request_before_scheduled_call_and_allocation():
    async def run():
        calls = []

        class Output:
            def release_json(self):
                calls.append("allocate")
                return '{"id":"synthetic"}'

            def discard(self):
                calls.append("discard")

        class Request:
            async def account_info_prepare(self):
                calls.append("prepare")
                return Output()

            def cancel(self):
                calls.append("cancel:A")

        class Native:
            def request(self):
                calls.append("admit:A")
                return Request()

        c = client(Native())
        assert await c.account_info() == {"id": "synthetic"}
        assert calls == ["admit:A", "prepare", "allocate", "discard", "cancel:A"]

    asyncio.run(run())


# contract-test: supporting surface=sdks.pip assertions=sdk.library.explicit-headless,sdk.auth.credential-separation
def test_cancelled_a_drains_and_b_uses_own_request():
    async def run():
        entered = asyncio.Event()
        finish = asyncio.Event()
        requests = []

        class Output:
            def __init__(self, request):
                self.request = request

            def release_json(self):
                if self.request.cancelled:
                    raise RuntimeError(
                        '{"code":"cancelled","message":"The operation was cancelled."}'
                    )
                return '{"b":true}'

            def discard(self):
                pass

        class Request:
            cancelled = False

            def cancel(self):
                self.cancelled = True

            async def run_skill_prepare(self, *_):
                entered.set()
                await finish.wait()
                return Output(self)

            async def account_info_prepare(self):
                return Output(self)

        class Native:
            def request(self):
                r = Request()
                requests.append(r)
                return r

        c = client(Native())
        a = asyncio.create_task(c.run_skill("web", "search", {"query": "synthetic"}))
        await entered.wait()
        a.cancel()
        assert await c.account_info() == {"b": True}
        assert not a.done()
        finish.set()
        with pytest.raises(asyncio.CancelledError):
            await a
        assert requests[0].cancelled and requests[1].cancelled
        await asyncio.sleep(0)
        assert not c._inflight

    asyncio.run(run())


# contract-test: supporting surface=sdks.pip assertions=sdk.library.explicit-headless,sdk.auth.credential-separation
def test_serialization_after_original_admission():
    async def run():
        calls = []

        class Request:
            def cancel(self):
                calls.append("cancel")

            def run_skill_prepare(self, *_):
                raise AssertionError("invalid input starts IO")

        class Native:
            def request(self):
                calls.append("admit")
                return Request()

        c = client(Native())
        with pytest.raises(RustApiKeyClientError) as failure:
            await c.run_skill("web", "search", {"bad": float("nan")})
        assert failure.value.code == "native_failure"
        assert calls == ["admit", "cancel"]

    asyncio.run(run())


# contract-test: supporting surface=sdks.pip assertions=sdk.library.explicit-headless,sdk.auth.credential-separation
def test_raw_native_failure_is_safe():
    async def run():
        class Native:
            def request(self):
                raise RuntimeError("synthetic-private-server-diagnostic")

        with pytest.raises(RustApiKeyClientError) as failure:
            await client(Native()).account_info()
        assert failure.value.code == "native_failure" and "private" not in str(
            failure.value
        )

    asyncio.run(run())
