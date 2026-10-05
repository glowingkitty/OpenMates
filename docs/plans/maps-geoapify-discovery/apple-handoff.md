# Apple maps discovery handoff

Task: **TASK-4743**. Specification: `feature.app-skill.maps-search@1`.
Status: source audit complete; final web baseline and native implementation/verification pending.

The user approved Geoapify discovery and requested CLI, web, then Apple parity.
They explicitly permitted instructions for the AI agent working on the Mac.
Reuse this Task and the existing engineering Project. Obtain or reuse the
Mac-owned workspace according to the `ios` skill; the Linux web workspace is
session `e390` and must not be borrowed for Mac edits.

## Web baseline

The final deployed web commit and screenshots will be recorded in
[verification.md](verification.md). Complete the native comparison against that
commit. The approved behavior and public fixture data are already available in:

- `specifications/features/app-skills/maps-search/specification.yml`
- `backend/apps/ai/testing/fixtures/maps_discovery_web.json`
- `frontend/apps/web_app/tests/components/maps-discovery.spec.ts`
- `frontend/apps/web_app/tests/maps-discovery-chat.spec.ts`
- `frontend/packages/ui/src/components/embeds/maps/*.preview.ts`

Use these web implementations as the rendering contract:

- `MapLocationEmbedPreview.svelte`: place cards, source and distance.
- `MapLocationEmbedFullscreen.svelte`: place details and provider-aware links.
- `MapsSearchEmbedPreview.svelte`: parent count, provider and readable quota error.
- `MapsSearchEmbedFullscreen.svelte`: child cards and markers, warnings and empty/filter/error states, responsive layout.
- `MapsLocationEmbedPreview.svelte`: pinned-location image failure fallback.
- `frontend/packages/ui/src/services/embedPreviewRegistry.ts`: payload-to-prop mapping.

The skill uses the existing backend and Geoapify connection. Six supported
categories are `ruins`, `viewpoints`, `drinking_water`, `toilets`, `picnic_sites`
and `campsites`. Bounds come from a named area or coordinates, with a default
10 km radius and a 50 km maximum. Existing Google search is preserved. No Apple
provider integration, subscription, server or pricing change is needed.

## Confirmed Swift gaps

| Responsibility | Existing source | Required change |
| --- | --- | --- |
| Place payload and external links | `apple/OpenMates/Sources/Features/Embeds/Renderers/MapsEmbedModel.swift` | Parse provider, source label/URL and distance. Recognize Geoapify by provider or the `geoapify:` ID prefix; use valid coordinates for its Google Maps link. Preserve Google place-ID links for Google results. |
| Place preview and details | `apple/OpenMates/Sources/Features/Embeds/Renderers/MapsEmbedRenderer.swift`, `apple/OpenMates/Sources/Features/Embeds/Grouping/EmbedFullscreenContainer.swift` | Render source and distance in preview/details, expose the source action, and preserve existing map/details/actions. Ratings and hours remain absent when unknown. |
| Search parent routing | `apple/OpenMates/Sources/Features/Embeds/Views/EmbedContentView.swift`, `apple/OpenMates/Sources/Features/Embeds/Renderers/AppSkillUseRenderer.swift` | Route `maps.search` to a maps-specific parent renderer instead of the generic search fallback. Support both regular Google and Geoapify groups. |
| Parent fields | `apple/OpenMates/Sources/Features/Embeds/Renderers/SearchResultsRenderer.swift` | Preserve parent counts, ordered child references, warnings, filter details, coverage and quota/error metadata in the maps renderer. |
| Fixtures and evidence | `apple/OpenMates/Sources/DevPreview/DevEmbedPreviewFixtures.swift`, `apple/OpenMatesTests/MapsEmbedModelTests.swift`, `apple/OpenMatesUITests/MapsEmbedParityUITests.swift` | Add discovery and state variants with focused parser/UI tests. Existing maps fixtures and tests cover legacy Google cases. |
| macOS UI proof | `apple/OpenMatesMacUITests/` | Add a maps-specific GUI case to the existing `OpenMates_macOS` scheme. A build alone does not prove appearance or interaction. |

The URL bug is at `MapsEmbedModel.googleMapsURL(isPlace:)`: every place ID is
currently placed into Google's `place_id:` query. `EmbedFullscreenContainer`
uses this action. Fix this first; Geoapify IDs are not Google place IDs.

Existing finite-coordinate guards and broken-image fallback are useful and
already have tests. Preserve them. The source audit did not establish native
runtime parity. Its Linux contract check could not resolve the local web YAML
dependency; that environment failure is separate from the Swift gaps above.

## Reuse native hydration and map components

`SearchSkillPreviewModel.mergedRecords` in
`Renderers/SearchEmbedModels.swift` preserves `embed_ids` order while replacing
inline rows with hydrated children. Reuse this pattern for partial hydration.
`SearchDomainParentModel` in `Renderers/SearchDomainRenderers.swift` handles
flattened rows and `results_toon`; its fullscreen grid uses `EmbedPreviewCard`
and `onOpenEmbed`. Reuse these child-opening and hydration mechanisms rather
than creating another cache or decryption path.

Reuse the existing `EmbedMapConfiguration`/marker renderer with only finite,
in-range coordinate pairs. The parent should provide all valid result markers,
an ordered place list and selection/opening behavior. On wide layouts, keep the
list inside its column and give the map the remaining width. On narrow layouts,
keep the map and cards readable with reachable controls. Show screenshots to
the user if the native interpretation leaves a material design decision unclear.

## Payload cases to preserve

Place children contain `place_id`, `provider`, `name`, `formatted_address`,
`location.latitude`/`longitude`, `place_type`, `categories`, `types`,
`distance_meters`, `data_source`, `source_url` and optional `osm_enrichment`.
The public CLI fixture contains **Ruine der Franziskaner-Klosterkirche** at
`52.5184314, 13.4125411`, distance `539` metres, with
`OpenStreetMap via Geoapify` attribution. Do not fabricate ratings, review counts
or opening hours. Derived names such as “Unnamed ruins” remain identifiable.

Parent fields are `provider`, `result_count`, `embed_ids`, `warnings`,
`filter_summary`, `coverage`, `search_context`, `error` and `search_status`.
They may be decoded from TOON with flattened amenity fields and pipe-delimited
arrays. Parent counts must work before children finish hydrating; counting an
absent inline `results` array incorrectly reports zero.

`quota_exhausted`, `quota_unavailable` and `rate_limited` can have parent
`status=finished`, zero children and a readable `error`. Render the error and
provider rather than a generic successful-empty result. A successful zero-hit
search and a strict amenity filter excluding unknown matches remain distinct
from quota failure. Warnings should remain visible alongside nonempty results.

## Focused Mac verification

Add meaningful cases to the existing parser tests and preview harness:

1. Google results retain their place-ID action, rating and ordinary details.
2. Geoapify results retain identity, source and distance; Google actions use
   coordinates and never contain `place_id:geoapify:` or the raw provider ID.
3. Missing ratings/hours stay hidden; source URLs use the existing safe HTTP URL
   validation. Preserve invalid/NaN/infinite/boolean coordinate rejection.
4. A parent with `result_count=2` and child references reports two places before
   and after hydration, resolves children in order and exposes both markers.
5. Empty, quota, filtered and warnings-with-results states are readable, including
   flattened/TOON metadata. A broken pinned image retains the name/address.
6. iPhone, iPad and macOS preview/fullscreen screenshots show readable cards,
   source/distance, map markers and reachable open/close controls without clipping.

Preserve existing `chats.surface.semantic-parity` test metadata. Add the relevant
maps assertions within eight lines of new test functions:
`maps-search.gui.place-rendering`, `maps-search.output.source-and-identity` and
`maps-search.compatibility.regular-search`. Use accurate direct/supporting
classifications, regenerate Specification coverage, and keep live-provider proof
distinct from fixture-driven UI proof.

The existing preview launch arguments are:

```text
--dev-preview embeds --dev-preview-app maps
--embed-registry-key <key> --embed-surface <preview|fullscreen>
--embed-variant <variant> --ui-test-embed-presentation
-AppleLanguages (en) -AppleLocale en_US
```

Existing keys include `app:maps:search`, `maps-place` and `maps`; add discovery,
quota and filtered variants to the same fixture system. Existing test IDs include
`embed-location-map`, `embed-location-marker`, `maps-open-google-maps`,
`maps-location-address` and `maps-location-title`. Add semantic source, distance,
parent-error and card identifiers matching the web test IDs where appropriate.

Use the `ios` skill's local Xcode commands on the Mac. With an already authorized
remote Mac connection, the orchestrator's existing focused commands are:

```sh
python3 scripts/apple_remote.py test-ios --only-testing 'OpenMatesTests/MapsEmbedModelTests'
python3 scripts/apple_remote.py test-ios --only-testing 'OpenMatesUITests/MapsEmbedParityUITests'
# After adding the maps macOS GUI test class:
python3 scripts/apple_remote.py test-macos --only-testing 'OpenMatesMacUITests/MapsDiscoveryParityUITests'
```

Run the UI cases on both iPhone and iPad simulator destinations, plus macOS;
the default simulator alone is insufficient. Retain `.xcresult` attachments and
comparison screenshots in light and dark appearance. Use disposable preview/QA
state and the established trusted-device workflow for any account-based smoke.
Update TASK-4743 with the native commit, focused results, screenshots and actual
remaining gaps. Do not mark Apple parity complete based on this source audit or
a successful build.
