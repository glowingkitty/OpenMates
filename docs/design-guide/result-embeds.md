# Mandatory result embed design

Read this guide before implementing or changing result previews or fullscreens.
The Website, Finished Search, Connection, Travel Search, Listing, Appointment and
Event Figma PDF exports reviewed in TASK-8017 define the approved structure.
Use existing OpenMates tokens for theme-aware colors, spacing and typography.

## Shared implementation

Use `UnifiedEmbedPreview` with `resultPreview` for result cards and
`ResultEmbedFullscreen` for individual results. The latter composes the existing
fullscreen shell/header, `EmbedLeafletMap` and private request composer. Use
`ResultEmbedCard` for image/title/fallback and wide information/media placement;
use its `contain` media mode when the whole image must remain visible. Use
`ResultEmbedInfo` for compact facts, amenity states and evidence. Collections use
`SearchResultsTemplate` and the same child cards as chat and Apps. Do not recreate
these structures or a local tooltip/composer implementation for each embed type.

Code editors, Docs and Sheets retain their specialized designs. Result extensions
must be opt-in so these surfaces are not restyled by a shared-component change.
Their previews may opt into `previewTools` to expose existing Copy/Download,
More and Expand actions while retaining their editor layout.

## Previews

- All previews inherit the standard `UnifiedEmbedPreview` geometry: 300×200px
  compact desktop, 150×290px when the existing mobile mode is selected, and full
  container width×400px in large mode. Every card keeps the established 30px
  corners. Result types must not override these dimensions or radius.
  Compact grouped and small reference wrappers establish their own named
  `embed-preview` container; they must never inherit a wide chat layout.
- Keep a 48px left/right text safety gap on compact cards even when ungrouped.
  Previous/next buttons belong only to grouped individual results in assistant
  responses, at the bottom corners. Never add them to horizontally scrolling
  app-skill execution cards, including processing and finished search calls;
  those rows retain native scrolling and their position indicator. Titles are at
  most two lines with ellipsis; one-line metadata truncates with ellipsis.
- Show the complete image with `contain`; never crop to fill. Large result cards
  give one third to information and two thirds to media. Letterboxing is dark,
  including in light mode. Existing image aspect ratio does not change card size.
- Dated cards reuse `EmbedCalendarDate`: red weekday over a large day number,
  beside the app tile in compact mode and above the title in large mode.
  Appointment time uses its theme-reactive rounded time pill.
- Event previews contain title, start time, organizer attribution and RSVP count;
  omit description, provider/type/price/location repetitions.

- App-gradient corner tile with the app icon.
- Image-led compact cards: image above the bottom title, fading into the card
  surface. Without an image: favicon/avatar, title and a short description.
- Wide assistant cards: concise information left, media right. Use container
  width so side panels and narrow chat columns behave correctly.
- Image previews use the whole card for the uncropped image, including compact,
  mobile and wide cards. Preserve aspect ratio with letterboxing; omit the
  title/source panel and text fade. Source details remain in fullscreen.
- Assistant content stays selectable; only Expand opens fullscreen. More exposes
  existing fullscreen actions, with one useful core action directly visible.
  Result collections and Apps still open fullscreen on card click. Card-wide
  hover/tilt/press effects apply only when that card itself opens fullscreen.
  More and Expand use existing icons in 36px controls.
- No broken media, repeated title/status blocks or unbounded descriptions.

## Fullscreens

The mandatory order is:

1. Shared app-gradient identity header with source/date, navigation and the
   standard report/share/close controls, with More when existing extra actions
   are available. Do not add an empty overflow menu.
   Reserve horizontal clearance for both navigation arrows on narrow screens.
2. Existing provider action at the header's bottom edge, using
   `EmbedHeaderCtaButton`. Preserve save, booking and calendar-download behavior.
3. Centered compact icon/value fact bar, with 12px additional separation below
   the provider CTA. Static facts have no hover effect. Reuse existing money,
   calendar and team icons. For example: home price/availability/area; appointment
   rating/price/insurance when known.
4. Centered media, with a responsive wide aspect of approximately 3.4:1 for the
   combined image/map row and equal halves. Without an image, the map fills the
   whole row. Map zoom controls keep solid theme surfaces above every tile/layer.
    Photos and maps share a row in wide containers and stack in
   narrow ones. Shared content is at most 64rem wide, with a 34rem detail column.
5. Compact location/identity cards, short description and scan-friendly icon groups.
   Events use the shared identity slot for equal-width organizer and venue cards;
   retain paragraphs, lists, emphasis and safe links in descriptions. Do not repeat
   provider/type/free/date/time/RSVP sections already visible above.
   Home galleries use square rounded thumbnails overlapping the image's bottom
   edge, inactive translucent white overlays and hover transitions. Gallery arrows
   reuse `EmbedChevron` without circular backgrounds; omit numeric counters.
   No-photo home previews use known map geometry. Rent/date facts belong in the
   compact information area. Do not add redundant listing/match/photo/neighborhood
   or location-evidence disclosures.
6. Shared floating follow-up composer with canonical MessageInput geometry and
   focus expansion, with enough bottom padding to scroll all
   information above it. Reuse the current privacy and chat-handoff boundaries.
   Use the same theme-aware background as the regular MessageInput composer. Reserve separate
   playback actions as well as the media itself when the composer expands.

Media-first results use the shared `immersive` layout. Fit the complete image or
player within the available viewport while retaining its natural aspect ratio.
Reserve the header, facts and floating composer's space so playback controls
remain unobscured. Base this budget on the actual fullscreen container height,
including inset Apps hosts; browser viewport units alone are insufficient. Small
source images should still fill the available media area without cropping.
Keep video ownership and playback controls in the existing media components.
For routes, reuse `resultMapRoutes` for parsing, markers and highlighting in both
the collection and map view; highlighting must not reset the map position.

Follow-up context must be an explicit allowlist of visible result metadata.
Never pass raw transport records, file encryption keys, nonces or private storage
credentials to the request interpreter. Cancel abandoned result requests and
ignore responses after the result, account, team or owning view changes.

Do not overlay a narrow text panel over the whole map or show evidence dictionaries
and repeated unknown values as a default wall of text. Short factual tables such
as cold/warm rent are allowed. Do not invent actions from design annotations.

Memory actions use the shared CTA's icon-only heart with an accessible label and
pressed state. Unsaved is white, saved is the existing health pink; transition
background and icon colors smoothly. Keep existing save/forget behavior.

## Icons and uncertainty

Every information icon needs an accessible name and an explanation on hover,
keyboard focus and tap. Tooltip surfaces and arrows import the same stylesheet
as the canonical close/share Tooltip; do not duplicate or invent tooltip styling. Tap pins the explanation; outside tap/Escape dismisses it.
Panels must stay within the viewport and escape transformed scrolling containers.
Confirmed presence uses a check, absence a cross and unknown a neutral question
mark; color is supplementary. Unknown insurance is never converted to eligibility.
Retain provider evidence, source conflicts, assessment coverage and timestamps in
the relevant explanations. Keep a concise location-accuracy label visible. Never
turn an estimated location area into an exact-address pin or a photo inference
into an advertised fact.

## Adaptations

| Result | Required adaptation |
| --- | --- |
| Website/news | Same image/title/fallback design. News adds an event-style top-left publication-date badge when known. |
| Git repository | Text-first avatar, owner/name, description and icon stats; shared fullscreen, provider CTA, languages/contributors. |
| 3D catalogue | Entire uncropped model image, creator/license/file-count facts and existing provider link. No model-file fetching for previews. |
| Image | Largest possible uncropped image, preserving aspect ratio. |
| Video | Largest possible uncropped player; preserve aspect ratio, playback controls and picture-in-picture. |
| Home | Navigable gallery beside OSM map; price/availability/area; amenity state icons and compact rent details. |
| Health | Date/time identity, wide OSM map, practice card, rating/price/insurance and icon-accessible practice details/availability caveats. |
| Travel | Reuse existing route maps and highlighting. Overview shows result routes; hover/focus highlights the corresponding route. |
| Events, stays, map places and flight details | Shared identity, location/route media and compact facts; retain booking, source, live status and calendar download controls. |
| Shopping, recipes, fitness and weather days | Shared card and detail order; keep galleries, ingredients, instructions, hourly forecasts and other useful domain detail below compact facts. |
| Jobs, financial filings, domains, electronics and social posts | Shared identity and scan-friendly facts; preserve source detail, requirements, quote/status uncertainty and existing expanded content. |
| Design icons | Uncropped asset with attribution, recoloring and existing copy/SVG/PNG exports. |

Collections reuse the same cards and shared child navigation. Preserve loading,
cancelled, diagnostic and filtered-empty states, provider-coverage notices and
domain-specific filter actions. Specialized dashboards, interactive editors,
radar animation and 3D viewers retain their functional viewer layouts.

Only mount interactive preview maps while visible and clean them up when hidden.
Preserve image proxying, map themes, factual location geometry and existing media
controls. Add meaningful default/missing-data fixtures and focused bare-preview
coverage, including phone/laptop layout, hover/focus/tap, long titles and unknown
states. Follow `.claude/rules/testing.md` for CI, recordings and visual smoke.

Deploy Home/Health first and provide their preview URLs, then continue other
results during user review. Calendar views and new additional-results behavior
remain a later phase.

## Deferred work

Calendar/additional-results views remain outside this phase. Add “more events
from the organizer” later, after this correction is applied and reviewed; do not
implement that section as part of this release.
