# Design editor format comparison

**Recommendation. Ship the versioned typed scene on Canvas 2D.** Use typed JSON for assistant creation and revision-checked operations for follow-up edits. Keep the restricted markup importer as an experiment. Browser markup produced the strongest flyer and reduced dense drag work. The gain at 250 layers is small relative to the added layout, editing, security and export work. Stable-ID vector paths remain editable as layers. Path control-point editing was outside the trial.

## Assistant creation and editing

Each format got the same five briefs, dimensions and local photos. Gemini 3.5 Flash-Lite ran in dev incognito with three independent creation calls and one joint repair/edit call per brief. The 18 returned replies reported 338 credits across 20 attempts. The gate checked syntax, page geometry, asset references, IDs and layer count. Visual review checked the copy, composition and clipping. Each creation result is one sample from one model.

| Brief | Typed JSON | Browser markup | Hybrid import |
| --- | --- | --- | --- |
| Event flyer | Valid first try. Bold, but the motif overlaps the date. | Valid first try. Strongest hierarchy and clearest ticket callout. | First reply used unsupported CSS and nesting. One repair still used an unsupported path command. |
| Photo collage | Valid first try. Three aligned crops and readable captions. | Valid first try. Stronger rhythm through staggered photos and frames. | One repair removed unsupported CSS and imported all photos, but accidentally applied the follow-up headline. |
| Square social post | Valid first try. Readable copy, larger botanical motif. | Dimensions lived in a stylesheet. The model patched the wrong format. Harness normalization preserved the styled card. | A nested layout failed import. One repair still used unsupported SVG structure. |
| Three-page app mockup | Valid first try. Consistent screens. Explore became Discover and omitted the destination cards. | Wrapper, links and dimensions failed the contract. After harness normalization it showed richer, consistent navigation and destination cards with placeholder images. | Unsupported image styling failed import. The shared follow-up returned malformed JSON, so neither app repair was accepted. |
| Dense 250-layer page | CLI timed out waiting for the AI response. | Returned 240 marks and 251 IDs. One repair met the 250-layer contract but dropped the artboard class, which made the headline hard to read. | CLI timed out waiting for the AI response. |

First-pass validity was **4/5 typed, 2/5 browser markup, 0/5 hybrid**. One bounded follow-up raised these to **4/5, 3/5 and 1/5**. Timed-out outputs were unavailable for repair. A short grid primitive or batched layer generation deserves a separate test before exposing dense assistant creation. These results depend on the prompt and validation contract. Browser markup has more visual range, and some failures came from ordinary HTML habits such as wrapper elements and stylesheet sizing.

Browser tests changed the headline, moved and resized its layer, then undid the edits on all 15 format and brief combinations, including the labeled fallbacks. Assistant follow-ups applied in **4/5** typed and converted-hybrid cases and **2/5** markup cases. The typed prompt supplied the target ID, base revision and operation shape. The markup prompt supplied the original element for an exact, unique replacement. The flyer patch collapsed whitespace, the collage patch targeted the hybrid element, and the shared app response was malformed. The successful social edit also exposed a separate problem. It passed structural validation, but the longer headline clipped on Canvas. Add text-fit feedback before saving assistant edits.

[Four brief screenshots](format-evidence/four-briefs.webp) · [All three app screens](format-evidence/app-pages.webp) · [Follow-up edit](format-evidence/follow-up.webp)

## Desktop and phone emulation

Chromium 156 on the dev host used a 1280 × 860 desktop viewport at 1× DPR and a 390 × 844 touch viewport at 2× DPR with 4× CPU throttling. The five scenes were matched across renderers, including Explore and the Phase 0 250-layer fixture. The same 750 ms drag updated one DOM node or repainted the Canvas page. Hybrid converted once and then used that same Canvas renderer. Each cell is the median of three fresh contexts. Cold time includes navigation, module load and photo decode through two animation frames. The harness omits app bootstrap.

| Profile / fixture | Format | Cold paint, ms | Drag FPS | Frame p95, ms | Render work p95, ms | Retained JS, MiB | Canvas RGBA, MiB |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Desktop / 250 | Typed | 132.3 | 60.1 | 18.5 | 4.2 | 1.27 | 1.77 |
| Desktop / 250 | Browser markup | 158.7 | 60.0 | 17.1 | 0.5 | 1.61 | — |
| Desktop / 250 | Hybrid | 130.1 | 60.1 | 18.6 | 4.1 | 1.32 | 1.77 |
| Phone / 250 | Typed | 297.9 | 59.2 | 20.5 | 8.9 | 1.31 | 1.44 |
| Phone / 250 | Browser markup | 412.9 | 60.3 | 18.0 | 2.6 | 1.65 | — |
| Phone / 250 | Hybrid | 357.8 | 58.3 | 23.2 | 9.9 | 1.34 | 1.44 |

The other four briefs stayed at about 59–61 FPS in both profiles. Phone first paint across those briefs ranged from 260–396 ms typed, 296–362 ms markup, and 274–399 ms hybrid. On the dense phone fixture, markup reduced frame p95 by 2.5 ms versus typed and first paint took 115 ms longer. The three repeats are too few to attribute hybrid's slower pacing to the format. It shares the typed renderer. Markup held about 0.33 MiB more JS heap in the dense phone case, with 1,273 counted DOM nodes versus 17 for typed. Heap excludes native DOM and layout memory, decoded images and GPU allocations. The canvas column counts one RGBA buffer. Physical-phone memory and touch latency remain unmeasured. [All 90 raw browser samples](format-evidence/measurements.csv)

## Safety and collaboration

- The markup and hybrid gates refused all seven test cases covering script, event attributes, remote HTML/SVG images, CSS URL and import, and a frame. The sandbox and CSP also suppressed the script marker and external requests in a separate bypass-of-validation control. Typed markup-like text stayed data and a remote asset reference failed validation. Direct rendering needs a maintained HTML/CSS/SVG and asset policy, script-free isolation and revalidation of patches, merges and exports. Hybrid adds an inert, fail-closed importer before reusing typed validation. Both need broader sanitizer and resource-limit tests.
- Yjs 13.6.27 replicas preserved independent headline and transform edits in typed maps and in a character CRDT. A whole-page markup string in a map lost one edit. Overlapping character edits combined two replacement titles, and concurrent tag and style edits produced duplicate headline IDs. Typed maps retained one whole transform under concurrent move and resize, delete won over a nested edit, and origin-tracked undo preserved the peer's move. A structured markup tree could assign stable IDs and field-specific merge rules. That would still require a layout and style model with deterministic validity checks.
- The repo-pinned Rust `yrs` 0.28.1 accepted Yjs updates in opposite orders and reproduced the independent edits. Rust origin-tracked undo kept a separately tagged color change. Yjs then consumed the Rust update in both orders and converged on the same state. This tested the merge primitive in isolation. Existing OpenMates transport, reconnect and permissions need design-specific integration tests.

## Export and client-side encryption

PNG, SVG and PDF were exercised on all 21 rendered artboards, including the three-page mockups at the correct size and order. Pixel drift is the share of pixels differing from the Chromium artboard capture by more than 16 levels in any RGB channel.

| Export | Typed JSON and converted hybrid | Browser markup |
| --- | --- | --- |
| PNG | All 14 pages matched the Canvas artboard pixel for pixel. | A blob-backed SVG with HTML `foreignObject` tainted the canvas. An SVG data URL exported in Chromium. Drift ranged from 0% to 28.23%. |
| SVG | Native rect, ellipse, path, text and embedded pictures. Chromium drift was at most 0.21%. | HTML remained within `foreignObject`. Chromium rendered it with the same drift as PNG. Portability to other SVG tools was outside the test. |
| PDF | Chromium printing retained vector paths and extractable text and produced 0.67–3.79% drift. | Page count and sizes passed. Drift was 2.05–53.86%, with the flyer gradient among the largest differences. |

All three formats can use the existing client-side encrypted embed envelope. An isolated AES-GCM check round-tripped all three payloads and a Yjs update. All four wrong-key attempts failed. The Rust writer seals opaque content with the embed key. Keep documents, assets, synced previews, snapshots, changes and presence client-side encrypted. Resolve and render assets locally after decryption. Assistant requests can use the existing explicit, bounded request-context disclosure path. Exports are user-initiated local copies. The prototype exercised the byte boundary. Design persistence and encrypted collaboration integration remain product work. [Embed writer](../../../packages/openmates-rust/src/client/embed_write_payload.rs) · [Collaboration specification](../../../specifications/features/live-collaboration/specification.yml)

## Finish the design embed

1. **View mode.** Add a versioned Design schema and bounds in the Rust core. Wire the client-side encrypted embed and authorized asset reads to the local renderer. Ship read-only page navigation and thumbnails, fit and zoom, and restricted-view permission checks. Prove load and reload with real encrypted assets.
2. **Edit mode.** Persist stable-ID, revision-checked text, path and transform commands with undo and version history. Connect assistant creation and follow-up edits to schema validation, text-fit feedback and a bounded repair path. Prove touch editing, reload, stale-revision rejection and local export. Keep the provisional cap at 250 layers until a physical-phone run covers both a dense page and decoded photo memory. Build live collaboration on the shared Rust core and add two-user conflict, reconnect and selective-undo checks before enabling it.
