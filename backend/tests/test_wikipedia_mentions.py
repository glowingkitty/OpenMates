# backend/tests/test_wikipedia_mentions.py
#
# Contract tests for explicit Wikipedia mention resolution and safe AI context.
# They cover the approved feature.wikipedia-mentions@1 assertions before product
# implementation, using provider fakes rather than Wikimedia or Groq requests.
# See: docs/specs/wikipedia-mentions/spec.yml and contracts/features/wikipedia-mentions/contract.yml.

from __future__ import annotations

from typing import Any
from types import SimpleNamespace
from unittest.mock import AsyncMock
import json
import sys
import types

import httpx
import pytest
from fastapi import HTTPException

from backend.apps.ai.processing.wikipedia_context import (
    WikipediaSafetyUnavailableError,
    build_wikipedia_reference_context,
)
from backend.core.api.app.utils.override_parser import (
    WikipediaReferenceLimitError,
    parse_wikipedia_directives,
)
from backend.shared.providers.wikipedia import wikipedia_api
from backend.shared.providers.wikipedia.wikipedia_api import (
    WikipediaSearchResult,
    _request_with_retry,
    search_wikipedia_titles,
)


def _import_wikipedia_proxy():
    if "slowapi" not in sys.modules:
        slowapi_module = types.ModuleType("slowapi")
        slowapi_util_module = types.ModuleType("slowapi.util")

        class _LimiterStub:
            def __init__(self, *_args, **_kwargs) -> None:
                pass

            def limit(self, *_args, **_kwargs):
                return lambda func: func

        slowapi_module.Limiter = _LimiterStub
        slowapi_util_module.get_remote_address = lambda _request: "127.0.0.1"
        sys.modules["slowapi"] = slowapi_module
        sys.modules["slowapi.util"] = slowapi_util_module
    if "backend.core.api.app.routes.apps_api" not in sys.modules:
        apps_api_module = types.ModuleType("backend.core.api.app.routes.apps_api")

        async def _charge_credits_via_internal_api(*_args, **_kwargs) -> None:
            return None

        async def _get_session_or_api_key_info(*_args, **_kwargs) -> None:
            from fastapi import HTTPException

            raise HTTPException(status_code=401, detail="unauthenticated")

        apps_api_module.charge_credits_via_internal_api = _charge_credits_via_internal_api
        apps_api_module.get_session_or_api_key_info = _get_session_or_api_key_info
        sys.modules["backend.core.api.app.routes.apps_api"] = apps_api_module
    from backend.core.api.app.routes import wikipedia_proxy

    return wikipedia_proxy


pytestmark = pytest.mark.asyncio


class _FakeResponse:
    def __init__(
        self,
        status_code: int,
        payload: dict[str, Any],
        headers: dict[str, str] | None = None,
    ) -> None:
        self.status_code = status_code
        self._payload = payload
        self.headers = headers or {}
        self.request = httpx.Request("GET", "https://en.wikipedia.org/api/rest_v1/page/title/search")

    def json(self) -> dict[str, Any]:
        return self._payload

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise httpx.HTTPStatusError("upstream error", request=self.request, response=self)


class _FakeClient:
    def __init__(self, responses: list[_FakeResponse]) -> None:
        self.responses = responses
        self.calls: list[dict[str, Any]] = []

    async def get(self, url: str, **kwargs: Any) -> _FakeResponse:
        self.calls.append({"url": url, **kwargs})
        return self.responses.pop(0)


class _FakeClientContext:
    def __init__(self, client: _FakeClient) -> None:
        self.client = client

    async def __aenter__(self) -> _FakeClient:
        return self.client

    async def __aexit__(self, *_args: Any) -> None:
        return None


# contract-test: direct surface=rest_api assertions=wikipedia-mentions.syntax.explicit-trigger,wikipedia-mentions.resolution.first-result,wikipedia-mentions.provider.bounded-access,wikipedia-mentions.privacy.explicit-third-party-query
async def test_title_search_normalizes_locale_preserves_first_result_and_omits_wikidata(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = _FakeClient(
        [
            _FakeResponse(
                200,
                {
                    "pages": [
                        {
                            "id": 736,
                            "key": "Albert_Einstein",
                            "title": "Albert Einstein",
                            "description": "German-born theoretical physicist",
                            "thumbnail": {"url": "https://upload.wikimedia.org/albert.jpg"},
                            "type": "standard",
                        },
                        {"id": 12, "key": "Albert", "title": "Albert", "type": "standard"},
                    ]
                },
            )
        ]
    )
    monkeypatch.setattr(
        wikipedia_api,
        "create_http_client",
        lambda *_args, **_kwargs: _FakeClientContext(client),
    )

    results = await search_wikipedia_titles("AlbertEinstein", language="de-DE", limit=2)

    assert [result.title for result in results] == ["Albert Einstein", "Albert"]
    assert results[0].language == "de"
    assert results[0].disambiguation is False
    assert client.calls[0]["params"] == {"q": "AlbertEinstein", "limit": 2}
    assert client.calls[0]["url"].startswith("https://de.wikipedia.org/")
    assert "wikidata" not in WikipediaSearchResult.model_fields
    assert "wikibase_item" not in results[0].model_dump()
    assert all("wikidata.org" not in call["url"] for call in client.calls)


# contract-test: direct surface=rest_api assertions=wikipedia-mentions.resolution.disambiguation-visible,wikipedia-mentions.resolution.first-result
async def test_title_search_marks_first_disambiguation_without_reranking(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = _FakeClient(
        [
            _FakeResponse(
                200,
                {
                    "pages": [
                        {"id": 19085, "key": "Mercury", "title": "Mercury", "type": "disambiguation"},
                        {"id": 18939, "key": "Mercury_(planet)", "title": "Mercury (planet)", "type": "standard"},
                    ]
                },
            )
        ]
    )
    monkeypatch.setattr(
        wikipedia_api,
        "create_http_client",
        lambda *_args, **_kwargs: _FakeClientContext(client),
    )

    results = await search_wikipedia_titles("Mercury", language="en")

    assert results[0].title == "Mercury"
    assert results[0].disambiguation is True
    assert results[1].title == "Mercury (planet)"
    assert results[1].disambiguation is False


# contract-test: direct surface=rest_api assertions=wikipedia-mentions.syntax.explicit-trigger,wikipedia-mentions.references.maximum-three,wikipedia-mentions.privacy.explicit-third-party-query
async def test_canonical_directives_are_locale_aware_ordered_and_ignore_generic_mentions() -> None:
    parsed = parse_wikipedia_directives(
        "@friend:alice @WIKIPEDIA:en:Mercury_%28planet%29 @wikipedia:Albert_Einstein compare them",
        locale="de-DE",
    )

    assert [(reference.language, reference.title) for reference in parsed.references] == [
        ("en", "Mercury_(planet)"),
        ("de", "Albert_Einstein"),
    ]
    assert parsed.cleaned_message == "@friend:alice compare them"


# contract-test: direct surface=rest_api assertions=wikipedia-mentions.references.maximum-three
async def test_fourth_canonical_directive_fails_before_inference() -> None:
    with pytest.raises(WikipediaReferenceLimitError, match="three"):
        parse_wikipedia_directives(
            "@wikipedia:en:One @wikipedia:en:Two @wikipedia:en:Three @wikipedia:en:Four",
            locale="en",
        )


# contract-test: direct surface=rest_api assertions=wikipedia-mentions.context.summary-only,wikipedia-mentions.safety.fail-closed
async def test_reference_context_is_bounded_sanitized_summary_only(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sanitizer = AsyncMock(side_effect=lambda content, **_kwargs: content.replace("\u200b", ""))
    monkeypatch.setattr(
        "backend.apps.ai.processing.wikipedia_context.sanitize_external_content",
        sanitizer,
    )

    context = await build_wikipedia_reference_context(
        [
            {
                "language": "en",
                "page_id": 736,
                "canonical_title": "Albert_Einstein",
                "source_url": "https://en.wikipedia.org/wiki/Albert_Einstein",
                "revision": "123",
                "description": "German\u200b-born physicist",
                "lead_extract": "A" * 20_000,
                "html": "<p>must not enter context</p>",
                "thumbnail_url": "https://upload.wikimedia.org/albert.jpg",
                "wikibase_item": "Q937",
            }
        ],
        task_id="test-wikipedia-context",
    )

    assert context[0]["description"] == "German-born physicist"
    assert len(context[0]["lead_extract"]) < 20_000
    assert set(context[0]) <= {
        "language", "page_id", "canonical_title", "source_url", "revision", "description", "lead_extract"
    }
    assert "wikibase_item" not in context[0]
    assert sanitizer.await_count == 2


# contract-test: direct surface=rest_api assertions=wikipedia-mentions.safety.fail-closed
async def test_unavailable_or_blocked_safety_rejects_all_wikipedia_context(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "backend.apps.ai.processing.wikipedia_context.sanitize_external_content",
        AsyncMock(return_value=""),
    )

    with pytest.raises(WikipediaSafetyUnavailableError):
        await build_wikipedia_reference_context(
            [{"language": "en", "page_id": 1, "canonical_title": "Safe", "lead_extract": "unsafe prose"}],
            task_id="test-wikipedia-context",
        )


# contract-test: direct surface=rest_api assertions=wikipedia-mentions.provider.bounded-access
@pytest.mark.parametrize("status_code", [429, 503])
async def test_retry_after_is_honored_for_upstream_throttling_and_overload(
    monkeypatch: pytest.MonkeyPatch,
    status_code: int,
) -> None:
    client = _FakeClient(
        [
            _FakeResponse(status_code, {}, {"Retry-After": "7"}),
            _FakeResponse(200, {"pages": []}),
        ]
    )
    sleep = AsyncMock()
    monkeypatch.setattr("backend.shared.providers.wikipedia.wikipedia_api.asyncio.sleep", sleep)

    response = await _request_with_retry(client, "https://example.invalid", {}, {})

    assert response.status_code == 200
    sleep.assert_awaited_once_with(7.0)


# contract-test: direct surface=rest_api assertions=wikipedia-mentions.resolution.first-result,wikipedia-mentions.privacy.explicit-third-party-query
async def test_proxy_search_returns_ordered_results_without_wikidata(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    wikipedia_proxy = _import_wikipedia_proxy()
    monkeypatch.setattr(wikipedia_proxy, "_authorize_request", AsyncMock(return_value={"source": "api_key"}))
    monkeypatch.setattr(wikipedia_proxy, "_check_anon_rate_limit", AsyncMock())
    monkeypatch.setattr(wikipedia_proxy, "_charge_if_api_key", AsyncMock())
    monkeypatch.setattr(
        wikipedia_proxy,
        "_fetch_cached_wikipedia_payload",
        AsyncMock(return_value=[
            WikipediaSearchResult(page_id=736, key="Albert_Einstein", title="Albert Einstein", language="en"),
        ]),
    )

    response = await wikipedia_proxy.wikipedia_search(SimpleNamespace(), SimpleNamespace(), query="AlbertEinstein", language="en", limit=2)
    payload = json.loads(response.body.decode("utf-8"))

    assert payload["results"][0]["title"] == "Albert Einstein"
    assert "wikidata" not in payload["results"][0]
    assert "wikibase_item" not in payload["results"][0]


# contract-test: direct surface=rest_api assertions=wikipedia-mentions.context.summary-only,wikipedia-mentions.safety.fail-closed
async def test_proxy_summary_returns_summary_only_payload(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    wikipedia_proxy = _import_wikipedia_proxy()
    monkeypatch.setattr(wikipedia_proxy, "_authorize_request", AsyncMock(return_value={"source": "api_key"}))
    monkeypatch.setattr(wikipedia_proxy, "_check_anon_rate_limit", AsyncMock())
    monkeypatch.setattr(wikipedia_proxy, "_charge_if_api_key", AsyncMock())
    monkeypatch.setattr(
        wikipedia_proxy,
        "_fetch_cached_wikipedia_payload",
        AsyncMock(return_value={
            "pageid": 736,
            "title": "Albert Einstein",
            "titles": {"canonical": "Albert_Einstein"},
            "description": "German-born theoretical physicist",
            "extract": "Albert Einstein was a theoretical physicist.",
            "content_urls": {"desktop": {"page": "https://en.wikipedia.org/wiki/Albert_Einstein"}},
            "originalimage": {"source": "https://upload.wikimedia.org/full.jpg"},
            "wikibase_item": "Q937",
        }),
    )

    response = await wikipedia_proxy.wikipedia_summary(SimpleNamespace(), SimpleNamespace(), title="Albert_Einstein", language="en")
    payload = json.loads(response.body.decode("utf-8"))

    assert payload["canonical_title"] == "Albert_Einstein"
    assert payload["extract"]
    assert "originalimage" not in payload
    assert "wikibase_item" not in payload


# contract-test: direct surface=rest_api assertions=wikipedia-mentions.provider.bounded-access
async def test_proxy_search_rejects_unauthenticated_before_upstream_fetch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    wikipedia_proxy = _import_wikipedia_proxy()
    fetch = AsyncMock()
    monkeypatch.setattr(
        wikipedia_proxy,
        "_authorize_request",
        AsyncMock(side_effect=HTTPException(status_code=401, detail="unauthenticated")),
    )
    monkeypatch.setattr(wikipedia_proxy, "_fetch_cached_wikipedia_payload", fetch)

    with pytest.raises(HTTPException) as exc_info:
        await wikipedia_proxy.wikipedia_search(SimpleNamespace(), SimpleNamespace(), query="AlbertEinstein", language="en", limit=2)

    assert getattr(exc_info.value, "status_code", None) == 401
    fetch.assert_not_awaited()
