# Weekly storage billing extension

Task: TASK-9893. Added at the user's request on 2026-10-03. This extension is
implemented alongside the approved storage architecture; it does not
change the approval fingerprint for `architecture.storage-lifecycle@2`.

## Team decisions — 2026-10-06

The user confirmed every Team has its own **1 GiB** free allowance and accepted
the recommended separate Team wallet. The rate remains **3 credits per started
excess GiB per week**, Sunday 03:00 UTC. Team usage never consumes a personal
allowance or personal wallet. Existing uploaded-file payer attribution remains
unchanged for this migration; replicas and multiple references are not billed twice.

The user selected **“Notify owner/admins; expire enough safe warned data.”** A
Team warning round counts only after provider-confirmed delivery to its current
owner and every admin. Four rounds must be at least seven days apart, with
expiry no earlier than day 28 or seven days after the fourth round. Changed or
unresolved recipient history holds expiry. Only complete, specifically warned,
independently removable Team units are candidates, oldest first and only enough
to restore the Team allowance. Active work, sole recovery copies, required
references outside selected units and later-paid data remain protected. No safe
sufficient subset means no removal or waiver. Verified removal may waive only
the warned unpaid episode, never later debt or paid periods.

Reuse the existing authoritative numeric Team wallet and version with an atomic
SYSTEM ledger debit; preserve the optional client-encrypted snapshot as advisory.
This does not require Team content-key migration. Add distinct Team invoice and
warning tables, owner/admin quote and affected-unit screens, CLI/SDK readers,
emails and conditional legal disclosures. Financial flags remain off until the
focused PostgreSQL/S3 and client gates pass. Official-cloud new Team archive
copies and pruning require Team billing readiness; self-host archival remains
independent of cloud charging, and existing cold reads remain available.

These decisions are transcribed in `feature.billing@7` and P-9. Current artifact
heads remain in PostgreSQL under D-9; optional Q-8 is not a completion gate.

## Apple client handoff for P-9

Update the existing Mac workspace to the published dev storage commit before
implementing this contract. Preserve the separate native writer work already
assigned; no Team content-key migration is required.

- Owner/admin storage quote: `GET /v1/teams/{id}/storage`, response root `storage`.
  Show `total_bytes`, `free_bytes`, `billable_gib`, `weekly_cost_credits` and
  `billing_status`. Supported status values are `disabled_pending_validation`,
  `current`, `unpaid` and `manual_review`. A disabled quote is an estimate.
- Affected units: `GET /v1/teams/{id}/storage/notice?limit=50&after_unit_id=<cursor>`.
  Limit is 1–100; the exclusive cursor is 64 lowercase hexadecimal characters.
  Use `has_more` and `next_after_unit_id` to paginate. Units have kinds `upload`,
  `cold_chat` and `artifact_history`; listing them does not mean deletion occurred.
- `measurement_at`, `deadline_at` and `oldest_at` are Unix seconds in UTC.
  Show the notified deadline and a readable manual-review message, without
  exposing internal hold codes. Optional `billing.notice_held` indicates delayed
  notices and held expiry; retain that state without treating it as deletion.
  Members without the owner/admin role cannot
  load or display billing notices.
- `GET /v1/teams/{id}/billing` returns authoritative `balance_credits` and
  `version`. Use that version for balance mutations; `encrypted_balance` and
  older local ciphertext are advisory and cannot replace a valid numeric balance.
- Explain the independent 1 GiB Team allowance and 3 Team credits per started
  excess GiB per week, Sunday 03:00 UTC, and the approved four delivered warning
  rounds and protected subset expiry described above.
- Native canonical writer, typed v2 persistence acknowledgements and archive
  reader proof remain prerequisites for real archival pruning.

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

**Approved 2026-10-06:** charge new Team-owned storage once to the Team wallet
with its own separate 1 GiB allowance. Team warning recipients and safe warned
expiry are approved as described above; activation still requires focused proof.

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
writer's sole copy. The approved archive-unit selection and invoice closure behavior
are recorded below; adding archive bytes to the
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

## Approved expiry selection and invoice closure (2026-10-04)

The user approved `feature.billing@6`, fingerprint
`65deeacf5875ee2c4e77325bec72102b0980f3dda2311f3728709f03a456ac99`.
The exact review and explicit confirmation are recorded in session 2f80.

Freeze a fixed list of complete, independently removable personal units before
sending the first notice. Select oldest first, only enough to bring usage within
the 1 GiB allowance. All four delivered notices refer to this same list. Recheck
current usage at expiry and remove only the necessary subset of that list.
Uncertain references, active writers, shared/Team/Project data, sole recovery
copies and later paid storage remain protected. If no complete safe set reaches
the allowance, leave data intact.

After verified customer-reference removal and a complete current quote at or
below the allowance, waive only the unpaid invoices included in the warned
episode. Record `waived_on_expiry`, removed units, amounts and period identities;
make no credit debit and never report payment. Preserve later unnotified debt,
paid periods and unrelated charges. Incomplete removal or measurement never
waives an invoice. A new debt episode requires its own notices.

## Implementation and verification

Development release `7a6034a17b37c3866037f5fb16b85d50326df144` contains
authoritative bounded metering, immutable Sunday invoices,
full-charge ledger checks, legacy charge-overlap fences, exact provider delivery
receipts and retry holds, the fixed affected-unit API/web/email list, atomic safe
expiry and audited invoice closure. Production defaults remain conservative.

Initial deletion admission has explicit bounds of 100 selected complete units
and 2000 object references. Complex chat graphs or uncertain histories remain
protected. Rare expiry transactions briefly lock reference authorities, with a
bounded lock wait, to fence writers that do not yet share a resource-level
protocol. Replacing these coarse locks with comprehensive resource-level fences
is a scaling follow-up; correctness is preserved while that work remains open.

The final isolated source `47dbe933681ada991f4c06199206c03a2a918868`
passed both [logical billing/expiry](https://github.com/glowingkitty/OpenMates/actions/runs/37253722468)
and [legacy compatibility](https://github.com/glowingkitty/OpenMates/actions/runs/37253838672)
profiles, each with one expected case and zero skipped, failed or flaky cases.
The tests exercise actual disposable PostgreSQL and S3-compatible SeaweedFS,
authenticated browser settings, exact provider-delivery fixtures, logical
removal, tombstones, invoice closure and verified cleanup. The expiry objects
are two 112-byte AES-GCM ciphertexts with explicitly SIMULATED declared usage;
there are no large uploads, real emails, inference requests or real user data.
A disposable single-region fixture does not prove actual Hetzner failover.

The publication source reconciles current dev changes without altering the
accepted billing SQL/metering/expiry implementation. Corrected warning links
were checked by 45 real-template/context tests. The relevant publication Python
gate passed 137 cases. One unrelated workflow-digest retry test fails equally on
unchanged dev because its fixed epoch has aged out; its repeated execution was
excluded with a recorded reason, without modifying the test. Specification,
lint, translation generation and all locale validation gates passed.

The matching web deployment, additive schema operation `docker-4777bd38` and
coherent 17-service backend restart `docker-40849e0b` succeeded. A complete
read-only scan checked 44 owners in 17.588 seconds; all 44 legacy and logical
quotes were complete, with zero held quotes or lookup errors.

Coordinated activation `docker-323e9d0d` enabled
`STORAGE_LOGICAL_S3_BILLING_ENABLED=1` and `STORAGE_UNPAID_EXPIRY_ENABLED=1`
on the development API, core worker, task worker and scheduler. Warning links
use `WEBAPP_URL=https://app.dev.openmates.org`. Final readback verifies all four
targets running and all 11 billing/metering indexes present, valid and ready.
All six archive copy/read/prune flags remain off. Readiness checks made zero
charges, email sends or deletions; no real-user manual expiry was run. The
configured support sender is active, confirmed by read-only provider lookup.
Actual notification delivery uses the existing provider; no real test email was
sent. Production is unchanged and its billing defaults remain off.
Official-cloud archive copy and pruning now require the logical S3 billing flag
to be exactly `1`; otherwise they report `storage_billing_disabled` while
retained archive reads remain available. The first production rollout must
reconcile the meter, customer notices and legal terms, persist approved billing
flags through the registered installation, and then use the standard server
update. No financial default or Team price is changed by the migration guard.

Operational receipts are retained under session 2f80's ignored
`logs/storage-integration-2f80/billing-expiry-release/`, including
`accepted-verification.json`, `product-publication.json`,
`warning-link-readiness.json`, `dev-usage-readiness.json`,
`dev-flags-activation.json` and `dev-runtime-readiness.json`.

Team payer and allowance policy remains unanswered, so Team usage is unrated and
Team billing/expiry is disabled. Archive/pruning and the larger capacity benchmark
retain their separately recorded gates. The two real CLI/web canary turns have
already passed; this billing extension requires no additional real inference.
