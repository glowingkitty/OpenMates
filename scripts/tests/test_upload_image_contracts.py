#!/usr/bin/env python3
"""
Regression tests for upload-server image packaging contracts.

The upload service image has a shell startup gate before Uvicorn starts. These
tests keep the Dockerfile and startup script aligned so published GHCR images do
not boot-loop on the isolated upload VM.

Architecture: docs/architecture/infrastructure/file-upload-pipeline.md
"""

from __future__ import annotations

import ast
import re
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]


def test_upload_image_installs_tools_required_by_startup_script() -> None:
    dockerfile = (PROJECT_ROOT / "backend" / "upload" / "Dockerfile").read_text(encoding="utf-8")
    startup_script = (PROJECT_ROOT / "backend" / "upload" / "vault" / "wait-for-vault.sh").read_text(
        encoding="utf-8"
    )

    assert "curl" in startup_script
    assert "curl" in dockerfile


def test_upload_service_does_not_import_core_backend_shared_modules() -> None:
    upload_files = (PROJECT_ROOT / "backend" / "upload").rglob("*.py")

    offenders = []
    for path in upload_files:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        imports_backend_shared = any(
            (
                isinstance(node, ast.ImportFrom)
                and node.module is not None
                and node.module.startswith("backend.shared")
            )
            or (
                isinstance(node, ast.Import)
                and any(alias.name.startswith("backend.shared") for alias in node.names)
            )
            for node in ast.walk(tree)
        )
        if imports_backend_shared:
            offenders.append(str(path.relative_to(PROJECT_ROOT)))

    assert offenders == []


def test_sightengine_http_client_accepts_provider_category() -> None:
    service_path = PROJECT_ROOT / "backend" / "upload" / "services" / "sightengine_service.py"
    module = ast.parse(service_path.read_text(encoding="utf-8"), filename=str(service_path))
    function = next(
        node
        for node in module.body
        if isinstance(node, ast.FunctionDef) and node.name == "create_http_client"
    )

    positional_args = [arg.arg for arg in function.args.args]
    assert positional_args[:1] == ["_category"]


def test_duplicate_images_with_failed_ai_detection_are_refreshed() -> None:
    route_source = (PROJECT_ROOT / "backend" / "upload" / "routes" / "upload_route.py").read_text(
        encoding="utf-8"
    )

    assert "def _duplicate_ai_detection_needs_refresh" in route_source
    assert 'ai_detection.get("status") == "failed"' in route_source
    assert "Duplicate has missing/failed AI metadata" in route_source
    assert "await sightengine.check_all(" in route_source


def test_image_authenticity_badge_collapsed_state_is_square() -> None:
    component = (
        PROJECT_ROOT
        / "frontend"
        / "packages"
        / "ui"
        / "src"
        / "components"
        / "embeds"
        / "images"
        / "ImageAuthenticityBadge.svelte"
    ).read_text(encoding="utf-8")

    assert re.search(r"^\s+width: 28px;$", component, re.MULTILINE)
    assert re.search(r"^\s+height: 28px;$", component, re.MULTILINE)
    assert ".authenticity-badge.fullscreen" in component
    assert re.search(r"^\s+height: 32px;$", component, re.MULTILINE)
    assert re.search(r"^\s+height: auto;$", component, re.MULTILINE)
