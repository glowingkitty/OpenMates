"""Actual facade/shared vectors; native doubles are not crypto or runtime proof."""
# contract-test-file: tooling
import asyncio
import json
from pathlib import Path
import pytest
from openmates import SessionClient, SessionClientError, SessionFullChatRead
FIXTURE=json.loads((Path(__file__).resolve().parents[3]/"packages/openmates-rust/tests/fixtures/full-chat-read-metadata.json").read_text())
# contract-test: supporting surface=sdks.pip assertions=sdk.library.explicit-headless,cli.surface.semantic-parity
def test_full_chat_vectors_preserve_optional_authentic_metadata_shape():
    async def scenario():
        client=SessionClient.__new__(SessionClient)
        client._essential_epoch=0
        for vector in FIXTURE["vectors"]:
            calls=[]
            class Output:
                def release_json(self):
                    calls.append("release")
                    return json.dumps(vector["expected"])
                def discard(self):
                    calls.append("discard")
            class Native:
                async def open_chat_prepare(self,chat_id):
                    calls.append(chat_id)
                    return Output()
            client._native=Native()
            assert await client.open_chat(FIXTURE["chat"]["id"])==vector["expected"]
            assert calls==[FIXTURE["chat"]["id"],"release","discard"]
        assert "slug" in SessionFullChatRead.__optional_keys__
    asyncio.run(scenario())
def test_changed_authority_epoch_refuses_queued_read():
    async def scenario():
        client=SessionClient.__new__(SessionClient)
        client._essential_epoch=0
        calls=[]
        class Output:
            def release_json(self):
                pytest.fail("stale output released")
            def discard(self):
                calls.append("discard")
        class Native:
            async def open_chat_prepare(self,chat_id):
                client._essential_epoch+=1
                return Output()
        client._native=Native()
        with pytest.raises(SessionClientError) as failure:
            await client.open_chat(FIXTURE["chat"]["id"])
        assert failure.value.code=="cancelled"
        assert calls==["discard"]
    asyncio.run(scenario())
def test_native_final_denial_is_normalized_and_discarded():
    async def scenario():
        client=SessionClient.__new__(SessionClient)
        client._essential_epoch=0
        calls=[]
        class Output:
            def release_json(self):
                raise RuntimeError(json.dumps({"code":"forbidden","message":"Denied."}))
            def discard(self):
                calls.append("discard")
        class Native:
            async def open_chat_prepare(self,chat_id):
                return Output()
        client._native=Native()
        with pytest.raises(SessionClientError) as failure:
            await client.open_chat(FIXTURE["chat"]["id"])
        assert failure.value.code=="forbidden"
        assert calls==["discard"]
    asyncio.run(scenario())
def test_cancelled_prepare_discards_its_original_result_after_completion():
    async def scenario():
        client=SessionClient.__new__(SessionClient)
        client._essential_epoch=0
        entered=asyncio.Event()
        resume=asyncio.Event()
        discarded=asyncio.Event()
        class Output:
            def release_json(self):
                pytest.fail("abandoned output released")
            def discard(self):
                discarded.set()
        class Native:
            async def open_chat_prepare(self,chat_id):
                entered.set()
                await resume.wait()
                return Output()
        client._native=Native()
        call=asyncio.create_task(client.open_chat(FIXTURE["chat"]["id"]))
        await entered.wait()
        call.cancel()
        with pytest.raises(asyncio.CancelledError):
            await call
        resume.set()
        await asyncio.wait_for(discarded.wait(),1)
    asyncio.run(scenario())
