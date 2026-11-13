"""Read package manifests without third-party dependencies.

The runner container may be a bare ``python:3.13-slim`` image without PyYAML.
This reader supports the YAML subset used by package manifests: block mappings
and sequences, flow lists of scalars, quoted scalars and folded/literal block
scalars. PyYAML is used instead whenever it is installed; JSON is accepted too.
"""
from __future__ import annotations

import json
import re
from typing import Any


# --------------------------------------------------------------------------

def _scalar(text: str) -> Any:
    text = text.strip()
    if not text:
        return None
    if text[0] in "'\"":
        quote = text[0]
        end = text.rfind(quote)
        if end <= 0:
            raise ValueError("unterminated quoted scalar")
        inner = text[1:end]
        return inner.replace("''", "'") if quote == "'" else json.loads(f'"{inner}"')
    if text.startswith("["):
        if not text.endswith("]"):
            raise ValueError("unterminated flow sequence")
        body = text[1:-1].strip()
        return [_scalar(part) for part in body.split(",")] if body else []
    text = re.sub(r"\s+#.*$", "", text)
    if text in ("null", "~"):
        return None
    if text in ("true", "false"):
        return text == "true"
    if re.fullmatch(r"-?\d+", text):
        return int(text)
    return text


def _logical_lines(source: str) -> list[tuple[int, str]]:
    lines: list[tuple[int, str]] = []
    for raw in source.splitlines():
        if not raw.strip() or raw.lstrip().startswith("#") or raw.strip() == "---":
            lines.append((-1, raw))
            continue
        if "\t" in raw[: len(raw) - len(raw.lstrip())]:
            raise ValueError("tabs are not allowed for indentation")
        lines.append((len(raw) - len(raw.lstrip(" ")), raw))
    return lines


def _parse_block(lines: list[tuple[int, str]], index: int, indent: int) -> tuple[Any, int]:
    while index < len(lines) and lines[index][0] < 0:
        index += 1
    if index >= len(lines):
        return None, index
    is_sequence = lines[index][1].strip().startswith("- ") or lines[index][1].strip() == "-"
    result: Any = [] if is_sequence else {}
    while index < len(lines):
        level, raw = lines[index]
        if level < 0:
            index += 1
            continue
        if level < indent:
            break
        if level > indent:
            raise ValueError(f"unexpected indentation: {raw.strip()[:40]}")
        content = raw.strip()
        if is_sequence:
            if not (content.startswith("- ") or content == "-"):
                break
            item = content[1:].strip()
            if not item:
                value, index = _parse_block(lines, index + 1, indent + 2)
            elif re.match(r"^[A-Za-z0-9_\-\"']+\s*:(\s|$)", item):
                lines[index] = (indent + 2, " " * (indent + 2) + item)
                value, index = _parse_block(lines, index, indent + 2)
            else:
                value, index = _scalar(item), index + 1
            result.append(value)
            continue
        key, sep, rest = content.partition(":")
        if not sep:
            raise ValueError(f"expected mapping entry: {content[:40]}")
        key = str(_scalar(key))
        rest = rest.strip()
        if rest[:1] in (">", "|"):
            index, value = _block_scalar(lines, index + 1, indent, folded=rest.startswith(">"), chomp=rest[1:2])
        elif rest and not rest.startswith("#"):
            value, index = _scalar(rest), index + 1
        else:
            value, index = _parse_block(lines, index + 1, _child_indent(lines, index + 1, indent))
        result[key] = value
    return result, index


def _child_indent(lines: list[tuple[int, str]], index: int, indent: int) -> int:
    while index < len(lines) and lines[index][0] < 0:
        index += 1
    if index < len(lines) and lines[index][0] > indent:
        return lines[index][0]
    if index < len(lines) and lines[index][0] == indent and lines[index][1].strip().startswith("-"):
        return indent
    return indent + 1


def _block_scalar(lines: list[tuple[int, str]], index: int, indent: int, *, folded: bool, chomp: str) -> tuple[int, str]:
    parts: list[str] = []
    while index < len(lines) and (lines[index][0] < 0 or lines[index][0] > indent):
        parts.append(lines[index][1].strip())
        index += 1
    while parts and not parts[-1]:
        parts.pop()
    text = " ".join(part for part in parts if part) if folded else "\n".join(parts)
    return index, text if chomp == "-" else text + "\n"


def parse_manifest(source: str) -> Any:
    stripped = source.lstrip()
    if stripped.startswith("{"):
        return json.loads(stripped)
    try:
        import yaml  # Optional: present in the OpenMates API image, absent on python:slim.
    except ImportError:
        value, _ = _parse_block(_logical_lines(source), 0, 0)
        return value
    return yaml.safe_load(source)


