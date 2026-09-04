"""Route policy tests for first-party encrypted work-control operations."""

import pytest

from backend.core.api.app.services.user_work_control_service import WorkControlPermissionError, WorkControlValidationError, validate_assumption_resolution_evidence, validate_browser_approval


# contract-test: direct surface=rest_api assertions=plans.approval.human-web-revision-bound
def test_approval_requires_authenticated_trusted_browser_session():
    with pytest.raises(WorkControlPermissionError):
        validate_browser_approval("api_key", "https://app.test", {"https://app.test"})
    with pytest.raises(WorkControlPermissionError):
        validate_browser_approval("session", None, {"https://app.test"})
    validate_browser_approval("session", "https://app.test", {"https://app.test"})


# contract-test: direct surface=rest_api assertions=plans.assumptions.investigated-before-work
def test_resolved_assumption_requires_encrypted_typed_proofs():
    with pytest.raises(WorkControlValidationError):
        validate_assumption_resolution_evidence({"status": "confirmed", "encrypted_sources": "cipher"})
    validate_assumption_resolution_evidence({"status": "confirmed", "encrypted_sources": "cipher-sources", "encrypted_evidence_summary": "cipher-summary"})
