# backend/tests/test_upload_image_pdf_triage.py
#
# The upload microservice runs from its own minimal image. Its PDF route imports the triage module
# lazily, so a missing COPY only shows up when the first PDF is uploaded. This guards the image
# recipe: every backend.apps module the upload code imports must be copied into the image and be
# exercised by the build-time import check.
# Specification: feature.pdf-processing (examples pricing).

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DOCKERFILE = (ROOT / "backend/upload/Dockerfile").read_text()


def _backend_apps_imports() -> set[str]:
    modules: set[str] = set()
    for path in (ROOT / "backend/upload").rglob("*.py"):
        modules.update(re.findall(r"^\s*(?:from|import)\s+(backend\.apps[\w.]*)", path.read_text(), re.M))
    return modules


# contract-test: supporting surface=rest_api assertions=pdf-processing.billing.exact-price
def test_every_backend_apps_module_the_upload_service_imports_is_in_its_image():
    modules = _backend_apps_imports()
    assert "backend.apps.pdf.services.pdf_triage" in modules  # the lazy import this guards
    for module in modules:
        source = module.replace(".", "/") + ".py"
        assert (ROOT / source).exists(), f"{module} does not exist"
        assert f"COPY {source} /app/{source}" in DOCKERFILE, f"{source} is not copied into the upload image"


# contract-test: supporting surface=rest_api assertions=pdf-processing.billing.exact-price
def test_image_build_runs_the_triage_before_publishing():
    assert "from backend.apps.pdf.services.pdf_triage import price_for, triage_pages_sync" in DOCKERFILE
    assert "triage_pages_sync(d.tobytes())" in DOCKERFILE
