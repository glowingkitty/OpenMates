---
status: active
doc_type: how-to
audience:
  - technical-users
last_verified: 2026-11-03
---

# App Packages

App packages let a server operator add **providers** to existing app skills on
their own OpenMates server. A typical example: your website publishes events
through its own JSON API, and you want the events search skill to include those
events for everyone on your server.

Architecture and package format: [instance app packages](../architecture/apps/instance-app-packages.md).

> **Server execution warning.** An app package contains executable code that
> runs on your server for every user request that selects its provider. Install
> only packages you built yourself or whose source you have reviewed. OpenMates
> isolates package code (see [Isolation](#isolation)), but it cannot make an
> untrusted program trustworthy: a provider sees the search input of the
> requests it serves, the secrets you configure for it, and has outbound
> internet access.

## 1. Enable app packages

App packages are off by default. Enable them in the server environment and
restart:

```bash
openmates server env set OPENMATES_APP_PACKAGES_ENABLED --value true
openmates server restart
```

The hosted OpenMates production service ignores the flag, and the `apps`
commands refuse to run there: packaged providers are not billed.

With the flag off nothing is read from the package directory, even if packages
are installed.

The package directory is `<install path>/.openmates/app-packages`. Set
`OPENMATES_APP_PACKAGES_DIR` to use a different host path. Only the CLI writes
to it; containers mount it read-only.

## 2. Build a package

A package is a ZIP with a `manifest.yml` and one executable per CPU type. For a
provider that reads your website's events API:

```yaml
format: openmates-app-package
format_version: 1
id: org.example.website-events
version: 1.0.0
name: Website events
description: Events published on example.org.
contributes:
  providers:
    - app: events
      skill: search
      contract: events.search@1
      id: example_site_events
      name: Example site events
      runtime: executable
      entrypoint: bin/{target}/provider    # {target} is aarch64 or x86_64
      secrets: [api_key]
      skill_hint: >-
        Use for events published on example.org.
```

```text
website-events-1.0.0.zip
├── manifest.yml
└── bin/
    ├── aarch64/provider
    └── x86_64/provider
```

The executable reads one JSON object on stdin:

```json
{"protocol": 1, "contract": "events.search@1", "provider": "example_site_events",
 "input": {"query": "open day", "location": "Berlin", "count": 10},
 "secrets": {"api_key": "..."}}
```

It prints one JSON object on stdout: `{"results": [...]}` or
`{"error": "short safe message"}`. For `events.search@1` each result needs
`title`, an `http(s)` `url` and an ISO 8601 `date_start`. Optional fields are
`date_end`, `description`, `venue` (object), `event_type`, `organizer`, `fee`
and `image_url`. Other fields are dropped, and invalid results are discarded.

For `jobs.search@1` the input is one jobs search request with the requested
`countries` (ISO 3166-1 alpha-2 codes), `limit` and any listing filters the user
set (`remote`, `employment_type`, `max_days_old`, `visa_sponsorship`,
`experience_levels`, `education_levels`, `start_after`, `start_before`,
`min_contract_duration_months`, `max_contract_duration_months`,
`deadline_after`, `min_salary` with `salary_currency` and `salary_period`,
`languages`). Each result needs `id`, `title` and an `http(s)` `url`. Optional
fields:

- text: `company`, `location`, `description`, `sector`, `role`, `seniority`,
  `organization_type`, `work_arrangement`, `salary_text`, `impact`,
  `impact_area`, `employment_type`, `detail_status`, `salary_currency`,
  `salary_period` (`hour`, `day`, `week`, `month` or `year`)
- `country`: the listing's own ISO 3166-1 alpha-2 code; leave it out for
  global or remote listings
- `apply_url`; booleans `remote`, `visa_sponsorship`
- ISO dates `published_at`, `valid_through` (application deadline),
  `start_date`
- numbers `salary_min`, `salary_max`; integers `contract_duration_months`
  (fixed-term length), `experience_years_min`
- `education_level`: `none`, `vocational`, `bachelor`, `master` or `doctorate`
- `experience_level`: `internship`, `entry`, `mid`, `senior` or `lead`
- `languages`: ISO 639-1 codes such as `["en", "de"]`

Leave out what the listing does not state. OpenMates applies the request's
filters to every result again and drops listings that do not state a filtered
value.

### Serve a paused skill (`skill.requests@1`)

Some built-in skills ship paused because no provider is configured (for example
appointment search in the Health app). Any such skill accepts a provider with
the generic contract `skill.requests@1`; nothing in OpenMates needs to change:

```yaml
contributes:
  providers:
    - app: health
      skill: search_appointments
      contract: skill.requests@1
      id: my_provider
      name: Example provider
      runtime: executable
      entrypoint: bin/{target}/provider
      optional_secrets: [proxy_url]   # passed only when you set it
      skill_hint: >-
        Use for appointments offered by the example provider.
```

A skill accepts it only when its `app.yml` has `provider_required: true`, no
built-in providers, no `provider_contract` and a tool schema. For a skill with a
`requests` array your executable is called once per request item; for a skill
with a flat schema it is called once with the skill's whole validated input as
`input`, and your results are returned in the skill's original response shape. Once installed, the skill becomes available, uses your `skill_hint`
(without one, its "unavailable" hint is removed) and is served by your
providers.

The executable receives one request item exactly as the skill's public tool
schema defines it, already validated:

```json
{"protocol": 1, "contract": "skill.requests@1", "provider": "my_provider",
 "input": {"speciality": "dentist", "city": "Example City", "max_doctors": 10, "days_ahead": 7},
 "secrets": {}}
```

It prints `{"results": [{...}, ...]}` with JSON objects in the shape the skill's
result cards expect, or `{"error": "short safe message"}`. The server checks the
structure only: at most 50 results, keys of letters, digits and `_`, nesting
depth at most 6, strings up to 20,000 characters, at most 64 KiB per result and
1 MiB per call. `url` and `*_url` values must be `http(s)` URLs or they are
removed. `provider` and `provider_id` are always set by the server. When
several installed providers serve the same skill, their results are interleaved
(first result of each, then the second of each, ...). A request can pick
providers by id or name with `provider`, `providers` or `provider_platform`;
otherwise all of them run. Ids such as `auto`, `all`, `any`, `none` and
`default` are reserved.

Build statically linked executables. The runner provides no language runtime,
shell tools or writable directories other than a per-call temporary directory.

## 3. Install

```bash
openmates server apps install ./website-events-1.0.0.zip --accept-server-execution
```

The CLI validates the archive and the manifest, stores the version, makes it
active and restarts the API, the Celery workers and the runner. Add
`--no-restart` to restart later yourself. Changes take effect only after a
restart.

Packages are rejected if they:

- target an unknown skill, or a skill that does not accept the declared contract
  (`skill.requests@1` only fits skills paused without any provider);
- reuse a built-in provider id or a provider id from another installed package
  (inside one package the same id may serve several skills, once per skill; those
  providers then share the same `SECRET__<PROVIDER ID>__<NAME>` values);
- contribute anything other than `providers`;
- have no executable for the server's CPU type.

## 4. Configure secrets

Each declared secret is read from `SECRET__<PROVIDER ID>__<NAME>` in upper case:

```bash
openmates server env set SECRET__EXAMPLE_SITE_EVENTS__API_KEY   # prompts for the value
openmates server restart
```

Names in `optional_secrets` (for example an outbound `proxy_url`) are read the
same way but are passed only when set and never make the provider unavailable.

Secrets are imported into Vault at `kv/data/providers/<provider id>` like
built-in provider keys. A provider receives only its own declared secrets, for
the duration of one call. While a declared secret is missing, the provider is
reported as unavailable and is never executed.

Because secrets share the built-in provider namespace, a package is rejected
when a provider id equals any built-in provider id (any app's providers,
provider configuration files, or provider secret paths such as `openai` or
`brave`) or a value the target skill already interprets (for events search:
`auto`, `none` and known conference keys). Pick a distinctive id such as
`example_site_events`.

## 5. Manage packages

```bash
openmates server apps list                               # installed packages and active versions
openmates server apps inspect org.example.website-events # manifest, versions and providers
openmates server apps rollback org.example.website-events --to 1.0.0
openmates server apps remove org.example.website-events --yes
```

Add `--json` for machine-readable output. Rollback switches the active version to one that
is already installed. Remove deletes every version of the package. Both
restart the affected services, and after a restart the skill metadata is back
to the built-in state for anything the package contributed.

## Isolation

Package code runs only in the `app-packages-runner` container:

- no access to the server environment file, Vault, the database or the cache;
- shares no network with other OpenMates services. Its only network gives it
  outbound internet access. The API and the chat and workflow workers reach it
  only through a Unix socket in a dedicated volume, so package code cannot
  connect to the API, the database, the cache or Vault;
- runs as an unprivileged user with all Linux capabilities dropped,
  `no-new-privileges`, a read-only root filesystem and a size-limited `/tmp`;
- packages are mounted read-only. Before each call the runner re-checks that
  the version is active and re-verifies the digest of every file. Changed,
  extra or linked files make the package unavailable;
- each call runs in a fresh temporary directory with a minimal environment
  (`PATH`, `HOME`, `LANG`, `TMPDIR`), a timeout of at most 60 seconds (the whole
  process group is killed), a 4 MiB output limit and discarded stderr.

### Residual network risk and mitigation

The egress network is an ordinary Docker bridge. Package code can therefore
still reach the Docker host's gateway address, any port the host publishes
(including OpenMates ports bound to the host), other hosts on private networks
and link-local addresses such as cloud instance metadata services
(`169.254.169.254`). Only install packages you trust, and block these
destinations for the runner's subnet on the host.

The network is named `openmates-app-packages-egress` and uses the fixed subnet
`10.250.71.0/24` (change it with `OPENMATES_APP_PACKAGES_EGRESS_SUBNET` in the
server environment before the first start if it overlaps a network you use).
With iptables, add rules to the `DOCKER-USER` chain, for example:

```bash
SUBNET=10.250.71.0/24
for DEST in 10.0.0.0/8 172.16.0.0/12 192.168.0.0/16 169.254.0.0/16 100.64.0.0/10; do
  sudo iptables -I DOCKER-USER -s "$SUBNET" -d "$DEST" -j DROP
done
# Traffic to the host itself (gateway and published ports) uses the INPUT chain:
sudo iptables -I INPUT -s "$SUBNET" -j DROP
# Allow replies to connections the runner opened to the internet:
sudo iptables -I DOCKER-USER -s "$SUBNET" -m conntrack --ctstate ESTABLISHED,RELATED -j ACCEPT
```

If the host uses a resolver on a private address, allow
UDP and TCP port 53 to it before the drop rules. Make the rules persistent with
your distribution's tooling (for example `iptables-persistent`); Docker does not
remove rules in `DOCKER-USER`. With IPv6 enabled on Docker, add the matching
`ip6tables` rules (`fc00::/7`, `fe80::/10`).

Provider errors are shown to users only as short generic messages such as
"Example site events did not respond in time." A failing provider does not
hide results from other providers in the same search.

## Credits

Installed providers are never charged. A search request is free when every
provider that returned results for it is an installed provider according to
the server's own registry. Requests whose results come only from built-in
providers, or from both built-in and installed providers, are charged as usual.
Flags or fields in provider output have no effect on charging. A paused skill
served only through `skill.requests@1` providers is never charged, also when
every provider fails.

## Troubleshooting

- **Provider not offered:** check that `OPENMATES_APP_PACKAGES_ENABLED=true` is
  set, that the declared secrets are configured, and that the services were
  restarted. The API log names each rejected package with the reason
  (`[AppPackages] Rejected package ...`).
- **"... is unavailable":** the runner could not verify the package. Reinstall
  it with the CLI and do not edit files in the package directory by hand.
- **"... failed" or "... reported an error":** run the executable locally with
  the stdin example above and check that it prints a single JSON object.
