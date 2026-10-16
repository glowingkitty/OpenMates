# Bundesagentur für Arbeit public Jobsuche reader

Verified 2026-10-13 against live BA responses and the [community-maintained endpoint description](https://github.com/bundesAPI/jobsuche-api). **BA does not publish an official supported public API contract for this endpoint.** Changes to behavior or access may require disabling this source. Reuse rights are uncertain under the [BA terms](https://www.arbeitsagentur.de/nutzungsbedingungen); this reader performs ordinary bounded search and returns links to BA, without bulk storage, contact extraction, CAPTCHA bypass, or application submission.

| Endpoint | Purpose | Authentication |
| --- | --- | --- |
| `GET https://rest.arbeitsagentur.de/jobboerse/jobsuche-service/pc/v6/jobs` | Search, returning `ergebnisliste[]` | Public client header `X-API-Key: jobboerse-jobsuche` |
| `GET https://rest.arbeitsagentur.de/jobboerse/jobsuche-service/pc/v4/jobdetails/{base64(ref)}` | Optional description for returned result | Same public client header |

The header is the public client identifier shown in the community API description, not a private secret. Search parameters include `was` for query, `wo` for location, `umkreis` for radius in kilometres, `angebotsart` for role category, `arbeitszeit` for full/part time, `veroeffentlichtseit` for recent listings, plus `page` and `size`. The wrapper limits searches to two pages of 50, returns at most 10 jobs, and fetches details only for final results. It uses an 8-second timeout and two short retries on 429, transient server errors, or transport errors. A search failure becomes a safe provider error; detail failures keep the search result with a null description.

| Normalized field | BA source |
| --- | --- |
| `id`, `provider`, `url`, `apply_url` | `arbeitsagentur:<referenznummer>`, `arbeitsagentur`, canonical BA job page. `apply_url` links to that page. |
| `title`, `company`, `location` | `stellenangebotsTitel`, `firma`, first `stellenlokationen[].adresse`. |
| `country`, `published_at` | `DE`; `datumErsteVeroeffentlichung`, falling back to `veroeffentlichungszeitraum.von`. |
| `description` | Plain text from v4 `stellenangebotsBeschreibung`, when available. |
| `remote` | True only for an explicit fully remote enum, false only for an explicit `homeofficemoeglich=false`; otherwise null. The common `NACH_VEREINBARUNG` value is **not** fully remote evidence. |
| Salary fields | Null; BA v6's `verguetungsangabe` is not a reliable numeric range. |

`country` other than DE returns no results. `radius_km` requires a location and is bounded to 0–200 km; the provider enforces geographic radius. Unsupported employment types return a safe `unsupported_filter` error. `impact_area` is accepted for the common signature but not natively filtered. A zero-result response remains empty, and the fixed page bound means high-filter searches may miss matches after page two.

Example source: `{"referenznummer":"10001-123-S","stellenangebotsTitel":"Engineer","firma":"Example GmbH","arbeitszeitVollzeit":true,"homeofficemoeglich":true,"homeofficetyp":"NACH_VEREINBARUNG"}`. It becomes `id=arbeitsagentur:10001-123-S`, `employment_type=full_time`, `remote=null`, with a canonical BA listing URL.

BA access is free for ordinary public searches; no published per-request price or rate limit was found. The [BA privacy page](https://www.arbeitsagentur.de/datenschutz) explains that employer contact details are protected against automated collection. This wrapper does not request those details.
