"""Facade boundary only, not native admission or actual crypto proof."""
# contract-test-file: tooling
import asyncio
import pytest
from openmates import SessionClient, SessionClientError
from openmates.session_client import SessionEmbeds

def client(native):
    c = SessionClient.__new__(SessionClient)
    c._essential_epoch = 0
    c._native = native
    return c, SessionEmbeds(c)

def test_signed_duration_and_arbitrary_password_are_exact_without_key_dto():
    async def scenario():
        calls = []
        class Native:
            async def embeds_share_url(self, *args):
                calls.append(args)
                return "https://app.example.org/#key=synthetic"
        _, embeds = client(Native())
        for duration in [0, -7, (1 << 63) - 1, -(1 << 63)]:
            assert "#key=" in await embeds.share_url("full-id", expires=duration, password="synthetic-long-password")
        assert [a[1] for a in calls] == ["0", "-7", "9223372036854775807", "-9223372036854775808"]
        for invalid in [True, 1.5, float("nan"), 1 << 63, -(1 << 63) - 1]:
            with pytest.raises(SessionClientError) as failure:
                await embeds.share_url("full-id", expires=invalid)
            assert failure.value.code == "invalid_argument"
        assert len(calls) == 4
    asyncio.run(scenario())

def test_original_unpolled_epoch_and_late_result_never_release_secret():
    async def scenario():
        calls = []
        loop = asyncio.get_running_loop()
        result = loop.create_future()
        class Native:
            def embeds_share_url(self, *args):
                calls.append(args)
                return result
            def cancel(self):
                pass
        c, embeds = client(Native())
        original = embeds.share_url("full-id")
        c.cancel()
        with pytest.raises(SessionClientError) as failure:
            await original
        assert failure.value.code == "cancelled" and not calls
        active = asyncio.ensure_future(embeds.share_url("full-id"))
        while not calls:
            await asyncio.sleep(0)
        c.cancel()
        result.set_result("https://app.example.org/#key=synthetic-secret")
        with pytest.raises(SessionClientError) as failure:
            await active
        assert failure.value.code == "cancelled"
        assert "synthetic-secret" not in str(failure.value)
    asyncio.run(scenario())
