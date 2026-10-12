"""The optional main-response trailer must never enter authored answer text."""

import pytest

from backend.apps.ai.processing.suggested_followup_stream import (
    CLOSE,
    OPEN,
    SuggestedFollowupStream,
)


def parse(chunks):
    parser = SuggestedFollowupStream()
    visible = "".join(parser.feed(chunk) for chunk in chunks) + parser.finish()
    return visible, parser.suggestion


@pytest.mark.parametrize("split", range(1, len(OPEN + CLOSE) + 24))
# contract-test: supporting surface=rest_api assertions=chats.followups.main-generated-composer
def test_every_two_chunk_split_keeps_trailer_out_of_answer(split):
    source = f"An answer.\n{OPEN}Could you compare the alternatives?{CLOSE}"
    visible, suggestion = parse([source[:split], source[split:]])
    assert visible == "An answer.\n"
    assert suggestion == "Could you compare the alternatives?"


# contract-test: supporting surface=rest_api assertions=chats.followups.main-generated-composer
def test_single_character_stream_and_language_are_preserved():
    source = f"La respuesta.\n{OPEN}¿Puedes darme un ejemplo?{CLOSE}"
    assert parse(source) == ("La respuesta.\n", "¿Puedes darme un ejemplo?")


@pytest.mark.parametrize("metadata", [
    f"{OPEN}unfinished",
    f"{OPEN}{'x' * 401}{CLOSE}",
    f"{OPEN}first{CLOSE}\n{OPEN}second{CLOSE}",
    f"{OPEN}first{CLOSE} extra text",
    f"{OPEN}{OPEN}nested{CLOSE}",
])
# contract-test: supporting surface=rest_api assertions=chats.followups.main-generated-composer
def test_invalid_trailers_are_hidden_and_produce_no_suggestion(metadata):
    assert parse(["Answer\n", metadata]) == ("Answer\n", None)


# contract-test: supporting surface=rest_api assertions=chats.followups.main-generated-composer
def test_quoted_and_fenced_markers_remain_literal_answer_text():
    literal = (
        f"> {OPEN}quoted{CLOSE}\n"
        f"```text\n{OPEN}code{CLOSE}\n```\n"
        f"~~~text\n{OPEN}also code{CLOSE}\n~~~\n"
    )
    visible, suggestion = parse([literal[:11], literal[11:]])
    assert visible == literal
    assert suggestion is None


# contract-test: supporting surface=rest_api assertions=chats.followups.main-generated-composer
def test_nontrailing_marker_is_not_interpreted_as_metadata():
    literal = f"The syntax is {OPEN}example{CLOSE}."
    assert parse([literal]) == (literal, None)
