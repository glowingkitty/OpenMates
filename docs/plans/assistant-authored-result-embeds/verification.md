# Verification in progress

The feature is not complete or released. Backend authoring was published to dev
as `c5831accf32584b3c149dc3260769140193f2382`. The web feature and durable
selected-media changes await successful application checks. The approved core
and TV Specifications remain authoritative; wiki is excluded.

## Implemented scope

All 23 eligible existing kinds plus TV movie/series have selected-only schemas,
sources, labelled drafts, ordinary encrypted identities, bounded groups, maps,
and typed web previews/details. Applicable calendar export and sharing remain
explicit. Selected image references have durable owner/chat/initiating-user-
message/subject/revision bindings. No canonical authorization or global recovery
epoch is relaxed. The landing event animation uses real event components.

## Latest isolated evidence

Request IDs identify normal coordinator receipts and their evidence inventories.
This table selects current checks rather than listing superseded attempts.

| Check | Request | Result |
| --- | --- | --- |
| All-kind CLI/npm/Python transport and cold reads | `9c55583fc62b618a54d825de38754b0a2d21227ab25eee866d1e47bdb655bbb8` | 3 passed; no skips/retries; cleanup verified |
| All 25 web kinds, provenance bounds, calendar/unknown/failure states; 390/1100 light/dark | `ebd44fb1fcbf6609b129921aab95cdd08f26e3014039792e69fb209a8b75180d` | 16 passed; no skips/retries |
| Streaming/media browser guards | `fd8f358830ccc11d507efcc6341c0a4a4bee5d252708bd7035a8c854721916ed` | 14 passed |
| Map selection and precision | `469ad902e7d232b74ec129e616690069c4198f0623c51050b53342ec2a9a4b1d` | 4 passed |
| TV movie/series browser presentation | `7e46fc08dbfffe3fc4c3b6ee0feac951c07e3e0f7daf019f6e20121a117824b7` | 11 passed; 1 startup retry then passed |
| Bare event landing animation | `b421e886312516bb65ede0b3fdb6ffb0139fce243d8193c3b6ee618b56ec64e7` | 3 passed |
| Existing landing hero | `065ce1993e1a6e5d23b2276e8dc09b968eea60d1916e26509649c522e05ddfad` | 11 passed; no skips/retries |
| Existing landing mobile / replay | `40de5d7973e5602506aab468d84669df029f17d87a6cc04904d652081761d3bf` / `a34041c27b4eb6ff4ade1bc552f7356d87603af015cadff1973db7b2c0c26f5d` | 5 / 3 passed |
| Saved application records, owner cold recovery and individual/group sharing | `78c865d42e582002c87d48658e19d67f3e03a96000b1c16360c2ca4e1dfb00f7` | Failed at guest movie decryption; prior owner assertions passed |
| Uploaded image retention and explicit child sharing | `9c6616016014819550a792ab6396a6bf86de1f1d2fa9f03e6619198e232b05b0` | Failed at third-turn CLI canonical persistence; later browser assertions not reached |

Latest matrix/hero and application-sharing source:
`b85ac5f7be20e6524dd1b468dc62f087554e185e`. Selected-media source:
`36dfbc5e5b7c9c2e8211783f274da67974e82774`.
The receipts were retrieved under the unchanged 30 GiB reserve. Their evidence
commands uploaded captures and retained S3 identities in the inventories.
Root inspected latest 390-light/1100-dark matrix screenshots: TV metadata and
provenance occupy separate readable space; event detail provenance is readable.

## Corrections awaiting application reruns

- Individual authored children have independent keys. Cold sharing previously
  inherited the carrier key before trying direct wrappers. Direct child wrappers
  now take precedence; invalid wrappers fail closed. Legacy children without
  direct wrappers retain parent fallback. Four focused regressions pass. Broader
  local UI checks encountered unrelated generated-import/setup failures and cold
  import timeouts; they are not claimed green.
- Terminal CLI writes omitted authored catalog/chat context. An existing
  catalogued head can reject that omission. Authored roots/children now send
  their validated existing app/skill identities and explicit chat/Team scope.
  Canonical fallback retains every check and reports only fixed mismatch labels,
  HTTP status and the original protocol code. Seventy focused tests pass. The
  original failure's exact canonical mismatch remains unproven until the rerun.
- Selected-only instruction guidance now distinguishes correction cards from
  decrypted legacy envelopes, preserves supplied photo credits/licence URLs and
  makes no in-place replacement claim. Thirty instruction/main-loop recovery
  tests pass; unsupported TOON/native result envelopes remain rejected.

Earlier durable-reference checks passed 362 Python, 197 recovery-transaction
Node and 88 canonical-transaction Node tests. Metadata service checks passed 44.
Missing local TypeScript runners prevent a package-wide typecheck claim;
isolated CI supplies the application dependency/build environment.

## Remaining acceptance work

1. Rerun both application flows on consolidated corrected source, preserving
   required storage/epoch profiles and individual/group privacy checks.
2. Publish the reviewed scoped feature to dev, refresh required consumers through
   the managed lease, and verify the exact healthy revision.
3. Run current-client, default-routed live mixed-card and uploaded-poster cases.
   An older timed-out mixed run did not establish a saved assistant and is not
   successful recovery evidence.
4. Run fresh real FOSDEM research, review the complete transcript/licensed image,
   admit and sanitize it, publish required locales, then verify phone/laptop
   routes and guest actions. The old candidate contains a later protocol failure
   and must not be published.

The prospective FOSDEM browser test stays outside the first feature candidate
until its real admitted fixture exists. No synthetic transcript, model/provider
override, automatic booking/publication, speech playback, or native Rust/Apple
parity is claimed. Broader native migration remains outside this web delivery's
critical path under the user's explicit scope correction.

## Existing-component reuse correction — 2026-10-28

The user rejected the synthetic landing event card. Its earlier animation
recordings are superseded and do not prove the requested visual reuse.

- Removed `EventResultDetails`; the app landing now instantiates the actual
  `CalendarEventEmbedPreview` and `CalendarEventEmbedFullscreen`. Its timeline
  invokes the preview's real expand button and requires its callback before
  showing the existing fullscreen. The public website keeps its runtime boundary
  and static actionable copy rather than receiving another replacement card.
- All 23 pre-existing authored kinds use their original preview/fullscreen
  constructors. A 24-case registry contract (inventory plus each kind) passes.
  Removed authored-only Fitness and Travel preview layout changes and Health
  fullscreen image sizing; standard image geometry lives in the shared shell.
- TV movie/series compose the shared result card and fullscreen, header, media,
  facts and composer. Eight focused parser/export checks pass. Browser coverage
  now checks shared hierarchy and phone/laptop geometry.

Fresh isolated bare-component evidence for this correction:

| Check | Source / request | Result |
| --- | --- | --- |
| Existing kinds, canonical previews/fullscreens and CTA styling | `ae54ab4c` / `fc91a8d88ae2f59c5ede8eb317151a5a9ce76d60d1f783310432931c8fe9a2aa` | 16 passed; no retries/skips |
| TV movie/series, shared phone/wide design and supplied details | `ae54ab4c` / `a1f3f16b0d5e87986aa8238acf0d0977663a723987f5e15e494d604d201271ea` | 12 passed; one successful retry after cold startup timeout |
| Actual calendar landing sequence, inert controls and visible calendar/action geometry | `0d846f2f` / `36d31ab4936ff56db2c7d34ec61de7bec552c711787e64f34dde0a52f84cc7ed` | 3 passed; no retries/skips |

The final landing candidate differs from the successful matrix/TV source only
in the thin landing adapter, its focused test, and regenerated assertion line
metadata. The initial one-frame scroll alignment left the calendar CTA partly
behind the composer; a bounded alignment step now follows native entrance/layout
changes. Its stricter geometry test passes on both 390px and 1280px profiles.

Inspected actual movie phone/wide previews and details, series seasons, and
existing event CTA captures. The fixture fullscreen now sits outside message
markdown styling, matching production. The existing 150px compact card truncates
long copy; full details remain readable. Shared card padding was preserved.
All matrix/TV/landing recordings uploaded without capture/upload failures. The
final landing preview and native calendar-week captures were inspected on phone
and laptop. Earlier
synthetic-card landing evidence is superseded and must not be presented as proof.
No deployment, full-application sharing/media acceptance, or public-example
completion is claimed by these focused visual checks.
