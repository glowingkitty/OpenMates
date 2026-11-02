"""SDK capability gate tooling (scripts/check_sdk_conformance.py, ci_sdk_conformance.py).

Engineering/tooling test. Synthetic matrices and results only: no SDK build,
network, account or native library. Run by the isolated sdk-conformance CI lane
before the real conformance stage.
"""
# contract-test-file: tooling
from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path

import pytest

# Package imports (as the other scripts/tests do), so no second top-level
# module instance can shadow scripts.ci_sdk_conformance in a shared session.
from scripts import check_sdk_conformance as gate
from scripts import ci_sdk_conformance as lane

ROOT = Path(__file__).resolve().parents[2]

LANGUAGES = ("rust", "npm", "python")


def support(status="partial", api=(), evidence=(), conformance=False, gaps=("Synthetic gate fixture gap.",)):
    return {"status": status, "api": list(api), "evidence": list(evidence),
            "conformance": conformance, "gaps": list(gaps)}


def matrix_with(capability):
    real = json.loads((ROOT / gate.MATRIX).read_text())
    return {**{key: real[key] for key in real if key != "capabilities"}, "capabilities": [capability]}


def capability(**languages):
    return {"id": "synthetic.capability.v1", "domain": "encryption",
            "description": "Synthetic gate fixture.",
            "languages": {language: languages.get(language, support()) for language in LANGUAGES}}


def test_real_matrix_validates_against_schema_and_lists_honest_gaps():
    matrix = json.loads((ROOT / gate.MATRIX).read_text())
    gaps = lane.matrix_gaps(matrix)
    # Every non-implemented language row is an open gap with its own reasons.
    expected = sum(1 for row in matrix["capabilities"] for language in LANGUAGES
                   if row["languages"][language]["status"] != "implemented")
    assert len(gaps) == expected and expected > 0
    for row in matrix["capabilities"]:
        for language in LANGUAGES:
            value = row["languages"][language]
            if value["status"] != "implemented":
                assert value["gaps"], f"{row['id']} [{language}] needs a recorded gap"


def test_untracked_or_removed_public_api_is_refused():
    row = capability(npm=support(api=["Client.known"]))
    inventory = {"rust": [], "npm": ["Client.known", "Client.added"], "python": []}
    with pytest.raises(ValueError, match=r"unclassified=\['Client.added'\]"):
        gate.validate_matrix(matrix_with(row), inventory, ROOT)
    inventory = {"rust": [], "npm": [], "python": []}
    with pytest.raises(ValueError, match=r"removed=\['Client.known'\]"):
        gate.validate_matrix(matrix_with(row), inventory, ROOT)
    inventory = {"rust": [], "npm": ["Client.known"], "python": []}
    gate.validate_matrix(matrix_with(row), inventory, ROOT)


def test_missing_or_non_test_evidence_is_refused():
    row = capability(npm=support(evidence=["tests/sdk-conformance/does-not-exist.mjs"]))
    with pytest.raises(ValueError, match="Missing or non-repository evidence"):
        gate.validate_matrix(matrix_with(row), {"rust": [], "npm": [], "python": []}, ROOT)
    row = capability(npm=support(evidence=["scripts/build_sdk_native.py"]))
    with pytest.raises(ValueError, match="executable test code"):
        gate.validate_matrix(matrix_with(row), {"rust": [], "npm": [], "python": []}, ROOT)


def test_result_must_cover_exact_vectors_fixture_and_language():
    ids = {"a", "b"}
    result = {"capability": "c", "language": "npm", "status": "passed", "fixtureSha256": "h",
              "results": [{"id": "a", "status": "passed"}, {"id": "b", "status": "passed"}]}
    gate.validate_result(result, "c", "npm", "h", ids)
    for field, value in (("fixtureSha256", "other"), ("language", "python"), ("status", "skipped"),
                         ("results", result["results"][:1]),
                         ("results", [{"id": "a", "status": "passed"}, {"id": "b", "status": "failed"}])):
        with pytest.raises(ValueError):
            gate.validate_result({**result, field: value}, "c", "npm", "h", ids)


def test_lane_plan_runs_every_conformance_row_with_its_exact_fixture():
    matrix = json.loads((ROOT / gate.MATRIX).read_text())
    plan = lane.execution_plan(ROOT, matrix)
    expected = {(row["id"], language) for row in matrix["capabilities"] for language in LANGUAGES
                if row["languages"][language]["conformance"]}
    assert {(row["capability"], row["language"]) for row in plan} == expected
    for row in plan:
        raw = (ROOT / row["fixture"]).read_bytes()
        assert row["fixtureSha256"] == hashlib.sha256(raw).hexdigest() and row["vectors"]
    # Turning conformance off removes the row; nothing is silently skipped.
    altered = copy.deepcopy(matrix)
    first = plan[0]
    for row in altered["capabilities"]:
        if row["id"] == first["capability"]:
            row["languages"][first["language"]]["conformance"] = False
    assert len(lane.execution_plan(ROOT, altered)) == len(plan) - 1


def test_lane_builds_every_sdk_artifact_before_conformance():
    source = (ROOT / "scripts/ci_sdk_conformance.py").read_text()
    order = [source.index(f'step("{name}"') for name in
             ("napi-build", "python-native-build", "python-binding-build", "wasm-build",
              "sdk-facade-build", "real-conformance")]
    assert order == sorted(order)
    assert '"--language", "python"' in source and '"--language", "wasm"' in source
