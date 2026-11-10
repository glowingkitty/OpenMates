"""The Rust core's serialised decks are fixed points of the backend normaliser.

A manual deck edit is saved as the markup the Rust client core serialises
(`serialise_deck_markup`); the server cannot re-normalise it because the embed
content is client-encrypted. The assistant's next diff edit then patches that
stored markup and normalises the result with `normalise_slides_markup`. Both
only agree when every deck the core writes is already normaliser output, so
the core's round-trip fixtures (each pinned byte for byte in
`deck_markup_tests.rs`) must normalise unchanged here. Reading them from the
Rust source keeps one copy of each fixture.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from backend.shared.python_utils.slides_markup import normalise_slides_markup

RUST_FIXTURES = (
    Path(__file__).resolve().parents[2]
    / "packages/openmates-rust/src/client/shared_items/deck_markup_tests.rs"
)
FIXTURE_NAMES = ("FULL_DECK", "LAPTOP_DECK", "CLASSIC_DECK", "NOTEPAD_DECK")


def _rust_fixture(name: str) -> str:
    source = RUST_FIXTURES.read_text(encoding="utf-8")
    match = re.search(rf'const {name}: &str = r##"(.*?)"##;', source, re.DOTALL)
    assert match, f"{name} not found in {RUST_FIXTURES.name}"
    return match.group(1)


# contract-test: supporting surface=rest_api assertions=slides.editor.direct-manipulation,slides.assistant.create-and-diff-edit
@pytest.mark.parametrize("name", FIXTURE_NAMES)
def test_rust_core_serialised_deck_is_a_backend_normaliser_fixed_point(name: str) -> None:
    markup = _rust_fixture(name)
    assert markup.startswith("<deck ") and markup.endswith("</deck>\n")
    assert normalise_slides_markup(markup).markup == markup
