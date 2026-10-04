#!/usr/bin/env bash
# Root-only actual native smoke; model directory must contain verified catalog assets.
set -euo pipefail
bridge_dir="$(cd "$(dirname "$0")" && pwd)"
repo_dir="$(cd "$bridge_dir/../.." && pwd)"
: "${POCKET_MODEL_ROOT:?verified January assets required}"
: "${POCKET_SMOKE_WAV:?isolated output path required}"
python3 "$bridge_dir/verify-assets.py" "$POCKET_MODEL_ROOT"
python3 "$bridge_dir/prepare.py"
export CARGO_HOME="$repo_dir/.tmp/apple-pocket-cargo"
export RUSTUP_HOME="$repo_dir/.tmp/apple-pocket-rustup"
export CARGO_BUILD_JOBS=2
export CMAKE_BUILD_PARALLEL_LEVEL=2
export CARGO_TARGET_DIR="$repo_dir/.runtime/pocket-tts/target"
unset CMAKE_TOOLCHAIN_FILE POCKET_APPLE_ARCH CMAKE_GENERATOR CMAKE_OSX_ARCHITECTURES || true
rustup toolchain install 1.98.1 --profile minimal --no-self-update >/dev/null
cargo +1.98.1 run --manifest-path "$bridge_dir/Cargo.toml" --locked --jobs 2 --release --example lab_smoke --quiet

python3 - <<'PYTHON'
import array, math, os, wave
with wave.open(os.environ["POCKET_SMOKE_WAV"], "rb") as wav:
    assert wav.getnchannels() == 1 and wav.getframerate() == 24000 and wav.getsampwidth() == 2
    count = wav.getnframes()
    samples = array.array("h", wav.readframes(count))
assert count > 0 and samples
peak = max(abs(sample) for sample in samples) / 32768
rms = math.sqrt(sum((sample / 32768) ** 2 for sample in samples) / len(samples))
assert peak > 0 and rms > 0, "Actual synthesis produced silent PCM"
print(f"audio_seconds={count / 24000:.3f} pcm_peak={peak:.6f} pcm_rms={rms:.6f}")
PYTHON
