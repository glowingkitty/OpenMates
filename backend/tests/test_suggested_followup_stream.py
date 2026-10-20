"""The optional main-response trailer must never enter authored answer text."""

import pytest

from backend.apps.ai.processing.suggested_followup_stream import (
    CLOSE,
    OPEN,
    XML_CLOSE,
    SuggestedFollowupCloseStyle,
    SuggestedFollowupOutcome,
    SuggestedFollowupStream,
)


def parse(chunks):
    parser = SuggestedFollowupStream()
    visible = "".join(parser.feed(chunk) for chunk in chunks) + parser.finish()
    return visible, parser.suggestion


@pytest.mark.parametrize("indent", range(4))
# contract-test: supporting surface=rest_api assertions=chats.followups.main-generated-composer
def test_every_chunk_boundary_keeps_indented_trailer_out_of_answer(indent):
    prefix = "An answer.\n" + " " * indent
    source = f"{prefix}{OPEN}Could you compare the alternatives?{CLOSE}"
    expected = (prefix, "Could you compare the alternatives?")
    for split in range(len(source) + 1):
        assert parse([source[:split], source[split:]]) == expected
    assert parse(source) == expected


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
    source = "Answer\n" + metadata
    for split in range(len(source) + 1):
        assert parse([source[:split], source[split:]]) == ("Answer\n", None)
    assert parse(source) == ("Answer\n", None)


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


@pytest.mark.parametrize("literal", [
    f"    {OPEN}indented code{CLOSE}\n",
    f"\t{OPEN}tab-indented code{CLOSE}\n",
    f">   {OPEN}quoted{CLOSE}\n",
    f"Text {OPEN}inline{CLOSE}\n",
    f"```text\n   {OPEN}fenced{CLOSE}\n```\n",
    f"~~~text\n {OPEN}fenced{CLOSE}\n~~~\n",
    f"   ```text\n  {OPEN}fenced{CLOSE}\n   ```\n",
])
# contract-test: supporting surface=rest_api assertions=chats.followups.main-generated-composer
def test_literal_markers_survive_every_chunk_boundary(literal):
    for split in range(len(literal) + 1):
        assert parse([literal[:split], literal[split:]]) == (literal, None)
    assert parse(literal) == (literal, None)


@pytest.mark.parametrize("source, outcome", [
    ("An answer.", SuggestedFollowupOutcome.ABSENT),
    (f"Inline {OPEN}literal{CLOSE}", SuggestedFollowupOutcome.ABSENT),
    (f"Answer\n{OPEN[:-1]}", SuggestedFollowupOutcome.ABSENT),
    (f"Answer\n{OPEN}A useful next message{CLOSE}", SuggestedFollowupOutcome.VALID),
    (f"Answer\n  {OPEN}A useful next message{CLOSE}", SuggestedFollowupOutcome.VALID),
    (f"Answer\n{OPEN}{CLOSE}", SuggestedFollowupOutcome.INVALID),
    (f"Answer\n{OPEN}{'x' * 401}{CLOSE}", SuggestedFollowupOutcome.INVALID),
    (f"Answer\n{OPEN}Suggestion{CLOSE} trailing", SuggestedFollowupOutcome.INVALID),
    (f"Answer\n{OPEN}unfinished", SuggestedFollowupOutcome.INCOMPLETE),
    (f"Answer\n{OPEN}unfinished{CLOSE[:-1]}", SuggestedFollowupOutcome.INCOMPLETE),
])
# contract-test: supporting surface=rest_api assertions=chats.followups.main-generated-composer
def test_content_free_outcome_survives_every_chunk_boundary(source, outcome):
    for chunks in ([source[:split], source[split:]] for split in range(len(source) + 1)):
        parser = SuggestedFollowupStream()
        for chunk in chunks:
            parser.feed(chunk)
        parser.finish()
        assert parser.outcome == outcome
    parser = SuggestedFollowupStream()
    for char in source:
        parser.feed(char)
    parser.finish()
    assert parser.outcome == outcome


@pytest.mark.parametrize("indent", range(4))
@pytest.mark.parametrize("closer, style", [
    (CLOSE, SuggestedFollowupCloseStyle.CANONICAL),
    (XML_CLOSE, SuggestedFollowupCloseStyle.XML),
])
# contract-test: supporting surface=rest_api assertions=chats.followups.main-generated-composer
def test_exact_closers_preserve_output_at_every_chunk_boundary(indent, closer, style):
    prefix = "Answer\n" + " " * indent
    source = f"{prefix}{OPEN}Could you compare these options?{closer}\n  "
    for chunks in [[source[:split], source[split:]] for split in range(len(source) + 1)] + [list(source)]:
        parser = SuggestedFollowupStream()
        visible = "".join(parser.feed(chunk) for chunk in chunks) + parser.finish()
        assert visible == prefix
        assert parser.suggestion == "Could you compare these options?"
        assert parser.outcome == SuggestedFollowupOutcome.VALID
        assert parser.close_style == style


@pytest.mark.parametrize("closer", [CLOSE[:-1], XML_CLOSE[:-1], "", "<</suggested_followup_message>"])
# contract-test: supporting surface=rest_api assertions=chats.followups.main-generated-composer
def test_partial_or_mixed_closers_stay_incomplete_at_every_chunk_boundary(closer):
    source = f"Answer\n{OPEN}Could you compare these options?{closer}"
    for chunks in [[source[:split], source[split:]] for split in range(len(source) + 1)] + [list(source)]:
        parser = SuggestedFollowupStream()
        visible = "".join(parser.feed(chunk) for chunk in chunks) + parser.finish()
        assert visible == "Answer\n"
        assert parser.suggestion is None
        assert parser.outcome == SuggestedFollowupOutcome.INCOMPLETE
        assert parser.close_style == SuggestedFollowupCloseStyle.NONE


@pytest.mark.parametrize("literal", [
    f"    {OPEN}code{XML_CLOSE}\n",
    f"> {OPEN}quoted{XML_CLOSE}\n",
    f"Text {OPEN}inline{XML_CLOSE}\n",
    f"```text\n {OPEN}fenced{XML_CLOSE}\n```\n",
])
# contract-test: supporting surface=rest_api assertions=chats.followups.main-generated-composer
def test_xml_closer_preserves_literal_markers_at_every_chunk_boundary(literal):
    for chunks in [[literal[:split], literal[split:]] for split in range(len(literal) + 1)] + [list(literal)]:
        assert parse(chunks) == (literal, None)


@pytest.mark.parametrize("suffix", ["extra", ">", f"\n{OPEN}second{XML_CLOSE}"])
# contract-test: supporting surface=rest_api assertions=chats.followups.main-generated-composer
def test_xml_closer_rejects_nonwhitespace_suffix_at_every_chunk_boundary(suffix):
    source = f"Answer\n{OPEN}Could you compare these options?{XML_CLOSE}{suffix}"
    for chunks in [[source[:split], source[split:]] for split in range(len(source) + 1)] + [list(source)]:
        parser = SuggestedFollowupStream()
        visible = "".join(parser.feed(chunk) for chunk in chunks) + parser.finish()
        assert visible == "Answer\n"
        assert parser.suggestion is None
        assert parser.outcome == SuggestedFollowupOutcome.INVALID
        assert parser.close_style == SuggestedFollowupCloseStyle.XML
