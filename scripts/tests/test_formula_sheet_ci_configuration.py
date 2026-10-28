"""The real restricted formula worker is scoped to the isolated source proof."""
from copy import deepcopy

import pytest

from scripts.ci_environment import configure_formula_sheet_worker


def profile():
    return {"services": {"api": {"environment": {
        "CI": "true", "OPENMATES_CI_ISOLATED": "1", "OPENMATES_CI_AI_FIXTURES": "1",
        "MOCK_EXTERNAL_APIS": "true", "SERVER_ENVIRONMENT": "development",
    }}}}


# contract-test: tooling
def test_exact_proof_uses_real_secret_free_worker_without_billing_fixture():
    value = profile()
    configure_formula_sheet_worker(value, ["formula-sheet-editing.spec.ts"])
    api = value["services"]["api"]
    assert api["environment"]["FORMULA_SHEETS_WORKER_URL"] == "http://formula-worker:8020"
    assert "FORMULA_SHEETS_BILLING_POLICY" not in api["environment"]
    assert value["networks"]["formula-calculation"]["internal"] is True
    worker = value["services"]["formula-worker"]
    assert worker["image"] == "openmates-ci-formula-worker:local"
    assert worker["read_only"] and worker["user"] == "65532:65532"
    assert worker["cap_drop"] == ["ALL"]
    assert worker["security_opt"] == ["no-new-privileges:true"]
    assert worker["mem_limit"] <= 384 * 1024**2 and worker["cpus"] == 1.0
    assert worker["pids_limit"] == 32
    assert worker["networks"] == ["formula-calculation"]
    assert all(field not in worker for field in ("environment", "env_file", "volumes", "ports"))
    unrelated = profile()
    original = deepcopy(unrelated)
    configure_formula_sheet_worker(unrelated, ["code-notebook-flow.spec.ts"])
    assert unrelated == original


# contract-test: tooling
@pytest.mark.parametrize("field,value", [("CI", "false"), ("OPENMATES_CI_ISOLATED", "0"), ("OPENMATES_CI_AI_FIXTURES", "0"),
                                        ("MOCK_EXTERNAL_APIS", "false"), ("SERVER_ENVIRONMENT", "production")])
def test_incomplete_isolation_cannot_enable_worker_profile(field, value):
    candidate = profile()
    candidate["services"]["api"]["environment"][field] = value
    with pytest.raises(RuntimeError, match="isolated"):
        configure_formula_sheet_worker(candidate, ["formula-sheet-editing.spec.ts"])


# contract-test: tooling
def test_worker_preserves_existing_networks_and_only_connects_needed_callers():
    value = profile()
    value["services"]["api"]["networks"] = {"default": {"aliases": ["api"]}}
    value["services"]["ai-worker"] = {"environment": {}, "networks": ["default"]}
    value["services"]["core-worker"] = {"environment": {}, "networks": ["default"]}
    configure_formula_sheet_worker(value, ["formula-sheet-editing.spec.ts"])
    assert value["services"]["api"]["networks"]["default"] == {"aliases": ["api"]}
    assert value["services"]["ai-worker"]["networks"] == ["default", "formula-calculation"]
    assert value["services"]["core-worker"] == {"environment": {}, "networks": ["default"]}


# contract-test: tooling
def test_exact_worker_image_build_is_bound_to_selected_candidate_only():
    from pathlib import Path
    import yaml
    workflow = yaml.safe_load((Path(__file__).resolve().parents[2] / ".github/workflows/isolated-tests.yml").read_text())
    build = next(step for step in workflow["jobs"]["test"]["steps"] if step.get("name") == "Build restricted offline formula worker")
    assert build["if"] == "inputs.mode == 'e2e' && inputs.specs_json == '[\"formula-sheet-editing.spec.ts\"]'"
    assert build["with"]["context"] == "./subject"
    assert build["with"]["file"] == "./subject/backend/formula_worker/Dockerfile"
    assert build["with"]["tags"] == "openmates-ci-formula-worker:local"
    assert "inputs.source_commit" in build["with"]["labels"]


# contract-test: tooling
def test_formula_runtime_remains_separate_from_unrelated_browser_batches():
    from scripts.ci_coverage import runtime_batches, validate_runtime_batch
    selected = ["code-notebook-flow.spec.ts", "formula-sheet-editing.spec.ts"]
    assert runtime_batches(selected, 10) == [["code-notebook-flow.spec.ts"], ["formula-sheet-editing.spec.ts"]]
    with pytest.raises(ValueError, match="separate batch"):
        validate_runtime_batch(selected)
    with pytest.raises(RuntimeError, match="separate batch"):
        configure_formula_sheet_worker(profile(), selected)
