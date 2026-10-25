---
status: research
last_verified: 2026-10-25
---

# Key-free event API output quality

Task: TASK-45. This follow-up tests the practical usefulness of candidates in the [provider research](discovery-provider-research-2026-10-25.md), rather than treating API availability as evidence of adequate coverage.

**Recommendation: defer a broad Events integration using the tested feeds.** Kulturdaten Berlin contains useful local activities, but only supports a specifically labelled Berlin neighbourhood/cultural calendar. The sampled Mobilizon instances are too sparse for general discovery. OpenMeet's unauthenticated request could not establish access. Use an existing weather forecast embed for the landing demonstration instead.

## Method and limits

On 25 October 2026, we made bounded, identified, key-free requests to documented interfaces:

- Kulturdaten Berlin: one initial 50-record sample, then the complete **30 October–1 November 2026** date window, capped at the documented 500-record maximum. Batch-fetch only the attractions and venues referenced by that window.
- Mobilizon: **25 October–25 November 2026**, within 30 km of Berlin centre, through mobilizon.fr and mobilize.adminforge.de, both listed in the [official instance directory](https://instances.mobilizon.org/). The documented public [GraphQL search](https://docs.mobilizon.org/5.%20Interoperability/3.graphql_api/) required one query-shape correction: descriptions belong in an Event fragment. Validation errors are not counted as poor inventory.
- OpenMeet: one unauthenticated request to the documented public collection; stop after the tenant error.
- Check two selected official venue listings against the Berlin window. These are spot checks, not a statistically representative recall benchmark.

No API keys, accounts, purchases, event mutations, live OpenMates inference or shared service changes were used. Raw responses remain private; the [sanitized evidence](evidence/event-api-quality-2026-10-25.json) records filters, response hashes and aggregate findings. These are direct provider evaluations, not product E2E results.

This cannot estimate what percentage of all relevant online events is missing. In particular, it does not establish a 98% omission rate, a citywide market denominator or whole-federation coverage.

## Kulturdaten Berlin: useful municipal activities, incomplete general discovery

[Documented production query](https://api-v2.kulturdaten.berlin/api/events?page=1&pageSize=500&startDate=2026-10-30&endDate=2026-11-01), [official schema](https://github.com/technologiestiftung/kulturdaten-api/blob/main/src/schemas/kulturdaten.berlin.openapi.generated.yml).

| Measure | Observed output |
| --- | --- |
| Occurrences / distinct attractions / venues | **310 / 224 / 116** |
| Occurrences by day | Friday 157; Saturday 96; Sunday 57 |
| Upstream origin | All 310 identify the municipal district calendar |
| Explicit free admission | 271 occurrences; 39 unknown |
| Descriptions after joining attraction records | 224/224 attractions |
| Attraction websites / venue street addresses | 126/224; 114/116 |
| Structured admission links in event records | 0/310; descriptions sometimes contain registration instructions/links |
| Schedule qualifications | 10 midnight starts; 61 midnight ends requiring cautious interpretation |
| Languages | 218 attractions German-only; 6 German and English |
| Photos | No field in the documented event/attraction schema |

Source categories overlap. There are 120 exhibition occurrences, 76 children-tagged occurrences, 66 recreation occurrences and 21 police-tagged occurrences. The 14 music-tagged occurrences include exhibitions and family activities, so that tag is not equivalent to a live-concert filter.

There are genuinely useful choices for a request such as free activities for children on Sunday: five matching records in this window, including storytelling, theatre and a picture-book cinema. By contrast, police outreach, advice services, recurring classes and exhibitions do not answer a general nightlife, concert or professional meetup request.

The date window is current and records are published/scheduled, but publication does not independently verify capacity, cancellations or availability. Many records were last edited months earlier; that alone does not prove staleness. Descriptions, dates, tags, venues and a source statement must survive normalization.

**Decision:** keep as a potential explicitly scoped local-calendar source, not the foundation of a general event-search promise. The previous content-licence qualification also remains. Its usefulness does not by itself justify a new broad skill or a flagship event-discovery demonstration.

## Mobilizon: small, overlapping Berlin samples

Both corrected searches succeeded without a key:

| Measure | mobilizon.fr | mobilize.adminforge.de |
| --- | --- | --- |
| Matching events / returned | 9/9 | 7/7 |
| Events with descriptions | 9 | 7 |
| Pictures / priced offers | 0 / 0 | 0 / 0 |
| Structured street fields | 0 | 0 |
| Free-text venue addresses | 9 | 7 |
| Distinct venues | 2 | 2 |

Six event URLs overlap, leaving **10 unique events across both instances for the month**. All returned canonical URLs point to mobilize.berlin. Most are at one venue; seven of the nine French-instance titles contain only one or two words. The descriptions help identify performers, but end times equal start times in every returned record.

These are useful niche community announcements. They do not justify a citywide recommendation product. Different instances may contain different inventory; these results are not a finding that all Mobilizon data is sparse everywhere.

**Decision:** do not integrate these sampled instances for broad discovery. Adding multiple instances did not produce much additional breadth, and content reuse permission remains separate.

## OpenMeet and OpenAgenda

[OpenMeet Swagger](https://api.openmeet.net/docs) describes public event search and a tenant header. A plain GET to `/api/events` returned **401, “Tenant ID is required.”** No tenant identifiers were guessed and no further API requests were made. Inventory quality is therefore **unmeasured**, rather than empty or poor. Obtain a documented public tenant configuration and resolve content rights before considering it again.

[OpenAgenda authentication](https://developers.openagenda.com/authentification/) requires an account-generated key for current REST reads, so its API was outside this key-free sample. Its [old JSON export](https://developers.openagenda.com/en/evenements/export-json/) explicitly warns against new implementations and says it was scheduled for removal at the end of 2025. Do not revive that retired route as a key-free workaround. OpenAgenda's permission evidence remains promising, but its useful geographic coverage still needs an authenticated quality test before implementation.

## Concrete coverage gaps

The complete Berlin weekend response and referenced attraction titles/descriptions contain no matches for:

- [DE STAAT at Lido, 31 October](https://www.lido-berlin.de/events/2026-10-31-de-staat). The current venue page marks it sold out; this tests catalogue coverage, not bookability.
- [HI! SPENCER at Lido, 1 November](https://www.lido-berlin.de/events/2026-11-01-hi--spencer). The venue lists a ticket link; live inventory and price were not checked.

Reading these two public listings is a bounded audit, not a new source connector. Robots policies permitted their paths. An attempted Jazzfest detail-page check returned 503 and was not retried; no live festival availability claim relies on it.

The omissions show why a large municipal record count should not be presented as a search of the whole event scene. They do not yield an overall recall percentage.

## Recommended landing-page replacement

**Use weather as a concrete daily decision, with the existing forecast preview and day fullscreen.**

Proposed request: **“Will it rain during my bike commute in Berlin tomorrow morning?”**

1. Show the request and a short response grounded in an actual forecast.
2. Reveal a real weather-day embed preview with the location, date, weather icon, temperature and rain chance.
3. Move the pointer to the card and visibly click it.
4. Open the actual day detail and show the hourly strip for the morning commute, including rain and temperature, with available wind information.
5. Keep the source/date visible and finish on the useful expanded result.

This demonstrates a bounded task whose result can be inspected directly. It needs no new discovery feed and does not imply an exhaustive search of unrelated websites.

Existing presentation: `WeatherDayEmbedPreview.svelte` and `WeatherDayEmbedFullscreen.svelte` under `frontend/packages/ui/src/components/embeds/weather/`. Weather is present in the generated public app catalogue. Existing weather example data uses historical dates; capture a fresh real example, or clearly date a historical replay, before publishing the animation. Do not invent favorable weather, reuse “today/tomorrow” labels on old data, or animate a graph/control the product does not provide.

The animation itself remains follow-up work: use the real components, preserve source attribution, and verify desktop/mobile and reduced motion when implementing it.
