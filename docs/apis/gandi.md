# Gandi anonymous domain search research

Tested 2026-10-01 from the dev `api` container. The provider and Hosting skill
are implemented in the task workspace; programmatic integration verification is
pending. The anonymous shop endpoints are not a supported Gandi API contract.

## Live evidence

[Probe fixtures](../plans/hosting-search-domains/evidence/gandi-search-probe-2026-10-01.json)
contain 36 paced requests, including full public synthetic responses. The
[probe script](../../scripts/api_tests/test_gandi_search_probe.py) uses async
`httpx`, disables environment proxies, creates fresh clients without Gandi
cookies/authorization, and loads existing Webshare credentials only in memory.

| Route | Requests accepted | Complete lookup/SSE responses | Median lookup | Median SSE |
|---|---:|---:|---:|---:|
| Direct dev-server egress | 18/18 HTTP 200 | 17/18 | 0.425 s | 1.413 s |
| Existing Webshare rotating residential proxy | 18/18 HTTP 200 | 17/18 | 1.046 s | 6.561 s |

The one incomplete case on each route was the exploratory, unsupported encoding
`tlds=com,net`: the server opened SSE, returned no suggestions, then stalled.
Both requests hit the 15-second idle timeout. All other tested encodings
completed. Complete responses include intentional negative cases, not only
available domains. This small sample does not establish uptime, capacity, or
published rate limits. Requests were sequential with a one-second pause; no
load test, registration, account access, or infrastructure mutation was performed.

Cases: registered `example.com`; three repeated synthetic `.com` lookups;
USD/US `.net`; Unicode `bücher-probe-20261001.com`; `.ai` minimum term;
unsupported `.invalid`; a domain containing a space; repeated keyword,
multiword and exact-word searches; single/repeated/comma TLD filters; and
the public premium domain `cedar.online`.

## Endpoints and request fields

| Method | URL | Format | Authentication |
|---|---|---|---|
| GET | `https://api.gandi.net/v5/domain/check?name=example.com` | Official REST | HTTP 401 without PAT/API key |
| GET | `https://shop.gandi.net/api/v5/suggest/lookup` | JSON | No Gandi credentials or cookies in successful tests |
| GET | `https://shop.gandi.net/api/v5/suggest/suggest` | `text/event-stream` | No Gandi credentials or cookies in successful tests |

Common tested fields are `search`, `currency`, `country`, and `grid=A`.
Suggestions additionally accept `lang=en`, `page=1`, `per_page=5`,
`source=shop`, `lock_sentence=false/true`, `phases=golive`, and `tlds`.
The probe sent a browser-style User-Agent and shop Referer; SSE also sent
`Accept: text/event-stream`. These headers worked; their individual necessity
was not isolated. The first plain suggestion attempt in the initial research
received HTTP 403 abuse. An OpenMates browser Origin received HTTP 400 CSRF
and no CORS allowance. Requests belong on the server.

`tlds=net` returned `.net` results. Repeated `tlds=com&tlds=net` produced only
`.com` results in this sample. Do not promise a multi-TLD filter using that
encoding. Comma encoding stalled on both routes. Implement explicit-TLD name
checks with bounded exact lookups; keep suggestion searches to one upstream
TLD per request and enforce requested extensions on normalized results.

`lock_sentence=true` is not an exact-domain lookup: `example.com` still
returned other `example.*` domains. Both multiword modes returned individual
word suggestions, with different lists between routes. Use `/lookup` for an
explicit FQDN. Do not silently treat a natural-language product brief as a
Gandi name keyword; the AI should propose a short name/keyword first.

## Response contract observed

Lookup returns `fqdn`, `availability`, numeric `premium`, and `prices`.
Unavailable results can have `prices: {}`. `.invalid` returned HTTP 200 with
`availability: error`; `bad domain.com` returned HTTP 200 with `unavailable`.
Validate names locally and distinguish unknown/error from unavailable.

Pricing contains `currency`, `grid`, `taxes`, and `products`. Products carry
`process` (`create` or `renew`), `name`, `status`, `prices`, and `phases`.
Standard product names are suffixes such as `.com`; premium product names can
be the complete domain. Attach prices to the lookup/event `fqdn`, not to
`products[].name` as the domain identity.

Each price tier contains `duration_unit`, `min_duration`, `max_duration`,
`price_before_taxes`, `price_after_taxes`, `discount`, optional normal prices,
`type`, `options`, and `features`. Preserve tiers and distinguish registration
from renewal: a normal registration price is not the renewal quote.
The official [Domain API price schema](https://api.gandi.net/docs/domains/#domain-availability)
describes the duration range over which a price unit applies. The shop is a
separate undocumented interface, so checkout amounts remain indicative.

For synthetic `.net`, EUR/DE returned €14.27 for the one-year registration
tier and €47.60 for the one-year renewal tier, including 19% VAT. USD/US
returned $12.99 registration, $39.98 renewal, and an empty taxes list.
`.ai` had a two-year minimum for both processes: never label it a one-year
offer. `cedar.online` was premium and returned €356.36 registration and
€1,292.51 renewal, with a €1,200.50 normal registration price, including
German VAT. These are dated examples, not current purchase guarantees.

Suggestion SSE events observed:

| Event | Meaning / normalization |
|---|---|
| `suggest_meta` | TLD filter list, opaque search UUID, filter status |
| `pagination` | Raw count/page/next/last; raw count is not an available-domain count |
| `suggestions` | Ordered domain candidates with suffix, corporate flag, language support, categories, phase, restriction |
| `das`, `das_failed` | Availability/premium/reserved status for one FQDN |
| `billing`, `billing_failed` | Pricing or missing pricing for one FQDN |
| `bundle_available`, `bundle_pricing` | Shop bundles; outside initial skill scope |
| `tick` | Heartbeat, not result content |
| `done` | Stream completed |

Events arrive in different orders. Join by FQDN, preserve candidate order, and
require bounded stream completion. An `available` result can have no pricing.
An individual result can report `error` even when the overall stream completes.
`cedarcom.et` alternated between available and error. Never convert that error
to unavailable or fabricate a price. Preserve complete useful children if the
stream times out and mark the response partial.

Explicit lookup availability/pricing was consistent between direct and proxy
for the paired sample. Suggestions differed: the third `cedarcomet` candidate
was `.fi` directly and `.nl`/`.yt` via the proxy despite `country=DE`.
Treat ranking/localization as provider-dependent, not deterministic parity.

## Proposed fallback and limits

Try direct first. On transport timeout, HTTP 403, 5xx, malformed response, or
incomplete stream, allow one bounded attempt through the existing Webshare
proxy. Preserve useful partial children and deduplicate by canonical FQDN.
For per-domain transient errors retry only affected exact lookups, within the
same attempt/result budget. A valid unavailable answer is a successful lookup.
Local validation errors, an unsupported suffix, or missing price alone do not
justify rotating the full search. Honor HTTP 429/Retry-After; do not rotate
repeatedly to evade limits. No infinite retries or proxy cycling.

Proposed bounds: 1–5 grouped requests, default 10/max 20 results per request,
at most two suggestion pages or 20 exact lookup candidates per group, two
in-flight Gandi operations, and a 40-second deadline per group including
fallback. Use an explicit timeout/content/event limit. Retain only known schema
fields and build external links from the fixed Gandi shop origin.

Domain searches can be sensitive. Prefer request-scoped deduplication; do not
put plaintext queries/results in a shared persistent cache or diagnostic logs.
If a cross-request cache is later needed, its encryption and TTL require an
explicit design. User-facing checked-at timestamps belong to encrypted embed
content; transport mode remains operational metadata.

## Credentials, privacy, and operating assumptions

No Gandi user account or key is required by the tested shop interface. Proxy
fallback uses the existing Vault path `kv/data/providers/webshare`, keys
`proxy_username`/`proxy_password`, with its rotating residential endpoint.
Never import an AI/app skill to obtain that helper; shared transport/secrets
logic belongs in `backend/shared/`. Gandi receives the selected name/keyword,
currency/country/language and server/proxy request metadata. Do not send chat
context, OpenMates identifiers, email, or user credentials. Webshare is an
additional network service; use HTTPS with normal certificate verification
and accurately document the proxy's metadata exposure before launch.

Gandi's [authentication docs](https://api.gandi.net/docs/authentication/) require
authentication for its official API. Shop search has no published integration
SLA, rate limit, or fee verified here. Proxy bandwidth has an existing service
cost; do not assume it is free or add a Gandi API-key requirement.

[Website terms](https://www.gandi.net/en/contracts/terms-of-use),
[privacy policy](https://www.gandi.net/en/contracts/privacy-policy), and
[shop robots.txt](https://shop.gandi.net/robots.txt) were inspected on 2026-10-01.
Robots disallows crawl URLs containing several search-related parameters.
The terms discuss restrictions on copying/redistributing website data; these
tests establish technical feasibility, not permission for a commercial
anonymous API integration. Record the intended use/terms decision before
launch. No claim about mass WHOIS access is made: that is a separate service.
Update Gandi and relevant Webshare privacy disclosures when implementation is
approved; the policy URL above resolved to the actual Privacy Policy page.

## Reproduce

From an authorized dev session, without printing secrets:

```sh
docker exec -i api python - --mode both < scripts/api_tests/test_gandi_search_probe.py
docker exec -i api python - --mode both --case registered --case premium < scripts/api_tests/test_gandi_search_probe.py
```

`--list`, `--mode direct|proxy|both`, and repeatable `--case` are supported.
There is no Gandi `--api-key`: the tested path is deliberately credential-free.
The script reports request/schema completeness separately from domain status.
The saved fixture includes two expected exploratory filter failures; a live
rerun is an external provider probe, not a product E2E pass.

## Hosting skill contract

`hosting/search_domains` uses the existing authenticated OpenMates skill route.
Gandi itself needs no API key. Initial quote currencies are EUR and USD, which
were verified by the probe; the tax-country default is returned explicitly as DE.

```json
{
  "requests": [{
    "id": "name-ideas",
    "query": "cedarcomet",
    "tlds": ["com", "net"],
    "country": "DE",
    "currency": "EUR",
    "max_results": 10,
    "availability": "prefer_available",
    "relevance_criteria": "Prefer a short name with low evidenced renewal cost."
  }]
}
```

POST this body to `/v1/apps/hosting/skills/search_domains`, or use:

```sh
openmates apps hosting search_domains --input '{"requests":[{"query":"cedarcomet","max_results":10}]}' --json
```

One app call accepts one to five independent searches in `requests`. Groups run
concurrently, share the two-operation provider limit, and preserve caller IDs
and response order. For example, check two exact domains in one CLI call:

```sh
openmates apps hosting search_domains --input '{"requests":[{"id":"first","query":"example.com","availability":"all"},{"id":"second","query":"example.net","availability":"all"}]}' --json
```

The npm SDK exposes `client.apps.hosting.searchDomains(input)`; the pip SDK
exposes `client.apps.hosting.search_domains(input)`. Both accept the same grouped
input. Each group defaults to ten selected results and permits at most twenty.

The default `prefer_available` selects available names first and fills a shortfall
with matching checked in-use domains. `available_only` never fills with in-use
domains. `all` preserves ranked available and in-use candidate order. Unknown
checks are diagnostic evidence and cannot fill result slots. Explicit FQDNs use
exact lookup, so an in-use exact query remains visible under the default policy.

Groups expose selected `results` bounded by `max_results` and a separate
`checked_results` pool bounded by 40. Quotes retain registration and renewal
tiers, original duration ranges, taxes, premium status and restrictions.
Nonblank `relevance_criteria` makes one bounded shared Jev decision after hard
filters, removes scores below one, and reports `relevance_applied`. Evaluator
failure preserves provider ordering and availability selection with a warning.

The implementation permits two simultaneous provider operations and a 40-second
group deadline. Completed checks survive a deadline. Direct requests precede one
lazy Webshare fallback; missing prices, valid in-use answers and rate limits do
not trigger repeated proxy attempts. Proxy evidence cannot replace a confirmed
status with an unknown check. Mismatched-currency prices remain unknown.

Programmatic coverage is in `skill-hosting-search-api.spec.ts`. The separate
`scripts/api_tests/test_hosting_requirements.py` requires real dev-server Jev
inference with disposable CLI state; replay does not satisfy that check.
