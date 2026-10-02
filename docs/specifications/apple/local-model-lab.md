# Apple local model laboratory

This engineering design records the directly approved experimental scope and accompanies
`specifications/features/apple-local-model-lab/` (draft pending fingerprint review
and approval). It does not promise production model routing or quality parity. Open **Settings → Developers → Local models lab**
on iPhone, iPad or Mac. Each model is optional and its weights are absent from the
application bundle. Enable the laboratory switch to run a downloaded model.

## Assets and app size

| Model | Selected assets | Exact download bytes |
|---|---|---:|
| Transcription | WhisperKit compressed Whisper large-v3 turbo (four decoder layers) plus local tokenizer | 629,481,698 |
| English speech | Kokoro seven-stage Core ML, af_heart voice, local lexicon and BART G2P | 94,821,034 |
| PII | OpenAI Privacy Filter CPU ExecuTorch export, tokenizer and calibrated decoder config | 1,269,572,251 |

The complete optional set occupies about 1.99 GB (decimal) before filesystem and
runtime cache overhead. Downloads use immutable Hugging Face commit URLs and
per-file SHA-256 digests, with atomic promotion only after verification. The
largest temporary download also needs space: installation checks reserve the
asset total, largest individual file and 150 MB of headroom. Assets are excluded
from device backups. Cancel discards partial files; interrupted downloads restart
when requested. Reopening the lab verifies cached files without network access.

Runtime libraries still increase the app binary. The selected ExecuTorch CPU
static-library inputs are about 12.8 MB per iOS arm64 slice before stripping;
WhisperKit and FluidAudio Swift code and the native tokenizer add further space.
The unnecessary NeMo trait is disabled with Swift 6.2 or later. FluidAudio carries
about 1 MB of unrelated upstream pronunciation resources. Measure the final
stripped Release/TestFlight archive and App Store thinning report before stating
an installed-app delta; package archive download sizes are not app sizes.

Only the main iOS/macOS app links the model runtimes. ExecuTorch's pinned SDK
archives lack x86_64 slices and its SwiftPM product conflicts with TokenizersRust's
flattened module-map output. All three supported arm64 platforms therefore use
`apple/LocalModelBridge` to stage the exact six pinned libraries, original Clang
headers/module map and Swift overlay in separate derived platform directories.
Only arm64 SDK settings expose those search paths and force-load registrations.
The Mac executable remains universal and Intel visibly unsupported without
linking these arm64 libraries into its x86_64 slice. Archive checksums, generated
output isolation and build source provenance remain enforced. The packaging's
native compilation and deployed inference verification are pending. Watch and share extensions
do not carry these dependencies or assets. The app's iOS 17/macOS 14 minimums
remain; package resolution requires a Swift 6.2-or-newer toolchain for trait opt-out.
The current adapter runs on arm64 Apple devices; Intel is visibly unsupported before installation; download and run controls are disabled. Kokoro also shows its OS restriction before installation and cannot download or run on OS 27 or later.

## Processing boundaries

Whisper uses its explicitly loaded local tokenizer and local Core ML models.
Kokoro bypasses the library's global English download cache using a local lexicon
and BART G2P frontend, then passes IPA to the real synthesis engine. This initial
frontend supports simple English text; spell out prices, times and decimal
numbers. It rejects unsupported text instead of silently dropping characters.
Its pronunciation/normalization must be evaluated separately from Kokoro's model
quality. The pinned FluidAudio release documents uncatchable native failures on
OS 27, so this adapter refuses that OS until the upstream issue is resolved.

Privacy Filter uses the native Rust tokenizer and CPU ExecuTorch export. The
export accepts 256 tokens, so centered overlapping windows assemble emissions
before one global constrained, calibrated BIOES/Viterbi decode. UTF-8 byte-fragment
boundaries map outward to UTF-16 spans for native highlighting. These spans are
lab results and do not change production redaction.

Only one test runs at a time. Cancellation is cooperative between inference
steps; a running native kernel may need to finish before resources unload. Page
exit clears entered text, results and private temporary recordings after the
active job has finished. Local tests do not call backend inference or credit
endpoints. The laboratory switch affects only these tests; it is not yet a
production server/local routing preference.

## Evidence and release gate

Authored automated fixtures cover download success, corruption, cancellation, restoration,
removal, PII grammar/Unicode/window boundaries and controller privacy/lifecycle.
Authored native UI tests cover the settings route, three optional model controls and switch
scope without downloading weights or consuming inference credits.

Swift syntax and catalog checks support review. They do not replace a native
compile, simulator run or physical-device inference. At implementation time the
Mac wrapper returned `MAC_NO_DELETE_STOP` (exit 77), so native build and tests are
blocked. Controller fixtures added during integration cover one active run, cancellation through unloading, private-file cleanup on page exit, and suppression of late results; these fixtures also require native execution. No measured quality, latency, battery or device-memory claim is made.

Before production routing, use the same labelled recordings with local raw ASR,
web raw Voxtral and the web's final corrected transcript as separate outputs.
Measure English/German word and character error rates, names/addresses/numbers,
silence hallucinations, noise and long recordings, then warm/cold latency, real-time
factor, peak memory, cancellation and sustained thermal behavior on iPhone 13 Pro
and the current base iPad. Review English Kokoro pronunciation and listening quality,
and labelled PII entity recall/precision including window seams and Unicode.

## Upstream and attribution

- [WhisperKit source](https://github.com/argmaxinc/argmax-oss-swift/tree/v1.1.0) (MIT)
- [Whisper Core ML assets](https://huggingface.co/argmaxinc/whisperkit-coreml) and [OpenAI Whisper](https://github.com/openai/whisper)
- [FluidAudio](https://github.com/FluidInference/FluidAudio/tree/v0.17.5) and [Kokoro](https://huggingface.co/hexgrad/Kokoro-82M) (Apache-2.0)
- [OpenAI Privacy Filter](https://huggingface.co/openai/privacy-filter) (Apache-2.0)
- [CPU export](https://huggingface.co/software-mansion/react-native-executorch-privacy-filter)
- [ExecuTorch](https://github.com/pytorch/executorch/tree/swiftpm-1.5.0) (BSD-style)
- [Native tokenizer](https://github.com/DePasqualeOrg/swift-tokenizers/tree/0.5.0) (Apache-2.0 and transitive Rust notices)

Preserve upstream notices in release dependency acknowledgements and model
attributions. The pinned catalog includes upstream license/attribution metadata;
weights are distributed from their original immutable upstream locations.
