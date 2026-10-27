# Voice pause completion verification

The broader rendering run `a33147b7cdbb2f14374f8761049ea7fa2025349370b3f3e021f693879bbabd0a` on source `8e9e0ebb337ae561651df35350582c04494944a6` passed the new speech-cue rendering coverage, with four expected cases and two unexpected existing cases overall. Retain this run as a broader suite failure; moving focused coverage does not change its result.

Source and history inspection attributes both existing failures to earlier code-preview UI changes. The failing `parsedCode` and `multilineUserCode` fixtures retain the user role, which bypasses the new assistant-only speech-cue transform. The code-preview components were unchanged by this task. Existing `UnifiedEmbedPreview` content-result rendering selects `BasicInfosBar` with `presentation="content"`, which emits `embed-result-identity` rather than the test's old `embed-basic-infos-bar` selector; the content-result shell was introduced by `44961e5c245` on October 23. Existing chat-result previews expose a group with Details/More buttons rather than a button named “Code snippet 6 lines, Svelte”; this behavior predates this task (`7520c7113f4`, October 22; context expansion `579321c6b0f`, October 23). The CI accessibility snapshot confirms that group and its buttons.

This is source/history and captured-CI evidence, not a separate baseline CI rerun. No unrelated code-preview UI or existing assertions were repaired or weakened. The original `read-only-message-parsed-doc.spec.ts` was restored byte-for-byte to task HEAD, and its exact appended speech-cue test moved to `components/voice-call-speech-rendering.spec.ts`. The focused target is classified in the existing `browser_component_contract` E2E group. It retains source-link rendering, hidden complete/pending cues, and literal inline-code checks.

Latest local verification for this move: focused ESLint and `git diff --check` passed. A byte comparison confirmed the original suite exactly matches task HEAD; a text comparison confirmed the moved test body is unchanged. CI execution and publication remain with the parent session.

## Earlier full voice-call run

Source `8e9e0ebb337ae561651df35350582c04494944a6`, GitHub run
`40380684664`, request
`3931b8c841929930c5c711a4a2dfe06f9df4649eeeb4237070dc9a647682d227`:
11 expected passes, two hard failures, one flaky case that passed on retry.

Both hard failures exhausted existing five-second `playing=false` assertions:
the pre-ready capture-order case and the muted replay at the end of the
silence/idle/resume case. Their default fixture playback had changed to the
entire 5.140-second WAV. The scoped correction uses its voiced 0.75–2.75-second
excerpt; the incomplete-pause excerpt stays at 0.75–1.10 seconds. The two-second
excerpt contains 64,000 voiced PCM bytes after 16 kHz resampling with transport
blocks, exceeding the 32,000-byte fixture continuation threshold. Existing waits
and assertions are retained. Subsequent full runs proved both corrected capture
cases; the separate manual-playback result below remains unresolved.

The German waiting-confirmation case failed on its first attempt and passed on
retry. Its captured trace shows bootstrap registration and acknowledgement
before call readiness, one finalized typed transcript, then
`chat_turn_preflight` at approximately 15,481 ms rejected with
`existing_chat_metadata_forbidden` at approximately 15,729 ms. No canonical
message was dispatched and no assistant speech status arrived; the call stopped.
This was an admission failure before speech generation, distinct from the two
fixture-duration failures. Its underlying cause and baseline status are not
confirmed; no shared-admission repair is included.

## Subsequent full voice-call runs

Sources `56ec12bc5069562248493a843f0e8c8f97e68009` (run `40385312129`)
and `68bb8157c68f3dd4cbd9ac989089a0925c76a818` (run `40390819506`) each
finished with 13 expected passes, one unexpected failure, and no flaky cases.
The incomplete-pause/resume admission and initial header readiness checks pass,
as do both capture cases above and the German case on its first attempt.

The remaining failure is manual Speak after hangup. The second run captures the
static `assistant_message_required` rejection before speech generation; the
outbound chat and assistant identities match the completed canonical turn.
Ownership succeeds, but the required saved assistant message is not visible at
that request. Correlated version conflicts are present. The older observation
did not capture modern sealed-recovery persistence acknowledgements, so absence
of a legacy storage acknowledgement does not establish abandoned persistence.

The manual lifecycle case passed in the two earlier runs with the longer
microphone fixture. This is consistent with a persistence timing race, but its
exact stopping condition requires the correlated recovery operation and window
refresh diagnostics added for source `056d63b7577ee577dbe52a48049752ab10157cd4`.
Assertions and timeouts remain unchanged. No persistence repair or authorization
relaxation is inferred from these observations.

Focused isolated component runs passed all four header cases (run `40379857203`)
and the speech-cue rendering case (run `40381659106`). The final read-only review
found no further completion admission, resume cancellation or silence-prompt
gaps. Physical MacBook/external-speaker echo remains unconfirmed; synthetic
text classification and provider-stream probes do not reproduce that acoustic
environment.

## Final isolated verification

Source `056d63b7577ee577dbe52a48049752ab10157cd4`, run `40395411917`,
request `7f043e45fd7cd8f538d1a9d9fad9ec68f4217a88b25c9fa8c92e6b00400c946f`:
14 expected passes, zero unexpected, flaky or skipped cases. Every case passed
on its first attempt, including native incomplete-pause/resume, canonical rich
chat retention, header readiness, capture startup, silence/resume, localized
waiting confirmation and manual speech generation/replay/deletion after hangup.

No product persistence change preceded this pass. The existing failure-only
transport attachment does not provide a successful save/request timeline, so
the passing lifecycle establishes current behavior without proving the cause
of the earlier intermittent save/playback failure. Preserve that uncertainty;
do not claim a persistence repair or a confirmed acoustic echo fix.

Post-run source cleanup changes only documentation and the fixture unit test's
lambda to a named function for Ruff. Its seven focused tests and Ruff check
pass. Production behavior remains identical to the fully passing source.
