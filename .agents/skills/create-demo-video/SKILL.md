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
- Never narrate a failed, skipped, timed-out, mocked, or fixture-only result as a successful feature.
- Use controlled dev/test accounts and do not intentionally capture production data, secrets, unrelated chats, or personal account content.
- The canonical scanner checks commands, transcripts, captions, metadata, filenames, and publication text. Frame OCR is intentionally not part of this workflow.
- Keep the full video out of model context. Review the bounded frame bundle only.
- Publish only after every claim receives a supported frame-review verdict.
- Confirm Discord delivery before deleting generated video and frame files. Retain sanitized transcripts, captions, manifests, review evidence, and publication status.

## Narration

Write three to five tutorial-style sentences that:

1. Explain the feature and why the viewer would use it.
2. Describe the action currently shown.
3. Name the visible result that proves success.
4. Mention an important follow-up or reversible action when visible.

Narration must help the reviewer detect mismatches. Do not use generic captions
such as "the feature works" or claims not visible in the recording.

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
  --caption "<tutorial narration>" \
  --expected-proof "<visible success contract>" \
  --acceptance-criterion <AC-ID>
```

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

Fix composition, timing, narration, recording, or implementation defects and
repeat review when needed. After a passed review:

```bash
python3 scripts/sessions.py proof-video publish \
  --session <session> \
  --run-dir <run-dir>
```

Report the source run, subject commit, duration, review result, Discord delivery
status, retained evidence path, tests, and any accepted differences.
