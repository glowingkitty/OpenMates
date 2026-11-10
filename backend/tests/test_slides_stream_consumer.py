"""```slides fence creation and diff editing of a deck embed (stream_consumer hooks)."""

from types import SimpleNamespace

import pytest

from backend.apps.ai.tasks.stream_consumer import (
    _apply_diff_block_to_existing_embed,
    _create_slides_deck_embed_reference,
)
from backend.apps.ai.utils.slides_fences import _is_slides_fence
from backend.shared.python_utils.slides_markup import normalise_slides_markup
from backend.tests.test_embed_diff_full_replacement import (
    _FakeCacheService,
    _FakeDirectusService,
    _FakeEncryptionService,
)
from backend.tests.test_slides_markup import VALID

# contract-test: direct surface=rest_api assertions=slides.assistant.create-and-diff-edit
def test_fence_language_detection() -> None:
    assert _is_slides_fence("slides") and _is_slides_fence(" Slides ")
    assert not _is_slides_fence("html") and not _is_slides_fence(None)


class _DeckEmbedService:
    def __init__(self) -> None:
        self.created = None
        self.updated = None
        self.history_rows = None

    async def create_deck_embed(self, **kwargs):
        self.created = kwargs
        return {"embed_id": "deck-1", "embed_reference": '{"type": "deck", "embed_id": "deck-1"}'}

    async def update_deck_embed_content(self, **kwargs):
        self.updated = kwargs["deck"]
        self.history_rows = kwargs["version_history_rows"]
        return True


def _request() -> SimpleNamespace:
    return SimpleNamespace(
        chat_id="chat-1", message_id="message-1", user_id="user-1", user_id_hash="hash-1",
        embed_file_path_index={"q3-results-AbC": "deck-1"},
    )


# contract-test: direct surface=rest_api assertions=slides.security.host-rendered-and-isolated
@pytest.mark.anyio
async def test_slides_fence_creates_a_deck_embed_with_normalised_content() -> None:
    service = _DeckEmbedService()
    chunk = await _create_slides_deck_embed_reference(
        embed_service=service, source=VALID + "\n", request_data=_request(), task_id="t",
        user_vault_key_id="vault-1", log_prefix="[test]",
    )
    deck = service.created["deck"]
    assert (deck.title, deck.slide_count, deck.aspect) == ("Q3 results", 2, "16:9")
    assert deck.markup.startswith('<deck title="Q3 results"') and 'id="s1"' in deck.markup
    assert '"embed_id": "deck-1"' in chunk


# contract-test: direct surface=rest_api assertions=slides.security.host-rendered-and-isolated
@pytest.mark.anyio
async def test_unified_diff_changes_one_slide_and_deck_is_renormalised() -> None:
    from toon_format import encode

    original = normalise_slides_markup(VALID).markup
    patch = (
        "@@ -9,4 +9,4 @@\n"
        '     <notes>Speaker notes.</notes>\n'
        "   </slide>\n"
        '   <slide id="s2">\n'
        '-    <text id="e7" role="title">Second</text>\n'
        '+    <text id="e7" role="title" onclick="x()">Changed <script>y()</script>title</text>\n'
    )
    lines = original.splitlines()
    start = next(i for i, line in enumerate(lines) if "<notes>" in line) + 1
    patch = patch.replace("@@ -9,4 +9,4 @@", f"@@ -{start},4 +{start},4 @@")
    cache = _FakeCacheService({"deck-1": {
        "embed_id": "deck-1", "type": "deck", "status": "finished",
        "version_number": 1, "encrypted_content": "encrypted",
    }})
    service = _DeckEmbedService()
    result = await _apply_diff_block_to_existing_embed(
        diff_content=patch, diff_embed_ref="q3-results-AbC", request_data=_request(),
        cache_service=cache, directus_service=_FakeDirectusService(),
        encryption_service=_FakeEncryptionService(encode({
            "type": "deck", "slides_markup": original, "title": "Q3 results",
            "slide_count": 2, "aspect": "16:9",
        })),
        embed_service=service, user_vault_key_id="vault-1", log_prefix="[test]",
    )
    assert service.updated is not None, result
    markup = service.updated.markup
    assert '<text id="e7" role="title">Changed title</text>' in markup
    assert "onclick" not in markup and "script" not in markup
    assert 'src="embed:revenue-chart"' in markup  # untouched slide kept as is
    assert service.updated.slide_count == 2
    assert normalise_slides_markup(markup).markup == markup


class _PassThroughEncryption:
    async def encrypt_with_user_key(self, plaintext: str, _key_id: str):
        return f"encrypted:{len(plaintext)}", "v1"


class _DeckServiceHost:
    """Minimal EmbedService stand-in recording what the deck mixin sends to clients."""

    def __init__(self) -> None:
        self.sent = []
        self.cache = {}
        self.encryption_service = _PassThroughEncryption()

    async def update_deck_embed_content(self, **kwargs) -> bool:
        from backend.core.api.app.services.slides_embed_service import SlidesEmbedMixin

        return await SlidesEmbedMixin.update_deck_embed_content(self, **kwargs)

    def _generate_direct_embed_ref(self, *_args) -> str:
        return "q3-results-AbC"

    async def _cache_embed(self, embed_id, data, *_args) -> None:
        self.cache[embed_id] = data

    async def _get_cached_embed(self, embed_id, *_args):
        return self.cache.get(embed_id)

    async def _get_cached_embed_toon(self, *_args):
        return None

    def _schedule_embed_persistence_fallback(self, _embed_id) -> None:
        return None

    async def send_embed_data_to_client(self, **kwargs) -> None:
        self.sent.append(kwargs)


# contract-test: direct surface=rest_api assertions=slides.assistant.create-and-diff-edit
@pytest.mark.anyio
async def test_new_deck_is_sent_with_catalog_identity_and_a_version_one_snapshot() -> None:
    from backend.core.api.app.services.slides_embed_service import SlidesEmbedMixin

    host = _DeckServiceHost()
    deck = normalise_slides_markup(VALID)
    result = await SlidesEmbedMixin.create_deck_embed(
        host, chat_id="chat-1", message_id="message-1", user_id="user-1",
        user_id_hash="hash-1", user_vault_key_id="vault-1", deck=deck,
    )
    assert result is not None
    assert [event["status"] for event in host.sent] == ["processing", "finished"]
    for event in host.sent:
        # Clients reject a chat embed head without its app and skill identity.
        assert (event["app_id"], event["skill_id"], event["version_number"]) == ("slides", "deck", 1)
    finished = host.sent[-1]
    assert finished["content_hash"]
    assert [(row["version_number"], row["snapshot"]) for row in finished["version_history_rows"]] == [(1, deck.markup)]
