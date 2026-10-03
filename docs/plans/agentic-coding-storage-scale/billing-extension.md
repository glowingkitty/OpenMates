# Weekly storage billing extension

Task: TASK-9893. Added at the user's request on 2026-10-03. This extension is
being implemented alongside the approved storage architecture; it does not
change the approval fingerprint for `architecture.storage-lifecycle@2`.

## Accepted requirements

- Charge credits weekly for customer S3 storage above the existing free limit.
- Preserve the initial personal allowance of **1 GiB (1,073,741,824 bytes)** and
  price of **3 credits per started additional GiB per week**. The existing
  schedule is Sunday at 03:00 UTC.
- The user selected **“Delete unpaid data after four weekly warnings.”**
- Update privacy and terms when their storage, deletion, or pricing statements
  are inaccurate. Coordinate publication with the matching runtime behavior.
- Use zero real inference for architecture, billing, and lifecycle verification.
  This approval does not authorize running destructive cleanup on real users.

## Metering and payer

Measure customer logical stored ciphertext once per `(bucket, object key)`.
Regional replicas, retry copies, migration buffers, and superseded system
generations do not multiply the customer charge. Shared references do not create
another bill for the same object. System records are not user storage.

Include authoritative encrypted chat archive pages and large payloads, old
artifact versions and snapshots, and sole durable S3 recovery outputs. Count
successful durable objects, not attempted uploads. Remove a logical object from
billable usage when its last customer reference is deleted; delayed regional
physical purge must not cause another customer charge. Keep separate operational
physical-byte measurements for capacity and provider costs.

Reuse existing archive/version/recovery metadata and bounded database aggregates
where practical. Do not add another per-object billing history row solely to
duplicate a million daily artifact-version records. Add missing immutable size
and owner metadata and reconcile it before charging. An ambiguous owner, missing
size, or incomplete usage calculation must pause billing rather than guess.

For this initial migration, preserve existing uploaded-file measurement and
personal uploader attribution. This avoids silently changing the legacy bill
while introducing archive billing. The settings quote and weekly charge must use
the same authoritative usage policy and expose the measured categories.

**Pending user decision:** charge new Team-owned storage once to the Team wallet
with its own 1 GiB allowance, or to its owner's personal wallet/allowance. The
question is already outstanding. Team policy is not assumed from silence.

Examples:

| Measured personal storage | Weekly charge |
| --- | --- |
| 1 GiB or less | 0 credits |
| 1.1 GiB | 3 credits |
| 2.5 GiB | 6 credits |
| 10 GiB | 27 credits |

Two regional copies of a 256 KiB archive page count as 256 KiB of customer
storage. An additional reference to that page does not add another 256 KiB.

## Settlement and warning safety

Freeze usage, amount, payer, policy version, and charge identity for each weekly
period. A retry cannot recompute the price under the same charge identity.
Mark paid only after the authoritative ledger confirms the complete charge.
Partial settlement, a scheduled retry, a timeout, or a database/S3 outage is not
proof of payment and is not proof of nonpayment. Preserve the existing credit
rules for other product charges.

Dunning belongs to the payer, not to each invoice independently. Process unpaid
periods without issuing multiple warnings for one week. Four successfully
delivered warnings must be separated by at least seven days. For a first warning
on day 0, the subsequent warnings are no earlier than days 7, 14, and 21; the
deletion deadline is no earlier than day 28. A failed notification does not count
as a delivered warning. Notices identify the affected storage, charge, export or
download opportunity, and dated deadline.

Before any expiration, recheck the current authoritative balance, outstanding
periods, allowance, ownership, references, and deletion eligibility. Successful
payment cancels expiration. Operational failures leave data intact. A successful
single current-week charge does not clear older unpaid periods. No charge or
dunning runs when paid service billing is disabled for the deployment edition.

The expiry operation must remain scoped to notified chargeable data and use the
existing reference-safe deletion path. It must not delete another owner's data,
another Team's data, required shared content, free account metadata, or an active
writer's sole copy. The exact archive-unit selection and invoice closure behavior
must be recorded before this action can be enabled; adding archive bytes to the
old upload-only “delete all files” loop is not an acceptable implementation.

## Public disclosures

Terms must explain the allowance, calculation, frequency, wallet charge, warning
process, and affected-data deletion. Privacy must distinguish the Vault-encrypted
server-readable AI working cache, client-encrypted PostgreSQL/S3 content, and
client-public-key-sealed unattended outputs. Explain reference ownership and
regional deletion without promising instant physical purge. Remove unsupported
claims about a user-retrievable 60-day export backup.

Public claims about four warnings or expanded archive billing must be published
with the matching implementation. Do not describe inactive rollout features as
already enabled. Translation sources and the canonical privacy mirror must agree.

## Required verification and rollout

- Exact allowance boundaries, started-GiB rounding, logical deduplication,
  ownership attribution, upload compatibility, and settings/charge agreement.
- Concurrent/retried weekly jobs commit one immutable period and one complete
  debit; pending, partial, and failed results cannot be reported as paid.
- Fake-clock four-warning timeline, failed notice delivery, final payment before
  deadline, older debt, operational outage, free allowance, protected references,
  and payment-disabled edition behavior.
- Disposable database/S3 integration verifies real metadata and ledger behavior,
  reference-safe deletion, and regional tombstones; no real inference or real-user
  data is used.
- Focused rendered legal-copy assertions, YAML mirror consistency, translation
  build, and coordinated publication dates.
- Observe/reconcile usage before enabling new archive charges; do not enable
  expiration until metering, notices, final settlement, reference checks, and the
  complete legal disclosure have source-bound evidence.

## Current state

Metering and personal settlement are implemented in the candidate with local
focused evidence. `STORAGE_LOGICAL_S3_BILLING_ENABLED` defaults off; only `1`
adds logical S3 categories to the personal bill. Team usage remains unrated.
The settings quote now uses bounded SQL category aggregation and exposes its
active policy version. Unknown or inconsistent usage fails visibly.

The frozen weekly invoice, exact-settlement check, provider-delivery notice ACK,
account-deletion billing closure, and bounded two-minute dunning/retry sweeps
are implemented. Notice delivery uses the existing Brevo idempotency guard;
uncertain delivery beyond its safe retry window becomes a durable manual-review
hold. Advertised UTC deadlines and the recorded notice timestamps both fence expiration.
A further audit found that the existing `email_deliveries.sent_at` proves Brevo
accepted a submission, not delivery to the recipient mail server. The candidate
now retains a private message ID and correlates bounded exact-ID provider events
before counting a warning. Accepted-only, unknown and bounced notices cannot
count; a later bounce holds expiry. Delayed delivery starts the warning clock at
the provider's delivered timestamp, and final admission rechecks all four
receipts. Storage warning records survive the generic seven-day email archive;
the separate receipt sweep can reconcile acceptance beyond the ten-minute send
retry window without sending the notice again. The provider's 90-day event
report horizon and uncertain receipts fail closed. These changes have focused
local evidence but no integrated delivery proof. Expiration must remain disabled
until that proof and the protected expiry action are complete; neither email
opening nor reading is promised.

Local focused checks include metering Node 9/9, Python 7/7, embed transaction
28/28, billing Python 70, warning transaction 7/7, notice rendering 21, legal
rendering 3, and the 21-locale translation build. These are candidate-local
checks, not isolated integrated PostgreSQL/S3 or source-bound release evidence.
A fixed-date unrelated workflow-digest retry test failed because its October 1
fixture had elapsed; it was not altered.

`feature.billing@6` is a validated draft covering the additional requirements;
its current fingerprint is
`ecf992c704d267106ce195106dec88fcf3ee31a0f75153638a5df175e61e87ab`.
An exact-fingerprint private review PDF was generated and visually inspected; it is not an approval. No approval receipt is claimed for that extension. The original approved
storage contract and its independently frozen CI sources remain unchanged.

Team payer, precise archive expiry and invoice-closure policy, formal extension
review, integrated evidence, and release activation remain open. No new storage charge or deletion has been run against real users.
