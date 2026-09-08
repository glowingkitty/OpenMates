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

## Parked for coordinator wake 2026-09-08T14:34:34.384340+00:00

User cost-control instruction: end when only waiting; preserve all jobs. Continue Astra LOW, session 08ef, same worktree. No new audio generation; no approved pilot yet.

Implemented and deployed:
- 7c4b796fe716c32857c5a53f2a76027f61fefbc2: preserve c6ec exact media clock assertion, replace removed region selector with actual waveform-region selector, attach measured playback JSON.
- 5bb0b335644ab8c095179ad4d4c980c00af61568: call proof.attach() after checkpoint; missing call prevented timeline import despite passing playback. Lint and Specification gates passed.

Playback established from validated CI attachments: initial corrected run 34233513231 currentTime=0.341824; deployed laptop 34234504912 currentTime=0.504076; deployed phone 34234565706 currentTime=0.443132. All paused=false, readyState=4, errorCode=null. No speech-generation WebSocket frames. No product player code changed.

Final pending proof jobs (both running at last reconciliation):
- laptop request c72164289ad76046af9b10b7e36df78165e6c8adaf64fb1faee428fd591ec47e; GitHub run 34238192461
- phone request f9dacbd66ba3caeec5197e5912314d30b2a0cdceeb11b73cb6d6b163e7d00096; GitHub run 34238375743
- tested commit for both: 5bb0b335644ab8c095179ad4d4c980c00af61568

Next commands in this worktree:
```bash
python3 scripts/ci_coordinator.py status c72164289ad76046af9b10b7e36df78165e6c8adaf64fb1faee428fd591ec47e
python3 scripts/ci_coordinator.py status f9dacbd66ba3caeec5197e5912314d30b2a0cdceeb11b73cb6d6b163e7d00096
# Once terminal, fetch each existing request; do not resubmit.
python3 scripts/ci_coordinator.py result c72164289ad76046af9b10b7e36df78165e6c8adaf64fb1faee428fd591ec47e
python3 scripts/ci_coordinator.py result f9dacbd66ba3caeec5197e5912314d30b2a0cdceeb11b73cb6d6b163e7d00096
python3 scripts/proof_video_workflow.py start --current --spec example-chat-speech.spec.ts --run-id 34238192461
python3 scripts/proof_video_workflow.py start --current --spec example-chat-speech.spec.ts --run-id 34238375743
```
Inspect actual media JSON, timeline, bounded frames; finish caption/render/review/publish workflow. If result download times out, prior bounded 180-second ci_results.DOWNLOAD_SECONDS override through the same Queue.result locking/validation succeeded; do not rerun tests for transport failure.

Updated Codex delivery rule applied: ran scripts/codex_evidence.py --upload for all five completed request directories d28e842..., f0bbf68..., 9866bfab..., edd1e6fe..., ecb5403a.... Explicit links for all 7 recordings and 7 images were posted in the visible commentary table after the compute-setting interruption. These are raw recording deliveries, not completed captioned proof reviews. Machine delivery receipts remain pending because actual assistant message ID was not exposed; never fabricate an ID. Resume by using actual delivered message ID if available, then codex_evidence.py --ack for only those posted records. New final runs need their own returned codex_evidence_command, links and acknowledgement.

Task connection to actual thread succeeded; all meaningful implementation and measured-playback milestone posts were acknowledged. Latest deployed-proof request activity delivery ID: 494a9728b767ea6937887b9ab1d3783b09e511c9a226d93936aadd38fccb1f5c. No uncertain activity to recreate.

Process finding checked against existing audit_playwright_proof_metadata.py: it checks runtime/contract fields but not final attach(), allowing a passing run without a timeline. Smallest future improvement is a deterministic audit/test for required finalization, not new prompt prose.

## Recording review, 15:05 UTC

Canonical receipts for GH 34238192461 and 34238375743 succeeded on 5bb0b335644ab8c095179ad4d4c980c00af61568. Concrete currentTime: laptop 0.635731, phone 0.313027; both paused=false, readyState=4, error=null. Raw media delivered visibly. Preliminary bounded review confirms playback controls but rejects the shared caption claiming both chapter labels visible on phone. Source intentionally hides adjacent labels below 730px; caption now describes actual playback control/current chapter, retaining the exact clock assertion and two-region count.

Reviewer flags phone title illustration occlusion. Approved assistant-response-speech contract explicitly pins an overlay over chat history and prioritizes current chapter on mobile; title-art treatment is not specified. No product layout changed. Escalate exact delivered frame to coordinator for ownership/design disposition; contrast remains an unclear warning, not an automatic fix.

Capture hold fix deployed at 803b0db587023725230e725147d4f8467614aef0. No test dispatched for that intermediate commit; combine corrected caption with required real 7-second recording before device captures. PII handoff request acknowledged as c83c73f184f9b437142b5f575a9f668a8006425838f2fdffe8f3518ea602b5cc; no approved candidate or audio generation.
