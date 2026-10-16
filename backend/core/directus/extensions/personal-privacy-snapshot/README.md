This internal service endpoint supplies first-party Personal privacy batches.
It accepts only `X-Internal-Service-Token`; neither a developer API key nor a
client session can call Directus directly. The API checks the exact current
session, device, owner and risk state before invoking it. Team rows are excluded.

The SQL-owned `personal_privacy_generations` table is not a registered Directus
collection and has no client permissions or revision/accountability snapshots.
An epoch and bigint counter cover all Personal Memory insert/update/delete and
changed user `encrypted_settings` writes in the same PostgreSQL transaction,
including admin, imports and raw SQL. Moving a row between owners or between
Personal and Team updates the appropriate Personal clocks. Memory truncation,
clock rollback/equal reset, deletion/recreation and schema initialization reset
epochs. Database backup restoration must run the initializer before serving
traffic; raw restoration without initialization is outside this protocol.

The extension verifies enabled triggers on their exact relations, acquires the
owner clock `FOR SHARE`, and keeps it through the encrypted settings and Memory
reads. Mutation triggers acquire the same clock before commit. Equality reads
only trigger enforcement and generation; ciphertext bodies are never loaded.
Missing extension or enforcement returns no reusable generation and the API
uses a full uncached batch. Other read errors fail closed.

Deployment requires rebuilding the CMS extension image and running CMS setup
with `migrate_personal_privacy_generation.sql`, then restarting/recreating CMS
as appropriate to clear Directus schema/system caches. Dev compose mounts the migration; self-host compose uses the setup image
that copies it. Isolated CI mounts the
setup directory and fingerprints both setup and extensions. No shared database
or runtime mutation was performed while preparing this change.

WebSocket capability is `personal_send_context_snapshot_v2`. Requests carry
`request_id`, `purpose: prepare|send`, `turn_id` (null for prepare), and optional
`known_generation`. Success replies carry opaque `privacy_generation` or null,
`unchanged`, `receipt_id` (null for prepare), `turn_id`, fresh Project candidates,
and `personal_memories` only for full reads. Project routing is read independently
on every send because its freshness is not certified by the privacy clock.

Preparation is bounded to once per socket. Send requests retain existing
per-session/user limits and may repeat. Up to eight live pending receipts coexist;
capacity returns an explicit error without evicting another valid turn. Expired
receipts are pruned and accepted exact-envelope replay records remain bounded.
The 30-second send receipt is held on that exact socket, binds user/session/device,
Personal scope, turn and generation, and is consumed before durable admission.
Only a successfully admitted exact envelope can replay the consumed receipt for
a lost ACK; modified requests never reuse it. Reconnect recovery obtains a fresh
receipt for the same turn and uses the existing durable idempotency transaction.
Phase telemetry records fresh authentication, generation read, snapshot read,
serialization and admission authentication durations without ciphertext/tokens.
