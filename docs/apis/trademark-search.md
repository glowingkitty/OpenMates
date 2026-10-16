# Trademark search sources

Verified on 2026-10-11. Free services only; no paid fallback or provider account
is required by the initial US implementation.

## USPTO public website endpoint

`POST https://tmsearch.uspto.gov/prod-stage-v1-0-0/tmsearch` is the JSON endpoint
used by the current USPTO search website. The public `configuration.json` names
its base URL; the website's JavaScript constructs Elasticsearch-style queries.
This is reverse-engineered website access, **not a documented stable API** or a
claim of an API service agreement. `robots.txt` returned 404; no access challenge
was required by the tested requests. Never solve a CAPTCHA, circumvent a block,
or route failures through a paid proxy. Recheck website terms and this contract
when access or response structure changes.

The client uses structured DSL, never caller-supplied query syntax. Exact names
use `wordmarkExact`; spelling similarity uses the `WM` field with `AUTO`
fuzziness. `LD=true` includes live applications and registrations. `IC` filters
use three-digit Nice classes. One first-page request returns at most twenty
records per name. The provider reports total matches and truncation separately.
Similarity does not cover the full legal/phonetic/visual analysis of a mark.

Only candidate names and search filters are transmitted server-side over HTTPS.
No chat history, OpenMates user identity, owner address, credentials, or private
Project data is sent. Responses omit address and attorney fields. No plaintext
query/result cache is created. A worker allows one request per second; 429,
access challenges, network failures and unreadable records produce safe errors.

Live exact ADIDAS searches returned active registrations, including official
status, class, goods/services and TSDR record links; spelling-similar searches
returned a broader candidate set. No-result and multiword exact checks must
remain in the live contract script.

## Region routing and gaps

- US: USPTO public endpoint; US federal coverage only, including international
  filings effective in the US. Owner nationality is not protection territory.
- EU: no configured anonymous provider. EUIPO's official Trademark Search API
  is free, but requires an account, subscription approval and client credentials:
  https://dev.euipo.europa.eu/faq . EUIPO coverage is not every EU national office.
- DE: no configured permitted keyless provider. DPMA's robots excludes search
  routes; DPMAconnectPlus has a paid connection fee and is outside this scope.
- WORLDWIDE: not a worldwide-clearance promise. WIPO explicitly prohibits
  automatic querying: https://www.wipo.int/en/web/global-brand-database/faqs_branddb .
- TMview: its website robots allows `/tmview/`, but repeated requests to its
  current `api/general/globals` and `api/search/results` endpoints reset
  connections from this host, including ordinary website cookies. Do not claim
  working TMview coverage from successful downloads of its static JavaScript.

Unsearched regions return an explicit unsupported row with official manual
sources. Mixed searches preserve searched US records and show partial coverage.
All-failed searches are errors, never successful empty searches. No matches are
only a result of the stated search/filter/time; unregistered rights and other
jurisdictions may still matter.

The Business response stores trademark rows under `matches`, alongside coverage,
the submitted class and status filters, and exact/similar matching. This retains
the whole response through the shared saved-embed pipeline, including completed
zero-match searches. Saved TOON embeds contain that response inside their outer
`results` list; client normalization accepts both direct and saved shapes.

## Free credential upgrade: EUIPO

Rechecked on 2026-10-13. The next useful signup is EUIPO's official
[Trademark search 1.1.0](https://dev.euipo.europa.eu/product/trademark-search_110).
Both Sandbox and Production API access are
[free of charge](https://dev.euipo.europa.eu/faq), subject to subscription approval
and plan rate limits. This searches EUIPO's database; it does not establish
coverage of every national register or worldwide trademark availability.

1. [Create an EUIPO account](https://euipo.europa.eu/ohimportal/en/web/guest/login?loginmode=register).
2. Sign into the [Sandbox API portal](https://dev-sandbox.euipo.europa.eu/),
   register an application under Apps, and retain its Client ID and Client Secret.
3. Subscribe to Trademark search's available plan. It provides name searches,
   individual trademark details and associated media endpoints.
4. After successful sandbox integration tests, request a Production subscription.
   Production approval also requires identity/address documentation; a company
   applicant must supply the acting person's ID and company-register authority.
   Follow EUIPO's [getting-started guide](https://dev.euipo.europa.eu/getting-started)
   and [production requirements](https://dev.euipo.europa.eu/faq).

Sandbox data is for integration testing, not live coverage. Credentialed EUIPO
integration remains deferred; merely creating an account does not change the
current skill's coverage. Goods And Services 1.2.0 in the
[catalog](https://dev.euipo.europa.eu/product) is an optional later addition for
TMclass classification lookup/validation, not another trademark register.

Germany's [DPMAconnectPlus](https://www.dpma.de/english/search/data_supply_services/dpmaconnect/index.html)
charges a EUR 200 one-time connection fee, even though register retrieval is
free afterwards. It does not meet the free-only scope. WIPO's
[Global Brand Database terms](https://www.wipo.int/en/web/global-brand-database/terms_and_conditions)
prohibit automated queries and scraping; a normal website account is not an
automation credential. Keep official manual-search links for these gaps.
