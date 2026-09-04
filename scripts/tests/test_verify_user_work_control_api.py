"""Tooling guard for pointerless encrypted Plan verifier fixtures."""

from pathlib import Path

# contract-test-file: tooling


def test_work_control_verifier_uses_master_wrapper_not_plan_row_key():
    script = (Path(__file__).resolve().parents[1] / "verify_user_work_control_api.py").read_text()
    assert '"encrypted_goal"' in script
    assert '"key_type": "master"' in script
    assert '"encrypted_plan_key": opaque()' in script
    assert '"key_type": "plan"' in script
    assert '"hashed_plan_id": hashed_id(plan_id)' in script


def test_work_control_cli_verifier_supplies_required_plan_goal():
    script = (Path(__file__).resolve().parents[1] / "verify_user_work_control_cli.py").read_text()
    assert '"--goal", "Verify encrypted work control"' in script
    assert "elif isinstance(value, list):" in script
