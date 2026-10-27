"""The Python SDK uses the same primary-only calendar vectors as the npm SDK."""
import json
from pathlib import Path

import pytest

from openmates.calendar_event import build_calendar_event_file

VECTORS = json.loads((Path(__file__).resolve().parents[3] / "shared/test-fixtures/calendar-event-export.json").read_text())


@pytest.mark.parametrize("sample", VECTORS["valid"], ids=lambda value: value["id"])
# contract-test: supporting surface=sdks.pip assertions=calendar-event.export.primary-only,calendar-event.content.validated
def test_primary_only_calendar_vectors(sample):
    file = build_calendar_event_file(VECTORS["embed_id"], sample["content"])
    assert file is not None
    unfolded = file.replace("\r\n ", "")
    assert sample["start_line"] + "\r\n" in unfolded
    if sample["end_line"]:
        assert sample["end_line"] + "\r\n" in unfolded
    else:
        assert "DTEND" not in unfolded
    assert unfolded.split("\r\n").count("BEGIN:VEVENT") == 1
    assert unfolded.split("\r\n").count("END:VEVENT") == 1
    assert f"UID:{VECTORS['embed_id']}@openmates\r\n" in unfolded
    assert "Context only" not in unfolded
    assert not any(line.startswith(("ATTENDEE:", "BEGIN:VALARM", "METHOD:")) for line in unfolded.split("\r\n"))
    assert all(len(line.encode("utf-8")) <= 75 for line in file.split("\r\n"))
    if sample["id"] == "unicode-and-injection":
        assert "Réunion\\; café\\, 東京 🚀" in unfolded
        assert "\\nBEGIN:VEVENT\\nATTENDEE:" in unfolded
        assert "URL:https://example.org/event?tags=a,b" in unfolded


@pytest.mark.parametrize("sample", VECTORS["invalid"], ids=lambda value: value["id"])
# contract-test: supporting surface=sdks.pip assertions=calendar-event.export.primary-only,calendar-event.content.validated
def test_invalid_primary_has_no_calendar_file(sample):
    assert build_calendar_event_file(VECTORS["embed_id"], sample["content"]) is None


# contract-test: supporting surface=sdks.pip assertions=calendar-event.streaming.saved-lifecycle,calendar-event.export.primary-only
def test_unfinished_events_are_unavailable():
    for status in ["processing", "error", "cancelled"]:
        assert build_calendar_event_file(VECTORS["embed_id"], {**VECTORS["valid"][0]["content"], "status": status}) is None
