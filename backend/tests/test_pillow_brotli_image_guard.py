"""Every image that installs Pillow wheels must replace their bundled Brotli decoder.

Pillow 13.0.0 wheels bundle libbrotlidec 1.2.0 without the upstream 1.2.1
memory-corruption fix. backend/core/api/docker/replace_pillow_brotli.py swaps it
for the patched Debian decoder and verifies what FreeType loads at build time.
"""

# contract-test-file: infrastructure

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
PILLOW_IMAGES = {
    "backend/core/api/Dockerfile": "backend/core/api/requirements.txt",
    "backend/core/api/Dockerfile.celery": "backend/core/api/requirements.txt",
    "backend/core/api/Dockerfile.selfhost": "backend/core/api/requirements.txt",
    "backend/core/api/Dockerfile.docs": "backend/core/api/requirements.txt",
    "backend/upload/Dockerfile": "backend/upload/requirements.txt",
    "backend/preview/Dockerfile": "backend/preview/requirements.txt",
}
PILLOW_REQUIREMENT = re.compile(r"^pillow\b", re.IGNORECASE | re.MULTILINE)


def test_known_pillow_images_cover_every_pillow_requirements_file() -> None:
    pillow_requirements = {
        str(path.relative_to(REPO_ROOT))
        for path in (REPO_ROOT / "backend").glob("**/requirements.txt")
        if "tests" not in path.parts and PILLOW_REQUIREMENT.search(path.read_text())
    }
    # The PDF app's requirements are installed through the core API image.
    pillow_requirements.discard("backend/apps/pdf/requirements.txt")
    assert pillow_requirements == set(PILLOW_IMAGES.values())


def test_pillow_images_replace_bundled_brotli_after_pip_install() -> None:
    for dockerfile, requirements in PILLOW_IMAGES.items():
        assert PILLOW_REQUIREMENT.search((REPO_ROOT / requirements).read_text()), requirements
        text = (REPO_ROOT / dockerfile).read_text()
        assert "libbrotli1" in text, f"{dockerfile} must install the patched system Brotli"
        pip_install = text.index("pip install --no-cache-dir -r")
        replacement = text.find("RUN python /tmp/replace_pillow_brotli.py")
        assert replacement > pip_install, f"{dockerfile} must replace Pillow's Brotli after pip install"
