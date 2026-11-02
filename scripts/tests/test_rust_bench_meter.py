"""Process-tree meter smoke: real child/grandchild/orphan processes, no CLI or network."""

import shutil
import sys
from pathlib import Path

import pytest

from scripts.rust_bench.meter import CgroupBackend, Meter, build_meter, own_cgroup
from scripts.rust_bench.selftest import run_selftest

pytestmark = pytest.mark.skipif(not sys.platform.startswith("linux") or not (shutil.which("cc") or shutil.which("gcc")),
                                reason="Linux with a C compiler required")


@pytest.fixture(scope="module")
def meter():
    return build_meter("rusage")


# contract-test: tooling
def test_selftest_captures_wall_cpu_and_memory_of_children_and_orphans(meter):
    result = run_selftest(meter)
    failures = {case["name"]: case["problems"] for case in result["cases"] if not case["ok"]}
    assert result["ok"], failures
    orphan = next(case for case in result["cases"] if case["name"] == "orphan-grandchild")["metrics"]
    # The main shell exits at once; the orphan's CPU and memory are still accounted.
    assert orphan["wallMs"] < 250 and orphan["cpuMs"] > 250 and orphan["processesReaped"] >= 2


# contract-test: tooling
def test_timeout_kills_tree_and_reports_timeout(meter, tmp_path):
    result = meter.run(["sleep", "30"], {"PATH": "/usr/bin:/bin"}, timeout=0.3)
    assert result["timedOut"] is True
    assert result["exitCode"] == 128 + 9
    assert result["leftoversKilled"] >= 1


# contract-test: tooling
def test_detached_leftover_is_killed_without_extending_wall(meter, tmp_path):
    out = tmp_path / "out"
    result = meter.run(["sh", "-c", "(sleep 30 &) ; echo done"], {"PATH": "/usr/bin:/bin"}, timeout=60,
                       stdout_path=out)
    assert result["exitCode"] == 0 and result["timedOut"] is False
    assert result["wallMs"] < 1000
    assert result["leftoversKilled"] >= 1
    assert out.read_text().strip() == "done"


# contract-test: tooling
def test_exit_code_and_cwd_are_forwarded(meter, tmp_path):
    out = tmp_path / "pwd"
    result = meter.run(["sh", "-c", "pwd; exit 3"], {"PATH": "/usr/bin:/bin"}, cwd=str(tmp_path), stdout_path=out)
    assert result["exitCode"] == 3
    assert Path(out.read_text().strip()).resolve() == tmp_path.resolve()


# contract-test: tooling
def test_cgroup_helpers_parse_fake_cgroup_files(tmp_path):
    proc = tmp_path / "cgroup"
    proc.write_text("0::/user.slice/bench.scope\n")
    assert own_cgroup(proc, tmp_path / "root") == tmp_path / "root" / "user.slice" / "bench.scope"
    sample = tmp_path / "sample"
    sample.mkdir()
    (sample / "cpu.stat").write_text("usage_usec 3500\nuser_usec 2000\nsystem_usec 1500\n")
    (sample / "memory.peak").write_text("10485760\n")
    (sample / "cgroup.events").write_text("populated 0\nfrozen 0\n")
    assert CgroupBackend.read(sample) == {"userUs": 2000, "systemUs": 1500, "peakBytes": 10485760}
    assert CgroupBackend.populated(sample) is False
    backend, reason = CgroupBackend.try_create(tmp_path / "missing")
    assert backend is None and "not mounted" in reason
    assert isinstance(Meter(None, "x").describe()["memory"], str)
