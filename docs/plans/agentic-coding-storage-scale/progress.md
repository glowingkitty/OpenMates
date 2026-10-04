# Storage implementation progress

Snapshot: 2026-10-04. OpenMates Tasks owns work status and dependencies.

## Current release status

- Core development release
  `1e7b84c33ea33734ec53c85deda27b90aad3124d` is public and active. It includes
  the bounded storage, recovery, archive and artifact-version foundation.
  Existing high-write Directus tracking policies, filtered scalar message counts
  and nine nonunique access indexes remain live; historical audit rows remain.
- The coordinated schema operation succeeded in 361.35 seconds. Coordinated
  restart `docker-867b0631` then succeeded in 295.41 seconds with all 17 services
  running and healthy. Independent catalog readback found 17/17 recovery indexes
  present, unique where required, valid and ready. All seven archive and
  expanded-billing switches are off across all 17 services.
- Matching Vercel web deployment `2w3u56hwciegHBEV9p8N4CjtvCut` succeeded.
  Production is unchanged.
- The exact backend gate passed 1,408 tests across the inferred 120 files.
  Focused recovery CI `33e0f616` passed both selected cases, with one synthetic
  fixture setup retry. This is scoped release evidence, not a full-scale proof.
- Full P-7 is deferred and remains the first-real-prune gate. Native typed
  readers/writers and cross-client concurrency remain unverified. Expanded
  billing's reference-safe expiry and Team policy remain incomplete and off.
  Archive copy/read/prune remains off.
- The user is the only Apple tester and waived development legacy compatibility.
  This clears the dev legacy-client hold for the published core. Native ordinary
  canonical writers must still implement capability-bound strict digest/source,
  request/count receipts and head-before-keys, including Watch. Typed v2 must be
  advertised only when its complete reader/persist/ACK flow is wired. Native
  typed readers remain a pruning gate.
- The final CLI and web canaries remain pending. Slot 10 was absent on dev. A
  later CLI command on registered slot 4 exited with status 1 after durable
  ledger dispatch; its server outcome is uncertain, it has not been retried, and
  neither provider dispatch nor canary success is inferred. The web canary on
  registered slot 3 has not sent a user turn.

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

## Prepared code

| Area | Implementation | Remaining verification or work |
| --- | --- | --- |
| Redis | Three recent main chats; separate bounded active children, embeds and pending writes | Target-load measurements |
| PostgreSQL/S3 | Bounded queries, indexed pages, large payloads, copy/verify/fences, initial 24-hour buffer | Reader compatibility and real-data rollout |
| Unattended output | Durable sealed messages, child results, embeds/diffs and checkpoints; pause on failed save | Updated restart/browser checks and native clients |
| Artifact versions | Paginated graph metadata, S3 payloads, periodic snapshots and bounded patches | Processing pilot rerun after the exact-content fixture fix; account-wide growth of current-head SQL payloads |
| Directus | Five-collection policy published and active; isolated actual Directus comparison passed, preserving intentional history | New checkpoint/archive/recovery policies await main release; any routine user-state writer change needs a separate focused proof |
| Billing | Logical S3 metering, frozen weekly settlement, retries and delivered-warning clocks | Exact billing review, Team payer, integrated proof and protected expiration implementation |
| Legal | Storage, encryption, deletion and cost copy corrected; retention-law claims corrected | Coordinated publication with matching behavior |

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
