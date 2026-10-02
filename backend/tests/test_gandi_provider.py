"""Fixture-only contract tests for the anonymous Gandi provider."""

from __future__ import annotations

import json
import logging
from urllib.parse import parse_qs

import httpx
import pytest

from backend.shared.providers.gandi import GandiClient, SUPPORTED_CURRENCIES

pytestmark = pytest.mark.asyncio


def _factory(handler, calls):
    def make(**kwargs):
        calls.append(kwargs)
        return httpx.AsyncClient(transport=httpx.MockTransport(handler), timeout=kwargs["timeout"])
    return make


def _sse(*events):
    return "".join(f"event: {name}\ndata: {json.dumps(data)}\n\n" if data is not None
                   else f"event: {name}\n\n" for name, data in events)


def _tier(before, after, min_duration=1, *, normal=None, kind=None):
    value = {"duration_unit": "y", "min_duration": min_duration, "max_duration": 10,
             "price_before_taxes": before, "price_after_taxes": after,
             "discount": normal is not None, "options": {"phase": "golive"}, "features": []}
    if normal is not None:
        value.update(normal_price_before_taxes=normal[0], normal_price_after_taxes=normal[1])
    if kind:
        value["type"] = kind
    return value


def _prices(*, premium=False, min_duration=1):
    return {"currency": "EUR", "grid": "A", "taxes": [{"name": "vat", "rate": 19}],
            "products": [
                {"process": "renew", "name": "cedar.online" if premium else ".ai", "status": "available",
                 "prices": [_tier(1086.14 if premium else 40, 1292.51 if premium else 47.60, min_duration,
                                  kind="premium" if premium else None)], "phases": []},
                {"process": "create", "name": "cedar.online" if premium else ".ai", "status": "available",
                 "prices": [_tier(299.46 if premium else 11.99, 356.36 if premium else 14.27,
                                  min_duration, normal=(1008.82, 1200.50) if premium else None,
                                  kind="premium" if premium else None)], "phases": []},
            ]}


class _Secrets:
    def __init__(self):
        self.calls = []

    async def get_secret(self, path, key):
        self.calls.append((path, key))
        return {"proxy_username": "user:name", "proxy_password": "p@ss/word"}[key]


# contract-test: supporting surface=rest_api assertions=hosting-domains.lookup.exact,hosting-domains.quotes.truthful,hosting-domains.provider.bounded-fallback
async def test_lookup_preserves_premium_price_tiers_and_never_loads_proxy_on_direct_success():
    calls = []
    secrets = _Secrets()

    def handler(request):
        assert request.url.host == "shop.gandi.net"
        assert request.url.path.endswith("/lookup")
        assert request.headers["accept"] == "application/json"
        assert parse_qs(request.url.query.decode())["search"] == ["cedar.online"]
        return httpx.Response(200, json={"fqdn": "cedar.online", "availability": "available",
                                         "premium": 1, "prices": _prices(premium=True)})

    result = await GandiClient(secrets, client_factory=_factory(handler, calls)).lookup("cedar.online")
    payload = result.to_dict()
    assert result.availability == "available" and result.premium is True
    assert payload["registration"][0]["tiers"][0]["price_after_taxes"] == 356.36
    assert payload["registration"][0]["tiers"][0]["normal_price_after_taxes"] == 1200.5
    assert payload["renewal"][0]["tiers"][0]["price_after_taxes"] == 1292.51
    assert payload["registration"][0]["status"] == "available"
    assert payload["taxes"][0]["rate"] == 19
    assert result.url.startswith("https://shop.gandi.net/")
    assert result.checked_at and secrets.calls == [] and len(calls) == 1


# contract-test: supporting surface=rest_api assertions=hosting-domains.lookup.exact,hosting-domains.quotes.truthful,hosting-domains.results.partial-and-safe
async def test_lookup_idn_minimum_term_and_provider_error_not_unavailable():
    calls = []
    responses = [
        {"fqdn": "bücher-probe.ai", "availability": "available", "premium": 0,
         "prices": _prices(min_duration=2)},
        {"fqdn": "bad.invalid", "availability": "error", "premium": 0, "prices": {}},
    ]

    def handler(request):
        return httpx.Response(200, json=responses.pop(0))

    client = GandiClient(client_factory=_factory(handler, calls))
    result = await client.lookup("bücher-probe.ai")
    assert result.domain_ascii == "xn--bcher-probe-thb.ai"
    assert result.domain_unicode == "bücher-probe.ai"
    assert result.registration[0].tiers[0].min_duration == 2
    assert result.renewal[0].tiers[0].min_duration == 2
    unknown = await client.lookup("bad.invalid")
    assert unknown.availability == "unknown" and unknown.provider_status == "error"
    assert unknown.pricing_status == "missing"


# contract-test: supporting surface=rest_api assertions=hosting-domains.results.partial-and-safe,hosting-domains.quotes.truthful
async def test_suggestion_events_join_by_idna_name_and_keep_candidate_order():
    calls = []
    stream = _sse(
        ("das", {"fqdn": "bücher.ai", "availability": "available", "premium": 0, "reserved": 0}),
        ("billing", {"fqdn": "xn--bcher-kva.ai", "prices": _prices(min_duration=2)}),
        ("das", {"fqdn": "cedar.online", "availability": "available", "premium": 1, "reserved": 0}),
        ("billing_failed", {"fqdn": "cedar.online", "prices": {}}),
        ("suggestions", [
            {"fqdn": "cedar.online", "tld": "online", "corporate": True,
             "restriction": "Registration restricted", "categories": ["gTLD"]},
            {"fqdn": "bücher.ai", "tld": "ai", "corporate": False},
        ]),
        ("done", None),
    )

    def handler(request):
        assert request.url.params.get_list("tlds") == []
        return httpx.Response(200, text=stream, headers={"Content-Type": "text/event-stream"})

    result = await GandiClient(client_factory=_factory(handler, calls)).search("cedar", max_results=2)
    assert [item.domain_ascii for item in result.results] == ["cedar.online", "xn--bcher-kva.ai"]
    assert result.results[0].corporate is True and result.results[0].restriction == "Registration restricted"
    assert result.results[0].availability == "available" and result.results[0].pricing_status == "missing"
    assert result.results[1].registration[0].tiers[0].min_duration == 2
    assert result.error is None and not result.partial
    assert result.to_dict()["results"][1]["domain_unicode"] == "bücher.ai"


# contract-test: supporting surface=rest_api assertions=hosting-domains.provider.bounded-fallback,hosting-domains.request.validated
async def test_search_one_tld_two_pages_and_rejects_tld_lists():
    calls = []
    page = 0

    def handler(request):
        nonlocal page
        page += 1
        assert request.url.params.get_list("tlds") == ["net"]
        body = _sse(("pagination", {"next": "untrusted" if page == 1 else None}),
                    ("suggestions", [{"fqdn": f"name{page}.net"}, {"fqdn": "stray.com"}]),
                    ("das", {"fqdn": f"name{page}.net", "availability": "available"}),
                    ("done", None))
        return httpx.Response(200, text=body, headers={"Content-Type": "text/event-stream"})

    client = GandiClient(client_factory=_factory(handler, calls))
    result = await client.search("name", max_results=40, tld="net")
    assert [item.domain_ascii for item in result.results] == ["name1.net", "name2.net"]
    assert page == 2
    with pytest.raises(ValueError):
        await client.search("name", tld="com,net")


# contract-test: supporting surface=rest_api assertions=hosting-domains.provider.bounded-fallback,hosting-domains.results.partial-and-safe
async def test_partial_stream_preserves_children_when_proxy_is_unavailable(monkeypatch):
    calls = []
    monkeypatch.delenv("SECRET__WEBSHARE__PROXY_USERNAME", raising=False)
    monkeypatch.delenv("SECRET__WEBSHARE__PROXY_PASSWORD", raising=False)

    def handler(request):
        return httpx.Response(200, text=_sse(("suggestions", [{"fqdn": "child.com"}]),
                                             ("das", {"fqdn": "child.com", "availability": "available"})),
                              headers={"Content-Type": "text/event-stream"})

    result = await GandiClient(client_factory=_factory(handler, calls)).search("child")
    assert result.partial and result.error == "incomplete_stream"
    assert len(result.results) == 1 and result.results[0].availability == "available"
    assert len(calls) == 1


# contract-test: supporting surface=rest_api assertions=hosting-domains.provider.bounded-fallback,hosting-domains.results.partial-and-safe
async def test_403_uses_one_proxy_attempt_and_escapes_credentials():
    calls = []
    secrets = _Secrets()
    attempts = 0

    def handler(request):
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            return httpx.Response(403)
        return httpx.Response(200, json={"fqdn": "name.com", "availability": "unavailable",
                                         "premium": 0, "prices": {}})

    result = await GandiClient(secrets, client_factory=_factory(handler, calls)).lookup("name.com")
    assert result.availability == "unavailable" and result.error is None
    assert attempts == 2 and len(calls) == 2 and calls[0]["proxy"] is None
    assert calls[1]["proxy"] == "http://user%3Aname-rotate:p%40ss%2Fword@p.webshare.io:80"
    assert secrets.calls == [("kv/data/providers/webshare", "proxy_username"),
                             ("kv/data/providers/webshare", "proxy_password")]


# contract-test: supporting surface=rest_api assertions=hosting-domains.provider.bounded-fallback,hosting-domains.results.partial-and-safe
async def test_timeout_fallback_and_429_retry_after_never_rotates():
    calls = []
    secrets = _Secrets()
    attempts = 0

    def handler(request):
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise httpx.ReadTimeout("timeout")
        return httpx.Response(429, headers={"Retry-After": "120"})

    result = await GandiClient(secrets, client_factory=_factory(handler, calls)).search("name")
    assert result.partial and result.error == "rate_limited" and result.retry_after == "120"
    assert attempts == 2 and len(calls) == 2

    calls.clear()
    secrets.calls.clear()
    limited = await GandiClient(secrets, client_factory=_factory(
        lambda request: httpx.Response(429, headers={"Retry-After": "60"}), calls)).lookup("name.com")
    assert limited.error == "rate_limited" and limited.retry_after == "60"
    assert len(calls) == 1 and not secrets.calls


# contract-test: supporting surface=rest_api assertions=hosting-domains.quotes.truthful,hosting-domains.results.partial-and-safe
async def test_malformed_price_fields_and_nonfinite_values_remain_json_safe():
    calls = []

    def handler(request):
        payload = {
            "fqdn": "name.com", "availability": "available", "premium": 0,
            "prices": {"currency": "EUR", "taxes": [{"rate": float("nan")}], "products": [
                {"process": "create", "prices": None},
                {"process": "renew", "prices": [{"duration_unit": "y", "min_duration": 1,
                                                   "price_after_taxes": float("inf"),
                                                   "options": {"bad": float("nan")}}]},
            ]},
        }
        return httpx.Response(200, content=json.dumps(payload).encode(), headers={"Content-Type": "application/json"})

    result = await GandiClient(client_factory=_factory(handler, calls)).lookup("name.com")
    assert result.availability == "available"
    assert result.registration[0].tiers == []
    assert result.renewal[0].tiers[0].price_after_taxes is None
    assert result.pricing_status == "missing"
    assert result.to_dict()["taxes"][0]["rate"] is None
    json.dumps(result.to_dict(), allow_nan=False)


# contract-test: supporting surface=rest_api assertions=hosting-domains.provider.bounded-fallback,hosting-domains.results.partial-and-safe
async def test_incomplete_child_status_triggers_single_fallback_and_keeps_order():
    calls = []
    secrets = _Secrets()
    attempts = 0

    def handler(request):
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            body = _sse(("suggestions", [{"fqdn": "first.com"}, {"fqdn": "second.com"}]),
                        ("das", {"fqdn": "first.com", "availability": "available"}),
                        ("done", None))
        else:
            body = _sse(("suggestions", [{"fqdn": "second.com"}]),
                        ("das", {"fqdn": "second.com", "availability": "unavailable"}),
                        ("done", None))
        return httpx.Response(200, text=body, headers={"Content-Type": "text/event-stream"})

    result = await GandiClient(secrets, client_factory=_factory(handler, calls)).search("name")
    assert not result.partial and result.error is None
    assert [item.domain_ascii for item in result.results] == ["first.com", "second.com"]
    assert [item.availability for item in result.results] == ["available", "unavailable"]
    assert attempts == 2


# contract-test: supporting surface=rest_api assertions=hosting-domains.quotes.truthful,hosting-domains.provider.bounded-fallback
async def test_wrong_currency_quote_is_missing_without_proxy_retry():
    calls = []
    secrets = _Secrets()

    def handler(request):
        quoted = _prices()
        quoted["currency"] = "USD"
        return httpx.Response(200, json={"fqdn": "name.com", "availability": "available",
                                         "premium": 0, "prices": quoted})

    result = await GandiClient(secrets, client_factory=_factory(handler, calls)).lookup("name.com", currency="EUR")
    assert result.availability == "available" and result.currency == "EUR"
    assert result.registration == [] and result.renewal == []
    assert result.pricing_status == "missing" and result.pricing_error == "currency_mismatch"
    assert len(calls) == 1 and secrets.calls == []
    assert SUPPORTED_CURRENCIES == {"EUR", "USD"}


# contract-test: supporting surface=rest_api assertions=hosting-domains.provider.bounded-fallback,hosting-domains.results.partial-and-safe,hosting-domains.quotes.truthful
async def test_proxy_unknown_child_does_not_replace_confirmed_direct_status_or_add_quote():
    calls = []
    secrets = _Secrets()
    attempts = 0

    def handler(request):
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            body = _sse(("suggestions", [{"fqdn": "available.com"}, {"fqdn": "used.com"}]),
                        ("das", {"fqdn": "available.com", "availability": "available"}),
                        ("das", {"fqdn": "used.com", "availability": "unavailable"}))
        else:
            body = _sse(("suggestions", [{"fqdn": "available.com"}, {"fqdn": "used.com"}]),
                        ("das_failed", {"fqdn": "available.com", "availability": "error"}),
                        ("das_failed", {"fqdn": "used.com", "availability": "error"}),
                        ("billing", {"fqdn": "available.com", "prices": _prices()}),
                        ("done", None))
        return httpx.Response(200, text=body, headers={"Content-Type": "text/event-stream"})

    result = await GandiClient(secrets, client_factory=_factory(handler, calls)).search("name")
    assert [item.availability for item in result.results] == ["available", "unavailable"]
    assert result.results[0].registration == []
    assert result.results[0].pricing_status == "missing"
    assert result.results[0].error is None and result.results[1].error is None
    assert not result.partial and result.error is None and attempts == 2


# contract-test: supporting surface=rest_api assertions=hosting-domains.results.partial-and-safe,hosting-domains.provider.bounded-fallback
async def test_gandi_http_library_logs_hide_query_on_success_and_preserve_other_requests(caplog):
    caplog.set_level(logging.DEBUG, logger="httpcore.http11")
    caplog.set_level(logging.INFO, logger="httpx")
    secret = "private-synthetic-customer-name"
    calls = []

    def handler(request):
        logging.getLogger("httpcore.http11").debug(
            "send_request_headers.started path=b'/api/v5/suggest/suggest?search=%s'", secret)
        logging.getLogger("httpx").info(
            'HTTP Request: %s %s "%s %d %s"',
            "GET", httpx.URL("https://elsewhere.test/?query=visible"), "HTTP/1.1", 200, "OK")
        return httpx.Response(200, text=_sse(("suggestions", []), ("done", None)),
                              headers={"Content-Type": "text/event-stream"})

    result = await GandiClient(client_factory=_factory(handler, calls)).search(secret)
    assert result.error is None
    messages = "\n".join(caplog.messages)
    assert secret not in messages
    assert "GET https://shop.gandi.net/api/v5/suggest/suggest status=200" in messages
    assert "https://elsewhere.test/?query=visible" in messages
    assert all(secret not in str(record.args) for record in caplog.records)


# contract-test: supporting surface=rest_api assertions=hosting-domains.results.partial-and-safe,hosting-domains.provider.bounded-fallback
async def test_gandi_http_library_exception_logs_hide_query_and_restore_scope(caplog, monkeypatch):
    caplog.set_level(logging.DEBUG, logger="httpcore.http11")
    caplog.set_level(logging.INFO, logger="httpx")
    monkeypatch.delenv("SECRET__WEBSHARE__PROXY_USERNAME", raising=False)
    monkeypatch.delenv("SECRET__WEBSHARE__PROXY_PASSWORD", raising=False)
    secret = "private-synthetic-exact-domain.com"
    proxy_secret = "synthetic-private-proxy-token"
    calls = []

    def handler(request):
        try:
            raise httpx.ReadTimeout(f"{secret} https://shop.gandi.net/api/v5/suggest/lookup?search={secret}")
        except httpx.ReadTimeout:
            logging.getLogger("httpcore.http11").error(
                "%s receive_response_headers.failed", secret, exc_info=True, stack_info=True)
            logging.getLogger("httpx").error(
                "Request failed for %s with proxy %s", secret, proxy_secret,
                exc_info=True, stack_info=True)
        raise httpx.ReadTimeout("synthetic timeout")

    result = await GandiClient(client_factory=_factory(handler, calls)).lookup(secret)
    assert result.error == "network_timeout"
    messages = "\n".join(caplog.messages)
    assert secret not in messages
    assert secret not in caplog.text
    assert proxy_secret not in caplog.text
    assert "GET https://shop.gandi.net/api/v5/suggest/lookup" in messages
    assert all(secret not in str(record.args) for record in caplog.records)
    logging.getLogger("httpx").info("Other request after Gandi: %s", "https://elsewhere.test/?query=visible")
    assert "https://elsewhere.test/?query=visible" in caplog.messages[-1]
