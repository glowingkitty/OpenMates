# contract-test-file: tooling
"""Apple CI rounds: the macOS cap and build once, test many (ci_coordinator.py, ci_apple.py).

The coordinator holds Apple jobs beyond GitHub's 5 macOS slots undispatched, and one
owner's unit/UI jobs on one source test the first Xcode job's build products. No requests
are sent; GitHub is a deterministic fake.
"""

import json
import subprocess
import time
from pathlib import Path

import pytest

from scripts import ci_apple
from scripts.ci_coordinator import GitHub, Queue

SOURCE = "a" * 40


class Remote:
    def __init__(self):
        self.sent = []
        self.visible = []
        self.artifacts = set()

    def budget(self):
        return {"remaining": 5000, "reset": 500}

    def runs(self):
        return self.visible

    def dispatch(self, job):
        self.sent.append(dict(job))

    def has_artifact(self, run_id, name):
        assert name == "apple-products"
        return run_id in self.artifacts


def _switch(tmp_path, monkeypatch, owners):
    switch = tmp_path / "speedups.json"
    switch.write_text(json.dumps({"owners": {owner: ["apple-shared-build"] for owner in owners}}))
    monkeypatch.setenv("OPENMATES_CI_SPEEDUPS_FILE", str(switch))


def _run(remote, job, run_id, status="in_progress", conclusion=None):
    remote.visible = [r for r in remote.visible if r["id"] != run_id] + [{
        "id": run_id, "display_title": f"Isolated tests {job['mode']} {job['token']}",
        "status": status, "conclusion": conclusion, "html_url": f"https://example.org/{run_id}",
    }]


def test_apple_jobs_beyond_the_macos_limit_wait_undispatched(tmp_path, monkeypatch):
    _switch(tmp_path, monkeypatch, [])
    queue = Queue(tmp_path / "queue.db")
    for n in range(7):
        queue.enqueue(f"owner{n}", SOURCE, [f"OpenMatesUITests/A{n}"], mode="apple-ui")
    linux = queue.enqueue("linux", SOURCE, ["x.spec.ts"])
    remote = Remote()
    queue.tick(remote, 100)
    sent = [job for job in remote.sent if job["mode"] == "apple-ui"]
    assert len(sent) == 5
    assert linux["id"] in {job["id"] for job in remote.sent}
    waiting = [job for job in queue.status() if job["mode"] == "apple-ui" and job["state"] == "queued"]
    assert len(waiting) == 2


def test_one_round_builds_once_and_its_other_jobs_test_those_products(tmp_path, monkeypatch):
    _switch(tmp_path, monkeypatch, ["owner"])
    queue = Queue(tmp_path / "queue.db")
    start = time.time()
    unit = queue.enqueue("owner", SOURCE, ["OpenMatesTests/A"], mode="apple-unit")
    remote = Remote()
    queue.tick(remote, start + 1)  # the round window: wait for the round's other jobs
    assert remote.sent == []
    assert queue.status(unit["id"])[0]["phase"] == "collecting the Apple round"
    ui = queue.enqueue("owner", SOURCE, ["OpenMatesUITests/B"], mode="apple-ui")
    ui2 = queue.enqueue("owner", SOURCE, ["OpenMatesUITests/C"], mode="apple-ui")
    other = queue.enqueue("other", SOURCE, ["OpenMatesUITests/B"], mode="apple-ui")
    queue.tick(remote, start + 100)
    assert {job["id"] for job in remote.sent} == {unit["id"], other["id"]}
    producer = next(job for job in remote.sent if job["id"] == unit["id"])
    assert producer["apple_producer"] == "self"
    assert next(job for job in remote.sent if job["id"] == other["id"])["apple_producer"] == "solo"

    _run(remote, unit, 901)
    queue.tick(remote, start + 140)  # still building: the consumers wait, holding no macOS slot
    assert len(remote.sent) == 2
    assert {job["phase"] for job in queue.status() if job["id"] in (ui["id"], ui2["id"])} == {
        "waiting for the shared Apple build"
    }

    remote.artifacts.add(901)
    queue.tick(remote, start + 180)
    consumers = [job for job in remote.sent if job["id"] in (ui["id"], ui2["id"])]
    assert len(consumers) == 2
    assert {job["prepared_run_id"] for job in consumers} == {901}


def test_consumers_build_themselves_when_the_producer_publishes_nothing(tmp_path, monkeypatch):
    _switch(tmp_path, monkeypatch, ["owner"])
    queue = Queue(tmp_path / "queue.db")
    unit = queue.enqueue("owner", SOURCE, ["OpenMatesTests/A"], mode="apple-unit")
    ui = queue.enqueue("owner", SOURCE, ["OpenMatesUITests/B"], mode="apple-ui")
    remote = Remote()
    start = time.time()
    queue.tick(remote, start + 100)
    _run(remote, unit, 902, status="completed", conclusion="failure")
    queue.tick(remote, start + 140)
    consumer = next(job for job in remote.sent if job["id"] == ui["id"])
    assert consumer["apple_producer"] == "solo"
    assert not consumer.get("prepared_run_id")


def test_without_the_switch_every_job_builds_itself(tmp_path, monkeypatch):
    _switch(tmp_path, monkeypatch, [])
    queue = Queue(tmp_path / "queue.db")
    queue.enqueue("owner", SOURCE, ["OpenMatesTests/A"], mode="apple-unit")
    queue.enqueue("owner", SOURCE, ["OpenMatesUITests/B"], mode="apple-ui")
    remote = Remote()
    queue.tick(remote, 100)
    assert [job["apple_producer"] for job in remote.sent] == ["solo", "solo"]


def test_producer_and_consumer_dispatch_inputs(tmp_path, monkeypatch):
    _switch(tmp_path, monkeypatch, [])
    github = GitHub.__new__(GitHub)
    github.repo = "example/repo"
    requests = []
    github.request = lambda endpoint, payload=None: requests.append(payload)
    queue = Queue(tmp_path / "queue.db")
    job = queue.enqueue("owner", SOURCE, ["OpenMatesUITests/B"], mode="apple-ui")
    github.dispatch({**job, "apple_producer": "self"})
    github.dispatch({**job, "apple_producer": "solo", "prepared_run_id": 901})
    github.dispatch({**job, "apple_producer": "solo"})
    producer, consumer, alone = (r["inputs"] for r in requests)
    assert "apple-products" in producer["ci_speedups"].split(",") and "prepared_run_id" not in producer
    assert consumer["prepared_run_id"] == "901" and "apple-products" not in consumer.get("ci_speedups", "")
    assert "prepared_run_id" not in alone and "apple-products" not in alone.get("ci_speedups", "")


def test_consumer_plan_tests_the_shared_products_without_building():
    built = Path("/out/DerivedData/Build/Products/OpenMates_iOS.xctestrun")
    for mode, specs in (("apple-unit", ["all"]), ("apple-ui", ["OpenMatesUITests/A"] * 13)):
        plan = ci_apple.xcode_plan(mode, Path("/out"), specs, xctestrun=built)
        assert ci_apple.BUILD_STEP not in [step[0] for step in plan]
        test = plan[-1][1]
        assert test[:2] == ["xcodebuild", "test-without-building"]
        assert test[test.index("-xctestrun") + 1] == str(built)
        assert "-scheme" not in test and ci_apple.TEST_SUPPORT_SETTING not in test
    recorded = ci_apple.xcode_plan("apple-ui", Path("/out"), ["OpenMatesUITests/A"], xctestrun=built)
    assert ci_apple.KEEP_RECORDINGS_STEP in [step[0] for step in recorded]
    assert recorded[-1][1][recorded[-1][1].index("-xctestrun") + 1].endswith(ci_apple.RECORDED_XCTESTRUN)


def test_build_identity_is_shared_across_lanes_but_not_with_other_builds():
    identities = {
        ci_apple.build_identity("apple-unit", ["all"]),
        ci_apple.build_identity("apple-ui", ["OpenMatesUITests/A"]),
        ci_apple.build_identity("apple-build", ["all"]),
    }
    assert len(identities) == 1


def _repo(tmp_path: Path) -> Path:
    root = tmp_path / "subject"
    root.mkdir()
    env = {"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@example.org",
           "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@example.org", "PATH": "/usr/bin:/bin"}
    subprocess.run(["git", "init", "-q"], cwd=root, check=True, env=env)
    (root / "a.txt").write_text("a")
    subprocess.run(["git", "add", "."], cwd=root, check=True, env=env)
    subprocess.run(["git", "commit", "-qm", "a"], cwd=root, check=True, env=env)
    return root


def _products(out: Path) -> None:
    products = out / "DerivedData" / "Build" / "Products"
    (products / "Debug-iphonesimulator" / "OpenMates.app").mkdir(parents=True)
    binary = products / "Debug-iphonesimulator" / "OpenMates.app" / "OpenMates"
    binary.write_text("bin")
    binary.chmod(0o755)
    (products / "Debug-iphonesimulator" / "Current").symlink_to("OpenMates.app")
    (products / "OpenMates_iOS.xctestrun").write_text("plist")


def test_shared_products_round_trip_keeps_links_and_refuses_other_sources(tmp_path):
    root = _repo(tmp_path)
    producer_out, consumer_out, folder = root / "p", root / "c", tmp_path / "shared"
    _products(producer_out)
    ci_apple.pack_shared_products(root, producer_out, "apple-unit", ["all"], folder)
    xctestrun, note = ci_apple.restore_shared_products(root, consumer_out, "apple-ui", ["OpenMatesUITests/A"], folder)
    assert xctestrun == consumer_out / "DerivedData" / "Build" / "Products" / "OpenMates_iOS.xctestrun", note
    restored = consumer_out / "DerivedData" / "Build" / "Products" / "Debug-iphonesimulator"
    assert (restored / "Current").is_symlink()
    assert (restored / "OpenMates.app" / "OpenMates").stat().st_mode & 0o111

    manifest = json.loads((folder / ci_apple.PRODUCTS_MANIFEST).read_text())
    (folder / ci_apple.PRODUCTS_MANIFEST).write_text(json.dumps({**manifest, "source_commit": "b" * 40}))
    xctestrun, note = ci_apple.restore_shared_products(root, root / "c2", "apple-ui", ["OpenMatesUITests/A"], folder)
    assert xctestrun is None and "source_commit" in note
    assert ci_apple.restore_shared_products(root, root / "c3", "apple-ui", ["OpenMatesUITests/A"], tmp_path / "none")[0] is None


def _fake_checks(monkeypatch, rows, codes):
    import sys
    import types

    fake = types.ModuleType("ci_rust_checks")
    fake.slug = lambda name: name.replace(" ", "-")
    names = []

    def run(name, command, *, blocking, cwd):
        names.append(name)
        rows.append({"excerpt": [], "seconds": 1, "diagnostics": 0})
        return codes.get(name, 0)

    fake.run = run
    fake.load_rows = lambda: rows
    monkeypatch.setitem(sys.modules, "ci_rust_checks", fake)
    return names


def test_producer_phases_run_the_one_plan_in_two_parts(tmp_path, monkeypatch):
    names = _fake_checks(monkeypatch, [], {})
    packed = []
    monkeypatch.setattr(ci_apple, "pack_shared_products", lambda *args: packed.append(args))
    monkeypatch.setenv("CI_APPLE_PRODUCTS_OUT", str(tmp_path / "shared"))
    monkeypatch.setenv("CI_APPLE_PHASE", "build")
    built: list[dict] = []
    ci_apple.run(tmp_path, built, "apple-ui", ["OpenMatesUITests/A"])
    assert names[-1] == ci_apple.BUILD_STEP and len(packed) == 1
    monkeypatch.setenv("CI_APPLE_PHASE", "test")
    results: list[dict] = []
    ci_apple.run(tmp_path, results, "apple-ui", ["OpenMatesUITests/A"])
    assert [row["suite"] for row in results][: len(built)] == [row["suite"] for row in built]
    assert names[-1].startswith("xcodebuild test ") and names.count(ci_apple.BUILD_STEP) == 1


def test_a_failed_producer_build_publishes_nothing_and_runs_no_tests(tmp_path, monkeypatch):
    names = _fake_checks(monkeypatch, [], {ci_apple.BUILD_STEP: 65})
    packed = []
    monkeypatch.setattr(ci_apple, "pack_shared_products", lambda *args: packed.append(args))
    monkeypatch.setenv("CI_APPLE_PRODUCTS_OUT", str(tmp_path / "shared"))
    monkeypatch.setenv("CI_APPLE_PHASE", "build")
    ci_apple.run(tmp_path, [], "apple-unit", ["all"])
    monkeypatch.setenv("CI_APPLE_PHASE", "test")
    results: list[dict] = []
    ci_apple.run(tmp_path, results, "apple-unit", ["all"])
    assert not packed and names[-1] == ci_apple.BUILD_STEP
    assert results[-1]["exit_code"] == 65


def test_shared_products_are_refused_for_the_private_benchmark_and_core(tmp_path, monkeypatch):
    monkeypatch.setenv("CI_APPLE_PRODUCTS_IN", str(tmp_path))
    with pytest.raises(ValueError, match="ordinary Xcode lanes"):
        ci_apple.run(tmp_path, [], "apple-build", ["all"])
    with pytest.raises(ValueError, match="ordinary Xcode lanes"):
        ci_apple.run(tmp_path, [], "apple-core", ["all"])
