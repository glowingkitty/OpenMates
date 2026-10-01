# backend/tests/test_hosting_embed_graph.py
#
# Focused encrypted-embed contract for Hosting domain checks.
# The model receives selected domains; the graph retains every bounded checked
# domain so local availability views and diagnostics remain truthful.
# Parent previews use only comparable one-year selected registration quotes.

from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace

import pytest

try:
    from toon_format import decode
    from backend.core.api.app.services.embed_service import EmbedService
    from backend.core.api.app.services.workflow_result_selection import (
        prepare_ask_preview, persistable_result_embed_type,
    )
except ImportError as _exc:
    pytestmark = pytest.mark.skip(reason=f"Backend dependencies not installed: {_exc}")


def _domain(name: str, availability: str, *, price: float | None = 12, years: int = 1) -> dict:
    return {
        "domain_ascii": name,
        "availability": availability,
        "currency": "EUR",
        "registration_tiers": [] if price is None else [{
            "unit": "year", "duration_range": {"minimum": years, "maximum": years},
            "price_including_tax": price,
        }],
        "type": "domain_result",
    }


# contract-test: supporting surface=rest_api assertions=hosting-domains.embeds.parent-child,hosting-domains.results.partial-and-safe
def test_hosting_parent_preserves_checked_pool_and_selected_order() -> None:
    checked = [_domain(f"name-{i}.example", "available") for i in range(38)]
    checked += [_domain("taken.example", "unavailable"), _domain("unclear.example", "unknown")]
    selected = [{**checked[3], "embed_ref": "chosen-3"}, {**checked[0], "embed_ref": "chosen-0"}]
    group = {"id": 7, "query": "name", "results": selected, "checked_results": checked,
             "partial": True, "warnings": ["One check was inconclusive"], "error": "Some checks failed"}
    children = EmbedService._hosting_checked_children(group, selected)
    ids = [f"child-{i}" for i in range(len(children))]
    parent = EmbedService._hosting_parent_metadata(group, children, ids,
                                                    {"availability": "all", "max_results": 2})

    assert len(children) == parent["checked_count"] == 40
    assert children[3]["embed_ref"] == "chosen-3"
    assert all(child["type"] == "hosting_domain" for child in children)
    assert parent["embed_ids"] == ids
    assert parent["selected_embed_ids"] == ["child-3", "child-0"]
    assert (parent["result_count"], parent["unavailable_count"], parent["unknown_count"]) == (2, 1, 1)
    assert parent["partial"] is True and parent["error"] == "Some checks failed"
    assert parent["preview_starting_registration"] == {
        "amount": 12, "currency": "EUR", "tax_basis": "including", "unit": "year", "duration": 1,
    }


# contract-test: supporting surface=rest_api assertions=hosting-domains.embeds.parent-child,hosting-domains.quotes.truthful
def test_hosting_parent_omits_incomparable_starting_quote() -> None:
    selected = [_domain("one.example", "available", price=9),
                _domain("two.example", "available", price=5, years=2)]
    group = {"results": selected, "checked_results": selected}
    children = EmbedService._hosting_checked_children(group, selected)
    parent = EmbedService._hosting_parent_metadata(group, children, ["a", "b"], {})
    assert parent["preview_starting_registration"] is None
    assert parent["available_count"] == 2


# contract-test: supporting surface=rest_api assertions=hosting-domains.surface-parity,hosting-domains.embeds.parent-child
def test_hosting_workflow_selection_uses_registered_child_type() -> None:
    item = _domain("available.example", "available")
    context = {"workflow": {"run_id": "run", "node_id": "ask"},
               "nodes": {"domains": {"app_id": "hosting", "skill_id": "search_domains",
                                     "output": {"results": [item]}}}}
    projected, embeds = prepare_ask_preview(
        "{{steps.domains.results}}", context, lambda app, skill: "hosting-domain"
        if (app, skill) == ("hosting", "search_domains") else None,
    )
    assert persistable_result_embed_type("hosting") == "hosting_domain"
    assert len(embeds) == 1
    assert embeds[0]["content_type"] == "hosting-domain"
    assert embeds[0]["content"]["domain_ascii"] == "available.example"
    assert projected["nodes"]["domains"]["output"]["results"][0]["embed_ref"] == embeds[0]["embed_id"]


# contract-test: supporting surface=rest_api assertions=hosting-domains.results.partial-and-safe
def test_hosting_grouped_request_logs_redact_caller_ids() -> None:
    source = (Path(__file__).resolve().parents[1] / "apps" / "ai" / "processing" / "main_processor.py").read_text()
    grouped = source.split("if is_multiple_requests:", 1)[1].split(
        "# Single request: Update the existing placeholder embed", 1,
    )[0]
    assert 'redact_group_ids = app_id == "hosting"' in grouped
    assert 'request_id_log = "<redacted>" if redact_group_ids else request_id' in grouped
    assert "log_prefix=request_log_prefix" in grouped
    for unsafe in (
        "f\"request_id={request_id}\"", "f\"{log_prefix}[request_id={request_id}]\"",
        "f\"Request IDs: {list(placeholder_embeds_map.keys())}\"",
        "f\"request_id={embed_data.get('request_id')}\"",
        "f\"for request {request_id}\"",
    ):
        assert unsafe not in grouped


# contract-test: supporting surface=rest_api assertions=hosting-domains.embeds.parent-child,hosting-domains.results.partial-and-safe
def test_hosting_empty_error_parent_has_encrypted_diagnostics() -> None:
    async def run() -> None:
        sent: list[dict] = []
        cached: list[dict] = []

        async def encrypt(value: str, _key: str):
            return "encrypted:" + value, None

        async def send(**kwargs):
            sent.append(kwargs)
            return True

        async def cache(_embed_id, data, *_args):
            cached.append(data)

        async def existing(*_args):
            return {}

        service = EmbedService.__new__(EmbedService)
        service.encryption_service = SimpleNamespace(encrypt_with_user_key=encrypt)
        service.send_embed_data_to_client = send
        service._cache_embed = cache
        service._get_cached_embed = existing
        service._schedule_embed_persistence_fallback = lambda _embed_id: None
        result = await service.update_embed_with_results(
            embed_id="parent", app_id="hosting", skill_id="search_domains", results=[],
            chat_id="chat", message_id="message", user_id="user", user_id_hash="hashed-user",
            user_vault_key_id="vault", request_metadata={"availability": "available_only"},
            hosting_group={"id": 1, "query": "secret.example", "checked_results": [], "results": [],
                           "partial": True, "error": "Domain provider unavailable"},
        )
        assert result["status"] == cached[0]["status"] == sent[0]["status"] == "error"
        content = decode(sent[0]["content_toon"])
        assert content["checked_count"] == 0
        assert content["selected_embed_ids"] == []
        assert content["error"] == "Domain provider unavailable"
        assert cached[0]["encrypted_content"].startswith("encrypted:")

    asyncio.run(run())


# contract-test: supporting surface=rest_api assertions=hosting-domains.embeds.parent-child
def test_hosting_create_graph_encrypts_checked_children_and_selected_refs() -> None:
    async def run() -> None:
        sent: list[dict] = []
        cached: list[dict] = []

        async def encrypt(value: str, _key: str):
            return "encrypted:" + value, None

        async def send(**kwargs):
            sent.append(kwargs)
            return True

        async def cache(_embed_id, data, *_args):
            cached.append(data)

        class EmptyMetadataCache:
            async def get_discovered_apps_metadata(self):
                return None

        service = EmbedService.__new__(EmbedService)
        service.cache_service = EmptyMetadataCache()
        service.encryption_service = SimpleNamespace(encrypt_with_user_key=encrypt)
        service.send_embed_data_to_client = send
        service._cache_embed = cache
        service._schedule_embed_persistence_fallback = lambda _embed_id: None
        checked = [_domain("available.example", "available"),
                   _domain("taken.example", "unavailable"),
                   _domain("unclear.example", "unknown")]
        selected = [{**checked[0], "embed_ref": "available-ref"}]
        group = {"id": 1, "query": "example", "checked_results": checked, "results": selected,
                 "partial": True, "warnings": ["One check inconclusive"], "error": None}
        result = await service.create_embeds_from_skill_results(
            app_id="hosting", skill_id="search_domains", results=selected,
            chat_id="chat", message_id="message", user_id="user", user_id_hash="hashed-user",
            user_vault_key_id="vault", request_metadata={"availability": "available_only", "max_results": 1},
            hosting_group=group,
        )
        assert result is not None
        child_ids = result["child_embed_ids"]
        assert len(child_ids) == 3
        assert [item["type"] for item in cached] == ["hosting_domain"] * 3 + ["app_skill_use"]
        assert all(item["encrypted_content"].startswith("encrypted:") for item in cached)
        child_contents = [decode(item["content_toon"]) for item in sent[:3]]
        assert [item["availability"] for item in child_contents] == ["available", "unavailable", "unknown"]
        assert child_contents[0]["embed_ref"] == "available-ref"
        assert all(item["type"] == "hosting_domain" for item in child_contents)
        parent = decode(sent[3]["content_toon"])
        assert parent["embed_ids"] == child_ids
        assert parent["selected_embed_ids"] == [child_ids[0]]
        assert (parent["result_count"], parent["checked_count"], parent["unknown_count"]) == (1, 3, 1)
        assert parent["partial"] is True

    asyncio.run(run())
