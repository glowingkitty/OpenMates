# Required-partial first-page continuation

`session.chat-first-page-continuation.v1` adds16 ordered shared vectors and three
fixed direct-library plans. Rust uses `SessionBridge` directly; npm uses the
built `SessionClient.readChatWithFirstPage`/NAPI facade; Python uses
`SessionClient.read_chat_with_first_page`/PyO3. No adapter launches the CLI.
The synthetic peer/account/crypto are isolated fixtures, never a product account.
The account and crypto protocol values exactly match the existing cache family;
old vectors remain unchanged. The new peer uses140 encrypted rows with latest100
and before40, including physical UUID vs logical composite/opaque IDs.

A cold admitted page requires explicit private/credential consent, a prospective
checkpoint capacity decision, then durable exact checkpoint AND credential writes.
A first-page ACK cannot be replaced with the capacity decision, credential hash,
final ACK or another stage ID. The callback receives100 rows41..140,
`history_complete=false`, `refreshing=true`, `cached=true`,
`pii_restoration=page_local`. No older request occurs until that callback returns
and the next same-operation pull resumes. Canonical140 requires a distinct exact
ACK and preserves `history_complete=true`, `refreshing=false`,
`pii_restoration=all_user_rows`. The request log must contain one latest100 and one
before100; composite/opaque before cursors must preserve the exact logical ID.

Explicit quota refusal skips only the optional first-page stage and continues
strict history; capacity IO/store/CAS/ACK/callback failures stop the owned read.
Callback cancellation closes only that read. Stale A cannot close or receipt B.
Warm reads remain cache-settled/incomplete, with no first-page callback or extra
window IO; existing cold strict APIs remain full140 with no new hook.

The16 vector IDs/order are fixed by the schema. Unknown modes or mismatched
fixtures must refuse, never pass by falling through. ACKs hash bytes read back
from fsynced files; host facades forward the actual receipt. The fixture store is
an explicit test admission policy, not a platform quota claim.

Pure schema/dispatch/refusal checks and source parsing do not execute these
interfaces. All actual Rust/NAPI/PyO3 vectors are authored UNRUN until isolated CI.
Queued original master-resource revoke/private-denial/request-cancel proofs remain
covered by the authored private-resource regression
`queued_original_checks_reject_private_denial_request_cancel_and_resource_revocation`
in `session_first_page_tests.rs`; public callers cannot construct those private
proofs. Core100-row lifecycle/rollback/epoch and native32MiB record-boundary tests
remain required separately. Product evidence and comparable performance remain
open. This family is required/partial, never release-complete from registration.
