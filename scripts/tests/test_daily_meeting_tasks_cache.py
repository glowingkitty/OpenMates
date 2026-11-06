# contract-test-file: tooling
"""OpenMates Tasks copy for the daily meeting: freshness, fallback and the loud banner."""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import daily_meeting_briefing as briefing  # noqa: E402
import daily_meeting_tasks_cache as cache_mod  # noqa: E402


def _stub_fetch(monkeypatch, result):
    def fake():
        if isinstance(result, Exception):
            raise result
        return result
    monkeypatch.setattr(cache_mod, "fetch", fake)


def test_live_read_refreshes_the_copy(tmp_path, monkeypatch):
    path = tmp_path / "tasks.json"
    _stub_fetch(monkeypatch, {"tasks": [{"short_id": "TASK-1"}]})
    data, status = cache_mod.load(path)
    assert data["tasks"][0]["short_id"] == "TASK-1"
    assert status["source"] == "live" and status["fresh"] and not status["error"]
    assert json.loads(path.read_text())["data"] == data


def test_failed_live_read_falls_back_to_the_copy_and_says_how_old(tmp_path, monkeypatch):
    path = tmp_path / "tasks.json"
    path.write_text(json.dumps({"fetched_at": "2026-11-01T00:00:00+00:00", "data": {"tasks": []}}))
    _stub_fetch(monkeypatch, cache_mod.TasksError("openmates CLI not found"))
    data, status = cache_mod.load(path)
    assert data == {"tasks": []}
    assert status["source"] == "cache" and not status["fresh"] and "not found" in status["error"]


def test_no_copy_and_no_live_read_is_reported_as_unavailable(tmp_path, monkeypatch):
    _stub_fetch(monkeypatch, cache_mod.TasksError("boom"))
    data, status = cache_mod.load(tmp_path / "none.json")
    assert data is None and status["source"] == "none"


def test_banner_is_silent_when_live_and_loud_otherwise():
    assert briefing._tasks_banner({"source": "live", "fresh": True}) == []
    stale = "\n".join(briefing._tasks_banner({"source": "cache", "fresh": False,
                                              "fetched_at": "2026-11-01T00:00:00+00:00", "age_hours": 120.0}))
    assert "NOT up to date" in stale and "120.0 h old" in stale
    assert "UNAVAILABLE" in "\n".join(briefing._tasks_banner({"source": "none"}))
    assert "UNAVAILABLE" in "\n".join(briefing._tasks_banner({}))
