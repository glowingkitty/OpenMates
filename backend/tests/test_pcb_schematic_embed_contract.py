# backend/tests/test_pcb_schematic_embed_contract.py
#
# Contract tests for the Electronics-owned PCB schematic embed. These tests keep
# atopile fenced blocks out of the generic Code embed path and enforce that the
# E2B compile wrapper uses a version-matched compiler/docs policy before any
# untrusted source is built.

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml


REPO_ROOT = Path(__file__).resolve().parents[2]
ELECTRONICS_APP_YML = REPO_ROOT / "backend/apps/electronics/app.yml"


def test_atopile_fence_metadata_defaults_to_electronics_pcb_embed() -> None:
    from backend.apps.ai.utils.pcb_schematic_fences import (
        _extract_pcb_schematic_metadata,
        _is_pcb_schematic_fence,
    )

    source = """import Resistor

module BuckInput:
    resistor = new Resistor
    resistor.resistance = 10kohm +/- 5%
"""

    assert _is_pcb_schematic_fence("atopile") is True
    assert _is_pcb_schematic_fence("ato") is True
    assert _is_pcb_schematic_fence("pcb_schematic") is True
    assert _is_pcb_schematic_fence("python") is False

    metadata = _extract_pcb_schematic_metadata("ato", None, source)

    assert metadata == {
        "language": "atopile",
        "filename": "buck_input.ato",
        "module_name": "BuckInput",
        "title": "BuckInput",
        "line_count": 6,
    }

    multi_module_source = """module Helper:
    pass

module App:
    helper = new Helper
"""
    assert _extract_pcb_schematic_metadata("atopile", None, multi_module_source)["module_name"] == "App"


def test_electronics_app_registers_pcb_schematic_with_version_matched_instructions() -> None:
    app = yaml.safe_load(ELECTRONICS_APP_YML.read_text())

    embed = next(
        item for item in app["embed_types"]
        if item.get("backend_type") == "pcb_schematic"
    )
    assert embed["category"] == "direct"
    assert embed["frontend_type"] == "electronics-pcb-schematic"
    assert embed["preview_component"] == "electronics/PcbSchematicEmbedPreview.svelte"
    assert embed["fullscreen_component"] == "electronics/PcbSchematicEmbedFullscreen.svelte"

    instruction = next(
        item for item in app["instructions"]
        if "schematic" in item.get("for_embed_types", [])
    )
    text = instruction["instruction"]
    assert "atopile==0.15.7" in text
    assert "atopile_docs_version: 0.15.7" in text
    assert "code.get_docs" in text
    assert "requires-atopile: \"^0.15.7\"" in text
    assert "module App:" in text
    assert "never write `new component`" in text


def test_pcb_schematic_provider_builds_safe_atopile_project(monkeypatch: pytest.MonkeyPatch) -> None:
    from backend.shared.providers.e2b_pcb_schematic_compiler import (
        ATOPILE_DOCS_VERSION,
        ATOPILE_PACKAGE_VERSION,
        PcbSchematicCompileRequest,
        compile_pcb_schematic_in_e2b,
    )

    assert ATOPILE_PACKAGE_VERSION == "0.15.7"
    assert ATOPILE_DOCS_VERSION == ATOPILE_PACKAGE_VERSION

    class FakeFiles:
        def __init__(self) -> None:
            self.writes: list[tuple[str, str]] = []

        def write(self, path: str, content: str) -> None:
            self.writes.append((path, content))

        def list(self, path: str):
            return [
                SimpleNamespace(name=".ato", path=f"{path}/.ato", is_dir=False),
                SimpleNamespace(name="ato.yaml", path=f"{path}/ato.yaml", is_dir=False),
                SimpleNamespace(name="main.ato", path=f"{path}/main.ato", is_dir=False),
                SimpleNamespace(name="board.kicad_pcb", path=f"{path}/build/default/board.kicad_pcb", is_dir=False),
            ]

        def read(self, path: str) -> str:
            return f"content for {path}"

    class FakeCommands:
        def __init__(self) -> None:
            self.commands: list[str] = []

        def run(self, command: str, **_kwargs):
            self.commands.append(command)
            return SimpleNamespace(exit_code=0, stdout="ok", stderr="")

    class FakeSandbox:
        create_kwargs: dict | None = None
        last: "FakeSandbox | None" = None

        def __init__(self) -> None:
            self.sandbox_id = "sandbox-pcb"
            self.files = FakeFiles()
            self.commands = FakeCommands()
            self.killed = False
            FakeSandbox.last = self

        @classmethod
        def create(cls, **kwargs):
            cls.create_kwargs = kwargs
            return cls()

        def kill(self) -> None:
            self.killed = True

    monkeypatch.setitem(__import__("sys").modules, "e2b", SimpleNamespace(Sandbox=FakeSandbox))

    result = compile_pcb_schematic_in_e2b(
        PcbSchematicCompileRequest(
            source="module App:\n    pass\n",
            filename="unsafe name.ato",
            module_name="App",
        ),
        api_key="test-key",
    )

    sandbox = FakeSandbox.last
    assert sandbox is not None
    assert FakeSandbox.create_kwargs == {
        "api_key": "test-key",
        "secure": True,
        "allow_internet_access": True,
        "network": {"allow_public_traffic": False},
    }
    assert any("uv venv --python 3.14 .venv" in cmd for cmd in sandbox.commands.commands)
    assert any("uv pip install --python .venv/bin/python atopile==0.15.7" in cmd for cmd in sandbox.commands.commands)
    assert any(".venv/bin/ato build" in cmd for cmd in sandbox.commands.commands)
    assert ("/home/user/openmates-pcb/ato.yaml", 'requires-atopile: "^0.15.7"\n\npaths:\n  src: ./\n  layout: ./layouts\n\nbuilds:\n  default:\n    entry: main.ato:App\n') in sandbox.files.writes
    assert result.status == "succeeded"
    assert result.sandbox_id == "sandbox-pcb"
    assert result.artifact_manifest["bundle"]["type"] == "source_bundle"
    assert not any(item["name"] == ".ato" for item in result.artifact_manifest["files"])
    assert any(item["type"] == "kicad_pcb" for item in result.artifact_manifest["files"])


def test_cached_pcb_schematic_artifact_lookup_sanitizes_filename() -> None:
    from backend.shared.python_utils.pcb_schematic_artifacts import get_cached_pcb_schematic_artifact

    record = {
        "compile_id": "compile-123",
        "artifacts": [
            {
                "id": "artifact-1",
                "name": 'board".kicad_pcb',
                "content": "kicad board content",
            }
        ],
    }

    assert get_cached_pcb_schematic_artifact(record, "artifact-1") == (
        "board.kicad_pcb",
        b"kicad board content",
    )
    assert get_cached_pcb_schematic_artifact(record, "missing") is None
