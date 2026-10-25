---
status: research
last_verified: 2026-10-25
---

# Official discovery APIs: events, apartments and jobs

Task: TASK-45. Reviewed 25 October 2026 by four independent researchers covering mainstream events, community events, housing and jobs. This is a provider-selection report and proposed sequence; implementation and publication remain follow-up work.

The intended use is a commercial conversational assistant that searches across organizers, landlords or employers, displays normalized result embeds, preserves results in encrypted user history, and can publish an attributed example on the landing page. An official API alone does not establish all those downstream rights. Software licences and event/listing-content licences are separate.

## Recommended selection

| Area | Best next candidate | Main qualification |
| --- | --- | --- |
| Events with explicit reuse rights | **OpenAgenda** | Free read key; good French cultural/community coverage. Check every event's licence and retain credits. Berlin coverage is unproven. |
| Useful Berlin cultural discovery | **Kulturdaten Berlin** | Working anonymous API and current inventory; resolve the applicability of its repository content licence to imported organizer records. Text results, without promised photos. |
| Broad ticketed entertainment | **Ticketmaster Discovery** | Strong technical fit; standard commercial/storage conditions do not establish our complete use case. |
| Remote jobs eligible in Germany/Europe | **Jobicy** | Explicit commercial AI and saved-opportunity permission; remote eligibility rather than local workplace search. |
| Swedish jobs | **JobTech** | Existing official CC0 adapter; Sweden does not replace German discovery. |
| German rental apartments | **ImmoScout24 partnership** | Genuine search exists, but partner access and 24-hour storage conflict with the proposed historical embeds unless the agreement changes those conditions. |
| US rental metadata | **RentCast** | Supported AI/search/storage use, subject to third-party conditions. No documented photos or direct listing URLs. |

## Events

### OpenAgenda: first integration candidate

The [official API](https://developers.openagenda.com/) is free with an account-generated read key. Agenda discovery precedes event search; it is not proof of universal geographic coverage. [Search](https://developers.openagenda.com/evenements/lecture/) supports dates, locations and text; [event fields](https://developers.openagenda.com/evenements/structure/) include schedules, descriptions, location, images, registration and canonical links. Up to 300 events/request; a numerical request-rate allocation was not found. Price conditions may be free text, not a reliable numeric range.

[Per-event rights](https://developers.openagenda.com/licence/) identify licence, licensor and publisher. Licence Ouverte 2.0 allows commercial copying, transformation and redistribution. Preserve the licensor, licence link, update date and image credits with each result, including saved/public examples. The [general terms, updated 14 October 2026](https://doc.openagenda.com/fr/article/conditions-generales-dutilisation-xq325m/), also describe third-party commercial reuse and contributor warranties covering images. Historical copies and an attributed demo are supported by inference from these grants; no maximum retention period was found.

Current inventory is real: [70 ans du Poutou de Toulouse](https://openagenda.com/fr/toulouse-metropole/events/76485758_70-ans-du-poutou-de-toulouse-exposition-et-festivites) has free exhibition dates through 31 October 2026, location, credits and an explicit open licence. This supports a French cultural example; it does not prove Berlin density. API responses were not tested because no key was obtained.

### Kulturdaten Berlin: useful local source, narrower rights gap

The [official site](https://www.kulturdaten.berlin/en) expressly invites API reuse for applications. Its [official repository](https://github.com/technologiestiftung/kulturdaten-api) distinguishes MIT software from content labelled CC BY, linked to [CC BY 3.0 Germany](https://creativecommons.org/licenses/by/3.0/de/). The applicability of that repository statement to every imported organizer record remains less explicit than OpenAgenda's event-level rights. Resolve that scope before implementation/publication; no provider has been contacted.

Bounded reads of the documented anonymous production API succeeded:

- [Upcoming sample](https://api-v2.kulturdaten.berlin/api/events?page=1&pageSize=1): reported 12,974 upcoming event records; one free Kaulsdorf exhibition dated 25 October.
- [30 October–1 November sample](https://api-v2.kulturdaten.berlin/api/events?page=1&pageSize=3&startDate=2026-10-30&endDate=2026-11-01): reported 310 records, including exhibitions and bookable children's tours.

These are API event-record counts, including repeated occurrences, rather than counts of distinct attractions or evening events. Midnight start/end values in samples must not become asserted midnight appointments. The [published schema](https://github.com/technologiestiftung/kulturdaten-api/blob/main/src/schemas/kulturdaten.berlin.openapi.generated.yml) provides schedules, admission, descriptions, websites and referenced venues, but no photo/credit fields. No published numerical quota or API fee was found. The website marks the original project complete in December 2023; current 2026 responses establish availability, not a support SLA.

### Other event sources

| Source | Findings and decision |
| --- | --- |
| **OpenMeet** | The user's suggested project exists at openmeet.net. Its [official API](https://api.openmeet.net/) supports public event search. [Hosted terms](https://openmeet.net/terms) grant platform use of uploader content, without establishing downstream commercial/history/demo permission for OpenMates. Apache-licensed code does not supply that permission. Useful Berlin inventory was not established. |
| **Mobilizon** | [Per-instance GraphQL](https://docs.mobilizon.org/5.%20Interoperability/3.graphql_api/) supports public geographic/topic/date searches. [Global search ended in 5.1.0](https://docs.mobilizon.org/3.%20System%20administration/configure/global_search/). Need an instance/content licence and useful inventory; federation and AGPL software are insufficient. |
| **Ticketmaster** | [Discovery](https://developer.ticketmaster.com/products-and-docs/apis/discovery-api/v2/) offers cross-organizer city/date/category search, images, optional price ranges and event URLs. Key-based self-service; 5,000/day. Reference says 5 requests/sec, [FAQ](https://developer.ticketmaster.com/support/faq/) says 2; use the granted conservative limit. [Terms](https://developer.ticketmaster.com/support/terms-of-use/) restrict revenue derivation, storage duration and require requested removals. Commercial AI, durable histories and marketing examples need a fitting agreement through the [distribution route](https://developer.ticketmaster.com/partners/distribution-partners/). |
| **Meetup** | [Access](https://help.meetup.com/hc/en-us/articles/41453576628749-How-can-I-get-access-to-Meetup-s-API) requires paid Pro and approved app; [licence](https://help.meetup.com/hc/en-us/articles/360028705532-Meetup-API-license-terms) requires express written commercial consent. The [GraphQL guide](https://www.meetup.com/graphql/guide/) mentions event search but examples do not prove unrestricted cross-network discovery. |
| **Eventbrite** | The [official reference](https://www.eventbrite.com/platform/new/api) records shutdown of public event search on 12 December 2019. Organization/known-ID access is not broad discovery; partner distribution would need approval. |
| **Songkick** | Genuine music-event search; current [developer access](https://www.songkick.com/developer/) requires a paid partnership. [Standard terms](https://www.songkick.com/developer/api-terms-of-use) are noncommercial with 24-hour caching, incompatible with our full use without negotiated terms. |
| **Skiddle** | Real discovery, apparently UK-focused. Its [API page](https://www.skiddle.com/api/) and [application terms](https://www.skiddle.com/api/join.php) conflict over commercial permission; attribution and unchanged-data requirements also matter. Resolve before use. |
| **SeatGeek** | [API terms](https://seatgeek.com/api-terms) prohibit supplying data to AI/ML applications under the standard grant. Exclude absent an express exception. |
| **pretix / DICE / Bandsintown** | [pretix](https://docs.pretix.eu/dev/api/resources/events.html) is organizer-scoped; [DICE](https://partners-endpoint.dice.fm/graphql/docs/index.html) is authenticated partner administration; [Bandsintown](https://help.artists.bandsintown.com/en/articles/7053475-what-is-the-bandsintown-api) normally assigns keys per artist. These are not self-service general city discovery replacements. |

## Jobs

**Jobicy** is the strongest new lead. Its [current documentation and reuse guidance](https://jobicy.com/jobs-rss-feed), updated 19 October 2026, explicitly permits commercial AI products, summaries, caching and saved opportunities. Credit Jobicy and preserve supplied application links. Public REST access is key-free; optional paid ATS links cost $0.01 per newly seen direct-link job/key. Discovery covers seven days with a three-hour delay; synchronize at most hourly and check saved IDs for closure.

Two bounded queries (`geo=germany`, `geo=europe`, `count=5`) returned five records each with more available. Germany includes Europe-wide eligibility, not Berlin workplaces. Some salary/seniority fields were implausible; normalize cautiously and mark confirmed closures on saved results.

| Source | Decision |
| --- | --- |
| **JobTech** | [Official catalogue](https://data.jobtechdev.se/dataservice/jobsearch/) confirms CC0, public, no key; Swedish scope. Existing adapter documentation: [jobtech.md](jobtech.md). |
| **Adzuna** | [Search API](https://developer.adzuna.com/docs/search) supports German local job discovery. [Current terms](https://developer.adzuna.com/docs/terms_of_service) give commercial organizations a 14-day evaluation, then require licensing for revenue products; attribution and termination/removal conditions apply. Limits are account-specific. Obtain terms covering history and AI. |
| **Arbeitnow** | [Official API invitation](https://www.arbeitnow.com/blog/job-board-api) exists, but [general terms](https://www.arbeitnow.com/terms) retain noncommercial/public-display restrictions that are not clearly overridden. Commercial AI/history permission unresolved. |
| **The Muse** | [API terms](https://www.themuse.com/developers/api/v2/terms) incorporate [general terms](https://www.themuse.com/user/terms) prohibiting AI use of content/metadata. Exclude under ordinary terms. |
| **Remotive** | [API guidance](https://github.com/remotive-com/remote-jobs-api) and [2026 general terms](https://remotive.com/terms-of-use) leave redistribution/AI/signup-wall conflicts for a commercial logged-in assistant. Seek a scoped agreement only if selected. |
| **USAJOBS** | [Official registration](https://developer.usajobs.gov/apirequest/) supports approved applications/job boards; US federal scope. Attribution, original displayed values and USAJOBS view/apply links apply; historical public-demo/AI transformations need scope review. |
| **Bundesagentur für Arbeit** | No generally licensed official public search feed established. The [official parliamentary answer](https://dserver.bundestag.de/btd/20/002/2000235.pdf) identifies the commonly reused interface as internal; [current terms](https://www.arbeitsagentur.de/nutzungsbedingungen) do not establish general extraction rights. Do not restore bund.dev/internal-endpoint access. |
| **Lever / Greenhouse** | Official employer-specific boards are useful where the employer permits reuse; they do not establish global discovery or blanket rights across all employers. |

The older [13 October jobs report](jobs-search-research.md) is historical. In particular its fixed Adzuna quotas and broad evaluation assumptions should not override the current terms above.

## Rental apartments

| Source | Discovery capability and permission |
| --- | --- |
| **ImmoScout24** | Genuine German [rental search](https://api.immobilienscout24.de/api-docs/search/introduction/) with filters, exposés and images, available to approved content partners. [Terms](https://api.immobilienscout24.de/terms-of-use/en/) include 24-hour storage, public availability and branding requirements. Persistent encrypted chat copies need agreed exceptions. Rooms must not be relabelled bedrooms. |
| **Immowelt** | [Official interface](https://www.immowelt.de/anbieten/gewerbe/apitechdoku) exists; [licence](https://www.immowelt.de/meineimmowelt/apinutzungsbedingungen.aspx) normally covers an advertiser's own inventory/site. Cross-advertiser aggregation needs express permission. |
| **idealista** | A real [Search API application](https://developers.idealista.com/access-request) exists. Country availability, quotas, pricing, media/retention and commercial AI terms were not established publicly. Valuation/comparables products are separate. |
| **HousingAnywhere** | [Official integration description](https://housinganywhere.com/how-to-integrate-property-database) concerns property-manager inventory and booking synchronization, not verified cross-landlord marketplace search. |
| **RentCast** | [US active rental search](https://developers.rentcast.io/reference/rental-listings-long-term), self-service key, documented [AI tools](https://developers.rentcast.io/reference/ai-tools). [Terms](https://www.rentcast.io/terms-api) permit storage/display/distribution, with third-party licensing and deletion qualifications. The [schema](https://developers.rentcast.io/reference/property-listings-schema) lacks listing photos and direct listing URL. [Pricing](https://www.rentcast.io/api): 50 free calls/month, then $74/1,000, $199/5,000, $449/25,000; [limit](https://developers.rentcast.io/reference/rate-limits) 20 requests/sec/key. No authenticated live inventory was sampled. |
| **Zillow / Bridge** | [MLS output](https://www.zillowgroup.com/developers/api/mls-broker-data/mls-listings/) is invite-only and MLS-controlled. Zillow rental-feed integrations send inventory into Zillow; they do not grant marketplace search access. |

No reviewed generally available German source establishes the entire requested workflow. A marketplace agreement is the realistic route; a US metadata-only integration is a separate deliverable.

## Proposed implementation order and landing-page follow-up

1. Select OpenAgenda and a demonstrated geographic scope. Obtain the free read key, validate a few city/date/topic queries, and record the exact permitted endpoints, normalization and per-record attribution/media conditions in a provider contract Specification.
2. Implement the backend provider and event skill, preserving licence/provenance in encrypted results. Validate actual usefulness, time zones/occurrences, unknown prices, no-results/outages and deduplication. Run focused units locally and product/CLI/SDK checks in isolated GitHub CI; live AI checks use dev and existing automatic routing.
3. Verify the event preview and full detail in the web app. Then publish a real example and restore the landing animation using its attributed result.
4. Add Jobicy as a separate remote-job source, preserving eligibility, trustworthy salary units and saved-result status. Retain Swedish JobTech as a correctly scoped option.
5. Add Berlin cultural coverage after the narrow content-licence gap is resolved; pursue Ticketmaster or German housing partner access only if selected. RentCast is optional if US metadata-only housing is useful.

The public landing source currently limits custom story playback to `privacy` in `frontend/packages/public-site/src/components/landing/LandingPage.svelte`; its actionable destination is undefined in `landingPageContent.ts`. The old event scene still exists elsewhere in source, but is not proof of current supported discovery.

The replacement flow should show: **user request → brief assistant response → actual event embed preview → visible click → full event details → source/registration action**. Preserve source attribution and avoid invented attendee counts, images, prices or availability. A credible initial prompt is a French city/cultural request backed by OpenAgenda; use Berlin only after its selected provider is validated. Reuse real result components, verify desktop/mobile and reduced motion, and use a clearly dated historical example or refreshed data when availability changes. The public demo can replay an approved result without making a live provider request on every landing-page visit.
