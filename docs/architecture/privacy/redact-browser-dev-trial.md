# Redact browser development trial

Task TASK-6119, session 678f. The user requested a working development integration
before making a production decision. Production activation remains disabled.

The published browser SDK is `@desert-ant-labs/redact` 4.1.0 with LiteRT.js 2.6.0.
Model revision `v0.4.0` is approximately 24.5 MB, plus tokenizer and runtime files.
The pinned SDK also generates about 45 MB of Redact WASM, 11 MB of LiteRT WASM,
and 384 KB of JavaScript before HTTP compression. The complete first-use asset
footprint is therefore around 80 MB, rather than just the advertised model size.
These are uncompressed artifact sizes, not network transfer measurements. The
generated runtime files total 57,623,876 bytes and gzip to 21,537,589 bytes in a
local packaging measurement. Actual dev CDN delivery is verified separately.
The browser performs classification locally. Redact is fallible and does not
establish that an undetected message is free of personal information.

The current license is source-available, rather than an open-source license. It
permits embedding the SDK/model in an application, requires linked attribution
and intact SDK usage reporting, and requires a commercial license above 100,000
monthly active devices per platform and model. Production needs an explicit
decision about these terms, licensing compatibility with OpenMates distribution,
and the corresponding privacy notice. No provider outreach is authorized here.

The SDK's licensing code sends a random installation identifier, application
identifier, platform, model/version and SDK/version to
`https://events.desertant.com/api/v1/license`; activation sends the resulting
license token to `/activate`. Reporting runs on model load, with monthly license
state and network retries. These request bodies do not contain inference text,
detected originals or replacement output. Like other direct HTTPS requests, the
service also receives connection metadata. The SDK must not be modified to
disable or suppress required reporting. Operating offline is supported, and
the normal SDK handles reporting when networking is available.

One discoverable linked attribution is sufficient under the published terms.
The existing dev Privacy settings description credits “Redact by Desert Ant Labs” and links to the provider.
Production placement and privacy disclosure are part of the later decision.

## Integration boundary

The current scope decision on 2026-10-27 keeps enhanced detection in message
inputs and the existing recording/transcript text send path. Document/file
scanning on Linux servers is deferred, including small-file and optional full-scan
integration. The native evaluation and resource-policy prototype remain
engineering evidence; they do not enable a product feature. Existing document
and code embed paths retain basic detection wherever already supported. CLI/TUI
model activation remains deferred. Inputs longer than 2,048 UTF-16 code units use complete basic detection plus
configured private entries, without semantic inference. Short inputs share a
2,500 ms enhanced-work deadline across queueing, model readiness, exclusions,
recording fields and final message text for one send. This is an enhancement
budget, not a promise that all serialization, basic scanning or transport finishes
in that time. Slow first-use asset downloads continue in the background; stalled
inference terminates its worker and falls back. Short drafts can reuse a healthy
model after an oversized paste, and a completed background download rechecks the
current draft. The 2,048-code-unit ceiling is a conservative trial limit, not a
measured universal token or performance threshold.

Owner-visible message placeholders use compact labels such as `[ADDRESS_1]` and
`[ADDRESS_2]` for generated semantic tokens. Numbering is local to the rendered
message and avoids existing literal, short and configured labels. The unique
canonical tokens remain unchanged in encrypted mappings, outbound content and
copied message text. This avoids unsafe reuse of short tokens when older chat
history is unloaded or another device sends. Reveal/hide still uses the exact
canonical mapping. Street, city and postcode spans retain the ADDRESS category;
this change does not group them into numbered complete addresses. Embed-specific
renderers and viewers without owner mappings retain their existing presentation.

The development browser uses the local model for semantic detection while
retaining the complete existing basic pattern detector, configured private
entries, category settings and exclusions. Basic detection remains immediate
during loading and is used for sends if the model cannot download, initialize
or classify. One normal notification per browser tab/session explains the basic
fallback and offers retry; there is no additional composer status row. Returning
online also retries an unavailable model.
Model spans enter existing OpenMates
placeholder and encrypted mapping handling. The CLI and other consumers of the
synchronous detector retain their existing detector. Organization and blanket
URL redaction are excluded to preserve normal company names and public links.

The composer discards obsolete preview results. Final send independently awaits
classification of its captured document/settings/exclusions, using the full basic
fallback on model errors. Both detectors failing still stops the send. A later edit or account/chat/team change cannot publish an old
preview or overwrite a newer draft. Only public, versioned model/runtime assets
are cached; private scan inputs and results remain transient.

Ordinary dictation already becomes editable composer text and receives the same
send scan. Existing recording embed titles, filenames and transcript variants
also need explicit text redaction because their embed references are protected
from the markdown scan. This does not change existing audio transcription or
transcript-correction services: they receive audio/raw transcripts before the
editable composer stage. URL metadata fetching also precedes final chat send;
this trial does not claim to retrofit privacy filtering into all existing
external read/metadata operations.

## Network audit of the pinned browser runtime

Read-only source and artifact inspection on 2026-10-26 found no inference-input,
detected-original, result or log-upload request in the examined execution path.
This is evidence about the pinned implementation, not a claim that an arbitrary
downloadable SDK is unable to transmit data. The worker's fetch wrapper controls
what it caches; it does not block outbound requests to other endpoints.

The npm metadata for both `@desert-ant-labs/redact@4.1.0` and
`@desert-ant-labs/core@4.1.0` identifies commit
`86b9b55fe8c61ec1c27c5b6383f545c6df1d6ceb`, also the `v4.1.0` tag.
Installed `browser.js`, `codec.js`, `src/sdk.js` and `src/litert.js` were
byte-compared with that commit's corresponding source files and matched.
The lockfile pins registry integrity for these packages. Generated Redact and
LiteRT WASM files were byte-identical to the installed package files:

| Checked artifact | SHA-256 |
| --- | --- |
| `RedactWeb.wasm` (46,278,336 bytes) | `84689a2378bbff7a8a8f5ba7790c5765173aa9b4ff38e2578999b8051dc8eea4` |
| `litert_wasm_compat_internal.wasm` (10,948,854 bytes) | `4190033238e53ec86b832bad4649851ad111025c226c1688cfae20e1f8fe8926` |
| Generated `sdk.js` | `df634631a5e13292bd7d346f31a8a3329dd3e30a295fd215b46c9a51a7f030bf` |
| Generated `worker.js` (including HTML-response cache guard) | `87886e4e686b17e99596552667006cac5a8a78fa172dbb98d6f502efa791cc20` |

The reviewed network paths are:

| Destination | Method and payload | Purpose |
| --- | --- | --- |
| Same-origin `/pii-runtime/redact-4.1.0-litert-2.6.0/` | GET runtime files; no scan text in URL/body | SDK, worker and WASM assets |
| `huggingface.co/api/models/desert-ant-labs/redact/tree/v0.4.0?recursive=true` | GET; no request body | Model file names, sizes and integrity metadata |
| `huggingface.co/desert-ant-labs/redact/resolve/v0.4.0/{redact.tflite,redact_tokenizer.bin,labels.json}` and download redirects | GET; no scan text in URL/body | Pinned model assets |
| `events.desertant.com/api/v1/license` | POST JSON: `installId`, `model`, `modelVersion`, `sdk:{name,version}`, `platform`, `app:{id}`; optional `key` | License grant |
| `events.desertant.com/api/v1/activate` | POST JSON: `license`; optional `key` | Activate the server-issued signed license token |

For this worker, the source specifies `model="redact"`,
`modelVersion="v0.4.0"`, `sdk={name:"desert-ant-core",version:"4.1.0"}`,
`platform="web"`, and the worker hostname as `app.id`. No publishable API key,
Hugging Face token, custom endpoint, app ID or device ID is supplied by our
integration, so optional request `key` is absent. Cross-origin JSON requests can
also cause browser CORS preflights. The receiving services still see ordinary
connection/request metadata, including source IP, browser headers and origin or
referrer as allowed by browser policy. This is not anonymous operation.

The audited session factory starts licensing when a model session loads; the
licensing schema contains no text, detections, token counts, timing or per-call
input/output fields. Redact's input string is encoded into local FFI bytes,
tokenized, passed as tensors through `JSInferenceSession` to the local LiteRT
WASM model, and returned to the page through worker `postMessage`. The worker
does not log scans or errors. The SDK has optional HTTP debug logging that can
print license request/response bodies, and its WASI stdout/stderr bridge writes
to the worker console; our integration does not enable that debug flag. No
network log-upload call was found in the reviewed path.

The SDK normally stores its random installation ID and license state through
`__dalUsageStore`, or `localStorage` when available, otherwise an in-memory
store. A dedicated browser worker has no `localStorage`, and our worker supplies
no supported store, so the source selects in-memory metadata storage. Identity
therefore lasts for that worker, rather than being a durable browser install
identifier. Persistent monthly-active-device identity and its privacy/licensing
implications remain a production decision; this trial neither adds an identity
store nor alters SDK reporting. Native Apple/Linux builds use `UserDefaults`
for this metadata, so the worker lifetime conclusion does not apply to them.

Our explicit CacheStorage allowlist persists only versioned GET model/runtime
asset responses. It excludes license/activation POSTs, metadata tree queries,
scan text and results. The SDK's browser model filesystem itself is in memory.
The pinned bundle contains a default jsDelivr LiteRT URL, but our injected
LiteRT loader and explicit WASM directory select self-hosted assets instead.

Inspection covered the installed JavaScript/glue and pinned Swift Redact,
ModelStore, inference, HTTP and licensing sources, plus binary identity and
endpoint-string checks. The precompiled WASM was not independently rebuilt or
fully reverse engineered. Server retention and behavior are outside this code
inspection. No inference was run for the source inspection itself.

The subsequent isolated browser audit passed on source
`09380d118c38b313d9e6d5c1fd80331163a0d946` in GitHub run `40302932513`
(two cases, no skips or retries). It observed actual license and activation
POSTs with the schemas above, plus public model downloads. All observed HTTP
URL, body and header values were checked for the synthetic names and unique
email markers typed during the test; none appeared. A sanitized inventory
retains only host, path, method and body key names, excluding identifiers,
license tokens, signed queries and header/body values. Newly typed names were
also classified with networking disabled. This is observed HTTP evidence for
the pinned trial, not proof against arbitrary encoded covert channels or
future package changes. The account-free preview also loaded existing Stripe
assets; these are separate from the Redact integration.

Pinned source evidence:

- [Licensing endpoints and request schemas](https://github.com/Desert-Ant-Labs/desert-ant-core/blob/86b9b55fe8c61ec1c27c5b6383f545c6df1d6ceb/Sources/Usage/Licensing.swift)
- [Exact SDK/platform/app wire fields](https://github.com/Desert-Ant-Labs/desert-ant-core/blob/86b9b55fe8c61ec1c27c5b6383f545c6df1d6ceb/Sources/Usage/Wire.swift)
- [Metadata storage selection](https://github.com/Desert-Ant-Labs/desert-ant-core/blob/86b9b55fe8c61ec1c27c5b6383f545c6df1d6ceb/Sources/Usage/Storage.swift)
- [Licensing on session load](https://github.com/Desert-Ant-Labs/desert-ant-core/blob/86b9b55fe8c61ec1c27c5b6383f545c6df1d6ceb/Sources/Inference/SessionFactory.swift)
- [Local JavaScript inference bridge](https://github.com/Desert-Ant-Labs/desert-ant-core/blob/86b9b55fe8c61ec1c27c5b6383f545c6df1d6ceb/Sources/Inference/JSSession.swift)
- [Browser downloads and memory filesystem](https://github.com/Desert-Ant-Labs/desert-ant-core/blob/86b9b55fe8c61ec1c27c5b6383f545c6df1d6ceb/Sources/ModelStore/WasmBackend.swift)

## Verified development delivery

Vercel deployment `d0b63e7fc24752caff675fd626fd316b05922c7f` succeeded.
HTTPS GET measurements on `app.dev.openmates.org` transferred 18,140,652 bytes
for Redact WASM and 2,919,460 bytes for LiteRT WASM, with Brotli encoding,
`application/wasm`, and immutable one-year caching. Decompressed hashes matched
the package artifacts above. The worker is JavaScript with
`no-cache, must-revalidate`; the version endpoint reports the pinned versions.
Inspected response headers imposed no script/worker CSP restriction.

The two runtime binaries therefore transferred about 21.1 MB rather than their
57.2 MB raw size. Adding the model/tokenizer and small scripts puts the expected
first-use transfer near 46 MB; this total is an estimate from measured runtime
transfers plus public model sizes, not a second full browser-network capture.

Missing runtime files pass through the application's 404 redirect and ultimately
produce HTTP 200 HTML. The worker explicitly rejects HTML/XHTML asset responses
before caching, and evicts old cached HTML before fetching again. The focused
failure/retry browser scenario injects exactly this HTTP 200 HTML response,
then restores the real model URL and requires successful classification.
Licensing requests are outside this asset-only guard.

The final security/cache candidate
`528e5291bd77d0adb9fc3629145962e51a2384c9` passed both real-model composer
scenarios in [GitHub run 40317398417](https://github.com/glowingkitty/OpenMates/actions/runs/40317398417)
with no skips, retries or flaky results. This repeats the content-leakage audit,
new-input offline classification, full-account exclusion, and failed-download
notification/retry checks against the final worker. Send/owner-reveal and embed
fullscreen checks passed in run `40309153386`; normal notification recovery
passed across phone and laptop profiles in run `40302937679`.

The [Linux evaluation](redact-linux-evaluation-2026-10-26.md) records the separate
native memory, latency, detection misses, and OS-enforced offline proof.

## Brotli security check

The subsequent [licensing/privacy review](redact-licensing-privacy-review-2026-10-26.md)
confirms that users' browsers directly contact the licensing service. The vendor's
website privacy page does not document key SDK telemetry details. Production
approval remains withheld. The user prefers retaining the current enabled dev
trial with a settings switch back to regex. The [vendor inquiry](desert-ant-privacy-questions-unsent-2026-10-26.md)
is an unsent draft, not an approved change to the SDK's mandatory reporting.

The user explicitly requested checking the October 2026 decoder vulnerability,
`CVE-2026-111497`. This integration adds no Brotli npm decoder dependency.
Vercel negotiates HTTP compression; browser fetch handles content decoding before
the SDK receives response bytes. No Brotli dependency or decoder marker was
found in the inspected SDK/LiteRT glue or WASM, although stripped binaries do not
provide a complete dependency attestation.

Local and isolated CI Node use the patched 24.22.1 release. Its embedded Brotli
version still reports 1.2.0, so version text alone is insufficient. A shared
web helper requires Node 24.22.1 or later within 24.x and the backported
`BROTLI_DECODER_ERROR_FORMAT_BLOCK_SWITCH=-17` constant. Both runtime preparation
and the server hook assert this before application processing. Vercel's API
reported the deployed runtime family as 24.x, without exposing an exact patch;
the new guard checks the actual executing runtime rather than assuming its patch
from the platform alias or WAF status.

Hosted verification on 2026-10-26 **did not pass**. The function logs for
development commit `929203c4454c663eec131f084da011dcb3761dce` reported Node
**24.21.0**, with the patch marker missing. The startup guard therefore rejects
server-rendered requests with HTTP 500. The static app root and the tested worker
still return HTTP 200; the worker hash matches the candidate above. A fresh
deployment of the same commit explicitly skipped the build cache and again
reported Node 24.21.0 in the hosted function. No malformed Brotli input was sent.

The remaining blocker is Vercel's managed runtime patch rollout. Its documented
project setting selects only a major version, and its security advisory still
describes the rollout as in progress. Keep the guard enforced and do not call
hosted verification complete until a real server request succeeds on the patched
runtime. Production model activation remains disabled. The sanitized
[hosted receipt](evaluations/2026-10-26-redact/security-web-brotli-2026-10-26/manifest.json)
and [unsent support draft](vercel-brotli-runtime-support-draft-2026-10-26.md)
record the exact affected deployments without user content or credentials.

Playwright 1.60.0 pins Chromium 148.0.7778.96. Inspection of that Chromium tag's
vendored Brotli source confirmed the block-switch rejection, error -17, and
error propagation at all three switch call sites. This is a source/provenance
check for this CVE, not a blanket browser security audit or a claim about every
end user's browser.

The Linux audit found a separate affected path: the native SDK's curl shim loads
the host's libcurl, which automatically enables Brotli decoding through the old
system `libbrotli1=1.1.0-2build2`. Patched Node does not fix that native path.
The native evaluation runner now requires a verified task-private Brotli 1.1.1
build and validates the decoder version, file hashes and actual function address
through the SDK's real curl shim before SDK loading. The check ran with network
access denied and no model or licensing request. Shared host libraries were not
changed. Historical benchmark records remain unchanged; the separate security
receipt documents the corrected loader path. SDK licensing behavior is intact.

Primary security references:

- [Node October 21 security release](https://nodejs.org/en/blog/vulnerability/october-2026-security-releases)
- [Patched Brotli release](https://github.com/google/brotli/releases/tag/v1.1.1)
- [Vercel's runtime advisory](https://vercel.com/kb/bulletin/node-js-security-advisory)
- [Pinned Chromium decoder](https://raw.githubusercontent.com/chromium/chromium/148.0.7778.96/third_party/brotli/dec/decode.c)
- [Pinned Chromium error definitions](https://raw.githubusercontent.com/chromium/chromium/148.0.7778.96/third_party/brotli/include/brotli/decode.h)

## Preliminary published-demo observations

A synthetic evaluation of the provider's published demo (which identifies its
embedded SDK as 1.0.1) ran in Chromium on the Linux ARM development host. After
loading the runtime/model, networking was disabled for classification and then
restored. Ten cases ran successfully. Short cases took 403–418 ms, and a roughly
2,100-character transcript took 863 ms. A second model load in that page took
1,696 ms. These are exploratory samples, not production latency percentiles.

The demo detected English and French names/addresses, email, a phone number and
an IBAN, including values after an emoji and at the end of the long transcript.
The complete German sentence “Ich bin Anna Schneider und wohne in der
Hauptstraße 17 in Berlin.” yielded no detections. A negative code example's
version `3.14.159` was incorrectly classified as an IP address. Company names
were preserved. All returned span offsets matched JavaScript UTF-16 slicing.
These observations concern the demo version; candidate CI must exercise the
actual pinned runtime before the trial is considered verified.

A separate Chromium cold-load measurement of the actual desertant.com page
found its SDK 4.0.0 runtime uses the same large WASM footprint. Brotli delivery
reduced its 46.27 MB Redact WASM to about 17.97 MB transferred, and its 9.00 MB
LiteRT WASM to 2.60 MB. Including the 24.53 MB model, tokenizer and small SDK
files, the measured transfer was approximately 45.5 MB with the browser cache
disabled. The input became available after 2.4 seconds and the first scan after
another 4.0 seconds on this host/network. Repeat classification with networking
disabled detected Amina and Okafor; the same German sentence still yielded zero
entities. A shorter version-only negative sentence was left unchanged. The
website lazily initializes its demo and loads the model separately from the
page UI. It uses real on-device classification, not simulated highlights.

Sources checked 2026-10-26:

- [Published demo source](https://huggingface.co/spaces/desert-ant-labs/redact-demo/blob/main/main.js)
- [SDK browser API](https://github.com/Desert-Ant-Labs/desert-ant-core/blob/86b9b55fe8c61ec1c27c5b6383f545c6df1d6ceb/packages/redact-node/README.md)
- [Licensing request implementation](https://github.com/Desert-Ant-Labs/desert-ant-core/blob/86b9b55fe8c61ec1c27c5b6383f545c6df1d6ceb/Sources/Usage/Licensing.swift)
- [License and attribution conditions](https://license.desertant.com/1.0)
- [Model card and supported labels](https://huggingface.co/desert-ant-labs/redact)
