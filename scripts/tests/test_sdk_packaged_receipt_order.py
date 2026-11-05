# contract-test-file: tooling
"""PURE source/receipt fixtures only. No real SDK/package/Git/network execution."""
import hashlib
import json
import pytest
from scripts import ci_results
from test_ci_sdk_conformance import green_sdk_evidence


@pytest.mark.parametrize("fault", [None, "wrong_digest", "reversed_digest", "sorted_plan_digest", "source_bytes_drift", "source_input_drift", "contract_drift", "missing_configuration_plan"])
def test_exact_source_ordered_vector_digest_not_merely_hex_or_sorted_plan(tmp_path, fault):
    report, evidence, job, expectation = green_sdk_evidence(tmp_path)
    fixture = "tests/sdk-conformance/fixtures/api-key-foundation.json"
    ids = [row["id"] for row in json.loads(expectation["expected_packaged_fixture"])["capabilities"]["sdk.configuration"]["vectors"]]
    plan = next(row for row in expectation["trust"]["plan"] if row["capability"] == "sdk.configuration" and row["language"] == "npm")
    def digest(values):
        return hashlib.sha256(json.dumps(values, separators=(",", ":")).encode()).hexdigest()
    assert ids != sorted(ids), "fixture meaningfully distinguishes source order from plan sorting"
    assert evidence["gate"]["packagedSdkV1"]["vectorIdsSha256"] == digest(ids)
    if fault == "wrong_digest":
        evidence["gate"]["packagedSdkV1"]["vectorIdsSha256"] = "e" * 64
    elif fault == "reversed_digest":
        evidence["gate"]["packagedSdkV1"]["vectorIdsSha256"] = digest(list(reversed(ids)))
    elif fault == "sorted_plan_digest":
        evidence["gate"]["packagedSdkV1"]["vectorIdsSha256"] = digest(plan["vectors"])
    elif fault == "source_bytes_drift":
        data = json.loads(expectation["expected_packaged_fixture"])
        data["capabilities"]["sdk.configuration"]["vectors"].reverse()
        expectation["expected_packaged_fixture"] = json.dumps(data).encode()
        evidence["gate"]["packagedSdkV1"]["vectorIdsSha256"] = digest(list(reversed(ids)))
    elif fault == "source_input_drift":
        expectation["expected_inputs"][fixture] = "e" * 64
    elif fault == "contract_drift":
        expectation["trust"]["contracts"][fixture] = "e" * 64
    elif fault == "missing_configuration_plan":
        expectation["trust"]["plan"].remove(plan)
    assert ci_results.valid_sdk_conformance_receipt(report, evidence, job, "b" * 40, **expectation) is (fault is None)


@pytest.mark.parametrize("fault", [None, "oversized", "wrong_length", "invalid_source"])
def test_normal_retrieval_reads_only_raw_immutable_job_git_blob(tmp_path, monkeypatch, fault):
    source = "a" * 40 if fault != "invalid_source" else "not-a-source"
    data = b'{"fixture":"INERT immutable bytes, no Git/product execution"}'
    calls = []
    def fixed_read(command, **options):
        calls.append(command)
        assert command[:2] == ["git", "cat-file"]
        assert command[-1] == "a" * 40 + ":tests/sdk-conformance/fixtures/api-key-foundation.json"
        assert options.get("cwd") == tmp_path and options.get("timeout") == 15
        if command[2] == "-s":
            assert options.get("text") is True
            return str(64 * 1024**2 + 1 if fault == "oversized" else len(data))
        assert command[2] == "blob" and "text" not in options
        return data + (b"changed" if fault == "wrong_length" else b"")
    monkeypatch.setattr(ci_results.subprocess, "check_output", fixed_read)
    if fault is None:
        assert ci_results.sdk_packaged_fixture_from_git(tmp_path, source) == data
        assert len(calls) == 2
    else:
        with pytest.raises(RuntimeError):
            ci_results.sdk_packaged_fixture_from_git(tmp_path, source)
        assert len(calls) == (0 if fault == "invalid_source" else 1 if fault == "oversized" else 2)
