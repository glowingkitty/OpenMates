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

For new user-visible claims, draft and show the user the complete proof contract
before capture:

- Three to five short tutorial-style caption sentences.
- One to five assertions describing what must be visibly or terminally true.
- Required device profiles.
- Every caption sentence and assertion lists the exact device profiles where it applies.

Save the canonical contract only after explicit approval, then persist the approval
record before rendering:

```bash
python3 scripts/proof_video_workflow.py approve --session <short-session> --spec <name>.spec.ts --contract <contract.json>
```

An unchanged already-approved contract may be reused. The transcript is canonical;
audio is off by default and `--audio-path` is an explicit opt-in.

## Capture And Render

- Use a real passing deployed Playwright result, Apple run, or real OpenMates CLI command.
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
complete device-applicable WebVTT cue text, approved device-applicable assertions, and deterministic metadata. Return exactly one status:

- `passed`
- `capture_defect`
- `render_defect`
- `product_defect`
- `uncertain`

Every verdict needs frame-grounded observations. Blank opening frames may be corrected mechanically once. Caption syntax, ordering, and bounds are deterministic checks rather than visual-review concerns. Unexplained scroll state returns to
capture. Clipping, broken headers, wrong UI state, raw implementation text, stale
loading, and broken navigation are product defects: add or strengthen a failing
test, fix the product, deploy, and recapture. Never hide them through trimming,
cropping, caption edits, or transcript edits.

The entire proof contract is limited to six AI review calls and forty-eight cumulative submitted frames.
It permits one initial review plus at most two
automatic correction rounds, including at most one product-code correction round.
Re-review only changed device hashes. Uncertain findings, repeated defect
fingerprints, or exhausted budgets require immediate user input.

After a passed frame review, upload the approved proof video with its hash-bound WebVTT sidecar or representative
proof screenshots with `python3 scripts/opencode_response_media.py <path> --alt
"..."` and paste the returned image Markdown or `<video>` HTML in the final
OpenCode response. Do not send proof media to Discord unless the user explicitly
asks for a separate Discord mirror. Retain transcripts, captions,
manifests, hashes, review evidence, and response-media publication state.
