"""Paired Rust-vs-TypeScript CLI benchmark: statistics, pairing, isolation and report shape."""

import json

import pytest

from scripts.rust_bench import flows as F
from scripts.rust_bench.stats import (
    flow_summary,
    paired_order,
    percentile,
    ratio,
    summarize,
)
from scripts.rust_bench.runner import build_report, write_outputs


def _sample(arm, index, wall, ok=True):
    metrics = {"wallMs": wall, "cpuMs": wall * 2, "cpuUserMs": wall, "cpuSystemMs": wall,
               "peakMemKiB": int(wall * 100), "maxRssKiB": int(wall * 100)}
    return {"index": index, "arm": arm, "ok": ok, "error": None if ok else "exit_1", "metrics": metrics}


# contract-test: tooling
def test_paired_order_alternates_first_arm_and_balances_arms():
    order = paired_order(4)
    assert order == [(0, "rust"), (0, "typescript"), (1, "typescript"), (1, "rust"),
                     (2, "rust"), (2, "typescript"), (3, "typescript"), (3, "rust")]
    assert sum(1 for _, arm in order if arm == "rust") == 4
    with pytest.raises(ValueError):
        paired_order(0)


# contract-test: tooling
def test_percentile_and_summary_match_linear_interpolation():
    values = list(range(1, 21))  # 1..20
    assert percentile(values, 50) == 10.5
    assert percentile(values, 95) == pytest.approx(19.05)
    assert percentile([7], 95) == 7
    summary = summarize(values)
    assert summary == {"n": 20, "median": 10.5, "p95": 19.05, "mean": 10.5, "min": 1.0, "max": 20.0}
    assert summarize([])["median"] is None


# contract-test: tooling
def test_ratio_is_rust_over_typescript_and_tolerates_missing():
    assert ratio(50, 200) == 0.25
    assert ratio(None, 200) is None
    assert ratio(50, 0) is None


# contract-test: tooling
def test_flow_summary_excludes_failed_samples_and_counts_them():
    samples = [_sample("rust", i, 10 + i) for i in range(3)] + [_sample("typescript", i, 100 + i) for i in range(3)]
    samples.append(_sample("rust", 3, 9999, ok=False))
    summary = flow_summary(samples)
    rust = summary["arms"]["rust"]
    assert rust["samples"] == 4 and rust["failures"] == 1
    assert rust["metrics"]["wallMs"]["median"] == 11
    assert summary["arms"]["typescript"]["metrics"]["wallMs"]["median"] == 101
    assert summary["ratioRustOverTypescript"]["wallMs"]["median"] == pytest.approx(11 / 101, abs=1e-4)


class _FakeMeter:
    def describe(self):
        return {"memory": "rusage-max-process-maxrss", "cpu": "rusage-tree-sum", "detail": "test"}


# contract-test: tooling
def test_report_json_shape_and_markdown_table(tmp_path):
    arms = {"rust": F.Arm("rust", ["/private/build/openmates"], tmp_path / "r", "http://api.test"),
            "typescript": F.Arm("typescript", ["node", "/private/dist/cli.js"], tmp_path / "t", "http://api.test")}
    samples = [s for i in range(2) for s in (_sample("rust", i, 10), _sample("typescript", i, 40))]
    flows = [{"name": "whoami", "semanticArgv": "openmates whoami --json", "samples": samples,
              "summary": flow_summary(samples)},
             {"name": "chats-show", "semanticArgv": "x", "skipped": "rust: no chat available"}]
    report = build_report(meter=_FakeMeter(), arms=arms, config={"samples": 2, "flows": ["whoami", "chats-show"]},
                          flows=flows, started="2026-01-01T00:00:00+00:00", versions={"rust": "r", "typescript": "t"})
    table = write_outputs(report, tmp_path / "out" / "report.json", tmp_path / "out" / "report.md")
    loaded = json.loads((tmp_path / "out" / "report.json").read_text())
    assert set(loaded) == {"schemaVersion", "kind", "startedAt", "finishedAt", "host", "meter", "config", "arms",
                           "flows"}
    assert loaded["kind"] == "rust-vs-typescript-cli-benchmark"
    assert loaded["arms"]["rust"]["command"] == "openmates"  # no private build path
    assert loaded["arms"]["typescript"]["command"] == "node cli.js"
    assert "/private" not in (tmp_path / "out" / "report.json").read_text()
    assert loaded["flows"][0]["summary"]["ratioRustOverTypescript"]["wallMs"]["median"] == 0.25
    assert "| whoami | wall ms | 10.0 |" in table and "| 0.250 |" in table
    assert "chats-show | skipped" in table
    assert (tmp_path / "out" / "report.md").read_text() == table


# contract-test: tooling
def test_arm_env_is_built_from_scratch_and_isolated(tmp_path):
    inherited = {"PATH": "/usr/bin", "OPENMATES_PROFILE": "real", "OPENMATES_API_KEY": "secret",
                 "DBUS_SESSION_BUS_ADDRESS": "unix:path=/run/user/1/bus", "HOME": "/home/real", "KEEP": "1"}
    rust = F.Arm("rust", ["/bin/openmates"], tmp_path / "rust", "http://api.test", pass_env=["KEEP"])
    ts = F.Arm("typescript", ["openmates"], tmp_path / "ts", "http://api.test")
    env = rust.env(inherited)
    assert env["HOME"] == str(tmp_path / "rust" / "home")
    assert env["OPENMATES_STATE_DIR"] == str(tmp_path / "rust" / "state")
    assert env["KEEP"] == "1" and env["PATH"] == "/usr/bin"
    for leaked in ("OPENMATES_PROFILE", "OPENMATES_API_KEY", "DBUS_SESSION_BUS_ADDRESS"):
        assert leaked not in env
    assert "KEEP" not in ts.env(inherited)
    assert rust.argv(["whoami", "--json"]) == ["/bin/openmates", "--state-dir", str(tmp_path / "rust" / "state"),
                                               "--api-url", "http://api.test", "whoami", "--json"]
    assert ts.argv(["whoami"]) == ["openmates", "--api-url", "http://api.test", "whoami"]


# contract-test: tooling
def test_isolation_refuses_shared_nested_or_real_profiles(tmp_path):
    def arms(rust, ts):
        return [F.Arm("rust", ["r"], rust, "u"), F.Arm("typescript", ["t"], ts, "u")]

    F.validate_isolation(arms(tmp_path / "a", tmp_path / "b"), tmp_path / "home")
    for rust, ts in ((tmp_path / "a", tmp_path / "a"), (tmp_path / "a", tmp_path / "a" / "ts"),
                     (tmp_path / "home" / ".openmates" / "x", tmp_path / "b"),
                     (tmp_path / "a", tmp_path / "home" / ".openmates-rust")):
        with pytest.raises(F.IsolationError):
            F.validate_isolation(arms(rust, ts), tmp_path / "home")


# contract-test: tooling
def test_flow_arguments_and_chat_id_extraction():
    assert F.flow_args("chats-list") == ["chats", "list", "--limit", "100", "--json"]
    assert F.flow_args("follow-up", chat_id="c1", followup="hi") == ["chats", "send", "--chat", "c1", "hi", "--json"]
    assert F.flow_args("app-skill", app_skill='math calculate "sqrt(144)"') == [
        "apps", "math", "calculate", "sqrt(144)", "--json"]
    assert F.first_chat_id({"chats": [{"id": "x1", "title": "t"}]}) == "x1"
    assert F.first_chat_id({"chats": []}) is None
    assert F.created_chat_id({"chat_id": "n1", "chat": {"id": "n1"}}) == "n1"
    assert F.created_chat_id({"chat": {"id": "n2"}}) == "n2"
    assert F.parse_json_output(b'{"a":1}\n') == {"a": 1}
    assert F.parse_json_output(b'progress\n{"done":true}\n') == {"done": True}
    assert F.error_code({"error": {"code": "authentication_required"}}) == "authentication_required"
    assert F.FLOWS["send"].needs_inference and not F.FLOWS["chats-show"].needs_inference


# contract-test: tooling
def test_inference_flows_require_opt_in(tmp_path):
    from scripts.rust_bench.__main__ import parser, selected_flows

    base = ["run", "--api-url", "u", "--rust-profile", str(tmp_path / "r"), "--ts-profile", str(tmp_path / "t")]
    assert selected_flows(parser().parse_args(base)) == list(F.READ_FLOWS)
    assert selected_flows(parser().parse_args([*base, "--inference"])) == list(F.ALL_FLOWS)
    with pytest.raises(F.IsolationError):
        selected_flows(parser().parse_args([*base, "--flows", "whoami,send"]))
    with pytest.raises(F.IsolationError):
        selected_flows(parser().parse_args([*base, "--flows", "nope"]))


# contract-test: tooling
def test_per_arm_messages_and_expected_model_gate_inference_samples(tmp_path):
    from scripts.rust_bench.runner import Runner

    runner = Runner(None, {}, samples=1, warmup=0, timeout=1, message="m", followup="f", app_skill="math x",
                    chat_ids={"rust": "c", "typescript": "c"},
                    arm_messages={"rust": "@ai-model:gemini-3.8-flash hi", "typescript": None},
                    arm_followups={"typescript": "@Gemini-3.8-Flash again"}, expect_model="Gemini 3.8 Flash")
    try:
        assert runner.args_for("send", "rust") == ["chats", "new", "@ai-model:gemini-3.8-flash hi", "--json"]
        assert runner.args_for("send", "typescript") == ["chats", "new", "m", "--json"]
        runner.chat_ids["followup:typescript"] = "c2"
        assert runner.flow_argv("follow-up", "typescript")[-2] == "@Gemini-3.8-Flash again"
        ok = {"timedOut": False, "exitCode": 0}
        assert runner.check("send", ok, {"chatId": "c", "modelName": "Gemini 3.8 Flash"}) is None
        assert runner.check("follow-up", ok, {"modelName": "Other"}) == "model_mismatch:Other"
        assert runner.check("send", ok, {"chatId": "c"}) == "model_mismatch:missing"
        assert runner.check("whoami", ok, {"user": {}}) is None  # read flows are not model-gated
    finally:
        runner.close()
