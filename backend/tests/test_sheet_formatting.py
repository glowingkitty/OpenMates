"""Validation checks for the optional formatting carried by sheet embeds."""

import json
from unittest.mock import AsyncMock

import pytest
from jsonschema import Draft202012Validator

from backend.apps.ai.utils.sheet_formatting import (
    SheetFormattingError,
    normalize_authored_sheet,
    sheet_formatting_schema,
    split_formatted_sheet,
    validate_sheet_formatting,
)


# contract-test: supporting surface=gui.web assertions=rich-sheets.creation.validated-formatting
def test_sheet_formatting_schema_is_valid():
    Draft202012Validator.check_schema(sheet_formatting_schema())


# contract-test: supporting surface=gui.web assertions=rich-sheets.creation.validated-formatting
def test_valid_sheet_formatting_preserves_false_and_zero():
    formatting = {
        "columnWidths": {"A": 192},
        "rowHeights": {"1": 56},
        "cells": {
            "A1": {
                "backgroundColor": "#1E3A8A", "textColor": "#FFFFFF", "fontFamily": "Arial",
                "fontSize": 24, "bold": True, "italic": False, "underline": True,
                "strikethrough": False, "horizontalAlign": "center", "verticalAlign": "middle",
                "wrap": True, "borders": {"bottom": {"style": "double", "color": "#44AAFF"}},
            },
            "B2": {"numberFormat": {"kind": "currency", "currency": "USD", "decimals": 0}},
            "B3": {"numberFormat": {"kind": "date", "pattern": "yyyy-mm-dd"}},
        },
        "merges": [{"start": "A1", "end": "B1"}],
        "frozenRows": 1,
        "frozenColumns": 0,
    }
    assert validate_sheet_formatting(formatting, rows=3, columns=2) == formatting
    assert validate_sheet_formatting({}, rows=3, columns=2) == {}


@pytest.mark.parametrize(("formatting", "message"), [
    ({"cells": {"B0": {}}}, "formatting.cells"),
    ({"cells": {"A1": {"fontFamily": "url(evil)"}}}, "fontFamily"),
    ({"cells": {"A1": {"backgroundColor": "red"}}}, "backgroundColor"),
    ({"cells": {"A1": {"borders": {"top": {"style": "thin"}}}}}, "borders"),
    ({"cells": {"C3": {}}}, "cells.C3"),
    ({"columnWidths": {"AA": 100}}, "columnWidths.AA"),
    ({"rowHeights": {"4": 32}}, "rowHeights.4"),
    ({"frozenRows": 4}, "frozenRows"),
    ({"frozenColumns": True}, "frozenColumns"),
    ({"frozenColumns": 1.0}, "frozenColumns"),
    ({"merges": [{"start": "A1", "end": "A1"}]}, "at least two cells"),
    ({"merges": [{"start": "B1", "end": "A2"}]}, "ordered and inside"),
    ({"merges": [{"start": "A1", "end": "B4"}]}, "ordered and inside"),
    ({"merges": [{"start": "A1", "end": "B2"}, {"start": "B2", "end": "B3"}]}, "overlaps"),
])
# contract-test: supporting surface=gui.web assertions=rich-sheets.creation.validated-formatting
def test_invalid_sheet_formatting_has_a_readable_error(formatting, message):
    with pytest.raises(SheetFormattingError, match=message):
        validate_sheet_formatting(formatting, rows=3, columns=2)


# contract-test: supporting surface=gui.web assertions=rich-sheets.compatibility.plain,rich-sheets.creation.validated-formatting
def test_normalized_authored_sheet_is_the_existing_table_with_an_optional_footer():
    table = "| Item | Price |\n| --- | --- |\n| Tea | 4.50 |"
    payload = {"title": "Shopping", "schemaVersion": 1, "table": table}
    assert normalize_authored_sheet(json.dumps(payload)) == ("Shopping", table, 1, 2)
    formatting = {"columnWidths": {"A": 200}, "cells": {"A1": {"bold": True}}}
    title, text, rows, columns = normalize_authored_sheet(json.dumps({**payload, "formatting": formatting}))
    assert (title, rows, columns) == ("Shopping", 1, 2)
    assert split_formatted_sheet(text) == (table, formatting)
    assert split_formatted_sheet(table) == (table, None)


@pytest.mark.parametrize(("footer", "message"), [
    ("<!-- openmates-sheet-format-v1: {} -->\n| More data |", "one final footer"),
    ("<!-- openmates-sheet-format-v1: {} -->\n<!-- openmates-sheet-format-v1: {} -->", "one final footer"),
    ("<!-- openmates-sheet-format-v1:{} -->", "invalid footer marker"),
    ("<!-- openmates-sheet-format-v1: " + " " * (256 * 1024) + "{} -->", "size limit"),
], ids=["nonfinal", "duplicate", "malformed", "oversized"])
# contract-test: supporting surface=gui.web assertions=rich-sheets.creation.validated-formatting
def test_split_rejects_invalid_formatting_footers(footer, message):
    with pytest.raises(SheetFormattingError, match=message):
        split_formatted_sheet(f"| Item |\n| --- |\n| Tea |\n{footer}")


@pytest.mark.parametrize(("source", "message"), [
    ('{"schemaVersion":1,"schemaVersion":2}', "duplicate JSON key"),
    ('{"schemaVersion":true,"title":"Sheet","table":"x"}', "schemaVersion"),
    ('{"schemaVersion":1,"title":"Sheet","table":"x"}', "header, separator"),
    ('{"schemaVersion":1,"title":"Sheet","table":"| A |\\n| --- |\\n| B | C |"}', "same number"),
])
# contract-test: supporting surface=gui.web assertions=rich-sheets.creation.validated-formatting
def test_authored_fence_rejects_invalid_source(source, message):
    with pytest.raises(SheetFormattingError, match=message):
        normalize_authored_sheet(source)


@pytest.mark.parametrize("valid", [True, False])
# contract-test: supporting surface=gui.web assertions=rich-sheets.creation.validated-formatting
async def test_formatted_fence_uses_the_sheet_lifecycle(monkeypatch, valid):
    from backend.core.api.app.services.embed_service import EmbedService

    create = AsyncMock(return_value={"embed_id": "sheet", "embed_reference": '{"type":"sheet","embed_id":"sheet"}'})
    update = AsyncMock(return_value=True)
    monkeypatch.setattr(EmbedService, "create_table_embed_placeholder", create)
    monkeypatch.setattr(EmbedService, "update_table_embed_content", update)
    service = object.__new__(EmbedService)
    identity = {"chat_id": "chat", "user_id": "user", "user_id_hash": "hash", "user_vault_key_id": "key"}
    placeholder = await service.create_json_content_embed_placeholder(
        **identity, message_id="message", source_language="openmates_sheet",
    )
    assert placeholder["embed_id"] == "sheet"
    create.assert_awaited_once()

    source = json.dumps({
        "title": "Budget", "schemaVersion": 1, "table": "| Item |\n| --- |\n| Tea |",
        "formatting": {"cells": {"A1": {"bold": True}}} if valid else {"columnWidths": {"Z": 80}},
    })
    await service.update_json_content_embed_content(
        **identity, embed_id="sheet", source_language="openmates_sheet", source_json=source,
    )
    values = update.await_args.kwargs
    if valid:
        assert values["status"] == "finished"
        assert values["row_count"] == 1
        assert split_formatted_sheet(values["table_content"])[1] == {"cells": {"A1": {"bold": True}}}
    else:
        assert values["status"] == "error"
        assert values["table_content"] == ""
        assert values["validation_error"] == "columnWidths.Z: column is outside the sheet"


# contract-test: supporting surface=gui.web assertions=rich-sheets.creation.validated-formatting,rich-sheets.collaboration.shared-history
@pytest.mark.parametrize(("live_enabled", "regenerate"), [(False, False), (True, False), (True, True)])
async def test_direct_sheet_diff_rejects_invalid_formatting_before_write_or_delivery(
    monkeypatch, live_enabled, regenerate,
):
    from toon_format import encode

    from backend.apps.ai.tasks import stream_consumer
    from backend.tests.test_assistant_live_changes import REQUEST, _setup
    from backend.tests.test_embed_diff_full_replacement import _FakeDirectusService

    table = "| Item | Amount |\n| --- | --- |\n| Tea | 12 |"
    existing_footer = '<!-- openmates-sheet-format-v1: {"frozenRows":1} -->'
    added_footer = '<!-- openmates-sheet-format-v1: {"frozenColumns":9} -->'
    if regenerate:
        added_footer = '<!-- openmates-sheet-format-v1: {"cells":{"A2":{"bold":true}}} -->'
    patch = f"@@ -3,1 +3,2 @@\n | Tea | 12 |\n+{added_footer}"
    cache, encryption, service = _setup(monkeypatch, flag=live_enabled, online=True)
    encryption.plaintext = encode({"type": "sheet", "table": table})
    claim = AsyncMock(return_value=True)
    deliver = AsyncMock(return_value="sent")
    resolve = AsyncMock(return_value=("suggestion_card", {
        "current_text_form": f"{table}\n{existing_footer}", "current_version": 4,
    }))
    monkeypatch.setattr(stream_consumer, "claim_embed_version", claim)
    monkeypatch.setattr(stream_consumer, "deliver_assistant_change", deliver)
    monkeypatch.setattr(stream_consumer, "resolve_outcome_details", resolve)

    result = await stream_consumer._apply_diff_block_to_existing_embed(
        diff_content=patch, diff_embed_ref=None, request_data=REQUEST, cache_service=cache,
        directus_service=_FakeDirectusService(), encryption_service=encryption,
        embed_service=service, user_vault_key_id="vault-1", log_prefix="[test]",
    )

    assert "invalid sheet formatting" in result
    claim.assert_not_awaited()
    assert service.writes == 0
    if regenerate:
        assert "one final footer" in result
        deliver.assert_awaited_once()
        assert deliver.await_args.kwargs["new_text_form"] == f"{table}\n{added_footer}"
    else:
        assert "frozenColumns" in result
        deliver.assert_not_awaited()
