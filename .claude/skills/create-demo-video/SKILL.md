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

Save the canonical contract only after explicit approval, then persist the approval
record before rendering:

```bash
python3 scripts/proof_video_workflow.py approve --session <short-session> --spec <name>.spec.ts --contract <contract.json>
```

An unchanged already-approved contract may be reused. The transcript is canonical;
audio is off by default and `--audio-path` is an explicit opt-in.

## Capture And Render

- Use a real passing deployed Playwright result, Apple run, or real dev CLI command.
- Browser/native capture must record an explicit ready timestamp after required UI
  is visible. Trim only to that marker minus the fixed lead; do not scan or crop
  until a product defect disappears.
- Exact profiles remain mandatory: web phone `390x844`, web laptop `1440x900`,
  iPhone portrait `393x852`, iPad landscape `1366x1024`, CLI `1280x720`.
- Captions are sentence-level and bottom-centered. Pacing may use only whole-video
  slowdown to `0.75x` and a final hold, with a 35-second output cap.
- Process one device at a time. Do not use OCR or place the full video in model
  context. Permit at most one automatic rerender for a mechanical defect.

## Review And Repair

Review only three to eight selected frames per device plus the approved contract
and deterministic metadata. Return exactly one status:

- `passed`
- `capture_defect`
- `render_defect`
- `product_defect`
- `uncertain`

Every verdict needs frame-grounded observations. Blank opening frames and caption
alignment may be corrected mechanically once. Unexplained scroll state returns to
capture. Clipping, broken headers, wrong UI state, raw implementation text, stale
loading, and broken navigation are product defects: add or strengthen a failing
test, fix the product, deploy, and recapture. Never hide them through trimming,
cropping, caption edits, or transcript edits.

After a passed frame review, publish through the existing
`sessions.py proof-video publish` path when Discord is configured. Confirm delivery
before deleting disposable video/frame files and retain sanitized transcripts,
captions, manifests, hashes, review evidence, and publication state.
