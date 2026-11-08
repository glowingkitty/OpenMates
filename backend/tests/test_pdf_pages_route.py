# backend/tests/test_pdf_pages_route.py
#
# First-party on-demand PDF page render route (pdf-processing.view.on-demand-render):
# ownership, page bounds, reuse of an existing render and the stored key after a new render.

from __future__ import annotations

import asyncio
import types

import pytest
from fastapi import HTTPException
from toon_format import encode as toon_encode

from backend.apps.pdf.services.page_render_service import PageRender
from backend.core.api.app.routes import pdf_pages

OWNER = "user-1"


class _Redis:
    def __init__(self):
        self.stored = {}

    async def set(self, key, value, **kwargs):
        self.stored[key] = (value, kwargs)


class _Cache:
    def __init__(self, embed):
        self.embed = embed
        self.redis = _Redis()

    async def get_embed_from_cache(self, _embed_id):
        return self.embed

    @property
    async def client(self):
        return self.redis

    def _get_embed_cache_key(self, embed_id):
        return f"embed:{embed_id}"


class _Encryption:
    async def decrypt_with_user_key(self, ciphertext, _key_id):
        return ciphertext

    async def encrypt_with_user_key(self, plaintext, _key_id):
        return plaintext, "1"


def _content(**overrides):
    content = {"type": "pdf", "status": "finished", "page_count": 5, "vault_wrapped_aes_key": "wrapped",
               "screenshot_s3_keys": {"1": "chatfiles/u/p1.png.bin"}}
    content.update(overrides)
    return content


def _call(embed, page_number, monkeypatch, render=None):
    cache = _Cache(embed)
    state = types.SimpleNamespace(
        cache_service=cache, encryption_service=_Encryption(), s3_service=object(), secrets_manager=object()
    )
    request = types.SimpleNamespace(app=types.SimpleNamespace(state=state))
    if render is not None:
        monkeypatch.setattr(pdf_pages, "get_page_render", render)
    user = types.SimpleNamespace(id=OWNER, vault_key_id="vault-key")
    coroutine = pdf_pages.render_pdf_page.__wrapped__(request, "embed-1", page_number, user)
    return asyncio.run(coroutine), cache


def _embed(content=None, **overrides):
    embed = {"user_id": OWNER, "vault_key_id": "vault-key", "encrypted_content": toon_encode(content or _content())}
    embed.update(overrides)
    return embed


# contract-test: supporting surface=rest_api assertions=pdf-processing.view.on-demand-render
def test_already_rendered_page_is_returned_without_rendering(monkeypatch):
    def fail(**_kwargs):
        raise AssertionError("must not render again")

    result, _cache = _call(_embed(), 1, monkeypatch, render=fail)
    assert (result.status, result.s3_key) == ("ok", "chatfiles/u/p1.png.bin")


# contract-test: supporting surface=rest_api assertions=pdf-processing.view.on-demand-render
def test_new_page_is_rendered_once_and_its_key_is_returned(monkeypatch):
    calls = []

    async def fake_render(**kwargs):
        calls.append(kwargs["page_number"])
        await kwargs["record_key"](kwargs["page_number"], "chatfiles/u/p3.png.bin")
        return PageRender(kwargs["page_number"], "ok", b"png", "chatfiles/u/p3.png.bin")

    result, cache = _call(_embed(), 3, monkeypatch, render=fake_render)
    assert calls == [3]
    assert (result.status, result.s3_key) == ("ok", "chatfiles/u/p3.png.bin")
    stored, options = cache.redis.stored["embed:embed-1"]
    assert "p3.png.bin" in stored and options == {"keepttl": True}


# contract-test: supporting surface=rest_api assertions=pdf-processing.safety.image-fail-closed
def test_withheld_page_has_a_status_but_no_key(monkeypatch):
    async def fake_render(**kwargs):
        return PageRender(kwargs["page_number"], "withheld")

    result, _cache = _call(_embed(), 2, monkeypatch, render=fake_render)
    assert (result.status, result.s3_key) == ("withheld", None)


@pytest.mark.parametrize(
    "embed,page,status",
    [
        (_embed(user_id="someone-else"), 2, 404),
        (None, 2, 404),
        (_embed(), 6, 404),
        (_embed(_content(status="error")), 2, 409),
    ],
)
# contract-test: supporting surface=rest_api assertions=pdf-processing.view.on-demand-render
def test_foreign_missing_out_of_range_or_failed_embeds_are_refused(embed, page, status, monkeypatch):
    with pytest.raises(HTTPException) as caught:
        _call(embed, page, monkeypatch)
    assert caught.value.status_code == status
