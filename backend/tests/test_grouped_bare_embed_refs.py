# backend/tests/test_grouped_bare_embed_refs.py
#
# Regression tests for grouped bare embed references produced by assistant
# responses, such as `[openai.com-msb, openai.com-Uoj]`.
#
# The backend normalizer should rewrite known grouped refs into canonical
# inline embed links before persisted messages are rendered by clients.

import pytest

try:
    from backend.apps.ai.tasks.stream_consumer import (
        _BARE_EMBED_REF_PATTERN,
        _GROUPED_BARE_EMBED_REFS_PATTERN,
        _fix_bad_embed_display_text,
    )
except ImportError as _exc:
    pytestmark = pytest.mark.skip(reason=f"Backend dependencies not installed: {_exc}")


class TestGroupedBareEmbedRefs:
    # contract-test: supporting surface=gui.web assertions=web-search.surface-parity
    def test_single_bare_ref_pattern_ignores_grouped_refs(self):
        text = "Sources: [openai.com-msb, openai.com-Uoj]"
        match = _BARE_EMBED_REF_PATTERN.search(text)

        assert match is None

    # contract-test: supporting surface=gui.web assertions=web-search.surface-parity
    def test_grouped_pattern_matches_domain_refs(self):
        text = "Sources: [openai.com-msb, openai.com-Uoj]"
        match = _GROUPED_BARE_EMBED_REFS_PATTERN.search(text)

        assert match is not None
        assert match.group(1) == "openai.com-msb, openai.com-Uoj"

    # contract-test: supporting surface=gui.web assertions=web-search.surface-parity
    def test_grouped_pattern_matches_suffix_only_refs(self):
        text = "Sources: [-7fJ, ‑4VF]"
        match = _GROUPED_BARE_EMBED_REFS_PATTERN.search(text)

        assert match is not None
        assert match.group(1) == "-7fJ, ‑4VF"

    # contract-test: supporting surface=gui.web assertions=web-search.surface-parity
    def test_grouped_pattern_ignores_plain_comma_lists(self):
        text = "Sources: [OpenAI, Microsoft]"
        match = _GROUPED_BARE_EMBED_REFS_PATTERN.search(text)

        assert match is None

    # contract-test: supporting surface=gui.web assertions=web-search.surface-parity
    @pytest.mark.asyncio
    async def test_converts_grouped_known_bare_refs_to_inline_links(self, monkeypatch):
        from backend.core.api.app.services import embed_service as embed_service_module
        from toon_format import encode

        parent_id = "parent-embed"
        first_child_id = "first-child"
        second_child_id = "second-child"
        encoded = {
            parent_id: encode({"embed_ids": f"{first_child_id}|{second_child_id}"}),
            first_child_id: encode({
                "type": "website",
                "embed_ref": "openai.com-msb",
                "title": "Product Releases & GPT-5.6 Ecosystem",
            }),
            second_child_id: encode({
                "type": "website",
                "embed_ref": "openai.com-Uoj",
                "title": "OpenAI Product Update",
            }),
        }

        class FakeEmbedService:
            def __init__(self, **_kwargs):
                pass

            async def _get_cached_embed_toon(self, embed_id, *_args):
                return encoded.get(embed_id)

        monkeypatch.setattr(embed_service_module, "EmbedService", FakeEmbedService)

        result = await _fix_bad_embed_display_text(
            aggregated_response="Sources: [openai.com-msb, openai.com-Uoj]",
            tool_calls_info=[{"embed_id": parent_id}],
            cache_service=object(),
            directus_service=None,
            encryption_service=object(),
            user_vault_key_id="vault-key",
        )

        assert result == (
            "Sources: [Product Releases & GPT-5.6 Ecosystem](embed:openai.com-msb), "
            "[OpenAI Product Update](embed:openai.com-Uoj)"
        )

    # contract-test: supporting surface=gui.web assertions=web-search.surface-parity
    @pytest.mark.asyncio
    async def test_converts_single_suffix_only_ref_to_inline_link(self, monkeypatch):
        from backend.core.api.app.services import embed_service as embed_service_module
        from toon_format import encode

        parent_id = "parent-embed"
        child_id = "child-embed"
        encoded = {
            parent_id: encode({"embed_ids": child_id}),
            child_id: encode({
                "type": "website",
                "embed_ref": "9to5mac.com-t3Z",
                "title": "iPhone Ultra Features",
            }),
        }

        class FakeEmbedService:
            def __init__(self, **_kwargs):
                pass

            async def _get_cached_embed_toon(self, embed_id, *_args):
                return encoded.get(embed_id)

        monkeypatch.setattr(embed_service_module, "EmbedService", FakeEmbedService)

        result = await _fix_bad_embed_display_text(
            aggregated_response="More details are in [‑t3Z].",
            tool_calls_info=[{"embed_id": parent_id}],
            cache_service=object(),
            directus_service=None,
            encryption_service=object(),
            user_vault_key_id="vault-key",
        )

        assert result == "More details are in [iPhone Ultra Features](embed:9to5mac.com-t3Z)."

    # contract-test: supporting surface=gui.web assertions=web-search.surface-parity
    @pytest.mark.asyncio
    async def test_converts_suffix_only_refs_and_removes_unresolved_tokens(self, monkeypatch):
        from backend.core.api.app.services import embed_service as embed_service_module
        from toon_format import encode

        parent_id = "parent-embed"
        first_child_id = "first-child"
        second_child_id = "second-child"
        encoded = {
            parent_id: encode({"embed_ids": f"{first_child_id}|{second_child_id}"}),
            first_child_id: encode({
                "type": "website",
                "embed_ref": "mashable.com-7fJ",
                "title": "iPhone 18 Release Date Rumors",
            }),
            second_child_id: encode({
                "type": "website",
                "embed_ref": "macrumors.com-TW4",
                "title": "Split Release Schedule",
            }),
        }

        class FakeEmbedService:
            def __init__(self, **_kwargs):
                pass

            async def _get_cached_embed_toon(self, embed_id, *_args):
                return encoded.get(embed_id)

        monkeypatch.setattr(embed_service_module, "EmbedService", FakeEmbedService)

        result = await _fix_bad_embed_display_text(
            aggregated_response="Sources: [-7fj, ‑tw4, -NOPE]",
            tool_calls_info=[{"embed_id": parent_id}],
            cache_service=object(),
            directus_service=None,
            encryption_service=object(),
            user_vault_key_id="vault-key",
        )

        assert result == (
            "Sources: [iPhone 18 Release Date Rumors](embed:mashable.com-7fJ), "
            "[Split Release Schedule](embed:macrumors.com-TW4)"
        )
