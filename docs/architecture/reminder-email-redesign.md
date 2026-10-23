# Reminder email redesign

Updated 2026-10-23. Task: TASK-4084; session: faf0. Status: implemented in the
scoped working tree. Isolated email delivery and responsive rendering passed;
all3 reminder/navigation and all4 shared-guest cases pass isolated CI with
verified cleanup. Dev deployment and both live test emails remain pending.
The user approved the rendered-card design,
requested embed descriptions, and authorized implementation, testing, both test
emails and the related specification updates. The executable record is
[the implementation plan](../plans/reminder-email-redesign/plan.yml).

## Implemented email and rendering design

The reminder template reuses the newsletter's shared header, footer and styles:
the soft gray rounded content panel, blue heading and legal footer, and orange
rounded action. Its envelope is replaced with the existing reminder bell. Chat
previews follow `WorkspaceContinueCard.svelte`; event and other saved-item
previews follow the existing result-card geometry, calendar badge and app corner.
The earlier text-led and app-card concepts are superseded by the accepted design.

`reminder_preview_renderer.py` draws a static 600×400 PNG, corresponding to a
300×200 product card at double resolution. It uses Pillow and CairoSVG with
bundled product category/app palettes, trusted local SVG glyphs and the existing
Lexend fonts. Their licenses accompany the assets. Chat cards retain the gradient,
centered icon, title/summary and decorative corner glyphs. Dated embeds retain
the calendar identity, app corner, title and available time/provider facts. An
optional bounded JPEG/PNG thumbnail is included when captured by the client;
without one, the card uses the actual result preview's text-first arrangement.

The runtime does not launch a browser, execute caller HTML/SVG, fetch external
URLs or open an authenticated app session. Structured input, thumbnail bytes,
decoded image pixels and output size are bounded. Only trusted bundled SVGs reach
CairoSVG. Failed rendering reports content-free error types. The earlier static
Svelte study established the visual reference; native rendering is the implemented
production path and does not claim pixel-identical browser output.

The subject and ordinary email text identify the saved chat/item. Descriptions,
notes, location and available relevant facts stay readable and selectable outside
the image. Event start/end time and captured timezone are distinct from reminder
delivery time. The image alt text is exactly the target title. Its destination is
the same canonical URL as the separate Open chat, Open event, Open appointment or
Open item action. The existing email pipeline generates the plain-text alternative
from the rendered HTML, retaining essential text and links when images are blocked
or expired. Generic embeds use the generic reminder heading and Open item action.

## Limited durable context

The client captures only the selected reminder's identifying facts at creation
or authorized enrichment. Version 1 permits kind, title, description, summary,
icon/category/app identity, absolute start/end time, IANA timezone, location, up
to eight label/value facts and an optional small raster thumbnail. The server
normalizer allowlists fields and bounds metadata to 8 KiB before the optional
image. Descriptions are normalized to text; the email renderer escapes all text.
The optional image is limited to 160 KiB of raw base64 and two million decoded
pixels at intake; native rendering independently validates its format and bounds.

The snapshot is encrypted with the existing per-user reminder Vault mechanism.
The bearer token and language live inside that ciphertext; only its token digest
and expiry are separately queryable. Reminder context therefore survives ordinary
temporary embed/inference cache expiry without giving the server a general path
to decrypt chats, memories or embeds. The snapshot is removed with its reminder.
It does not contain a transcript, full provider response, share key or unrestricted
rendering document. Saved facts describe the captured item; they do not claim a
live provider availability check.

This is deliberately limited server-readable reminder content, not end-to-end
encrypted email. The recipient's mail provider can see the selected details. Rich
reminder content is enabled under inherited defaults, while an explicit user
hide-content choice causes dispatch to omit prompt, title, snapshot and preview.
The result is a generic subject/body. Other notification kinds retain their own
content rules. Existing email eligibility and the `backupReminder` preference gate
remain in place. Legacy reminders preserve their saved prompt and known fields;
unavailable descriptions, titles or dates are not invented.

## Private preview transport

Private card images use the first-party route
`/v1/email/reminder-preview/<reminder-id>/<opaque-token>.png`. GET and HEAD are
an unauthenticated email-client capability surface, not developer-key or cookie
authority. The random 256-bit bearer grants access to one reminder image only;
anyone holding that URL can retrieve that image while the capability is valid.
It grants no general chat/embed access and contains no plaintext title or facts.
An explicit GET/HEAD Caddy route forwards this capability before the general
Origin-gated API rules; its bearer path is excluded from access logging.

The origin validates reminder identity, bearer digest, reminder state and expiry
before decrypting the snapshot. Wrong-token, expired, cancelled, failed or deleted
records return the same unavailable result. Expiry is at most 90 days after the
latest reminder email delivery. Responses use private five-minute cache headers,
no-referrer, nosniff and a restrictive content security policy. Origin revocation
does not remove an image already retained by a mail client or mail-image proxy.
Requests are rate-limited to 120 per minute under the existing limiter. Rendering
incurs no AI inference and accepts no arbitrary remote source. Bearer paths and
private context are redacted from application/access diagnostics.

This transport is chosen instead of assuming Brevo ordinary attachments provide
inline Content-ID images. The reminder bell is a public first-party PNG; private
reminder rasters use only the opaque first-party URL. Essential email text and
actions remain useful after preview expiry or when the recipient blocks images.

## Exact-target propagation

Creation/enrichment retains the source chat and child embed identity. Source
resolution checks fresh Personal ownership and source/parent provenance; an embed
author hash alone does not authorize Team data. Known public calendar events keep
their existing guest behavior. Verified source context is persisted rather than
recovered by scanning full chat histories on every preview request.

Dispatch passes `notification_context`, `target_embed_id` and `preview_url` through
the backward-compatible email task. Destination URLs come from the configured
frontend base and encoded identifiers, never caller-supplied redirect HTML. Chat
links select the referenced chat. Private embed links retain both fields, for
example `/#chat-id=<source>&embed-id=<child>`, and select that child detail.
Supported standalone public or recoverable legacy embed targets retain their
existing route semantics.

The web changes retain the complete pending target through required login,
application startup and sync readiness. Missing or inaccessible targets produce
a visible unavailable state instead of selecting an unrelated recent chat.
Duplicate chat-selection events retain the complete URL. Initial Personal owner
hydration invalidates account caches without emitting a false workspace-switch
event that clears the route. Fullscreen echo suppression compares the actual
open/in-flight embed, source chat and message target; it permits a different or
missing embed in an already-open chat. Public/shared guest regression coverage
is included in the current isolated CI verification.

## Verification and remaining evidence

The focused reminder backend suite passed **81 cases** and the frontend unit
suite passed **48 cases** locally on 2026-10-23. They exercise real MJML output
and its plain-text conversion,
escaped descriptions/notes/facts, exact image/action destinations, title alt text,
generic embed actions, legacy jobs, explicit redaction, light/dark geometry,
optional local thumbnails, network exclusion, input/pixel limits, timezone/end
time and private exception handling. The translation build generated all 21
locales; Python compilation and whitespace checks passed for the email/rendering
slice. These are supporting local checks, not evidence of deployed delivery.

Isolated email CI passed at source `6edecaf3178e3a82934dc153508694d2edc1d36a`
(run `39968453003`): actual skill/Vault/cache recovery, scheduler and broker
delivery to Mailpit, the API-fetched PNG, invalid/expired/cancelled capabilities,
explicit opt-out, duplicate suppression, private logs, desktop/phone layout and
blocked images. Its backend/email inputs are unchanged in the final candidate.

Navigation CI at source `5ead0fcc6a4813e1df8bfc36b5f8f6377595cee0` (run
`39979787941`) passed initial exact-target opening, reload, cold login and real
reminder creation, then exposed the same-chat embed echo guard described above.
That guard is repaired, compilation/lint pass, and the test now requests a
missing embed while the valid fullscreen is still open. Final candidate
`256e41626964d2537f3883f8886b1d47a765d9ce` is materialized in session faf0.

Runs `39983703203` and `39983874264` stopped before candidate setup because
the newly deployed shared Node supplier guard rejected `source_mode`. They
produced no application-test recordings or result artifact and do not prove or
disprove the reminder changes. The user subsequently authorized resolving the CI
blocker. The harness owner published a verified official Node download into a
private supplier cache in `1edab52b66`, preserving strict executable guards.
The reminder candidate passed the complete3-case suite in isolated run
`39990431096`, including full targets, reload/cold login, reminder creation and
same-chat missing targets. Shared-guest run `39993579945` passes all4 cases
after correcting ambiguous test assertions. Both report complete coverage, no
skips/retries and verified cleanup. The shared regression source differs only
in assertions/docs/generated records; product files are identical. No guard was bypassed.

Required completion evidence remains:

- Scoped dev deployment followed by the two already authorized test deliveries,
  one chat and one event/embed, to the user's verified configured notification
  address. Delivery success and selected recordings belong in the final receipt.
- Persist the reviewed gateway route in root-owned `/etc/caddy/Caddyfile`;
  this session can update live Caddy configuration but lacks root file access.

The related approved behavior is recorded under
`specifications/features/notifications`. CI, deployment and actual receipt of the
two emails must be recorded when they occur; this report does not claim them.
