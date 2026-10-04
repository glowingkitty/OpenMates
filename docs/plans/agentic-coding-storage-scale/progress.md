# Storage implementation progress

Snapshot: 2026-10-04. OpenMates Tasks owns work status and dependencies.

## Published to dev

Specification, Plan, Apple handoff, synthetic crypto fixture and scoped CI tooling.
Latest trusted tooling: `d0dee04a6e69c2bade6bc4f89586b0cb69c33b98`.
The main storage/API implementation is still in private candidates. No real-user
migration, pruning, new S3 charge or protected unpaid-data expiration is active.

## Prepared code

| Area | Implementation | Remaining verification or work |
| --- | --- | --- |
| Redis | Three recent main chats; separate bounded active children, embeds and pending writes | Target-load measurements |
| PostgreSQL/S3 | Bounded queries, indexed pages, large payloads, copy/verify/fences, initial 24-hour buffer | Reader compatibility and real-data rollout |
| Unattended output | Durable sealed messages, child results, embeds/diffs and checkpoints; pause on failed save | Updated restart/browser checks and native clients |
| Artifact versions | Paginated graph metadata, S3 payloads, periodic snapshots and bounded patches | First-version processing failure; account-wide growth of current-head SQL payloads |
| Directus | Five-collection tracking policy; intentional product history preserved | Verification could not read the container-owned private receipt; fix host/container ownership and rerun the full comparison |
| Billing | Logical S3 metering, frozen weekly settlement, retries and delivered-warning clocks | Exact billing review, Team payer, integrated proof and protected expiration implementation |
| Legal | Storage, encryption, deletion and cost copy corrected; retention-law claims corrected | Coordinated publication with matching behavior |

## Retrieved evidence

- Source 328: actual disposable PostgreSQL/S3 probe passed, 20 source messages,
  one verified page, 20 pruned messages, late-write/recovery/reference/race fences.
- Source 0ab9: four selected unattended-recovery browser cases passed.
- Source 0b81: selected UI unit run passed 24/24 cases in five suites; three signed
  browser cases and diagnostic processing pilot are still under verification.
- Source 998c: Directus integration failed at receipt validation after startup;
  no measured tracking/storage improvement is claimed from that run.
- Source 1f755, trusted harness d0dee: the corrected single-attempt Directus run
  failed while reading its private receipt. The host test and artifact collector
  could not read the container-owned mode-0600 file. The probe subprocess and
  cleanup returned successfully, but the receipt assertions were not verified.
  Preserve private permissions and fix only the guarded receipt's ownership;
  no tracking or write-overhead pass is claimed yet.
- Latest legal draft: four rendered-copy unit cases and 21-locale generation passed.
- The accepted 1000-heavy-user/500-active-execution capacity target has not run.
  The current CI worker profile cannot admit 500 active prefork tasks.

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
