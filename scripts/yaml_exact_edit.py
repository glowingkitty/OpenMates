"""Exact, layout-preserving edits of YAML files using PyYAML node positions.

Round-tripping catalog files through a YAML dumper reflows long strings and
flow lists. These helpers change only the characters of the addressed scalar
values, or insert a block after an addressed mapping entry, so comments and
formatting elsewhere stay untouched.
"""

from __future__ import annotations

from typing import Any, Iterable

import yaml

Path_ = tuple[Any, ...]


def _child(node: yaml.Node, step: Any) -> tuple[yaml.Node | None, yaml.Node]:
    """(key node or None, value node) for a mapping key or sequence index."""
    if isinstance(node, yaml.MappingNode):
        for key, value in node.value:
            if key.value == step:
                return key, value
        raise KeyError(step)
    if isinstance(node, yaml.SequenceNode):
        return None, node.value[step]
    raise KeyError(step)


def locate(root: yaml.Node, path: Path_) -> tuple[yaml.Node | None, yaml.Node]:
    key: yaml.Node | None = None
    node = root
    for step in path:
        key, node = _child(node, step)
    return key, node


def _scalar_text(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value)


def replace_scalars(text: str, updates: Iterable[tuple[Path_, Any]]) -> str:
    """Replace the scalar value at each path; values must already exist."""
    root = yaml.compose(text)
    spans = []
    for path, value in updates:
        _, node = locate(root, path)
        if not isinstance(node, yaml.ScalarNode):
            raise ValueError(f"{path} is not a scalar")
        spans.append((node.start_mark.index, node.end_mark.index, _scalar_text(value)))
    for start, end, replacement in sorted(spans, reverse=True):
        text = text[:start] + replacement + text[end:]
    return text


def insert_after_entry(text: str, mapping_path: Path_, after_key: str, block: str) -> str:
    """Insert ``block`` (YAML lines at the entry's indentation) after a mapping entry.

    ``block`` is written without leading indentation; it is indented to the
    column of ``after_key`` and placed after the last line of that entry's value.
    """
    root = yaml.compose(text)
    _, mapping = locate(root, mapping_path)
    key_node, value_node = _child(mapping, after_key)
    column = key_node.start_mark.column
    end = value_node.end_mark.index
    line_start = text.rfind("\n", 0, end) + 1
    if text[line_start:end].strip():
        # The value ends mid-line (a scalar or flow value): insert after that line.
        line_end = text.find("\n", end)
        insert_at = len(text) if line_end == -1 else line_end + 1
    else:
        # A block value ends where the next token's line starts.
        insert_at = line_start
    indented = "".join(" " * column + line + "\n" if line else "\n" for line in block.rstrip("\n").split("\n"))
    return text[:insert_at] + indented + text[insert_at:]
