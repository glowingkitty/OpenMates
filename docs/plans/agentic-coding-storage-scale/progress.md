# Storage implementation progress

Snapshot: 2026-10-06. OpenMates Tasks owns work status and dependencies.

## Latest checkpoint — 2026-10-06

Public dev is `a5ad0627a99a105a75bcb45ea0abf4a0002351e4`, including Team
storage settlement and the Apple publication `25fdf752`. The storage foundation,
personal billing, two real CLI/web canaries (58 credits total), and automatic
schema-before-writer migration are already published. The verified storage
runtime is `a5ad0627`: personal and Team billing/expiry on and all
six archive copy/read/prune flags off. Production is unchanged.

All eight required Team GitHub gates passed: backend, web service, CLI, Python
SDK, component preview, actual PostgreSQL/S3/Vault logical billing, Team
creation and personal legacy compatibility. The exact ordered publication
unit gate passed 221 cases after three test-only fixture/import repairs.
The reviewed 62 source paths were published with normal Specification artifact
regeneration, preserving concurrent Apple and workflow changes. Required lint,
Specification and the 20-file/221-case pytest publication gate passed. Locked
cache recovery runs `37475279594` and `37479516969` authenticated every archive
and exported content file; create-only restoration preserved existing bytes and
the final selected-package audit found no missing or invalid entries. No dev
download or cache overwrite was needed. Coordinated additive Team setup
`docker-0572a336`, coherent 17-service restart `docker-c285502e`, and same-source
Team activation `docker-aca9f1f7` all completed. Read-only PostgreSQL catalog
verification found all three Team tables, five valid/ready indexes (three
unique), and generic tracking disabled. All 17 services are healthy with both
Team flags on, both personal flags preserved on and all six archive flags off.
Matching Vercel deployment `DgtXuzYZ5VHM5WZT1RptMzmMxmSu` succeeded. P-9's
backend/web/CLI/SDK dev rollout is complete; Apple work remains separately owned.
No real inference, charge, email or deletion is used in Team verification.

The previous P-7 pilot, run `37466140278` on exact source `52daf9e7`, passed the
browser encryption/reload case and the PostgreSQL/S3 archive probe. Processing
failed at a version callback: 46/60 rounds, 8/8 embeds, 4/8 versions and both
children completed. It recorded 272 fixture hits, 281 misses, 429 blocked
attempts and zero real inference calls. Cleanup passed. Hot-window PostgreSQL
and cold-read latency qualification were not reached; the archive probe does
not establish those results.

Actual client privacy and signed ledger probes prove two fixture defects:
complete version prompts exceed the synthetic 8000-character limit, and
privacy-transformed OLD/NEW diffs differ from raw seeded bytes. Narrow patch
`60597bda` preserves signed episode/actor/successor bindings and ordinary
request limits. It passed 77 focused cases; original source fails the four new
regression cases, and independent review closed. Other actual signed pre/post
scenario probes pass. The retained logs do not identify the predicates behind
54 preprocessing and 48 postprocessing rejections. Reviewed bounded sanitized
branch attribution and stream context cleanup are now in strict pilot
`37478841402`, frozen source `f299c3cb`, harness `b971d533`. That run failed at
revision 3 with 46/60 rounds, 8/8 embeds, 4/8 versions and 2/2 children; it
recorded 301 hits, 261 misses, 411 blocks and zero real calls. Browser and the
actual PostgreSQL/S3 archive probe passed; strict cleanup verified zero
containers/volumes and disposable account removal. No warm/cold page samples
were reached, so query/latency qualification remains open.

The complete fixed histogram identifies 48 decision-token bounds, 50 invalid
preprocessing states, two Project-read rejects, 67 unrecognized nonstream
branches, 14 unmatched no-tool branches, six version-read rejects, six version
ack rejects, 68 phase mismatches and 150 raw HTTP blocks. Exact inner causes of
the phase and HTTP rows were not retained; their counts are not attribution.
Actual separate message/Project privacy flows reproduce the legitimate
revision-3 read rejection: independently bound views of the same fixed raw
ledger have different placeholder IDs. A narrow fixture patch has old-fail/
new-pass proof for both actors and preserves invalid-read rejections. Actual
20k pilot requests also exceed the artificial 8k latest-request allowance, and
a signed post request of 31,643 bytes fits the unchanged 30k token budget at
15,690 tokens. Faithful bound fixture corrections and offline tokenizer setup
are being prepared; no retry or calibration has been submitted.
Calibration and the dedicated-host 1000-user-day/500-execution target have not run.

There is no evidence that workflow chat `01a10cd6…` caused this CI failure.
Its `971af2c5` publication changes only two workflow planning documents. Earlier
schema, admission, disk-budget and preparation-reuse commits linked to its
session `0e70` are present in the failed snapshots, but none touched the proven
fixture/privacy failure boundaries. The failed pilot requested no prepared
builds and passed source binding, archive probes and cleanup. Earlier unknown
rejection predicates remain unknown; timing does not establish causation.
The removed shared dependency cache has no established actor attribution.

Remaining gates: successful strict P-7
pilot and calibration, provisioned dedicated capacity runner, native typed
reader/recovery evidence, and signed release eligibility before real archival
pruning. The Apple canonical-writer publication explicitly keeps typed recovery
and archive-reader qualification separate. No skipped assertions or raised
timeouts count as a pass.

## Historical release status — 2026-10-05

The user explicitly resumed the remaining work on 2026-10-05: heavy-user
simulation, Team storage completion, and automatic migration for production and
self-hosted installations. Four workers share session 2f80: capacity harness and
proof (TASK-7213), archive/update automation (TASK-5795), Team storage and billing
(TASK-9893), and artifact payload/history correctness (TASK-5243). The parent owns
client compatibility enforcement, release evidence publication, Specifications
and this Plan. Worker patches are integrated; combined-source CI and the full capacity workload
remain required evidence.

Team payer/allowance policy and the D-9 refinement permitting S3-backed inactive
current artifact payloads have been asked and remain pending. Work independent
of those decisions continues. No new real inference is authorized or required;
production and real-data pruning remain behind their existing safety gates.


- Core development release
  `1e7b84c33ea33734ec53c85deda27b90aad3124d` is public and active. It includes
  the bounded storage, recovery, archive and artifact-version foundation.
  Existing high-write Directus tracking policies, filtered scalar message counts
  and nine nonunique access indexes remain live; historical audit rows remain.
- The coordinated schema operation succeeded in 361.35 seconds. Coordinated
  restart `docker-867b0631` then succeeded in 295.41 seconds with all 17 services
  running and healthy. Independent catalog readback found 17/17 recovery indexes
  present, unique where required, valid and ready. Archive copy/read/prune
  remains disabled; the personal billing rollout is recorded below.
- Matching Vercel web deployment `2w3u56hwciegHBEV9p8N4CjtvCut` succeeded.
  Production is unchanged.
- The exact backend gate passed 1,408 tests across the inferred 120 files.
  Focused recovery CI `33e0f616` passed both selected cases, with one synthetic
  fixture setup retry. This is scoped release evidence, not a full-scale proof.
- Full P-7 is deferred and remains the first-real-prune gate. Native typed
  readers/writers and cross-client concurrency remain unverified. Team payer
  policy remains unanswered and Team billing/expiry remains off. All six
  archive copy/read/prune flags remain off.
- The user is the only Apple tester and waived development legacy compatibility.
  This clears the dev legacy-client hold for the published core. Native ordinary
  canonical writers must still implement capability-bound strict digest/source,
  request/count receipts and head-before-keys, including Watch. Typed v2 must be
  advertised only when its complete reader/persist/ACK flow is wired. Native
  typed readers remain a pruning gate.
- Missing-version recovery guard `9f42f3f23c5550c1166d0fdab792c3b113c0c82d`
  is public and active. Operation `docker-2ca18e8b` restarted 16 API/worker
  services in 84.36 seconds; all are healthy and CMS schema was unchanged.
  Exact-source isolated CI `37233294260` passed the bounded version-404 case
  1/1 in 0.50 seconds; the focused local route suite passed 15/15.
- Saved-reference restoration `8addcd723385c67660d77623f167f8d7408dd85d`
  is now public and active. It repairs the unintended removal of reference
  availability and authorized cross-chat reads in the follow-up recovery commit,
  while preserving the missing-version 404 fix. All 21 route tests passed locally
  and in isolated CI run `37239918530` at exact source `899f9575676d02282df460e77f0294aef5d145ba`.
  Coordinated restart `docker-0557ff83` completed with all API/worker services healthy.
- Personal billing release `7a6034a17b37c3866037f5fb16b85d50326df144`
  is published on dev. It adds authoritative logical usage, fixed weekly
  invoices, confirmed-delivery warnings, protected expiry of only enough warned
  units, and write-off of only the warned unpaid episode after verified removal
  restores the free allowance. Matching settings, emails, privacy and terms are
  published. The user approved `feature.billing@6` and its invoice-closure policy.
- Both isolated billing profiles passed on source
  `47dbe933681ada991f4c06199206c03a2a918868`, with zero retries or flaky cases:
  [logical usage and expiry](https://github.com/glowingkitty/OpenMates/actions/runs/37253722468)
  and [legacy billing compatibility](https://github.com/glowingkitty/OpenMates/actions/runs/37253838672).
  They use actual disposable PostgreSQL and S3-compatible SeaweedFS, two 112-byte
  AES-GCM objects and explicitly simulated declared usage. They send no real
  inference or email requests and touch no real user data. Actual Hetzner
  multi-region failover is not established by these tests.
- Reconciliation with current dev preserved other chats' settings and translation
  changes. Billing SQL/metering/expiry behavior matches the accepted CI source.
  The corrected real warning templates and contexts passed 45 local tests. The
  publication Python gate passed 137 cases; the unrelated workflow-digest retry
  case also fails on unchanged dev because its fixed timestamp has aged out.
  Its repeated execution was excluded with a recorded reason, without changing
  that test. Specification, lint, translation and locale gates passed.
- Matching billing web deployment succeeded. Additive schema setup
  `docker-4777bd38` and coherent 17-service restart `docker-40849e0b` succeeded.
  The complete read-only scan checked 44 owners in 17.588 seconds: 44 complete
  legacy quotes, 44 complete logical quotes, zero held quotes or lookup errors.
- Coordinated development activation `docker-323e9d0d` enabled personal logical
  S3 billing and protected unpaid expiry on the API and all three billing worker
  targets. Warning links use `https://app.dev.openmates.org`. Final readback
  confirms the targets are running, all 11 billing/metering indexes are present,
  valid and ready, and all six archive copy/read/prune flags remain off. The
  readiness checks made zero charges, email sends or deletions. Read-only provider
  lookup confirmed the configured support sender is active; delivery behavior is
  tested with provider fixtures, not real emails. Production is unchanged.
- Exactly two real user turns completed, once each and without inference retry:
  CLI used 25 credits and web used 33, 58 total. CLI SQL and a fresh process
  verify exactly one user/assistant pair, the exact saved `add_one` code embed,
  one bounded v1 snapshot row, an acknowledged sealed diff, one canonical v1
  row and no duplicate charge. Web SQL and fresh CLI read verify one
  user/assistant pair; a read-only browser renders the exact stored answer with
  synced status. The first browser harness compared the CLI JSON database row
  `id` with the DOM `clientMessageId`; the CLI deliberately exposes `id` and
  `clientMessageId` separately, so this was a harness error rather than a product
  identity defect. Corrected receipt
  `final-live-smoke-preparation/readback-verified/browser-receipt.json` passed at
  20:57:23 UTC with the exact canonical client message ID, one user and one
  assistant, synced status, and an identical rendered answer hash after reload
  and after login from a second empty browser context. It used zero new inference.
  The initial live-browser ACK capture timeout remains recorded; stronger
  canonical and fresh-device recovery evidence passed. Across both canaries there
  were exactly two sends, two charges (25 + 33 = 58 credits) and no retries.

## Implemented foundation and remaining gates

| Area | Implemented on dev | Remaining work |
| --- | --- | --- |
| Redis | Three recent main chats; separate bounded active children, embeds and pending writes | Target-load measurements |
| PostgreSQL/S3 | Bounded queries, indexed pages, encrypted payloads, copy/verify/fences, initial 24-hour buffer | Native readers, full P-7 and first real-data archive/prune rollout |
| Unattended output | Durable sealed messages, child results, embeds/diffs and checkpoints; failed saves pause work; two live canaries passed | Native writers/readers and cross-client concurrency |
| Artifact versions | Paginated metadata, S3 history, client snapshots and bounded patches | Complete processing benchmark and account-wide growth of current-head SQL payloads |
| Directus | High-write policies and checkpoint/archive/recovery policies active; intentional product history preserved | Historical audit cleanup and any narrower routine user-state writer change require their own scope |
| Personal billing | Metering, fixed invoices, four delivered warnings, protected expiry, warned-only write-off and matching notices active on dev | Production rollout is separate; coarse expiry locks need a future scaling review |
| Team billing | Separate allowance, wallet settlement, confirmed recipient rounds and safe expiry implemented; all eight CI gates passed | Publication cache repair and schema-before-writer dev activation |
| Legal | Matching storage, encryption, deletion, costs and conditional rollout copy published | Production release remains separate |

## Earlier release and verification history

## Published to dev

The entries in this section are historical checkpoints; the current active state above supersedes their release wording.

Specification, Plan, Apple handoff, synthetic crypto fixture and scoped CI tooling.
Latest trusted tooling: `4c0cf8b1b5e28bae3e5121a22f6179131a2ae1c8`.
The Docs worker profile (`03ca9f0`) and fresh-epoch PostgreSQL claim-probe
runner (`0bea8af`) are published. These tooling deployments do not activate
the main storage API or pruning.
The five-collection Directus policy and read-only inventory are published as
`a46e480f7acbb4ac2c571c74fb586295fb974db6`; metadata-only coordinated activation
was published as `046e28be58d3ba80d7dfc5912ee33321362e4bd6` and completed on dev
under operation `docker-0f33873f`. Independent SQL readback confirms all five
policies. It ran no schema/data migrations or historical audit cleanup.
The main storage/API implementation is still in private candidates. No real-user
migration, pruning, new S3 charge or protected unpaid-data expiration is active.

## Retrieved evidence

- Source 328: actual disposable PostgreSQL/S3 probe passed, 20 source messages,
  one verified page, 20 pruned messages, late-write/recovery/reference/race fences.
- Source 0ab9: four selected unattended-recovery browser cases passed.
- Source 0b81: selected UI unit run passed 24/24 cases in two selected files. Later
  browser and pilot runs are diagnostic only: their actual workflow head differs
  from the reported trusted harness, so they are not accepted source-bound proof.
  Observations identify the first-version failure at readback, a missing code card
  after reload and absent dropped-preflight replay. The next private source adds
  content-free version mismatch diagnostics and retry after a current-connection
  zero-chat cache response. It clears that evidence on disconnect/logout and
  preserves exact canonical ciphertext through status-only updates. Focused
  reconnect tests passed 5/5; the updated browser boundary cases are still pending.
- Source 998c: Directus integration failed at receipt validation after startup;
  no measured tracking/storage improvement is claimed from that run.
- Source 1f755, trusted harness d0dee: the corrected single-attempt Directus run
  failed while reading its private receipt. The host test and artifact collector
  could not read the container-owned mode-0600 file. The probe subprocess and
  cleanup returned successfully, but the receipt assertions were not verified.
  Preserve private permissions and fix only the guarded receipt's ownership;
  no tracking or write-overhead pass is claimed yet.
- Source e24c, trusted harness 83ca: actual Directus test passed 1/1 with zero
  retries, matching workflow head, and coordinator-verified disposable cleanup.
  Private receipt SHA-256
  `0e01ddad1297a4b35562665ad432531e2306c25a692ef7e5ff0b74434a9caa9a`
  confirms zero new generic audit rows for all five reviewed collections. A
  temporary disposable `all` comparison produced 20 audit rows and 13,638
  serialized JSON UTF-8 bytes. These are small synthetic call measurements,
  not sustained throughput or PostgreSQL relation-size savings. The policies
  and fixture rows were restored/cleaned; historical audit data was untouched.
  Published candidate 06fae differs only by two test-wrapper lint repairs,
  retaining all fixture and cleanup assertions; product policy blobs match.
- The next merged source passed 31 schema-setup unit cases and two version-stage
  diagnostics. The new checkpoint summary collection also has a reviewed null
  tracking policy; its canonical summary and coverage records remain intact.
  Archive and recovery collections use explicit policies and transactional SQL.
  Other collection policies, including financial records, remain unchanged.
- The metadata-only activation mode passed 80 focused setup/coordinator tests,
  was published, and completed on dev without running full setup migrations.
  Fresh read-only inventory: database 7,505,277,487 bytes; `directus_revisions`
  5,190,279,168 bytes; `directus_activity` 573,308,928 bytes (about 77% combined).
  These include relation indexes/TOAST; they are not solely agentic user data.
  Approximate catalog row counts are 1,957,273 revisions and 3,058,540 activities.
  Per-collection `pg_column_size(data + delta)` identifies `directus_users` as the
  largest historical snapshot source (1,556,150,373 payload bytes). Its policy
  remains unchanged. The writer/reader review found that routine presence,
  device, active-chat and storage-usage updates share the user collection with
  security/admin changes. No product reader of generic user revisions was found;
  registration statistics still read create activity. Any narrower routine-state
  writer change must preserve those audit paths and dedicated financial records.
  Existing records were retained; stopping new snapshots does not
  immediately shrink database files. The private aggregate report is retained
  in session evidence; no account payloads were read or emitted.
- Source 07e1, trusted harness 046e: selected UI checks formally passed 32/32
  tests across four selected files (the prior two plus reconnect and recovery
  privacy copy). The receipt verifies source/head identity. Signed browser
  bundle failed two cases on both initial and retry attempts: saved-code wrapper
  absent after reload, and interrupted-preflight replay observing only one
  request instead of at least two. Its v31→v32 migration case passed first
  attempt. Source/head match and disposable cleanup were verified. These are
  reproducible failures, not flaky passes; bounded IDB/WS flags are being
  retrieved for targeted debugging. The source-bound processing pilot failed at exact
  artifact-version readback: `revision_matches=true`, `content_matches=false`
  for revision 1. It completed 16/60 rounds and 8/8 embeds, but 0/8 versions and
  no child/cold-page workload. Its signed browser turn passed first attempt;
  actual PostgreSQL/S3 probe passed with 20 source messages, 20 pruned and one
  verified page, including its fence/Team/Project/legacy JSON checks. The
  coordinator verified cleanup and retained bounded private diagnostics after
  teardown. Real provider calls were zero. This is a pilot failure, not a capacity
  or latency pass. Exact content equality remains required; the first-version
  content path is being investigated before any rerun.
- Latest legal draft: five prepared rendered-copy cases and three privacy-release
  cases passed locally; the three selected recovery privacy cases also passed CI.
  Locale JSON/fallback checks passed for all 21 locales.
- The accepted 1000-heavy-user/500-active-execution capacity target has not run.
  The current CI worker profile cannot admit 500 active prefork tasks.

## Targeted release fixes in progress

- The exact version-content failure was traced to client privacy placeholders in
  the synthetic fixture, not a weakened reconstruction assertion. The fix uses
  actual client redaction/restoration, validates the completed Project operation
  and path, and caps completion decoding at 512 KiB. Four focused regressions
  passed locally; the isolated processing pilot rerun remains pending.
- Interrupted first-send recovery lost its draft because Phase 2 treated an
  uncommitted chat's absence as deletion. The patch distinguishes explicit
  deletion from inferred absence and guards draft deletion within one IndexedDB
  transaction. A durable, content-free PostgreSQL chat-deletion fence rejects
  recreation after Redis tombstones expire. Chat DELETE requires its exact
  committed receipt before cleanup; rewind uses a separate operation. Historical
  deletions that predate this fence cannot be safely backfilled after their rows
  are gone. This cutover limitation requires review before activation.
- The first integrated local checks passed 26 Python tests, 78 transaction tests,
  and 41 schema/retention tests. The subsequent producer integration passed 87
  transaction tests and 50 recovery/schema checks, plus 16 producer-admission and
  27 embed-publication tests. These focused suites overlap; counts are not a
  unique overall-test total. The transaction fake serializes all calls, so these are
  not proof of real PostgreSQL advisory-lock concurrency. The authored cross-device
  deletion browser regression has not run.
- The saved-code rendering failure was traced to reparsing only the first text
  node of an already parsed multi-node TipTap document. The narrow renderer repair passed its first three isolated component cases.
  Screenshot review then found an invalid code-preview fixture, so the corrected
  fixture now checks visible code and footer containment. Exact-source component
  rerun 720a232 failed footer containment on both initial and retry attempts
  (the actual code text assertion passed; two other cases passed). Diagnostic source 8db7333 confirmed that the same card fits outside the read-only
  message. Inherited `white-space: pre-wrap` preserves template whitespace and
  shifts its 200-pixel layout by 24 pixels. The scoped `white-space: normal` fix
  preserves explicit code whitespace. Component source b9b9319 passed 3/3 first-attempt cases in isolated GitHub CI
  run 37178947965, with matching source/harness receipts. Screenshot review confirms
  visible code and contained footer. The saved-code browser rerun is now unblocked.
- Detached producer repair is now being implemented: register a durable task and
  subject intent before broker dispatch, verify it before provider/billing work,
  seal before finished cache/publication, and preserve immutable saved bytes on
  retry. Late output after root completion is limited to previously admitted
  producers. No new execution mode or legacy SDK inference restriction is used.

- Direct-skill canonical completion now has a focused patch that sends the
  head/key durability receipts before attempting completion, preventing an ACK
  deadlock while wrappers are pending. A bounded 100-row maintenance cursor
  retries incomplete work. Thirty-one integrated focused receipt/deletion tests passed; actual product
  verification remains pending.
- A disposable actual-PostgreSQL deletion/producer race probe and a real detached
  worker test with deterministic providers are being added. Existing fake
  transaction and mock-stream checks do not cover these concurrency boundaries.
  Source review found that the Team actor/deleter account locks differ. The patch
  now takes the global chat lock before mutable row locks across producer writes
  and deletion. Actual two-actor PostgreSQL scenarios are authored but have not run.
  The real local Docs worker scenario covers broker admission, seal-before-publication,
  loss of the Redis embed copy, typed discovery and canonical client ACK. Its two
  retry-boundary unit cases need Celery in CI; local dependency skips are not passes.
- Draft privacy copy now discloses content-free anti-restoration deletion markers
  and their current lack of automatic expiry, including after account deletion.
  Four rendered-copy tests passed. The marker retention/minimization review is a
  follow-up; no real-user historical revision cleanup has been performed.

## Deployment and normal-chat smoke

After required fixes and client compatibility, publish the scoped product changes
and activate the explicit dev runtime under its coordinator lease. The user has
authorized two live chat turns total: one CLI and one web. Verify real streaming,
completion, exactly one canonical user/assistant pair, persisted content, reload
or reopen, and matching error logs. Record downstream provider calls and credits.
These smoke checks have not run. The bulk architecture/load workload remains
strictly zero-inference; the two live turns do not prove capacity or migration.

## Apple coordination

The separate Mac chat owns Swift and native verification. In its own clean dev
checkout, pull with `git pull --ff-only origin dev` and follow
[apple-handoff.md](apple-handoff.md). The published contract is available now;
pull the actual backend implementation once its deployment commit is announced.
Strict new write handlers must wait for coordinated supported-client compatibility.
The exact 07e1 source audit found two missing compatibility checks: current Apple
clients send wrappers before the canonical embed head and understand only v1
final-text recovery. Recovery epoch/protocol 1 does not identify the new clients.
The first capability-guard scratch passed 14 policy-function unit cases, but
review rejected it for integration: it over-blocked existing SDK v1 final-text
recovery, failed to propagate capability proof durably to children/continuations,
and advertised contracts before every recovery receipt reader checked them.
Its browser case only checked a URL; it did not prove zero database/lease writes.
The follow-up audit confirmed that existing protocol-1 SDK/native recovery keys
can seal v2 outputs. A capable same-owner device derives the private key from the
synced root chat key; v1 final-job persistence leaves typed pending records
intact. The execution-mode/tool-restriction proposal is therefore superseded.
The revised patch preserves SDK admission and v1 jobs, gates typed recovery
consumption and canonical embed writes, and tightens client receipts before
advertising support. It still needs actual no-mutation and exact-save E2E proof.
The audit also found detached async app workers that omit the recovery context;
their finished embeds can miss typed sealing. The propagation/failure-fence
patches are implemented in isolated scratch and are being integrated with
authoritative legacy and ephemeral request admission before activation.
The Mac handoff names both intended capabilities and the native proof required
before advertising them. Existing pending outputs must survive unsupported
reconnects. Main API activation remains held.

## Additional execution correctness refinements

- Epoch-0 queued requests need a bounded non-destructive Redis prefix lease, exact
  broker handoff acknowledgement and durable pre-provider batch claim. Redis queue
  loss remains best-effort legacy behavior; this is not typed durable transcript
  recovery. Admission or broker failure retains the batch and becomes visible to
  the client. A retried batch keeps its exact identity and never repeats the parent
  provider execution. These changes are in progress.
- Permanent, indexed, content-free batch claim markers prevent replay after old
  lifecycle JSON tombstones are pruned. This adds small warm metadata rows, not
  message or artifact payloads. Future compaction requires an authoritative account
  or chat deletion fence that still rejects recreation.
- Standalone REST generators have no canonical chat embed or master wrapper. Their
  encrypted asset ledger already persists files, but the new direct intent would
  otherwise remain RUNNING. Completion must follow successful Celery result storage
  and verify the exact indexed encrypted assets and current authority. A crash after
  paid dispatch without immutable proof remains held, with no automatic regeneration.
  Existing task-result backend TTL is not a durable copy of prompt/result metadata;
  uploaded assets remain independently discoverable and downloadable.
- The existing users writer audit found `last_opened` after signup as a possible
  narrow future tracking optimization. Security, device, signup, balance and storage
  billing fields share the collection; its collection policy is unchanged.

- The detached Docs CI harness is published on dev in `03ca9f0` (four tool paths,
  ten local coordinator/profile tests). This does not activate the storage API.
- Standalone asset completion is integrated after Celery stores a successful
  finished result. Its integrated transaction suite passed 102/102. The asset-only
  periodic completion proposal was rejected because it could race finished
  publication. A callback failure leaves the intent held; result-aware recovery is
  being evaluated without storing plaintext prompts or rerunning providers.
- Weekly billing remains in the separate staged materialized source. The frozen
  main storage candidates do not contain its metering extension, immutable period
  schema or fourth notice. Reference-safe unpaid expiry is still unimplemented;
  Team payer, exact billing contract and invoice closure decisions remain open.
  Expanded charging and expiry remain disabled.

## Current integration boundary

- Permanent ordinary/batch execution claims are indexed, content-free rows,
  separate from bounded legacy lifecycle records. Transaction unit checks pass
  93/93 plus 14/14 metadata transaction cases. The integrated full-dependency Python selection passes 121 cases;
  two Docs-specific cases remain skipped locally and require full CI dependencies. The actual PostgreSQL concurrent-claim probe is authored but has not
  run on this integrated source. Canonical message lookup uses the production
  `client_message_id`, which differs from the database row UUID.
- Canonical persistence acknowledgement requires the exact stored assistant
  ciphertext and current chat/owner identity before closing a legacy claim.
- Completed legacy queue handoff exposed a follower-liveness issue after a
  lost prefix acknowledgement. The prepared repair uses Vault encryption for paused and completion
  contexts, existing byte budgets and a bounded 600-second TTL. Integrated
  verification and actual broker/browser proof remain pending.
  Completed work must never be sent to the provider again.
- Standalone asset producers close only after Celery has stored a successful
  result and the exact actor-owned encrypted asset ledger is verified. If the
  completion callback fails, the intent remains RUNNING for operator
  reconciliation. An asset row alone does not authorize provider replay or
  prove successful result publication.
- The main candidate is not deployed. Updated real PostgreSQL/S3, Docs broker,
  browser and processing pilot runs remain release gates. Zero paid inference
  calls have been made for this work; the two authorized live smoke turns
  remain pending after coordinated main deployment.

### Full capacity profile prerequisite

The target profile currently requests 500 active executions but silently caps
its one AI worker at four prefork slots. That is a configuration cap, not a
measured hardware limit. Its 1536 MiB memory limit and 512 PID limit cannot
safely be increased to 500 slots without measured sizing. A separate isolated
profile needs aggregate measured worker slots, memory/disk/timeout admission
checks and independent server-active interval evidence. The current verifier
also glob-loads about 1.51 million per-task receipt files at full volume;
streaming or sharded aggregation is required. The 60-minute workflow cannot
prove the separately required paced 24-hour sustained run. No target hardware
was provisioned and no full-scale run has passed. These are P-7 work items,
not grounds to relax the approved target or enable pruning.

The merged follower repair passed 76 integrated local cases, including queue,
cache-budget, persistence and recovery service checks. Review found that later
normal cache writes still apply separate main/child pools rather than the
approved combined 64 MiB user limit. The focused aggregate guard is now merged: normal writes and child registration
count both pools against the same 64 MiB total. Refused admission plans no
eviction, preserving existing active and pending contexts. Its helper selection
passed 18 cases; final integrated queue/cache verification passed 36/36 cases.
The complete candidate also passed metadata checks for 109 changed test files
and Python syntax checks for 168 files. The approved storage Specification
fingerprint remains unchanged; actual product CI remains pending.

- Prepared truthful privacy-copy correction in isolated scratch for historical Directus
  revisions and activity after chat/account deletion. The active English/German
  text and English fallbacks distinguish those snapshots from content-free
  deletion fences and remove the unenforced two-year generic-history promise.
  No historical rows were changed. A scoped revision/activity redaction or purge
  implementation remains outstanding and must preserve dedicated security,
  financial and registration evidence.

### Latest full-dependency CI findings

- Source 4370a09 focused worker CI ran 11 cases: 10 passed, one failed because
  the new Docs fixture omitted its disposable internal HMAC key.
- Source 9850245 supplied that key. One Docs case passed; the sealed-redelivery
  case exposed an unconditional Celery FAILURE update that can overwrite an
  earlier SUCCESS. The focused repair ignores the exact SEALED hold without
  reading or writing the result backend and never invents SUCCESS after expiry.
  Three full-dependency local regressions passed; corrected CI remains pending.
- Historical generic Directus snapshots are not removed by current canonical
  chat/account deletion and have no enforced automatic expiry. Truthful copy
  now discloses that separately from content-free deletion fences; five rendered
  cases and 21-locale checks passed in its scratch. Scoped historical snapshot
  redaction/purge remains open and no bulk cleanup was performed.

The four source-4370 browser/processing jobs share a pre-browser legacy-probe
fixture failure at user creation. All four retrieved, source-bound reports
contain no browser results and verify disposable cleanup, so no browser,
concurrency or latency pass is claimed. The repaired actor fixture uses the
production synthetic-login shape, with 23 focused local cases passing. The exact
original HTTP rejection is unknown because its response was not retained.
A narrow harness repair will preserve only whitelisted status/code/field
diagnostics and validate the probe's canonical-presence count. A bounded actual
PostgreSQL proof is required before the remaining bundle rerun.

The strict legacy-probe receipt/diagnostic tooling repair is published to dev in
`4c0cf8b`. The integrated fixture, coordinator and sealed-redelivery selection
passed 61/61 local checks with full disposable dependencies. Four changed test
files passed Specification metadata validation; six changed Python files compile.
These local checks do not prove real SQL concurrency. A single isolated
PostgreSQL/processing pilot precedes the remaining browser bundle rerun.

Candidate `047ff025` is privately published against trusted dev `4c0cf8b`.
Its PostgreSQL/processing pilot (`8b41d0b2`) and focused three-case worker retry
check (`854e06cf`) are acknowledged queued. Neither has a result yet. The
full-target profile/admission and streaming-receipt patch is a separate P-7
work item in progress; no full-target hardware or workload has been launched.

Retrieved source-bound worker result `854e06cf`, run37185706240: all three
Docs retry cases passed, no skips. Source047ff025 and trusted harness4c0cf8b
match. This fixes sealed redelivery without regenerating output or overwriting
Celery success; the actual PostgreSQL/processing pilot still has no result.

### Subsequent release-gate work

- Apple contract handoff is published on dev in `e2cd90a659ee01d3c02969fc9b0b9d7964e6aba7`;
  the Mac chat can pull it before backend activation. It includes exact receipt
  fields, capability negotiation, preflight journal and zero-inference native cases.
- The explicit500-slot target profile and sharded/streamed receipt verifier are
  prepared in separate integration source. All99 focused profile/environment/runner
  unit cases pass. Dedicated self-hosted hardware, same-source measured calibration
  and sufficiently long jobs remain external prerequisites; no target was launched.
- Candidate047ff025 actual PostgreSQL probe passed actor creation and reached task
  retirement, then failed because the fixture requested removal before completion
  and canonical persistence proof. Source/harness match and disposable cleanup
  were verified. The revised probe preserves production holds, verifies exact
  ciphertext ACK plus worker completion, then ages only the disposable completed
  tombstone before proving permanent replay exclusion. Its27 unit cases pass;
  actual PostgreSQL rerun remains pending. No browser or S3 pass is claimed.
- Cache review found a15-second per-user admission lease can expire during slow
  work. Token-fenced commits and renewal are being added; a renewal-only solution
  does not exclude a stale owner from committing after another writer.
- A separate public-policy patch corrects only currently misleading historical
  database retention statements without announcing inactive archive/billing behavior.
  Its focused browser coverage is being prepared before publication.

### Publication priority and final cache integration

The user requested focus on publishing the database update, with important
correctness tests and debugging. The large target benchmark and automated
calibration refinement are deferred and do not block safe additive publication.
No full-target scalability claim is made. Initial archival reads/pruning and
expanded storage billing stay disabled pending their activation gates.

The renewed, token-fenced cache admission repair and queued-state integration
passed33/33 focused local cases. Tests cover lease expiry/reacquisition, internal
renewal failure without cancelling the caller, preserved external cancellation,
and legacy queued handoff behavior. The actual legacy SQL completion probe's
27 unit cases pass; its corrected actual PostgreSQL/S3 pilot is next.

The public-only historical-retention policy candidate d7a86534 has a single
logged-out browser check queued. Its locale diff contains only privacy values.
Dependency classification is published in be5d1baa; no provider or mail access
is required. This separate legal correction does not block the database pilot.

A focused index-only deployment slice is being prepared: nine nonunique
PostgreSQL access paths. Independent review confirms all indexed columns exist
in the public schema and that archive migrations install active write triggers,
so those migrations and new client-dependent API handlers are excluded from this
first database deployment. The coordinated setup mode will apply only the exact
query SQL with bounded lock/statement waits; independent readback will check all
index definitions plus ready/valid flags. The read-only dev baseline found1of9
indexes already present. No SQL changes have been applied yet.

### First query-index database deployment is live

- Published six-file isolated index setup in `ecb865c34d3748017eae435f657931254a908595`,
  then the missing dev readonly SQL mount in `d84085c99f5ea469dcf32e8e6da0233d22fe9c41`.
- The first coordinated run failed before SQL connection because that dev mount
  was absent. Corrected run `docker-b13171bf` completed on development `cms-setup`.
  Only the exact nine-index transaction and index readback ran, with5s lock and
  5min statement timeouts. No user content, schema/data migration, archive trigger,
  API/client contract or billing activation was changed.
- Independent development `cms-database` readback confirms all nine indexes are
  nonunique, ready and valid, and every canonical definition matches the reviewed
  order/directions and warm-chat predicate. Combined index relations total
  29,843,456 bytes; one index existed before this operation. This is not a measured
  request-speed or full-capacity result. API health is healthy; no API restart ran.
- SQL SHA256 `8b2fec4a6cdd0670ffe2b2b3bb3c6a35ef15d9cc074b91534da59543dc34e119`
  equals the frozen047 and1212 integration SQL. Focused setup/coordinator safety
  checks passed14/14; deployment's existing setup-test gate also passed.
- Public privacy correction is published in `88ab79eed0ccae09110480aa024b60a54204d136`.
  Isolated run37189938160 passed its logged-out browser case1/1, zero skips/flaky,
  matching sourced7a86534 and harnessbe5d1baa with verified disposable cleanup.
- Broader database/API archive, recovery and version changes remain private while
  the corrected1212 PostgreSQL/S3 pilot runs and supported-client gates remain open.
  The full target benchmark/calibration refinement is deferred under the user's
  publication priority. Real-data archive/prune and expanded storage billing remain
  off. The two authorized real-inference CLI/web turns remain unused.

Commit metadata note: the ecb865c commit's assertion trailer used an invalid
assertion name; it is not evidence of bounded-tail conformance. The subsequent
correct trailer is `storage.warm.bounded-chat-tail`. Index application/readback
above proves the additive access paths only; broader behavior still needs its
source-bound runtime proof.

### Latest database and processing result

Run37193018171, source `3e283ddc`, harness `d84085c9`: the actual PostgreSQL/S3
probe passed all recorded source-mutation, late-arrival, pending-recovery,
concurrent-prune, reader-verification, deletion, Team and Project fences. It copied
one page from20 synthetic messages and pruned only those disposable messages.
The signed encrypted browser turn passed1/1, zero skips/flaky. The processing
workload failed its child-completion assertion after20 rounds and2 correct versions;
no throughput, cold-read latency or target-load pass is claimed. Real provider
requests were zero and disposable cleanup was verified. The two bounded private
failure rows were retrieved with source/run provenance and restrictive permissions.

Candidate `a9f26651` reconciles the main implementation with already-public index
setup and privacy changes. Runtime storage code is identical to `3e283ddc`; its
setup merge preserves the bounded index-only mode (4 focused checks), and its
legal merge preserves historical-record/60-day backup disclosure while removing
inactive archive/unpaid-deletion claims (8 rendered checks,21 locales). It remains
private. Further publication is currently guarded because another task has
uncommitted tracked changes in the canonical checkout. Those changes were not
altered. Supported Apple/client compatibility also remains required for API
activation; the Mac chat has been asked for its commit, native proof and policy
for older installed clients.

The child-round investigation confirmed the synthetic tool configuration is
correct. The four-tool log tail is the parent continuation after its child
completed, where hiding further child creation is intentional. Only the CLI
child lifecycle routing and its unrealistic root-ID fixture were changed; no
preprocessor, main processor, capacity fixture or benchmark was changed. The
minimal patch is `d7293127`, two files, with26 focused tests passing and the two
changed fixtures failing against the baseline. The Apple handoff now requests
the equivalent parent-scoped synthetic event test. The remaining focused browser
bundle is queued on reconciled source `a9f26651`; it covers saved message/embed
bundles, recovery/deletion, detached producer durability and accurate legal copy.

The reconciled legal browser gate passed1/1 in run37195535787, source
`a9f26651`, harness `d84085c9`, with zero skips/flaky and verified disposable
cleanup. Three remaining critical browser selectors and the corrected small
processing pilot remain pending. The repaired pilot source is `f0be743e`; it
adds only the reviewed two-file CLI child-event fix and current progress/handoff
documentation to `a9f26651`. Backend/database code is unchanged.

Critical browser results on `a9f26651` exposed release blockers. Recovery
run37195542585 passed4/6 cases; failures concern a legacy test's uncorrelated
capability-error total and send acceptance in the another-device deletion case.
Bundle run37195540269 passed1/3 without retry; the upgrade fixture passed only
on retry after a blocked IndexedDB delete, and immutable preflight digest
comparison failed after reload. Both receipts match the reviewed source and
trusted harness `d84085c9`, with verified cleanup. Focused owners are repairing
only these failures, preserving canonical, replay and deletion assertions; no
new optional benchmark or inference run was requested. The successful f0
preparation event is not a completed processing-pilot result.

The narrow browser repairs are ready: immutable saved preflights no longer gain
a fresh outer tracing field on replay; the upgrade fixture waits for its actual
IndexedDB deletion; recovery denials are correlated to six exact request IDs;
the lost-ACK deletion case proves its dropped ACK and exact journal before closing
the sending page. Docs initializes only core services and required S3, avoiding
an unrelated Invoice Ninja configuration failure; its focused regression passed
1/1. These patches preserve producer authorization, sealing, replay identity and
delete fencing. The next run covers only the three previously failed browser
selectors. No full benchmark, new real inference or storage activation is added.

Repaired release candidate `247b9dea` (tree `f3ee44c0`, reviewed patch
`b8c35adc`) is queued for exactly the three previously failed browser selectors.
It changes eight paths from `f0be743e`: two minimal product fixes, their
regression fixtures/unit case, current plan notes and regenerated test references.
The nine-index SQL, storage-lifecycle Specification fingerprints and coverage
counts are unchanged. The legal browser result and actual PostgreSQL/S3 safety
probe are reused with their original source provenance.

Small processing run37196327970 on `f0be743e`, trusted harness `d84085c9`,
confirmed both expected child completions (2/2) and passed its signed encrypted
browser turn1/1, zero skips/flaky. The processing workload then stopped at
`version_callback_count` in the version adapter after30/60 rounds,8/8 embeds
and2/8 versions. Cleanup was verified and real provider calls were zero. The
version owner is inspecting only this exact failure from existing evidence;
no additional workload or inference request has been scheduled. The pilot is
not a capacity pass. Candidate `247b9dea` remains queued only for the three
previously failed critical browser selectors.

The exact version-pilot blocker is synthetic continuation provenance: a Project
update requires a read followed by another model step; the server-created step
loses the already verified signed replay context after the original prompt marker
is stripped. CI has no live credentials, and the replay stopped before an update
commit. Zero callbacks are inferred from source/logs, not measured by the generic
private row. The owner is adding a server-only, scoped, expiring HMAC continuation
claim while retaining client-field rejection and fail-before-provider-dispatch.
This is P-7 harness work. Per the approved Plan, P-7 remains required before
real-data pruning; it does not add a core publication gate. Core publication
uses the critical storage/browser proof, supported-client compatibility and
coordinator checkout guard. No new full replay or benchmark is scheduled.

Saved-bundle run37198323212 on `247b9dea`, harness `d84085c9`, passed3/3:
v31-to-v32 journal indexing, complete canonical bundle persistence, and exact
preflight replay after reload. Zero skips/unexpected/flaky and verified cleanup.
Detached Docs run37198320734 reached finished publication but its pending-output
probe failed: the direct CMS request used a stale startup token and returned401
on both attempts. The worker's durable-save transaction precedes publication in
source and logs; no product ordering change was made. The one-file probe repair
uses disposable isolated admin login while preserving every exact PENDING-row
identity/timestamp check. Only this selector requires a new run. The remaining
recovery result is pending. P-7's trusted continuation claim patch is private,
12/12 focused trust cases pass, and it remains outside core release activation.

Recovery run37198325478 on `247b9dea` passed4/6 cases and advanced beyond
its previous assertion failures. The remaining failures were test-only: a
localhost page chose the external public API via hostname fallback, and a
restored page attempted a second login inside its preserved authenticated
context. The fixes require the runner's isolated API URL and await the existing
authenticated session. Canonical rejection, tombstone, exact journal and no-replay
assertions remain unchanged. Combined with the Docs probe authentication fix,
the next candidate changes no product runtime from `247b9dea`; only these two
failed selectors will run. The3/3 saved-bundle proof is reused.

The combined test-only candidate `c507f81f`, tree `54d21c10`, patch
`38f89473`, is queued for exactly Docs durability and recovery/deletion. Its
product runtime is byte-identical to `247b9dea`; saved-bundle3/3, database safety
and legal evidence are reused with their original sources. Only the two fixed
fixtures, generated reference lines and current notes differ. No fresh capacity
replay or real inference was requested. Core publication still requires its
external checkout and Apple gates; new archive/prune and billing stay off.

The core release was reconciled with published dev `2505cd4f` (including focus phases). Three merge conflicts are resolved: the chat metadata lists retain both focus phase state and storage fields; generated references retain both approved contracts. The existing focused metadata fallback test passed1/1. The private resolved tree is `007097a1`, with321 scoped paths and no additional product changes; final Docs and recovery browser consumers remain pending after successful environment preparation. The large benchmark and its trusted-continuation patch remain deferred. Archive/prune and expanded billing stay off. A separate bounded-query publication slice is being checked to avoid blocking safe database work on older Apple writers.

## Published database query improvement and remaining recovery fix — 2026-10-04

Commit `e1aa61e796d878bad05a42b954d3a3e8d99b3287` is published to dev. Its
four scoped paths change only hot count/window reads and their focused coverage
and generated references. Deployment specification, lint and four-case pytest
gates passed; one existing metadata fallback case passed during preparation.
The canonical metadata build also removes historical logs/source-copy test
references while preserving all actual source tests. Coordinated API operation
`docker-9478fcad` completed, including its required worker dependents; every
service reports running and healthy. No schema, archive/prune, client protocol
or expanded billing was activated by this slice. Older full startup sync is
still part of the separate client cutover.

Recovery run `37201164890`, source `c507f81f`, harness `a314f905`, has4
first-attempt passes and2 retry passes, zero skips/unexpected outcomes, and
verified cleanup. Its first embed write errored before the canonical receipt;
source proves `recovery_record_id` could enter the legacy embed transaction even
though it is protocol-only and absent from the embed schema. The raw SQL
exception was not retained, so this is a source-proven failure path consistent
with the observed error, pending exact E2E verification. Stripping the field
after the WebSocket capability check passes8 focused authorization/receipt
cases. No sole-copy loss or unsafe acknowledgement was observed.

Docs run `37201162529` confirms fresh probe login succeeds and the exact
prepublication seal probe passes. The remaining fixture expected new discovery
on an already-connected source socket, then navigated during the recovery
socket's acknowledgement sequence. The repair preserves producer/PENDING row
identity/timestamps and waits for discovery, acknowledgement and canonical head
before navigation. Syntax/metadata checks pass.

Private source `bd7ea2bd5700a81903d32f0d3e372abfa93dd386`, tree `415c0d20`,
patch `ef868a99`, changes one runtime handler from `c507f81f`, its focused test,
the Docs fixture and generated reference lines. Only Docs and recovery/deletion
are queued: `b194a1c3` and `65137c48`. This isolated proof retains its old public
baseline; the final release still must preserve newer published focus changes
and the live query improvement. Saved-bundle3/3, legal and actual database safety
proof are not rerun for this field strip. Apple compatibility is still required
before full writer activation. The full benchmark remains a future prune gate;
both final real-inference CLI/web turns remain unused.


## Publication focus: 2026-10-04 final checks

- Public `e1aa61e7` replaces per-message count transfers with an uncached scalar
  aggregate and makes bounded window failures explicit. Coordinated API/worker
  restart `docker-9478fcad` completed; all affected services are healthy. These
  query changes, the five tracking policies and nine PostgreSQL indexes are live.
- Private source `bd7ea2bd` passed the real detached Docs worker browser case
  first attempt (run 37205089797, one case, zero skips/retries). Its recovery
  selection completed six cases (run 37205092599): four passed first attempt and
  two passed on retry. Both receipts match harness `e1aa61e7` and verify cleanup.
  The two exact-ACK timeouts remain an unresolved liveness issue, not a stable
  recovery pass. No additional broad test selection is planned.
- The Docs fixture now waits for completed recovery before navigating. Recovery
  protocol metadata is removed before the ordinary embed database write; eight
  focused authorization/receipt cases passed. That field fix does not explain
  the remaining retry-only successes, whose failed-attempt API errors were not
  retained. Investigate only those two boundaries before strict writer activation.
- Final source reconciliation preserves the public focus fields, Apple Watch
  metadata, scalar count/error handling and all unrelated dev changes. It remains
  a private reviewed source until the critical recovery and native writer gates
  clear. Additive schema publication is separable from strict writer activation.
- The public Apple audit `docs/architecture/apple/storage-compatibility-2026-10-03.md`
  confirms the main writer is head-first but production still permits legacy
  receipts, advertises neither storage capability, and lacks typed recovery
  wiring. Watch retains keys-first and weak receipts. Native synthetic receipt
  tests can proceed now from the published contract; they need no API activation
  or real inference. See the updated Apple handoff's immediate next action.
- Full P-7 target-load processing is deferred under the publication priority; it
  remains a prerequisite for real-data pruning. Archive/prune/expanded billing
  flags remain OFF. Reference-safe unpaid expiry and Team billing remain open.
  No real user data has been moved or deleted. The two final real CLI/web turns
  remain unused and will follow the core API activation.
## Exact recovery race follow-up and activation order — 2026-10-04

The current exact two-case recovery CI completed only after flaky first attempts;
it is not a stable first-attempt pass. The bounded review identified a same-embed
canonical write race, missing correlation on a canonical denial, and a test
catalog-context mismatch. The correlation repair and focused backend regression
are included in the next candidate together with the frontend same-embed race
and catalog-context repair. Its focused unit selection passed 13/13: canonical
reuse, bounded v1 history when the head is v2, exact wrappers, no new journal or
head overwrite for a verified recovered event, and shared local-preparation lease
with exact acknowledgement are covered. The two exact browser cases remain
pending, so this is unit-ready rather than a stable critical recovery pass.

After publication and proof, development activation order is a coordinated
`cms-setup --build` first, followed by one coordinated rebuild/restart of `cms`,
`api`, and `app-ai-worker`. The setup step creates the additive columns and
indexes before new application code starts; its authenticated health check uses
the existing v1 metadata read. Archive, prune, and expanded billing flags remain
OFF. The development-only Apple rollout decision permits web, CLI, and backend
activation after critical proof; native typed-reader support remains a pruning
gate. No activation has been performed here.

## 2026-10-04 — approved unpaid-storage invoice closure implemented

The user approved the exact billing@6 review and the proposed warned-episode
write-off. Session 2f80 now contains fixed affected-unit notices, owner-scoped
metadata pagination, protected atomic expiry, authoritative balance-CAS admission
and auditable warned-only invoice waiver. The isolated fixture uses two 112-byte
objects with explicit simulated logical sizes; no GiB upload or inference is
required. Focused checks and source-bound PostgreSQL/S3 CI precede dev publication.
Team policy, real-data archive/pruning and the full capacity target remain gated.


## Personal billing release completed on dev (2026-10-05)

Release `7a6034a` and matching web deployment are public. Additive schema setup,
coherent backend restart, complete 44-owner read-only metering scan and coordinated
billing activation all succeeded. Final readiness verifies both personal billing
flags on the API/core/task/scheduler targets, all 11 valid-ready indexes, and all
six archive flags off. No real-user manual settlement/deletion job was run.

Both final isolated profiles passed cleanly at source `47dbe933`; tiny encrypted
objects carry simulated logical sizes. Warning context/template checks passed
45/45. The publication gate passed 137 relevant Python cases with the recorded
unchanged-dev workflow-digest timestamp exception. This release adds no real
inference to the two previously completed CLI/web canaries (58 credits total).

TASK-9893's approved personal billing scope is complete. Team payer policy,
native storage/writer work, full P-7 capacity evidence, current-head payload growth
and the first real archive/prune activation remain separate open work. The
architecture is not yet claimed proven for 1000 heavy daily users.


## Remaining execution resumed (2026-10-05)

- At resumption, the old isolated profile capped 500 requested prefork slots
  to four. The published admission repair removes that cap; measured target-scale
  evidence is still required.
- Automatic schema setup exists, but the full unattended copy/read/prune pipeline
  needs release eligibility and actual compatible-client enforcement. The user
  authorized this completion for official-cloud and self-hosted updates.
- Team archive metadata listing and complete cold-content export are being
  repaired. Team storage quote/settlement policy must preserve Team ownership
  and current role/revocation checks; payer semantics await the user answer.
- Artifact reconstruction must reject corrupt or incomplete patch chains and
  store history patches matching the actually committed final content. The
  current-head warm-byte refinement is a separate pending storage decision.


## Integration and simulation checkpoint (2026-10-05)

- Capacity admission/calibration and the dedicated runner route are published in
  dev `29bf4246d4356c53d7164d9edfadd6209388b247`; 143 focused harness checks passed.
  The requested 500 active executions are never silently reduced to four. No
  target-scale pass is claimed. GitHub currently has no dedicated self-hosted
  runner; actual calibration must size the target host before admission.
- Team storage quotes remain measured and unrated while the payer choice is
  pending. Personal cold listings exclude Team-owned manifests. Team/personal
  account exports include bounded verified encrypted archive parts. Unsupported
  graph restoration, membership/invite imports and authoritative credit/usage
  ledgers are rejected before writes; selected supported metadata still imports.
- Historical reconstruction rejects missing/corrupt patch chains and archive
  envelopes, and generated patches describe the actually committed final bytes.
  Shared Project history carries the authorized Project/Team scope and retains
  the successfully unwrapped file key in the existing ephemeral client cache.
- Automatic migration is being integrated with trusted source-specific release
  eligibility, actual distributed API reader enforcement, periodic retries and
  host inventory refresh. A release attestation does not waive per-unit
  ciphertext, reference, generation, acknowledgement or 24-hour source fences.
  No real eligibility certificate has been issued; production is unchanged.
- Legacy whole-graph deletion is not the automatic bounded migration path. It
  must remain held where it would delete current artifact heads or chat listing
  metadata, or lacks an atomic source-write fence. The approved message-page and
  historical-version paths retain those PostgreSQL indexes and heads.
- Apple evidence, actual combined-source CI, the heavy target and first real
  pruning activation remain open. No new real inference or test email has run.

## Combined-source publication checkpoint

- All four worker patches are integrated with current dev changes. The exact
  combined rollout, release issuer and runtime inventory unit checks passed
  53 cases; changed Python syntax, whitespace and Specification generation pass.
- The coordinator stages verified reader admission before retiring incompatible
  sessions, and still requires zero incompatible sessions before pruning. The
  host updater renews complete process inventory automatically after updates.
- This checkpoint authorizes no real-data pruning: release eligibility is absent,
  native and full P-7 evidence remain open, and production has not been changed.


## Published automatic migration and focused client evidence — 2026-10-05

- Dev `8d50ac6555faff1f44a447c8b3600fa1e95080d8` publishes the integrated
  automatic migration, archive transport, exact Project-aware reconstruction,
  bounded Team/personal exports and measured unrated Team storage quotes. All
  352 backend publication cases passed.
- Isolated browser run `37319285267` passed all three bounded history cases,
  including a shared Team Project and original-version reconstruction. Focused
  backend run `37319297030` passed its 12 selected files. CLI run `37319290856`
  passed all seven selected encrypted-version/server-migration checks; the
  unrelated Project API mock in that run lacked the new fetch export.
- Test-only dev `34beeb72d2bb88cbef5a7322cb0614630336894e` adds that export
  while preserving all Project assertions. Its focused run `37321647498`
  passed 9/9 with zero failed or pending cases; its retained receipt matches
  source and harness `34beeb72`.
- Capacity calibration `c443b957` never started. Preparation run `37319190281`
  rejected a PostgreSQL index predicate whose equivalent AND nesting changed
  on SQL restore. The disposable schema producer round-trip repair has 27
  focused checks and preserves exact comparison and independent fresh
  consumers. No capacity measurement or target-load pass is claimed.
- The registered CLI update path installs and renews full serving-process
  inventory and periodically retries trusted release eligibility. An absent
  release certificate or native/capacity evidence holds advancement; complete
  compatibility and all per-unit checks remain mandatory before pruning. The
  first real cohort retains PostgreSQL source payloads for at least 24 hours.
- Production is unchanged. Team wallet/expiry policy and native evidence remain
  pending. Current heads remain PostgreSQL-resident under approved D-9; the
  optional warm-head byte refinement has not been approved.

- Operational repair `58885a96991799cd8f528f77c0fcb454f3421726` packages
  migration modules in every legacy Celery build and stabilizes only disposable
  test-schema generation. Four projected-image checks and 27 schema checks passed.
  Coordinated rebuild `docker-677cdc07` completed for all 16 affected services;
  the API is healthy and the core worker/scheduler no longer restart.
- Repaired-source calibration `609e81d5` is queued on exact source/harness
  `58885a9`; preparation run `37323757755` is in progress. This is sizing work,
  with zero real inference and no target-scale result yet.
- Actual dev startup inspection also found Compose stripping scalar command
  continuations and omitting intended worker queue/concurrency/limit flags. The
  command-vector repair preserves those configured values and all non-command
  service settings; 15 actual Compose-resolution and executable shell cases
  passed. Runtime admission is verified after its coordinated restart.
- Task-owned generated source backups were deduplicated without omitting file
  bodies or metadata. Coordinated cleanup removed only unreferenced images from
  this Task and unused build cache; user data, volumes and referenced images
  remain intact. The standard CI disk reserve is preserved.


## Dev deployment and actual admission verified

Command-vector release `3bdf7a4d1a83d8ef87e8f78e502da24753850a04` is public.
Coordinated restart `docker-d3726518` completed for all 16 affected services.
Read-only inspection of actual Celery process argv confirms configured queues,
concurrency, child-task/memory limits and prefetch are now present. All six
archive flags remain explicitly off on API/core/task/scheduler/AI targets; the
two active personal billing flags remain on. This verifies the scoped dev
deployment and preserves the existing migration hold.

These dev images were built without `BUILD_COMMIT_SHA`, so their source
provenance is unavailable and migration remains fail-closed. This does not
certify that dev cohort for archival. The supported registered CLI and official
image update paths supply source provenance and install complete host monitoring;
raw Compose updates need the documented monitoring/provenance setup. No release
eligibility certificate or real-user prune has been issued.

Repaired schema preparation `37323757755` passed and its retrieved receipt
confirms source/harness `58885a9`, exact tree `46bb33c5`, and required web/CLI
capabilities. Calibration `37325705842` failed at isolated backend startup after 481 seconds;
selected checks were skipped and no measurements exist. Disposable cleanup
verified zero containers/volumes and removed private account state. The helper
is investigating retained startup diagnostics before any retry. Results remain
labeled separately from the eventual
matching-source 500-execution/1000-user-day target. No new inference ran.

Team quote/export implementation is public; choosing a Team wallet versus the
owner personal wallet still precedes rated quotes and settlement. Team notice
recipients and any Team-specific unpaid expiry must also be resolved before
activation. Personal expiry continues to protect Team data. The Apple chat
should consume the published archive handoff before declaring native capability.

The startup failure occurred in the isolated Vault provider-namespace proof,
not container health. Its discarded one-shot output cannot establish the exact
old HTTP/import cause. The focused repair uses the authenticated disposable
initializer, verifies root scope, and emits only bounded whitelisted
stage/status/count diagnostics. Source inspection found normal API startup creates
local VAPID signing keys. The fixture now explicitly creates a fresh disposable
EC key pair and the proof/validator require the exact `core_server`/`hetzner`/
`vapid` namespace plus generated-fixture provenance. Missing VAPID, imported
provenance or any additional inference-provider entry rejects the profile.
Fourteen positive/negative/privacy probe checks and 23 focused rollout tests
passed; no production Vault policy was changed and no calibration pass is claimed
before the repaired run.

CLI npm publication for product source `8d50ac6` succeeded in run `37319010149`.
Production rollout must use the updated CLI release with the matching official
images or clean source build; direct git/Compose commands alone do not install
the host monitoring service.


## Fresh self-host source-install provenance

The supported CLI source-start path now builds selected services with the exact
clean Git revision before creating containers. Dirty checkouts, unavailable Git
and invalid revisions pass an empty build revision and cannot claim release
eligibility. Official image pull/start behavior is preserved. Six focused CLI
checks passed, including actual source-start execution against controlled command
fixtures for clean, dirty, invalid, unavailable and image cases. Exact-source
isolated CLI run `37330852686` passed all six cases on source/harness
`94440c1cb432cee48cb0604cbd15b0e42ae2d105`, with zero failed, skipped or pending
cases. Its retained report and selected-run log are verified; no real server
was started by these fixtures. Standard new CLI installations install host monitoring, and existing
registered updates upgrade/restart it; plain Git/Compose still requires the
documented equivalent inventory service.

Sizing calibration `012a5314` is queued on exact source/harness `3539f6d`; it
is separate sizing evidence and cannot certify a later protected source for the
full 500-execution target. Production and real-user pruning remain unchanged.


## Official image-publication audit contract

CLI publication `37330781930` succeeded for source `94440c1` on the npm alpha
channel, including the fresh source-install fix. Official image publication
`37330781963` stopped before building images because the domain-policy audit
expected the old Celery Dockerfile layout. The actual complete backend tree,
including encrypted policy files, is present. The verifier now recognizes the
actual backend-qualified COPY declaration and rejects comments, RUN strings and
unrelated similarly named source trees. Two focused checks passed, including
the actual policy/image audit and rejection of a removed worker policy tree.
The exact publication audit command also passed. No security check was skipped
and no image contents or dev runtime changed for this verifier repair. The next
official image-publication result remains pending.


## Actual inventory admission remains unverified

Preparation `37330338224` passed. Its sizing consumer `37332433657` failed
on exact source/harness `3539f6d` during isolated backend startup. The corrected
authenticated three-key Vault namespace proof passed, all services were healthy,
and the next actual serving-process inventory refresh failed before workload
execution. No throughput, memory or latency measurements exist. Cleanup
verified zero containers/volumes and removed private account state.

The original collector output was discarded before its renewal log began, so
retained artifacts cannot identify the failed inspection/cohort/bootstrap/publish
transition. Source/profile inspection confirms the expected Compose project,
source revision, script mount and single-serving-process layout; it does not
prove a collector defect. The next changed-source run retains only typed
allowlisted stages, reasons, error classes, counts and status. Admission still
requires the exact source, complete real process inventory and short expiry.
The fixture setup returns a typed exact-source/count result; a safe startup
artifact is retained for failed and successful stages. Nine focused collector
checks and 26 startup/namespace checks passed. No guard, source fence, heartbeat
check or provider restriction was relaxed, and no retry policy was added.

One instrumented existing calibration is authorized: startup failure stops
processing; fully admitted startup may continue with the small eight-user sizing
pilot. This is not the 500-execution/1000-heavy-user-day proof. Team payer and
notice/expiry decisions, native evidence and dedicated target measurement remain
open. Production and real-data pruning are unchanged.

Official image run `37333952572` passed the repaired policy audit and is building
the release; its schema image passed independent fresh-consumer verification.
Completed image jobs do not establish that all required images or release
eligibility are available. The final complete-image result remains pending.


## Instrumented inventory publisher repair

+Preparation `37337645394` succeeded on exact source/harness `c239876`. Its
+consumer `37339557130` stopped before workload execution: actual API inspection
+and source-cohort validation passed, but the publisher returned exit zero with
+output that failed strict JSON parsing. The retained sanitized startup artifact
+identifies `inventory_refresh` / `publish` / `runtime_inventory_json_invalid`
+and `JSONDecodeError` for one API container. The unretained service bytes cannot
+establish which output caused that failure. Cleanup verified zero containers,
+zero volumes and removal of private account state. No measurements exist.
+
+The focused repair contains backend bootstrap/service/cleanup output and emits
+one safe JSON result after restoring its output streams. It neither parses log
+fragments nor changes source, complete inventory, nonce, expiry, Redis or provider
+guards. Eleven focused collector checks and lint passed, including actual main
+success and failure with noisy initialization and cleanup. Positive runtime
+admission remains pending one changed-source startup/calibration run.
+
+All eleven official images passed publication `37338545678` for public
+`51dfcd58`; CLI alpha publication `37338545610` also succeeded. Earlier full
+image publication `37333952572` succeeded on `f4480746`. Complete image builds
+do not supply the still-pending reviewed capacity/native proof registry or an
+eligible migration certificate. Production and real-user pruning are unchanged.
+
+The Team helper confirmed quote/export/import implementation and focused
+pytest evidence. One real-path coverage gap remains: the new Team manifest/part
+queries and metadata import writes have not yet been verified through actual
+PostgreSQL/Directus and S3. One existing disposable Team probe is being extended,
+using tiny ciphertext with zero inference or delivered email. Team payer and
+notice/expiry decisions still precede charging and deletion activation.
+

## Bound standalone migration tasks and real Team portability coverage

The exact-source `a6d7d5e` preparation `37341441618` passed. Its consumer
`37342192109` verified clean inventory JSON, then failed during publisher
bootstrap with a typed `AttributeError`; no workload measurements exist.
Retained startup and cleanup artifacts are digest-bound in session 2f80's
`logs/helper-ready/p7-a6d7d5/manifest.json`. Cleanup verified zero containers,
zero volumes and removal of private account state.

Static tracing identified standalone `BaseServiceTask` request access without
Celery application binding. Both collector and capacity fixture now bind the
task to the actual application before service initialization. Eleven collector
checks and one fixture regression passed using real Celery 5.5.1 request
behavior; they reproduce the unbound failure and verify binding before access.
The clean output protocol and source/process/nonce/expiry/provider fences remain
intact. Actual complete startup and the conditional sizing pilot still require
one changed-source run; the 500-execution target remains separate and unproven.

Team imports now require a successful database acknowledgement and created
record identity before incrementing confirmed imports. A failure stops the
import and reports the confirmed count and possible partial state; it does not
claim transactional rollback. Four persistence regressions and two resource
cleanup checks passed. The focused real-path probe verifies original archive
ciphertext, Personal/other-Team isolation, viewer and removed-member denial,
rejected authority/content imports without writes, selected metadata persistence
and local destination-key readability, plus exact row and regional-object cleanup.

One dedicated `storage-team-portability.spec.ts` reuses the existing guarded
storage profile. It creates no browser or signup account and makes no inference
or email request. Its selector is standalone, has zero retries and checks an
exact-source bounded receipt. Python/TypeScript syntax, Ruff, ESLint, metadata
and registry validation passed; actual isolated PostgreSQL/S3 execution is
pending. No new testing harness was introduced.

Team payer and notice/expiry choices remain unresolved, so Team charging and
deletion are not activated. Production, archive flags and real-user pruning
remain unchanged; no eligibility certificate is issued from these unit checks.


## Complete initialization admitted; shared Team schema blocker repaired

Exact source/harness `3e3f3bc` preparations `37344988875` (Team) and
`37345229697` (P-7) passed. They have the same compatibility key but are distinct
preparation producers. Their consumers `37346829687` and `37347124888` failed;
neither is passing product or capacity evidence.

The retained P-7 startup proves complete serving-process inventory publication
with its 180-second expiry, disposable fixture setup, four actual worker slots,
absent real provider credentials, blocked provider network access and authenticated
disposable object storage. Its one browser scenario passed. The preliminary archive
transaction probe then reached Team export and received HTTP 403 for the undeclared
`team_connected_account_grants` collection. The focused Team consumer failed at the
same query. Both cleanups verified zero containers, zero volumes and removal of
private account state. No sizing report, workload counts or 500-execution proof exists.

The repair declares the existing grant collection through ordinary YAML schema
setup, using the already executable `hashed_team_id` contract. Grant account keys
are redacted from exports. Grant records carry access authority and are rejected
before import writes, alongside memberships, invites and financial records. The
tiny real probe now verifies scoped/redacted grant export, authority rejection and
grant cleanup. Safe failure receipts retain allowlisted stage/reason/class codes;
private process output and exception messages are excluded. Fifteen focused grant
and schema cases, nine diagnostic/selector cases and five actual-wrapper checks
passed; Ruff, ESLint, metadata and patch application checks passed. The real Team
flow and one changed-source sizing calibration remain pending.

The final migration-path audit confirms successful registered image/source updates
run and verify schema/index setup before starting target services, then install
and renew the complete runtime monitor. Fresh standard installations also install
monitoring; clean source starts carry the actual commit. Documentation now states
Linux/systemd host privileges and administrator-shell Node/CLI requirements,
one-minute monitoring and 180-second inventory expiry. Bare registration followed
only by start, or raw Git/Compose operations, need the documented monitor/update
step. Failed setup, missing provenance, failed monitoring or absent exact-source
eligibility keep advancement paused. No production operation, signed eligibility,
archive activation or real-user pruning is authorized by this audit.

Team payer and notice/expiry choices remain unresolved, so Team rating, settlement
and expiry remain off. Supported native-reader evidence and the required capacity
proof still precede first real-data pruning, followed by the initial 24-hour source
buffer. The dev API activation follows successful real Team verification.


## Team execution succeeded; result-reader integration corrected

Published `2432ffe` declares the missing Team grant collection, redacts account
keys, rejects authority imports before writes and corrects automatic migration
setup documentation. Both backend module gates, lint and Specification checks
passed. Official image build `37350338801` completed successfully.

Team and P-7 consumers share the actual successful preparation `37350556290`,
including two fresh schema consumers, exact source/harness `2432ffe`, web and CLI
bytes and no upload capability. Team run `37351907220` completed green, but its
first result retrieval correctly rejected missing browser evidence: the new
API-only selector was absent from the existing frontend-free result-validator
branch. It has no accepted receipt yet. A bounded diagnostic read of the actual
artifact, using the existing size/extraction/disk limits and source/run/harness
checks, confirms all nine actors, identical readonly backend mounts, internal
provider network, absent live credentials, disposable Vault/S3 proof and no
frontend. That diagnostic is explicitly not acceptance evidence.

The reader correction admits only the exact standalone Team selector with those
strict source, actor, network, credential and storage checks. Existing hosted
runner, report identity, spec inventory and independent verified cleanup gates
remain enforced. Forty focused checks, including poisoned evidence fields and
cleanup rejection, passed with Ruff and metadata checks. The existing green Team
run will be retrieved through the corrected normal coordinator; no product rerun
is needed for this local reader correction. P-7 continues on its existing pinned
source; no final-source equivalence or 500-execution capacity is claimed.

Team payer/notice/expiry decisions, native-reader eligibility and full capacity
proof remain open. Production and real-user archive pruning remain unchanged.


## Team proof accepted; calibration stopped at first version updates

After publishing local result-reader correction `09e01ba`, normal coordinator
retrieval accepted the existing Team run `37351907220` on exact source/harness
`2432ffe`: one expected test, zero skipped, failed or flaky tests, 13.851 seconds,
artifact `11362688707`, verified container/volume/private-state cleanup. The
backend tree for the tested source and `09e01ba` is identical. This is Team
portability proof, not full-source or capacity equivalence.

P-7 run `37351901002` used the same successful preparation. Startup, its archive
PostgreSQL/S3 preliminary probe and one browser test passed. The eight-user,
four-slot calibration expected 240 rounds, 32 embeds and 32 versions; it stopped
after 60 rounds, 16 embeds and four initial versions. Four first-update failures
reported `version_callback_count`. The old adapter combined response completion
and callback-count checks without retaining either value, so no product root
cause or calibration admission is established. Cleanup verified zero containers,
zero volumes and private account-state removal. The guarded private driver report
and rows are retained in session 2f80's `p7-2432ffee/manifest.json`. Its partial
421.886-second measurements cannot size the full 500-execution host.

The narrow diagnostic change preserves every completion, exact callback,
content and revision assertion. It retains only documented response-state enums,
bounded callback counts and expected revision in the existing private report;
raw response bodies, arbitrary codes, account identifiers and keys are excluded.
Six focused shape/privacy checks, Ruff, Node syntax and patch checks passed.
The next diagnostic uses the existing two-user/two-thread replay selector
(60 rounds, eight embeds, eight versions), explicitly a smoke check, rather than
another full calibration or any real-inference test. No new test harness is added.

The dev additive schema application completed through coordinated `cms-setup`
operation `docker-36d9718f`. Runtime operation `docker-df1ad6a2` activated the
coherent generation across all 16 backend services and verified health. The
post-rebuild check exposed absent persistent dev archive opt-outs: unset flags
use default-on copy behavior, while unknown source and missing eligibility still
hold read/prune activation. The six explicit zeros were restored in canonical
`.env`, followed by a coordinated same-code recreation without a new build.
All 16 effective container environments verify archive copy/read/prune off and
personal logical-storage billing/expiry on. Production remains unchanged; no
certificate or real-user pruning is issued. Team payer/expiry choices, supported
native proof and required full capacity admission remain open.


## Official-cloud billing admission and replay readback repair

The diagnostic replay on exact source/harness `071a70d` prepared successfully
(run `37358091378`) but consumer `37358679220` failed before the capacity driver
started. The browser displayed a synthetic assistant response; its test readback
probe omitted the `agentic-storage-v2` capability header required by the activated
CI archive guard. The previous run did not retain that request's HTTP status, so
HTTP 426 is source-inferred and no canonical save failure or artifact callback
root cause is established. Verified cleanup left zero containers, zero volumes
and no private account files. Bounded receipts are retained in session 2f80's
`p7-071a70db/manifest.json`; there are no workload or callback-count measurements.

The replay probe now declares the same capability as the calibration and target
probes. It retains the encrypted canonical assistant, fresh reload and 30-second
checks, with failure diagnostics restricted to HTTP status, array shape and
capped row counts. ESLint, Specification metadata and the existing four HTTP
compatibility cases passed. This repair does not weaken a server admission gate.

The rollout audit found that server updates preserve existing `.env` and expanded
logical billing defaults off. New official-cloud archive copy and pruning now
require `STORAGE_LOGICAL_S3_BILLING_ENABLED=1`, including direct message/version
writer and transition paths; the coordinator reports `storage_billing_disabled`.
Existing cold reads, recovery and exports remain available, and self-host billing
configuration stays independent. Source, signed eligibility, client, durable ACK,
generation, replication and 24-hour initial source-copy gates are preserved.
The guard does not enable financial flags or decide Team rates. First production
rollout still requires reconciled metering and the approved notice/legal/settlement
checks, then persisted billing flags before the normal server update. Subsequent
eligible archive work advances automatically.

The coupling passed Ruff/compilation for ten Python files, twelve focused hold
cases and 83 broader checks; one checkout-path-dependent case was excluded from
the partial overlay run and remains covered by full-source verification. The
existing isolated PostgreSQL/S3 probe now checks that rejected copies leave
originals and no S3 object, and that held pruning keeps stored history readable.
That real probe awaits the combined-source CI result. The exact 42-test backend gate also passed with all six archive flags initially disabled after making the existing fence tests declare their prerequisites explicitly; no rollout gate or assertion was removed.

After the daemon interruption, the canonical dev API is healthy and inspected
core/AI/task/scheduler services retain all six archive flags at zero and both
personal billing flags at one. No production mutation, new real inference,
certificate issuance or real-user pruning was performed. The earlier two real
CLI/web canaries remain the only inference runs (58 credits total). Team payer
and warning/expiry choices and supported native proof remain open. The next run
uses the existing two-user replay, not a new harness or a capacity claim.


## Migration-aware CLI release prerequisite and dev activation

Release `d63b7cc5e00fd54ea948489053e6e4700aff2206` published the official-cloud
billing admission guard and repaired the replay test readback header. Its
Specification, lint, locale and exact 42-case backend publication gates passed.
Coordinated dev restart `docker-eed4fbc6` refreshed all 16 backend services without
a dependency or image rebuild. The API is healthy; the loaded guard hash matches
the published source; all six archive opt-outs remain zero and both personal
billing flags remain one. Production is unchanged.

A read-only supported-path audit found no further updater omission: target
schema precedes writers, the monitor renews complete inventory, eligibility
retries automatically, and initial eligible pruning retains PostgreSQL source
for 24 hours. The first rollout must also upgrade the global CLI. Server updates
do not self-update it, and main's npm workflow skips a stable version that
already exists. Publish a new stable CLI version containing the migration-aware
updater, verify it, then run the registered server update with the intended
qualified images/source. This release sequencing is documented in
`docs/architecture/storage/automatic-migration.md`.

GitHub's repository runner inventory currently contains zero registered
self-hosted runners. The full target requires the dedicated `openmates-capacity`
runner labels plus passing same-source calibration and measured resource
admission; no 500-concurrent or 1000-heavy-user-day result is claimed. The
existing dev host reports approximately 32 GB total RAM and 36 GB free disk;
these observations do not establish target capacity or justify using shared dev
services for product testing. Team payer/notice policy and native proof remain
open. Existing real canaries are not repeated.

The immutable public release configuration is stable base `0.27.0`; the npm
registry currently reports stable `0.26.0` and alpha `0.27.0-alpha.27`. Thus the
configured main release is a new stable version, and the existing CLI workflow
should publish it automatically after a successful qualifying main push. Verify
the successful publication, upgrade each host CLI, check `openmates version`,
and then update its registered server. A version bump is not needed solely for
this prerequisite while `0.27.0` remains unpublished.

The replay request `0837838601b9593496bf0a888b0a1e823e46ca16b5358d978f1581932610b1cf`
prepared in run `37365927430`, but consumer `37366539285` failed without receiving
a GitHub-hosted runner. GitHub reports runner ID zero and no executed steps. No
application test, workload, callback, billing probe or cleanup ran. The normal
coordinator correctly rejected this run as execution evidence. This establishes
an infrastructure failure, not a new product defect.

GitHub's official status at `2026-10-05T19:50:50Z` confirms degraded Actions
performance and incident `3q1yb5m7ltvb` investigating hosted-runner assignment
delays since `19:11:58Z`. One same-source replay retry is queued under request
`6af5b376eb9c3428293c5c96633a1014d24b93193763842fdcb9eb51cf1e74e8`,
using the same preparation key. No further run is dispatched until its outcome
is known; repeated runner-acquisition failure requires waiting for infrastructure
recovery. The next four-slot calibration and full target remain unexecuted.

References: [GitHub Actions incident](https://www.githubstatus.com/incidents/3q1yb5m7ltvb),
normal coordinator requests and bounded private receipts in session 2f80.
