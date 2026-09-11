"""Focused regression coverage for the safety benchmark proof contract."""

from types import SimpleNamespace

from backend.scripts import test_app_skill_safety_benchmark as benchmark


# contract-test: supporting surface=rest_api assertions=web-search.safety.quality-gate
def test_corpus_contains_all_literal_specification_safety_cases():
    ids = {case["id"] for case in benchmark.load_corpus()["cases"]}
    assert {
        "whole-snippet-not-prefix",
        "paraphrased-phrase-insertion",
        "spoofed-system-authority",
        "secret-exfiltration",
        "unauthorized-tool-call",
        "instruction-split-across-snippets",
        "benign-api-header-and-quoted-attack",
        "metadata-injection-mixed",
    } <= ids


# contract-test: supporting surface=rest_api assertions=web-search.safety.quality-gate
def test_corpus_has_mixed_safe_and_injection_units_and_lexical_url_is_safe():
    case = next(
        case
        for case in benchmark.load_corpus()["cases"]
        if case["id"] == "metadata-injection-mixed"
    )
    assert [unit["expected"] for unit in case["units"]] == ["injection", "safe", "safe"]


# contract-test: supporting surface=rest_api assertions=web-search.safety.quality-gate
def test_payload_builder_keeps_unit_identity():
    case = next(
        case
        for case in benchmark.load_corpus()["cases"]
        if case["id"] == "whole-snippet-not-prefix"
    )
    payload, positions = benchmark.payload_for(case)
    assert len(payload["results"][0]["results"]) == 3
    assert positions["b"] == ("benchmark-result-1", "description")


# contract-test: supporting surface=rest_api assertions=web-search.safety.quality-gate
def test_candidate_without_application_is_not_preservation_success():
    case = {"id": "safe", "units": [{"id": "a", "text": "safe", "expected": "safe"}]}
    result = benchmark.assess(case, {"a": "safe"}, None)
    assert result["application_status"] == "unavailable"
    assert result["exact_preservation"] is None


# contract-test: supporting surface=rest_api assertions=web-search.safety.quality-gate
def test_technical_error_is_not_an_injection_block():
    case = {
        "id": "attack",
        "units": [{"id": "a", "text": "attack", "expected": "injection"}],
    }
    result = benchmark.assess(case, {}, None, "OUTPUT_SAFETY_TIMEOUT")
    assert not result["classification_correct"]
    assert result["decisions"] == ["error"]


# contract-test: supporting surface=rest_api assertions=web-search.safety.latency-gate
def test_nearest_rank_percentiles_are_not_interpolated():
    assert benchmark.nearest_rank([1.0, 2.0, 3.0, 4.0], 50) == 2.0
    assert benchmark.nearest_rank([1.0, 2.0, 3.0, 4.0], 95) == 4.0


# contract-test: supporting surface=rest_api assertions=web-search.safety.latency-gate
def test_live_argv_is_fixed_and_query_is_single_argument():
    argv = benchmark.live_argv("x; rm -rf /")
    assert argv[:4] == ["openmates", "apps", "web", "search"]
    assert argv[4] == "x; rm -rf /"
    assert argv[5] == "--json"
    assert len(argv) == 6


# contract-test: supporting surface=rest_api assertions=web-search.safety.latency-gate
def test_live_marks_invalid_json_as_failure(monkeypatch):
    corpus = {"live_request_manifest": {"version": "v", "requests": ["one"] * 50}}
    monkeypatch.setattr(
        benchmark.subprocess,
        "run",
        lambda *args, **kwargs: SimpleNamespace(returncode=0, stdout="not-json"),
    )
    result, code = benchmark.run_live(corpus)
    assert code == 1
    assert result["metrics"]["failure_count"] == 50


# contract-test: supporting surface=cli assertions=web-search.safety.latency-gate
def test_live_fails_when_safety_log_metrics_are_missing(monkeypatch):
    corpus = {"live_request_manifest": {"version": "v", "requests": ["one"] * 50}}

    def run(command, **kwargs):
        if command[0] == "openmates":
            return SimpleNamespace(
                returncode=0,
                stdout='{"success": true, "data": {"results": []}, "error": null}',
                stderr="",
            )
        if command[0] == "git":
            return SimpleNamespace(returncode=0, stdout="a" * 40, stderr="")
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(benchmark.subprocess, "run", run)
    result, code = benchmark.run_live(corpus)

    assert code == 1
    assert result["metrics"]["metric_failure_count"] == 50
    assert {sample["failure"] for sample in result["samples"]} == {
        "missing_safety_metrics"
    }


# contract-test: supporting surface=cli assertions=web-search.safety.latency-gate
def test_live_fails_when_same_window_has_ambiguous_safety_completions(monkeypatch):
    corpus = {"live_request_manifest": {"version": "v", "requests": ["one"] * 50}}
    logs = "\n".join(
        (
            '{"message": "[AppSkillOutputSafety web/search] Output safety completed in 10ms", "request_id": "one"}',
            '{"message": "[AppSkillOutputSafety web/search] Output safety completed in 20ms", "request_id": "two"}',
        )
    )

    def run(command, **kwargs):
        if command[0] == "openmates":
            return SimpleNamespace(
                returncode=0,
                stdout='{"success": true, "data": {"results": []}, "error": null}',
                stderr="",
            )
        if command[0] == "git":
            return SimpleNamespace(returncode=0, stdout="b" * 40, stderr="")
        return SimpleNamespace(returncode=0, stdout=logs, stderr="")

    monkeypatch.setattr(benchmark.subprocess, "run", run)
    result, code = benchmark.run_live(corpus)

    assert code == 1
    assert result["metrics"]["metric_failure_count"] == 50
    assert {sample["failure"] for sample in result["samples"]} == {
        "ambiguous_safety_metrics"
    }


# contract-test: supporting surface=cli assertions=web-search.safety.latency-gate
def test_live_percentiles_include_all_valid_safety_samples(monkeypatch):
    corpus = {"live_request_manifest": {"version": "v", "requests": ["one"] * 50}}
    log_calls = 0

    def run(command, **kwargs):
        nonlocal log_calls
        if command[0] == "openmates":
            return SimpleNamespace(
                returncode=0,
                stdout='{"success": true, "data": {"results": []}, "error": null}',
                stderr="",
            )
        if command[0] == "git":
            return SimpleNamespace(returncode=0, stdout="c" * 40, stderr="")
        log_calls += 1
        request_id = f"request-{log_calls}"
        safety_ms = 3000 if log_calls in {48, 49, 50} else 10
        logs = "\n".join(
            (
                f'{{"message": "[AppSkillOutputSafety web/search] Output safety completed in {safety_ms}ms", "request_id": "{request_id}"}}',
                f'{{"message": "Structured output safety batch completed: units=1 model_calls=1", "request_id": "{request_id}"}}',
            )
        )
        return SimpleNamespace(returncode=0, stdout=logs, stderr="")

    monkeypatch.setattr(benchmark.subprocess, "run", run)
    result, code = benchmark.run_live(corpus)

    assert code == 1
    assert result["metrics"]["safety_p95_ms"] == 3000
    assert not result["gates"]["safety_p95_within_2s"]
