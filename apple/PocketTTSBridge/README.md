# Pocket TTS developer laboratory

This standalone CPU bridge runs actual Pocket TTS inference for the Apple developer
lab. It is not a chat speech provider. No model weights, prebuilt XCFramework,
reference voice recordings, text or audio are committed. Model downloads use the
existing optional download/verification/cancellation/Live Activity store.

## Pinned inputs and licensing

- Rust source: UnaMentis/pocket-tts-ios at
  `ce0a41d118077bfed02361406f5fac747cd8e411`, MIT (included attribution/license).
  Public source archive SHA256:
  `b497ad679aefcf9fb3063eaa1c14990b7eade140584c920bfca798c84429a5c2`.
- Model assets: Kyutai/pocket-tts-without-voice-cloning at
  `1e08e6a23401048648a9fdcfde2f89348215c2a7`, CC BY 4.0.
  January English model `tts_b6369a24.safetensors`, SentencePiece tokenizer and
  `embeddings/alba.safetensors` (236,310,159 bytes total).
- Voice: Alba MacKenna, casual voice; CC BY 4.0, per
  <https://huggingface.co/kyutai/tts-voices#alba-mackenna>.
  The model's pretrained Alba embedding is used directly. No voice cloning.
- Exact publisher URLs, per-file sizes and SHA256 are in the app's
  `Resources/LocalModels/catalog.json`. The runtime does not download assets.

The released UnaMentis XCFramework includes iOS arm64 slices. This separate
source builder compiles CPU slices for iOS arm64, iOS Simulator arm64/x86_64 and
macOS arm64/x86_64 using Rust 1.98.1, Cargo.lock and SentencePiece CMake. Intel
Mac execution is permitted by the source target; real performance is unmeasured.
The newer Kyutai multilingual Python model is not registered as supported.

## Privacy patch and ownership

`prepare.py` verifies the pinned archive before extraction, rejects links and
traversal, and applies a deterministic crate-level patch before any module:
`eprintln!`, `println!`, `eprint!`, `print!` expand to nothing. Upstream prints
text token IDs, tensor/audio values and paths; none may reach the lab's logs.
The patch does not change process-wide logging or model math. It also restricts
this dependency to an rlib; the private bridge supplies the only static library.
Post-patch `src/lib.rs` SHA256 is
`5dd1daa5bf0720c3d8d9537128e0fa61cf6db5d2d58fd67cab33837d3bf7e474`.
Post-patch file hashes are recorded in `.runtime/pocket-tts/source-receipt.json`
and reconstructed on each preparation. Source/Cargo caches and targets stay
inside this repository, separate from the Pair bridge caches. The app archive localizes only
`_rust_eh_personality` on every Apple destination, preserving the C ABI and
avoiding the existing Pair static library’s exported runtime symbol.

The Swift detached worker exclusively owns its C engine and WAV buffers. Input
is at most 600 UTF-8 bytes, four sentence chunks, 160 bytes and 64 model tokens per
chunk. Invalid input is rejected, never truncated. The synchronous upstream
kernel does not honor cancellation; cancellation remains busy until its bounded
sentence returns and the engine is destroyed. Late output is discarded. Page
exit/background clears private text, stops playback and cancels inference.
Only bounded scalar timings/memory/phase data use the existing lab metrics.

## Root-run verification

No model download or native build is required for `python3 test_prepare.py`.
Xcode runs `build-apple.sh` for the active application platform/architectures.
`CPocketTTS` is a source-only C module; the generated archive lives in
`$(DERIVED_FILE_DIR)/PocketTTS`.

For an isolated actual Mac CPU smoke (no Debug app installation/account data):

```sh
python3 apple/PocketTTSBridge/verify-assets.py .runtime/pocket-tts/smoke-model --download
POCKET_MODEL_ROOT="$PWD/.runtime/pocket-tts/smoke-model" \
POCKET_SMOKE_WAV="$PWD/.runtime/pocket-tts/smoke.wav" \
  apple/PocketTTSBridge/run-smoke.sh
```

The tool verifies the catalog assets before root invokes the smoke. The Rust
example speaks only the fixed public sentence “The quick brown fox jumps over
the lazy dog.”, saves a real mono 24 kHz PCM16 WAV and prints load/total time and
byte count. The wrapper validates mono 24 kHz PCM16, nonzero PCM, duration,
peak and RMS without logging samples. Listen to this output and record actual quality/performance; mocked
unit/UI tests establish lifecycle/policy, not synthesis quality. Use at most two
native build jobs and keep the compiled Cargo cache for incremental app builds.
