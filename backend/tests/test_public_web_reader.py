"""Adversarial direct-reader coverage without contacting public websites."""
# contract-test-file: infrastructure

import asyncio
import socket
import ssl
from unittest.mock import AsyncMock

import httpx
import pytest

from backend.shared.python_utils import public_web_reader as reader


class Body(httpx.AsyncByteStream):
    def __init__(self, data):
        self.data = data
        self.iterated = False

    async def __aiter__(self):
        self.iterated = True
        for offset in range(0, len(self.data), 32768):
            yield self.data[offset:offset + 32768]


@pytest.fixture
async def origin(monkeypatch):
    reader._ACCESS.clear()
    monkeypatch.setattr(reader, "MIN_REQUEST_INTERVAL", 0.0)
    calls = []
    replies = {}
    configurations = []
    real_client = httpx.AsyncClient

    async def dns(host, port, **kwargs):
        assert port == 443 and kwargs["type"] == socket.SOCK_STREAM
        address = "127.0.0.1" if host == "private.example" else "11.22.33.44"
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (address, port))]

    async def dispatch(request):
        calls.append(request)
        key = (request.headers["host"], request.url.raw_path.decode())
        value = replies.get(key, (404, {"content-type": "text/plain"}, b""))
        status, headers, body = value
        return httpx.Response(status, headers=headers, stream=Body(body))

    def client(**kwargs):
        configurations.append(kwargs)
        assert kwargs["follow_redirects"] is False and kwargs["trust_env"] is False
        assert isinstance(kwargs["verify"], ssl.SSLContext)
        assert kwargs["verify"].check_hostname is True
        assert kwargs["verify"].verify_mode == ssl.CERT_REQUIRED
        return real_client(**kwargs, transport=httpx.MockTransport(dispatch))

    monkeypatch.setattr(asyncio.get_running_loop(), "getaddrinfo", dns)
    monkeypatch.setattr(httpx, "AsyncClient", client)
    replies[("site.example", "/page")] = (200, {"content-type": "text/html"}, b"<main><h1>Public page</h1><p>Readable text.</p></main>")
    return replies, calls, configurations


@pytest.mark.asyncio
async def test_full_markup_metadata_and_tls_pinning_without_proxy_cookies_or_subresources(origin, monkeypatch):
    replies, calls, configurations = origin
    monkeypatch.setenv("HTTPS_PROXY", "http://private.example:8080")
    monkeypatch.setenv("ALL_PROXY", "http://private.example:8080")
    content = ("full content line " * 3000) + "FINALCONTENTMARKER"
    document = f'''<html lang="en"><head><title>Public article</title><meta property="og:site_name" content="Publisher">
    <meta property="og:image" content="/cover.jpg"><link rel="icon" href="/icon.png"></head><body>
    <nav>Navigation</nav><main><h1>Heading</h1><a href="/details">Link</a><pre><code>print("code")</code></pre>
    <p>{content}</p><img src="/photo.jpg" alt="Image description"><script>secretScript()</script></main><footer>Footer</footer></body></html>'''
    replies[("site.example", "/page")] = (200, {"content-type": "text/html"}, document.encode())
    page = await reader.read_public_web_page("https://site.example/page#private-fragment")
    assert page["read_status"] == "usable" and page["http_status"] == 200
    assert "FINALCONTENTMARKER" in page["markdown"] and len(page["markdown"]) > 50_000
    assert "# Heading" in page["markdown"] and '[Link](https://site.example/details)' in page["markdown"]
    assert '```' in page["markdown"] and 'print("code")' in page["markdown"]
    assert "secretScript" not in page["markdown"] and "Navigation" not in page["markdown"]
    assert page["title"] == "Public article" and page["language"] == "en"
    assert page["favicon"] == "https://site.example/icon.png"
    assert page["og_image"] == "https://site.example/cover.jpg"
    assert page["og_sitename"] == "Publisher"
    assert len(calls) == 2 and len(configurations) == 2
    for request in calls:
        assert request.url.host == "11.22.33.44"
        assert request.headers["host"] == "site.example"
        assert request.extensions["sni_hostname"] == "site.example"
        assert request.headers["user-agent"] == reader.USER_AGENT
        assert request.headers["accept-encoding"] == "identity"
        assert not {"cookie", "authorization", "proxy-authorization", "referer"} & set(request.headers)


@pytest.mark.asyncio
@pytest.mark.parametrize("rules,path,allowed", [
    ("User-agent: *\nDisallow: /", "/page", False),
    ("User-agent: *\nDisallow: /\nAllow: /page", "/page", True),
    ("User-agent: *\nDisallow: /private/*\nAllow: /private/public$", "/private/other", False),
    ("User-agent: *\nDisallow: /private/*\nAllow: /private/public$", "/private/public", True),
    ("User-agent: *\nDisallow: /\nUser-agent: OpenMatesReader\nAllow: /page", "/page", True),
    ("User-agent: OtherReader\nAllow: /\nUser-agent: OpenMatesReader\nDisallow: /", "/page", False),
    ("User-agent: *\nDisallow: /private/\nAllow: /private/public\nDisallow: /private/public/blocked", "/private/public/blocked", False),
    ("User-agent: *\nDisallow: /page\nAllow: /page", "/page", True),
    ("User-agent: *\nDisallow: /caf%C3%A9", "/caf%C3%A9", False),
    ("User-agent: *\nDisallow: /page?secret=*", "/page?secret=1", False),
])
async def test_rfc_robots_matching_groups_wildcards_end_anchor_priority_and_encoding(origin, rules, path, allowed):
    replies, calls, _ = origin
    replies[("site.example", "/robots.txt")] = (200, {"content-type": "text/plain"}, rules.encode())
    replies[("site.example", path)] = replies[("site.example", "/page")]
    if allowed:
        assert (await reader.read_public_web_page("https://site.example" + path))["read_status"] == "usable"
        assert len(calls) == 2
    else:
        with pytest.raises(reader.PublicWebReadError) as error:
            await reader.read_public_web_page("https://site.example" + path)
        assert error.value.code == "robots_denied" and len(calls) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [401, 403, 429, 500, 503])
async def test_unavailable_robots_never_fetches_page(origin, status):
    replies, calls, _ = origin
    replies[("site.example", "/robots.txt")] = (status, {}, b"")
    with pytest.raises(reader.PublicWebReadError) as error:
        await reader.read_public_web_page("https://site.example/page")
    assert error.value.code == "robots_unavailable" and error.value.http_status == status
    assert len(calls) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [404, 410])
async def test_absent_robots_allows_public_page(origin, status):
    replies, _, _ = origin
    replies[("site.example", "/robots.txt")] = (status, {"content-encoding": "gzip"}, b"ignored")
    assert (await reader.read_public_web_page("https://site.example/page"))["read_status"] == "usable"


@pytest.mark.asyncio
async def test_redirect_target_requires_own_robots_permission(origin):
    replies, calls, _ = origin
    replies[("site.example", "/page")] = (302, {"location": "https://other.example/private"}, b"")
    replies[("other.example", "/robots.txt")] = (200, {"content-type": "text/plain"}, b"User-agent: *\nDisallow: /private")
    with pytest.raises(reader.PublicWebReadError) as error:
        await reader.read_public_web_page("https://site.example/page")
    assert error.value.code == "robots_denied"
    assert [(call.headers["host"], call.url.path) for call in calls] == [
        ("site.example", "/robots.txt"), ("site.example", "/page"), ("other.example", "/robots.txt"),
    ]


@pytest.mark.asyncio
async def test_private_page_redirect_never_reaches_private_address(origin):
    replies, calls, _ = origin
    replies[("site.example", "/page")] = (302, {"location": "https://private.example/hidden"}, b"")
    with pytest.raises(reader.PublicWebReadError) as error:
        await reader.read_public_web_page("https://site.example/page")
    assert error.value.code == "unsafe_address" and len(calls) == 2


@pytest.mark.asyncio
async def test_same_origin_robots_redirect_is_allowed_but_cross_origin_is_not(origin):
    replies, calls, _ = origin
    replies[("site.example", "/robots.txt")] = (302, {"location": "/policy.txt"}, b"")
    replies[("site.example", "/policy.txt")] = (200, {"content-type": "text/plain"}, b"User-agent: *\nAllow: /")
    assert (await reader.read_public_web_page("https://site.example/page"))["read_status"] == "usable"
    reader._ACCESS.clear()
    calls.clear()
    replies[("site.example", "/robots.txt")] = (302, {"location": "https://other.example/robots.txt"}, b"")
    with pytest.raises(reader.PublicWebReadError) as error:
        await reader.read_public_web_page("https://site.example/page")
    assert error.value.code == "robots_unavailable" and len(calls) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("url", ["http://site.example/", "https://user:pass@site.example/", "https://site.example:444/", "file:///etc/passwd", "https://site.example/\nprivate"])
async def test_rejected_url_never_resolves_or_connects(monkeypatch, url):
    dns = AsyncMock(side_effect=AssertionError("No DNS allowed"))
    monkeypatch.setattr(asyncio.get_running_loop(), "getaddrinfo", dns)
    with pytest.raises(reader.PublicWebReadError) as error:
        await reader.read_public_web_page(url)
    assert error.value.code == "invalid_url"
    dns.assert_not_called()


@pytest.mark.asyncio
async def test_mixed_public_private_dns_answers_are_rejected(monkeypatch):
    answers = [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (ip, 443)) for ip in ["11.22.33.44", "127.0.0.1"]]
    monkeypatch.setattr(asyncio.get_running_loop(), "getaddrinfo", AsyncMock(return_value=answers))
    with pytest.raises(reader.PublicWebReadError) as error:
        await reader._public_ip("mixed.example")
    assert error.value.code == "unsafe_address"


@pytest.mark.asyncio
@pytest.mark.parametrize("headers,body,code", [
    ({"content-encoding": "gzip", "content-type": "text/html"}, b"not decompressed", "unsupported_encoding"),
    ({"content-length": str(reader.MAX_INPUT_BYTES + 1), "content-type": "text/html"}, b"", "too_large"),
    ({"content-type": "text/plain"}, b"x" * (reader.MAX_INPUT_BYTES + 1), "too_large"),
    ({"content-type": "text/plain"}, b"x" * (reader.MAX_PAGE_BYTES + 1), "too_large"),
    ({"content-type": "application/pdf"}, b"data", "unsupported_content_type"),
    ({"content-type": "text/html"}, b"<title>Access denied</title><body>Checking your browser</body>", "blocked"),
    ({"content-type": "text/html"}, b"<body>Subscription required. Subscribe to read this article.</body>", "blocked"),
    ({"content-type": "text/html"}, b"<main></main>", "empty"),
], ids=["compression", "declared-size", "stream-size", "text-size", "unsupported-type", "captcha", "paywall", "empty"])
async def test_encoding_size_content_and_access_fail_visibly_without_partial_result(origin, headers, body, code):
    replies, _, _ = origin
    replies[("site.example", "/page")] = (200, headers, body)
    with pytest.raises(reader.PublicWebReadError) as error:
        await reader.read_public_web_page("https://site.example/page")
    assert error.value.code == code
    assert not hasattr(error.value, "markdown")


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [401, 403, 429, 503])
async def test_page_access_errors_are_not_retried(origin, status):
    replies, calls, _ = origin
    replies[("site.example", "/page")] = (status, {}, b"unread error body")
    with pytest.raises(reader.PublicWebReadError) as error:
        await reader.read_public_web_page("https://site.example/page")
    assert error.value.code == "http_error" and error.value.http_status == status
    assert len(calls) == 2


@pytest.mark.asyncio
async def test_plain_text_full_body_and_non_main_content(origin):
    replies, _, _ = origin
    replies[("site.example", "/page")] = (200, {"content-type": "text/plain; charset=utf-8"}, "Complete multilingual page: café 終わり".encode())
    assert (await reader.read_public_web_page("https://site.example/page"))["markdown"].endswith("終わり")
    replies[("site.example", "/page")] = (200, {"content-type": "text/html"}, b"<body><nav>Navigation</nav><main>Article</main><footer>Footnote</footer></body>")
    page = await reader.read_public_web_page("https://site.example/page", only_main_content=False)
    assert all(word in page["markdown"] for word in ["Navigation", "Article", "Footnote"])


@pytest.mark.asyncio
async def test_robots_delay_and_request_rate_are_applied(origin):
    replies, _, _ = origin
    replies[("site.example", "/robots.txt")] = (200, {"content-type": "text/plain"}, b"User-agent: OpenMatesReader\nCrawl-delay: 0.01\nRequest-rate: 1/1s")
    access = reader._Access()
    await reader._robots(reader._target("https://site.example/page"), access)
    assert access.origins["https://site.example"].interval == 1.0
    assert access.origins["https://site.example"].next_request >= access.origins["https://site.example"].last_request + 1.0


@pytest.mark.asyncio
async def test_total_timeout_includes_robots_waits(origin, monkeypatch):
    async def stalled(*args, **kwargs):
        await asyncio.sleep(10)
    monkeypatch.setattr(reader, "_robots", stalled)
    with pytest.raises(reader.PublicWebReadError) as error:
        await reader.read_public_web_page("https://site.example/page", timeout_ms=1000)
    assert error.value.code == "timeout"


@pytest.mark.asyncio
async def test_dns_rebinding_between_robots_and_page_is_blocked(origin, monkeypatch):
    _, calls, _ = origin
    addresses = iter(["11.22.33.44", "127.0.0.1"])

    async def dns(*args, **kwargs):
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (next(addresses), 443))]

    monkeypatch.setattr(asyncio.get_running_loop(), "getaddrinfo", dns)
    with pytest.raises(reader.PublicWebReadError) as error:
        await reader.read_public_web_page("https://site.example/page")
    assert error.value.code == "unsafe_address" and len(calls) == 1


@pytest.mark.asyncio
async def test_cookie_and_authorization_are_not_carried_across_redirects(origin):
    replies, calls, _ = origin
    replies[("site.example", "/page")] = (302, {"location": "/final", "set-cookie": "private=value"}, b"")
    replies[("site.example", "/final")] = (200, {"content-type": "text/plain"}, b"Public final page")
    page = await reader.read_public_web_page("https://site.example/page")
    assert page["source_url"] == "https://site.example/final"
    assert all("cookie" not in call.headers and "authorization" not in call.headers for call in calls)


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["page", "robots"])
async def test_redirect_loops_stop_at_fixed_budget(origin, kind):
    replies, calls, _ = origin
    path = "/page" if kind == "page" else "/robots.txt"
    replies[("site.example", path)] = (302, {"location": path}, b"")
    with pytest.raises(reader.PublicWebReadError) as error:
        await reader.read_public_web_page("https://site.example/page")
    assert error.value.code == ("redirect_limit" if kind == "page" else "robots_unavailable")
    assert len(calls) == reader.MAX_REDIRECTS + (2 if kind == "page" else 1)


@pytest.mark.asyncio
@pytest.mark.parametrize("body,headers", [
    (b"User-agent: *\n" + b"x" * reader.MAX_ROBOTS_BYTES, {"content-type": "text/plain"}),
    (b"<html>Access denied</html>", {"content-type": "text/html"}),
])
async def test_oversized_or_html_robots_fail_closed(origin, body, headers):
    replies, calls, _ = origin
    replies[("site.example", "/robots.txt")] = (200, headers, body)
    with pytest.raises(reader.PublicWebReadError):
        await reader.read_public_web_page("https://site.example/page")
    assert len(calls) == 1


@pytest.mark.asyncio
async def test_network_failure_during_robots_does_not_fall_back_to_page(origin, monkeypatch):
    calls = []

    async def failed(*args, **kwargs):
        calls.append(1)
        raise httpx.ConnectError("isolated synthetic failure")

    monkeypatch.setattr(reader, "_fetch", failed)
    with pytest.raises(reader.PublicWebReadError) as error:
        await reader.read_public_web_page("https://site.example/page")
    assert error.value.code == "network_error" and len(calls) == 1


@pytest.mark.asyncio
async def test_global_parallel_reads_are_bounded(origin, monkeypatch):
    entered = 0
    maximum = 0
    release = asyncio.Event()

    async def blocked(*args, **kwargs):
        nonlocal entered, maximum
        entered += 1
        maximum = max(maximum, entered)
        await release.wait()
        entered -= 1
        return {"read_status": "usable"}

    monkeypatch.setattr(reader, "_read", blocked)
    tasks = [asyncio.create_task(reader.read_public_web_page(f"https://site.example/{n}")) for n in range(8)]
    await asyncio.sleep(0.02)
    assert entered == maximum == 4
    release.set()
    await asyncio.gather(*tasks)
    assert maximum == 4


@pytest.mark.asyncio
async def test_origin_requests_are_serial_and_spaced(origin, monkeypatch):
    import time
    _, calls, _ = origin
    access = reader._Access()
    entry = reader._origin(access, "https://site.example")
    entry.interval = 0.02
    timestamps = []
    original = reader._public_ip

    async def timestamped(hostname):
        timestamps.append(time.monotonic())
        return await original(hostname)

    monkeypatch.setattr(reader, "_public_ip", timestamped)
    await asyncio.gather(*[reader._fetch(reader._target("https://site.example/robots.txt"), access, max_bytes=100) for _ in range(3)])
    assert len(calls) == 3
    assert all(later - earlier >= 0.018 for earlier, later in zip(timestamps, timestamps[1:]))


@pytest.mark.asyncio
async def test_hidden_html_and_unsafe_link_targets_are_not_extracted(origin):
    replies, _, _ = origin
    replies[("site.example", "/page")] = (200, {"content-type": "text/html"}, b'''<main>Public body
    <div hidden>Hidden gated body</div><span style="display:none">Hidden style</span>
    <a href="javascript:alert(1)">Visible link label</a></main>''')
    text = (await reader.read_public_web_page("https://site.example/page"))["markdown"]
    assert "Public body" in text and "Visible link label" in text
    assert "Hidden" not in text and "javascript:" not in text


@pytest.mark.asyncio
@pytest.mark.parametrize("declaration", [
    {"@type": "NewsArticle", "isAccessibleForFree": False,
     "hasPart": {"@type": "WebPageElement", "isAccessibleForFree": False, "cssSelector": ".paywall"}},
    {"@graph": [{"@type": ["NewsArticle", "WebPage"], "isAccessibleForFree": False}]},
    {"@type": "https://schema.org/Article", "hasPart": [
        {"@type": "WebPageElement", "isAccessibleForFree": False, "cssSelector": ".paywall"}]},
    {"@type": "WebPage", "isAccessibleForFree": "false"},
])
async def test_long_structured_gated_articles_are_blocked_before_jsonld_is_removed(origin, declaration):
    import json
    replies, calls, _ = origin
    document = ('<html><head><title>Publisher article</title><script type="application/ld+json">'
                + json.dumps(declaration) + '</script></head><body><main class="paywall">'
                + "Long subscriber content. " * 500 + "Subscribe to continue.</main></body></html>")
    assert len(document) > 4000
    replies[("site.example", "/page")] = (200, {"content-type": "text/html"}, document.encode())
    with pytest.raises(reader.PublicWebReadError) as error:
        await reader.read_public_web_page("https://site.example/page")
    assert error.value.code == "blocked" and error.value.http_status == 200
    assert len(calls) == 2
    assert not hasattr(error.value, "markdown")


@pytest.mark.asyncio
async def test_article_text_about_paywalls_is_readable_without_nonfree_page_declaration(origin):
    replies, _, _ = origin
    document = b'''<html><head><title>Understanding paywalls</title>
    <script type="application/ld+json">{"@type":"NewsArticle","isAccessibleForFree":true}</script>
    </head><body><main><h1>Understanding paywalls</h1>
    <p>This public article explains paywall designs and discusses isAccessibleForFree:false examples.</p></main></body></html>'''
    replies[("site.example", "/page")] = (200, {"content-type": "text/html"}, document)
    page = await reader.read_public_web_page("https://site.example/page")
    assert page["read_status"] == "usable" and "public article explains" in page["markdown"]


@pytest.mark.asyncio
async def test_robots_html_without_content_type_fails_closed(origin):
    replies, calls, _ = origin
    replies[("site.example", "/robots.txt")] = (200, {}, b"<!doctype html><title>Access denied</title>")
    with pytest.raises(reader.PublicWebReadError) as error:
        await reader.read_public_web_page("https://site.example/page")
    assert error.value.code == "robots_unavailable" and len(calls) == 1


@pytest.mark.asyncio
async def test_cancelled_read_keeps_parser_slots_until_actual_threads_finish(monkeypatch):
    import threading
    access = reader._Access()
    release = threading.Event()
    entered = threading.Event()
    lock = threading.Lock()
    active = 0
    maximum = 0

    def parse(*args):
        nonlocal active, maximum
        with lock:
            active += 1
            maximum = max(maximum, active)
            if active == 2:
                entered.set()
        try:
            release.wait(2)
            return {"markdown": "Complete result"}
        finally:
            with lock:
                active -= 1

    monkeypatch.setattr(reader, "_extract", parse)
    tasks = [asyncio.create_task(reader._parse_page(access, "https://site.example/", httpx.Headers(), b"", True)) for _ in range(4)]
    try:
        assert await asyncio.to_thread(entered.wait, 1)
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        assert access.parsers.locked()
        extra = asyncio.create_task(reader._parse_page(access, "https://site.example/", httpx.Headers(), b"", True))
        await asyncio.sleep(0.02)
        assert maximum == 2 and not extra.done()
        release.set()
        assert (await extra)["markdown"] == "Complete result"
        assert maximum == 2
    finally:
        release.set()
        await asyncio.gather(*tasks, return_exceptions=True)


@pytest.mark.asyncio
async def test_origin_state_capacity_is_bounded_without_resetting_active_rate_windows(monkeypatch):
    monkeypatch.setattr(reader, "MAX_ORIGINS", 2)
    access = reader._Access()
    for host in ["https://one.example", "https://two.example"]:
        entry = reader._origin(access, host)
        entry.last_request = reader.time.monotonic()
        entry.next_request = entry.last_request + 1
    with pytest.raises(reader.PublicWebReadError) as error:
        reader._origin(access, "https://three.example")
    assert error.value.code == "rate_limited" and len(access.origins) == 2
