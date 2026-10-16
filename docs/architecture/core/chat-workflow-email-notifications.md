# Chat response email and Workflow notifications

Email sends use verified account contact ciphertext through the existing Vault
key and freshly check the global block list. Client-only encrypted addresses
cannot be decrypted offline. A missing verified address skips delivery.

Before this change, notification defaults were off, legacy preference values
had no choice provenance, and a connected WebSocket stood in for human activity.
The response worker accepted decrypted recipient/content arguments after the
upstream offline check, with no final preference or viewed-message recheck.
The daily dispatcher handled backup reminders and applied a fourteen-day
activity gate; it had no Workflow-run digest.

`aiResponses` covers completed visible Mate responses and committed messages
from other Team users. `workflowRuns` covers scheduled Workflow runs. Explicit
choices live separately in `email_notification_preference_choices`; sparse
updates persist before acknowledgement and preserve other category choices.
`includeContent` requires a recorded user opt-in. It starts off.
Per-user Redis leases serialize fresh read/merge/write operations across
devices. Settings opening fetches a durable read-only snapshot rather than
replaying stale cached preferences as a write.

Legacy master-off values have no provenance. The user-approved clean transition
sets ambiguous legacy master flags on while preserving identifiable explicit
opt-outs, stored false categories and global blocks. Previously master-off
backup/webhook categories remain effectively off. The idempotent migration runs
with `cms-setup`; the aggregate inventory query exposes no identities.

Supported core updates apply this migration automatically. The upgraded CLI
pulls/builds target CMS and setup images, stops the old API, email worker and
scheduler, starts the target CMS, and requires fresh setup to finish successfully
before resuming compatible consumers. Filtered core-runtime updates include this
cohort; observability-only updates remain scoped. Stop, CMS startup or setup
failure prevents consumer startup. Setup may safely run again: recorded user
choices and category opt-outs still win. Production rollout must first install
the released CLI with the `coreSetupGate` dry-run capability. An already-running
old CLI or sidecar cannot provide the new ordering; the production runbook blocks
that bootstrap path. No operator-run notification SQL is needed.

Chat email candidates contain only routing metadata and bounded Vault-encrypted
preview envelopes. The email broker receives only user, chat and message IDs.
Dispatch waits 15 seconds for reconnects and reads durable preferences, verified
recipient, membership, presence and opaque viewed-message receipts immediately
before sending. Foreground web/Apple activity suppresses email for every chat;
TTY viewer presence covers only its selected chat. Leases refresh at 25 seconds
and expire at 75 seconds. Ordinary SDK and automation sockets report no human
presence. Background clients remove their lease. Installed Apple lifecycle frames without
a client type are classified using their established Apple headers. Only a
declared foreground state renews on received application messages; control pings
are not visible to the ASGI handler. Legacy idle foreground clients expire after
75 seconds and need the updated lifecycle heartbeat. Old Watch clients declare no
lifecycle state and likewise need the client update. Headers classify a client;
they do not constitute an authentication boundary.

The standalone Watch uses one root-owned chat socket across hub sections.
Foreground heartbeats cover the whole Watch app; only committed transcript
messages in the visible scroll area generate correlated viewed receipts.
A receipt is confirmed only after a positive server acknowledgement.
Eligibility is checked again after awaited provider credentials and optional
preview decryption. Revoked preview consent removes both content and title from
the body and subject; late ineligibility records a skipped delivery.

Default email contains the sender, a signed-in chat link and settings link.
Ordinary encrypted Team turns use the existing atomic preflight even while
Personal/AI turns remain on protocol epoch zero. The server validates Team scope,
sender identity, preflight, message and ciphertext before relaying or confirming
the turn. The global pause and expected-version guards remain enforced. This
prevents a local rendered message or a ciphertext relay from masquerading as a
durable commit. SDK Team sends likewise preserve the authorized Team hash in the
atomic write and enqueue notifications only after it succeeds.
The browser retains the original ciphertext-only ordinary Team preflight in tab
session storage, bound to the account, Team, chat, message and a chat-keyed content
check. A timeout or reconnect reuses its turn, ciphertext, wrapped key, metadata
and trace. A matching committed-message confirmation clears it. If tab storage
is lost, authoritative sync must reconcile a committed row; exact replay is no
longer available. The browser regression drops a real preflight acknowledgement
and checks recovery plus one durable message.
Team links include the Team ID as routing metadata; the web client verifies
access and changes context before opening the chat, including after login.
Preview consent permits a 60-character title and first ten logical response
lines, capped at 2,000 characters. Providers receive this enabled preview in
plaintext. Team sender clients request recipient-consent capability before
submitting a separate preview, and the server immediately seals it under the
recipient's notification Vault key. The staged envelope is scoped to the Team,
chat, committed message, author and recipient, so another author/chat cannot
consume it. The server never reads stored chat/Team keys.
Web and CLI sender paths implement this exchange. Apple's current Chat/send
model has no Team identity for a safely scoped preview capability; it does not
infer one or upload chat keys. Unavailable preview material falls back to
content-free email.

Pre-transition queued email tasks have no committed message identity and cannot
be rechecked safely. The new worker discards those old plaintext envelopes.
New candidates retry within ten minutes of their original reservation, using a
per-delivery Redis lock and stable provider idempotency key. Retry tasks retain
the original message identity or digest cutoff and recheck consent before send.
Brevo documents [provider idempotency](https://developers.brevo.com/docs/heterogenous-versions-batch-emails)
for this endpoint; our ten-minute retry window is shorter than its documented TTL. SMTP has no
equivalent provider guarantee: after an ambiguous failed attempt, retries stop
instead of risking a second email. Switching transports during a retry also
stops that retry.

At 09:00 UTC the daily dispatcher aggregates scheduled runs accepted in the
preceding half-open 24-hour window. The immutable window endpoint identifies
the digest across retries and scheduling boundaries. Manual/test outputs never
generate digest rows or individual chat emails. Empty periods reserve/send
nothing. The current eligible-trigger allowlist has a future webhook seam.
Digest retry tasks expire after ten minutes and reject a cutoff older than the
latest daily window before initializing services and at the send boundary,
including after awaited credentials and verified-address reads. A delayed sweep or
retry cannot send yesterday's digest alongside today's digest. The paginated user
sweep also bypasses HTTP cache so a stale disabled preference cannot omit a user.

Counts, run states, UTC timestamps and signed-in run links form the default
digest. Computation completion and device delivery acknowledgement are separate:
pending/claimed Send message work is shown as awaiting delivery. Email sends
never update acknowledgement state. Cancelled, failed and expired deliveries
have separate totals. An overdue unpersisted pending/claimed lease counts as
expired; a device-persisted delivery still awaiting server acknowledgement stays
pending. The digest reads these outcomes without changing delivery rows.
Optional title previews use the existing
Workflow encryption path. Output previews use only intended Send message text
from a valid, unexpired owner-scoped Vault payload, capped at ten lines and
2,000 characters, with at most one message per run. Internal execution inputs,
embeds and other node outputs have no safe preview field and are excluded.
Cleared or expired payloads fall back to metadata-only rows. Up to fifty run
rows are shown with complete totals and an omitted
count for larger windows.

## Scheduled completion notifications

Successful scheduled runs also reserve a metadata-only
`workflow_completion_notifications` row before executing effects. Completion
pins the first successful Send message's delivery, chat and message identities;
a run that never executes Send message keeps only its Workflow and run identity.
Manual/test, failed and cancelled runs do not send completion notifications. The
daily digest remains independent.

The completion dispatcher keeps separate event, email and Apple device ledgers.
It rechecks ownership, current notification preferences, verified contact and
content consent before dispatch. A rotating paginated reconciler recovers queued
or interrupted work without starving later rows. Redis reservations and provider
idempotency use the stable run identity. Definite transient provider rejection
may retry; ambiguous acceptance is retained as uncertain to avoid duplicate
notifications. Email does not wait for a device to persist the chat message.

Apple iOS/macOS pushes use `OPENMATES_WORKFLOW_COMPLETED` without an inline Reply
action. The public payload contains routing metadata and generic completion
text. A Workflow name, when available, uses the existing device-encrypted preview
envelope. Email includes the name only with explicit content consent; otherwise
the run reference and completion time identify the result.

Both channels link to the pinned chat/message after an actual Send message, or
the exact run page otherwise. The authenticated run detail exposes the durable
completion target even after run content is pruned. Web and Apple reauthorize
that target, finish the existing owner-device encrypted delivery protocol, and
wait for persisted chat/message sync before navigation. Account, profile,
workspace and transport changes invalidate pending work. Missing, deleted or
mismatched targets show unavailable rather than opening another chat or run.

Coverage includes dispatch recovery, privacy and idempotency unit tests, isolated
scheduled SMTP integration, cold-open web routes, and Apple parsing/preview/
delivery tests. Native execution and real APNs device receipt require an admitted
Mac runner and device; Linux source checks do not establish those results.

Isolated product tests use runner-private Directus/Redis/Vault and SMTP Mailpit,
without real inference or public fixture endpoints. Captured mail is integration
evidence, not live provider or external inbox delivery evidence. Controlled live
samples need separate provider acceptance and mailbox receipt records.

Live provider acceptance and external mailbox receipt are currently unverified:
no controlled mailbox is configured, and the user deferred mailbox setup. Native
runtime verification also requires a Mac build; source audits alone do not prove
Apple lifecycle behavior on a device.

Dev activation and packaged migration completed on 2026-10-02: 413 of 414
accounts are enabled, the exact global unsubscribe remains disabled, and unrelated
category counts did not increase. Production rollout still requires the released
setup-gate CLI described above. Runtime health is separate from external mail,
live-inference and Apple device verification.

Current verification and rollout evidence is recorded in
`docs/plans/chat-email-workflow-digest/verification.md`.
