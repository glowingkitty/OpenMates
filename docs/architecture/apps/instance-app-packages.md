# Instance App Packages

Specification: `specifications/features/instance-app-packages` (feature.instance-app-packages@1).

Server operators add providers for existing app skills with
`openmates server apps install <zip>`. Installed providers are available to all
users of that server, execute only in the isolated `app-packages-runner`
container and are never charged credits. App packages are off unless
`OPENMATES_APP_PACKAGES_ENABLED=true` is set in the server environment.

## Package format (ZIP)

```text
my-events-1.0.0.zip
├── manifest.yml
└── bin/
    ├── aarch64/provider     # executable, statically linked recommended
    └── x86_64/provider
```

```yaml
format: openmates-app-package
format_version: 1
id: my.events                 # [a-z0-9]+(\.[a-z0-9_-]+)+, max 64 chars
version: 1.0.0                # semantic version
name: My events
description: Events from my own website.
contributes:
  providers:
    - app: events
      skill: search
      contract: events.search@1        # must equal the target skill's provider_contract
      id: my_events                    # [a-z0-9_]{2,40}, not a built-in provider id
      name: My events                  # shown as provider name on result cards
      runtime: executable
      entrypoint: bin/{target}/provider  # {target} = uname -m of the runner (aarch64, x86_64)
      secrets: [api_key]               # optional; operator sets SECRET__MY_EVENTS__API_KEY
      optional_secrets: [proxy_url]    # optional; passed only when set, never affects availability
      skill_hint: >-                   # optional; replaces the skill's routing hint
        Search concerts, meetups and other events in a city.
```

Only `contributes.providers` is supported in format 1. Any other contribution
key (`skills`, `focus_modes`, `apps`, ...) is rejected as unsupported.

Archive limits: 64 MiB compressed, 256 MiB uncompressed, 2,000 entries, no
absolute paths, `..` segments, backslashes, symlinks or device files. Paths are
relative and UTF-8.

## On-disk layout

The package root is `<install_path>/.openmates/app-packages` (override with
`OPENMATES_APP_PACKAGES_DIR`). It is written only by the CLI on the host and is
mounted read-only at `/app-packages` into the API, the skill-executing workers
and the runner.

```text
registry.json
packages/<package_id>/<version>/manifest.yml
packages/<package_id>/<version>/install.json
packages/<package_id>/<version>/files/<archive paths...>
```

`registry.json` (written atomically: temp file + rename, under a lock):

```json
{
  "format": 1,
  "revision": 7,
  "active": {"my.events": {"version": "1.0.0", "sha256": "<archive sha256>"}},
  "installed": {"my.events": ["1.0.0", "1.1.0"]}
}
```

`install.json`:

```json
{
  "package_id": "my.events",
  "version": "1.0.0",
  "archive_sha256": "<hex>",
  "installed_at": 1793180254,
  "file_digests": {"bin/aarch64/provider": "<sha256 hex>", "manifest.yml": "<sha256 hex>"}
}
```

`manifest.yml` is stored both at the version root and inside `files/`.
`file_digests` covers every regular file under `files/`. The loader and the
runner both read `files/manifest.yml`; the loader rejects the package when its
sha256 differs from `file_digests["manifest.yml"]`. The version-root copy is
informational only.

## Runner protocol

The runner serves HTTP only on the Unix domain socket
`/run/app-packages-runner/runner.sock` (override with
`OPENMATES_APP_PACKAGES_RUNNER_SOCKET` for callers and
`APP_PACKAGES_RUNNER_SOCKET` for the runner). The socket lives in the dedicated
tmpfs volume `app-packages-runner-socket`: the runner mounts it read-write
(uid 65534, socket mode 0666, stale socket removed on start), and only the
callers `api`, `app-ai-worker` and `workflow-worker` mount it read-only. Clients
use the base URL `http://app-packages-runner` over that socket. The runner
shares no Docker network with OpenMates services; its only network,
`app-packages-egress` (Docker name `openmates-app-packages-egress`, fixed
subnet `${OPENMATES_APP_PACKAGES_EGRESS_SUBNET:-10.250.71.0/24}`), provides
internet access. `runner.py --healthcheck` probes `/v1/health` over the socket.

Residual risk: the egress bridge can still reach the Docker host gateway, ports
published on the host, private networks and link-local metadata endpoints
(`169.254.169.254`). The fixed subnet lets operators drop RFC 1918, CGNAT and
link-local destinations from it in `DOCKER-USER` and host traffic in `INPUT`;
the operator guide (docs/self-hosting/app-packages.md, "Residual network risk
and mitigation") gives the rules. OpenMates does not install host firewall
rules itself.

`POST /v1/run`

```json
{
  "package_id": "my.events",
  "version": "1.0.0",
  "provider_id": "my_events",
  "contract": "events.search@1",
  "input": {"query": "techno", "location": "Berlin", "count": 10},
  "secrets": {"api_key": "..."},
  "timeout_seconds": 30
}
```

Before running, the runner re-reads `registry.json`, requires
`active[package_id] == {version, sha256 from install.json}`, and re-verifies every
digest in `install.json`. It then executes the entrypoint with:

- stdin: `{"protocol": 1, "contract": ..., "provider": ..., "input": ..., "secrets": ...}`
- environment: only `PATH`, `HOME=/tmp/run`, `LANG=C.UTF-8`, `TMPDIR=/tmp/run`
- working directory: a fresh temporary directory, removed afterwards
- timeout: `min(timeout_seconds, 60)`; the whole process group is killed on timeout
- stdout limit: 4 MiB; stderr is discarded

The provider prints one JSON object on stdout:
`{"results": [ ...contract results... ]}` or `{"error": "safe message"}`.

Runner response: `{"ok": true, "results": [...]}` or
`{"ok": false, "error": "<CODE>"}` where `CODE` is one of `PACKAGE_UNAVAILABLE`,
`EXECUTION_FAILED`, `TIMEOUT`, `OUTPUT_TOO_LARGE`, `INVALID_OUTPUT`,
`PROVIDER_ERROR` (with an additional sanitized `message` of at most 300 chars).
`GET /v1/health` returns `{"ok": true}`.

The worker validates every result against the contract and discards invalid
entries. Results are never trusted to decide billing.

## Contracts

A built-in skill opts in with `provider_contract: <app>.<skill>@<n>` in its
`app.yml` skill definition (today Events search and Jobs search). Paused skills without any provider accept the
generic `skill.requests@1` contract without any `app.yml` change.

| Contract | Target | Input | Output result |
|---|---|---|---|
| `events.search@1` | skills with `provider_contract: events.search@1` | one `EventsSearchRequestItem` (`query`, `location`, `lat`, `lon`, `start_date`, `end_date`, `event_type`, `count`, `past_events`) | `EventResult`: `title`, `url` (http/https), `date_start` (ISO 8601) required; optional `date_end`, `description`, `venue` (object), `event_type`, `organizer`, `fee`, `image_url` |
| `jobs.search@1` | skills with `provider_contract: jobs.search@1` | one validated `JobsSearchRequestItem` (`model_dump(mode="json", exclude_none)`) with the resolved `countries` list (any ISO 3166-1 alpha-2 codes), the candidate `limit` and the listing filters (see below); `provider`, `providers` and `country` are removed | `job_result` (fields below) |
| `skill.requests@1` | any paused skill (see below) | one request item of the skill's public request schema | any JSON object, validated structurally (see below) |

The worker sets each result's `provider` to the contribution `name` and
`provider_id` to the contribution id; package values for both keys are replaced.

**`job_result` fields** (`validate_jobs_search_result`). Required: `id`, `title`,
`url` (http/https). Optional, dropped when invalid:

| Field | Type |
|---|---|
| `company`, `location`, `description` (up to 20,000 chars), `sector`, `role`, `seniority` (source wording), `organization_type`, `work_arrangement`, `salary_text`, `impact` (why the work matters), `impact_area` (cause label, up to 200 chars), `detail_status`, `employment_type` | text |
| `country` | ISO 3166-1 alpha-2 (upper-cased); absent for global or remote listings without one |
| `apply_url` | http/https URL |
| `remote`, `visa_sponsorship` | bool |
| `published_at`, `valid_through` (application deadline), `start_date` | ISO 8601 date or date-time |
| `salary_min`, `salary_max` | finite numbers |
| `salary_currency`, `salary_period` | text (`hour`, `day`, `week`, `month`, `year` for filtering) |
| `contract_duration_months` | integer 1–600 (fixed-term length; absent when permanent or unstated) |
| `experience_years_min` | integer 0–60 |
| `education_level` | `none`, `vocational`, `bachelor`, `master`, `doctorate` |
| `experience_level` | `internship`, `entry`, `mid`, `senior`, `lead` |
| `languages` | list of ISO 639-1 codes (lower-cased, deduplicated, at most 10) |

**Jobs listing filters** (request item fields, also passed to installed
providers): `remote`, `employment_type`, `max_days_old`, `visa_sponsorship`
(bool), `experience_levels` and `education_levels` (lists of the enums above),
`start_after`/`start_before` and `deadline_after` (ISO dates),
`min_contract_duration_months`/`max_contract_duration_months` (integers),
`min_salary` with required `salary_currency` (ISO 4217) and `salary_period`
(month and year convert, other periods must match, no currency conversion), and
`languages` (ISO 639-1; at least one stated language must match). The server
applies every filter to every listing (`backend/apps/jobs/listing_filters.py`):
a listing that does not state the filtered value is excluded. Providers may
filter server-side as well; they never need to return unstated listings.

**Jobs search routing** (`backend/apps/jobs/skills/search_skill.py`). A request
selects installed providers by id or display name in `provider`/`providers`;
`auto` runs the built-in country routing plus every installed provider.
Installed providers declare no country coverage: each receives the request and
returns `[]` when it is out of scope. When an installed provider is selected, a
built-in limit (country not covered, radius, unsupported employment type) skips
the built-in source with a `coverage_gap` / `unsupported_filter` warning instead
of failing the request. Requests accept any ISO 3166-1 alpha-2 country; the
built-in source keeps its own coverage, installed providers receive the
requested countries and each installed listing keeps its own `country`.
Installed listings pass the same listing filters, are interleaved round-robin with
the built-in listings (one source each), deduplicated by URL and then ranked by
`relevance_criteria` like built-in listings. The group's `providers` lists every
source asked for that request, so a group that also asked the built-in source
is charged as before.

## Generic contract (`skill.requests@1`)

Code: `backend/shared/app_packages/generic_contract.py` (rules),
`delegate_skill.py` (execution), `delegate_flat_skill.py` (flat schemas),
`overlay.py` (class swap).

**Eligible target.** A built-in skill accepts `skill.requests@1` when its
`app.yml` definition has `provider_required: true`, no `provider_contract`, no
built-in `providers` (empty or absent), a `class_path`, and a `tool_schema`
with properties: either a top-level `requests` array, or a flat schema without
a `requests` property (a non-array `requests` is refused). These are the skills shipped
paused for lack of a provider. Any other target rejects the package. Reserved
ids for this contract: `auto`, `all`, `any`, `none`, `default`, `unavailable`,
`multi`, in addition to the built-in provider namespace and cross-package
uniqueness.

**Overlay.** With at least one active provider for an eligible skill, the
overlay adds the provider entries, removes `default_enabled: false`, replaces
`preprocessor_hint` with the joined `skill_hint`s (or removes the paused
"unavailable" hint when no provider gives one), stores the original class path
in `delegated_class_path` and sets `class_path` to
`backend.shared.app_packages.delegate_skill.InstalledProviderSkill` (flat
schemas: `delegate_flat_skill.InstalledProviderFlatSkill`). Chat skill
execution, REST skill routes, anonymous REST and workflows all resolve the class
from this metadata, so none of them changes. The REST route builds its OpenAPI
request/response models from `delegated_class_path`. Preview metadata from the
delegate is empty (no "Unavailable" placeholder).

**Execution** (`InstalledProviderSkill.execute`), per request item, items
concurrently, at most 10 items per call:

1. Validate the item with the original skill's request item model: the typed
   `execute` parameter, else the single `*Request` model of the skill module
   whose `requests` field is a list of models, else the single `*RequestItem`
   model; without one the item must be a JSON object and is passed unchanged.
   The provider input is `model_dump(mode="json", exclude_none=True)`. An invalid
   item becomes a group error `Invalid request: <field>: <message>` and runs no
   provider.
2. Provider selection: values of `provider`, `providers` (list) and
   `provider_platform` in the raw item that equal an installed provider id or
   display name (case-insensitive) select only those providers; otherwise every
   installed provider of the skill runs.
3. Each selected provider runs concurrently through the runner with stdin
   `{"protocol": 1, "contract": "skill.requests@1", "provider": "<id>", "input": {<item>}, "secrets": {...}}`.
4. Results are merged round-robin across providers in registry order (sorted by
   package id, then manifest order): first result of each provider, then the
   second, and so on. No server-side caps beyond the validator or sorting.

**Flat schemas** (`InstalledProviderFlatSkill`, set as `class_path` instead).
The tool input (call arguments named by the public `tool_schema` properties;
context such as user or chat ids is never included) is validated by the module's
single `*Request` model without a `requests` field (or a typed `execute`
argument), nulls dropped, and the whole result is the single `input` item; the
same selectors and round-robin merge apply. The response keeps the original
`*Response` model (its defaults must validate from `{}`): results go into its
`results` field, else its first list-of-objects field; input values it declares
under the same name, or as the singular of a list input (`queries` -> `query`,
joined with ", "), are echoed, never execution fields such as `status`, `success`
or `error`; `provider`, `providers`, `error`, `warnings` and, when declared,
`result_count`, `success` and `partial` are set.

**Result validation** (`validate_generic_result`): each result must be a JSON
object; at most 50 results per provider call; keys must match
`^[A-Za-z][A-Za-z0-9_]{0,63}$`, at most 100 keys per object; nesting depth at
most 6 (the result is depth 1; deeper values are dropped); lists at most 100
items; strings truncated to 20,000 chars; integers beyond ±2^53 and non-finite
numbers dropped; a key `url` or ending in `_url` at any depth must be an
`http(s)` URL with a host and at most 2,048 chars or it is dropped. Top-level
`provider`, `provider_id`, `embed_id`, `embed_ids`, `task_id`,
`credits_charged` and `usage` are dropped before stamping. A result serialized
above 64 KiB is dropped; once the results of one call exceed 1 MiB, the rest
are dropped. A result with no usable keys is dropped.

**Response.** The standard grouped response
`{"results": [{"id": <request id or 1-based index>, "results": [...], "providers": [<ids with results>]}], "provider": "<names>", "providers": [...], "error": ...}`
built on the defaults of the original skill's `*Response` model (the first one
with a `results` field that validates with only `results`), so fields such as
`ignore_fields_for_inference` keep their values; without such a model it is a
plain dict. A provider failure is a short safe message: in `warnings` when other
providers returned results, otherwise the group's `error`. The top-level `error`
is set only when every group failed; a `success` field of the original model is
set to `not all_failed`.

## Secrets

A provider declaring `secrets: [api_key]` reads
`SECRET__<PROVIDER_ID upper>__<NAME upper>` (here `SECRET__MY_EVENTS__API_KEY`),
set with `openmates server env set`. The existing Vault import stores it at
`kv/data/providers/<provider_id>` key `<name>`. The worker resolves only the
declared names for the invoked provider and sends them in that call.
`optional_secrets` (same name rules, no overlap with `secrets`) resolve from the
same place, are included only when set, never affect availability and are
redacted from provider error messages like required secrets.

Provider ids share that namespace with built-in providers, so the loader
(`backend/shared/app_packages/reserved_ids.py`) rejects a package whose provider
id equals any id derived at load time from: provider ids and names in every
built-in `app.yml`, `backend/providers/*.yml` (`provider_id` and file name),
module names under `backend/shared/providers`, and `kv/data/providers/<id>` /
`SECRET__<ID>__` references in backend code, compose files and `.env.example`.
It also rejects selector values the target skill interprets itself, declared per
contract in `contracts.RESERVED_PROVIDER_ID_SOURCES` (events search: `auto`,
`none`, provider aliases and conference keys; jobs search: `auto` and the
built-in source aliases). Rejected packages never load, so
their secrets are never resolved. Provider ids are also unique across packages; inside one
package the same id may serve several skills (once per skill) and then shares its
secrets between them.

## Availability and billing

- With the flag on, each process loads `registry.json` at startup. Active
  provider contributions are added to their target skill's providers. A skill
  shipped with `default_enabled: false` (paused) becomes available while at least
  one installed provider targets it, and its parent app becomes discoverable.
- Install, rollback and remove restart `api`, every Celery worker (each builds
  the skill registry at startup) and the runner. These are exactly the services
  that mount the package root; Celery beat (`task-scheduler`) does not.
- A request group is not charged when every provider that returned results for it
  is an installed provider according to the server's registry. Mixed groups and all
  built-in-only groups are charged unchanged.
- A skill served through `skill.requests@1` has no built-in provider (the loader
  only accepts such targets), so while the registry lists only generic-contract
  providers for it, none of its request groups is charged, including groups
  where every provider failed (`billing.served_only_by_installed_providers`).
  Package output never influences this.
