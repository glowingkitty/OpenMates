# backend/apps/models3d/preview.py
#
# Bounded glTF Transform wrapper for the interactive fullscreen model. The
# provider master remains immutable; this derivative is Meshopt/WebP optimized
# and stored separately so chat never loads it automatically.

from __future__ import annotations

import subprocess
import tempfile
from pathlib import Path
from typing import Callable

from backend.shared.providers.hi3d.client import Hi3DClient, Hi3DProviderError


MAX_PREVIEW_BYTES = 25 * 1024 * 1024
PREVIEW_TIMEOUT_SECONDS = 180


class ModelPreviewOptimizationError(RuntimeError):
    """A safe failure while deriving a bounded interactive model preview."""


def optimize_preview_glb(
    master_glb: bytes,
    *,
    run: Callable[..., subprocess.CompletedProcess[bytes]] = subprocess.run,
) -> bytes:
    """Create a Meshopt/WebP GLB derivative without changing the master."""
    if not master_glb:
        raise ModelPreviewOptimizationError("Model master is empty")
    try:
        Hi3DClient._validate_glb(master_glb)
    except Hi3DProviderError as exc:
        raise ModelPreviewOptimizationError("Model master is invalid") from exc

    with tempfile.TemporaryDirectory(prefix="openmates-model3d-") as directory:
        source = Path(directory) / "master.glb"
        preview = Path(directory) / "preview.glb"
        source.write_bytes(master_glb)
        try:
            completed = run(
                [
                    "gltf-transform",
                    "optimize",
                    str(source),
                    str(preview),
                    "--compress",
                    "meshopt",
                    "--texture-compress",
                    "webp",
                ],
                check=False,
                capture_output=True,
                timeout=PREVIEW_TIMEOUT_SECONDS,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise ModelPreviewOptimizationError("Interactive model preview optimization failed") from exc
        if completed.returncode != 0 or not preview.is_file():
            raise ModelPreviewOptimizationError("Interactive model preview optimization failed")
        optimized = preview.read_bytes()

    if not optimized or len(optimized) > MAX_PREVIEW_BYTES:
        raise ModelPreviewOptimizationError("Interactive model preview exceeds the configured size limit")
    try:
        Hi3DClient._validate_glb(optimized)
    except Hi3DProviderError as exc:
        raise ModelPreviewOptimizationError("Interactive model preview is invalid") from exc
    return optimized
