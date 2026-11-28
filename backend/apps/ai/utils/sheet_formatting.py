"""Validate optional sheet formatting before admitting assistant output."""

from __future__ import annotations

from functools import lru_cache
import json
from pathlib import Path
import re
from typing import Any

from jsonschema import Draft202012Validator, validators

_SHEET_FORMAT_MARKER = "<!-- openmates-sheet-format-v1"
SHEET_FORMAT_PREFIX = f"{_SHEET_FORMAT_MARKER}: "
SHEET_FORMAT_SUFFIX = " -->"
SHEET_FENCE_LANGUAGE = "openmates_sheet"
_MAX_FORMATTING_BYTES = 256 * 1024
_FormattingValidator = validators.extend(
    Draft202012Validator,
    type_checker=Draft202012Validator.TYPE_CHECKER.redefine(
        "integer", lambda _checker, value: type(value) is int,
    ),
)


class SheetFormattingError(ValueError):
    """The formatting could not be applied to the supplied sheet."""


@lru_cache(maxsize=1)
def sheet_formatting_schema() -> dict[str, Any]:
    """Load the schema shared by prompt instructions and validation."""
    path = Path("/shared/config/sheet_formatting.schema.json")
    if not path.is_file():
        path = Path(__file__).resolve().parents[4] / "shared/config" / path.name
    return json.loads(path.read_text(encoding="utf-8"))


def _column_index(letters: str) -> int:
    index = 0
    for letter in letters:
        index = index * 26 + ord(letter) - ord("A") + 1
    return index


def _coordinate(address: str) -> tuple[int, int]:
    row_start = re.search(r"[0-9]", address)
    assert row_start is not None
    index = row_start.start()
    return int(address[index:]), _column_index(address[:index])


def _check_merges(merges: list[dict[str, str]], rows: int, columns: int) -> None:
    rectangles: list[tuple[int, int, int, int]] = []
    for index, merge in enumerate(merges):
        top, left = _coordinate(merge["start"])
        bottom, right = _coordinate(merge["end"])
        if not (top <= bottom <= rows and left <= right <= columns):
            raise SheetFormattingError(f"merges[{index}]: range must be ordered and inside the sheet")
        if (top, left) == (bottom, right):
            raise SheetFormattingError(f"merges[{index}]: range must include at least two cells")
        if any(
            top <= other_bottom and bottom >= other_top and left <= other_right and right >= other_left
            for other_top, other_left, other_bottom, other_right in rectangles
        ):
            raise SheetFormattingError(f"merges[{index}]: range overlaps another merge")
        rectangles.append((top, left, bottom, right))


def validate_sheet_formatting(
    value: object, *, rows: int, columns: int,
) -> dict[str, Any]:
    """Check types and references against the table, counting its heading as row one."""
    if not isinstance(value, dict):
        raise SheetFormattingError("formatting: expected an object")
    error = next(_FormattingValidator(sheet_formatting_schema()).iter_errors(value), None)
    if error is not None:
        path = ".".join(str(part) for part in error.absolute_path)
        raise SheetFormattingError(f"formatting{'.' + path if path else ''}: invalid field ({error.validator})")

    for address in value.get("cells", {}):
        row, column = _coordinate(address)
        if row > rows or column > columns:
            raise SheetFormattingError(f"cells.{address}: cell is outside the sheet")
    for column in value.get("columnWidths", {}):
        if _column_index(column) > columns:
            raise SheetFormattingError(f"columnWidths.{column}: column is outside the sheet")
    for row in value.get("rowHeights", {}):
        if int(row) > rows:
            raise SheetFormattingError(f"rowHeights.{row}: row is outside the sheet")
    if value.get("frozenRows", 0) > rows:
        raise SheetFormattingError("frozenRows: count exceeds the sheet height")
    if value.get("frozenColumns", 0) > columns:
        raise SheetFormattingError("frozenColumns: count exceeds the sheet width")
    _check_merges(value.get("merges", []), rows, columns)
    return value


def sheet_table_dimensions(table: str) -> tuple[int, int]:
    """Validate the rectangular Markdown table used by rich sheet authoring."""
    lines = table.splitlines()
    if not 2 <= len(lines) <= 1001:
        raise SheetFormattingError("table: expected a header, separator and up to 999 data rows")
    if any(not line.startswith("|") or not line.endswith("|") for line in lines):
        raise SheetFormattingError("table: each row must begin and end with a pipe")
    columns = lines[0].count("|") - 1
    if not 1 <= columns <= 256 or any(line.count("|") != columns + 1 for line in lines):
        raise SheetFormattingError("table: expected the same number of cells in each row")
    if not all(re.fullmatch(r":?-{3,}:?", part.strip()) for part in lines[1][1:-1].split("|")):
        raise SheetFormattingError("table: expected a Markdown alignment separator")
    return len(lines) - 1, columns


def serialize_formatted_sheet(table: str, formatting: object) -> tuple[str, int, int]:
    """Put styling in the same versioned text as the grid, with the old plain form as default."""
    rows, columns = sheet_table_dimensions(table)
    normalized = validate_sheet_formatting(formatting, rows=rows, columns=columns)
    if normalized:
        encoded = json.dumps(normalized, ensure_ascii=True, separators=(",", ":"), sort_keys=True)
        encoded = encoded.replace("<", "\\u003c").replace(">", "\\u003e")
        table = f"{table}\n{SHEET_FORMAT_PREFIX}{encoded}{SHEET_FORMAT_SUFFIX}"
    return table, rows - 1, columns


def split_formatted_sheet(table: str) -> tuple[str, dict[str, Any] | None]:
    """Read and validate the optional final formatting line in assistant edits."""
    body, separator, last = table.rstrip("\n").rpartition("\n")
    if any(line.startswith(_SHEET_FORMAT_MARKER) for line in body.splitlines()):
        raise SheetFormattingError("formatting: expected one final footer")
    if not last.startswith(_SHEET_FORMAT_MARKER):
        return table, None
    if not separator or not last.startswith(SHEET_FORMAT_PREFIX) or not last.endswith(SHEET_FORMAT_SUFFIX):
        raise SheetFormattingError("formatting: invalid footer marker")
    encoded = last[len(SHEET_FORMAT_PREFIX):-len(SHEET_FORMAT_SUFFIX)]
    if len(encoded.encode("utf-8", errors="replace")) > _MAX_FORMATTING_BYTES:
        raise SheetFormattingError("formatting: size limit exceeded")
    try:
        formatting = json.loads(encoded, object_pairs_hook=_unique_object)
    except (ValueError, RecursionError) as exc:
        raise SheetFormattingError("formatting: expected valid JSON") from exc
    rows, columns = sheet_table_dimensions(body)
    return body, validate_sheet_formatting(formatting, rows=rows, columns=columns)


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise SheetFormattingError("sheet: duplicate JSON key")
        result[key] = value
    return result


def normalize_authored_sheet(source: str) -> tuple[str, str, int, int]:
    """Convert a complete authoring fence to the existing sheet embed text."""
    if len(source.encode("utf-8", errors="replace")) > 256 * 1024:
        raise SheetFormattingError("sheet: size limit exceeded")
    try:
        value = json.loads(source, object_pairs_hook=_unique_object)
    except SheetFormattingError:
        raise
    except (ValueError, RecursionError) as exc:
        raise SheetFormattingError("sheet: expected valid JSON") from exc
    if not isinstance(value, dict) or set(value) - {"schemaVersion", "title", "table", "formatting"}:
        raise SheetFormattingError("sheet: unexpected authoring fields")
    if type(value.get("schemaVersion")) is not int or value["schemaVersion"] != 1:
        raise SheetFormattingError("sheet: schemaVersion must be 1")
    title, table = value.get("title"), value.get("table")
    if not isinstance(title, str) or not title.strip() or len(title) > 240:
        raise SheetFormattingError("title: expected nonempty text up to 240 characters")
    if not isinstance(table, str):
        raise SheetFormattingError("table: expected Markdown table text")
    if any(0xD800 <= ord(char) <= 0xDFFF for char in title + table):
        raise SheetFormattingError("sheet: invalid Unicode")
    if any(ord(char) < 32 for char in title) or any(ord(char) < 32 and char not in "\n\r\t" for char in table):
        raise SheetFormattingError("sheet: invalid control character")
    text, rows, columns = serialize_formatted_sheet(table.strip(), value.get("formatting", {}))
    return title.strip(), text, rows, columns
