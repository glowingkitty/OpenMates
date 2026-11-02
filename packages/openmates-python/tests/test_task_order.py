"""Actual native stateless sorting; no session, profile or product transport."""

# contract-test: supporting surface=cli assertions=cli.surface.semantic-parity
import pytest
from openmates import SessionClientError, TaskOrderRow, sort_tasks


def test_reference_identity_and_opaque_metadata_are_preserved():
    metadata = {"opaque": object()}
    metadata["cycle"] = metadata
    b = {"title": "b", "position": 0, "metadata": metadata}
    a = {"title": "a", "position": None, "metadata": metadata}
    rows = [b, a, a]
    result = sort_tasks(rows, locale="en")
    assert result is not rows and result == [a, a, b]
    assert result[0] is a and result[1] is a and result[2] is b
    assert result[0]["metadata"] is metadata
    assert rows[0] is b and rows[1] is a
    assert TaskOrderRow.__optional_keys__ == {"position", "title", "source"}


# contract-test: supporting surface=cli assertions=cli.surface.semantic-parity
@pytest.mark.parametrize(
    "row",
    [
        None,
        [],
        3,
        {"title": 3},
        {"source": False},
        {"position": "0"},
        {"position": False},
        {"position": float("nan")},
        {"position": float("inf")},
    ],
)
# contract-test: supporting surface=cli assertions=cli.surface.semantic-parity
def test_malformed_sort_fields_are_not_coerced(row):
    with pytest.raises(SessionClientError) as caught:
        sort_tasks([row], locale="en")
    assert caught.value.code == "invalid_argument"


# contract-test: supporting surface=cli assertions=cli.surface.semantic-parity
def test_locale_is_explicit_and_unknown_keywords_are_rejected():
    with pytest.raises(TypeError):
        sort_tasks([])
    with pytest.raises(TypeError):
        sort_tasks([], locale="en", unknown=True)
    with pytest.raises(SessionClientError) as caught:
        sort_tasks([], locale=3)
    assert caught.value.code == "invalid_argument"


# contract-test: supporting surface=cli assertions=cli.surface.semantic-parity
def test_malformed_locale_tags_are_rejected_by_the_shared_sdk():
    for locale in ("", "en_US", "en-@-invalid"):
        with pytest.raises(SessionClientError) as caught:
            sort_tasks([], locale=locale)
        assert caught.value.code == "invalid_argument"
