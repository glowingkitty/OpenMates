# contract-test-file: tooling
"""Pooled real-conformance adapters: plan-ordered replay and exported timings.

The INERT synthetic aggregate and drivers mirror the trusted-executor test in
test_ci_sdk_conformance.py; only the executor's concurrency is exercised here.
"""

import json
import time

import pytest

from scripts import ci_sdk_conformance as sdk
from scripts import ci_sdk_conformance_exec as executor
from test_ci_sdk_conformance import gate_fixture, synthetic_trust

AGGREGATE = '''
from pathlib import Path
import os,sys,json
ROOT=Path(__file__).resolve().parents[1]
RUNNERS={language:[sys.executable,str(ROOT/'synthetic-driver.py'),'--language',language] for language in ('rust','npm','python')}
ADAPTER_OVERRIDES={}
def check_generated(root): pass
def discover_inventory(root): return {}
def validate_matrix(matrix,inventory,root): return ['synthetic.local.v1 [rust] partial: synthetic gap']
def conformance(matrix,root):
    output=[]
    for language in ('rust','npm','python'):
        result=subprocess.run(RUNNERS[language]+['--fixture',str(root/matrix['fixture']),'--capability','synthetic.local.v1'],cwd=root,capture_output=True,text=True,timeout=TIMEOUT,env={**os.environ,'OPENMATES_SDK_CONFORMANCE_PYTHON':sys.executable,'CARGO_INCREMENTAL':'0'})
        output.append(json.loads(result.stdout))
    return output
'''

DRIVER = '''
import argparse,hashlib,json,sys,time
from pathlib import Path
p=argparse.ArgumentParser();p.add_argument('--language');p.add_argument('--fixture');p.add_argument('--capability');a=p.parse_args()
time.sleep(SLEEP)
if a.language in FAIL:
    print('never-export-private-stream', file=sys.stderr); sys.exit(3)
raw=Path(a.fixture).read_bytes();vectors=json.loads(raw)['capabilities'][a.capability]['vectors']
print(json.dumps({'capability':a.capability,'language':a.language,'status':'passed','fixtureSha256':hashlib.sha256(raw).hexdigest(),'results':[{'id':row['id'],'status':'passed'} for row in vectors]}))
'''


def prepare(tmp_path, monkeypatch, *, sleep=0.0, fail=(), timeout=600, workers=3):
    root, report = gate_fixture(tmp_path)
    trust = synthetic_trust(root)
    program = root / "scripts/check_sdk_conformance.py"
    program.parent.mkdir()
    program.write_text(AGGREGATE.replace("TIMEOUT", str(timeout)))
    driver = root / "synthetic-driver.py"
    driver.write_text(DRIVER.replace("SLEEP", repr(sleep)).replace("FAIL", repr(tuple(fail))))
    trust["programs"] = {"scripts/check_sdk_conformance.py": sdk.sha(program.read_bytes()),
                         "synthetic-driver.py": sdk.sha(driver.read_bytes())}
    monkeypatch.setattr(executor, "git", lambda *args: "0" * 40)
    monkeypatch.setattr(executor, "load_trust_for_source", lambda *args, **kwargs: trust)
    monkeypatch.setattr(executor, "snapshot", lambda root: {})
    monkeypatch.setattr(executor, "run_packaged_sdk_v1", lambda *args: report["packagedSdkV1"])
    monkeypatch.setattr(executor, "adapter_workers", lambda: workers)
    private = tmp_path / "private"
    private.mkdir()
    return root, trust, private


def test_pooled_adapters_run_concurrently_and_replay_in_plan_order(tmp_path, monkeypatch):
    root, trust, private = prepare(tmp_path, monkeypatch, sleep=0.8)
    began = time.monotonic()
    executor.execute(root, private / "gate.json", time.monotonic() + 30)
    elapsed = time.monotonic() - began
    actual = json.loads((private / "gate.json").read_text())
    # Three 0.8 s adapters on three workers overlap instead of adding up.
    assert elapsed < 2.0
    assert [row["language"] for row in actual["actualLaunches"]] == ["rust", "npm", "python"]
    assert [row["language"] for row in actual["conformance"]] == ["rust", "npm", "python"]
    assert all(row["status"] == "passed" and row["elapsedSeconds"] >= 0.8 for row in actual["actualLaunches"])
    assert sdk.gate_receipt(root, actual, trust=trust)["vectorOutcomeCount"] == 6
    timings = sdk.launch_timing_diagnostics(private, trust["plan"])
    assert timings["workers"] == 3 and len(timings["adapters"]) == 3
    assert {row["status"] for row in timings["adapters"]} == {"passed"}


@pytest.mark.parametrize("workers", [1, 3])
def test_failure_exports_first_plan_failure_and_durations_only(tmp_path, monkeypatch, workers):
    root, trust, private = prepare(tmp_path, monkeypatch, sleep=0.2, fail=("npm", "python"), workers=workers)
    with pytest.raises(sdk.Refused, match="driver_failed"):
        executor.execute(root, private / "gate.json", time.monotonic() + 30)
    failure = json.loads((private / "driver-failure.json").read_text())
    # Deterministic: the first failing adapter in plan order, never the later one.
    assert failure["adapter"]["language"] == "npm"
    report = sdk.failure_diagnostics(private, root, "real-conformance", {}, trust["plan"])
    timings = report["launchTimings"]
    assert timings["status"] == "recorded" and timings["workers"] == workers
    by_language = {row["language"]: row for row in timings["adapters"]}
    assert by_language["rust"]["status"] == "passed" and by_language["npm"]["status"] == "failed"
    assert all(set(row) <= {"planIndex", "capability", "language", "status",
                            "startedOffsetSeconds", "elapsedSeconds"} for row in timings["adapters"])
    assert {row["phase"] for row in timings["steps"]} <= sdk.TIMING_PHASES
    assert report["adapter"]["language"] == "npm"
    assert "never-export" not in json.dumps(report)


def test_replay_refuses_a_call_that_differs_from_the_pooled_launch(tmp_path, monkeypatch):
    root, _trust, private = prepare(tmp_path, monkeypatch, timeout=2)
    with pytest.raises(sdk.Refused, match="driver_prefetch_mismatch"):
        executor.execute(root, private / "gate.json", time.monotonic() + 30)
    assert json.loads((private / "driver-failure.json").read_text()) == {"code": "trusted_adapters_failed"}


def test_timing_diagnostics_drop_unknown_or_mismatched_rows(tmp_path):
    root, _report = gate_fixture(tmp_path)
    plan = synthetic_trust(root)["plan"]
    (tmp_path / "driver-timings.json").write_text(json.dumps({
        "workers": 4, "elapsedSeconds": 12.5,
        "steps": [{"phase": "prebuild", "status": "passed", "startedOffsetSeconds": 0, "elapsedSeconds": 1.0},
                  {"phase": "secret-path", "status": "passed", "startedOffsetSeconds": 0}],
        "adapters": [{"planIndex": 0, "capability": plan[0]["capability"], "language": plan[0]["language"],
                      "status": "running", "startedOffsetSeconds": 2.0, "stdout": "never-export"},
                     {"planIndex": 1, "capability": "other", "language": plan[1]["language"],
                      "status": "passed", "startedOffsetSeconds": 1.0, "elapsedSeconds": 3.0},
                     {"planIndex": 99, "capability": "x", "language": "rust", "status": "passed",
                      "startedOffsetSeconds": 1.0}]}))
    value = sdk.launch_timing_diagnostics(tmp_path, plan)
    assert [row["phase"] for row in value["steps"]] == ["prebuild"]
    assert [row["planIndex"] for row in value["adapters"]] == [0]
    assert "never-export" not in json.dumps(value)
