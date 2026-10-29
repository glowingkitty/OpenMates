# contract-test-file: tooling
"""Fixed infrastructure selector admission/planner cases; no service execution."""

import ast
from pathlib import Path
import re
from types import SimpleNamespace
from unittest.mock import patch

import pytest
import yaml

from scripts import ci_coverage as coverage, ci_environment as environment
import ci_run_tests as runner

SPEC = "cli-memory-readiness.spec.ts"
ROOT = Path(coverage.__file__).resolve().parents[1]


def steps():
    document = yaml.safe_load(
        (ROOT / ".github/workflows/isolated-tests.yml").read_text()
    )
    return {
        row.get("name"): row
        for row in document["jobs"]["test"]["steps"]
        if row.get("name")
    }


def enabled(expression, mode, specs, *, cli="false", prepared="false"):
    expression = (
        re.sub(r"!(?!=)", "not ", expression)
        .replace("&&", " and ")
        .replace("||", " or ")
    )
    inputs = SimpleNamespace(mode=mode, specs_json=specs, prepare_cli=cli)
    outputs = SimpleNamespace(web=prepared, cli=prepared)
    context = {
        "inputs": inputs,
        "steps": SimpleNamespace(artifacts=SimpleNamespace(outputs=outputs)),
        "contains": lambda value, token: token in value,
        "always": lambda: True,
    }
    return bool(eval(expression, {"__builtins__": {}}, context))


def test_only_memory_readiness_moves_to_normal_e2e():
    assert coverage.execution_mode(SPEC) == "e2e"
    assert coverage.partition([SPEC], {"groups": {}, "holds": {}}) == ([SPEC], {})
    assert SPEC in coverage.CORE_SPECS and SPEC not in coverage.ARTIFACT_SPECS
    assert (
        coverage.execution_mode("security-reporting-email-proof.spec.ts") == "artifact"
    )
    assert coverage.ARTIFACT_SPECS == {"security-reporting-email-proof.spec.ts"}
    assert coverage.execution_mode("tasks-flow.spec.ts") == "e2e"
    assert (
        coverage.execution_mode("components/fixture.spec.ts", coverage.COMPONENT_MARKER)
        == "component"
    )


def test_zero_account_slots_keep_normal_private_backend_classification():
    assert environment.browser_account_slots(SPEC) == 0
    assert environment.browser_account_count([SPEC]) == 0
    assert environment.browser_account_count([SPEC, "tasks-flow.spec.ts"]) == 2
    assert environment.browser_account_slots("tasks-flow.spec.ts") == 2
    for name in environment.DIRECT_CHAT_SPECS:
        assert environment.browser_account_slots(name) == 3
    assert SPEC in environment.PRIVATE_BACKEND_SPECS


class AdmissionBoundary(RuntimeError):
    pass


class LogBoundary:
    def __truediv__(self, name):
        assert name == "ci-web.log"
        return self

    def open(self, *args, **kwargs):
        raise AdmissionBoundary("after all selector guards before work")


@pytest.mark.parametrize(
    "options",
    [
        {"artifact": True},
        {"component": True},
        {"visual_smoke": True},
        {"case_title": "foreign filter"},
    ],
)
def test_memory_profile_rejects_other_modes_and_filters_before_work(
    tmp_path, monkeypatch, options
):
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / SPEC).write_text("// infrastructure")
    monkeypatch.setattr(runner, "WEB", tmp_path)
    monkeypatch.setattr(runner, "RESULTS", LogBoundary())
    with pytest.raises(ValueError):
        runner.run_e2e([SPEC], **options)


def test_normal_exact_e2e_reaches_work_boundary_but_mixed_batch_refuses(
    tmp_path, monkeypatch
):
    (tmp_path / "tests").mkdir()
    for name in (SPEC, "tasks-flow.spec.ts"):
        (tmp_path / "tests" / name).write_text("// infrastructure")
    monkeypatch.setattr(runner, "WEB", tmp_path)
    monkeypatch.setattr(runner, "RESULTS", LogBoundary())
    with pytest.raises(AdmissionBoundary, match="after all selector guards"):
        runner.run_e2e([SPEC])
    with pytest.raises(ValueError, match="Memory readiness requires"):
        runner.run_e2e([SPEC, "tasks-flow.spec.ts"])


def test_security_reporting_retains_real_artifact_isolation_guard():
    with patch.object(runner, "verify_shared_dev_rejected") as isolation:
        runner.verify_artifact_profile(["security-reporting-email-proof.spec.ts"])
        isolation.assert_called_once()
        with pytest.raises(ValueError, match="Artifact-only mode"):
            runner.verify_artifact_profile([SPEC])
        isolation.assert_called_once()


def test_existing_node_probe_and_account_free_classifiers_cover_only_fixed_memory_selector():
    function = next(
        node
        for node in ast.parse(Path(runner.__file__).read_bytes()).body
        if isinstance(node, ast.FunctionDef) and node.name == "run_e2e"
    )
    context = dict(
        vars(runner),
        accountability_only=False,
        component=False,
        artifact=False,
        source="",
        name=SPEC,
        specs=[SPEC],
    )
    for name in ("node_probe_only", "account_free"):
        expression = next(
            node.value
            for node in ast.walk(function)
            if isinstance(node, ast.Assign)
            and any(
                isinstance(target, ast.Name) and target.id == name
                for target in node.targets
            )
        )
        assert (
            eval(
                compile(
                    ast.Expression(expression),
                    "<existing-fixed-probe-classifier>",
                    "eval",
                ),
                context,
            )
            is True
        )
        foreign = {
            **context,
            "name": "tasks-flow.spec.ts",
            "specs": ["tasks-flow.spec.ts"],
        }
        assert (
            eval(
                compile(
                    ast.Expression(expression),
                    "<existing-fixed-probe-classifier>",
                    "eval",
                ),
                foreign,
            )
            is False
        )


def test_fixed_memory_e2e_skips_only_web_cli_and_browser_work():
    selected = steps()
    for name in (
        "Build local web app",
        "Build local CLI only when consumed",
        "Install browser",
    ):
        assert (
            enabled(
                selected[name]["if"],
                "e2e",
                '["cli-memory-readiness.spec.ts"]',
                cli="true",
            )
            is False
        )
    for name in (
        "Prepare isolated stack",
        "Log in to GHCR for compatible runtime images",
        "Reuse compatible published runtime images",
        "Start isolated backend",
        "Collect bounded stack diagnostics",
        "Remove disposable containers and databases",
    ):
        assert (
            enabled(selected[name]["if"], "e2e", '["cli-memory-readiness.spec.ts"]')
            is True
        )


@pytest.mark.parametrize(
    "mode,specs,expected",
    [
        ("e2e", '["tasks-flow.spec.ts"]', (True, True, True)),
        ("e2e", '["storage-accountability-integration.spec.ts"]', (False, True, False)),
        (
            "artifact",
            '["security-reporting-email-proof.spec.ts"]',
            (False, False, True),
        ),
        ("prepare", "[]", (True, True, False)),
        (
            "e2e",
            '["cli-memory-readiness.spec.ts","tasks-flow.spec.ts"]',
            (True, True, True),
        ),
    ],
)
def test_non_target_build_and_browser_plans_are_unchanged(mode, specs, expected):
    selected = steps()
    names = (
        "Build local web app",
        "Build local CLI only when consumed",
        "Install browser",
    )
    assert (
        tuple(enabled(selected[name]["if"], mode, specs, cli="true") for name in names)
        == expected
    )
