# Hard Problems impact jobs RSS

The UK nonprofit [Hard Problems](https://www.hardproblems.com/jobs) curates design, product, research and writing jobs at organisations addressing climate, health, education and public-service problems. Its Jobs page explicitly offers an [RSS subscription feed](https://www.hardproblems.com/jobs/feed.xml), including country-filtered URLs. This is a small, specialist source; it does not replace broad software or engineering job search.

| Contract | Behavior |
| --- | --- |
| Endpoint | `GET https://www.hardproblems.com/jobs/feed.xml?country=Germany` or `?country=Sweden` |
| Authentication / price | No key or account; public RSS, no published API price or numeric rate limit. One request per search, at most 15 returned listings. |
| Request disclosure | The selected country is sent to Hard Problems. Query, city, remote, impact area and recency stay in the OpenMates backend for local filtering. Server IP and HTTP user agent are inherently visible to the feed host. [Privacy notice](https://www.hardproblems.com/privacy). |
| Response used | RSS `title`, board `link`, original-source `guid`, `pubDate`, `category`, and only the final location/work-style paragraph of `description`. Full RSS descriptions are not stored or returned. |
| Output | Normalized `JobListing` with `provider=hard_problems`, board source URL, original listing URL when HTTPS, company/title, verified country and location, publication timestamp and explicit fully remote status. Salary, employment type and full description remain unknown. |

The adapter accepts only `DE`/Germany and `SE`/Sweden. The feed's country filter is not trusted alone: each result must also have a location paragraph naming the requested country. Entries labelled only `Global` are excluded from a country search even if the feed returns them. City filtering compares the stated city, not incidental text in a description. `remote=true` requires an explicit standalone `Remote` marker; hybrid and unspecified arrangements remain unknown. `remote=false`, employment type and radius filters are unsupported and return an explicit provider error. Recency uses RSS publication date. Impact area matches the feed's category tags; keyword search uses title, company and categories only.

The [public Jobs page](https://www.hardproblems.com/jobs) advertises RSS for subscribing to filters, but no general licence to republish listing bodies or build a competing job database was found. This development integration retains source links and only minimal metadata; assess any broader or production redistribution with the board. Some `guid` values point to third-party boards and may be stale or require their own access. The board says it removes **most**, not all, closed jobs; a returned item is not independently verified as still accepting applications. RSS structure and country labels can change, so malformed/oversize feeds fail closed. No account or API key is required and there is no billing retry risk. Transient failures get at most two short retries; no-results return an empty list.

Verified on 13 October 2026 with bounded live GETs: Germany returned 17 entries and Sweden 8 before local country checks. These counts are a snapshot, not a coverage promise.
