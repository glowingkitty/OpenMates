# Arbeitnow public job feed

Verified 2026-10-13 against [Arbeitnow's API announcement](https://blog.arbeitnow.com/blog/job-board-api) and a live page response.

The Jobs search wrapper reads `GET https://www.arbeitnow.com/api/job-board-api?page=N`. The multi-country feed requires no key. Responses contain `data[]` and `links.next`; a job exposes `slug`, `company_name`, `title`, HTML `description`, Boolean `remote`, `url`, `job_types`, `location`, and Unix `created_at`. The feed says it updates hourly, orders by creation date, asks clients not to abuse the API, and appreciates a link back. The public feed has no searchable query, location, or radius parameter; the wrapper filters locally.

| Input | Handling |
| --- | --- |
| `query`, `location`, `remote`, `employment_type`, `max_days_old` | Local filters over at most three newest pages. |
| `country` | Germany only; unsupported country returns no results. |
| `radius_km` | Unsupported; returns a safe `unsupported_filter` error. |
| `impact_area` | Accepted for the common signature; semantic matching belongs to Jobs search. |
| `limit` | Capped at 20. |

Each result has `id=arbeitnow:<slug>`, `provider=arbeitnow`, title, company, canonical HTTPS board URL, location, `country=DE`, the feed's explicit remote Boolean, normalized employment type, UTC publication time, plain text description, and nullable salary fields. `apply_url` points to the board listing. HTML is stripped; URL credentials, non-HTTPS links and fragments are rejected. Only records whose location explicitly names Germany, Deutschland, or a standalone DE country code are emitted as `country=DE`. City-only, remote-only, missing, and unrecognized foreign locations are excluded because the same `.com` feed currently includes jobs from several countries and provides no structured country field. This conservative policy omits some genuine German jobs with city-only labels.

Pages are cached in memory for 10 minutes and no search reads beyond three pages. Sparse matches may exist farther back, so an empty result does not prove there are no matching jobs on Arbeitnow. Requests use an 8-second timeout and at most two short retries for transient errors. Rate limits become a safe error, not an empty result. Pricing for the public feed is free according to Arbeitnow; higher-volume tailored feeds are commercial. Exact public rate limits are not stated. **The current [terms](https://www.arbeitnow.com/terms) contain two provisions whose interaction needs clarification for commercial reuse:** §2 limits the generic website-materials license to personal, non-commercial transitory viewing, while §11 explicitly contemplates using the API on another platform, requires a link back to Arbeitnow, and allows permission to be revoked. The API announcement does not resolve that commercial scope. This integration links every result back to Arbeitnow; production reuse should be reviewed against both provisions. See the [privacy policy](https://www.arbeitnow.com/privacy).

Example source record: `{"slug":"role-123","title":"Engineer","company_name":"Example GmbH","remote":true,"created_at":1791849600,"location":"Berlin, Germany","job_types":["full_time"],"url":"https://www.arbeitnow.com/view/role-123"}`. It becomes `id=arbeitnow:role-123`, `country=DE`, `remote=true`, `employment_type=full_time`, with unsupported salary fields null.
