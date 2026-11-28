# contract-test-file: infrastructure
"""Session videos: 7-day S3 objects linked from findings, reports and the Discord pushes."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import ai_test_users_exec as execution  # noqa: E402
import ai_test_users_message as message_text  # noqa: E402
import ai_test_users_report as reporting  # noqa: E402
import ai_test_users_scenarios as scenarios  # noqa: E402
import ai_test_users_video as video  # noqa: E402

URL = "https://nbg1.example.org/openmates-ai-test-user-videos/key.webm?X-Amz-Signature=abc"


def persona(name: str, **extra) -> dict:
    return {"persona": name, "target": "prod", "status": "persona_finished", "reports": [],
            "video": {"url": URL, "key": "k"}, **extra}


def test_object_keys_are_per_run_target_and_persona_and_safe():
    assert video.object_key("20261120-143143", "prod", "a_fosdem_chat-1") == (
        "ai-test-users/20261120-143143/prod/a_fosdem_chat-1.webm")
    assert "/" not in video.object_key("r", "dev", "../x y").split("/", 3)[3].removesuffix(".webm")
    assert video.LIFECYCLE_DAYS == 7 and video.LINK_SECONDS == 7 * 24 * 3600


def test_links_open_at_the_problem_moment():
    assert video.moment(URL, 83.4) == f"{URL}#t=83 (at 1:23)"
    assert video.moment(URL, None) == URL
    assert reporting.video_link(persona("x"), 83.4) == f"[video 1:23](<{URL}#t=83>)"
    assert reporting.video_link(persona("x")) == f"[video](<{URL}>)"
    assert reporting.video_link({"persona": "x"}) == ""


def test_every_problem_and_report_in_the_push_links_its_video():
    broken = persona("a-1", required_goals=True, goal_outcomes=[{"achieved": False, "why": "no event card"}])
    assert all(URL in line for line in reporting.problems([broken]))
    filed = persona("b-1", findings=[{"title": "t", "video_seconds": 61.0, "kept": True}],
                    reports=[{"short_issue_id": "AB12C", "status": "submitted", "finding_ids": [0]}])
    text = message_text.run_message("daily", [filed], [])
    assert f"report AB12C · [video 1:01](<{URL}#t=61>)" in text


def test_scenario_flow_verdicts_keep_each_runs_video():
    results = [persona("c_model_picker_export-1", goal_outcomes=[{"achieved": True}]),
               {"persona": "c_model_picker_export-2", "status": "persona_finished", "video_error": "no recording",
                "goal_outcomes": [{"achieved": True}]}]
    verdicts = scenarios.flow_verdicts(results)
    assert verdicts["c_model_picker_export"]["videos"] == [f"[video](<{URL}>)", "no video"]


def test_store_video_records_missing_and_failed_uploads(tmp_path, monkeypatch):
    summary: dict = {}
    execution.store_video(summary, tmp_path / "video.webm", "k", URL)
    assert summary["video_error"] == "no recording" and "video" not in summary
    (tmp_path / "video.webm").write_bytes(b"webm")

    def fail(path, key):
        raise RuntimeError("S3 down")

    monkeypatch.setattr(execution.video, "upload", fail)
    summary = {}
    execution.store_video(summary, tmp_path / "video.webm", "k", URL)
    assert summary["video_error"].startswith("upload failed: S3 down")
    monkeypatch.setattr(execution.video, "upload", lambda path, key: {"url": "fresh", "key": key})
    summary = {}
    execution.store_video(summary, tmp_path / "video.webm", "k", URL)
    assert summary["video"] == {"url": URL, "key": "k"}


def test_attach_run_links_earlier_recordings_and_estimates_finding_moments(tmp_path):
    import json

    run_dir = tmp_path / "20261120-140007"
    folder = run_dir / "dev" / "traveller"
    folder.mkdir(parents=True)
    (folder / "video.webm").write_bytes(b"webm")
    (folder / "result.json").write_text(json.dumps({
        "signup": {"seconds": 20.0}, "gift_card": {"seconds": 3.5},
        "findings": [{"title": "t", "severity": "medium", "step": 2, "kept": True}]}))
    (folder / "transcript.json").write_text(json.dumps([{"step": 1, "at_seconds": 1.0}, {"step": 2, "at_seconds": 40.0}]))
    run = {"kind": "daily", "date": "2026-11-20", "personas": [
        {"persona": "traveller", "target": "dev", "status": "persona_finished",
         "reports": [{"short_issue_id": "NZLBW", "status": "submitted", "finding_ids": [0]}]},
        {"persona": "cook", "target": "dev", "status": "persona_finished", "reports": []}],
        "totals": {"total_usd": 0.5, "harness_usd": 0.3, "e2b_usd": 0.1, "app_usd_list_price": 0.1}, "areas": [], "estimate_usd": 1.0, "cap_usd": 3.0}
    (run_dir / "run.json").write_text(json.dumps(run))
    uploaded = []
    out = video.attach_run(run_dir, uploader=lambda path, key: uploaded.append(key) or {"url": URL})
    assert uploaded == ["ai-test-users/20261120-140007/dev/traveller.webm"]
    traveller, cook = out["personas"]
    assert traveller["video"]["url"] == URL and traveller["video_offset_estimated"] is True
    assert traveller["findings"][0]["video_seconds"] == 63.5
    assert cook["video_error"] == "no recording"
    assert f"NZLBW (dev/traveller): submitted [video 1:03](<{URL}#t=63>)" in (
        run_dir / "report.md").read_text()
