# contract-test-file: infrastructure
"""Check the pinned Directus schema-cache behavior without starting CMS or a database."""

from pathlib import Path
import os
import re
import subprocess
import uuid

import pytest


ROOT = Path(__file__).resolve().parents[2]
DOCKERFILE = ROOT / "backend/core/directus/Dockerfile"
NODE_TEST = ROOT / "backend/tests/fixtures/directus-schema-freeze-cache.test.mjs"
VENDOR_FILES = {
    "/directus/node_modules/@directus/api/dist/permissions/cache.js":
        "852e1c349365aa38a66af6b0c9e3ce509fe1b12f8ffc05558afbb0828ec13d48",
    "/directus/node_modules/@directus/api/dist/permissions/modules/validate-access/validate-access.js":
        "529cbd20b1b9a14b6e81b1126bb3ec98900a2d730032b6d538cce6267b07cf53",
    "/directus/node_modules/@directus/api/dist/bus/index.js":
        "99c564a836c7177e6d5b8e5a6799751d611f9e3d6b25e76cf28463bd26ed2532",
    "/directus/node_modules/@directus/api/dist/services/schema.js":
        "3282a026c744a43552e1e5c5bc1d61da845ac32704dd1fc5147c12bc9410d90d",
    "/directus/node_modules/@directus/api/dist/utils/get-snapshot.js":
        "d47a51791cc7a339e5c8632e67019082ee5f6764e4321c1b147b4ea831a15a43",
    "/directus/node_modules/@directus/api/dist/utils/apply-diff.js":
        "c668fad22c9c7d37ee9a67c3ed72accb3327ededd105080d961e9fe0300df1b2",
    "/directus/node_modules/@directus/api/dist/utils/apply-snapshot.js":
        "79b26641d1fd2601a4244de72435a7bfbc4c76909f0f7bd8835c11602afe5d32",
    "/directus/node_modules/@directus/api/dist/cache.js":
        "e99133a250f3d7f5705fc0791cc7e3fe3ece8bd3ad5e80c1f32ce238b0c4c16c",
    "/directus/node_modules/@directus/api/dist/utils/freeze-schema.js":
        "fd1b4ae5dcfce78c8e949b08598ac17e73003e8a2a7161604a9da3a2d7ec61e1",
    "/directus/node_modules/@directus/api/dist/utils/get-schema.js":
        "43b1d2ecf30fd0a3492bdcfb0bdb8448f076c86e05ef80c912fea7b169aa9d8a",
}


def _run_isolated_container(options: list[str], *, timeout: int) -> subprocess.CompletedProcess[str]:
    name = f"openmates-schema-freeze-{os.getpid()}-{uuid.uuid4().hex[:12]}"
    original_error: BaseException | None = None
    try:
        return subprocess.run(
            ["docker", "run", "--name", name, "--rm", "--pull", "never", "--network", "none",
             "--read-only", *options],
            capture_output=True, text=True, timeout=timeout, check=False,
        )
    except BaseException as error:
        original_error = error
        raise
    finally:
        try:
            cleanup = subprocess.run(
                ["docker", "rm", "-f", name],
                capture_output=True, text=True, timeout=10, check=False,
            )
            if (original_error is None and cleanup.returncode != 0
                    and "No such container" not in cleanup.stderr):
                raise RuntimeError("isolated_container_cleanup_failed")
        except (OSError, subprocess.TimeoutExpired):
            if original_error is None:
                raise


@pytest.fixture(scope="module")
def pinned_image() -> str:
    match = re.search(
        r"^FROM (directus/directus:11\.5@sha256:[0-9a-f]{64})$",
        DOCKERFILE.read_text(),
        re.MULTILINE,
    )
    assert match, "The CMS base image must stay pinned for this source-bound test"
    return match.group(1)


def test_vendor_source_matches_profiled_cms(pinned_image: str) -> None:
    result = _run_isolated_container(
        ["--entrypoint", "sha256sum", pinned_image, *VENDOR_FILES], timeout=60,
    )
    assert result.returncode == 0, f"Vendor source check failed: {result.stderr[-1000:]}"
    observed = {
        path: digest
        for line in result.stdout.splitlines()
        for digest, path in [line.split(None, 1)]
    }
    assert observed == VENDOR_FILES


@pytest.mark.parametrize("freeze_enabled", ["true", "false"])
def test_directus_schema_cache_in_isolated_node(
    pinned_image: str, freeze_enabled: str,
) -> None:
    result = _run_isolated_container(
        ["--cap-drop", "ALL", "--security-opt", "no-new-privileges",
         "--pids-limit", "64", "--memory", "512m", "--user", "1000:1000",
         "--tmpfs", "/tmp:rw,nosuid,size=16m,mode=1777",
         "--env", "PM2_HOME=/tmp/.pm2",
         "--env", f"CACHE_SCHEMA_FREEZE_ENABLED={freeze_enabled}",
         "--volume", f"{NODE_TEST}:/probe/schema-freeze-cache.test.mjs:ro",
         "--entrypoint", "node", pinned_image,
         "--test", "/probe/schema-freeze-cache.test.mjs"],
        timeout=30,
    )
    assert result.returncode == 0, (
        f"Pinned Directus cache test failed with freeze={freeze_enabled}: "
        f"{result.stdout[-2000:]} {result.stderr[-1000:]}"
    )


def test_isolated_container_cleanup_after_timeout_and_error(monkeypatch: pytest.MonkeyPatch) -> None:
    for failure in ("timeout", "error"):
        commands: list[list[str]] = []

        def fake_run(command: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
            commands.append(command)
            if command[1] == "run":
                if failure == "timeout":
                    raise subprocess.TimeoutExpired(command, kwargs["timeout"])
                return subprocess.CompletedProcess(command, 19, "", "synthetic failure")
            return subprocess.CompletedProcess(command, 0, "", "")

        monkeypatch.setattr(subprocess, "run", fake_run)
        if failure == "timeout":
            with pytest.raises(subprocess.TimeoutExpired):
                _run_isolated_container(["synthetic-image"], timeout=1)
        else:
            assert _run_isolated_container(["synthetic-image"], timeout=1).returncode == 19
        assert len(commands) == 2
        assert commands[0][1:4] == ["run", "--name", commands[1][-1]]
        assert commands[1][1:3] == ["rm", "-f"]
