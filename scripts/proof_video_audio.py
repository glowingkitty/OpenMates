#!/usr/bin/env python3
# contract-test-file: tooling
"""Put the browser's audio into Playwright proof videos, in sync (owner, 22 Nov 2026).

Playwright records video without sound. Voice and audio specs therefore record the page's
audio inside the browser (frontend/apps/web_app/tests/helpers/proof-audio.ts): every Web Audio
output, every playing <audio>/<video> element and the fake microphone (a test voice), as
WebM/Opus segments with the wall-clock time each segment started. The helper writes a
manifest next to the segments and a copy of each page's video:

  {"schema_version": 1, "pages": [{"video": "video-0.webm", "created_epoch_ms": 1.0,
    "segments": [{"file": "audio-0-ab12.webm", "start_epoch_ms": 2.0}]}]}

``mux`` delays each segment by (segment start - page creation) — the Playwright video starts
when its page is created — mixes them, pads the mix to the video's length and writes
``<video>-with-audio.webm`` (video stream copied, audio Opus). ``mux-all`` does that for every
manifest below a folder whose output is missing or older, which the real-stack runners and
scripts/ci_evidence.py call when a run could not mux by itself. ``loudness`` prints the
maximum volume (dB) of a file's audio, so tests can prove the sound is really there.

Usage: proof_video_audio.py mux <manifest.json>
       proof_video_audio.py mux-all <folder>
       proof_video_audio.py loudness <media file> [--start S] [--duration S]
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

MANIFEST_NAME = "proof-audio-manifest.json"
SUFFIX = "-with-audio.webm"
FFMPEG_TIMEOUT = 600
_MAX_VOLUME = re.compile(r"max_volume:\s*(-?[\d.]+|-inf) dB")


class MuxError(RuntimeError):
    """ffmpeg is missing, a manifest is malformed or ffmpeg failed."""


def ffmpeg() -> str:
    path = shutil.which("ffmpeg")
    if not path:
        raise MuxError("ffmpeg is not installed")
    return path


def mux_command(video: Path, segments: list[tuple[Path, float]], output: Path) -> list[str]:
    """ffmpeg arguments that lay each (segment, offset seconds) onto the video's timeline."""
    command = [ffmpeg(), "-y", "-loglevel", "error", "-i", str(video)]
    filters, labels = [], []
    for index, (path, offset) in enumerate(segments, start=1):
        command += ["-i", str(path)]
        if offset >= 0:
            shift = f"adelay={round(offset * 1000)}:all=1"
        else:  # started before the page (clock skew): drop the part before the video
            shift = f"atrim=start={-offset:.3f},asetpts=PTS-STARTPTS"
        filters.append(f"[{index}:a]aresample=48000,{shift}[a{index}]")
        labels.append(f"[a{index}]")
    if len(labels) > 1:
        filters.append(f"{''.join(labels)}amix=inputs={len(labels)}:normalize=0:duration=longest[mix]")
    else:
        filters.append(f"{labels[0]}anull[mix]")
    filters.append("[mix]apad[aout]")
    return command + ["-filter_complex", ";".join(filters), "-map", "0:v", "-map", "[aout]",
                      "-c:v", "copy", "-c:a", "libopus", "-b:a", "96k", "-shortest", str(output)]


def mux(manifest_path: Path) -> list[Path]:
    """Mux every page of one manifest; returns the written videos (pages without audio are skipped)."""
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        pages = manifest["pages"]
    except (OSError, ValueError, KeyError, TypeError) as error:
        raise MuxError(f"{manifest_path}: unreadable proof-audio manifest ({error})") from error
    base, written = manifest_path.parent, []
    for page in pages:
        video = base / page["video"]
        segments = [(base / s["file"], (float(s["start_epoch_ms"]) - float(page["created_epoch_ms"])) / 1000)
                    for s in page.get("segments") or [] if (base / s["file"]).is_file()]
        if not video.is_file() or not segments:
            continue
        output = video.with_name(video.stem + SUFFIX)
        try:
            done = subprocess.run(mux_command(video, segments, output), capture_output=True, text=True,
                                  timeout=FFMPEG_TIMEOUT)
        except (OSError, subprocess.SubprocessError) as error:
            raise MuxError(f"{video.name}: ffmpeg did not finish ({error})") from error
        if done.returncode != 0 or not output.is_file():
            raise MuxError(f"{video.name}: ffmpeg failed: {done.stderr.strip()[-400:]}")
        written.append(output)
    return written


def mux_all(folder: Path) -> list[Path]:
    """Mux every manifest below ``folder`` whose videos are not muxed yet (or older than the manifest)."""
    written: list[Path] = []
    for manifest in sorted(folder.rglob(MANIFEST_NAME)):
        try:
            pages = json.loads(manifest.read_text(encoding="utf-8")).get("pages") or []
        except (OSError, ValueError) as error:
            raise MuxError(f"{manifest}: unreadable proof-audio manifest ({error})") from error
        outputs = [manifest.parent / (Path(p.get("video", "")).stem + SUFFIX) for p in pages]
        if outputs and all(o.is_file() and o.stat().st_mtime >= manifest.stat().st_mtime for o in outputs):
            continue
        written += mux(manifest)
    return written


def loudness(path: Path, start: float = 0.0, duration: float | None = None) -> float:
    """Maximum volume in dB of the file's audio (or of a window of it); -inf for silence."""
    window = ["-ss", f"{start:.3f}"] + (["-t", f"{duration:.3f}"] if duration else [])
    done = subprocess.run([ffmpeg(), "-hide_banner", "-nostats", *window, "-i", str(path), "-map", "0:a:0",
                           "-af", "volumedetect", "-f", "null", "-"], capture_output=True, text=True,
                          timeout=FFMPEG_TIMEOUT)
    match = _MAX_VOLUME.search(done.stderr)
    if done.returncode != 0 or not match:
        raise MuxError(f"{path.name}: no audio stream ({done.stderr.strip()[-200:]})")
    return float("-inf") if match.group(1) == "-inf" else float(match.group(1))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("mux").add_argument("manifest", type=Path)
    sub.add_parser("mux-all").add_argument("folder", type=Path)
    loud = sub.add_parser("loudness")
    loud.add_argument("media", type=Path)
    loud.add_argument("--start", type=float, default=0.0)
    loud.add_argument("--duration", type=float)
    args = parser.parse_args(argv)
    try:
        if args.command == "loudness":
            print(loudness(args.media, args.start, args.duration))
            return 0
        written = mux(args.manifest) if args.command == "mux" else mux_all(args.folder)
    except MuxError as error:
        print(f"proof_video_audio: {error}", file=sys.stderr)
        return 1
    print("\n".join(str(p) for p in written))
    return 0


if __name__ == "__main__":
    sys.exit(main())
