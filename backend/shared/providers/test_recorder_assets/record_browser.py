"""Sandbox-side browser test recorder (stdlib only, runs inside the test sandbox).

Usage: record_browser.py [--preview-step NAME] [--workspace-root DIR] -- <test command...>

Runs the user's `playwright test` command with a config overlay that forces
video, failure traces and screenshots plus a custom reporter, then writes into
$OPENMATES_TEST_RUN_DIR: report.json, video.webm, trace.zip (optional) and
preview.png. Evidence over the contract caps is re-encoded or dropped and the
reason is recorded in report.json `notes` and printed; the run never fails for
oversized evidence. The exit code is the test command's exit code.

Preview marker convention: a `test.step` whose title starts with `[preview]`
(prefix stripped from the step name) or equals the requested `preview_step`
input (the input wins). Otherwise the last non-blank frame before the final
`expect` step. Blank = gray-level standard deviation below BLANK_STDDEV.
"""
from __future__ import annotations

import glob
import json
import math
import os
import re
import shlex
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Callable, Optional

MARKER_PREFIX = "[preview]"
BLANK_STDDEV = 2.0  # gray levels (0..255); a uniform page has stddev ~0
SAMPLE_W, SAMPLE_H = 64, 36
SAMPLE_STEP_S = 0.25
MAX_STEPS = 500
VIDEO_MAX = 15_000_000
TRACE_MAX = 8_000_000
PREVIEW_MAX = 2_000_000
REPORT_MAX = 1_000_000
OVERLAY_NAME = ".openmates-playwright.config"
CONFIG_NAMES = ("playwright.config.ts", "playwright.config.mts", "playwright.config.js", "playwright.config.mjs", "playwright.config.cjs")
ASSET_DIR = Path("/tmp/openmates-recorder")
RUNNER_NAMES = ("playwright", "playwright.js", "cli.js")

GraySampler = Callable[[float], Optional[bytes]]


def log(message: str) -> None:
    print(f"[openmates-recorder] {message}", flush=True)


# ---------------------------------------------------------------- steps / report

def _clamp_name(text: str, limit: int = 300) -> str:
    text = " ".join(text.split())
    return (text or "step")[:limit]


def build_steps(raw_tests: list, bases: list, preview_step: Optional[str]) -> tuple:
    """Return (steps, marked_index, final_expect_index) on the video timeline.

    bases[i] is the video-timeline offset (ms) of raw_tests[i]. Step offsets are
    relative to the test's own start plus that base.
    """
    steps: list = []
    requested_index: Optional[int] = None
    marker_index: Optional[int] = None
    final_expect: Optional[int] = None
    requested = preview_step.strip() if preview_step else None
    for test, base in zip(raw_tests, bases):
        t0 = test["startMs"]
        for raw in test.get("steps", []):
            title = str(raw.get("title", ""))
            is_step = raw.get("category") == "test.step"
            is_marker = is_step and title.startswith(MARKER_PREFIX)
            name = _clamp_name(title[len(MARKER_PREFIX):] if is_marker else title)
            start = max(0, base + raw["startMs"] - t0)
            end = start + max(0, int(raw.get("durationMs", 0)))
            index = len(steps)
            steps.append({
                "name": name, "start_ms": start, "end_ms": end,
                "status": "failed" if raw.get("error") else "passed",
                "error": raw.get("error"), "is_preview": False,
            })
            if is_marker and marker_index is None:
                marker_index = index
            if requested and is_step and requested_index is None and requested in (name, title):
                requested_index = index
            if raw.get("category") == "expect":
                final_expect = index
    marked = requested_index if requested_index is not None else marker_index
    return steps, marked, final_expect


def cap_steps(steps: list, keep: list) -> tuple:
    """Truncate to MAX_STEPS keeping the last step; remap the tracked indexes."""
    if len(steps) <= MAX_STEPS:
        return steps, keep, False
    kept = list(range(MAX_STEPS - 1)) + [len(steps) - 1]
    remap = {old: new for new, old in enumerate(kept)}
    last = len(steps) - 1
    mapped = [None if i is None else remap.get(i, MAX_STEPS - 1 if i >= last else None) for i in keep]
    return [steps[i] for i in kept], mapped, True


def is_blank(gray: Optional[bytes]) -> bool:
    """True for a missing or near-uniform frame (gray stddev < BLANK_STDDEV)."""
    if not gray:
        return True
    mean = sum(gray) / len(gray)
    variance = sum((value - mean) ** 2 for value in gray) / len(gray)
    return math.sqrt(variance) < BLANK_STDDEV


def choose_preview_time(steps: list, marked: Optional[int], final_expect: Optional[int],
                        video_seconds: float, sampler: GraySampler) -> tuple:
    """Pick (seconds, step index, reason). Deterministic for the same input."""
    limit = max(0.0, video_seconds - 0.1)
    if marked is not None:
        return min(steps[marked]["end_ms"] / 1000, limit), marked, "marked_step"
    anchor = steps[final_expect]["start_ms"] / 1000 if final_expect is not None else limit
    anchor = min(anchor, limit)
    candidates = []
    t = anchor
    while t > 0:
        candidates.append(round(t, 3))
        t -= SAMPLE_STEP_S
    candidates.append(0.0)
    chosen = candidates[0]
    reason = "all_frames_blank"
    for candidate in candidates:
        if not is_blank(sampler(candidate)):
            chosen, reason = candidate, "last_non_blank_before_final_assertion"
            break
    index = None
    for i, step in enumerate(steps):
        if step["start_ms"] / 1000 <= chosen + 1e-6:
            index = i
    return chosen, index, reason


def build_report(tests: list, steps: list, preview_index: Optional[int], notes: list) -> str:
    """Serialise report.json, shrinking it under REPORT_MAX instead of failing."""
    if preview_index is not None and 0 <= preview_index < len(steps):
        steps[preview_index]["is_preview"] = True
    payload = {"tests": tests, "steps": steps, "preview_step_index": preview_index, "notes": notes}
    text = json.dumps(payload)
    if len(text.encode()) > REPORT_MAX:
        notes.append("report_trimmed: error texts dropped to fit 1 MB")
        for entry in tests + steps:
            entry["error"] = None
        text = json.dumps(payload)
    return text


def test_results(raw_tests: list) -> list:
    return [{
        "name": _clamp_name(t["title"], 500), "status": t["status"],
        "duration_ms": max(0, int(t["durationMs"])), "error": t.get("error"),
    } for t in raw_tests]


# ---------------------------------------------------------------- ffmpeg

def find_ffmpeg() -> Optional[str]:
    system = shutil.which("ffmpeg")
    if system:
        return system
    root = os.environ.get("PLAYWRIGHT_BROWSERS_PATH") or str(Path.home() / ".cache/ms-playwright")
    bundled = sorted(glob.glob(os.path.join(root, "ffmpeg-*", "ffmpeg-linux")))
    return bundled[-1] if bundled else None


def probe_seconds(ffmpeg: str, path: str) -> Optional[float]:
    proc = subprocess.run([ffmpeg, "-hide_banner", "-i", path], capture_output=True, text=True)
    match = re.search(r"Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)", proc.stderr)
    if not match:
        return None
    h, m, s = match.groups()
    return int(h) * 3600 + int(m) * 60 + float(s)


def gray_sampler(ffmpeg: str, video: str) -> GraySampler:
    def sample(seconds: float) -> Optional[bytes]:
        proc = subprocess.run(
            [ffmpeg, "-v", "error", "-ss", f"{seconds:.3f}", "-i", video, "-frames:v", "1",
             "-vf", f"scale={SAMPLE_W}:{SAMPLE_H}", "-pix_fmt", "gray", "-f", "rawvideo", "-"],
            capture_output=True)
        data = proc.stdout
        return data if proc.returncode == 0 and len(data) == SAMPLE_W * SAMPLE_H else None
    return sample


def extract_png(ffmpeg: str, video: str, seconds: float, out: Path, width: Optional[int] = None) -> bool:
    cmd = [ffmpeg, "-v", "error", "-y", "-ss", f"{seconds:.3f}", "-i", video, "-frames:v", "1"]
    if width:
        cmd += ["-vf", f"scale={width}:-2"]
    proc = subprocess.run(cmd + [str(out)], capture_output=True)
    return proc.returncode == 0 and out.exists()


def concat_videos(ffmpeg: str, videos: list, out: Path, work: Path) -> bool:
    """Concatenate with a VP8 re-encode (the encoder every bundled ffmpeg has)."""
    listing = work / "concat.txt"
    listing.write_text("".join(f"file {shlex.quote(v)}\n" for v in videos))
    proc = subprocess.run(
        [ffmpeg, "-v", "error", "-y", "-f", "concat", "-safe", "0", "-i", str(listing),
         "-c:v", "libvpx", "-b:v", "2M", "-an", str(out)], capture_output=True)
    return proc.returncode == 0 and out.exists()


def shrink_video(ffmpeg: str, source: str, out: Path, seconds: float, max_bytes: int) -> bool:
    """Re-encode to fit max_bytes: two attempts (lower bitrate and resolution), then give up."""
    for factor, width in ((0.8, 1280), (0.45, 800)):
        kbps = int(min(4000, max(80, max_bytes * factor * 8 / max(seconds, 1.0) / 1000)))
        proc = subprocess.run(
            [ffmpeg, "-v", "error", "-y", "-i", source, "-vf", f"scale='min({width},iw)':-2",
             "-c:v", "libvpx", "-b:v", f"{kbps}k", "-maxrate", f"{kbps}k", "-bufsize", f"{kbps * 2}k", "-an", str(out)],
            capture_output=True)
        if proc.returncode == 0 and out.exists() and out.stat().st_size <= max_bytes:
            return True
    out.unlink(missing_ok=True)
    return False


# ---------------------------------------------------------------- config overlay

def find_user_config(cwd: Path, argv: list) -> Optional[Path]:
    for i, arg in enumerate(argv):
        if arg in ("--config", "-c") and i + 1 < len(argv):
            return (cwd / argv[i + 1]).resolve()
        if arg.startswith("--config="):
            return (cwd / arg.split("=", 1)[1]).resolve()
    for name in CONFIG_NAMES:
        if (cwd / name).exists():
            return (cwd / name).resolve()
    return None


def overlay_source(user_config: Optional[Path], overlay: Path, reporter: str, output_dir: str) -> str:
    import_line = "const base = {};"
    if user_config is not None:
        rel = os.path.relpath(user_config, overlay.parent).replace(os.sep, "/")
        rel = rel if rel.startswith(".") else "./" + rel
        import_line = (
            f"import * as mod from {json.dumps(rel)};\n"
            "const base = typeof mod.default === 'function' ? {} : (mod.default ?? {});"
        )
    return f"""{import_line}
const forced = {{ video: {{ mode: 'on', size: {{ width: 1280, height: 720 }} }}, trace: 'retain-on-failure', screenshot: 'on' }};
const withUse = (cfg) => ({{ ...cfg, use: {{ ...(cfg.use || {{}}), ...forced }} }});
const cfg = withUse(base);
if (Array.isArray(cfg.projects)) cfg.projects = cfg.projects.map(withUse);
cfg.reporter = [[{json.dumps(reporter)}], ['list']];
cfg.outputDir = {json.dumps(output_dir)};
cfg.workers = 1;
cfg.fullyParallel = false;
export default cfg;
"""


def overlay_path(user_config: Optional[Path], cwd: Path) -> Path:
    directory = user_config.parent if user_config else cwd
    ts = user_config is not None and user_config.suffix in (".ts", ".mts")
    return directory / f"{OVERLAY_NAME}{'.ts' if ts else '.mjs'}"


def inject_config(argv: list, overlay: Path) -> tuple:
    """Point `playwright test` at the overlay config. Returns (argv, injected)."""
    out: list = []
    injected = False
    skip_next = False
    seen_runner = False
    for i, arg in enumerate(argv):
        if skip_next:
            skip_next = False
            continue
        if arg in ("--config", "-c") and seen_runner:
            skip_next = True
            continue
        if arg.startswith("--config="):
            continue
        if Path(arg).name in RUNNER_NAMES:
            seen_runner = True
        out.append(arg)
        if not injected and arg == "test" and i > 0 and Path(argv[i - 1]).name in RUNNER_NAMES:
            out.append(f"--config={overlay}")
            injected = True
        elif not injected and re.search(r"\bplaywright(\.js)?\s+test\b", arg):
            flag = f"--config={shlex.quote(str(overlay))}"
            out[-1] = re.sub(r"\bplaywright(\.js)?\s+test\b", lambda m: f"{m.group(0)} {flag}", arg, count=1)
            injected = True
    return out, injected


# ---------------------------------------------------------------- orchestration

def shrink_png(ffmpeg: Optional[str], png: Path, notes: list) -> None:
    if png.stat().st_size <= PREVIEW_MAX:
        return
    for width in (960, 640):
        tmp = png.with_suffix(".small.png")
        if ffmpeg and extract_png(ffmpeg, str(png), 0, tmp, width) and tmp.stat().st_size <= PREVIEW_MAX:
            tmp.replace(png)
            notes.append(f"preview_downscaled: {width}px wide")
            return
        tmp.unlink(missing_ok=True)
    png.unlink()
    notes.append("file_too_large: preview.png dropped")


def _video_bases(raw_tests: list, ffmpeg: Optional[str]) -> tuple:
    """Video-timeline offset per test (probed video length, else test duration)."""
    bases = []
    cursor = 0
    for test in raw_tests:
        bases.append(cursor)
        length = None
        video = test.get("video")
        if video and ffmpeg and os.path.exists(video):
            seconds = probe_seconds(ffmpeg, video)
            length = None if seconds is None else int(seconds * 1000)
        cursor += length if length is not None else int(test["durationMs"])
    return bases, cursor


def finalize(raw: dict, run_dir: Path, work: Path, preview_step: Optional[str], ffmpeg: Optional[str]) -> list:
    """Write all evidence files from the reporter's raw events; return notes."""
    notes: list = []
    raw_tests = raw.get("tests", [])
    videos = [t["video"] for t in raw_tests if t.get("video") and os.path.exists(t["video"])]
    bases, cursor = _video_bases(raw_tests, ffmpeg)
    steps, marked, final_expect = build_steps(raw_tests, bases, preview_step)

    video_path: Optional[str] = None
    if len(videos) == 1:
        video_path = videos[0]
    elif len(videos) > 1:
        if ffmpeg and concat_videos(ffmpeg, videos, work / "combined.webm", work):
            video_path = str(work / "combined.webm")
        else:
            video_path = videos[0]
            notes.append("video_partial: could not concatenate; video covers the first test only")
    video_seconds = cursor / 1000
    if video_path and ffmpeg:
        video_seconds = probe_seconds(ffmpeg, video_path) or video_seconds

    preview_index = marked
    preview_done = False
    if video_path and ffmpeg and steps:
        seconds, preview_index, reason = choose_preview_time(
            steps, marked, final_expect, video_seconds, gray_sampler(ffmpeg, video_path))
        preview_done = extract_png(ffmpeg, video_path, seconds, run_dir / "preview.png")
        notes.append(f"preview: {reason} at {seconds:.3f}s")
    if not preview_done:
        shots = [t["screenshot"] for t in raw_tests if t.get("screenshot") and os.path.exists(t["screenshot"])]
        if shots:
            shutil.copy(shots[-1], run_dir / "preview.png")
            preview_done = True
            notes.append("preview: end-of-test screenshot (no ffmpeg or no video available)")
        else:
            notes.append("preview_missing: no video frame or screenshot available")
    if preview_index is None and final_expect is not None:
        preview_index = final_expect
    if preview_done:
        shrink_png(ffmpeg, run_dir / "preview.png", notes)

    if video_path:
        size = os.path.getsize(video_path)
        if size <= VIDEO_MAX:
            shutil.copy(video_path, run_dir / "video.webm")
        elif ffmpeg and shrink_video(ffmpeg, video_path, run_dir / "video.webm", video_seconds, VIDEO_MAX):
            notes.append(f"video_reencoded: {size} bytes exceeded {VIDEO_MAX}")
        else:
            notes.append(f"file_too_large: video.webm dropped ({size} bytes)")
    traces = [t["trace"] for t in raw_tests if t.get("trace") and os.path.exists(t["trace"])]
    if traces:
        if os.path.getsize(traces[0]) <= TRACE_MAX:
            shutil.copy(traces[0], run_dir / "trace.zip")
        else:
            notes.append("file_too_large: trace.zip dropped")

    steps, (preview_index,), trimmed = cap_steps(steps, [preview_index])
    if trimmed:
        notes.append(f"steps_truncated: kept {MAX_STEPS} steps")
    (run_dir / "report.json").write_text(build_report(test_results(raw_tests), steps, preview_index, notes))
    return notes


def parse_args(argv: list) -> tuple:
    preview = root = None
    i = 0
    while i < len(argv) and argv[i] != "--":
        if argv[i] == "--preview-step" and i + 1 < len(argv):
            preview = argv[i + 1] or None
            i += 2
        elif argv[i] == "--workspace-root" and i + 1 < len(argv):
            root = argv[i + 1]
            i += 2
        else:
            raise SystemExit(f"unknown recorder argument: {argv[i]}")
    return preview, root, argv[i + 1:]


def main(argv: list) -> int:
    preview_step, root, command = parse_args(argv)
    if not command:
        raise SystemExit("no test command given")
    cwd = Path.cwd()
    workspace = Path(root) if root and Path(root).is_dir() else cwd
    run_dir_env = os.environ.get("OPENMATES_TEST_RUN_DIR", "outputs/test-run")
    run_dir = Path(run_dir_env) if os.path.isabs(run_dir_env) else workspace / run_dir_env
    run_dir.mkdir(parents=True, exist_ok=True)
    work = ASSET_DIR / "work"
    shutil.rmtree(work, ignore_errors=True)
    (work / "pw-output").mkdir(parents=True)
    raw_path = work / "raw.json"

    user_config = find_user_config(cwd, command)
    overlay = overlay_path(user_config, cwd)
    overlay.write_text(overlay_source(user_config, overlay, str(ASSET_DIR / "reporter.cjs"), str(work / "pw-output")))
    command, injected = inject_config(command, overlay)
    if not injected:
        log("no `playwright test` invocation found in the command; running it unchanged without recording")
    env = dict(os.environ, OPENMATES_RECORDER_RAW=str(raw_path))
    try:
        code = subprocess.run(command, env=env, cwd=cwd).returncode
    except FileNotFoundError as exc:
        log(f"test command could not be started: {exc}")
        return 127
    finally:
        overlay.unlink(missing_ok=True)

    if raw_path.exists():
        for note in finalize(json.loads(raw_path.read_text()), run_dir, work, preview_step, find_ffmpeg()):
            log(note)
    elif injected:
        log("the test reporter wrote no events; no report produced")
    return code


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
