# Deterministic security reporting

The approved contract is `specifications/architecture/security-reporting/` and the executable Plan is `docs/plans/deterministic-security-reporting/plan.yml`. Reporting stores observations in private host-local SQLite independently of remediation state. The delivery slice at `75d156ee67c1b271bade65d3c6cd7e3b9cfdcb69` remains unchanged.

## September 7 execution hold

Automatic OpenCode launches remain disabled. Workflow migration belongs to TASK-8338 (September 14 backlog). The coordinator owns every cron/systemd change. Do not install the old dependency scheduler or invoke scanner shell wrappers that launch agents.

`SECURITY_REPORTING_COLLECTION_ONLY=true` makes dependency helpers exit after deterministic collection, before remediation tracking, prompts or dispatch. The audit/red-team helpers instead ingest existing structured snapshots. The common launcher rejects this mode before filesystem/process effects. This mode also prevents critical delivery, even if the reporting marker otherwise enables email.

## Staged readiness

1. `verify_security_reporting.py --initialize-collection` creates private reporting state with collection enabled and scheduled monitoring disabled. It changes no scheduler and sends nothing. Repeat initialization preserves existing state.
2. Use only the coordinator-reviewed no-agent commands. `SECURITY_REPORTING_SLOT` may carry an actual original UTC scheduled slot across retries; do not assign a manual observation to a fictional scheduled slot. Disabled intervals are recorded with `ReportingStore.set_schedule`, which changes reporting expectations, not host schedules.
3. `verify_security_reporting.py --verify-adapters` runs isolated temporary-state tests and records hashes of the tested adapter sources. Source changes invalidate this evidence. This is not a live transport receipt.
4. `verify_security_reporting.py --prepare-test --output <private-directory>` freezes one labeled current-data test payload per reporting day and writes private HTML/text for review. Empty scan history is refused. No email is sent.
5. After existing explicit test-email authorization and coordinator admission, `verify_security_reporting.py --env dev --send-test` sends that frozen payload through the existing configured container transport. Replaying the same ID retains the original payload/hash. Queue acceptance or an ambiguous result never substitutes for provider acceptance.
6. The coordinator may separately install/enable reporting timers only after readiness verification and the scheduling hold is released. The timer proposal is daily 08:30 UTC with persistent catch-up and a 15-minute retry tick; no scanner schedules or OpenCode jobs are created by the reporting installer. `--check-cutover` checks exact units, runtime activity, durable accepted test receipt and source-bound adapter evidence.

Do not turn ordinary collection records into delivery receipts. Accepted test evidence must match the durable delivery ledger and immutable test payload and be no older than 36 hours. Unknown outcomes require reconciliation, never blind replay. Rollback disables only reporting timers and suppression, retaining history and receipts; it must not re-enable held scanner jobs.

## Audit snapshot input

Existing nightly JSON can include `details.security_reporting` containing `subject_commit`, `outcome`, and a list of normalized `findings`. The outer `ran_at` remains the observation date. Each finding includes a stable `vuln_id`, `ecosystem`, `package`, severity and optional explicit resolution/remediation metadata. The adapter copies only allowlisted fields and does not interpret summaries or transcripts. Identical dated snapshots are idempotent. Missing or legacy unstructured snapshots remain unavailable.

Scanner absence, dispatch completion and historical commit mentions never resolve ledger findings. Resolution requires the approved explicit complete-inventory or passed-check evidence; incomplete inventories retain open/unknown findings. OSV response cardinality, malformed entries, missing classification and enrichment failures remain visible, and the same advisory on distinct packages is preserved.

## Evidence

Run the focused pytest commands in the Plan offline first. `security-reporting-email-proof.spec.ts` renders the production templates with committed synthetic clean/findings/incomplete/critical fixtures. It captures the actual email HTML at phone and laptop dimensions and attaches MIME, HTML hashes, assertions and the spec-owned caption timeline. It creates no product page and sends no email. Dispatch through `scripts/tests.py` only after scoped dev deployment and coordinator admission, separately using `--proof-video-profile web-phone` and `web-laptop`.

The existing REST/CLI/SDK/Apple exclusions remain: no public endpoint, product CLI command, SDK method or native UI is introduced. If internal transport behavior changes later, real authenticated dev acceptance must precede proof dispatch. Keep full Plan completion pending until actual provider acceptance, reviewed/published captioned videos, deployed cutover evidence and the required user appearance confirmation exist.
