# contract-test-file: infrastructure
"""Every supported worker image must load release gates without host script mounts."""
from pathlib import Path
import os
import shlex
import shutil
import subprocess
import sys

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]


def copied_source(dockerfile: Path, destination: str) -> Path:
    for line in dockerfile.read_text().splitlines():
        if not line.startswith("COPY "):
            continue
        args = shlex.split(line)[1:]
        if len(args) != 2 or args[0].startswith("--"):
            continue
        source, target = args
        if destination == target or destination.startswith(target.rstrip("/") + "/"):
            suffix = destination[len(target):].lstrip("/")
            return ROOT / source / suffix if suffix else ROOT / source
    raise AssertionError(f"{dockerfile.name} does not package {destination}")


@pytest.mark.parametrize("name", ["Dockerfile", "Dockerfile.selfhost", "Dockerfile.celery"])
def test_supported_worker_images_ship_rollout_imports_trust_and_explicit_provenance(name, tmp_path):
    dockerfile = ROOT / "backend/core/api" / name
    text = dockerfile.read_text()
    assert 'ARG BUILD_COMMIT_SHA=""' in text
    assert "ENV BUILD_COMMIT_SHA=${BUILD_COMMIT_SHA}" in text
    for target in ("/app/scripts/storage_rollout.py", "/app/scripts/storage_runtime_inventory.py",
                   "/app/backend/shared/python_utils/storage_archive_rollout_config.py",
                   "/app/backend/shared/config/storage_rollout_release_public_key.json",
                   "/app/backend/core/api/app/tasks/storage_rollout_tasks.py"):
        assert copied_source(dockerfile, target).is_file()
    scripts = tmp_path / "scripts"
    scripts.mkdir()
    shutil.copyfile(copied_source(dockerfile, "/app/scripts/storage_rollout.py"), scripts / "storage_rollout.py")
    # Import from the projected image layout with no repository working directory
    # or inherited PYTHONPATH. Empty provenance cannot authorize a deployment.
    code = """from scripts.storage_rollout import automatic_tick, source_commit
assert callable(automatic_tick)
assert source_commit({'BUILD_COMMIT_SHA': 'a' * 40}) == 'a' * 40
try:
    source_commit({})
except ValueError:
    pass
else:
    raise AssertionError('missing provenance accepted')
"""
    result = subprocess.run([sys.executable, "-c", code], cwd=tmp_path,
                            env={**os.environ, "PYTHONPATH": str(tmp_path)},
                            capture_output=True, text=True)
    assert result.returncode == 0, result.stderr


def test_all_legacy_celery_services_build_complete_repository_layout_without_volume_changes():
    compose_path = ROOT / "backend/core/docker-compose.yml"
    compose = yaml.safe_load(compose_path.read_text())
    workers = [service for service in compose["services"].values()
               if service.get("build", {}).get("dockerfile", "").endswith("Dockerfile.celery")]
    assert len(workers) == 10
    for worker in workers:
        build = worker["build"]
        context = (compose_path.parent / build["context"]).resolve()
        assert context == ROOT
        assert (context / build["dockerfile"]).is_file()
        assert "../../backend:/app/backend" in worker.get("volumes", [])
    text = (ROOT / "backend/core/api/Dockerfile.celery").read_text()
    assert "USER celeryuser" in text
    assert '"backend.core.api.app.tasks.celery_config"' in text
    assert "COPY . /app/" not in text
