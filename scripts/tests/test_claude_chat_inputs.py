# contract-test-file: tooling
"""Input-box watch: typed-but-unsent text vs Claude Code's grey next-prompt suggestion.

Regression: on 2026-11-14/15 the connector's send_message refused six chats for hours
because their empty input boxes showed Claude Code's suggestion, which a colourless
zellij dump cannot tell from typed text (scripts/claude_chat_inputs.py).
"""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import claude_chat_inputs as inputs  # noqa: E402  (path set above)

NOW = 1_800_000_000.0
SUGGESTION = "Go ahead with the backup setup, separate EU b…"


@dataclass
class FakeChat:
    session_id: str
    pane_id: str
    status: str = "idle"
    waiting_for: str = ""
    kind: str = "pane"
    zellij_session: str = "claude"
    title: str = "Production reliability audit"
    name: str = ""


class Panes:
    """Claude Code input boxes as zellij sees them (behaviour checked live on 2026-11-15):
    typing replaces the suggestion, Backspace on the last letter brings it back."""

    def __init__(self, boxes: dict[str, dict]):
        self.boxes, self.calls = boxes, []

    def __call__(self, session, *args):
        self.calls.append(args)
        box = self.boxes[args[2]]
        if args[0] == "write-chars":
            box["typed"] += args[-1]
        elif args[0] == "write" and args[-1] == inputs.BACKSPACE:
            box["typed"] = box["typed"][:-1]
        shown = box["typed"] or box.get("suggestion", "")
        screen = f"  Done.\n────\n❯ {shown}\n────\n  ⏵⏵ auto mode on" if shown else "────\n❯\n────"
        return type("Result", (), {"returncode": 0, "stdout": screen, "stderr": ""})()


def no_sleep(_seconds: float) -> None:
    return None


def test_input_text_reads_only_the_boxed_line_not_old_prompts():
    screen = "❯ an earlier prompt\n  Done.\n────\n❯ keep going\n────"
    assert inputs.input_text(screen) == "keep going"
    assert inputs.input_text("❯ an earlier prompt\n────\n❯\n────") == ""


def test_probe_tells_suggestion_from_typed_text_and_leaves_both_as_they_were():
    panes = Panes({"terminal_1": {"typed": "", "suggestion": SUGGESTION},
                   "terminal_2": {"typed": "deploy when green", "suggestion": SUGGESTION},
                   "terminal_3": {"typed": ""}})
    assert inputs.probe(panes, "claude", "terminal_1", no_sleep) == "suggestion"
    assert inputs.probe(panes, "claude", "terminal_2", no_sleep) == "typed"
    assert inputs.probe(panes, "claude", "terminal_3", no_sleep) == "empty"
    assert [box["typed"] for box in panes.boxes.values()] == ["", "deploy when green", ""]
    assert not any(call[-1] == "13" for call in panes.calls)  # never presses Enter


def test_probe_counts_a_screen_that_does_not_react_as_typed():
    def frozen(session, *args):
        return type("Result", (), {"returncode": 0, "stdout": "────\n❯ keep going\n────", "stderr": ""})()

    assert inputs.probe(frozen, "claude", "terminal_1", no_sleep) == "typed"


def test_watch_records_first_seen_and_probes_once_after_ten_quiet_minutes(tmp_path, monkeypatch):
    monkeypatch.setattr(inputs.lifecycle, "log_event", lambda directory, event: None)
    panes = Panes({"terminal_1": {"typed": "", "suggestion": SUGGESTION},
                   "terminal_2": {"typed": "outdated plan"}})
    live = [FakeChat("ghost", "1"), FakeChat("held", "2")]
    first = inputs.watch(live, tmp_path, NOW, panes, no_sleep)
    assert {sid: entry["verdict"] for sid, entry in first.items()} == {"ghost": "unchecked", "held": "unchecked"}
    assert not any(call[0] == "write-chars" for call in panes.calls)  # nothing typed before 10 min

    later = inputs.watch(live, tmp_path, NOW + inputs.PROBE_AFTER_SECONDS, panes, no_sleep)
    assert {sid: entry["verdict"] for sid, entry in later.items()} == {"ghost": "suggestion", "held": "typed"}
    assert later["held"]["since"] == NOW  # first seen, not last seen
    probes = sum(call[0] == "write-chars" for call in panes.calls)

    inputs.watch(live, tmp_path, NOW + 2 * inputs.PROBE_AFTER_SECONDS, panes, no_sleep)
    assert sum(call[0] == "write-chars" for call in panes.calls) == probes  # checked once per text
    stored = json.loads((tmp_path / inputs.INPUTS_FILE).read_text())
    assert stored["held"] == {**later["held"]}


def test_watch_restarts_the_clock_when_the_text_changes_and_never_probes_a_busy_chat(tmp_path, monkeypatch):
    monkeypatch.setattr(inputs.lifecycle, "log_event", lambda directory, event: None)
    panes = Panes({"terminal_1": {"typed": "first idea"}})
    busy = [FakeChat("c1", "1", status="busy")]
    inputs.watch(busy, tmp_path, NOW, panes, no_sleep)
    panes.boxes["terminal_1"]["typed"] = "second idea"
    entries = inputs.watch(busy, tmp_path, NOW + 3600, panes, no_sleep)
    assert entries["c1"]["since"] == NOW + 3600
    entries = inputs.watch(busy, tmp_path, NOW + 7200, panes, no_sleep)
    assert entries["c1"]["verdict"] == "unchecked"
    assert not any(call[0] == "write-chars" for call in panes.calls)


def test_watch_drops_chats_with_an_empty_box_and_non_pane_chats(tmp_path):
    panes = Panes({"terminal_1": {"typed": ""}})
    entries = inputs.watch([FakeChat("c1", "1"), FakeChat("w", "", kind="rc_worker")], tmp_path, NOW, panes)
    assert entries == {}


@pytest.mark.parametrize("payload", ["[]", "{}"])
def test_load_tolerates_an_empty_or_odd_file(tmp_path, payload):
    (tmp_path / inputs.INPUTS_FILE).write_text(payload)
    assert inputs.load(tmp_path) == {}
