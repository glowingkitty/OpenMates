# backend/tests/test_models3d_preview.py
#
# Tests for the bounded local GLB preview optimizer. These run with a fake CLI
# process and prove that only valid, size-limited Meshopt/WebP derivatives can
# reach encrypted storage.

from __future__ import annotations

import json
import struct
import subprocess
from pathlib import Path

import pytest

from backend.apps.models3d.preview import MAX_PREVIEW_BYTES, ModelPreviewOptimizationError, optimize_preview_glb


def _glb() -> bytes:
    document = json.dumps({"asset": {"version": "2.0"}}).encode("utf-8")
    document += b" " * (-len(document) % 4)
    total_length = 12 + 8 + len(document)
    return b"glTF" + struct.pack("<II", 2, total_length) + struct.pack("<I4s", len(document), b"JSON") + document


def test_optimizes_master_with_meshopt_and_webp() -> None:
    master = _glb()
    command: list[str] = []

    def fake_run(args: list[str], **_kwargs: object) -> subprocess.CompletedProcess[bytes]:
        command.extend(args)
        Path(args[3]).write_bytes(master)
        return subprocess.CompletedProcess(args, 0, b"", b"")

    assert optimize_preview_glb(master, run=fake_run) == master
    assert command[:2] == ["gltf-transform", "optimize"]
    assert "--compress" in command and command[command.index("--compress") + 1] == "meshopt"
    assert "--texture-compress" in command and command[command.index("--texture-compress") + 1] == "webp"


def test_rejects_failed_or_oversized_preview() -> None:
    master = _glb()

    def failed_run(args: list[str], **_kwargs: object) -> subprocess.CompletedProcess[bytes]:
        return subprocess.CompletedProcess(args, 1, b"", b"failed")

    with pytest.raises(ModelPreviewOptimizationError, match="optimization failed"):
        optimize_preview_glb(master, run=failed_run)

    def oversized_run(args: list[str], **_kwargs: object) -> subprocess.CompletedProcess[bytes]:
        Path(args[3]).write_bytes(b"glTF" + b"x" * MAX_PREVIEW_BYTES)
        return subprocess.CompletedProcess(args, 0, b"", b"")

    with pytest.raises(ModelPreviewOptimizationError, match="size limit"):
        optimize_preview_glb(master, run=oversized_run)
