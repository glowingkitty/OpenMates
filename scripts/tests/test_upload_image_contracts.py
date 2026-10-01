#!/usr/bin/env python3
# contract-test-file: infrastructure
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


def test_upload_service_only_imports_packaged_shared_modules() -> None:
    upload_files = (PROJECT_ROOT / "backend" / "upload").rglob("*.py")
    dockerfile = (PROJECT_ROOT / "backend" / "upload" / "Dockerfile").read_text(encoding="utf-8")
    # These pure utilities carry no core service credentials or dependencies.
    allowed = {
        "backend.shared.python_utils.media_encryption",
        "backend.shared.python_utils.object_storage_regions",
    }
    imported = set()
    for path in upload_files:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module and node.module.startswith("backend.shared"):
                imported.add(node.module)
            elif isinstance(node, ast.Import):
                imported.update(alias.name for alias in node.names if alias.name.startswith("backend.shared"))

    assert imported <= allowed, f"Unapproved core dependency in upload image: {imported - allowed}"
    for module in imported:
        source = module.replace(".", "/") + ".py"
        assert f"COPY {source} /app/{source}" in dockerfile, f"Shared upload dependency is not packaged: {module}"


def test_upload_image_imports_its_entry_point_during_build() -> None:
    dockerfile = (PROJECT_ROOT / "backend" / "upload" / "Dockerfile").read_text(encoding="utf-8")
    assert 'RUN python -c "import backend.upload.main; import backend.scripts.runtime_health_verifier"' in dockerfile


def test_upload_image_packages_verifier_shared_imports() -> None:
    dockerfile = (PROJECT_ROOT / "backend" / "upload" / "Dockerfile").read_text(encoding="utf-8")
    verifier = PROJECT_ROOT / "backend" / "scripts" / "runtime_health_verifier.py"
    tree = ast.parse(verifier.read_text(encoding="utf-8"), filename=str(verifier))
    shared_imports = {
        node.module
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom)
        and node.module
        and node.module.startswith("backend.shared")
    }
    for module in shared_imports:
        source = module.replace(".", "/") + ".py"
        assert f"COPY {source} /app/{source}" in dockerfile, f"Upload verifier dependency is not packaged: {module}"


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
