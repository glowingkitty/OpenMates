---
name: create-demo-video
description: Create narrated review videos of OpenMates CLI interactions or deployed Playwright feature flows and publish passed examples to Discord dev-smoke. Use when asked for a CLI video, feature demo, proof video, narrated spec recording, or Discord example video.
user-invocable: true
argument-hint: "<CLI command | Playwright spec.ts> [feature or claim to demonstrate]"
---

# Create Demo Video

Use this skill for engineering demonstrations made from real CLI or deployed
Playwright evidence. Do not use the marketing `create-video` workflow or public
temporary uploads.

## Contract

- Start or reuse a `sessions.py` session before producing artifacts.
- Use a real dev CLI command or a passing deployed Playwright test result.
- Generate ElevenLabs `eleven_flash_v2_5` narration audio before rendering and pass it with `--audio-path`; every final proof video must have that audio track and burned-in captions.
- Reuse the same narration transcript and audio across viewport recordings unless the narration must change.
- Keep web/spec/example-chat proof as separate phone and laptop videos, Apple proof as separate iPhone portrait and iPad landscape videos, and CLI proof as one terminal video.
- Use the exact proof-video device profile for each surface. Do not put phone or iPad recordings inside a 16:9 or 16:10 wrapper: phone web is `390x844`, laptop web is `1440x900`, iPhone portrait is `393x852`, iPad landscape is `1366x1024`, and CLI terminal is `1280x720`.
- Reject videos with black bars, letterboxing, pillarboxing, or visible generic landscape canvases around a device recording. Re-record with the correct Playwright `recordVideo.size` or Apple simulator capture instead of cropping around the wrapper.
- Never narrate a failed, skipped, timed-out, mocked, or fixture-only result as a successful feature.
- Use controlled dev/test accounts and do not intentionally capture production data, secrets, unrelated chats, or personal account content.
- The canonical scanner checks commands, transcripts, captions, metadata, filenames, and publication text. Frame OCR is intentionally not part of this workflow.
- Keep the full video out of model context. Review the bounded frame bundle only.
- Publish only after every claim receives a supported frame-review verdict with a frame-grounded observation.
- Confirm Discord delivery before deleting generated video and frame files. Retain sanitized transcripts, captions, manifests, review evidence, and publication status.

## Narration

Write three to five realistic tutorial-style sentences that:

1. Explain the feature and why the viewer would use it.
2. Describe the action currently shown.
3. Name the visible result that proves success.
4. Mention an important follow-up or reversible action when visible.

Narration must help the reviewer detect mismatches. Name concrete visible UI,
terminal output, controls, playback state, messages, or reversible actions. Do
not use generic captions such as "the feature works", "the demo is successful",
or claims not visible in the recording.

Generate the narration audio with the cheap/fast ElevenLabs model used by the
audio app (`eleven_flash_v2_5`, default voice `warm_neutral`) and retain the
audio file so the same file can be reused for each viewport-specific render.

## CLI Source

Run the current CLI against `https://api.dev.openmates.org`. Put configuration
such as `OPENMATES_API_URL` in the environment when it does not need to appear in
the tutorial command. Produce the video with:

```bash
python3 scripts/sessions.py proof-video produce \
  --session <session> \
  --run-dir test-results/proof-videos/<session>/<slug> \
  --proof-id <proof-id> \
  --subject-commit <commit> \
  --run-id <run-id> \
  --target-environment https://api.dev.openmates.org \
  --audio-path <elevenlabs-narration.mp3> \
  --audio-model eleven_flash_v2_5 \
  --caption "<tutorial narration>" \
  --expected-proof "<visible success contract>" \
  --acceptance-criterion <AC-ID> \
  -- openmates <command...>
```

CLI videos use readable 1280x720 terminal composition, visible command typing,
captured PTY response delays, sentence-level captions, and command/output only in
the visible terminal. Exit status and provenance remain in evidence metadata.

## Playwright Source

1. Resolve the exact deployed subject commit and run:

```bash
python3 scripts/tests.py run --spec <name>.spec.ts \
  --gate-deploy --expected-commit <commit>
```

2. Use the video attached to one passing test result. An overall workflow may
   contain other failures, but the selected source record itself must be passed.
3. Record the exact spec, test run/case ID, deployed target, deployment reference,
   subject commit, artifact path, and controlled-account provenance.
4. Produce the narrated copy:

```bash
python3 scripts/sessions.py proof-video produce-playwright \
  --session <session> \
  --run-dir test-results/proof-videos/<session>/<slug> \
  --source-video <passing-video.webm> \
  --proof-id <proof-id> \
  --subject-commit <deployed-commit> \
  --run-id <test-case-run-id> \
  --spec-name <name>.spec.ts \
  --source-status passed \
  --target-environment https://app.dev.openmates.org \
  --deployment-reference <deployment-id> \
  --test-account-provenance "<controlled account description>" \
  --audio-path <elevenlabs-narration.mp3> \
  --audio-model eleven_flash_v2_5 \
  --device-profile <web-phone|web-laptop|apple-iphone-portrait|apple-ipad-landscape> \
  --caption "<tutorial narration>" \
  --expected-proof "<visible success contract>" \
  --acceptance-criterion <AC-ID>
```

For audio or video playback proofs, add `--demo-audio-path <product-audio-file>`
so the product audio is mixed quietly underneath narration. For fast flows, use
`--playback-rate 0.75` or `--hold-last-frame-seconds 2` instead of editing claims
around unreadable timing. The renderer preserves the source aspect ratio and
fails if the source/output dimensions do not exactly match the device profile.

## Review And Publish

Read `review-request.json`, inspect every referenced frame, and compare each
caption and expected claim with the visible state and timing. Record one verdict
per claim:

```bash
python3 scripts/sessions.py proof-video review \
  --session <session> \
  --run-dir <run-dir> \
  --claims-json '[{"claim_id":"CLAIM-1","verdict":"supported","observation":"<frame-grounded observation>"}]'
```

Fix composition, timing, narration, audio, recording, or implementation defects and
repeat review when needed. Obvious product/rendering defects in reviewed frames
must auto-trigger product work rather than an accepted difference: add or
strengthen a failing test, fix the code or web app, deploy, rerun the real source
proof, and create a replacement video. This includes clipping, premature text
truncation, wrong icons/gradients/metadata, raw protocol or implementation text,
missing active-processing animation, stale loading/error states, and broken
navigation. Never approve or publish a video that merely hides, documents, or
narrates around such a defect. After a passed review:

```bash
python3 scripts/sessions.py proof-video publish \
  --session <session> \
  --run-dir <run-dir>
```

When `DISCORD_WEBHOOK_DEV_SMOKE` is configured, confirmed Discord delivery is a
hard completion gate. Report the source run, subject commit, duration, audio
model, review result, Discord delivery status, retained evidence path, tests, and
any accepted differences.
