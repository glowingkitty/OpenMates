# scripts/tests/test_audit_skill_embed_registry.py
#
# Regression coverage for app-skill embed registry exceptions.
# Workflows control-plane skills intentionally do not render app_skill_use
# embeds, but new non-exempt skills must still be reported by the audit.
#

from scripts import audit_skill_embed_registry as audit


def test_workflow_control_plane_skills_are_documented_exceptions() -> None:
    path = audit.REPO_ROOT / "backend/apps/workflows/app.yml"

    assert audit.audit([path]) == []


def test_non_exception_skill_without_embed_is_reported(monkeypatch) -> None:
    path = audit.REPO_ROOT / "backend/apps/workflows/app.yml"
    monkeypatch.setattr(audit, "load_app", lambda _: {"skills": [{"id": "not-exempt"}], "embed_types": []})

    issues = audit.audit([path])

    assert len(issues) == 1
    assert "not-exempt" in issues[0]
