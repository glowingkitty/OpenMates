"""Real-run Project names are natural language, never numbers."""

from __future__ import annotations

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from project_names import natural_nickname, natural_project_name  # noqa: E402 - scripts/ on path above


# contract-test: tooling
def test_project_name_is_topic_plus_word_nickname_without_digits() -> None:
    for _ in range(200):
        name = natural_project_name("Kitchen renovation")
        assert re.fullmatch(r"Kitchen renovation: [a-z]+ [a-z]+", name), name
        assert not re.search(r"\d", name)


# contract-test: tooling
def test_nicknames_vary() -> None:
    assert len({natural_nickname() for _ in range(200)}) > 50
