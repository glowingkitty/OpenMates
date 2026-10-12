# Diagram Design embeds

OpenMates vendors the MIT-licensed [Diagram Design](https://github.com/cathrynlavery/diagram-design)
prompt resources at revision `7a2e22170ee838e859d8142ba825d83f8b6375e6`.
It is drawing guidance, SVG primitives and HTML templates, rather than a renderer
package. The 44 type guides and shared layout/style instructions retain the
upstream composition rules. OpenMates changes the palette, uses local Lexend
fonts, removes host installation/onboarding instructions and supplies its own
artifact contract. There is no Diagram Design runtime dependency.

## Selection and generation

JEV stage 1 sees one short Diagrams app capability summary. If relevant, stage 2
receives concise type choices backed by the app's `memories/type-*.md` metadata,
and selects a primary type, at most two additional types, and a visual variant.
It never receives all 44 full guide bodies. The main processor then loads the
complete common guidance, the matching HTML template and only the selected type
guides. Manifest allowlists and SHA-256 checks pin the loaded resources. The
`memories_loaded` event records which type revisions entered the generation
context. Existing generic Memory selection/context limits remain in place.

The model returns a complete static HTML document in an `openmates_diagram`
fence. Streaming first publishes a processing embed; finalization validates the
document before publishing its source. Its stored type is `diagram_html`, app
`diagrams`, skill `html`; the web renderer uses registry key `diagrams-html`.
The encrypted payload contains `html_source`, `title`, `diagram_kind`,
`render_width`, `render_height`, `schema_version: 1`, `version_number` and
`status`. Original HTML and inline SVG are the canonical artifact.

## Rendering and editing

Preview and fullscreen render that same complete HTML page in an opaque iframe
and scale the whole artboard uniformly. Root `data-om-render-width` and
`data-om-render-height` cover the complete page, including titles and legends;
`data-om-background` matches its page background and colors the surrounding
canvas, so fitting an artboard never introduces white gutters. Fullscreen adds fit, zoom, pan and HTML
export. Generated scripts, event handlers and external resources are rejected;
visible read-only frames have no script permission. A separate opaque measurement
frame runs only a first-party nonce-protected reporter after fonts settle. Its
source, opaque origin and per-source token are checked before accepting bounded
dimensions. Presentation can grow beyond an imperfect declared height to fit the
complete page; canonical HTML remains unchanged. Source/history transitions
invalidate old measurements, and excessive or non-converging pages show an error
instead of clipping. The pen control sits immediately left
of Close and uses the same button styling. Edit enables only a trusted runtime
protected by a fresh CSP nonce and source/origin/token checked messages. Changing
edit mode remounts the iframe with its permissions set before loading the HTML.
The fullscreen captures its owning chat when opened. A late selection event for
that same chat preserves the view and its draft; selecting a different chat
still closes it.

Stable, nonvisual SVG metadata identifies editable parts:

- A movable group has `data-om-component="node-id"` and `data-om-editable="true"`.
- A text element has `data-om-text="label-id"` and `data-om-editable="text"`.
- A connector group has `data-om-edge`, `data-om-from`, `data-om-to`, and explicit
  `data-om-from-side`/`data-om-to-side` anchors. Its editable SVG path has
  `data-om-path`; optional label backgrounds have `data-om-label-mask`.
  Rounded elbows and arc bridges remain part of the original visual composition.
- Sequence lifelines and activation shapes use `data-om-owner="participant-id"`
  to follow their participant column. Participant dragging is horizontal, and
  each message retains its original chronological height and endpoint offset.

Clicking text edits it in place. Dragging a group moves its shapes and labels
together and updates attached connectors while preserving their original ports,
rounded paths and message rows. Undo and Cancel operate on
the local draft. Export strips all injected editor/runtime nodes.

Save encrypts the new head and the existing unified-diff history format with the
embed key, adding an initial snapshot only when missing and checkpoints every
32 versions. `commit_chat_diagram_revision` commits head, history and an
idempotent operation receipt in one transaction. Owning-chat authorization,
expected version and source-hash checks reject stale or unauthorized writes.
Legacy writers cannot overwrite a finished diagram. Project-file approval gates
remain authoritative. Version selection reconstructs encrypted history locally;
restoring creates another revision through the same atomic save operation.

The CLI can import/export HTML, summarize the embed and restore versions. Apple
and TUI graphical editors can reuse the canonical source, stable component IDs
and atomic revision contract; they are outside this web-editor implementation.

The CLI waits for the correlated durable first-version receipt before finishing
stream persistence. Retrying the same source reuses its existing encrypted
snapshot. A terminal-message revision-conflict refresh reads the latest chat
version without replaying typed recovery outputs on its second connection; the
original send connection retains recovery ownership and acknowledges the output
once. Ordinary sync continues to recover pending outputs normally.

When a known embed falls outside the bounded sync window, the CLI can fetch its
encrypted head and keys through the existing authorized `request_embed` path.
`embeds show --chat <chat-id>` supplies the owning chat explicitly; live chat
ownership and Team access checks remain authoritative. Missing and denied
embeds still produce errors.

## Evidence and provenance

The vendored `manifest.json`, `audit.json` and `LICENSE` retain provenance and
the security review. Focused prompt, fence, HTML, transaction, revision and
editor tests cover the contract. Browser component tests use the full original
upstream example composition. Authenticated browser tests use signed offline
provider responses through normal JEV and streaming, real chat encryption,
storage, reload and revision restoration. Real inference is validated separately
on dev with a leased disposable test account.

The real-example fixture provenance records each ordinary request, selected
guide revision and original HTML digest. Clean examples cover a dark shop
architecture, a light support flowchart and a dark passwordless-login sequence.
Their generated HTML is copied byte for byte; browser checks compare its SVG
and complete artboard at desktop and phone widths. Earlier failed stream
attempts retain their separate failure provenance and recordings.

JEV still enforces its ordinary token budget for signed offline fixtures. Both
worker images cache the pinned tokenizer tables during the build and verify
that a fresh process can load them without network fetching, since question
packing needs them before the provider fixture boundary.
