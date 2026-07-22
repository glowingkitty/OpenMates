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


def test_provider_audit_blocks_direct_chinese_server_routes(tmp_path) -> None:
    provider_path = tmp_path / "blocked.yml"
    provider_path.write_text(
        """
provider_id: blocked
name: Blocked
description: Blocked provider fixture
privacy_policy: https://example.test/privacy
logo_svg: icons/moonshot.svg
optional_keys:
  - env_key: SECRET__MOONSHOT__API_KEY
    vault_path: kv/data/providers/moonshot
    vault_key: api_key
models:
  - id: blocked-model
    name: Blocked Model
    input_types: [text]
    output_types: [text]
    servers:
      - id: moonshot
        name: Moonshot AI
        model_id: kimi-k3
        region: CN
        base_url: https://api.moonshot.ai/v1
""",
        encoding="utf-8",
    )

    issues = audit_provider_file(provider_path)

    messages = "\n".join(issue.message for issue in issues)
    assert "optional key 'env_key'" in messages
    assert "optional key 'vault_path'" in messages
    assert "uses blocked Chinese region" in messages
    assert "uses blocked Chinese server" in messages
    assert "blocked Chinese server URL" in messages


def test_provider_audit_blocks_known_openrouter_direct_chinese_route(tmp_path) -> None:
    provider_path = tmp_path / "blocked_openrouter.yml"
    provider_path.write_text(
        """
provider_id: blocked_openrouter
name: Blocked OpenRouter
description: Blocked provider fixture
privacy_policy: https://example.test/privacy
logo_svg: icons/moonshot.svg
models:
  - id: kimi-k3
    name: Kimi K3
    input_types: [text]
    output_types: [text]
    servers:
      - id: openrouter
        name: OpenRouter
        model_id: moonshotai/kimi-k3
        region: US
""",
        encoding="utf-8",
    )

    issues = audit_provider_file(provider_path)

    assert any("currently forwards to a Chinese upstream" in issue.message for issue in issues)


def test_provider_audit_allows_chinese_origin_models_on_non_chinese_servers(tmp_path) -> None:
    provider_path = tmp_path / "allowed.yml"
    provider_path.write_text(
        """
provider_id: allowed
name: Allowed
description: Allowed provider fixture
privacy_policy: https://example.test/privacy
logo_svg: icons/moonshot.svg
optional_keys:
  - env_key: SECRET__TOGETHER__API_KEY
    vault_path: kv/data/providers/together
    vault_key: api_key
models:
  - id: kimi-k3
    name: Kimi K3
    country_origin: CN
    input_types: [text]
    output_types: [text]
    servers:
      - id: together
        name: Together AI
        model_id: moonshotai/Kimi-K3
        region: US
""",
        encoding="utf-8",
    )

    issues = audit_provider_file(provider_path)

    assert not any("Chinese" in issue.message for issue in issues)
