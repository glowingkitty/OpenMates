# Apple local model laboratory

The developer laboratory offers optional Whisper speech recognition plus the user-selected Supertonic3 neural speech experiment. Enhanced OpenAI Privacy Filter downloads belong
in **Settings → Privacy**; its diagnostics are reachable there. Installed and
enabled enhanced PII also runs in the active message composer.

## Execution and downloads

| Test | Runtime | Availability |
| --- | --- | --- |
| Whisper | Pinned WhisperKit | Supported arm64 iOS/iPadOS/macOS; Watch tiny test is separate |
| Supertonic3 | Pinned publisher Swift helper and CPU ONNX | Supported arm64 iOS/iPadOS/macOS; stock voices and explicit local files |
| Enhanced PII | Same pinned OpenAI model through ExecuTorch/XNNPACK | Supported arm64 iOS/iPadOS/macOS |

KittenTTS Mini0.8, Pocket TTS, Apple system voice testing and Kokoro are removed at the user's request. Supertonic3 remains selected for developer testing. The existing production assistant speech media pipeline remains independent of the laboratory.

Downloads use immutable publisher revisions, explicit consent, bounded transfer
progress, resume/retry, streaming SHA-256 and atomic verified installation.
Partial or corrupt assets are never offered as ready. The runtime never fetches
weights or sends inference inputs to a server. Local download activities are
independent of the user's chat push-notification preference.

## Privacy and ownership

Laboratory input, recordings and generated audio/results stay temporary and are
cleared on leaving the page; neural speech also clears on backgrounding, lab opt-out and account/server/Team/scope changes. One laboratory operation owns its
native resources until cancellation drains the current kernel and cleanup.
No rejected speech adapter is exposed and no cloud or system-voice replacement is
added. Only numeric timing, phase and memory diagnostics are retained.

Production PII warms one model for an eligible foreground composer, displays
regex results immediately and debounces enhanced detection by 500 ms. Only one
native scan and the newest pending snapshot are retained. Cold warming and
preview scans use utility priority. Final send verifies the immutable document,
settings and exclusions, waits for installed-model readiness, and rechecks
account/route/settings/foreground immediately before dispatch. Missing,
unsupported or failed models retain visible regex fallback. Cancellation,
backgrounding, opt-out, model removal and memory pressure invalidate stale work.

## Current testing selection

The user retained Supertonic3 and rejected KittenTTS Mini0.8 on 2026-10-05. Asset bytes/SHA256 and source revisions are pinned; weights are optional downloads. Model loading measures voice-style loading and ONNX session initialization. Generating speech measures the engine's text frontend and synthesis kernels. Preparing audio playback measures mono WAV encoding and writing. These timings are processing wall-clock duration; generated audio duration measures playback length. Personal-data detection retains its own separate inference stage.

A rejected post-return WAV is removed using its request destination, even when no result is published. Fixed public English/German listening and physical-device runtime/memory evaluation remain required for a production-quality claim.

The requested production playback follow-up is pending separately: use the normal web-style playback UI, prefer installed local Supertonic3, offer downloading when absent, and request ElevenLabs only after user choice or a failed local attempt. The current first-party WebSocket assistant-speech transport, encrypted generated-asset media resolution and player remain available for that explicit provider route; no REST TTS endpoint or local-to-provider fallback is added here.

## Verification limits

The exact PII engine on M1 measured 3.94 seconds to load, then 2.02–2.65 seconds
for warm synthetic scans. Historically, before its removal and the user quality
rejection, Pocket generated a real 3.12-second WAV in 2.413 seconds
including model loading. These establish Mac execution, not iPhone speed,
Neural Engine placement, subjective voice quality or physical Watch performance.
The permanent contracts are
`specifications/features/apple-local-model-lab/specification.yml` and
`specifications/features/pii-protection/specification.yml`.
