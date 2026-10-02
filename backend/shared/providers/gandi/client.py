"""Bounded anonymous access to Gandi's shop lookup and suggestion endpoints.

The shop interface is undocumented. A transport failure can use one residential
proxy attempt; domain availability and missing prices are separate outcomes.
"""

from __future__ import annotations

import asyncio
from contextlib import contextmanager
from contextvars import ContextVar
import json
import logging
import math
import os
import re
from threading import Lock
from dataclasses import dataclass, field
from typing import Any, Callable
from urllib.parse import quote, urlencode

import httpx

from backend.shared.testing.caching_http_transport import create_http_client

from .models import DomainPriceProduct, DomainPriceTier, DomainResult, DomainSearchResult, checked_now

_ORIGIN = "https://shop.gandi.net"
_API = f"{_ORIGIN}/api/v5/suggest"
_HEADERS = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36",
    "Referer": f"{_ORIGIN}/en/domain/suggest",
}
_VAULT_PATH = "kv/data/providers/webshare"
# Only EUR/DE and USD/US are evidenced by the bounded anonymous probe.
SUPPORTED_CURRENCIES = frozenset({"EUR", "USD"})
MAX_RESULTS = 40
_MAX_BODY_BYTES = 512_000
_MAX_EVENTS = 160
_LOG_CONTEXT: ContextVar[str | None] = ContextVar("gandi_request_path", default=None)
_LOG_FACTORY_LOCK = Lock()
_LOG_STATUS = re.compile(r"\b(?:status(?:_code)?[=: ]+|HTTP/[12](?:\.\d)?['\", ]+)([1-5][0-9]{2})\b")


def _install_log_redaction() -> None:
    """Sanitize library records before any handler, including CI capture, sees them."""
    with _LOG_FACTORY_LOCK:
        previous = logging.getLogRecordFactory()
        if getattr(previous, "_gandi_url_redaction", False):
            return

        def make_record(*args: Any, **kwargs: Any) -> logging.LogRecord:
            record = previous(*args, **kwargs)
            path = _LOG_CONTEXT.get()
            if path is None or not (record.name == "httpx" or record.name.startswith("httpcore")):
                return record
            if (
                record.name == "httpx"
                and record.msg == 'HTTP Request: %s %s "%s %d %s"'
                and isinstance(record.args, tuple)
                and len(record.args) == 5
                and isinstance(record.args[1], httpx.URL)
                and record.args[1].scheme in {"http", "https"}
                and record.args[1].host
                and record.args[1].host != "shop.gandi.net"
            ):
                # Only a recognized request to another origin can bypass this
                # scope. Originless diagnostics can still contain private data.
                return record
            # httpx includes the URL object as an argument; httpcore can place
            # full URLs, query strings, or exception reprs inside its message.
            # Build from known safe values rather than trying to scrub every
            # possible encoding of the private query or proxy credentials.
            event = "request" if record.name == "httpx" else "transport"
            status = None
            if record.name == "httpx" and isinstance(record.args, tuple) and len(record.args) >= 5:
                value = record.args[3]
                status = value if isinstance(value, int) and 100 <= value <= 599 else None
            else:
                rendered = record.getMessage()
                match = _LOG_STATUS.search(rendered)
                status = match.group(1) if match else None
            record.msg = f"Gandi HTTP {event}: GET {_ORIGIN}{path}" + (f" status={status}" if status else "")
            record.args = ()
            record.exc_info = None
            record.exc_text = None
            record.stack_info = None
            return record

        make_record._gandi_url_redaction = True  # type: ignore[attr-defined]
        logging.setLogRecordFactory(make_record)


@contextmanager
def _request_log_context(endpoint: str):
    token = _LOG_CONTEXT.set(f"/api/v5/suggest/{endpoint}")
    try:
        yield
    finally:
        _LOG_CONTEXT.reset(token)


class _ProviderFailure(Exception):
    def __init__(self, code: str, *, fallback: bool = False, retry_after: str | None = None):
        super().__init__(code)
        self.code = code
        self.fallback = fallback
        self.retry_after = retry_after


@dataclass
class _Page:
    results: list[DomainResult] = field(default_factory=list)
    next_page: bool = False
    failure: _ProviderFailure | None = None


def _currency(value: str) -> str:
    value = value.upper()
    if value not in SUPPORTED_CURRENCIES:
        raise ValueError("Unsupported currency")
    return value


def _locale(value: str, *, length: int) -> str:
    if not isinstance(value, str) or len(value) != length or not value.isalpha() or not value.isascii():
        raise ValueError("Invalid locale")
    return value.upper() if length == 2 else value.lower()


def _fqdn(value: str) -> tuple[str, str]:
    if not isinstance(value, str) or len(value) > 253 or value != value.strip():
        raise ValueError("Invalid domain")
    value = value.rstrip(".").lower()
    if "." not in value:
        raise ValueError("A full domain name is required")
    try:
        ascii_name = value.encode("idna").decode("ascii")
        labels = ascii_name.split(".")
        if any(not label or len(label) > 63 or label[0] == "-" or label[-1] == "-" or
               any(char not in "abcdefghijklmnopqrstuvwxyz0123456789-" for char in label)
               for label in labels):
            raise ValueError
        unicode_name = ascii_name.encode("ascii").decode("idna")
    except (UnicodeError, ValueError) as exc:
        raise ValueError("Invalid domain") from exc
    return ascii_name, unicode_name


def _url(domain_ascii: str) -> str:
    # Only the fixed shop origin is ever emitted; untrusted input is a query value.
    return f"{_ORIGIN}/en/domain/suggest?{urlencode({'search': domain_ascii})}"


def _number(value: Any) -> float | None:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        try:
            number = float(value)
            return number if math.isfinite(number) else None
        except (OverflowError, ValueError):
            return None
    return None


def _safe(value: Any, depth: int = 0) -> Any:
    """Discard non-JSON scalars and bound nested provider metadata."""
    if depth > 4:
        return None
    if value is None or isinstance(value, (str, bool)):
        return value
    if isinstance(value, (int, float)):
        try:
            return value if math.isfinite(value) else None
        except (OverflowError, ValueError):
            return None
    if isinstance(value, list):
        return [_safe(item, depth + 1) for item in value[:40]]
    if isinstance(value, dict):
        return {key: _safe(item, depth + 1) for key, item in list(value.items())[:40] if isinstance(key, str)}
    return None


def _integer(value: Any) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def _flag(value: Any) -> bool | None:
    return bool(value) if isinstance(value, (bool, int)) else None


def _prices(result: DomainResult, value: Any) -> None:
    if not isinstance(value, dict) or not value:
        result.pricing_status = "missing"
        return
    quoted_currency = value.get("currency")
    if not isinstance(quoted_currency, str):
        result.pricing_status = "missing"
        result.pricing_error = "currency_missing"
        return
    if quoted_currency.upper() != result.currency:
        result.pricing_status = "missing"
        result.pricing_error = "currency_mismatch"
        return
    result.grid = value.get("grid") if isinstance(value.get("grid"), str) else None
    result.taxes = [_safe(item) for item in value.get("taxes", []) if isinstance(item, dict)] if isinstance(value.get("taxes"), list) else []
    products = value.get("products")
    if not isinstance(products, list):
        result.pricing_status = "missing"
        return
    for item in products:
        if not isinstance(item, dict) or item.get("process") not in ("create", "renew"):
            continue
        tiers = []
        raw_tiers = item.get("prices")
        for tier in raw_tiers if isinstance(raw_tiers, list) else []:
            if not isinstance(tier, dict):
                continue
            tiers.append(DomainPriceTier(
                duration_unit=tier.get("duration_unit") if isinstance(tier.get("duration_unit"), str) else None,
                min_duration=_integer(tier.get("min_duration")),
                max_duration=_integer(tier.get("max_duration")),
                price_before_taxes=_number(tier.get("price_before_taxes")),
                price_after_taxes=_number(tier.get("price_after_taxes")),
                price=_number(tier.get("price")),
                discount=_flag(tier.get("discount")),
                normal_price_before_taxes=_number(tier.get("normal_price_before_taxes")),
                normal_price_after_taxes=_number(tier.get("normal_price_after_taxes")),
                normal_price=_number(tier.get("normal_price")),
                type=tier.get("type") if isinstance(tier.get("type"), str) else None,
                options=_safe(tier.get("options")) if isinstance(tier.get("options"), dict) else {},
                features=_safe(tier.get("features")) if isinstance(tier.get("features"), list) else [],
            ))
        product = DomainPriceProduct(
            process=item["process"], name=item.get("name") if isinstance(item.get("name"), str) else None,
            status=item.get("status") if isinstance(item.get("status"), str) else None,
            tiers=tiers,
            taxes=[_safe(tax) for tax in item.get("taxes", []) if isinstance(tax, dict)] if isinstance(item.get("taxes"), list) else [],
            phases=[_safe(phase) for phase in item.get("phases", []) if isinstance(phase, dict)] if isinstance(item.get("phases"), list) else [],
        )
        (result.registration if product.process == "create" else result.renewal).append(product)
    result.pricing_status = "priced" if any(
        tier.price_before_taxes is not None or tier.price_after_taxes is not None
        for product in result.registration + result.renewal for tier in product.tiers
    ) else "missing"


def _result(name: str, currency: str, country: str, checked_at: str) -> DomainResult:
    ascii_name, unicode_name = _fqdn(name)
    return DomainResult(
        domain_ascii=ascii_name, domain_unicode=unicode_name, currency=currency,
        country=country, checked_at=checked_at, url=_url(ascii_name),
    )


class GandiClient:
    """Async shop client. Pass the application's SecretsManager for Vault fallback."""

    def __init__(self, secrets_manager: Any = None, *, client_factory: Callable[..., httpx.AsyncClient] | None = None):
        _install_log_redaction()
        self._secrets_manager = secrets_manager
        self._client_factory = client_factory or (lambda **kwargs: create_http_client("gandi", **kwargs))

    async def _proxy_url(self) -> str | None:
        values: dict[str, str | None] = {}
        for key in ("proxy_username", "proxy_password"):
            value = None
            if self._secrets_manager is not None:
                try:
                    async with asyncio.timeout(2):
                        value = await self._secrets_manager.get_secret(_VAULT_PATH, key)
                except Exception:
                    pass  # Secret exceptions can contain credentials or Vault metadata.
            if not value:
                value = os.environ.get(f"SECRET__WEBSHARE__{key.upper()}")
            values[key] = value if isinstance(value, str) and value and value != "IMPORTED_TO_VAULT" else None
        if not all(values.values()):
            return None
        return (f"http://{quote(values['proxy_username'] + '-rotate', safe='')}:"
                f"{quote(values['proxy_password'], safe='')}@p.webshare.io:80")

    def _client(self, proxy: str | None) -> httpx.AsyncClient:
        return self._client_factory(proxy=proxy, trust_env=False, follow_redirects=False,
                                    timeout=httpx.Timeout(10, connect=7))

    async def _read_json(self, client: httpx.AsyncClient, params: dict[str, Any]) -> dict[str, Any]:
        try:
            async with asyncio.timeout(18):
                async with client.stream("GET", f"{_API}/lookup", params=params,
                                         headers={**_HEADERS, "Accept": "application/json"}) as response:
                    if response.status_code == 429:
                        raise _ProviderFailure("rate_limited", retry_after=response.headers.get("Retry-After"))
                    if response.status_code == 403 or response.status_code >= 500:
                        raise _ProviderFailure("provider_unavailable", fallback=True)
                    if response.status_code != 200:
                        raise _ProviderFailure("provider_rejected")
                    body = bytearray()
                    async for chunk in response.aiter_bytes():
                        body.extend(chunk)
                        if len(body) > _MAX_BODY_BYTES:
                            raise _ProviderFailure("malformed_response", fallback=True)
                    value = json.loads(body)
                    if not isinstance(value, dict) or not isinstance(value.get("fqdn"), str) or not isinstance(value.get("availability"), str):
                        raise _ProviderFailure("malformed_response", fallback=True)
                    return value
        except (httpx.TimeoutException, httpx.NetworkError, TimeoutError):
            raise _ProviderFailure("network_timeout", fallback=True) from None
        except (json.JSONDecodeError, UnicodeDecodeError):
            raise _ProviderFailure("malformed_response", fallback=True) from None

    async def lookup(self, domain: str, *, currency: str = "EUR", country: str = "DE", lang: str = "en") -> DomainResult:
        currency = _currency(currency)
        country = _locale(country, length=2)
        _locale(lang, length=2)
        ascii_name, unicode_name = _fqdn(domain)
        checked_at = checked_now()
        result = _result(ascii_name, currency, country, checked_at)
        params = {"search": unicode_name, "currency": currency, "country": country, "grid": "A"}
        direct_failure: _ProviderFailure | None = None
        for attempt in range(2):
            proxy = await self._proxy_url() if attempt else None
            if attempt and proxy is None:
                break
            try:
                with _request_log_context("lookup"):
                    async with self._client(proxy) as client:
                        body = await self._read_json(client, params)
                body_ascii, _ = _fqdn(body["fqdn"])
                if body_ascii != ascii_name:
                    raise _ProviderFailure("malformed_response", fallback=True)
                result.availability = body["availability"] if body["availability"] in ("available", "unavailable") else "unknown"
                result.provider_status = body["availability"]
                result.premium = _flag(body.get("premium"))
                _prices(result, body.get("prices"))
                if result.availability == "unknown":
                    result.error = "provider_status_error"
                return result
            except _ProviderFailure as exc:
                if attempt == 0 and exc.fallback:
                    direct_failure = exc
                    continue
                result.error = exc.code
                result.retry_after = exc.retry_after
                return result
            except (httpx.HTTPError, ValueError):
                if attempt == 0:
                    direct_failure = _ProviderFailure("malformed_response", fallback=True)
                    continue
                result.error = "malformed_response"
                return result
            except Exception:
                # Cache, Vault, or transport failures may embed request URLs or
                # proxy credentials in their messages. Expose a fixed code only.
                result.error = "provider_error"
                return result
        result.error = direct_failure.code if direct_failure else "proxy_unavailable"
        result.retry_after = direct_failure.retry_after if direct_failure else None
        return result

    async def _search_page(self, client: httpx.AsyncClient, params: dict[str, Any],
                           currency: str, country: str, checked_at: str, tld: str | None) -> _Page:
        page = _Page()
        candidates: list[str] = []
        suggestions: dict[str, dict[str, Any]] = {}
        das: dict[str, tuple[str, bool | None, bool | None]] = {}
        billing: dict[str, tuple[str, Any]] = {}
        completed = False
        saw_suggestions = False
        event_name = "message"
        data_lines: list[str] = []
        events = 0
        bytes_read = 0

        def key(value: Any) -> str | None:
            try:
                return _fqdn(value)[0]
            except ValueError:
                return None

        def event() -> None:
            nonlocal event_name, data_lines, events, completed, saw_suggestions
            if not data_lines and event_name == "message":
                return
            events += 1
            if events > _MAX_EVENTS:
                raise _ProviderFailure("incomplete_stream", fallback=True)
            try:
                data = json.loads("\n".join(data_lines)) if data_lines else None
            except json.JSONDecodeError:
                raise _ProviderFailure("malformed_stream", fallback=True) from None
            if event_name == "suggestions":
                saw_suggestions = True
                if not isinstance(data, list):
                    raise _ProviderFailure("malformed_stream", fallback=True)
                for item in data:
                    if not isinstance(item, dict):
                        continue
                    fqdn = key(item.get("fqdn"))
                    if fqdn and fqdn not in suggestions and (not tld or fqdn.endswith("." + tld)):
                        candidates.append(fqdn)
                        suggestions[fqdn] = item
            elif event_name in ("das", "das_failed") and isinstance(data, dict):
                fqdn = key(data.get("fqdn"))
                if fqdn:
                    status = data.get("availability")
                    das[fqdn] = (status if isinstance(status, str) else "error", _flag(data.get("premium")), _flag(data.get("reserved")))
            elif event_name in ("billing", "billing_failed") and isinstance(data, dict):
                fqdn = key(data.get("fqdn"))
                if fqdn:
                    billing[fqdn] = (event_name, data.get("prices"))
            elif event_name == "pagination" and isinstance(data, dict):
                page.next_page = bool(data.get("next"))
            elif event_name == "done":
                completed = True
            event_name, data_lines = "message", []

        try:
            async with asyncio.timeout(9):
                async with client.stream("GET", f"{_API}/suggest", params=params,
                                         headers={**_HEADERS, "Accept": "text/event-stream"}) as response:
                    if response.status_code == 429:
                        raise _ProviderFailure("rate_limited", retry_after=response.headers.get("Retry-After"))
                    if response.status_code == 403 or response.status_code >= 500:
                        raise _ProviderFailure("provider_unavailable", fallback=True)
                    if response.status_code != 200:
                        raise _ProviderFailure("provider_rejected")
                    if "text/event-stream" not in response.headers.get("content-type", ""):
                        raise _ProviderFailure("malformed_stream", fallback=True)
                    buffer = bytearray()
                    async for chunk in response.aiter_bytes():
                        bytes_read += len(chunk)
                        if bytes_read > _MAX_BODY_BYTES:
                            raise _ProviderFailure("incomplete_stream", fallback=True)
                        buffer.extend(chunk)
                        while b"\n" in buffer:
                            raw, _, rest = buffer.partition(b"\n")
                            buffer = bytearray(rest)
                            line = raw.rstrip(b"\r").decode("utf-8")
                            if not line:
                                event()
                            elif line.startswith("event:"):
                                event_name = line[6:].strip()
                            elif line.startswith("data:"):
                                data_lines.append(line[5:].strip())
                            if completed:
                                break
                        if completed:
                            break
                    if not completed or not saw_suggestions:
                        raise _ProviderFailure("incomplete_stream", fallback=True)
        except _ProviderFailure as exc:
            page.failure = exc
        except (httpx.TimeoutException, httpx.NetworkError, TimeoutError):
            page.failure = _ProviderFailure("network_timeout", fallback=True)
        except UnicodeDecodeError:
            page.failure = _ProviderFailure("malformed_stream", fallback=True)
        except Exception:
            page.failure = _ProviderFailure("provider_error")

        for fqdn in candidates:
            result = _result(fqdn, currency, country, checked_at)
            item = suggestions[fqdn]
            result.tld = item.get("tld") if isinstance(item.get("tld"), str) else None
            result.corporate = _flag(item.get("corporate"))
            result.allow_lang = _flag(item.get("allow_lang"))
            result.phase = item.get("phase") if isinstance(item.get("phase"), str) else None
            result.restriction = item.get("restriction") if isinstance(item.get("restriction"), str) else None
            result.categories = [category for category in item.get("categories", []) if isinstance(category, str)] if isinstance(item.get("categories"), list) else []
            if fqdn in das:
                status, result.premium, result.reserved = das[fqdn]
                result.provider_status = status
                result.availability = status if status in ("available", "unavailable") else "unknown"
                if status not in ("available", "unavailable"):
                    result.error = "provider_status_error"
            else:
                result.error = "availability_missing"
            if fqdn in billing:
                kind, prices = billing[fqdn]
                _prices(result, prices)
                if kind == "billing_failed":
                    result.pricing_status = "missing"
            else:
                result.pricing_status = "missing"
            page.results.append(result)
        if page.failure is None and any(result.error == "availability_missing" for result in page.results):
            page.failure = _ProviderFailure("incomplete_stream", fallback=True)
        return page

    async def search(self, query: str, *, max_results: int = 10, currency: str = "EUR",
                     country: str = "DE", lang: str = "en", tld: str | None = None) -> DomainSearchResult:
        if not isinstance(query, str) or not query.strip() or len(query) > 100:
            raise ValueError("Invalid search query")
        if not isinstance(max_results, int) or isinstance(max_results, bool) or not 1 <= max_results <= MAX_RESULTS:
            raise ValueError("max_results must be between 1 and 40")
        currency = _currency(currency)
        country = _locale(country, length=2)
        lang = _locale(lang, length=2)
        if tld is not None:
            if not isinstance(tld, str) or "," in tld or "&" in tld:
                raise ValueError("One TLD is required")
            tld = tld.lstrip(".").lower()
            _fqdn("example." + tld)
        output = DomainSearchResult(query=query, currency=currency, country=country)
        direct_failure: _ProviderFailure | None = None
        for attempt in range(2):
            proxy = await self._proxy_url() if attempt else None
            if attempt and proxy is None:
                break
            results: list[DomainResult] = []
            seen: set[str] = set()
            failure: _ProviderFailure | None = None
            try:
                with _request_log_context("suggest"):
                    async with self._client(proxy) as client:
                        for page_number in (1, 2):
                            params: dict[str, Any] = {
                                "search": query, "currency": currency, "country": country, "grid": "A",
                                "lang": lang, "page": page_number, "per_page": min(20, max_results),
                                "source": "shop", "lock_sentence": "false", "phases": "golive",
                            }
                            if tld:
                                params["tlds"] = tld
                            page = await self._search_page(client, params, currency, country, output.checked_at, tld)
                            for item in page.results:
                                if item.domain_ascii not in seen:
                                    seen.add(item.domain_ascii)
                                    results.append(item)
                            if page.failure:
                                failure = page.failure
                                break
                            if len(results) >= max_results or not page.next_page:
                                break
            except httpx.HTTPError:
                failure = _ProviderFailure("network_timeout", fallback=True)
            except Exception:
                failure = _ProviderFailure("provider_error")
            if attempt == 0:
                output.results = results[:max_results]
                direct_failure = failure
                if failure is None or not failure.fallback:
                    output.partial = failure is not None
                    output.error = failure.code if failure else None
                    output.retry_after = failure.retry_after if failure else None
                    return output
                continue
            # Keep usable direct children, then apply more complete proxy data.
            positions = {item.domain_ascii: index for index, item in enumerate(output.results)}
            conflict = False
            for item in results:
                if item.domain_ascii in positions:
                    old = output.results[positions[item.domain_ascii]]
                    if old.availability == "unknown" and item.availability != "unknown":
                        old.availability = item.availability
                        old.provider_status = item.provider_status
                        old.premium = item.premium
                        old.reserved = item.reserved
                        old.error = item.error
                    elif old.availability != "unknown" and item.availability != "unknown" and old.availability != item.availability:
                        old.error = "availability_conflict"
                        conflict = True
                    if (old.availability == "available" and item.availability == "available"
                            and old.pricing_status != "priced" and item.pricing_status == "priced"):
                        old.registration = item.registration
                        old.renewal = item.renewal
                        old.taxes = item.taxes
                        old.grid = item.grid
                        old.pricing_status = "priced"
                        old.pricing_error = None
                elif len(output.results) < max_results:
                    positions[item.domain_ascii] = len(output.results)
                    output.results.append(item)
            output.partial = failure is not None or conflict
            output.error = failure.code if failure else None
            output.retry_after = failure.retry_after if failure else None
            return output
        output.partial = True
        output.error = direct_failure.code if direct_failure else "proxy_unavailable"
        output.retry_after = direct_failure.retry_after if direct_failure else None
        return output
