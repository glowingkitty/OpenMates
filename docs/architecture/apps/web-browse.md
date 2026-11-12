# Web Browse

The behavior contract is [feature.app-skill.web-browse@1](../../../specifications/features/app-skills/web-browse/specification.yml).
Delivery is tracked in [the implementation Plan](../../plans/web-browse/plan.yml).
This document records the implementation and provider integration; it does not claim completed deployment or live performance verification.

## Execution and authority

`web.browse` accepts a natural-language `task`, a public HTTPS `start_url` for a new session, an optional owned `session_id`, finite limits and an optional object/array JSON Schema. The existing preprocessor selects the skill from its hint. Detailed operating constraints are carried by the selected tool schema.

The skill admits a wallet reservation and creates encrypted owner/chat state before dispatching onto the existing `app_code` E2B worker. The broker carries opaque session/run/embed identities. Its exact invocation uses the existing detached-producer admission and deduplication protocol. Each run has a stable job identity; completed replays read its original encrypted result.

The run loop lives in `web_browse_run.py`; `BrowseService.run` keeps admission, identity, replay and the final result and settlement. The browser runtime speaks protocol `preboot-v2`. A runtime that reports another protocol fails with a clear unavailable error.

A run starts with one `start` call, which does the live and blank-state checks, the crawler-policy check, navigation, a bounded settle and the first observation. An existing session resumes and calls `observe` instead. Each step then has this order:

1. Blocked, private-input and no-progress checks on the current observation.
2. One planner call (text helper, 4,096 output tokens). The input is the goal, the output schema, the page (URL, title, dialogs, up to 150 controls, visible text and a document excerpt of at most 24,000 characters around the viewport), the evidence ledger and the last 8 action results (kind, target, outcome and, for a refused action, only the runtime's fixed reason such as a covered target). The prompt tells the planner to close a covering banner, pop-up or region chooser before other clicks, and to use the site's search, navigation or start page after an error or not-found page instead of guessing further URLs. The reply is JSON with `notes`, `actions`, `done` and `blocked`, validated against the observation. Validation tolerates only what cannot execute anything unintended: unknown keys and extra action fields are dropped and every executed action is rebuilt from validated fields; missing `notes`/`actions` mean `[]`, missing `done` means `false`, missing or `"null"`/`""` `blocked` means `null`; malformed notes are dropped and counted as rejected; only the first six actions count; `click` may target any observed control, while `type` needs a type control and `select` a select control with an observed option value or exact option label. Unknown action kinds, unknown targets, wrong target kinds, unobserved options, invalid fields, non-HTTPS or mixed `goto`, unknown `blocked` codes and an unfinished plan without an action are rejected with a fixed, content-free `plan_error_code` in the run metrics. An invalid plan gets one repair attempt with the rejection reason; a second invalid plan fails the run. `blocked` is one of the fixed codes `sign_in`, `captcha`, `payment`, `sending`, `deleting`, `personal_information`, `age_confirmation` and `access_denied`. Each code maps to a fixed user-facing reason, so page-influenced text never becomes a reason.
3. The gate. A label, href or URL matching the dangerous-action pattern on any planned action ends the run as `needs_user` before any model call. Then, concurrently, one Jev injection question on the page and one single-target Jev `safe` decision (`{goal, target, page_title}`, the pre-v2 shape) for each non-plain action. Plain actions ask no question: scroll, wait, back, plain HTTPS link clicks, choosing a dropdown option and typing without Enter. Typed text and current field values never reach the gate. A safe score below 0.6 or injection above the threshold ends the run as `needs_user`. Content-free scores (`gate_injection_score`, step minimum `gate_safe_score`) are recorded in the run metrics.
4. Notes that pass the code check enter the evidence ledger.
5. One `step` call runs up to six planned actions, with one pending-action journal entry per batch.

The run finishes when the planner returns `done`, when it is blocked, or when a limit is reached. Code, not the model, decides which targets exist, which dropdown values are allowed and which URLs may be opened. Actions are `click`, `type` (optionally submitting with Enter), `select`, `scroll`, `wait`, `back` and `goto`; `goto` is only valid as the single action of a batch. Generated text is a bounded JSON field value, never executable code, a selector or a shell command. A `step` call rejects a stale observation id and checks each action against the snapshot of that observation for URL, target identity, geometry and occlusion. The batch stops without error before the first action that fails those checks and after any action that changes the URL; the rest are reported as skipped. An exception after input was sent is an uncertain outcome and ends the run as `needs_user` without a retry. Controls outside the viewport are valid targets; the runtime scrolls them into view. Unsupported canvas, upload and popup interactions require user intervention; Box-based targeting is not enabled without separate presence and geometry validation.

After each navigation or input the runtime settles: `domcontentloaded`, then no request in flight and no DOM mutation for 300 ms, capped at 2.5 seconds. Observations cover the whole document, including open shadow roots and same-origin frames, with up to 150 controls and the full document text (120,000 characters at most, marked when truncated). Screenshots are JPEG quality 60.

Model calls execute outside the session execution lock. The lock is held only around browser input, and the run reloads the record to detect manual takeover before any input. Takeover invalidates the browser observation and pending decisions. Viewing frames does not grant control. Manual sign-in consent is checked against the live origin. Pages requesting passwords, MFA or card secrets produce masked saved/AI previews and no text/control observations. Live frames during manual control go only to the authenticated owner and are not persisted.

The final result contains extracted and verified JSON `data`, `missing` JSON paths for values that could not be confirmed, source references, bounded checked `observations` of the last page, a safe screenshot and timing/usage counters. `screenshot_ref` identifies the image inside the owner-authorized encrypted result; the binary `screenshot_base64` field is excluded from model input. Browser-job result bodies are encrypted separately from the Celery task backend. Transient results expire after 24 hours; saved encrypted chat embeds have independent retention.

## Evidence ledger and answer checks

The ledger is the run's memory across pages: one entry per page with `{fact, quote}` notes. It is stored in the encrypted session record with a hash of the task text, so a takeover or continuation of the same task keeps it; a new run with a different task text starts with an empty ledger and step list. Code accepts a note only when its quote, whitespace and case normalised and at least 3 characters long, occurs in the current page's document text or equals an observed link URL. Other notes are counted as rejected and never stored. Limits are 60 pages, 400 notes and 600 characters per quote. A page enters the ledger only when it has at least one accepted note.

Every completed information task extracts a goal-specific answer once, from the goal, the schema, the ledger and the current page. It uses a default object schema when the caller omits `output_schema`. Raw tables, links and full page text remain in the separately checked observations. Snapshot metadata does not stand in for the requested answer.

Code then matches every string and number leaf of the answer. A leaf is matched when it occurs in a ledger quote, the current page text or an observed URL; numbers compare digit sequences. The model-written `fact` text is never used for matching. Then one Jev verification judges the whole answer against the current page, the ledger quotes and the run's interaction history (executed steps as kind, target label and page URL, never typed text, plus visited URLs), asking grounded, answer complete, interaction complete and empty search with unchanged thresholds. The outcome is:

- Jev accepts: `completed` with the answer as extracted (or `no_results`).
- Otherwise unmatched leaves are removed (set to `null`, array items without a matched leaf dropped). Without a matched value, or when the pruned answer does not validate, the result is `needs_user`.
- Otherwise one separately admitted and metered text-helper review (256 output tokens) of the pruned answer, with up to 400 matched quotations, the bounded ledger and the interaction history, returns strict booleans `grounded`, `answer_complete` and `interaction_complete`. Interaction is complete only when the history and the observed page show every required navigation, search submission, filter and form step; a filled but unsubmitted search is not. Quotation presence alone cannot pass. Grounded, interaction complete, answer complete and nothing pruned: `completed`. Grounded and interaction complete otherwise: `completed` with the partial reason and `missing` (empty when only completeness failed). Anything else: `needs_user`.

`sources` list every page that contributed a matched value. Output schema and safety validation remain mandatory. Use `backend/scripts/test_web_browse_text_helpers.py --execute` with a retained public observation to repeat the provider controls without revisiting the website; this does not substitute for real CLI/SDK proof.

## First-party HTTP contract

Routes are hidden from public developer documentation. An authenticated session or approved first-party device is required. API-key scopes and spending limits still apply; broad developer keys cannot access browser data.

| Operation | Route | Limit per owner/minute |
| --- | --- | --- |
| Submit | `POST /v1/apps/web/skills/browse` | 6 |
| State | `GET /v1/apps/web/browse/{session_id}` | 90 |
| Frame | `GET /v1/apps/web/browse/{session_id}/frame` | 90 |
| Control | `POST /v1/apps/web/browse/{session_id}/control` | 120 |

Session controls use first-party proxy handlers so browser cookies retain
FastAPI's specific-origin credentialed CORS headers. The narrow
`/v1/apps/web/browse/*` path must precede the public developer handler; its
wildcard CORS cannot be used with browser credentials. Both preflight and actual
requests must preserve FastAPI's headers. Authentication, owner checks and
quotas remain authoritative in the backend.

Direct library requests additionally supply an owned `chat_id` and stable `message_id`. Submission returns a normal async skill job; existing npm/Python library polling resolves the final JSON response. Three running browsers per owner are admitted; a fourth pauses the least recently used browser the AI holds idle (no active run, not under the user's control), which resumes on its next use, and is refused only when none is idle. Controller operations are `take_control`, `resume`, `stop`, `close`, `input` and `sign_in`; manual input has a typed allowlist. Let AI continue must also send a normal follow-up to the originating chat with the exact session ID.

## E2B runtime and cost

The stock desktop currently allocates 8 CPUs and 8 GiB according to its [official build script](https://github.com/e2b-dev/desktop/blob/main/template/build_prod.py). Browse instead uses a prepared Chromium image built by `backend/scripts/build_web_browse_template.py`, with 2 CPUs and 4 GiB. The image contains public dependencies and no user browser state. Set its immutable ID as `E2B_BROWSE_TEMPLATE` in the coordinated target runtime after verification.

With `E2B_BROWSE_PREBOOTED=true`, the immutable public template starts Chromium
before snapshotting. The optional `E2B_BROWSE_POOL_SIZE` (default zero, maximum ten)
keeps never-assigned, pristine VMs confirmed paused. Preparation and periodic
replacement are platform overhead. A new user's metered window starts only with
that user's admitted resume. An empty pool returns a bounded capacity failure;
it does not fall back to a slow cold start or charge a user for preparation.

Each pool slot has an immutable SQL claim receipt. Its primary-key constraint
permits exactly one destination session; an uncertain insert response grants no
access. Before resume, the encrypted handle is saved under the owner's Vault key
and the platform's credential copy is removed. A claimed VM never returns to the
pool, including after cancellation, sign-out, cleanup or a failed handoff. The
owner may resume their original VM; closing or expiry destroys it. The pool
janitor follows the durable claim across worker/cache restarts. A fresh blank
check verifies the live page is `about:blank` with no cookies or stored origins
before any page navigation or model access. There is no profile reuse or browser
state clearing operation intended to make a used VM available to another user.

The browser uses authenticated E2B ingress plus a separate RPC bearer. Neither credential enters chat embeds, model state or viewer URLs. E2B egress rules deny private networks; the browser independently checks public HTTPS destinations, DNS answers for navigation and subresources. Robots exclusions are checked for document navigations (main frame and subframes); other subresources skip the robots lookup but still use the pinned transport. Block detection is structural: a 401, 403 or 429 navigation response, a CAPTCHA frame or widget, or a page with under 1,500 characters of text whose text or title matches the human-verification, access-denied or paywall patterns. A long article that mentions a CAPTCHA is not blocked. Popups and WebSockets are not alternate unguarded channels. The browser never receives OpenMates credentials.

Chromium and the robots reader share a CONNECT-only loopback transport. It resolves IPv4, rejects any non-public DNS answer and connects to the validated literal IP without a second resolution. Origin TLS/SNI and certificate validation remain with the clients. QUIC, non-proxied WebRTC and Chromium's implicit loopback bypass are disabled; there is no direct transport fallback. IPv6-only destinations are currently unavailable. This transport also covers unspecified/reserved addresses that E2B's denial-list validator cannot express using an unspecified CIDR base. The reviewed provider implementation is [E2B's validation](https://github.com/e2b-dev/runtime/blob/main/packages/shared/pkg/sandbox-network/firewall.go) and [connection filtering](https://github.com/e2b-dev/runtime/blob/main/packages/orchestrator/pkg/tcpfirewall/handlers.go).

Known provider creation rejections release the unused wallet reservation. Transport failures with uncertain allocation retain the recoverable creation intent for the independent inventory reconciler. A session whose original browser is missing never silently creates a replacement.

Google's successful GenerateContent usage reports use a [proto3 scalar cache counter](https://github.com/googleapis/googleapis/blob/master/google/ai/generativelanguage/v1beta/generative_service.proto), whose zero is omitted on the wire. Browse applies that documented default only to successful reports containing complete prompt/candidate/total counters, preserving both the native absent field and its protocol evidence in metrics. Missing usage or incomplete/failed responses remain unresolved. Other providers retain their reported cache counters without this default.

Supplier compute is measured from actual allocation and confirmed lifecycle events using allocated CPU/memory. For a verified 2-CPU/4-GiB instance the reviewed rate is `$0.000046/second`; resource metadata is checked rather than assumed. All internal model attempts and inherited output-safety decisions add native usage at the actual provider's effective tariff. The strict output boundary stops if safety processing cannot complete; it cannot introduce an unmetered generative fallback.

Customer credits are the existing floor/minimum policy applied once to cumulative supplier USD × (1 + `pricing.margin_percent`, default 50%) ÷ `$0.001`. There is no per-click minimum or additional public `ai.decide` markup. Running manual use and idle grace count; confirmed pause is free. Compute pauses as soon as a run ends under AI control, except a `needs_user` run, which keeps its idle window so the owner can take over at once. Otherwise idle compute pauses after 120 seconds, and an independent worker deletes remote state after 86400 idle seconds. Polling does not extend either deadline or resume compute. Missing usage keeps the reservation for reconciliation instead of creating free successful work. Ordinary assistant inference has separate billing.

Use `backend/scripts/test_web_browse_runtime.py --execute` for the provider smoke probe after deployment. This does not substitute for the required real CLI/library and web flows. Record startup, observation/action latency, model calls, native tokens, completion/failures and settled charges separately from estimates. The first prepared-template build took 57.76 seconds; this is one-time engineering preparation, not a measured user browsing latency.

## Provider permission and data policy

Reviewed 2026-10-26. Use documented supplier APIs and their account terms; website automation itself grants no collection or downstream-use rights.

| Provider | Permission/reference | Enforced integration conditions |
| --- | --- | --- |
| E2B | [Terms](https://e2b.dev/terms), [SDK/API source](https://github.com/e2b-dev/E2B) | Isolated cloud runtime under the existing account; no infrastructure fallback. Authenticated ingress, bounded running allocation, confirmed pause and explicit deletion. |
| TypeSafe Jev | [Official agent example](https://github.com/browser-use/jev-ultrafast), [data handling](https://help.typesafe.ai/articles/5974925716-how-is-submitted-data-used-or-retained) | Existing direct Jev API; bounded typed decisions and images. No statement that deleting E2B also deletes provider records. No passwords/MFA/cookies/tokens in observations. |
| Together / DeepSeek | [API/model reference and MIT model licence](https://www.together.ai/models/deepseek-v4-1-flash-1017), [terms](https://www.together.ai/terms-of-service), [privacy/ZDR](https://www.together.ai/privacy) | Existing reviewed `DeepSeek-V4.1-Flash-1017` snapshot, reasoning effort 1. Only eligible public field/extraction context. Sensitive/private-account context is withheld. Verify organization ZDR before setting `WEB_BROWSE_TOGETHER_ZDR_VERIFIED=true`; otherwise use the permitted fallback. This flag does not change the supplier's settings. |
| Gemini | [Gemini API terms](https://ai.google.dev/gemini-api/terms) and existing Google provider configuration | Existing Gemini 3.8 Flash route, one bounded fallback with LOW thinking. The existing account must use the permitted Paid Services data policy; promotional credits do not imply use of unpaid quota. No change to ordinary chat routing. |

General public reading honors crawler exclusions and stops at access denial, paywall or CAPTCHA barriers. Manual login remains limited to permitted site access. Provider-specific collection requires the separately documented permission described in `docs/contributing/guides/add-api.md`; Browse is not a substitute for an unavailable licensed connector.

The user warning is contextual, once per site/session: this is a cloud browser; resumed AI can access account information and send relevant page content to providers. It offers Continue to sign in and Cancel. Login consent does not authorize consequential submissions.

The web embed is implemented by `BrowseEmbedPreview`, `BrowseEmbedFullscreen`
and `BrowseSessionViewer`. The viewer shows the step list (`steps`, target labels only, never typed text, last 80) and the `phase` from the state route, and the result views show `missing`. While an AI run is active, state and frame read the stored record without waiting on the session lock, and a frame is the latest stored observation screenshot; only manual control reads live pixels. Authenticated frame requests use first-party cookies
and no-store transport; live object URLs are released on view/account changes.
Public and read-only embeds use only their saved masked screenshot. A terminal
result without one has an explicit missing-screenshot state. Watching does not
resume compute or extend inactivity. Manual input stays in memory and is cleared
before sending; an uncertain input is not automatically retried. Stop is shown
as cancelled only after the owned session acknowledges its paused state.
AI continuation uses the existing normal-chat handoff with the exact session,
originating chat and original spending cap. The saved `data_json` field preserves
arbitrary JSON independently of the shared TOON table's flattened keys.

Text helpers accept a complete JSON document, optionally enclosed by one complete
JSON code fence. Commentary and extra fences remain invalid. Protocol failures
retain only allowlisted reason codes, shape/length and helper purpose; no raw
provider response or page text enters these diagnostics. This normalization does
not change factual confidence, answer coverage, literal-quotation matching or
the separate semantic review.
