# Web Browse

The behavior contract is [feature.app-skill.web-browse@1](../../../specifications/features/app-skills/web-browse/specification.yml).
Delivery is tracked in [the implementation Plan](../../plans/web-browse/plan.yml).
This document records the implementation and provider integration; it does not claim completed deployment or live performance verification.

## Execution and authority

`web.browse` accepts a natural-language `task`, a public HTTPS `start_url` for a new session, an optional owned `session_id`, finite limits and an optional object/array JSON Schema. The existing preprocessor selects the skill from its hint. Detailed operating constraints are carried by the selected tool schema.

The skill admits a wallet reservation and creates encrypted owner/chat state before dispatching onto the existing `app_code` E2B worker. The broker carries opaque session/run/embed identities. Its exact invocation uses the existing detached-producer admission and deduplication protocol. Each run has a stable job identity; completed replays read its original encrypted result.

The worker owns observe → decide → validate → act. Jev chooses compatible operations and indexed DOM targets, with the current screenshot as image input. Code consumes each observation once and rechecks URL, target identity, geometry and occlusion. Generated text is a bounded JSON field value, never executable code, a selector or a shell command. Unsupported canvas, shadow-root, frame, upload and popup interactions require user intervention; Box-based targeting is not enabled without separate presence and geometry validation.

Model calls execute outside the session execution lock. Manual takeover invalidates the browser observation and pending decisions; code rechecks the controller before input. Viewing frames does not grant control. Manual sign-in consent is checked against the live origin. Pages requesting passwords, MFA or card secrets produce masked saved/AI previews and no text/control observations. Live frames during manual control go only to the authenticated owner and are not persisted.

The final result contains observed JSON `data`, source references, complete bounded extracted `observations`, a safe screenshot and timing/usage counters. `screenshot_ref` identifies the image inside the owner-authorized encrypted result; the binary `screenshot_base64` field is excluded from model input. Browser-job result bodies are encrypted separately from the Celery task backend. Transient results expire after 24 hours; saved encrypted chat embeds have independent retention.

Literal string-only answers have an additional verification path when the normal
Jev answer check abstains. Code first matches every nonempty leaf to observed
page text or URLs; unmatched values, paraphrases, numbers and empty containers
cannot use this path. A separately metered, 256-output-token text-helper call
then checks field meanings, relationships and complete requested coverage.
Quotation presence alone cannot pass. Required website actions still need the
existing Jev verification, and output schema/safety validation remains mandatory.
The original Jev thresholds are unchanged. Native controls cover a complete
quotation, omitted caveats, invented claims, an inverted claim and unfinished
navigation. Use `backend/scripts/test_web_browse_text_helpers.py --execute` with a
retained public observation to repeat those provider controls without revisiting
the website; this does not substitute for real CLI/SDK proof.

## First-party HTTP contract

Routes are hidden from public developer documentation. An authenticated session or approved first-party device is required. API-key scopes and spending limits still apply; broad developer keys cannot access browser data.

| Operation | Route | Limit per owner/minute |
| --- | --- | --- |
| Submit | `POST /v1/apps/web/skills/browse` | 6 |
| State | `GET /v1/apps/web/browse/{session_id}` | 90 |
| Frame | `GET /v1/apps/web/browse/{session_id}/frame` | 90 |
| Control | `POST /v1/apps/web/browse/{session_id}/control` | 120 |

Direct library requests additionally supply an owned `chat_id` and stable `message_id`. Submission returns a normal async skill job; existing npm/Python library polling resolves the final JSON response. Three active browsers per owner are admitted. Controller operations are `take_control`, `resume`, `stop`, `close`, `input` and `sign_in`; manual input has a typed allowlist. Let AI continue must also send a normal follow-up to the originating chat with the exact session ID.

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

The browser uses authenticated E2B ingress plus a separate RPC bearer. Neither credential enters chat embeds, model state or viewer URLs. E2B egress rules deny private networks; the browser independently checks public HTTPS destinations, DNS answers and robots exclusions for navigation and subresources. Popups and WebSockets are not alternate unguarded channels. The browser never receives OpenMates credentials.

Chromium and the robots reader share a CONNECT-only loopback transport. It resolves IPv4, rejects any non-public DNS answer and connects to the validated literal IP without a second resolution. Origin TLS/SNI and certificate validation remain with the clients. QUIC, non-proxied WebRTC and Chromium's implicit loopback bypass are disabled; there is no direct transport fallback. IPv6-only destinations are currently unavailable. This transport also covers unspecified/reserved addresses that E2B's denial-list validator cannot express using an unspecified CIDR base. The reviewed provider implementation is [E2B's validation](https://github.com/e2b-dev/runtime/blob/main/packages/shared/pkg/sandbox-network/firewall.go) and [connection filtering](https://github.com/e2b-dev/runtime/blob/main/packages/orchestrator/pkg/tcpfirewall/handlers.go).

Known provider creation rejections release the unused wallet reservation. Transport failures with uncertain allocation retain the recoverable creation intent for the independent inventory reconciler. A session whose original browser is missing never silently creates a replacement.

Google's successful GenerateContent usage reports use a [proto3 scalar cache counter](https://github.com/googleapis/googleapis/blob/master/google/ai/generativelanguage/v1beta/generative_service.proto), whose zero is omitted on the wire. Browse applies that documented default only to successful reports containing complete prompt/candidate/total counters, preserving both the native absent field and its protocol evidence in metrics. Missing usage or incomplete/failed responses remain unresolved. Other providers retain their reported cache counters without this default.

Supplier compute is measured from actual allocation and confirmed lifecycle events using allocated CPU/memory. For a verified 2-CPU/4-GiB instance the reviewed rate is `$0.000046/second`; resource metadata is checked rather than assumed. All internal model attempts and inherited output-safety decisions add native usage at the actual provider's effective tariff. The strict output boundary stops if safety processing cannot complete; it cannot introduce an unmetered generative fallback.

Customer credits are the existing floor/minimum policy applied once to cumulative supplier USD × 2 ÷ `$0.001`. There is no per-click minimum or additional public `ai.decide` markup. Running manual use and idle grace count; confirmed pause is free. Idle compute pauses after 120 seconds, and an independent worker deletes remote state after 86400 idle seconds. Polling does not extend either deadline or resume compute. Missing usage keeps the reservation for reconciliation instead of creating free successful work. Ordinary assistant inference has separate billing.

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
