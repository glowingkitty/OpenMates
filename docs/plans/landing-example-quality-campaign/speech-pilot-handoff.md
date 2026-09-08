# Speech pilot continuation — TASK-5641

Session: `08ef`; actual Codex thread: `01a080f6-bd42-73b1-8e36-b412e39fbe2f`.
Worktree: `.openmates-agent-worktrees/agent-08ef`, distinct from c6ec and coordinator 4aa6.

## Preserved earlier work

Reviewed c6ec's uncommitted `example-chat-speech.spec.ts` diff in its worktree. It observes real HTMLMediaElement playback without substituting audio and requires the public immutable audio clock to advance beyond 0.25 seconds. Do not recreate this patch or overwrite c6ec.

Cached CI queue shows two c6ec requests for that spec, both queued without run IDs:
- `d28e8422931741e9cb4b1e20b8681a7ea75bbb86b43f1697e5ed8eccc0d75d6a` (source `cb686a2137c4a5d7337471b81aad207aa8236f49`)
- `f0bbf68d766021dd11f60f38de15b88e7f5fa3b729fe820d5e2f52ba96b6b091` (source `28ea0a529bda27dc4d95ec347b129cb97181f64f`)
No additional CI request submitted. Use canonical coordinator status/result for subsequent evidence.

## Investigation and verification

Only the existing workspace-welcome fixture currently contains `public_speech` in this checkout's example data. The campaign handoff says selected replacement examples lack manifests. No new candidate content approval was found in the supplied handoff or coordinator Plan.

Existing workspace-welcome public audio was fetched anonymously with urllib (no credentials). Both objects returned HTTP 200 and audio/mpeg; SHA-256 matched their immutable filenames. ffprobe accepted both, reporting 4.597551 and 9.795918 seconds. This proves existing publication availability and parseable audio, not browser playback or candidate approval.

`node --test scripts/tests/create_example_chat_from_share.test.mjs`: 15/15 passed, including reviewed manifest requirements, immutable URL validation, and private-data stripping. Subject checkout: `a9efbf0ee9878dee77efcfdf1ff05f63f4834978`.

## Continuation once candidate is approved

1. Obtain candidate source chat ID, approved assistant message IDs, fixture path, and content approval evidence from coordinator/example owner. Do not select the welcome fixture merely because it already has speech.
2. Use source CLI `chats speak <chat-id> --message <approved-message-id> --json` for the single approved example only. Backend voice profiles already resolve ElevenLabs. Verify generation success before publication.
3. Under coordinator runtime lease, use existing trusted-runtime `scripts/publish_example_speech.py --chat-id <id> --message-id <id> --output <manifest-path> --reviewed`. It decrypts in memory and publishes content-addressed public MP3s. Never print private asset records or keys.
4. Coordinate exact candidate-file lease with its owner; attach through existing `--public-speech-manifest` converter support. Preserve other worker data and catalog ownership.
5. Verify anonymous objects/hashes, then adapt/reuse c6ec playback assertion for approved candidate and obtain phone/laptop browser proof through canonical test/proof tooling. Do not claim guest playback from HTTP checks.
6. Present one pilot for user confirmation before any remaining example audio generation.

## Attribution and dependency

Task history and thread-connect calls returned HTTP 429. No connection acknowledged. Coordinator instructed all workers to stop Tasks API reads/connect/posts for at least ten minutes and will serialize recovery. This local milestone is pending acknowledged posting to TASK-5641 and coordinator TASK-5745; do not auto-retry. Supplied local handoff establishes prior work during recovery.

No new audio generated, no runtime mutations, no account memory changes, no product code edits. Pilot remains dependent on a content-approved candidate; browser evidence remains queued.

Recorded UTC: 2026-09-08T12:27:24.493205+00:00

## CI monitoring checkpoint 2026-09-08T12:41:17.759572+00:00

Coordinator confirms no content-approved candidate yet. No audio generation or repeated asset checks. Earlier request d28e842 is running as GitHub run 34227149605; later request f0bbf68 remains queued. Exact git snapshot inspection confirms source cb686a2 does NOT contain the clock assertion, while source 28ea0a5 contains both `media.currentTime > 0.25` and `return originalPlay.call(this)`. Only the latter request can prove strengthened playback. c6ec working diff remains intact.

## Terminal CI verification 2026-09-08T13:10:10.128383+00:00

Both existing requests reached terminal failure; no replacement test submitted.

- Baseline `d28e8422931741e9cb4b1e20b8681a7ea75bbb86b43f1697e5ed8eccc0d75d6a`: run `34227149605`, source `cb686a2137c4a5d7337471b81aad207aa8236f49`, harness `7bf8f5aa3b5ff48436cab02167b98648db1eb66e`. Canonical result receipt validated. Detailed `test-results/ci-spec-0.json` shows both attempts fail at spec line 75: obsolete `assistant-speech-region` count expected 2, got 0. Read-only E2E investigator inspected both screenshots: visible speech player, Pause, Part 1, next Part 2. Exact source renders current/next chapter and waveform region IDs instead. This is a stale test selector, not proof of broken audio. Test stopped before response assertions and this baseline source has no clock check.
- Strengthened `f0bbf68d766021dd11f60f38de15b88e7f5fa3b729fe820d5e2f52ba96b6b091`: run `34228225842`, source `28ea0a529bda27dc4d95ec347b129cb97181f64f`, terminal failure. `python3 scripts/ci_coordinator.py result <request-id>` failed twice at the existing 60-second bounded artifact-download timeout. Actual failure assertion and media currentTime evidence remain unavailable; do not infer its exact failure from the baseline. Source has unchanged `media.currentTime > 0.25` assertion but the same earlier obsolete count check.

Next actionable verification repair: update obsolete region-count checks to the component's existing current/next chapter assertions while preserving c6ec's exact real-play observer and media-clock check; coordinate ownership before a new run. Retrieve strengthened artifacts through canonical coordinator when available. No product player changes justified by baseline evidence. Candidate must still be explicitly content-approved before the one narration generation.

Artifact discovery correction: `rg --files` omitted ignored nested test-results; `rg --files --hidden --no-ignore <exact-artifact-directory>` revealed existing reports/screenshots without another download. Existing E2E investigator instructions require direct report/screenshot discovery; avoid claiming missing artifacts from ignore-aware searches. No source/test/asset reruns or audio generation performed in this continuation.
