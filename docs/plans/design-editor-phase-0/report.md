# Design editor Phase 0 report

The web preview exercises direct editing on a fixed artboard. It uses five editable documents: an event flyer, a photo collage, a square social post, an app mockup with Explore, Saved and Profile pages, and a pattern study that scales to 1,000 layers. The preview retains edits as you switch between view and edit. Reloading restores the sample. The app mockup switches pages from a compact chooser with thumbnails. Open the [dev preview](https://app.dev.openmates.org/dev/preview/embeds/design/editor/DesignEditorFullscreen) to choose a sample, theme and viewport.

## Document model

A design is one document with a title and an ordered list of pages. Each page has a stable ID, a name, a fixed width and height, a background, and an ordered layer list. A one-page design is a regular document. Page sizes may differ in the same document. A layer belongs to exactly one page. Every embed owns its document. Copying a layer creates a fresh ID and independent properties.

The origin is the top-left of the page. Coordinates and sizes are page units. Zoom and pan map those units to screen pixels without editing the document. All layers have stable IDs, names, local bounds, a rotation around their centre, and visibility and lock flags. Stacking runs from back to front. A locked layer keeps its place and is visible when its visibility is on. The editor exposes geometry for the chosen layer and only exposes color or text controls for applicable layer types.

| Layer | Fields and behavior |
| --- | --- |
| Shape | Rectangle or ellipse, solid fill, optional rectangle corner radius |
| Text | Plain text, explicit line breaks and wrapping inside the box, font, size, weight and color |
| Image | Asset reference, crop-to-fill inside its box, position, size and rotation |
| Path | A bounded set of filled vector commands, source bounds and one fill color |

The preview uses a Canvas 2D backing surface at up to 2× pixel density. Every change paints the active page from its layer values. A pointer gesture updates a temporary layer and commits once on release so one undo reverses one gesture. Page thumbnails use the same renderer with a small backing surface while the chooser is open. The list mounts at most 40 rows at once. The preview caps clipboard insertion at 250 layers per page and exposes larger built-in stress fixtures for testing.

For a first product build, add a schema version and enforce a nonempty, bounded page list, unique IDs, positive bounded page dimensions, finite bounded transforms, minimum layer sizes, byte and command limits for paths, text length limits and supported fonts. Use document-owned asset references in place of the bundled preview image URLs. Normalize the path command subset and cap both total decoded pixels and individual asset dimensions. Keep editor zoom, current selection and transient drag drafts outside the document. These limits protect memory as well as parsing and rendering. A layer count by itself cannot predict the cost of a large image or a complicated path.

## Performance

The isolated GitHub Chromium run used a desktop viewport of 1280 × 860 CSS pixels and a phone viewport of 390 × 844 with 4× CPU throttling and touch emulation. The benchmark requested a higher phone pixel ratio. The table gives the canvas backing size observed in the runner. GPU throughput, memory limits, heat and touch latency need a real handset.

Each row is the median of three fresh browser contexts. Cold paint runs from navigation start to the first complete canvas draw. It includes preview-route and runtime module loading on the runner-local Vite server. Drag timing counts actual canvas redraws and records the 95th-percentile interval between draws. JavaScript heap was sampled after collection and includes the preview runtime. The canvas figure estimates one RGBA backing buffer from its pixel dimensions. GPU allocation, browser process overhead and decoded photo memory are outside those figures. The stress design mixes shapes, text and simple paths. The collage exercises image decoding in the visual check.

| Profile | Layers | Drag FPS | p95 frame interval | Cold paint | Retained JS heap | Canvas buffer |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Desktop | 50 | 59.0 | 17.2 ms | 3.03 s | 107.61 MiB | 2.35 MiB |
| Desktop | 100 | 59.0 | 17.0 ms | 2.77 s | 107.64 MiB | 2.35 MiB |
| Desktop | 250 | 59.0 | 17.1 ms | 2.78 s | 107.72 MiB | 2.35 MiB |
| Desktop | 500 | 59.0 | 17.2 ms | 2.73 s | 107.86 MiB | 2.35 MiB |
| Desktop | 1,000 | 58.9 | 17.1 ms | 2.80 s | 108.14 MiB | 2.35 MiB |
| Phone emulation | 50 | 60.0 | 17.2 ms | 5.88 s | 107.47 MiB | 1.16 MiB |
| Phone emulation | 100 | 60.0 | 17.2 ms | 5.84 s | 107.49 MiB | 1.16 MiB |
| Phone emulation | 250 | 60.0 | 17.3 ms | 5.71 s | 107.56 MiB | 1.16 MiB |
| Phone emulation | 500 | 60.0 | 17.2 ms | 5.80 s | 107.68 MiB | 1.16 MiB |
| Phone emulation | 1,000 | 58.5 | 19.3 ms | 5.72 s | 107.89 MiB | 1.16 MiB |

The phone profile stayed near 60 FPS through 500 layers. At 1,000 layers it dropped to 58.5 FPS with a 19.3 ms p95 frame interval. Raising the count from 50 to 1,000 added 0.53 MiB of retained JavaScript heap on desktop and 0.42 MiB on the phone profile. Initial paint varied far more by CPU profile than by layer count. The first optimization target is startup cost. Profile module loading and app bootstrap separately before introducing canvas tiling or changing the renderer. [Benchmark run and raw samples](https://github.com/glowingkitty/OpenMates/actions/runs/45312899792)

**Provisional cap: 250 layers per page, to be confirmed on a physical phone.** The Phase 0 phone measurements use throttled emulation as agreed. Image-heavy pages also need a separate stress profile. Treat the cap as a guardrail for a defined minimum device and supported artboard and asset budgets. Revisit it after profiling, especially if the first product release needs many large images on one page.

## Assistant creation and edits

A later release should admit authoring as its own embed kind, for example `design.document`, with an explicit `authoring` block on that embed type in `backend/apps/design/app.yml`. Follow the existing pattern where each `backend/apps/*/app.yml` owns the opt-in, and the authoring catalog matches kind, schema ID and backend embed type. Add the versioned Design schema and concise Design instructions to that catalog. The preprocessor already admits authoring definitions from discovered app metadata and resolves the relevant preview kinds. The main processor then builds only the admitted schemas and relevant guidance into the assistant prompt. Connect Design to that route so a request for a flyer gets Design instructions and other requests avoid carrying them. The current catalog models structured result cards. Validate the envelope size and streaming behavior for a full document before adopting the existing fence as-is.

For creation, give the assistant a typed document schema and a compact working example. Describe units, page size, element IDs, back-to-front order, text bounding boxes, supported fonts, how to reference approved image assets and the layer cap. Ask for meaningful names and editable text. Show how to produce a layout with safe margins, a reading order and sufficient contrast. Require a confirmed reference for any image or icon. A plain path may contain bounded geometry and no script, markup, external resources or style.

Parse the response as data. Validate schema and limits before allocation or rendering, then check referential integrity, dimensions, asset ownership, permissions and basic layout. Warn about clipped text or a fully off-page layer. Return compact diagnostics with JSON field paths and an error code to the assistant for a bounded repair. Screen layout quality separately because valid geometry can still be unusable. If repair fails, explain why creation failed and offer a fresh attempt. For an existing design, leave the current revision in place. Invalid output should never become a saved revision.

For edits, send a small, authorized snapshot containing stable target IDs, relevant geometry and text, and a revision token. The assistant proposes typed operations against that base revision, such as update the headline text or insert a shape behind an existing layer. The client validates the complete change set, shows the affected pages and applies it atomically. Preserve page and layer IDs so links to selection and changes survive. Re-check the base and permissions at apply time. If another edit removed a target or changed the same properties, seek a refreshed edit against the new revision. Reuse the existing embed diff history for user-facing versions. Prefer structured IDs for applying a canvas edit. A text diff of stable serialization can explain what changed and support existing history tooling.

## Real-time editing and undo

The current shared collaboration plan puts the authoritative Yjs-format replica in the Rust core, using yrs. The web editor renders core view models and sends typed commands. The core owns merge, encrypted transport and snapshots, reconnect, undo, assistant changes and version history. The current Rust `DeckDocument` provides a reference for typed operations, validation, view projection and tracked undo in `packages/openmates-rust/src/client/shared_items/`. Model the Design page and layer maps after Slides, with stable IDs for records and explicit ordering. Add a typed Design projection and serialiser and reuse the same core infrastructure. The Phase 0 Svelte history is a prototype UI mechanism. [Shared collaboration plan](../live-collaboration-crdt/plan.yml)

A freeform canvas needs insert, delete and duplicate for pages and layers, order changes anchored to stable IDs, text and style edits, asset replacement, visibility and lock changes, and a transform command for position, size and angle. Use the local pointer preview during a drag, then commit one transform. Publish only ephemeral hints for active handles or cursors if collaborators need to see the gesture.

Store a transform as a single value so concurrent edits cannot combine a new left edge with someone else's width into an unintended rectangle. Edits to different layers or independent fields converge independently. For the first real-time version, make competing transforms of the same layer resolve consistently to one complete transform using shared CRDT ordering. A color edit and a move can both survive. A resize racing a move will lose one transform, so provide collaborator presence and show when the visible layer has moved underneath a local gesture. Delete takes precedence over edits to the deleted layer. Use stable ordering keys and an ID tie-break for concurrent reorder, then test moves across the same neighbors and reorder versus delete. Start without automatic transform composition. It is difficult to preserve the anchor and intent of rotated resizes. Also define behavior when concurrent inserts cross the layer cap. Keep the overflow recoverable, agree on which layers fit the rendering budget, and surface the state to both editors.

Track local operation origins for undo, including an assistant change applied on the requester's behalf as one group. Check that undo of a superseded transform leaves the other collaborator's current transform intact. The inverse becomes a normal shared update. Named versions should use the shared client-made encrypted snapshots with contributors and a compact change description. Restore applies a new validated change set over the shared state and creates a new version.

## Client-side encryption

Design documents, image assets, thumbnails saved for sync, operation payloads, version snapshots and collaboration presence must be client-side encrypted using the existing embed key and membership rules. The server authorizes access to opaque records and relays encrypted packets. It has neither the design key nor a plaintext canvas copy. Keep the generated thumbnails local until an approved encrypted cache path exists. Avoid plaintext document content in telemetry, logs, crash reports and performance fixtures.

Assistant authoring needs the product's existing explicit request context path. Only disclose the bounded content the requester addresses and is authorized to share, with the same treatment for images. Give model responses to the authorized client for validation and encrypted storage. Keep version and selection context local unless it is needed for that request. Retain the existing restrictions for members without write access or share-link viewers. Exports are user-initiated and rendered using the locally decrypted document. A downloaded file can contain readable artwork and should be handled like any other downloaded copy.

## Export

1. **PNG.** Draw the requested page at the selected size with the same renderer, after decoding available assets and fonts. Use a separate export surface with a pixel budget, and test transparency, crop, clipping and missing-asset handling. Start with one page per file.
2. **SVG.** Serialize only the typed elements and attributes from the document. Generate rectangles, ellipses, paths and transforms and use vetted embedded images. Decide whether to embed fonts or convert text to outlines after reviewing font licensing and the need for editable output. Compare file rendering against the live artboard.
3. **PDF.** Put each page at the correct document size in page order. Preserve text and shapes as vectors where the PDF path is reliable. Rasterize unsupported layers using deterministic settings and check page sizes, clipping and font appearance in representative viewers. Bound work by total pages and pixels.

## Phased delivery and feasibility

Estimates are engineer-weeks for a web-first build with focused verification. Integration schedules and review can add elapsed time. Later phases start after Marco reviews Phase 0.

| Phase | Work | Estimate |
| --- | --- | --- |
| 1 | Shared Design schema, validated asset ingestion, client-side encrypted persistence and versions, accessible editing and physical-device performance tests | 3–5 weeks |
| 2 | Page strip, page creation and ordering, starter templates and PNG/SVG/PDF export with renderer parity checks | 3–5 weeks |
| 3 | Assistant creation and typed revision edits, repair loop, layout evaluation on distinct design briefs | 3–5 weeks |
| 4 | Reuse live collaboration core for the canvas. Add two-user gestures, reconnect, presence, conflicts, undo and versions evidence | 3–6 weeks after the core is ready |
| Later | Evaluate auto layout after the fixed-artboard editing model has real usage. | Separate estimate after discovery |

**Verdict.** A bounded flyer, collage, social post and fixed-screen mockup editor is feasible. Product readiness depends on predictable text layout and export, a reliable touch editor, and real-device evidence for the asset and layer limits. Collaboration has a viable reuse path, with the largest correctness risk in simultaneous transforms, reorder and undo. Assistant layout quality is a separate unknown and needs visual evaluation beyond schema validation. Phase 0 supports review of the editing model and the interface. Use the measured results to decide how much of the renderer can carry into the next phase.
