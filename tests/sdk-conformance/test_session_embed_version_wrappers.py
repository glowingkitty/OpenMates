"""Exact source-extracted Python facade with fake native; no SDK/product IO."""

# contract-test-file: tooling

import ast
import asyncio
import json
from pathlib import Path
from typing import Any
import pytest

ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "packages/openmates-python/openmates/session_client.py"


def classes():
    tree = ast.parse(SOURCE.read_text())
    selected = [
        n
        for n in tree.body
        if isinstance(n, ast.ClassDef)
        and n.name in ("SessionEmbeds", "SessionClientError")
    ]
    assert len(selected) == 2
    module = ast.Module(
        body=[
            ast.ImportFrom(
                module="__future__", names=[ast.alias(name="annotations")], level=0
            ),
            *selected,
        ],
        type_ignores=[],
    )
    values = {"json": json, "Any": Any}
    exec(compile(ast.fix_missing_locations(module), str(SOURCE), "exec"), values)
    return values["SessionEmbeds"], values["SessionClientError"]


class Native:
    def __init__(self):
        self.calls = []

    async def embeds_version_content(self, id, version):
        self.calls.append((id, version))
        return json.dumps({"content": "synthetic output", "opaque": {"kept": True}})


class Fake:
    def __init__(self):
        self._native = Native()

    async def _essential_call(self, op):
        return await op()


def test_direct_facade_forwards_only_explicit_id_and_closed_numeric_json():
    facade, _ = classes()
    fake = Fake()
    out = asyncio.run(facade(fake).version_content("synthetic-full-id", 2))
    assert out == {"content": "synthetic output", "opaque": {"kept": True}}
    assert fake._native.calls == [("synthetic-full-id", "2")]


@pytest.mark.parametrize("bad", [True, 1.5, 0, 9007199254740992])
def test_bad_versions_do_not_call_native(bad):
    facade, error = classes()
    fake = Fake()
    with pytest.raises(error) as e:
        asyncio.run(facade(fake).version_content("synthetic-full-id", bad))
    assert e.value.code == "invalid_argument" and fake._native.calls == []
