# Spike (a): decrypted image/video bytes inside the interactive-HTML sandbox

Status: done, observed with a real browser. Product code unchanged.
Script: `docs/plans/slides-core/prototype/sandbox-media-spike.cjs` (raw rows in
`sandbox-media-spike.results.json`). Run:
`CHROMIUM_PATH=<headless_shell> NODE_PATH=<dir with playwright-core> node sandbox-media-spike.cjs`.

## Setup (identical to production)
Outer `<iframe sandbox="allow-scripts">` with srcdoc = script-free wrapper (CSP, `frame-src 'none'`)
containing one `<iframe sandbox="allow-scripts">` whose srcdoc is the author document (CSP meta first,
guard script, author markup). Builder copied verbatim from `interactiveHtmlSandbox.ts`. Page served from
`http://127.0.0.1` (non-opaque parent). Browser: Chromium 145 headless shell (Playwright chromium-1208).
Firefox and WebKit are not installed: **not tested**. Fixtures: 64x64 PNG, 3 s VP8 WebM (0.04 MB), 10 s noisy
VP8 WebM (18.6 MB, about "20 MB"). MP4/H.264 not tested (Chromium headless shell has no proprietary codecs
guarantee; the decrypted container format is an app concern, not a sandbox one).

## Results

| Option | PNG | small video | 18.6 MB video | Latency (18.6 MB, incl. 0.8 s play + seek) | Heap |
|---|---|---|---|---|---|
| a. parent blob: URL in `<img>/<video>` | FAIL | FAIL | FAIL | n/a (probe timed out at 8 s) | n/a |
| b. data: URL inlined in srcdoc | ok | renders, plays, seeks | renders, plays, seeks | 4.3 s | ~78 MB JS heap (srcdoc string is 24.8 MB, held 2-3x) |
| c. postMessage + MessageChannel, frame calls `URL.createObjectURL` | ok | renders, plays, seeks | renders, plays, seeks | 1.5 s | ~40 MB JS heap (one parent copy + transient clone) |

Heap numbers are `performance.memory.usedJSHeapSize` (parent and frame share one renderer isolate; ArrayBuffer
backing stores are partly outside it, so treat as relative only). RSS/per-process memory not measured.

Option a, verbatim errors:
- image: `[console.error] Not allowed to load local resource: blob:http://127.0.0.1:38577/72d6a957-...`
- video: `MEDIA_ELEMENT_ERROR: Media load rejected by URL safety check` (+ same console error)
Cause: blob URL partitioning; a `blob:http://host/...` URL is only loadable by that origin; the frame is
opaque (`null`). Not fixable without `allow-same-origin` (which would void the sandbox). Do not use.

Option b works but needs the whole payload in the author srcdoc string, re-parsed by the wrapper and by the
author frame (two copies), base64 +33%, and every re-render re-sends it. It is acceptable only for small
images (thumbnails, icons). Video should not go this way.

Option c: `URL.createObjectURL` works inside the opaque-origin frame (URL form `blob:null/<uuid>`); CSP
`img-src/media-src blob:` accepts it; video plays and seeks. Console errors: none.

## Structure probes (Chromium)
- The parent CAN post to the inner frame through the script-free wrapper:
  `wrapper.contentWindow.frames[0].postMessage(msg, '*', [port])` works (cross-origin `frames[i]` indexing and
  `postMessage` are always allowed). **The wrapper stays script-free.** Parent saw `length === 1`.
- Parent cannot read anything from it: `frames[0].location.href` throws `SecurityError`.
- targetOrigin: `'null'` throws `SyntaxError: Invalid target origin 'null'`; the opaque origin forces `'*'`.
  So targetOrigin gives no protection; use `event.source` identity + a capability (below), as the diagram
  editor already does (`event.source === frame.contentWindow`, `event.origin === 'null'`, token).
- Revoke: after `revoke`, a new `Image` on the old `blob:null/...` URL gets `naturalWidth 0` (URL dead);
  an already-decoded element stays rendered.
- Spoof: a hostile sibling slide frame can reach other frames via `window.top.frames[i].frames[0]` and post
  an `init` with its own port (observed: it sent 1 message). The victim's bootstrap ignored it
  (`event.source !== window.top`), the victim's `openmatesMedia.load` was `rejected:not initialised`, the
  hostile frame received nothing, and the victim's author-level `message` listener never saw the traffic.

## Recommended mechanism (option c)
1. Trusted bootstrap `<script>` injected by the host right after the guard script and before author markup
   (same position as `GUARD_SCRIPT`; the wrapper is untouched). It registers a capture-phase `window` `message`
   listener FIRST and calls `stopImmediatePropagation()` on channel traffic, so author listeners never see it.
   It exposes a frozen `window.openmatesMedia.load(id) -> Promise<blobUrl>`.
2. Handshake: bootstrap posts `{channel:'openmates-slide-media-v1', type:'hello'}` to `window.top` (`'*'`).
   Parent accepts it only when `event.source === wrapper.contentWindow.frames[0]` and `event.origin === 'null'`,
   once per mount, then posts `{type:'init'}` with a fresh `MessageChannel` port2 transferred. Bootstrap accepts
   `init` only if `event.source === window.top` and no port yet. All further traffic is on the port.
3. The port IS the capability. Add a per-mount random `token` (as the diagram bridge does) inside init and echo it
   on port messages as defence in depth; it is not the primary protection because the author could in theory
   observe the message only if it ran before the bootstrap, which it cannot.
4. Parent holds a per-frame allowlist `id -> {bytes|loader, mime}`; ids not granted get `{type:'error',
   reason:'not granted'}` (observed behaviour: error path implemented). The parent decrypts lazily on `get`.

## Security properties preserved
- Still opaque origin, `sandbox="allow-scripts"` only, same CSP, `connect-src 'none'`, `frame-src 'none'`,
  script-free wrapper, guard script. **No CSP or sandbox attribute change is required.** (No loud change.)
- No network: the only new channel is the MessagePort to the parent, created by the parent.
- No app access: the block gets only `openmatesMedia.load(id)` for ids the parent granted; no keys, no storage,
  no DOM, no other blocks' media (other frames lack the port; spoofed init ignored).
- Residual: a block can read back media it was given (canvas/blob), by design; it cannot exfiltrate it (no
  network). Pixel/timing side channels out of the frame are not new (already possible with `postMessage` to
  top: the block can `window.top.postMessage`, so parent must treat all non-port messages as untrusted and
  ignore them, which the existing sandbox already requires).

## Bridge API sketch (`openmates-slide-media-v1`)
Window messages (parent <-> inner frame, targetOrigin `'*'`):
- frame -> parent: `{channel, type:'hello'}`
- parent -> frame: `{channel, type:'init', token}` + `ports:[port2]`
- parent -> frame: `{channel, type:'revoke'}` (frame revokes every object URL it created)
Port messages:
- frame -> parent: `{type:'get', req:number, id:string}`
- parent -> frame: `{type:'bytes', req, buffer:ArrayBuffer (transferred), mime}` or `{type:'error', req, reason}`
Lifecycle: mount -> hello -> init -> lazy `get`s; slide leaves view/unmount -> `revoke` then drop the iframe and
close port1; parent keeps its own copy (clone before transfer, as the spike does; a transfer detaches the sender's
buffer) or re-decrypts. Re-send `init` is refused after first init, so a new mount (new iframe) is needed per
session. Block-side helper is a thin wrapper (`const url = await openmatesMedia.load('img-1')`); the host can
also pre-rewrite `data-media-id="..."` attributes in the bootstrap to avoid author code for the simple case.

## Not verified
Firefox, WebKit/Safari (blob URL creation in opaque-origin frames and MessagePort transfer likely fine but
untested); MP4/H.264; real encrypted-embed decrypt path; true per-process RSS for 20 MB; mobile/Apple WKWebView;
that a legitimate init is invisible to an author `message` listener (spoofed init was observed invisible, same
code path); behaviour with a streaming (range) source instead of whole-buffer blob.
