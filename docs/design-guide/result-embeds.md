# Mandatory result embed design

Read this guide before implementing or changing result previews or fullscreens.
The Website, Finished Search, Connection, Travel Search, Listing, Appointment and
Event Figma PDF exports reviewed in TASK-8017 define the approved structure.
Use existing OpenMates tokens for theme-aware colors, spacing and typography.

## Shared implementation

Use `UnifiedEmbedPreview` with `resultPreview` for result cards and
`ResultEmbedFullscreen` for individual results. The latter composes the existing
fullscreen shell/header, `EmbedLeafletMap` and private request composer. Use
`ResultEmbedInfo` for compact facts, amenity states and evidence. Collections use
`SearchResultsTemplate` and the same child cards as chat and Apps. Do not recreate
these structures or a local tooltip/composer implementation for each embed type.

Code editors, Docs and Sheets retain their specialized designs. Result extensions
must be opt-in so these surfaces are not restyled by a shared-component change.

## Previews

- App-gradient corner tile with the app icon.
- Image-led compact cards: image above the bottom title, fading into the card
  surface. Without an image: favicon/avatar, title and a short description.
- Wide assistant cards: concise information left, media right. Use container
  width so side panels and narrow chat columns behave correctly.
- Assistant content stays selectable; only Expand opens fullscreen. More exposes
  existing fullscreen actions, with one useful core action directly visible.
  Result collections and Apps still open fullscreen on card click.
- No broken media, repeated title/status blocks or unbounded descriptions.

## Fullscreens

The mandatory order is:

1. Shared app-gradient identity header with source/date, navigation and the
   standard report/share/More/close controls.
2. Existing provider action at the header's bottom edge, using
   `EmbedHeaderCtaButton`. Preserve save, booking and calendar-download behavior.
3. Centered compact icon/value fact bar: home price/availability/area; appointment
   rating/price/insurance when known.
4. Centered media. Photos and maps share a row in wide containers and stack in
   narrow ones. Shared content is at most 64rem wide, with a 34rem detail column.
5. Compact location/identity card, short description and scan-friendly icon groups.
6. Shared floating follow-up composer, with enough bottom padding to scroll all
   information above it. Reuse the current privacy and chat-handoff boundaries.

Do not overlay a narrow text panel over the whole map or show evidence dictionaries
and repeated unknown values as a default wall of text. Short factual tables such
as cold/warm rent are allowed. Do not invent actions from design annotations.

## Icons and uncertainty

Every information icon needs an accessible name and an explanation on hover,
keyboard focus and tap. Tap pins the explanation; outside tap/Escape dismisses it.
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

Only mount interactive preview maps while visible and clean them up when hidden.
Preserve image proxying, map themes, factual location geometry and existing media
controls. Add meaningful default/missing-data fixtures and focused bare-preview
coverage, including phone/laptop layout, hover/focus/tap, long titles and unknown
states. Follow `.claude/rules/testing.md` for CI, recordings and visual smoke.

Deploy Home/Health first and provide their preview URLs, then continue other
results during user review. Calendar views and new additional-results behavior
remain a later phase.
