# scripts/tests/test_audit_app_provider_contracts.py
#
# Regression tests for explicit app/provider metadata audit targets.
# These contracts keep feature-specific audits deterministic even when the
# relevant metadata files are absent or not part of the staged diff.

from scripts import audit_app_provider_contracts
from scripts.audit_app_provider_contracts import PROVIDERS_ROOT, audit_provider_file, main


def test_required_missing_app_and_provider_fail(capsys) -> None:
    result = main(["--require-app", "missing-app", "--require-provider", "missing-provider"])

    assert result == 1
    errors = capsys.readouterr().err
    assert "required app metadata is missing" in errors
    assert "required provider metadata is missing" in errors


def test_required_existing_app_and_provider_pass() -> None:
    assert main(["--require-app", "design", "--require-provider", "iconify"]) == 0


def test_hi3d_training_disclosure_surfaces_pass() -> None:
    assert main(["--require-provider", "hi3d"]) == 0


def test_hi3d_training_disclosure_rejects_mismatched_privacy_url(tmp_path, monkeypatch) -> None:
    privacy_path = tmp_path / "privacy_policy.yml"
    privacy_path.write_text(
        "provider_groups:\n  model_generation:\n    providers:\n      hi3d:\n        privacy_policy: https://example.test/wrong\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(audit_app_provider_contracts, "PRIVACY_POLICY_PATH", privacy_path)

    issues = audit_provider_file(PROVIDERS_ROOT / "hi3d.yml")

    assert any("privacy_policy.yml" in issue.message for issue in issues)
