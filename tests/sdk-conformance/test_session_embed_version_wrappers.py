"""Exact source-extracted Python facade with fake native; no SDK/product IO."""

# contract-test-file: tooling

import ast
import asyncio
import json
from pathlib import Path
from typing import Any
import pytest

ROOT = Path(__file__).resolve().parents[2]


# The Python SessionClient source is split across these modules; definitions
# are extracted from their combined module body without importing the package.
SESSION_SOURCES = ("session_types.py", "session_facades.py", "session_client.py")


def session_source_text(root):
    package = root / "packages/openmates-python/openmates"
    return "\n".join((package / name).read_text() for name in SESSION_SOURCES)
SOURCE = ROOT / "packages/openmates-python/openmates/session_client.py"


def classes():
    tree = ast.parse(session_source_text(ROOT))
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

    async def _prepared_call(self, operation, prepare, *, essential=False):
        # Same contract as SessionClient._prepared_call: owned arguments are
        # prepared immediately before the single native dispatch.
        return await operation(*prepare())


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
