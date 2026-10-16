# contract-test-file: infrastructure
"""Resolve real Compose commands, then prove one bounded Celery invocation."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
QUEUES = {
    "task-worker": "email", "user-init-worker": "user_init",
    "core-worker": "persistence,health_check,server_stats,demo,e2e_tests,push,leaderboard",
    "user-tasks-worker": "user_tasks", "reminder-worker": "reminder", "workflow-worker": "workflow",
    "app-ai-worker": "app_ai", "app-images-worker": "app_images", "app-music-worker": "app_music",
    "app-videos-worker": "app_videos", "app-pdf-worker": "app_pdf", "app-docs-worker": "app_docs",
    "app-code-worker": "app_code", "app-social-media-worker": "app_social_media",
    "task-scheduler": None,
}


@pytest.fixture(scope="module")
def resolved_commands(tmp_path_factory):
    if not shutil.which("docker"):
        pytest.skip("Docker Compose is required for command resolution")
    directory = tmp_path_factory.mktemp("celery-compose-resolution")
    services = yaml.safe_load((ROOT / "backend/core/docker-compose.yml").read_text())["services"]
    # Keep only commands and synthetic settings: no real env files, mounts,
    # service dependencies, provider credentials or running Docker services.
    fixture = {"services": {name: {"image": "example.invalid/unused:proof",
        "command": services[name]["command"], "environment": {"CELERY_AUTOSCALE_MAX": "2"}}
        for name in QUEUES}}
    path = directory / "compose.yml"
    path.write_text(yaml.safe_dump(fixture))
    result = subprocess.run(["docker", "compose", "-p", "storage-command-proof", "-f", str(path),
                             "config", "--format", "json"],
                            env={**os.environ, "CELERY_AUTOSCALE_MAX": "2", "CELERY_VIDEOS_AUTOSCALE_MAX": "2"},
                            capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stderr
    resolved = json.loads(result.stdout)["services"]
    # Compose config re-escapes every dollar for reusable serialization. Undo
    # only that presentation step to execute the actual resolved engine argv:
    # https://github.com/docker/compose/blob/v2.34.0/cmd/compose/config.go#L154
    for service in resolved.values():
        service["command"] = [argument.replace("$$", "$") for argument in service["command"]]
    return resolved


@pytest.mark.parametrize("name", QUEUES)
def test_resolved_shell_passes_every_execution_bound_to_one_celery_process(name, resolved_commands, tmp_path):
    command = resolved_commands[name]["command"]
    assert command[:2] == ["sh", "-c"] and len(command) == 3
    executable_dir = tmp_path / "bin"
    executable_dir.mkdir()
    for operation in ("chown", "mkdir", "chmod", "find"):
        stub = executable_dir / operation
        stub.write_text("#!/bin/sh\nexit 0\n")
        stub.chmod(0o700)
    gosu = executable_dir / "gosu"
    gosu.write_text('#!/bin/sh\ntest "$1" = celeryuser || exit 91\nshift\nexec "$@"\n')
    gosu.chmod(0o700)
    python = executable_dir / "python"
    python.write_text(f"#!{sys.executable}\nimport json, sys\nprint(json.dumps(sys.argv[1:]))\n")
    python.chmod(0o700)
    result = subprocess.run(["/bin/sh", *command[1:]],
        env={"PATH": str(executable_dir), "CELERY_AUTOSCALE_MAX": "2"},
        capture_output=True, text=True, timeout=10)
    assert result.returncode == 0, result.stderr
    lines = result.stdout.splitlines()
    assert len(lines) == 1, "A worker command must execute Celery exactly once"
    argv = json.loads(lines[0])
    mode = "beat" if name == "task-scheduler" else "worker"
    assert argv[:5] == ["-m", "celery", "-A", "backend.core.api.app.tasks.celery_config", mode]
    flags = dict(flag[2:].split("=", 1) for flag in argv[5:])
    if name == "task-scheduler":
        assert flags == {"loglevel": "info", "schedule": "/celerybeat-data/celerybeat-schedule"}
    else:
        tasks = 10 if name in {"app-videos-worker", "app-pdf-worker", "app-docs-worker"} else 20 if name in {"app-music-worker", "app-code-worker"} else 50
        memory = 1000000 if name in {"app-videos-worker", "app-pdf-worker", "app-docs-worker"} else 600000
        assert flags == {"loglevel": "info", "queues": QUEUES[name], "concurrency": "2",
                         "max-tasks-per-child": str(tasks), "max-memory-per-child": str(memory),
                         "prefetch-multiplier": "1"}
