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
import re
import socket
import time
import uuid
from urllib.parse import parse_qsl, urlencode, urljoin, urlsplit, urlunsplit

READER_AGENT = "OpenMatesBrowser"
USER_AGENT = "OpenMatesBrowser/1.0 (+https://openmates.org)"


class SessionAuthorization:
    """An unclaimed public snapshot rejects requests until privately configured.

    No bearer secret is baked into the template. Each fresh sandbox receives its
    own configuration through E2B's authenticated filesystem API. Once bound,
    changing that file cannot replace the session's authorization.
    """

    def __init__(self, path=Path("/home/user/.openmates-browse/config.json")):
        self.path = path
        self.token = None

    def permits(self, authorization):
        if self.token is None:
            try:
                token = json.loads(self.path.read_text())["token"]
                if not isinstance(token, str) or not 32 <= len(token) <= 128:
                    return False
            except (OSError, ValueError, KeyError, TypeError):
                return False
            self.token = token
        return hmac.compare_digest(authorization, "Bearer " + self.token)


async def capture_page_snapshot(page):
    """Retry a read destroyed by navigation; never repeat the preceding action."""
    for attempt in range(3):
        handle = None
        try:
            handle = await page.evaluate_handle(SNAPSHOT)
            observation = await handle.evaluate("(s)=>s.observation")
            return handle, observation
        except Exception as exc:
            if handle is not None:
                try:
                    await handle.dispose()
                except Exception:
                    pass
            transient = any(
                marker in str(exc)
                for marker in (
                    "Execution context was destroyed",
                    "Cannot find context with specified id",
                )
            )
            if not transient or attempt == 2:
                raise
            await page.wait_for_load_state("domcontentloaded", timeout=5000)
            await asyncio.sleep(0.15)


async def public_ipv4(hostname: str) -> list[str]:
    """Resolve once; callers connect to these literal, validated addresses."""
    rows = await asyncio.get_running_loop().getaddrinfo(
        hostname, 443, family=socket.AF_INET, type=socket.SOCK_STREAM
    )
    addresses = list(dict.fromkeys(row[4][0] for row in rows))
    if not addresses or any(not ipaddress.ip_address(ip).is_global for ip in addresses):
        raise ValueError("Non-public destination")
    return addresses


async def connect_public_https(reader, writer):
    """Local CONNECT-only transport pins DNS while preserving origin TLS/SNI.

    Chromium and the robots reader both use this transport. It has no direct
    fallback, resolves IPv4 only, and never logs destinations or tunnel bytes.
    """
    upstream_writer = None
    pumps = []
    established = False
    try:
        async with asyncio.timeout(45):
            header = await asyncio.wait_for(reader.readuntil(b"\r\n\r\n"), 5)
            if len(header) > 8192:
                raise ValueError("Oversized proxy request")
            method, authority, version = (
                header.split(b"\r\n", 1)[0].decode("ascii").split()
            )
            target = urlsplit("https://" + authority)
            if (
                method != "CONNECT"
                or version not in ("HTTP/1.0", "HTTP/1.1")
                or not target.hostname
                or target.port != 443
                or target.username is not None
                or target.password is not None
                or target.path
                or target.query
                or target.fragment
            ):
                raise ValueError("Unsupported proxy request")
            addresses = await public_ipv4(target.hostname)
            upstream_reader, upstream_writer = await asyncio.wait_for(
                asyncio.open_connection(addresses[0], 443, family=socket.AF_INET), 5
            )
            writer.write(b"HTTP/1.1 200 Connection Established\r\n\r\n")
            await writer.drain()
            established = True

            async def pump(source, destination):
                while block := await source.read(65536):
                    destination.write(block)
                    await destination.drain()

            pumps = [
                asyncio.create_task(pump(reader, upstream_writer)),
                asyncio.create_task(pump(upstream_reader, writer)),
            ]
            await asyncio.wait(pumps, return_when=asyncio.FIRST_COMPLETED)
    except Exception:
        if not established:
            writer.write(
                b"HTTP/1.1 502 Destination Unavailable\r\nContent-Length: 0\r\nConnection: close\r\n\r\n"
            )
    finally:
        for task in pumps:
            task.cancel()
        if pumps:
            await asyncio.gather(*pumps, return_exceptions=True)
        for stream in (upstream_writer, writer):
            if stream is not None:
                stream.close()
                try:
                    await stream.wait_closed()
                except Exception:
                    pass


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


PROTOCOL = "preboot-v2"
# Controls nearest the viewport fill the window, so a long product grid keeps
# the visible offers instead of the first page-order menu entries. Links are
# collected separately (nearest first) for source verification.
MAX_CONTROLS = 150
MAX_LINKS = 300
MAX_CANDIDATES = 4000
DOCUMENT_TEXT_LIMIT = 120000
MAX_BATCH = 6
SETTLE_CAP_SECONDS = 2.5
SETTLE_QUIET_SECONDS = 0.3
BLOCK_TEXT_LIMIT = 1500
BLOCK_PATTERN = re.compile(
    r"\b(captcha|verify you are human|access denied|subscribe to (continue|read)|paywall)\b",
    re.I,
)
TARGET_KINDS = ("click", "type", "select")
STEP_DENIED = "Target is stale, hidden or covered"

PRIVATE_FIELD_JS = r"""e => {
  const label=(e.ownerDocument||document).querySelector(`label[for="${CSS.escape(e.id||'__none__')}"]`)?.innerText || e.closest('label')?.innerText || '';
  return /password|passcode|otp|mfa|2fa|verification.?code|security.?code|authentication.?code|one.?time.?code|credit.?card|card.?number|cvv|cvc|cc-|api.?key|access.?token|auth.?token|secret|private.?key/i.test(
    [e.type,e.name,e.id,e.autocomplete,e.placeholder,e.getAttribute('aria-label'),label].join(' '));
}"""

SNAPSHOT = (
    r"""() => {
  const SEL='a[href],button,input,select,textarea,[contenteditable=true],[role=button],[role=tab],[role=checkbox],[role=combobox]';
  const win=e=>e.ownerDocument.defaultView;
  const rect=e=>{const r=e.getBoundingClientRect();let x=r.x,y=r.y,w=win(e);
    while(w&&w.frameElement){const f=w.frameElement.getBoundingClientRect();x+=f.x;y+=f.y;w=w.parent;}
    return {x,y,w:r.width,h:r.height};};
  const shown=e=>e.getClientRects().length>0 && win(e).getComputedStyle(e).visibility!=='hidden';
  const inView=e=>{const r=rect(e);return r.w>0&&r.h>0&&r.y+r.h>0&&r.x+r.w>0&&r.y<innerHeight&&r.x<innerWidth;};
  const privateField = __PRIVATE_FIELD_PREDICATE__;
  const deepAt=(doc,x,y)=>{
    for(;;){
      let h=doc.elementFromPoint(x,y); if(!h)return null;
      while(h.shadowRoot){const n=h.shadowRoot.elementFromPoint(x,y); if(!n||n===h)break; h=n;}
      if(h.tagName==='IFRAME'&&h.contentDocument){const f=h.getBoundingClientRect();x-=f.x+h.clientLeft;y-=f.y+h.clientTop;doc=h.contentDocument;continue;}
      return h;
    }};
  const candidates=[],inputs=[];let captcha=false,scanned=0;
  const bigEnough=e=>{const r=e.getBoundingClientRect();return r.width>=100&&r.height>=50;};
  const walk=root=>{
    for(const e of root.querySelectorAll('*')){
      if(++scanned>30000)return;
      if(e.shadowRoot)walk(e.shadowRoot);
      if(e.tagName==='IFRAME'){
        let d=null;try{d=e.contentDocument;}catch(_){}
        if(d&&d.documentElement)walk(d);
        if(/recaptcha\/api2\/(anchor|bframe)|hcaptcha\.com|challenges\.cloudflare\.com|turnstile/i.test(e.src||'')&&!e.closest('.grecaptcha-badge')&&shown(e)&&bigEnough(e))captcha=true;
      } else if(e.matches('.g-recaptcha,.h-captcha,.cf-turnstile')&&shown(e)&&bigEnough(e))captcha=true;
      if(e.matches('input,textarea,[contenteditable=true]'))inputs.push(e);
      if(candidates.length<__MAX_CANDIDATES__&&e.matches(SEL)&&shown(e)&&!e.disabled&&!privateField(e))candidates.push(e);
    }};
  walk(document);
  const away=e=>{const r=rect(e);
    return Math.max(0,-(r.y+r.h),r.y-innerHeight)+Math.max(0,-(r.x+r.w),r.x-innerWidth);};
  const ranked=candidates.map((e,i)=>({e,i,d:away(e)})).sort((a,b)=>a.d-b.d||a.i-b.i);
  const nodes=ranked.slice(0,__MAX_CONTROLS__).sort((a,b)=>a.i-b.i).map(c=>c.e);
  const seenLinks=new Set();
  const buttonLike=e=>e.tagName==='INPUT'&&/^(submit|button|reset|image|checkbox|radio)$/i.test(e.type||'');
  const label=e=>(e.getAttribute('aria-label') || e.ownerDocument.querySelector(`label[for="${CSS.escape(e.id||'__none__')}"]`)?.innerText ||
    e.innerText || (buttonLike(e)&&!/^(checkbox|radio)$/i.test(e.type)?e.value:'') || e.placeholder || e.name || e.tagName).trim().slice(0,180);
  const signature=e=>JSON.stringify([e.tagName,label(e),e.getAttribute('href'),e.value,e.checked,e.getAttribute('aria-expanded'),e.form?.action,e.form?.method]);
  const controls=nodes.map((e,i)=>({id:String(i),role:e.getAttribute('role')||e.tagName.toLowerCase(),label:label(e),
    kind:e.tagName==='SELECT'?'select':buttonLike(e)?'click':e.matches('input,textarea,[contenteditable=true]')?'type':'click',
    value:(e.value||'').slice(0,300),href:e.tagName==='A'?e.href:undefined,in_viewport:inView(e),
    options:e.tagName==='SELECT'?[...e.options].filter(o=>!o.disabled).slice(0,40).map(o=>({value:o.value,label:o.text})):undefined}));
  const tables=[...document.querySelectorAll('table')].slice(0,8).map(t=>[...t.rows].slice(0,100)
    .map(r=>[...r.cells].slice(0,20).map(c=>c.innerText.trim().slice(0,500))));
  const text=(document.body?.innerText||'').slice(0,__TEXT_LIMIT__+1);
  const vis=e=>e&&shown(e)&&inView(e);
  const walker=document.createTreeWalker(document.body,NodeFilter.SHOW_TEXT);
  const passages=[];let count=0;
  for(let n=walker.nextNode();n&&count<6000;n=walker.nextNode()){
    if(!n.textContent.trim()||!vis(n.parentElement))continue;
    const range=document.createRange();range.selectNodeContents(n);const r=range.getBoundingClientRect();
    if(r.bottom>0&&r.top<innerHeight&&r.right>0&&r.left<innerWidth){const v=n.textContent.trim().slice(0,6000-count);passages.push(v);count+=v.length;}
  }
  const dialogs=[...document.querySelectorAll('[role=dialog],dialog[open]')].filter(e=>shown(e)).slice(0,3)
    .map(e=>(e.innerText||'').trim().slice(0,600)).filter(Boolean);
  const observation={url:location.href,title:document.title,text:passages.join('\n'),document_text:text,controls,tables,dialogs,captcha,
    scroll:{y:Math.round(scrollY),height:document.documentElement.scrollHeight,viewport:innerHeight},
    has_private_input:inputs.some(e=>privateField(e)&&shown(e)&&inView(e)),
    links:ranked.filter(c=>c.e.tagName==='A'&&c.e.href&&!seenLinks.has(c.e.href)&&seenLinks.add(c.e.href))
      .slice(0,__MAX_LINKS__).map(c=>({text:label(c.e),url:c.e.href})),width:innerWidth,height:innerHeight};
  return {nodes,signatures:nodes.map(signature),signature,rect,deepAt,observation};
}""".replace("__PRIVATE_FIELD_PREDICATE__", PRIVATE_FIELD_JS)
    .replace("__MAX_CONTROLS__", str(MAX_CONTROLS))
    .replace("__MAX_LINKS__", str(MAX_LINKS))
    .replace("__MAX_CANDIDATES__", str(MAX_CANDIDATES))
    .replace("__TEXT_LIMIT__", str(DOCUMENT_TEXT_LIMIT))
)

# Freshness check against the real element; scrolls it into view before measuring.
PREPARE_JS = r"""(s,i)=>{
  const e=s.nodes[i];
  if(!e?.isConnected||e.disabled||s.signature(e)!==s.signatures[i])return null;
  e.scrollIntoView({block:'center',inline:'center'});
  const r=s.rect(e),x=r.x+r.w/2,y=r.y+r.h/2;
  if(!r.w||!r.h||x<0||y<0||x>=innerWidth||y>=innerHeight)return null;
  let n=s.deepAt(document,x,y);
  while(n){if(n===e)return {x,y,frame:e.ownerDocument!==document};
    n=n.nodeType===9?n.defaultView?.frameElement:(n.parentNode||n.host);}
  return null;}"""

MUTATION_JS = r"""()=>{
  if(!window.__omMutation){window.__omMutation=Date.now();
    new MutationObserver(()=>{window.__omMutation=Date.now();}).observe(document,{subtree:true,childList:true,attributes:true,characterData:true});}
  return Date.now()-window.__omMutation;}"""


def truncate_document_text(text: str) -> tuple[str, bool]:
    """Long pages are truncated and flagged instead of rejected."""
    if len(text) > DOCUMENT_TEXT_LIMIT:
        return text[:DOCUMENT_TEXT_LIMIT], True
    return text, False


def block_reason(access_failure, title: str, text: str, captcha_present: bool):
    """Structural block detection: status, short gate pages, or a CAPTCHA widget."""
    if access_failure:
        return access_failure
    short_gate = len(text) < BLOCK_TEXT_LIMIT and (
        BLOCK_PATTERN.search(text) or BLOCK_PATTERN.search(title or "")
    )
    if short_gate or captcha_present:
        return "The page requires human verification or restricted access."
    return None


def robots_applies(resource_type: str) -> bool:
    """Crawler exclusions govern document navigations (main frame and subframes)."""
    return resource_type == "document"


def batch_stops(url_before, url_after, navigations_before, navigations_after) -> bool:
    """A batch ends after any action that changed the URL or started a navigation."""
    return url_after != url_before or navigations_after != navigations_before


def settle_ready(in_flight: int, network_quiet: float, mutation_quiet: float) -> bool:
    return (
        in_flight <= 0
        and network_quiet >= SETTLE_QUIET_SECONDS
        and mutation_quiet >= SETTLE_QUIET_SECONDS
    )


def validate_actions(actions) -> list[dict]:
    """Fixed vocabulary only; targets are observation control ids."""
    if not isinstance(actions, list) or not 1 <= len(actions) <= MAX_BATCH:
        raise ValueError("Invalid action batch")
    checked = []
    for raw in actions:
        if not isinstance(raw, dict):
            raise ValueError("Invalid action")
        kind = raw.get("kind")
        action = {"kind": kind}
        if kind in TARGET_KINDS:
            target = raw.get("target")
            if isinstance(target, bool) or not isinstance(target, (str, int)):
                raise ValueError("Invalid target")
            action["target"] = str(int(target))
            if kind == "type":
                text = raw.get("text")
                if not isinstance(text, str) or len(text) > 2000:
                    raise ValueError("Invalid field value")
                action.update(text=text, submit=raw.get("submit") is True)
            elif kind == "select":
                value = raw.get("value")
                if not isinstance(value, str) or len(value) > 300:
                    raise ValueError("Invalid field value")
                action["value"] = value
        elif kind == "scroll":
            action["delta"] = max(-800, min(800, int(raw.get("delta", 500))))
        elif kind in ("wait", "back"):
            pass
        elif kind == "goto":
            if len(actions) != 1 or not isinstance(raw.get("url"), str):
                raise ValueError("goto must be the only action in a batch")
            action["url"] = raw["url"]
        else:
            raise ValueError("Unsupported action")
        checked.append(action)
    return checked


def finalize_observation(observation: dict, access_failure) -> dict:
    """Redact URLs, truncate text, blank private pages and mark blocked pages."""
    observation["url"] = observation_url(observation["url"])
    for link in observation["links"]:
        link["url"] = observation_url(link["url"])
    for item in observation["controls"]:
        if item.get("href"):
            item["href"] = observation_url(item["href"])
    raw_text = observation.get("document_text", "")
    observation["document_text"], observation["document_text_truncated"] = (
        truncate_document_text(raw_text)
    )
    captcha = observation.pop("captcha", False)
    if observation["has_private_input"]:
        observation.update(
            text="",
            document_text="",
            document_text_truncated=False,
            title="Private input",
            controls=[],
            tables=[],
            links=[],
            dialogs=[],
        )
        return observation
    reason = block_reason(access_failure, observation["title"], raw_text, captcha)
    if reason:
        observation.update(blocked_reason=reason, controls=[])
        if access_failure:
            observation.update(text="", tables=[], links=[])
    return observation


class BrowseRuntime:
    """Browser RPC state machine; Playwright objects are injected for testing."""

    def __init__(self, page, context, crawler_allowed, browser_error=RuntimeError):
        self.page = page
        self.context = context
        self.crawler_allowed = crawler_allowed
        self.browser_error = browser_error
        self.snapshot = None
        self.snapshot_url = None
        self.observation_id = None
        self.control = "ai"
        self.sign_in_origins = set()
        self.access_failure = None
        self.in_flight = 0
        self.last_network = time.monotonic()
        self.navigations = 0

    # Browser events -----------------------------------------------------
    def _main_navigation(self, request) -> bool:
        return request.is_navigation_request() and request.frame is self.page.main_frame

    def on_request(self, request):
        self.in_flight += 1
        self.last_network = time.monotonic()
        if self._main_navigation(request):
            self.navigations += 1

    def on_request_done(self, request):
        self.in_flight = max(0, self.in_flight - 1)
        self.last_network = time.monotonic()

    def on_response(self, response):
        if self._main_navigation(response.request) and response.status in (
            401,
            403,
            429,
        ):
            self.access_failure = "The site denied access; no bypass was attempted."

    def on_frame_navigated(self, frame):
        if frame is self.page.main_frame:
            self.navigations += 1

    async def guard(self, route):
        """Every request uses the pinned proxy; robots applies to documents only."""
        request = route.request
        if robots_applies(request.resource_type):
            try:
                if not await self.crawler_allowed(request.url):
                    raise ValueError("Crawler access denied")
            except Exception:  # any policy failure must abort the request
                if self._main_navigation(request):
                    self.access_failure = "The destination is unavailable under the browser access policy."
                await route.abort("blockedbyclient")
                return
        await route.continue_()

    # Page helpers ---------------------------------------------------------
    async def screenshot(self, private: bool = False) -> str:
        if private:
            return base64.b64encode(
                await self.page.screenshot(type="jpeg", quality=60)
            ).decode()
        # No saved or model-facing image of a page currently requesting secrets.
        private_fields = await self.page.locator(
            "input,textarea,[contenteditable=true]"
        ).evaluate_all(
            "es=>es.some(e=>(" + PRIVATE_FIELD_JS + ")(e) && e.getClientRects().length)"
        )
        masks = [self.page.locator("body")] if private_fields else []
        return base64.b64encode(
            await self.page.screenshot(type="jpeg", quality=60, mask=masks)
        ).decode()

    async def check_pristine(self):
        state = await asyncio.wait_for(self.context.storage_state(indexed_db=True), 2)
        if self.page.url != "about:blank" or state["cookies"] or state["origins"]:
            raise ValueError("The browser template is not pristine")

    async def navigate_to(self, url):
        if not await self.crawler_allowed(url):
            raise ValueError("Crawler access denied")
        self.access_failure = None
        try:
            await self.page.goto(url, wait_until="domcontentloaded", timeout=20000)
        except self.browser_error:
            if not self.access_failure:
                raise

    async def settle(self):
        """Bounded wait: no requests or DOM mutations for 300 ms, max 2.5 s."""
        deadline = time.monotonic() + SETTLE_CAP_SECONDS
        try:
            await self.page.wait_for_load_state(
                "domcontentloaded", timeout=int(SETTLE_CAP_SECONDS * 1000)
            )
        except self.browser_error:
            pass
        while True:
            try:
                mutation_quiet = await self.page.evaluate(MUTATION_JS) / 1000
            except self.browser_error:
                mutation_quiet = 0.0  # navigation destroyed the context
            now = time.monotonic()
            if settle_ready(self.in_flight, now - self.last_network, mutation_quiet):
                return
            if now >= deadline:
                return
            await asyncio.sleep(0.1)

    async def observe_page(self, with_screenshot: bool) -> dict:
        if self.snapshot:
            snapshot, self.snapshot = self.snapshot, None
            await snapshot.dispose()
        self.snapshot, observation = await capture_page_snapshot(self.page)
        self.snapshot_url = observation["url"]
        observation = finalize_observation(observation, self.access_failure)
        self.observation_id = uuid.uuid4().hex
        observation["observation_id"] = self.observation_id
        if with_screenshot:
            observation["screenshot"] = await self.screenshot()
        return observation

    async def prepare(self, index: int):
        return await self.snapshot.evaluate(PREPARE_JS, index)

    async def element(self, index: int):
        handle = await self.snapshot.evaluate_handle("(s,i)=>s.nodes[i]", index)
        return handle.as_element()

    async def perform(self, action: dict, point):
        kind = action["kind"]
        if kind == "click":
            if point["frame"]:  # frame-relative handle API; page coordinates are wrong
                await (await self.element(int(action["target"]))).click(timeout=2000)
            else:
                await self.page.mouse.click(point["x"], point["y"])
        elif kind == "type":
            await (await self.element(int(action["target"]))).fill(
                action["text"], timeout=3000
            )
            if action["submit"]:
                await self.page.keyboard.press("Enter")
                await asyncio.sleep(0.3)
        elif kind == "select":
            await (await self.element(int(action["target"]))).select_option(
                action["value"], timeout=3000
            )
        elif kind == "scroll":
            await self.page.mouse.wheel(0, action["delta"])
        elif kind == "wait":
            await asyncio.sleep(0.5)
        elif kind == "back":
            await self.page.go_back(wait_until="domcontentloaded", timeout=10000)
        elif kind == "goto":
            await self.navigate_to(action["url"])

    async def execute(self, action: dict):
        """Run one action; returns (result, stop_batch)."""
        result = {"kind": action["kind"]}
        point = None
        if "target" in action:
            result["target"] = action["target"]
            try:
                point = await self.prepare(int(action["target"]))
            except self.browser_error:
                point = None
            if point is None:
                return {**result, "outcome": "rejected", "detail": STEP_DENIED}, True
        elif action["kind"] == "goto":
            try:
                allowed = await self.crawler_allowed(action["url"])
            except (ValueError, OSError):
                allowed = False
            if not allowed:
                return {
                    **result,
                    "outcome": "rejected",
                    "detail": "Crawler access denied",
                }, True
        url_before, navigations_before = self.page.url, self.navigations
        try:
            await self.perform(action, point)
            await asyncio.sleep(0.1)
        except Exception:  # input may have been sent; never retry, report uncertain
            return {
                **result,
                "outcome": "uncertain",
                "detail": "The action may or may not have completed",
            }, True
        result["outcome"] = "executed"
        return result, batch_stops(
            url_before, self.page.url, navigations_before, self.navigations
        )

    # Operations -------------------------------------------------------------
    async def start(self, body):
        timings = {}
        mark = time.monotonic()

        def lap(name):
            nonlocal mark
            now = time.monotonic()
            timings[name] = round(now - mark, 3)
            mark = now

        await asyncio.wait_for(self.page.title(), 2)
        lap("ready")
        if body.get("require_pristine"):
            await self.check_pristine()
        lap("pristine")
        self.control = "ai"
        self.observation_id = None
        await self.navigate_to(body.get("url", ""))
        lap("navigate")
        await self.settle()
        lap("settle")
        observation = await self.observe_page(True)
        lap("observe")
        return {
            "control": "ai",
            "runtime_protocol": PROTOCOL,
            **({"pristine": True} if body.get("require_pristine") else {}),
            "observation": observation,
            "timings": timings,
        }

    async def step(self, body):
        if (
            self.control != "ai"
            or not self.observation_id
            or body.get("observation_id") != self.observation_id
        ):
            raise ValueError("Stale or unauthorized action")
        actions = validate_actions(body.get("actions"))
        self.observation_id = None  # Consume before input; replay cannot repeat it.
        if self.snapshot_url != self.page.url:
            raise ValueError("The page changed after observation")
        self.access_failure = None
        started = time.monotonic()
        results, stopped = [], False
        for action in actions:
            if stopped:
                skipped = {"kind": action["kind"], "outcome": "skipped"}
                if "target" in action:
                    skipped["target"] = action["target"]
                results.append(skipped)
                continue
            result, stopped = await self.execute(action)
            results.append(result)
        acted = time.monotonic()
        await self.settle()
        settled = time.monotonic()
        observation = await self.observe_page(body.get("screenshot") is True)
        return {
            "results": results,
            "observation": observation,
            "timings": {
                "act": round(acted - started, 3),
                "settle": round(settled - acted, 3),
                "observe": round(time.monotonic() - settled, 3),
            },
        }

    async def manual(self, body):
        if self.control != "user":
            raise ValueError("Manual control is not active")
        page = self.page
        kind = body.get("kind")
        private_fields = await page.locator(
            "input,textarea,[contenteditable=true]"
        ).evaluate_all(
            "es=>es.some(e=>(" + PRIVATE_FIELD_JS + ")(e) && e.getClientRects().length)"
        )
        origin = "https://" + urlsplit(page.url).netloc
        if private_fields and origin not in self.sign_in_origins:
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
            await page.mouse.wheel(0, max(-800, min(800, int(body.get("delta", 500)))))
        else:
            raise ValueError("Unsupported input")
        return {"executed": True}

    async def act(self, body):
        if (
            self.control != "ai"
            or not self.observation_id
            or body.get("observation_id") != self.observation_id
        ):
            raise ValueError("Stale or unauthorized action")
        self.observation_id = None  # Consume before input; replay cannot double-click.
        kind = body.get("kind")
        # Also reject changes to the page URL since observation (including SPA navigation).
        if self.snapshot_url != self.page.url:
            raise ValueError("The page changed after observation")
        if kind == "scroll":
            await self.page.mouse.wheel(
                0, max(-800, min(800, int(body.get("delta", 500))))
            )
            return {"executed": True}
        if kind == "wait":
            await asyncio.sleep(0.5)
            return {"executed": True}
        index = int(body["target"])
        point = await self.prepare(index)
        if not point:
            raise ValueError(STEP_DENIED)
        if kind == "click":
            await self.perform({"kind": "click", "target": str(index)}, point)
        elif kind == "type":
            text = body.get("text")
            if not isinstance(text, str) or len(text) > 2000:
                raise ValueError("Invalid field value")
            await (await self.element(index)).fill(text, timeout=3000)
        elif kind == "select":
            await (await self.element(index)).select_option(body["value"], timeout=3000)
        else:
            raise ValueError("Unsupported action")
        await asyncio.sleep(0.1)
        return {"executed": True}

    async def command(self, body):
        op = body.get("operation")
        if op == "metadata":
            return {
                "url": observation_url(self.page.url),
                "origin": "https://" + urlsplit(self.page.url).netloc,
            }
        if op == "sign_in_consent":
            origin = "https://" + urlsplit(self.page.url).netloc
            if self.control != "user" or body.get("origin") != origin:
                raise ValueError("The sign-in destination changed")
            self.sign_in_origins.add(origin)
            return {"origin": origin}
        if op == "control":
            if body.get("mode") not in ("ai", "user", "stopped"):
                raise ValueError("Invalid control mode")
            if body.get("check_ready"):
                # Prove a live Chromium round trip, not just a restored HTTP
                # listener or a cached Playwright page URL.
                await asyncio.wait_for(self.page.title(), 2)
            if body.get("require_pristine"):
                await self.check_pristine()
            self.control = body["mode"]
            self.observation_id = None
            return {
                "control": self.control,
                "runtime_protocol": PROTOCOL,
                **({"pristine": True} if body.get("require_pristine") else {}),
            }
        if op == "start":
            return await self.start(body)
        if op == "step":
            return await self.step(body)
        if op == "navigate":
            await self.navigate_to(body.get("url", ""))
            return {"url": self.page.url}
        if op == "frame":
            return {
                "image": await self.screenshot(private=self.control == "user"),
                "width": 1280,
                "height": 800,
            }
        if op == "observe":
            if self.control != "ai":
                raise ValueError("AI observations are paused")
            return await self.observe_page(body.get("screenshot", True) is not False)
        if op == "manual":
            return await self.manual(body)
        if op == "act":
            return await self.act(body)
        raise ValueError("Unsupported operation")


async def serve() -> None:
    from playwright.async_api import Error as PlaywrightError, async_playwright
    from protego import Protego
    from http.client import HTTPSConnection

    authorization = SessionAuthorization()
    policy_cache = {}
    policy_lock = asyncio.Lock()

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
        await public_ipv4(p.hostname)
        return p

    # Both clients use the same pinned transport, including policy redirects.
    proxy = await asyncio.start_server(
        connect_public_https, "127.0.0.1", 8877, limit=8192
    )

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
                        target = urlsplit(robots_url)
                        connection = HTTPSConnection("127.0.0.1", 8877, timeout=5)
                        connection.set_tunnel(target.hostname, 443)
                        try:
                            path = target.path or "/"
                            if target.query:
                                path += "?" + target.query
                            connection.request(
                                "GET", path, headers={"User-Agent": USER_AGENT}
                            )
                            response = connection.getresponse()
                            content = response.read(512001)
                            if len(content) > 512000:
                                raise ValueError("Crawler policy exceeds size limit")
                            return (
                                response.status,
                                content.decode("utf-8", errors="replace"),
                                response.getheader("Location"),
                            )
                        finally:
                            connection.close()

                    status, content, location = await asyncio.to_thread(fetch)
                    if status in (301, 302, 303, 307, 308) and location:
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
        proxy={"server": "http://127.0.0.1:8877", "bypass": "<-loopback>"},
        args=[
            "--no-sandbox",
            "--disable-dev-shm-usage",
            "--disable-background-networking",
            "--disable-quic",
            "--proxy-bypass-list=<-loopback>",
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
    page = await context.new_page()
    runtime = BrowseRuntime(page, context, crawler_allowed, PlaywrightError)
    await context.route("**/*", runtime.guard)
    # WebSockets are not needed by the initial supported browser action set.
    if hasattr(context, "route_web_socket"):
        await context.route_web_socket("**/*", lambda ws: ws.close())

    # Popups are never an unguarded second browsing channel.
    async def close_popup(popup):
        await popup.close()

    page.on("popup", close_popup)
    page.on("request", runtime.on_request)
    page.on("requestfinished", runtime.on_request_done)
    page.on("requestfailed", runtime.on_request_done)
    page.on("response", runtime.on_response)
    page.on("framenavigated", runtime.on_frame_navigated)
    lock = asyncio.Lock()

    async def handle(reader, writer):
        try:
            header = await asyncio.wait_for(reader.readuntil(b"\r\n\r\n"), 5)
            if len(header) > 8192:
                raise ValueError("Oversized headers")
            lines = header.decode("ascii").split("\r\n")
            headers = dict(line.split(":", 1) for line in lines[1:] if ":" in line)
            headers = {k.strip().lower(): v.strip() for k, v in headers.items()}
            if not authorization.permits(headers.get("authorization", "")):
                raise ValueError("Unauthorized")
            size = int(headers.get("content-length", "0"))
            if not 0 < size <= 64000:
                raise ValueError("Invalid body")
            body = json.loads(await asyncio.wait_for(reader.readexactly(size), 5))
            async with lock:
                result = await runtime.command(body)
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

    server = await asyncio.start_server(handle, "0.0.0.0", 8765, limit=70000)
    async with server, proxy:
        await server.serve_forever()


if __name__ == "__main__":
    asyncio.run(serve())
