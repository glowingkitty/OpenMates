# Geoapify maps discovery verification

Task: TASK-4743. Session: `e390`. Verification order: live CLI, web, then Apple audit and Mac handoff.

## Live OpenMates CLI

Backend discovery was deployed to dev as `c39192d29976c0eb2486b48acca1c65d5736a6d1`.

- A `ruins` search around latitude `52.52`, longitude `13.405`, radius `10000` metres and page size `5` returned five Geoapify places.
- A `drinking_water` search around the named area `Potsdam, Germany`, radius `5000` metres and page size `5` returned five places.
- Repeating the coordinate ruins request returned five places with `search_context.cache_hit=true`.
- An ordinary cafes search in Berlin Mitte with enrichment disabled returned two Google Places results.
- Discovery results retained `geoapify:` identities, finite coordinates, category, distance and `OpenStreetMap via Geoapify` attribution. Unnamed places were labelled explicitly; missing ratings and hours were absent.

The first natural-language worker request timed out at the original five-second limit. Read-only investigation found no network, DNS, TLS or proxy difference between API and worker. Discovery now allows ten seconds; timeout diagnostics record only subtype and elapsed time. This correction was deployed as `b6c858031d8855baa2664f55a141bcd8464be2f5`, followed by the coordinated API/worker reload.

The repeated incognito CLI prompt, **“Find 5 ruins within 10 km of Berlin, Germany, and show them on a map.”**, completed with a `maps.search` parent and five place references. Incognito avoided persistent chat state. The empty disposable QA Project was deleted after verification.

After the final deployment and coordinated API/worker reload, the same coordinate discovery returned five cached Geoapify places with `success=true` and the existing 40-credit Maps charge. A CLI request with latitude `91` was rejected with the expected coordinate-range validation error.

## Backend checks

- Focused provider, discovery and existing enrichment checks passed locally (42 checks before the timeout correction).
- Provider and discovery checks, including sanitized timeout diagnostics, passed after the correction (37 checks).
- [Discovery/provider isolated CI](https://github.com/glowingkitty/OpenMates/actions/runs/37244789627) passed.
- [Parent metadata, main processor and composite embed isolated CI](https://github.com/glowingkitty/OpenMates/actions/runs/37245936444) passed.
- [API response isolated CI](https://github.com/glowingkitty/OpenMates/actions/runs/37249437448) passed; the same file passed all twenty checks locally. Discovery validation errors retain their grouped details, return `success=false` and charge zero credits. Ordinary Google responses retain their existing envelope.
- [Final backend integration CI](https://github.com/glowingkitty/OpenMates/actions/runs/37262118163) passed the parent-metadata, invalid-tool-call and composite-embed suites against source `ec904b2d25e381a741c022292dfca58bca5dcf49`, based on current dev `7c64393fc0c77c58bfa8be7df3eefedf80ec8f3d`. This verifies the small maps processor change after preserving newer shared AI pipeline code during integration.

These include atomic shared credit reservations, the five-request-per-second limit, cache reuse, unavailable-cache fail-closed behavior, invalid/ambiguous areas, all six category mappings, unknown amenities, malformed provider responses and regular-search compatibility.

## Web component checks

[Component CI](https://github.com/glowingkitty/OpenMates/actions/runs/37247175333) passed all ten cases with zero skips or retries, using candidate source `d752e3811196159ef13a445e45688a5092fd0a5d`.

The cases cover regular and Geoapify cards/markers at 390, 800 and 1100 pixels; parent result counts and provider labels; coordinate-based Google links for Geoapify places; source/distance without invented ratings; empty, quota and flattened amenity metadata; and broken pinned-map images.

Screenshot review caught fullscreen rules conflicting with the newer shared map view. The corrected fullscreen uses a vertical desktop list and fills the remaining width with the map. Assertions now check the selected card and its preview remain inside the list and that the map reaches the right edge. The shared in-chat map-view layout is unchanged.

[npm and Python SDK CI](https://github.com/glowingkitty/OpenMates/actions/runs/37250379994) passed both checks with zero skips or retries, using source `6d6b38d742e5de3bbf0d0b0b04c709734b79cfc9`. Both built SDKs called the isolated API and preserved `success=false`, Geoapify grouped validation details and zero charged credits for an invalid area. Live successful provider results were verified through the CLI above.

SDK verification exposed a discovery validation error incorrectly marked successful in the outer API envelope; the maps-specific response correction is covered by the API checks above. The first full-chat attempt was assigned to the core profile without an AI fixture worker, so it blocked before sending. Moving the candidate manifest entry to the committed-fixture profile did not enable the worker on the rerun: profile admission uses the separately deployed, pinned CI harness manifest. The registration was integrated as `c8c71ff2e8ed2ff0102ce02306a0cf6fedfd7aad`, preserving concurrent registrations, after seventeen focused profile/coverage/model-status checks and a direct manifest-membership check passed. The unchanged candidate was resubmitted against that harness.

The committed `maps_discovery_web` fixture uses real public places from the live CLI response with a deterministic test transcript; it is not a recording of an AI conversation.

The [registered-harness chat run](https://github.com/glowingkitty/OpenMates/actions/runs/37253198330)
included the AI worker and accepted both chat sends, but produced no assistant
response or finished maps embed. This was a different failure from the earlier
profile admission issue; the following diagnostics identified its boundary.

The [bounded dispatch diagnostic run](https://github.com/glowingkitty/OpenMates/actions/runs/37256816266)
used candidate `8cfe8216c9cb5a2e96e8547fa1d852d778c32122` and harness
`591700567415c6da3ce3ea7d04066efaf5886b97`. All four browser sends received
`chat_turn_preflight_ack` with state `LEGACY`, then `chat_message_confirmed`,
then an `error` with code `inference_temporarily_paused`. History construction
completed, but no AI worker task started. The CLI validation case passed; both
browser cases failed before reaching map rendering. The captured diagnostics
contain only event types, booleans, counts and fixed stage labels. Disposable
runtime and private account cleanup were verified. A read-only check of dev's
authoritative cutover state returned `protocol_epoch=1` and `sends_paused=false`.
The isolated AI-fixture setup needs to initialize that same saved-chat mode for
this spec. Its small sealed outputs fit the existing inline recovery bound, so
no object-storage service is required. The guarded setup correction was deployed
as `36cc5889a5cb87b5ca8ccf9cdbff9365e755297a`, affecting only the runner and its
focused tooling test. Thirty-five combined runner/tooling checks passed before
the final added GitHub-runner rejection case; all fourteen focused maps safety
cases then passed. The existing capacity guard remains separate. The unchanged
browser candidate was resubmitted.

The [corrected full-chat run](https://github.com/glowingkitty/OpenMates/actions/runs/37260202596)
passed all three cases with zero skips, retries or unexpected failures in 73
seconds, using the same candidate and harness `36cc5889a5cb87b5ca8ccf9cdbff9365e755297a`.
Both browser sends received a `PREPARED` preflight and `ai_task_initiated`; each
started one worker task and completed dispatch. Regular search showed one Google
place with its existing rating; discovery showed two places and markers, source
attribution, `539 m` distance and no fabricated rating. Fullscreen screenshots
were visually reviewed. Runtime/private-account cleanup was verified. The
[artifacts](https://github.com/glowingkitty/OpenMates/actions/runs/37260202596/artifacts/11324791565)
include screenshots as named Playwright report attachments.

## Final dev deployment and visual review

The product changes were published as `5df32f6c00975317099d4058c5646bcd4a4afd0d`.
The deployment gates passed Specification validation, embed registration, lint,
translations and six related backend suites. Vercel reported the exact commit
successful. Coordinated reload `docker-fee632df` restored a consistent source
generation across the API and Python workers; all services reported healthy.

Eight deployed Playwright screenshots were inspected at 1440×1000 and 390×844:

- [Geoapify fullscreen](https://app.dev.openmates.org/dev/preview/embeds/maps/MapsSearchEmbedFullscreen?chrome=0&variant=discovery): two readable cards and markers, source/distance, no fabricated ratings.
- [Regular Google fullscreen](https://app.dev.openmates.org/dev/preview/embeds/maps/MapsSearchEmbedFullscreen?chrome=0): existing ratings, cards and markers preserved.
- [Discovery parent preview](https://app.dev.openmates.org/dev/preview/embeds/maps/MapsSearchEmbedPreview?chrome=0&variant=discovery): correct provider and two-place count before child hydration.
- [Discovery place preview](https://app.dev.openmates.org/dev/preview/embeds/maps/MapLocationEmbedPreview?chrome=0&variant=discovery): readable source/distance and no rating.

No UI defect or accepted UI difference was found. The fullscreen capture helper
marked its raw reports failed solely for canceled OpenStreetMap tile requests
during initialization. Both final maps rendered completely, with no missing
tiles, page/console/HTTP errors, broken images or document overflow. The preview
captures passed their automated checks. The raw reports remain unchanged; the
separate manual screenshot-review receipt is
`test-results/visual-smoke/maps-e390-deployed-review.json` in session `e390`,
linking all eight PNGs and the discovery, regular and preview capture reports.

## Provider cost boundary

No new provider subscription, server or API key was added. Existing OpenMates Maps credit pricing is unchanged. The shared wrapper defaults to 2500 uncached basic provider requests per UTC day, with a hard configurable ceiling of 3000; cached calls do not reserve provider credits. External account usage is outside this counter, and the provider dashboard's remaining allowance has not been verified. Quota failures return a readable status rather than requesting an upgrade.

## Apple

The read-only Swift source audit confirmed that Geoapify IDs currently reach
Google's place-ID action, source/distance fields are missing, and maps search
parents use generic rendering without the web child-map and quota states.
Existing coordinate validation and image-failure guards already have legacy
coverage. The local contract scan was blocked by a missing web YAML dependency;
it provides no native runtime proof.

[Mac agent instructions](apple-handoff.md) identify the affected Swift files,
ordered child-hydration patterns, public fixtures, final deployed web baseline
and focused iPhone/iPad/macOS verification. Native changes and runtime parity
remain pending on the Mac; TASK-4743 stays in progress for that work.
