"""Regression checks for the Playwright GitHub Actions process guard.

The workflow wraps Playwright with GNU timeout so hung jobs still preserve
artifacts. This check keeps that outer guard longer than every explicit spec
timeout, allowing Playwright to report its own failures cleanly.
"""

# contract-test-file: tooling

from pathlib import Path
import re


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
WORKFLOW_PATH = REPOSITORY_ROOT / ".github/workflows/playwright-spec.yml"
SPECS_DIRECTORY = REPOSITORY_ROOT / "frontend/apps/web_app/tests"
REPORTING_MARGIN_SECONDS = 30


def test_workflow_guard_exceeds_longest_declared_spec_timeout() -> None:
    workflow = WORKFLOW_PATH.read_text(encoding="utf-8")
    guard_match = re.search(r"timeout --kill-after=\d+s (\d+)s", workflow)
    assert guard_match is not None, "Playwright workflow process guard is missing"

    declared_timeouts = [
        int(timeout)
        for spec_path in SPECS_DIRECTORY.rglob("*.spec.ts")
        for timeout in re.findall(
            r"test\.setTimeout\((\d+)\)", spec_path.read_text(encoding="utf-8")
        )
    ]
    assert declared_timeouts, "No explicit Playwright spec timeouts were found"

    guard_seconds = int(guard_match.group(1))
    longest_spec_seconds = max(declared_timeouts) // 1000
    assert guard_seconds >= longest_spec_seconds + REPORTING_MARGIN_SECONDS


def test_signup_invite_secret_is_scoped_to_invite_required_specs() -> None:
    workflow = WORKFLOW_PATH.read_text(encoding="utf-8")

    assert (
        "E2E_SIGNUP_INVITE_CODE: ${{ inputs.requires_account && (contains(inputs.spec, 'signup') "
        "|| inputs.spec == 'referral-signup-purchase.spec.ts' "
        "|| inputs.spec == 'create-test-account.spec.ts') "
        "&& secrets.E2E_SIGNUP_INVITE_CODE || '' }}"
    ) in workflow
    assert 'echo "OPENMATES_TEST_ACCOUNT_API_KEY=${{ secrets.OPENMATES_TEST_ACCOUNT_API_KEY }}" >> "$GITHUB_ENV"' in workflow
    assert 'echo "OPENMATES_TEST_ACCOUNT_API_KEY=$api_key" >> "$GITHUB_ENV"' in workflow
    assert "/v1/auth/e2e/restore_signup_invite_code" not in workflow


def test_spec_owned_deep_research_proof_uses_exact_laptop_video_size() -> None:
    workflow = WORKFLOW_PATH.read_text(encoding="utf-8")

    assert "inputs.spec == 'deep-research-real-inference.spec.ts') && '1440'" in workflow
    assert "inputs.spec == 'deep-research-real-inference.spec.ts') && '900'" in workflow


def test_cli_account_login_failure_exits_with_original_status() -> None:
    workflow = WORKFLOW_PATH.read_text(encoding="utf-8")

    assert "else\n              login_status=$?" in workflow
    assert "exit \"$login_status\"" in workflow


def test_expanded_accounts_use_one_consolidated_repository_secret() -> None:
    workflow = WORKFLOW_PATH.read_text(encoding="utf-8")

    assert "environment: e2e-tests" not in workflow
    assert "migrate_account_secrets_to_expanded_bundle:" in workflow
    assert "Secret migration is limited to expanded normal account slots 21-27." in workflow
    assert "secrets.OPENMATES_TEST_ACCOUNTS_EXPANDED_JSON" in workflow
    assert "gh secret set OPENMATES_TEST_ACCOUNTS_EXPANDED_JSON" in workflow
    assert "--env e2e-tests" not in workflow
    assert 'echo "::add-mask::$EMAIL"' in workflow
    assert 'echo "OPENMATES_TEST_ACCOUNT_1_EMAIL=$EMAIL"' in workflow
    assert 'gh secret delete "OPENMATES_TEST_ACCOUNT_${SLOT}_EMAIL"' in workflow
    assert "inputs.migrate_account_secrets_to_expanded_bundle }}\" = \"true\"" in workflow
    assert "playwright-account-secret-writes" in workflow

    bundle_writes = workflow.split("gh secret set OPENMATES_TEST_ACCOUNTS_EXPANDED_JSON")
    assert len(bundle_writes) == 4
    for preceding_workflow in bundle_writes[:-1]:
        current_step = preceding_workflow.rsplit("      - name:", 1)[-1]
        assert "EXPANDED_ACCOUNTS_JSON: ${{ secrets.OPENMATES_TEST_ACCOUNTS_EXPANDED_JSON }}" in current_step
