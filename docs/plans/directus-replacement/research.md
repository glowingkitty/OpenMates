# Should OpenMates move away from Directus?

Research for TASK-8014, 21 Nov 2026. Research only: nothing has been changed.
The facts come from the code on `dev` and from read-only checks on the dev
server. Production was not inspected.

## Summary

- **Recommendation: yes, replace Directus, step by step.** Keep its tables
  exactly where they are and swap only the layer in front of them. Start now
  with the Postgres upgrade, which is needed in every option.
- **Directus is not a CMS for us.** For OpenMates it is a slow HTTP proxy to
  Postgres, plus the session-token engine, plus a host for 13 small extensions.
  Every request uses one admin identity, so its permission system protects
  nothing. Its file storage, Flows, hooks, GraphQL and web app are all unused.
- **The data stays put.** All data, including every client-side encrypted
  value, lives in ordinary Postgres tables (user files are in S3). Directus
  never sees plaintext. A new access layer reads and writes the same rows and
  bytes, so no data has to be moved, converted or re-encrypted.
- **Staying on Directus is a dead end.** Directus 12 changed its license. A
  free self-hosted instance may have at most 25 collections, and we have about
  214. Above that limit, after 30 days, logins for non-admin users are blocked,
  and our users' logins run through Directus. Every self-hosting operator would
  need their own license key. On 11.x we can upgrade to its last release, but
  Directus has published no support window for 11.x.
- **Gains from replacing it:**
  - Less attack surface: a large Node application that holds full admin access
    to all data goes away.
  - Faster requests: a Directus read costs about 10 ms against about 0.1 ms in
    Postgres (measured on dev).
  - A smaller database: Directus's change log takes 9.9 GB of the 12 GB dev
    database.
  - No more license or upgrade treadmill.
- **What it costs:** about 6 to 10 weeks of focused work to remove Directus
  completely. The first speed and security gains arrive after about 2 to 3
  weeks. Every step sits behind a switch, so it can be undone without touching
  data, and the old and new paths can run side by side and be compared.
- **Postgres 13 has been out of support since 13 Nov 2025.** Postgres 14 also
  went out of support on 12 Nov 2026. The upgrade (to 17, or 18) is independent
  of Directus and should come first.

The immediate Directus security mitigation runs in its own chat (Caddy already
blocks Directus paths in production). This report covers only the long-term
question.

## 1. What Directus does for us today

| Area | What the code shows | Still needed without Directus? |
|---|---|---|
| Data access | About 214 collections over 250 Postgres tables. The backend uses the Directus REST API as admin for every read and write. No Python code talks to Postgres directly: the api image has no Postgres driver. | Yes, replaced by our own layer |
| Users | `directus_users` is our user table, with about 103 custom fields (`hashed_email`, `lookup_hashes`, `vault_key_id`, `encrypted_*`, Stripe and safety fields). Passkeys live in `user_passkeys`. | The table stays; only who reads it changes |
| Login and sessions | Mixed. FastAPI checks the real credentials: passkey, password lookup hash and 2FA. Then it logs the user into Directus with a synthetic email and a password derived from that email (`services/directus/user/user_authentication.py:553`). Directus issues the refresh token, rotates it (`/auth/refresh`) and stores it in `directus_sessions`, which holds about 34k rows on dev. FastAPI re-publishes the token as its own `auth_refresh_token` cookie and caches it in Redis. | Yes. About 300 lines of auth logic move into FastAPI, on the same rows |
| Roles and permissions | Not used for protection. Users have `role=None`, and the backend uses one admin token for everything (`services/directus/auth_methods.py:181`, "Always use admin token"). Owner scoping is done in Python with `hashed_user_id` filters. | No |
| File storage | Not used. User files go straight to S3 through boto3 (`services/s3/`). The Directus uploads folder is empty. | No |
| Flows, hooks | None. No `directus_flows` and no hook extensions. All change-driven logic already lives in about 38 Postgres triggers (sync feed `pg_notify`, deletion guards, privacy generations). | The triggers stay in Postgres |
| Extensions | 13 internal endpoint extensions with about 16.5k lines of JavaScript source and 15k lines of tests: chat recovery, sub-chat orchestration with billing reservations, embed versions, chat archive, workflow runtime and authoring, anonymous usage, chat sync, project task sync, specifications, storage metering, email feedback, privacy snapshot. They are our transactional commit layer, using transactions, `FOR UPDATE` row locks and advisory locks, and two of them listen to Postgres `LISTEN` channels. **They use only three things from Directus: the database handle (knex), env and logger.** | Yes, but the code can move unchanged (see 3c) |
| Schema and migrations | `directus/setup/setup_schemas.py` creates 170 YAML collections through the Directus `/collections`, `/fields` and `/relations` API. It then runs 24 raw SQL files (212 indexes, the triggers) directly over psycopg. There is no migration history table: everything is idempotent and re-run at every setup. | Yes, replaced by Alembic |
| App-side defaults | Directus generates the UUID primary key for 203 fields (217 `uuid` id columns have no database default). It also returns its own JSON, datetime and aggregate formats, and applies a default `limit` of 100. | Yes, the new layer must copy these exactly |
| Change log | `directus_activity` and `directus_revisions` are written for all but 25 high-volume collections. On dev they take 0.75 GB and 9.9 GB. Only maintenance scripts read them. | No |
| Cache | The Directus Redis response cache is on (`CACHE_AUTO_PURGE`). | No: we already have our own cache |

**Who calls Directus:**

- **Python backend:**
  - 862 files mention `directus_service`, with at least 1,516 call sites.
  - By area: API routes 172 files, API services 79, Celery tasks 56,
    `backend/apps` 70, `backend/shared` 21, `backend/scripts` 56, root
    `scripts/` 17, tests 380.
  - About 50 non-test files skip the wrapper and make raw HTTP calls. Five
    services build their own `CMS_URL` client.
  - The Directus filter format is written by hand all over the code: `_eq`
    appears 1,948 times, `_in` 206, `_null` 189, and `aggregate` 36.
- **Directus extension endpoints:** about 20 Python modules call them.
- **Tests and CI:** 6 Playwright specs and helpers run inline Python against
  `cms:8055`, and 3 CI `.mjs` fixtures do the same.
- **Not callers:** the Rust client core, the CLI, the web app and the Apple
  apps never call Directus. The self-host CLI only runs `pg_dump` against
  `cms-database` for backups.
- **Network:** Directus is not public. It listens only on the Docker network
  and on `127.0.0.1:8055`, and no Caddyfile routes to it.

## 2. Where the data lives, and what replacement means for it

- **Postgres** holds all structured data:
  - It runs in the `cms-database` container on `postgres:13-alpine`, version
    13.23, in the volume `openmates-postgres-data`.
  - On dev the database is 12 GB, of which 10.7 GB is Directus's own change
    log.
  - The Directus system tables there fall into three groups:
    - Tables we really use: `directus_users` and `directus_sessions`.
    - Metadata tables that nothing needs once Directus is gone, such as
      `directus_collections`, `directus_fields` and `directus_permissions`.
    - The change log.
- **S3** (multi-region, through boto3) holds user files. Directus is not
  involved.
- **Vault** holds the server-side keys. Directus is not involved.

**What replacing the Directus layer means for the data: nothing is moved.**
Directus is only a program that runs SQL against these tables. The new layer
runs SQL against the same tables, columns and rows:

- No export, import or copy is needed.
- `directus_users` can keep its name.
- Encrypted values (chat content, keys, wrapped keys, memories, credentials)
  are opaque strings to both layers. The only rule is to pass them through
  byte for byte, and step 3 of the plan checks exactly that.
- Client-side encryption is untouched, because neither Directus nor the new
  layer ever has the keys.

The only data copy in the whole programme is the Postgres major-version
upgrade, which Postgres itself requires. The plan keeps the old volume
untouched as the way back.

Cleanup is a separate decision for later. It needs a backup first and owner
approval, because it deletes data:

- Directus's unused metadata tables can be dropped at the very end.
- The change log can be pruned.

## 3. Options

Measured on dev (this is the dev host, not production):

- Reading one row through Directus: median 9.7 ms, p95 14.3 ms.
- Reading 50 rows: median 16.7 ms.
- The same queries inside Postgres: 0.08 ms and 7.1 ms of execution.

So Directus adds roughly 8 to 10 ms to every database call. A chat turn,
startup sync and the billing paths each make many such calls.

### (a) Keep Directus, upgrade it and lock it down

- **What:**
  - Upgrade to the last 11.x release (11.5 to about 11.17, through the
    breaking changes listed for each 11.x minor).
  - Turn off everything we don't use: the admin web app, WebSockets, GraphQL,
    and the change log for the remaining collections.
  - Give it a least-privilege database role.
  - Allow only the api and worker containers to reach it on the network.
- **Effort:** 3 to 5 days for the upgrade and lock-down with CI. After that,
  ongoing work for every advisory.
- **Risk:** low in the short term. The extensions use only knex, which is
  stable across 11.x.
- **Security gain:** moderate. The application is still there with full admin
  power, an admin password login and its own secrets. Its own advisories keep
  coming.
- **Speed gain:** none, apart from a small one from turning off the change
  log.
- **Maintenance:** stays high, and it ends in a wall:
  - Directus 12 needs a license key for our size: 214 collections against a
    free limit of 25.
  - Over the limit, logins for non-admin users are blocked after 30 days.
  - We probably qualify for the free "Open Innovation Grant" (under 50
    employees and under $5M revenue), but every self-hosting operator would
    need their own key.
  - Licensed instances call the Directus licensing server.
  - No support window has been announced for 11.x.
- **Postgres 13:** must be upgraded anyway. Directus 11 works with current
  Postgres; this still needs proof in CI.

### (b) Thin internal data layer straight on Postgres, behind `DirectusService`

- **What:**
  - An async Postgres pool (asyncpg, with SQLAlchemy Core as the query
    builder) inside the existing api and worker processes, so no new service
    is added.
  - A translator that accepts today's Directus query format (`filter`,
    `fields`, `sort`, `limit`, `aggregate`, `groupBy`) and returns
    Directus-shaped results.
  - With that, the call sites in 862 files do not change at first. The
    `DirectusService` primitives (`get_items`, `create_item`, `_update_item`,
    `update_item_if_version`, `delete_*`, aggregates) switch underneath, one
    collection at a time.
  - Login, refresh and logout move into FastAPI on the same
    `directus_sessions` and `directus_users` rows, accepting the existing
    tokens so nobody is logged out.
  - Alembic takes over schema changes, starting from a baseline stamped from
    the current schema without touching any data.
- **Effort:** about 6 to 10 weeks to finish, including the extensions (see 3c)
  and the self-host CLI update path. The read path and its speed gain come
  after about 2 to 3 weeks.
- **Risk:** medium, and controllable.
  - The real dangers are small behaviour differences: the default 100-row
    limit, datetime and JSON formats, aggregates returned as strings,
    app-side UUIDs, and empty `_in` lists.
  - The other danger is session continuity: if tokens are not accepted, every
    user is logged out.
  - Both are caught by running the two paths side by side and comparing them
    before any switch. The switch is a flag, and both paths use the same rows,
    so going back never needs data repair.
- **Security gain:** high.
  - The Node application with full admin power over all user data goes away,
    together with its admin password, `DIRECTUS_SECRET`, admin token cache and
    HTTP surface.
  - Database access can use narrow Postgres roles. The runtime role gets no
    rights to change the schema.
- **Speed gain:** about 8 to 10 ms per database call. A connection pool
  replaces HTTP plus Directus's permission and schema checks. Change-log
  writes stop.
- **Maintenance:** we own roughly 3 to 5k lines of plain, tested Python
  instead of a vendor application. There are no license keys or vendor
  upgrades, and one container less for self-hosters.
- **Postgres 13:** upgraded first and separately (step 1 below), so a database
  change and a code change never land at the same time.

### (c) Other options

1. **Re-host the 13 extensions unchanged in a minimal internal Node service.**
   - This is the credible shortcut, and I recommend it as part of (b).
   - The extensions are plain Express routers that take `{database, env,
     logger}`. A host of about 150 lines (Express, knex and pg) can serve the
     same URLs with the same token check.
   - The 16.5k lines of transaction logic and their 15k lines of tests move
     without a rewrite.
   - Both hosts can run at the same time, because all locking and transactions
     happen inside Postgres.
   - Porting them to Python (or to Rust later, when the parked backend Rust
     plan resumes) then becomes optional, one extension at a time.
2. **Another generic API server** (PostgREST, Hasura, Supabase): replaces one
   general-purpose data server with another. The attack-surface problem
   stays, and our query format and transactional extensions do not fit it.
   Not recommended.
3. **Fork Directus 11 and patch it ourselves:** we would own a large Node
   codebase we don't use. This is the worst maintenance option.
4. **Wait for the backend Rust migration** (`docs/plans/backend-rust-migration`,
   parked): that plan explicitly leaves Directus in place and would otherwise
   build a Rust Directus client. Going straight to Postgres now makes that
   later work smaller, but waiting leaves the security and license problem
   open for many months. Not recommended.

## 4. Migration plan (if Marco chooses (b) with (c1))

These rules apply to every step:

- It is behind a switch, and it lands on dev first and stays green there
  before it reaches production.
- Production gets a fresh `pg_dump`, plus a test restore into a scratch
  database, before each step.
- Nothing is deleted until the very last step, and that step needs owner
  approval.

0. **Preparation (about 2 days).**
   - Check production backup and restore end to end.
   - Measure production's database size, change-log size and Directus calls
     per request (add a timing metric to `_make_api_request`).
   - Keep the lock-down quick wins from option (a) in place in the meantime.
1. **Postgres 13 to 17 or 18 (about 3 to 5 days).**
   - Dump and restore into a new volume, and leave the old volume untouched.
   - Directus keeps running on top, and CI proves it still works.
   - Self-hosters get the upgrade through `openmates server update`, which
     already takes a backup first.
   - Way back: point the container at the old volume.
2. **Additive database preparation (about 2 days).**
   - Add `DEFAULT gen_random_uuid()` to the UUID primary keys Directus fills
     today, and add the date defaults.
   - Create narrow Postgres roles for the api, the workers and migrations.
   - Way back: drop the defaults and roles. No row changes.
3. **New layer in shadow mode (about 1 to 2 weeks).**
   - Build the pool and the translator.
   - On dev and in CI, reads still come from Directus, and a sample is also
     run through SQL and compared field by field, encrypted values byte for
     byte. Differences are logged and fixed.
   - Move the roughly 50 raw-call files and the 5 separate `CMS_URL` clients
     onto the shared primitives. This can run in parallel with the rest of the
     step.
   - Nothing changes for users. Way back: switch shadow mode off.
4. **Reads switch, collection by collection (about 1 week).**
   - A list of collections decides which reads go to SQL. Directus still does
     every write.
   - Way back: remove a collection from the list.
5. **Writes switch, collection by collection (about 1 to 2 weeks).**
   - This includes optimistic version updates and bulk deletes.
   - Directus keeps running, so the way back is again only the switch: both
     paths write the same rows, so nothing needs reconciling.
   - The change log stops growing for switched collections.
6. **Extensions in the small Node host (about 1 week).**
   - Same code, same URLs and the same internal token, running beside
     Directus.
   - The Python callers switch their base URL, one extension at a time.
   - Way back: switch the URL back.
7. **Login and sessions in FastAPI (about 1 week).**
   - Copy Directus 11.5's exact token storage and rotation on
     `directus_sessions`, so existing sessions keep working.
   - First validate in parallel and compare with Directus, then switch.
   - Way back: the switch. Same rows, nobody logged out.
8. **Schema ownership to Alembic (about 3 to 5 days).**
   - Stamp a baseline from the live schema.
   - Retire the REST part of `setup_schemas.py`.
   - Move the test fixtures that call `cms:8055` (6 Playwright, 3 `.mjs`) onto
     a test helper.
9. **Directus off, not deleted.**
   - Stop the `cms` container on dev for a week with the full suites green,
     then do the same in production.
   - Keep the image, its secrets and its tables.
   - Way back: start the container.
10. **Cleanup, only with owner approval and after a backup.**
    - Remove `cms` from compose and from the self-host CLI.
    - Drop the Directus metadata tables, and prune or drop the change log.
    - Rotate the remaining secrets.

**Proof at each step:**

- The existing pytest and E2E suites run against the switched paths.
- The comparison logs from step 3 must be empty for each switched collection.
- A web and an Apple login, sync and decrypt run after each production step.

Once Marco decides, the durable Plan (`/create-plan`) and the owning
Specification for the data-access contract follow.

## Open points for Marco

- **Go or no-go on (b) with (c1).** The alternative is (a) for now, deciding
  again before 11.x support ends.
- **The Postgres target:** 17, which is conservative, or 18, which is the
  newest.
- **Whether to prune the Directus change log early.** It is 9.9 GB on dev;
  production is unknown until step 0.

## Sources

- Code on `dev` (paths above). Dev database figures come from read-only
  queries on 21 Nov 2026.
- Directus 12 breaking changes:
  https://directus.com/docs/releases/breaking-changes/version-12
- Directus 12 license change and pricing:
  https://directus.com/resources/directus-v12-license-change,
  https://directus.com/pricing
- Directus extended security updates (precedent for 10.x):
  https://directus.com/resources/extended-security-updates-directus-10-12
- Postgres 13 end of life:
  https://www.percona.com/blog/postgresql-13-is-reaching-end-of-life-the-time-to-upgrade-is-now/
