#!/usr/bin/env python3
"""Validate the checked-in media writer rollout gate.

The audit is deterministic and read-only. It rejects malformed or premature R2
activation before any writer reads the manifest, while legacy writer mode stays
valid until all pinned R1 reader evidence and the rollback floor are recorded.
"""

from __future__ import annotations

import argparse
from pathlib import Path
import sys
from typing import Any, Mapping

import yaml

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MANIFEST = ROOT / "config/media_encryption_rollout.yml"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.shared.python_utils.media_encryption import validate_rollout_manifest  # noqa: E402


PACKAGING_CONTRACTS = {
    "backend/upload/Dockerfile": (
        "COPY config/media_encryption_rollout.yml /app/config/media_encryption_rollout.yml",
        "COPY backend/shared/python_utils/media_encryption.py /app/backend/shared/python_utils/media_encryption.py",
    ),
    "backend/core/api/Dockerfile": (
        "COPY config/media_encryption_rollout.yml /app/config/media_encryption_rollout.yml",
    ),
    "backend/core/api/Dockerfile.selfhost": (
        "COPY config/media_encryption_rollout.yml /app/config/media_encryption_rollout.yml",
    ),
    "backend/core/docker-compose.yml": (
        "../../config/media_encryption_rollout.yml:/app/config/media_encryption_rollout.yml:ro",
    ),
    ".github/workflows/publish-selfhost-images.yml": (
        "config/media_encryption_rollout.yml",
    ),
}

MEDIA_WRITER_COMPOSE_SERVICES = (
    "app-code-worker",
    "app-images-worker",
    "app-music-worker",
    "app-videos-worker",
)
COMPOSE_ROLLOUT_MOUNT = "../../config/media_encryption_rollout.yml:/app/config/media_encryption_rollout.yml:ro"


def load_manifest(path: Path) -> Mapping[str, Any]:
    manifest = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(manifest, Mapping):
        raise ValueError("media rollout manifest is invalid")
    return manifest


def validate_rollout_packaging(root: Path = ROOT) -> None:
    """Ensure every writer runtime receives the same checked-in manifest."""
    for relative_path, required_texts in PACKAGING_CONTRACTS.items():
        content = (root / relative_path).read_text(encoding="utf-8")
        for required_text in required_texts:
            if required_text not in content:
                raise ValueError(f"media rollout packaging is missing from {relative_path}")
    compose = yaml.safe_load((root / "backend/core/docker-compose.yml").read_text(encoding="utf-8"))
    services = compose.get("services") if isinstance(compose, Mapping) else None
    if not isinstance(services, Mapping):
        raise ValueError("backend/core/docker-compose.yml services are invalid")
    for service_name in MEDIA_WRITER_COMPOSE_SERVICES:
        service = services.get(service_name)
        volumes = service.get("volumes") if isinstance(service, Mapping) else None
        if not isinstance(volumes, list) or COMPOSE_ROLLOUT_MOUNT not in volumes:
            raise ValueError(f"media rollout packaging is missing from backend/core/docker-compose.yml service {service_name}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    args = parser.parse_args()
    validate_rollout_manifest(load_manifest(args.manifest))
    validate_rollout_packaging()
    print(f"PASS media encryption rollout: {args.manifest}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
