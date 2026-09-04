# backend/tests/test_ai_finalization_embed_graph.py
"""Contract tests for request-scoped AI finalization embed reuse.

The graph may coalesce cache reads only inside one finalization request. These
tests prove unchanged versions load once, mutation invalidates cached data, and
separate requests never share decrypted embed content.
"""

import asyncio
import json

from backend.shared.python_utils.finalization_embed_graph import FinalizationEmbedGraph


class _CountingEmbedService:
    def __init__(self):
        self.loads = 0
        self.values = {"embed-1": {"embed_ref": "example-ref", "version": 1}}

    async def _get_cached_embed_toon(self, embed_id, user_vault_key_id, log_prefix=""):
        self.loads += 1
        await asyncio.sleep(0)
        return json.dumps(self.values[embed_id])


# contract-test: supporting surface=rest_api assertions=ai-request-observability.no-behavior-change
def test_concurrent_reads_load_and_decode_unchanged_embed_once():
    async def exercise():
        service = _CountingEmbedService()
        graph = FinalizationEmbedGraph(service, "vault-key", "[test]", decoder=json.loads)

        first, second = await asyncio.gather(graph.get("embed-1"), graph.get("embed-1"))
        return service, first, second

    service, first, second = asyncio.run(exercise())
    assert first is second
    assert first.decoded["version"] == 1
    assert service.loads == 1


# contract-test: supporting surface=rest_api assertions=ai-request-observability.no-behavior-change
def test_mutation_invalidation_reloads_new_version():
    async def exercise():
        service = _CountingEmbedService()
        graph = FinalizationEmbedGraph(service, "vault-key", decoder=json.loads)
        assert (await graph.get("embed-1")).decoded["version"] == 1

        service.values["embed-1"]["version"] = 2
        graph.invalidate("embed-1")

        assert (await graph.get("embed-1")).decoded["version"] == 2
        return service

    service = asyncio.run(exercise())
    assert service.loads == 2


# contract-test: supporting surface=rest_api assertions=ai-request-observability.no-behavior-change
def test_separate_requests_never_share_decrypted_nodes():
    async def exercise():
        service = _CountingEmbedService()

        first = await FinalizationEmbedGraph(service, "vault-key", decoder=json.loads).get("embed-1")
        second = await FinalizationEmbedGraph(service, "vault-key", decoder=json.loads).get("embed-1")
        return service, first, second

    service, first, second = asyncio.run(exercise())
    assert first is not second
    assert service.loads == 2


# contract-test: supporting surface=rest_api assertions=ai-request-observability.no-behavior-change
def test_invalidation_does_not_cancel_existing_readers() -> None:
    class _VersionedEmbedService(_CountingEmbedService):
        def __init__(self):
            super().__init__()
            self.first_load_started = asyncio.Event()
            self.release_first_load = asyncio.Event()

        async def _get_cached_embed_toon(self, embed_id, user_vault_key_id, log_prefix=""):
            self.loads += 1
            snapshot = json.dumps(self.values[embed_id])
            if self.loads == 1:
                self.first_load_started.set()
                await self.release_first_load.wait()
            return snapshot

    async def exercise():
        service = _VersionedEmbedService()
        graph = FinalizationEmbedGraph(service, "vault-key", decoder=json.loads)
        existing_reader = asyncio.create_task(graph.get("embed-1"))
        await service.first_load_started.wait()

        service.values["embed-1"]["version"] = 2
        graph.invalidate("embed-1")
        new_reader = asyncio.create_task(graph.get("embed-1"))
        service.release_first_load.set()
        return service, await existing_reader, await new_reader

    service, old_node, new_node = asyncio.run(exercise())

    assert old_node.decoded["version"] == 1
    assert new_node.decoded["version"] == 2
    assert service.loads == 2
