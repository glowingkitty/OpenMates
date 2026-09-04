"""Pip SDK facade coverage for structured work-control operations."""

# contract-test-file: tooling

from openmates import OpenMates


# contract-test: direct surface=sdks.pip assertions=sdk.surface.semantic-parity,plans.approval.human-web-revision-bound
def test_pip_work_control_facades_exclude_plan_approval():
    client = OpenMates(api_key="test", api_url="http://127.0.0.1", device_id="test-device")
    assert hasattr(client.plans, "dependencies")
    assert hasattr(client.plans, "revisions")
    assert hasattr(client.tasks, "dependencies")
    assert not hasattr(client.plans.approval, "approve")
