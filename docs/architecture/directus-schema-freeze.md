# Development Directus schema freeze

The development Compose override enables `CACHE_SCHEMA_FREEZE_ENABLED` for CMS.
The shared and self-hosted Compose definitions leave the vendor default unchanged.
The pinned Directus 11.5 image then returns the same deeply frozen schema metadata
instead of cloning it for each cached read. This does not cache Personal Memory
bodies, request results, account authority, Team membership or privacy generations.
No latency improvement is claimed until source-matched development measurement.

`backend/tests/test_directus_schema_freeze.py` checks the exact pinned vendor
source hashes and runs the shipped cache, schema-read and access-validation code
in disposable read-only containers with networking disabled. Both enabled and
disabled modes verify field/relation reads, admin collection validation, cache
identity and immutability, system/permission invalidation, administrative cache
purge and the real `schemaChanged` subscriber. The subscriber is exercised on a
local bus; this check does not claim cross-process Redis or live database proof.

Directus schema edits retain their normal schema-change invalidation. Forced
system-cache clearing also drops local schema and permission caches; the normal
administrative purge additionally clears response caches. Schema snapshot/apply
uses the vendor's cache-bypass path. OpenMates extensions must treat supplied
request schema as read-only; database-builder `trx.schema` is a separate object.

The new durable Personal privacy-context generation and its mutation triggers
remain database authority. Every Memory/settings write covered by that contract
must advance the generation regardless of schema caching. Out-of-band SQL setup
of generation columns, tables or triggers does not publish Directus schema-change
events. The deployment coordinator must run the approved schema setup, verify
trigger coverage, then explicitly clear CMS system/schema caches or recreate CMS
before exercising the new API. Existing Redis and `CACHE_AUTO_PURGE` settings stay
in effect. This candidate authorizes no shared runtime or schema mutation itself.
