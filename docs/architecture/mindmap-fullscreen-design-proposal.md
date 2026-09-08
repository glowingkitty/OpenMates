# Mindmap fullscreen design proposal

Status: draft, awaiting current visual evidence and user design approval.
Task: TASK-4213 / coordinator TASK-5745, Plan assignment TASK-18.
Session: cf3b. Codex thread: 01a080f6-dbe3-7151-97d7-1e0dd6916fa2.

## Evidence and boundaries

Source inspected at session starting commit 7bf8f5aa3:

- `MindMapEmbedFullscreen.svelte` unconditionally renders a Source heading and
  `pre` containing source JSON, including after a valid visual map.
- `MindMapCanvas.svelte` renders fixed-width cards with wrapping descriptions;
  `mindMapContent.ts` calculates positions and bounds using a fixed 64px height.
  Overlap with long text is a risk, not yet a browser-confirmed defect.
- `mindmap-embed.spec.ts` checks opening, zoom, collapse, export and closing;
  it does not assert absence of normal-view source JSON or long-label geometry.
- The existing mindmap Plan explicitly preserves source/error recovery for
  unparseable documents. Removing normal-view JSON must retain that recovery
  behavior and `.ommindmap` export.

Coordinator clarified that none of the six parent attachments shows a mindmap;
the Figma screenshot refers to video preview only. No historical mindmap image
is required. This proposal is an original directional
interpretation of the requested MindNode-style design, not a fidelity claim.

## Proposed design

Use one canvas filling the available fullscreen body beneath the existing
OpenMates title/download/close header. Normal fullscreen contains the rendered
map and navigation controls, with no Source panel or raw JSON.

For tree-shaped maps, place the central topic in a prominent rounded node and
balance primary branches to its left and right. Use gently curved branch lines,
one restrained color per primary branch and lighter descendants. Preserve
explicit document colors. Reduce card borders and shadows so relationships and
labels carry the hierarchy. Keep explicit cross-links and disconnected nodes
visible; never infer new relationships or discard graph content for symmetry.

Measure wrapped labels when laying out branches. Reserve space for expanded
descriptions and collapse controls. No truncation of the only accessible copy
of a label. Branch collapse retains a visible descendant count. Preserve pan,
pinch, zoom, fit, download and embed navigation. Collapsing a branch should
preserve the user's local focus; fitting the entire map remains an explicit
action after initial opening.

On laptop, place compact zoom/fit controls over a safe canvas corner. On phone,
keep them above the safe-area inset with adequate touch targets. Fit the map on
opening; allow zooming into labels without horizontal document scrolling.

Partially invalid maps retain visible warnings and valid branches. Completely
invalid maps retain an explicit error and existing copyable source recovery.
Keep canonical storage, encrypted content, upload and export formats unchanged.

## Concrete review examples

- Launch Plan: central topic, Research and Delivery on opposite sides, curved
  colored branches, full canvas, no JSON beneath the map.
- Long-label map: multi-line topic labels reserve their actual height without
  overlapping siblings or clipping links.
- Phone: pan to a branch, expand it, zoom in, then Fit to recover the overview.
- Broken import: visible error and source recovery rather than a fabricated map.

## Implementation and verification after approval

Own the mindmap fullscreen, shared canvas and layout utility; lease exact files
before edits. Preserve other workers' changes. Add component preview fixtures
and focused assertions for valid/no-source, invalid recovery, long labels,
collapse, fit and touch navigation. Extend the existing import/export E2E only
where broader coverage is needed. Review phone/laptop proof and the actual
candidate conversation after component verification.

Locate the applicable approved Specification before semantic changes; if it
requires amendment, present its exact review PDF separately. Follow the test
dispatcher and report any unsupported runtime hold rather than bypassing it.
Apple has a mindmap counterpart; native work follows web approval.

## Current gates

1. Capture the current renderer with the approved isolated browser tooling.
2. Present a visual proposal from current rendering and obtain design approval.
3. Confirm Specification coverage before semantic implementation.

The authorized normal-view JSON fix is implemented; the canvas redesign is
untouched. No browser/test pass is claimed while the shared CI gate holds.

Proposal illustration: [laptop and phone](mindmap-fullscreen-proposal.svg).
Rendered review copy: `test-results/mindmap-design/proposal.png`.
This is a design illustration, not evidence of the current renderer.

## Local milestone outbox

2026-09-08: Own worktree verified distinct from coordinator agent-4aa6 and
source-CLI worker agent-6d7a. Task activity read succeeded and contained creation
only. Thread connection and milestone posting failed with HTTP 429; neither is
claimed acknowledged. Coordinator instructed all workers to stop Tasks calls
for at least ten minutes and await serialized recovery. Preserve this milestone
for later acknowledged posting to TASK-4213 and reporting to TASK-5745.

Process note: repeated connection retries, including an unnecessary UUID retry,
did not resolve the shared rate limit. Existing coordinator backoff instruction
is sufficient; no additional workflow prose is proposed.

Coordinator correction: missing historical mindmap imagery is not a blocker.
Raw JSON removal is authorized independently of the redesign. The existing
import/chat E2E dispatch returned a coverage hold for live model credentials,
spending caps and isolated upload/media infrastructure. A public component
fixture avoids those unrelated dependencies for renderer inspection; it does
not replace the held upload/chat coverage.

2026-09-08 12:42 UTC coordinator handoff:

- CI dependency classification deployed as `d0802d26d039d52350a24ca4c95fdce9b80c1fdd`.
  Only `scripts/ci_coverage_manifest.json` was deployed; no renderer redesign.
- Current-renderer visual capture request:
  `62d53eb0aa51f0cd12d6975b625349ed9aac966d339f84412dd5f644de2c1f6a`,
  source `f9e57458c25881fec56632ba3f0a4a58a8f1e65a`, queued.
- Public component no-JSON regression request:
  `9891e754eb332707787cf9ef7ec152d920efc4c2b2f3fe42cc90f3d7f97e3334`,
  source `8ba4bc69c3e991995fd18a54357b6b6193f53355`, queued, no coverage hold.
- CI health identifies prerequisite
  `46493e6e920ebdade2670c7bb54bc3f76a85d0c462306b7072d5cf4474d8661e`;
  its cached state is failure, run `34202406401`. Leave shared queue recovery
  with its coordinator; do not change that prerequisite or bypass isolation.
- Focused regression metadata validates. Local TypeScript lint could not run
  because this worktree has no tsc/eslint dependencies. Browser red/green and
  current visual evidence are still unavailable while the prerequisite holds.
- After the no-JSON regression reaches its expected red result, wrap the Source
  section in `normalized.status === 'invalid_source'`, retain source JSON for
  download, correct the outdated header comment, and rerun both valid/invalid
  component cases. Preserve error recovery and do not redesign the canvas.
- Review current capture, present it with the original proposal illustration,
  obtain user design approval, then proceed with the separately approved redesign.

Coordinator repeated the explicit instruction to continue the raw-JSON fix.
Implemented the narrow Source-panel condition under that authorization despite
the queued red run. The queued red candidate remains immutable and pre-fix;
its result must not be inferred from source inspection. Valid maps now omit
the panel; unparseable documents retain it. Download and canvas code are intact.
