# contract-test-file: tooling
"""End-to-end engineering checks with actual service/client subprocesses.

Only a private temporary capacity sensor is synthetic; no shared disk is filled,
no account is used, and cleanup touches only a fixture-owned disposable file.
"""

import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time
import uuid
import pytest

from scripts.disk_coordinator import Coordinator, group_alive

ROOT = Path(__file__).resolve().parents[2]
GIB = 1024**3


def until(predicate, timeout=10):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        result = predicate()
        if result:
            return result
        time.sleep(0.05)
    raise AssertionError("isolated disk protocol did not converge")


def launch(code, *args):
    environment = {**os.environ, "CODEX_THREAD_ID": "", "PYTHONPATH": str(ROOT)}
    return subprocess.Popen(
        [sys.executable, "-c", code, *map(str, args)],
        cwd=ROOT,
        env=environment,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )


def stop(process):
    if process.poll() is None:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)


def test_service_wait_cleanup_recovery_and_restart_preserve_durable_ticket(tmp_path):
    repository = tmp_path / "repo"
    repository.mkdir()
    sensor = tmp_path / "sensor.json"
    sensor.write_text(json.dumps({"free": 10 * GIB, "used": 90 * GIB}))
    disposable = repository / "disposable-cache"
    disposable.write_bytes(b"fixture cache")
    coordinator = Coordinator(tmp_path / "host")
    coordinator.register(repository, maintenance=("managed",))
    service = """import json,sys,time
from pathlib import Path
from collections import namedtuple
from scripts.disk_coordinator import Coordinator
sensor=Path(sys.argv[2]); root=Path(sys.argv[3]); Usage=namedtuple('Usage','total used free')
def usage(_):
 x=json.loads(sensor.read_text()); return Usage(100*1024**3,x['used'],x['free'])
def clean(*_):
 if (root/'allow-cleanup').exists():
  (root/'disposable-cache').unlink(missing_ok=True)
  sensor.write_text(json.dumps({'free':50*1024**3,'used':50*1024**3}))
 return {'fixture_cleanup':True}
c=Coordinator(sys.argv[1],usage=usage)
with c.leadership():
 while True: c.tick(cleaner=clean); time.sleep(.05)
"""
    process = launch(service, coordinator.root, sensor, repository)
    try:
        until(coordinator.available)
        thread = str(uuid.uuid4())
        client = launch(
            """import sys
from pathlib import Path
from scripts.resource_budget import reserve
from scripts.disk_coordinator import DiskWait
try:
 with reserve(Path(sys.argv[1]),1024**3,operation='integration-build',thread=sys.argv[2]):
  raise AssertionError('low-capacity request was admitted')
except DiskWait as wait: print(wait.request['id'],flush=True)
""",
            repository,
            thread,
        )
        output, error = client.communicate(timeout=10)
        assert client.returncode == 0, error
        request_id = output.strip()
        assert coordinator.get(request_id)["state"] == "waiting"
        assert disposable.exists()
        stop(process)
        assert coordinator.get(request_id)["state"] == "waiting"
        # Reboot/restart recovery uses the same ledger; capacity recovery is an
        # isolated sensor transition, never real host disk consumption.
        (repository / "allow-cleanup").write_text("fixture cleanup authorized")
        with coordinator.db(write=True) as db:
            db.execute("UPDATE pressure SET next_cleanup=0")
        process = launch(service, coordinator.root, sensor, repository)
        until(coordinator.available)
        grant = until(
            lambda: (
                r if (r := coordinator.get(request_id))["state"] == "granted" else None
            )
        )
        assert not disposable.exists()
        assert coordinator.valid_grant(request_id, grant["grant_id"])
        retried = coordinator.request(
            repository, GIB, operation="integration-build", thread=thread
        )
        assert retried["id"] == request_id
        # Both processes observe one persistent reservation, never a new ticket.
        assert len(coordinator.requests(repository)) == 1
    finally:
        stop(process)


def test_wrapper_crash_keeps_live_child_group_reservation(tmp_path):
    repository = tmp_path / "repo"
    repository.mkdir()
    coordinator = Coordinator(tmp_path / "host")
    coordinator.register(repository, maintenance=())
    service = launch(
        """import sys,time
from collections import namedtuple
from scripts.disk_coordinator import Coordinator
U=namedtuple('Usage','total used free'); c=Coordinator(sys.argv[1],usage=lambda _:U(100*1024**3,50*1024**3,50*1024**3))
with c.leadership():
 while True: c.tick(); time.sleep(.05)
""",
        coordinator.root,
    )
    wrapper = None
    child_group = None
    try:
        until(coordinator.available)
        wrapper = launch(
            """import sys,shutil
from collections import namedtuple
from pathlib import Path
from scripts.disk_coordinator import run_command
U=namedtuple('Usage','total used free')
shutil.disk_usage=lambda _:U(100*1024**3,50*1024**3,50*1024**3)
raise SystemExit(run_command(Path(sys.argv[1]),1024**2,'owned-process',[sys.executable,'-c','import time; time.sleep(60)']))
""",
            repository,
        )

        def child_owned():
            if wrapper.poll() is not None:
                raise AssertionError(wrapper.communicate()[1])
            return next(
                (
                    r
                    for r in coordinator.requests(repository)
                    if r["state"] == "claimed" and r["owner_group"]
                ),
                None,
            )

        row = until(child_owned)
        child_group = row["owner_group"]
        assert group_alive(child_group)
        wrapper.kill()
        wrapper.wait(timeout=5)
        time.sleep(0.15)
        assert coordinator.get(row["id"])["state"] == "claimed"
        assert coordinator.get(row["id"])["outstanding"] == 1024**2
        os.killpg(child_group, signal.SIGKILL)
        until(lambda: coordinator.get(row["id"])["state"] == "complete")
    finally:
        if child_group and group_alive(child_group):
            os.killpg(child_group, signal.SIGKILL)
        if wrapper:
            stop(wrapper)
        stop(service)


def test_linked_worktree_and_canonical_checkout_share_the_same_host_marker(tmp_path):
    repository = tmp_path / "repo"
    repository.mkdir()

    def git(*args):
        return subprocess.check_output(
            ["git", "-C", str(repository), *args], text=True
        ).strip()

    git("init", "--quiet")
    git("config", "user.email", "fixture@example.test")
    git("config", "user.name", "Fixture")
    (repository / "source").write_text("source")
    git("add", "source")
    git("commit", "-qm", "isolated fixture")
    worktree = tmp_path / "linked"
    git("worktree", "add", "--detach", str(worktree))
    coordinator = Coordinator(tmp_path / "host")
    coordinator.register(repository, maintenance=())
    from scripts.disk_coordinator import configured

    assert configured(worktree).root == coordinator.root
    first = coordinator.request(
        worktree, 1, operation="shared", thread=str(uuid.uuid4())
    )
    assert coordinator.requests(repository)[0]["id"] == first["id"]
    assert first["repository"] == str(repository)


@pytest.mark.parametrize("script", ["docker-cleanup.sh", "cleanup-proof-videos.sh"])
def test_corrupt_coordinator_state_cannot_fall_back_to_independent_cleanup(
    tmp_path, script
):
    repository = tmp_path / "repo"
    scripts = repository / "scripts"
    scripts.mkdir(parents=True)
    copied = scripts / script
    copied.write_text((ROOT / "scripts" / script).read_text())
    stub_dir = tmp_path / "bin"
    stub_dir.mkdir()
    sentinel = tmp_path / "independent-cleanup-ran"
    probe = stub_dir / "python3"
    probe.write_text("#!/usr/bin/python3\nimport sys\nraise SystemExit(1)\n")
    probe.chmod(0o755)
    docker = stub_dir / "docker"
    docker.write_text(
        f"#!/usr/bin/python3\nfrom pathlib import Path\nPath({str(sentinel)!r}).touch()\n"
    )
    docker.chmod(0o755)
    result = subprocess.run(
        ["bash", str(copied)],
        capture_output=True,
        text=True,
        env={**os.environ, "PATH": str(stub_dir) + os.pathsep + os.environ["PATH"]},
    )
    assert result.returncode == 1
    assert "refusing independent cleanup" in result.stderr
    assert not sentinel.exists()
