"""Trusted browser RPC executable. Runs ONLY inside an isolated E2B desktop.

This module is copied as inert source into the sandbox. Playwright code and DOM
extraction are fixed; neither model output nor website content is executed as code.
The control bearer never enters the page, model input, or browser observations.
"""

from __future__ import annotations

import asyncio
import base64
import hmac
import ipaddress
import json
from pathlib import Path
import socket
import uuid
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

READER_AGENT = "OpenMatesBrowser"
USER_AGENT = "OpenMatesBrowser/1.0 (+https://openmates.org)"


def observation_url(value: str) -> str:
    """Credentials in callback URLs are live browser state, never observations."""
    parsed = urlsplit(value)
    public_query_keys = {
        "q",
        "query",
        "search",
        "page",
        "sort",
        "order",
        "lang",
        "locale",
        "limit",
        "offset",
    }
    query = [
        (
            k,
            "[redacted]" if k.lower() not in public_query_keys else v,
        )
        for k, v in parse_qsl(parsed.query, keep_blank_values=True)
    ]
    return urlunsplit((parsed.scheme, parsed.netloc, parsed.path, urlencode(query), ""))


PRIVATE_FIELD_JS = r"""e => {
  const label=document.querySelector(`label[for="${CSS.escape(e.id||'__none__')}"]`)?.innerText || e.closest('label')?.innerText || '';
  return /password|passcode|otp|mfa|2fa|verification.?code|security.?code|authentication.?code|one.?time.?code|credit.?card|card.?number|cvv|cvc|cc-|api.?key|access.?token|auth.?token|secret|private.?key/i.test(
    [e.type,e.name,e.id,e.autocomplete,e.placeholder,e.getAttribute('aria-label'),label].join(' '));
}"""

SNAPSHOT = r"""() => {
  const visible = e => { const r=e.getBoundingClientRect(); return r.width>0 && r.height>0 &&
    r.bottom>0 && r.right>0 && r.top<innerHeight && r.left<innerWidth && getComputedStyle(e).visibility!=='hidden'; };
  const privateField = __PRIVATE_FIELD_PREDICATE__;
  const nodes = [...document.querySelectorAll('a[href],button,input,select,textarea,[contenteditable=true],[role=button],[role=tab],[role=checkbox],[role=combobox]')]
    .filter(e=>visible(e) && !e.disabled && !privateField(e)).slice(0,100);
  const label=e=>(e.getAttribute('aria-label') || document.querySelector(`label[for="${CSS.escape(e.id||'__none__')}"]`)?.innerText ||
    e.innerText || e.placeholder || e.name || e.tagName).trim().slice(0,180);
  const signature=e=>JSON.stringify([e.tagName,label(e),e.getAttribute('href'),e.value,e.checked,e.getAttribute('aria-expanded'),e.form?.action,e.form?.method]);
  const controls=nodes.map((e,i)=>({id:String(i),role:e.getAttribute('role')||e.tagName.toLowerCase(),label:label(e),
    kind:e.tagName==='SELECT'?'select':e.matches('input,textarea,[contenteditable=true]')?'type':'click',
    value:(e.value||'').slice(0,300),href:e.tagName==='A'?e.href:undefined,
    options:e.tagName==='SELECT'?[...e.options].filter(o=>!o.disabled).slice(0,40).map(o=>({value:o.value,label:o.text})):undefined}));
  const tables=[...document.querySelectorAll('table')].slice(0,8).map(t=>[...t.rows].slice(0,100)
    .map(r=>[...r.cells].slice(0,20).map(c=>c.innerText.trim().slice(0,500))));
  const text=document.body?.innerText||'';
  if(text.length>200000)throw new Error('Page exceeds the supported extraction limit');
  const walker=document.createTreeWalker(document.body,NodeFilter.SHOW_TEXT);
  const passages=[];let count=0;
  for(let n=walker.nextNode();n&&count<6000;n=walker.nextNode()){
    if(!n.textContent.trim()||!visible(n.parentElement))continue;
    const range=document.createRange();range.selectNodeContents(n);const r=range.getBoundingClientRect();
    if(r.bottom>0&&r.top<innerHeight&&r.right>0&&r.left<innerWidth){const v=n.textContent.trim().slice(0,6000-count);passages.push(v);count+=v.length;}
  }
  const observation={url:location.href,title:document.title,text:passages.join('\n'),document_text:text,controls,tables,
    has_private_input:[...document.querySelectorAll('input,textarea,[contenteditable=true]')].some(e=>privateField(e)&&visible(e)),
    links:nodes.filter(e=>e.tagName==='A').map(e=>({text:label(e),url:e.href})),width:innerWidth,height:innerHeight};
  return {nodes,signatures:nodes.map(signature),signature,observation};
}""".replace("__PRIVATE_FIELD_PREDICATE__", PRIVATE_FIELD_JS)


async def serve() -> None:
    from playwright.async_api import async_playwright

    config = json.loads(Path("/tmp/openmates-browse/config.json").read_text())
    token = config["token"]
    from protego import Protego
    from urllib.request import build_opener, ProxyHandler, HTTPRedirectHandler, Request
    from urllib.error import HTTPError
    import time
    import re

    policy_cache = {}
    policy_lock = asyncio.Lock()
    access_failure = None

    async def public_target(url):
        p = urlsplit(url)
        if (
            p.scheme != "https"
            or not p.hostname
            or p.username is not None
            or p.password is not None
            or p.port not in (None, 443)
        ):
            raise ValueError("Only public HTTPS destinations are supported")
        addresses = await asyncio.get_running_loop().getaddrinfo(
            p.hostname, 443, type=socket.SOCK_STREAM
        )
        if not addresses or any(
            not ipaddress.ip_address(a[4][0]).is_global for a in addresses
        ):
            raise ValueError("Non-public destination")
        return p

    class NoRedirect(HTTPRedirectHandler):
        def redirect_request(self, *args, **kwargs):
            return None

    async def crawler_allowed(url):
        p = await public_target(url)
        origin = "https://" + p.netloc
        async with policy_lock:
            cached = policy_cache.get(origin)
            if not cached or time.monotonic() - cached[0] > 300:
                robots_url = origin + "/robots.txt"
                policy = None
                for _ in range(6):
                    await public_target(robots_url)

                    def fetch():
                        opener = build_opener(ProxyHandler({}), NoRedirect())
                        try:
                            with opener.open(
                                Request(robots_url, headers={"User-Agent": USER_AGENT}),
                                timeout=5,
                            ) as response:
                                content = response.read(512001)
                                if len(content) > 512000:
                                    raise ValueError(
                                        "Crawler policy exceeds size limit"
                                    )
                                return (
                                    response.status,
                                    content.decode("utf-8", errors="replace"),
                                    None,
                                )
                        except HTTPError as exc:
                            return exc.code, "", exc.headers.get("Location")

                    status, content, location = await asyncio.to_thread(fetch)
                    if status in (301, 302, 303, 307, 308) and location:
                        from urllib.parse import urljoin

                        robots_url = urljoin(robots_url, location)
                        continue
                    if status == 200:
                        policy = Protego.parse(content)
                    elif status not in (404, 410):
                        raise ValueError(
                            "Crawler policy is unavailable or denies access"
                        )
                    break
                else:
                    raise ValueError("Crawler policy redirected too often")
                cached = (time.monotonic(), policy)
                policy_cache[origin] = cached
            return cached[1] is None or cached[1].can_fetch(url, READER_AGENT)

    playwright = await async_playwright().start()
    browser = await playwright.chromium.launch(
        headless=True,
        args=[
            "--no-sandbox",
            "--disable-dev-shm-usage",
            "--disable-background-networking",
            "--disable-features=WebRtcHideLocalIpsWithMdns",
            "--force-webrtc-ip-handling-policy=disable_non_proxied_udp",
        ],
    )
    context = await browser.new_context(
        viewport={"width": 1280, "height": 800},
        service_workers="block",
        accept_downloads=False,
        user_agent=USER_AGENT,
    )

    async def guard(route):
        nonlocal access_failure
        try:
            if not await crawler_allowed(route.request.url):
                raise ValueError("Crawler access denied")
        except Exception:
            if route.request.is_navigation_request():
                access_failure = (
                    "The destination is unavailable under the browser access policy."
                )
            await route.abort("blockedbyclient")
            return
        await route.continue_()

    await context.route("**/*", guard)
    # WebSockets are not needed by the initial supported browser action set.
    if hasattr(context, "route_web_socket"):
        await context.route_web_socket("**/*", lambda ws: ws.close())
    page = await context.new_page()

    # Popups are never an unguarded second browsing channel.
    async def close_popup(popup):
        await popup.close()

    page.on("popup", close_popup)

    def check_response(response):
        nonlocal access_failure
        if response.request.is_navigation_request() and response.status in (
            401,
            403,
            429,
        ):
            access_failure = "The site denied access; no bypass was attempted."

    page.on("response", check_response)
    snapshot = None
    observation_id = None
    control = "ai"
    sign_in_origins = set()
    lock = asyncio.Lock()

    async def screenshot(private: bool = False) -> str:
        if private:
            return base64.b64encode(
                await page.screenshot(type="jpeg", quality=65)
            ).decode()
        # No saved or model-facing image of a page currently requesting secrets.
        private_fields = await page.locator(
            "input,textarea,[contenteditable=true]"
        ).evaluate_all(
            "es=>es.some(e=>(" + PRIVATE_FIELD_JS + ")(e) && e.getClientRects().length)"
        )
        masks = [page.locator("body")] if private_fields else []
        return base64.b64encode(
            await page.screenshot(type="jpeg", quality=65, mask=masks)
        ).decode()

    async def command(body):
        nonlocal snapshot, observation_id, control, access_failure
        op = body.get("operation")
        if op == "metadata":
            return {
                "url": observation_url(page.url),
                "origin": "https://" + urlsplit(page.url).netloc,
            }
        if op == "sign_in_consent":
            origin = "https://" + urlsplit(page.url).netloc
            if control != "user" or body.get("origin") != origin:
                raise ValueError("The sign-in destination changed")
            sign_in_origins.add(origin)
            return {"origin": origin}
        if op == "control":
            if body.get("mode") not in ("ai", "user", "stopped"):
                raise ValueError("Invalid control mode")
            control = body["mode"]
            observation_id = None
            return {"control": control}
        if op == "navigate":
            url = body.get("url", "")
            if not await crawler_allowed(url):
                raise ValueError("Crawler access denied")
            access_failure = None
            try:
                await page.goto(url, wait_until="domcontentloaded", timeout=20000)
            except Exception:
                if not access_failure:
                    raise
            return {"url": page.url}
        if op == "frame":
            return {
                "image": await screenshot(private=control == "user"),
                "width": 1280,
                "height": 800,
            }
        if op == "observe":
            if control != "ai":
                raise ValueError("AI observations are paused")
            if snapshot:
                await snapshot.dispose()
            snapshot = await page.evaluate_handle(SNAPSHOT)
            observation = await snapshot.evaluate("(s)=>s.observation")
            observation["url"] = observation_url(observation["url"])
            for link in observation["links"]:
                link["url"] = observation_url(link["url"])
            for item in observation["controls"]:
                if item.get("href"):
                    item["href"] = observation_url(item["href"])
            if observation["has_private_input"]:
                observation.update(
                    text="",
                    document_text="",
                    title="Private input",
                    controls=[],
                    tables=[],
                    links=[],
                )
            if access_failure:
                observation.update(
                    blocked_reason=access_failure,
                    text="",
                    controls=[],
                    tables=[],
                    links=[],
                )
            elif re.search(
                r"\b(captcha|verify you are human|access denied|subscribe to (continue|read)|paywall)\b",
                observation["text"],
                re.I,
            ):
                observation.update(
                    blocked_reason="The page requires human verification or restricted access.",
                    controls=[],
                )
            observation_id = uuid.uuid4().hex
            observation.update(
                observation_id=observation_id, screenshot=await screenshot()
            )
            return observation
        if op == "manual":
            if control != "user":
                raise ValueError("Manual control is not active")
            kind = body.get("kind")
            private_fields = await page.locator(
                "input,textarea,[contenteditable=true]"
            ).evaluate_all(
                "es=>es.some(e=>("
                + PRIVATE_FIELD_JS
                + ")(e) && e.getClientRects().length)"
            )
            origin = "https://" + urlsplit(page.url).netloc
            if private_fields and origin not in sign_in_origins:
                return {"needs_sign_in_consent": True, "origin": origin}
            if kind == "click":
                x, y = float(body["x"]), float(body["y"])
                if not 0 <= x < 1280 or not 0 <= y < 800:
                    raise ValueError("Invalid coordinates")
                await page.mouse.click(x, y)
            elif kind == "type":
                text = body.get("text")
                if not isinstance(text, str) or len(text) > 2000:
                    raise ValueError("Invalid input")
                await page.keyboard.insert_text(text)
            elif kind == "key" and body.get("key") in (
                "Enter",
                "Tab",
                "Shift+Tab",
                "Backspace",
                "Escape",
                "ArrowDown",
                "ArrowUp",
                "Control+A",
            ):
                await page.keyboard.press(body["key"])
            elif kind == "scroll":
                await page.mouse.wheel(
                    0, max(-800, min(800, int(body.get("delta", 500))))
                )
            else:
                raise ValueError("Unsupported input")
            return {"executed": True}
        if op == "act":
            if (
                control != "ai"
                or not observation_id
                or body.get("observation_id") != observation_id
            ):
                raise ValueError("Stale or unauthorized action")
            observation_id = None  # Consume before input; replay cannot double-click.
            kind = body.get("kind")
            # Also reject changes to the page URL since observation (including SPA navigation).
            if await snapshot.evaluate("(s)=>s.observation.url") != page.url:
                raise ValueError("The page changed after observation")
            if kind == "scroll":
                await page.mouse.wheel(
                    0, max(-800, min(800, int(body.get("delta", 500))))
                )
                return {"executed": True}
            if kind == "wait":
                await asyncio.sleep(0.5)
                return {"executed": True}
            index = int(body["target"])
            point = await snapshot.evaluate(
                r"""(s,i)=>{
              const e=s.nodes[i];if(!e?.isConnected||e.disabled||s.signature(e)!==s.signatures[i])return null;
              const r=e.getBoundingClientRect(),x=r.x+r.width/2,y=r.y+r.height/2;
              if(!r.width||!r.height||x<0||y<0||x>=innerWidth||y>=innerHeight||!e.contains(document.elementFromPoint(x,y)))return null;
              return {x,y};} """,
                index,
            )
            if not point:
                raise ValueError("Target is stale, hidden or covered")
            if kind == "click":
                await page.mouse.click(**point)
            elif kind == "type":
                text = body.get("text")
                if not isinstance(text, str) or len(text) > 2000:
                    raise ValueError("Invalid field value")
                element = await snapshot.evaluate_handle("(s,i)=>s.nodes[i]", index)
                await element.as_element().fill(text, timeout=3000)
            elif kind == "select":
                element = await snapshot.evaluate_handle("(s,i)=>s.nodes[i]", index)
                await element.as_element().select_option(body["value"], timeout=3000)
            else:
                raise ValueError("Unsupported action")
            await asyncio.sleep(0.1)
            return {"executed": True}
        raise ValueError("Unsupported operation")

    async def handle(reader, writer):
        try:
            header = await asyncio.wait_for(reader.readuntil(b"\r\n\r\n"), 5)
            if len(header) > 8192:
                raise ValueError("Oversized headers")
            lines = header.decode("ascii").split("\r\n")
            headers = dict(line.split(":", 1) for line in lines[1:] if ":" in line)
            headers = {k.strip().lower(): v.strip() for k, v in headers.items()}
            if not hmac.compare_digest(
                headers.get("authorization", ""), "Bearer " + token
            ):
                raise ValueError("Unauthorized")
            size = int(headers.get("content-length", "0"))
            if not 0 < size <= 32000:
                raise ValueError("Invalid body")
            body = json.loads(await asyncio.wait_for(reader.readexactly(size), 5))
            async with lock:
                result = await command(body)
            status = "200 OK"
        except Exception:
            status = "409 Conflict"
            result = {
                "error": "Browser operation was rejected; observe before retrying."
            }
        data = json.dumps(result).encode()
        writer.write(
            f"HTTP/1.1 {status}\r\nContent-Type: application/json\r\nCache-Control: no-store\r\nContent-Length: {len(data)}\r\nConnection: close\r\n\r\n".encode()
            + data
        )
        await writer.drain()
        writer.close()
        await writer.wait_closed()

    server = await asyncio.start_server(handle, "0.0.0.0", 8765, limit=40000)
    async with server:
        await server.serve_forever()


if __name__ == "__main__":
    asyncio.run(serve())
