# Voice-mode migration verification

Task: TASK-6487. Session: cabb. Scope: the accepted shared-pipeline call replacement and removal of Gemini Live calling.

Status: implementation complete; final browser and dev deployment verification pending.

| Accepted behavior | Implementation and coverage | Evidence / remaining risk |
| --- | --- | --- |
| Voxtral speech; ordinary automatic pre/main/post routing | STT-only call transport, canonical encrypted message sender, normal router and skill executor | [Backend CI](https://github.com/glowingkitty/OpenMates/actions/runs/39834639334); [current startup/provider CI](https://github.com/glowingkitty/OpenMates/actions/runs/39841025802) |
| Rich answers and one ordered prose player | Canonical response projection, immutable voice clauses, owner-scoped asset replay | Backend projection/replay/lifecycle coverage; full browser verification pending |
| Listener cues preserved; intentional interruption cancels current work | Exact stop/backchannel rules, bounded Jev intent, call/turn/task fences | [Intent/protocol CI](https://github.com/glowingkitty/OpenMates/actions/runs/39836113082); browser verification pending |
| Next turn knows what was actually heard | Completed clauses and actual playback offset, shared preprocessing/main context; rich history retained | [Heard-boundary and continuation CI](https://github.com/glowingkitty/OpenMates/actions/runs/39839939189); actual browser playback case pending |
| Localized, nonblocking waiting speech | Delayed current-Mate clause in the request language; no English fallback | Backend waiting coverage; German browser case pending |
| Consent, ownership and billing | Separate v2 consent, call/session/turn checks, real microphone duration, normal LLM/TTS settlement | [Privacy component CI](https://github.com/glowingkitty/OpenMates/actions/runs/39834536466); [owner routing CI](https://github.com/glowingkitty/OpenMates/actions/runs/39837624433) |
| Existing composer, header and media controls | Shared UI controls and normal source attachment path | [Composer CI](https://github.com/glowingkitty/OpenMates/actions/runs/39841031723), [media CI](https://github.com/glowingkitty/OpenMates/actions/runs/39841040379), [header CI](https://github.com/glowingkitty/OpenMates/actions/runs/39837253691). Composer desktop preview mounted on retry after a cold-preview timeout. |
| Remove old Gemini calling | Provider, broker/task, custom tools/receipts, metadata scheduler and standalone experiment removed | Legacy-retirement tests in backend CI; final read-only review found no callable legacy runtime |
| Apple source compatibility | Updated app/Watch protocol, canonical send, shared playback and heard boundary; focused tests updated | Changed Swift files pass scoped SwiftLint. Compilation/tests unavailable because the configured Mac is unreachable; no TestFlight publication. |
| Real provider compatibility | Vault-authenticated Voxtral 3 STT/TTS probe, including two final turns on one connection | Local provider probe passed; repeat against deployed source after restart |

The first browser candidates exposed a context-free-start admission defect before turn execution. Both admission sites now accept omitted context and still reject malformed supplied context; protocol fixtures use the actual client wire shape. The final browser candidate is `c7c1aaae4413ea46ca73fa6142a98316556435fa` ([run](https://github.com/glowingkitty/OpenMates/actions/runs/39841046499)).

Contract references: `feature.video-call@11`, `feature.assistant-response-speech@8`, `feature.message-input@8`, and superseded `feature.video-call-experiment@1`. The user's explicit implementation/deployment instruction is recorded as the scoped prompt waiver. Plan/schema verification passes; this does not replace the pending browser and deployment gates.
