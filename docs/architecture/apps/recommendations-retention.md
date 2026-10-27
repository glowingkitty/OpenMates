---
status: active
last_verified: 2026-10-20
---

# Apps recommendation storage and funding

The private Apps library is a first-party session surface. Developer API keys
cannot read its saved searches, temporary recommendation batches, or saved result
graphs. Each scope combines the authenticated owner, app, and explicit Team.
Team membership is checked on every read; spend roles are checked before claiming
and publishing an automatic search. Team charges use the Team ledger, never the
acting member's Personal account.

Private search titles, queries, parameters and the daily enabled preference are
stored in the backed-up PostgreSQL collection `apps_workspace_libraries`, inside
one per-owner Vault-encrypted configuration document. The entire temporary result
batch, including nested child payloads, is encrypted with the same owner's
server-managed Vault Transit key before its separate ephemeral disk write. This
is the scheduled Workflow encryption pattern; it never uses a client/master key.
Durable DB metadata contains only internal scheduler owner references, app/Team
scope, a conditional-update version and paid-attempt identities/times. Operational
disk metadata contains only activity timestamps and opaque attempt identities.

The scanner enumerates authoritative database records, including after a restore
with an empty temporary volume. A saved optout therefore never becomes a default
opt-in after restore. The default enabled daily search selects only the most recent
saved search in a scope. Older searches stay available. An account must have been
active during the last seven days. Eligibility reads the existing general
`last_online_timestamp` (successful auth session validation/login) and Directus
`last_access` freshly with internal admin access, plus the content-free Apps
activity fallback. Web session checks and CLI identity/socket admission refresh
that general session timestamp; background recommendation jobs never update it. Durable claims precede provider dispatch, with a server cap of
100 credits and stable authoritative billing identities. A failed or interrupted
attempt is not paid/replayed automatically again during that 24h interval.

Only the latest successful temporary batch exists. Same-filesystem fsync and
atomic replace publish it without backup files. Every batch expires 24h after its
creation; reads fail closed at expiry and a 60s cleanup task unlinks it regardless
of activity. Failed replacements do not extend an older batch's expiry. Nested
children remain inside that one encrypted batch. Automatic results are not copied
into ordinary saved embed graphs, Redis result caches, task arguments or Celery
result records. Explicit user saves use the separate durable embed store.
HTTP library responses use no-store. Clients must discard expired in-memory cards.

## Runtime storage and managed backups

API and task-worker mount the dedicated `apps-recommendations-data` volume at
`/app/data/apps-recommendations`, configured by `APPS_RECOMMENDATIONS_DIR`. Only
temporary recommendation batches, public batches and operational locks/
activity/cleanup manifests use this volume. Saved searches and preferences never
use it. The worker startup owns it as its unprivileged service account and enforces 0700.
Root API file writes inherit that directory's service owner; files are 0600.
Neither `config`, database storage, log mounts, nor ordinary embed storage contain
temporary recommendation payloads. Durable saved queries/settings and paid-attempt
claims are in PostgreSQL and therefore included in managed database backups.
Public batches occupy the `public` subdirectory and
contain no user identity or personalization; they are intentionally unencrypted.

The actual managed `openmates server backup` implementation
(`frontend/packages/openmates-cli/src/server.ts`, `createServerBackup`) stages only
runtime `.env`, runtime `config`, a PostgreSQL dump, manifest and checksums.
`planBackup` in `serverPlanning.ts` is the corresponding allowlist. It never copies
Docker volumes. The dedicated temporary volume therefore stays out of managed
backups while
`apps_workspace_libraries` is included in the PostgreSQL dump;
`openmates.backup.exclude=true` also records the policy on the volume. The old
commented Compose backup-service has no volume mount for this data.

Operators of external disk/VM/container-volume snapshot tools must explicitly
exclude this volume. The app cannot erase preexisting external snapshots or
promise physical block erasure on SSDs/copy-on-write filesystems. During a complete
worker outage disk unlink is delayed; authenticated reads still enforce expiry,
and cleanup resumes when workers recover. No application backup or cached copy is
used to restore expired temporary batches.

## Public discovery

Unauthenticated GET `/v1/apps/workspace/public/{app_id}?language=en|de` only reads
an existing current batch. It cannot trigger provider work. Only Code, News,
Videos and 3D Models have fixed, versioned editorial queries and localized CTAs.
There is no public Health, Jobs, Home, Fitness, Weather or personalized catalog.
The daily task uses existing SkillRegistry/provider initialization without a user,
Team, model override or user billing context. OpenMates funds provider usage.
Videos may reuse factual external media fields from today's already-published
science Daily Inspiration defaults; private pool rows, personalized phrases and
assistant responses are excluded. Otherwise the fixed public search runs.
Both public and private batches expire after 24h. Public and private stores never
share a search query, billing identity, result identifier or payload.
