# backend/tests/test_browser_test_recorder.py
#
# Unit tests for the browser test recorder: report generation and parsing
# against the test-run contract, deterministic preview-frame selection and
# evidence size-cap handling. The sandbox-side script is loaded by path.

from __future__ import annotations

import importlib.util
import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from backend.shared.providers.e2b_test_recorder import ASSET_DIR, browser_recorder_wrapper
from backend.shared.python_schemas.code_test_run import TestRunSpec, parse_recorder_report

_spec = importlib.util.spec_from_file_location("record_browser", ASSET_DIR / "record_browser.py")
rb = importlib.util.module_from_spec(_spec)
sys.modules["record_browser"] = rb
_spec.loader.exec_module(rb)

FFMPEG = shutil.which("ffmpeg")


def raw_test(title="t", start=1_000, steps=None, status="passed", **extra):
    return {"title": title, "status": status, "startMs": start, "durationMs": 3000, "error": None,
            "steps": steps or [], **extra}


def raw_step(title, offset, duration=100, category="test.step", error=None, start=1_000):
    return {"title": title, "category": category, "depth": 0, "startMs": start + offset,
            "durationMs": duration, "error": error}


def sample_test():
    return raw_test(steps=[
        raw_step("open page", 0, category="pw:api"),
        raw_step("[preview] filled form", 1000),
        raw_step("click save", 1500, category="pw:api"),
        raw_step("expect list", 2500, category="expect"),
    ])


# contract-test: supporting surface=rest_api assertions=code-run.tests.recorded-evidence
def test_steps_are_ordered_with_offsets_and_marker() -> None:
    steps, marked, final_expect = rb.build_steps([sample_test()], [0], None)
    assert [s["name"] for s in steps] == ["open page", "filled form", "click save", "expect list"]
    assert [s["start_ms"] for s in steps] == [0, 1000, 1500, 2500]
    assert marked == 1 and final_expect == 3


# contract-test: supporting surface=rest_api assertions=code-run.tests.recorded-evidence
def test_requested_preview_step_wins_over_marker_and_offsets_follow_base() -> None:
    first = raw_test(steps=[raw_step("[preview] a", 0)])
    second = raw_test(start=9_000, steps=[raw_step("checkout", 200, start=9_000)])
    steps, marked, _ = rb.build_steps([first, second], [0, 5000], "checkout")
    assert marked == 1 and steps[1]["start_ms"] == 5200


# contract-test: supporting surface=rest_api assertions=code-run.tests.recorded-evidence
def test_report_round_trips_through_contract_parser() -> None:
    steps, marked, _ = rb.build_steps([sample_test(), raw_test("b", status="failed", steps=[
        raw_step("boom", 0, error="Error: x", category="expect")])], [0, 3000], None)
    text = rb.build_report(rb.test_results([sample_test()]), steps, marked, ["n"])
    tests, parsed_steps, preview = parse_recorder_report(text)
    assert preview == 1 and parsed_steps[1].is_preview and parsed_steps[4 - 1 + 1].status == "failed"
    assert tests[0].name == "t"


# contract-test: supporting surface=rest_api assertions=code-run.tests.recorded-evidence
def test_step_cap_keeps_last_step_and_remaps_preview() -> None:
    steps = [{"name": str(i), "start_ms": i, "end_ms": i, "status": "passed", "error": None, "is_preview": False}
             for i in range(rb.MAX_STEPS + 20)]
    capped, (preview,), trimmed = rb.cap_steps(steps, [len(steps) - 1])
    assert trimmed and len(capped) == rb.MAX_STEPS and capped[-1]["name"] == str(len(steps) - 1)
    assert preview == rb.MAX_STEPS - 1


# contract-test: supporting surface=rest_api assertions=code-run.tests.recorded-evidence
def test_blank_definition() -> None:
    assert rb.is_blank(None) and rb.is_blank(bytes([255]) * 100) and rb.is_blank(bytes([10, 11] * 50))
    assert not rb.is_blank(bytes([0, 255] * 50))


# contract-test: supporting surface=rest_api assertions=code-run.tests.recorded-evidence
def test_preview_selection_marked_step_is_end_of_step() -> None:
    steps, marked, final_expect = rb.build_steps([sample_test()], [0], None)
    seconds, index, reason = rb.choose_preview_time(steps, marked, final_expect, 4.0, lambda t: None)
    assert (seconds, index, reason) == (1.1, 1, "marked_step")


# contract-test: supporting surface=rest_api assertions=code-run.tests.recorded-evidence
def test_preview_selection_last_non_blank_before_final_assertion_is_deterministic() -> None:
    steps, _, final_expect = rb.build_steps([raw_test(steps=[
        raw_step("goto", 0, category="pw:api"), raw_step("expect", 2500, category="expect")])], [0], None)
    blank, content = bytes([255]) * 2304, bytes([0, 255] * 1152)
    # content is visible only up to 1.6s; the page is blank right before the assertion at 2.5s
    def sampler(t):
        return content if t <= 1.6 else blank

    runs = {rb.choose_preview_time(steps, None, final_expect, 4.0, sampler) for _ in range(3)}
    assert runs == {(1.5, 0, "last_non_blank_before_final_assertion")}


# contract-test: supporting surface=rest_api assertions=code-run.tests.recorded-evidence
def test_preview_all_blank_uses_frame_before_assertion() -> None:
    steps, _, final_expect = rb.build_steps([sample_test()], [0], None)
    seconds, _, reason = rb.choose_preview_time(steps, None, final_expect, 4.0, lambda t: bytes([9]) * 10)
    assert seconds == 2.5 and reason == "all_frames_blank"


# contract-test: supporting surface=rest_api assertions=code-run.tests.recorded-evidence
def test_inject_config_variants() -> None:
    overlay = Path("/w/.o.mjs")
    out, ok = rb.inject_config(["npx", "playwright", "test", "--config", "x.ts", "a.spec.ts"], overlay)
    assert ok and out == ["npx", "playwright", "test", f"--config={overlay}", "a.spec.ts"]
    out, ok = rb.inject_config(["bash", "-lc", "npm ci && npx playwright test a"], overlay)
    assert ok and "playwright test --config=/w/.o.mjs a" in out[2]
    assert rb.inject_config(["npm", "test"], overlay) == (["npm", "test"], False)


# contract-test: supporting surface=rest_api assertions=code-run.tests.recorded-evidence
def test_overlay_imports_user_config_relative_to_overlay() -> None:
    user = Path("/w/web/playwright.config.ts")
    src = rb.overlay_source(user, Path("/w/web/.openmates-playwright.config.ts"), "/tmp/r.cjs", "/tmp/out")
    assert '"./playwright.config.ts"' in src and "retain-on-failure" in src and "workers = 1" in src
    assert "const base = {};" in rb.overlay_source(None, Path("/w/o.mjs"), "/tmp/r.cjs", "/tmp/out")


# contract-test: supporting surface=rest_api assertions=code-run.tests.recorded-evidence
def test_wrapper_argv_embeds_assets_and_preview_step() -> None:
    spec = TestRunSpec.model_validate({"kind": "browser", "preview_step": "filled form",
                                       "test_command": {"argv": ["npx", "playwright", "test"]}})
    argv = browser_recorder_wrapper(spec)
    assert argv[:2] == ["python3", "-c"] and argv[-4:] == ["--", "npx", "playwright", "test"]
    assert argv[argv.index("--preview-step") + 1] == "filled form"


# contract-test: supporting surface=rest_api assertions=code-run.tests.recorded-evidence
def test_trace_and_video_caps_are_reported_not_fatal(tmp_path: Path) -> None:
    big_trace = tmp_path / "trace.zip"
    big_trace.write_bytes(b"0" * (rb.TRACE_MAX + 1))
    run_dir, work = tmp_path / "run", tmp_path / "work"
    run_dir.mkdir(), work.mkdir()
    raw = {"tests": [raw_test(trace=str(big_trace), steps=[raw_step("expect", 100, category="expect")])]}
    notes = rb.finalize(raw, run_dir, work, None, None)
    assert "file_too_large: trace.zip dropped" in notes and not (run_dir / "trace.zip").exists()
    tests, steps, _ = parse_recorder_report((run_dir / "report.json").read_text())
    assert len(tests) == 1 and len(steps) == 1


# contract-test: supporting surface=rest_api assertions=code-run.tests.recorded-evidence
def test_report_over_cap_drops_error_text() -> None:
    steps = [{"name": "s", "start_ms": 0, "end_ms": 0, "status": "failed", "error": "e" * 3900, "is_preview": False}
             for _ in range(rb.MAX_STEPS)]
    notes: list = []
    text = rb.build_report([], steps, None, notes)
    assert len(text.encode()) <= rb.REPORT_MAX and notes


# contract-test: supporting surface=rest_api assertions=code-run.tests.recorded-evidence
def test_reporter_script_is_valid_node() -> None:
    node = shutil.which("node")
    if node is None:
        pytest.skip("node not installed")
    assert subprocess.run([node, "--check", str(ASSET_DIR / "reporter.cjs")]).returncode == 0


# contract-test: supporting surface=rest_api assertions=code-run.tests.recorded-evidence
@pytest.mark.skipif(FFMPEG is None, reason="ffmpeg not installed")
def test_end_to_end_finalize_with_fixture_video_is_repeatable(tmp_path: Path) -> None:
    # 3s clip: black 0-1s, a test pattern 1-2s, black again 2-3s.
    video = tmp_path / "v.webm"
    subprocess.run([FFMPEG, "-v", "error", "-y", "-f", "lavfi", "-i", "color=black:s=320x180:d=1",
                    "-f", "lavfi", "-i", "testsrc=s=320x180:d=1:r=10", "-f", "lavfi", "-i", "color=black:s=320x180:d=1",
                    "-filter_complex", "[0][1][2]concat=n=3:v=1:a=0", "-r", "10", "-c:v", "libvpx", str(video)], check=True)
    raw = {"tests": [raw_test(video=str(video), steps=[
        raw_step("goto", 0, category="pw:api"), raw_step("expect", 2400, category="expect")])]}
    frames = []
    for name in ("a", "b"):
        run_dir, work = tmp_path / name, tmp_path / f"w{name}"
        run_dir.mkdir(), work.mkdir()
        notes = rb.finalize(raw, run_dir, work, None, FFMPEG)
        frames.append((run_dir / "preview.png").read_bytes())
        assert any("last_non_blank_before_final_assertion" in n for n in notes)
        assert (run_dir / "video.webm").exists()
        _, steps, preview = parse_recorder_report((run_dir / "report.json").read_text())
        assert preview == 0 and steps[0].is_preview
    assert frames[0] == frames[1] and len(frames[0]) > 0
    assert json.loads((tmp_path / "a" / "report.json").read_text())["notes"]
