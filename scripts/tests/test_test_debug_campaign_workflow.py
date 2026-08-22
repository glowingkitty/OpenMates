#!/usr/bin/env python3
"""
Static workflow guard for durable failed-test debug campaigns.

This test prevents the agent skills and auto-fix controller from drifting back
to chat-only diagnoses, one-entry verification, or local JSON coordination.
"""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def text(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


# contract-test: tooling
def test_fix_tests_is_campaign_orchestrator_and_fix_next_is_resume_wrapper():
    fix_tests = text(".claude/skills/fix-tests/SKILL.md")
    fix_next = text(".claude/skills/fix-next-test/SKILL.md")

    assert "campaign start" in fix_tests
    assert "campaign list --active --overlap-current-failures" in fix_tests
    assert "campaign status" in fix_tests
    assert fix_tests.index("campaign list --active --overlap-current-failures") < fix_tests.index("campaign start")
    assert "acceptance criteria" in fix_tests.lower()
    assert "complete-group" in fix_tests
    assert "campaign dispatch" in fix_tests
    assert "campaign next" in fix_next
    assert "independent workflow" in fix_next.lower()


# contract-test: tooling
def test_triager_and_auto_fix_use_durable_campaign_records():
    triager = text(".claude/agents/test-failure-triager.md")
    auto_fix = text("scripts/auto_fix_failed_tests.py")

    assert "campaign" in triager.lower()
    assert "acceptance_criteria" in triager
    assert "root_cause" in triager
    assert "start_debug_campaign" in auto_fix
    assert "append_debug_group_attempt" in auto_fix
    assert "last-failed-tests.json" not in auto_fix


# contract-test: tooling
def test_unit_workflows_accept_exact_campaign_targets():
    pytest_workflow = text(".github/workflows/pytest-unit.yml")
    vitest_workflow = text(".github/workflows/vitest.yml")
    runner = text("scripts/run_tests.py")

    assert "test_targets_json" in pytest_workflow
    assert 'pytest "${PYTEST_TARGETS[@]}"' in pytest_workflow
    assert 'for v in values), end="")' in pytest_workflow
    assert "PYTEST_EXIT=${PIPESTATUS[0]}" in pytest_workflow
    assert 'if [ $PYTEST_EXIT -ne 0 ]; then exit $PYTEST_EXIT; fi' in pytest_workflow
    assert "test_files_json" in vitest_workflow
    assert '"${TEST_FILES[@]}"' in vitest_workflow
    assert "VITEST_EXIT=${PIPESTATUS[0]}" in vitest_workflow
    assert vitest_workflow.count('for v in values if marker in v), end="")') == 2
    assert vitest_workflow.count('if [ $VITEST_EXIT -ne 0 ]; then exit $VITEST_EXIT; fi') == 2
    assert "OPENMATES_CAMPAIGN_TEST_LABELS_JSON" in runner
