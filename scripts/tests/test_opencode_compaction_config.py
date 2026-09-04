import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


# contract-test: tooling
def test_compaction_keeps_a_bounded_recent_tail_before_auto_continuation() -> None:
    config = json.loads((ROOT / "opencode.json").read_text(encoding="utf-8"))

    assert config["compaction"] == {
        "auto": True,
        "prune": True,
        "tail_turns": 1,
        "preserve_recent_tokens": 32_000,
        "reserved": 64_000,
    }


def test_primary_build_turn_has_a_bounded_tool_loop() -> None:
    config = json.loads((ROOT / "opencode.json").read_text(encoding="utf-8"))

    assert config["agent"]["build"]["steps"] == 8
