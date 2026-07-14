"""Regression checks for the Playwright GitHub Actions process guard.

The workflow wraps Playwright with GNU timeout so hung jobs still preserve
artifacts. This check keeps that outer guard longer than every explicit spec
timeout, allowing Playwright to report its own failures cleanly.
"""

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
        "E2E_SIGNUP_INVITE_CODE: ${{ (contains(github.event.inputs.spec, 'signup') "
        "|| github.event.inputs.spec == 'referral-signup-purchase.spec.ts' "
        "|| github.event.inputs.spec == 'create-test-account.spec.ts') "
        "&& secrets.E2E_SIGNUP_INVITE_CODE || '' }}"
    ) in workflow
    assert "OPENMATES_TEST_ACCOUNT_API_KEY: ${{ secrets.OPENMATES_TEST_ACCOUNT_API_KEY }}" in workflow
    assert "/v1/auth/e2e/restore_signup_invite_code" not in workflow
