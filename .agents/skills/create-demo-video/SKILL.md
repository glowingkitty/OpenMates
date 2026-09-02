---
name: create-demo-video
description: Create captioned engineering proof videos from real CLI, deployed Playwright, or Apple evidence with bounded media processing and frame-only review.
user-invocable: true
argument-hint: "<spec.ts | CLI command> [visible claim]"
---

# Create Demo Video

Use this skill for engineering proof, not marketing video production. Start with
one command:

```bash
python3 scripts/proof_video_workflow.py start --current --spec <name>.spec.ts
```

The command resolves the current sessions.py session, subject commit, and matching
passing run. If evidence is missing or ambiguous, follow its single reported next
action instead of searching artifacts manually.

## Approval Boundary

If `start --current --spec ...` returns `status: contract_approved` with
`approval_source: spec_timeline`, the deployed spec already emitted its checked-in
proof contract and passed every declared assertion. Do not ask for a second chat
approval; continue directly to render/review/publish.

Only for legacy proofs without a spec-owned timeline, draft and show the user the
complete proof contract before capture:

- Three to five short tutorial-style caption sentences.
- One to five assertions describing what must be visibly or terminally true.
- Required device profiles.
- Every caption sentence and assertion lists the exact device profiles where it applies.

For legacy proofs, save the canonical contract only after explicit approval, then
persist the approval record before rendering:

```bash
python3 scripts/proof_video_workflow.py approve --session <short-session> --spec <name>.spec.ts --contract <contract.json>
```

An unchanged already-approved contract may be reused. The spec-owned or approved
transcript is canonical; audio is off by default and `--audio-path` is an explicit
opt-in.

## Capture And Render

- Use a real passing deployed Playwright result, Apple run, or real OpenMates CLI command.
- For Playwright/spec proofs, the rendered video must include real source-video
  segments from the attested Playwright recording. Checkpoint frames may only be
  short freeze segments; never publish checkpoint-frame-only screenshot montages
  or a manifest with `rendered_from: spec_timeline_checkpoint_frames`.
- For web UI component proofs, use the focused component spec recording from
  `https://app.dev.openmates.org/dev/preview/{component-path}?chrome=0`. Every
  inspection and recording must include `chrome=0` and show only the component,
  never the configuration UI. Use the `.preview.ts` default fixture for the
  standard state and encode every non-default input or configuration in URL
  query parameters such as `variant`, `props`, `theme`, `background`, and
  `width`. Publish the component video for every modified UI component, use separate phone/laptop
  profiles only when responsive behavior differs, and derive still frames only
  from the completed video for failures, explicit requests, or ambiguous visual
  inspection.
- Use CLI proof only when the actual `openmates` CLI is the product surface being
  demonstrated or fixed. Do not use CLI proof for generic smoke scripts, pytest
  helpers, Node scripts, or shell wrappers that do not visibly execute the
  OpenMates CLI.
- Browser/native capture must record an explicit ready timestamp after required UI
  is visible. Trim only to that marker minus the fixed lead; do not scan or crop
  until a product defect disappears.
- Exact profiles remain mandatory: web phone `390x844`, web laptop `1440x900`,
  iPhone portrait `393x852`, iPad landscape `1366x1024`, CLI `1280x720`.
- Captions are sentence-level WebVTT cues delivered through the video player's toggleable captions track. Never burn captions into video pixels or shrink, pad, border, or otherwise reserve frame area for captions. Pacing may use only whole-video
  slowdown to `0.75x` and a final hold, with a 35-second output cap.
- Process one device at a time. Do not use OCR or place the full video in model
  context. Sample periodically every five seconds, prioritize event boundaries,
  deduplicate nearby timestamps, and cap the immutable index at twelve frames per
  device.

## Review And Repair

Run the canonical review command rather than manually selecting frames or writing
claim verdicts:

```bash
python3 scripts/proof_video_workflow.py review --run-dir <path> --correction-round 0 --correction-kind none
```

Review every clean frame in the immutable one-to-twelve-frame device index plus the
complete device-applicable WebVTT cue text, approved device-applicable assertions,
and deterministic metadata. Before evaluating assertions, complete the mandatory
per-frame critical UI scan for layout, readability, geometry, controls, visual
assets, application state, consistency, and proof alignment. Return exactly one status:

- `passed`
- `capture_defect`
- `render_defect`
- `product_defect`
- `uncertain`

Every verdict needs frame-grounded observations. Blank opening frames may be corrected mechanically once. Caption syntax, ordering, and bounds are deterministic checks rather than visual-review concerns. Unexplained scroll state returns to
capture. Clipping, broken headers, wrong UI state, raw implementation text, stale
loading, and broken navigation are product defects. When the reviewer classifies
the defect intent as `obvious`, automatically add or strengthen a failing test,
fix the product, deploy, and recapture. When intent is `unclear`, upload the
representative blocker frame and ask the user for consent before product-code
changes. Never hide defects through trimming, cropping, caption edits, or transcript edits.
Contrast, text-size, opacity, font-weight, and related typography/readability findings
are advisory design concerns from frame-only review: report them to the user as
`unclear` warnings and never route them to automatic product correction.
Do not ask that visual-intent question until the exact cited blocker image is
successfully embedded in the same response with a short explanation of what the
user should inspect. If media delivery fails, repair or retry it first; never
substitute a text-only question, local path, or uncited description.
After explicit user approval, bind the exact unclear finding into the receipt with
`python3 scripts/proof_video_workflow.py approve-intent --run-dir <path> --finding-id <id> --reason "<decision>" --approved-at <ISO-8601>`. This may resolve only
`uncertain` checks cited by that finding and must not override failed checks or
unsupported assertions.

The entire proof contract is limited to six AI review calls and forty-eight cumulative submitted frames.
It permits one initial review plus at most two
automatic correction rounds, including at most one product-code correction round.
Re-review only changed device hashes. Unclear intent, uncertain findings, repeated
defect fingerprints, or exhausted budgets require immediate user input.

If review returns any blocker status (`capture_defect`, `render_defect`,
`product_defect`, or `uncertain`), inspect the returned `blocker_media` metadata
before responding. Run its `upload_command` and paste the returned `<video>` HTML
in the blocker response so the user can see the exact failed recording. If
`blocker_media.media_status` is `missing`, state that as a workflow defect and
include the missing `video_path`; do not report the blocker or ask for design
consent with text alone. Run `image_upload_command` and embed the cited frame before
any visual-intent question.

After a passed frame review, upload the approved proof video with its hash-bound WebVTT sidecar or representative
proof screenshots with `python3 scripts/opencode_response_media.py <path> --alt
"..."` and paste the returned image Markdown or `<video>` HTML in the final
OpenCode response. Do not send proof media to Discord unless the user explicitly
asks for a separate Discord mirror. Retain transcripts, captions,
manifests, hashes, review evidence, and response-media publication state.
