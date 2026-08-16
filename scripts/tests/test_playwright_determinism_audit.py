"""Regression checks for deterministic Playwright test infrastructure.

These tests keep inactive inbox providers and ambiguous email helper contracts
out of active E2E source, workflow, and container configuration. Historical
release notes and synthetic security-domain fixtures are intentionally outside
this audit because they do not perform inbox delivery.
"""

from pathlib import Path

# contract-test-file: tooling


REPO_ROOT = Path(__file__).resolve().parents[2]
ACTIVE_EMAIL_PATHS = (
    "frontend/apps/web_app/tests/signup-flow-helpers.ts",
    "frontend/apps/web_app/tests/reminder-email.spec.ts",
    "frontend/apps/web_app/tests/signup-flow-stripe-managed.spec.ts",
    "frontend/apps/web_app/tests/signup-flow-stripe-eu.spec.ts",
    "frontend/apps/web_app/tests/signup-flow-passkey.spec.ts",
    "frontend/apps/web_app/tests/account-recovery-flow.spec.ts",
    "frontend/apps/web_app/tests/create-test-account.spec.ts",
    "frontend/apps/web_app/tests/newsletter-flow.spec.ts",
    "frontend/apps/web_app/tests/referral-signup-purchase.spec.ts",
    "frontend/apps/web_app/tests/settings-buy-credits-stripe-managed.spec.ts",
    "frontend/apps/web_app/tests/settings-change-email.spec.ts",
    "frontend/apps/web_app/tests/signup-skip-2fa-flow.spec.ts",
    "frontend/apps/web_app/tests/prod-smoke/prod-smoke-signup-giftcard-chat.spec.ts",
    ".github/workflows/playwright-spec.yml",
    ".github/workflows/release-core-journeys.yml",
    "docker-compose.playwright.yml",
    ".claude/agents/test-failure-triager.md",
    ".claude/skills/fix-next-test/SKILL.md",
    "frontend/apps/web_app/tests/README.md",
    "frontend/apps/web_app/tests/dev-smoke/README.md",
    "docs/contributing/guides/testing.md",
    "backend/core/api/app/services/directus/gift_card_methods.py",
    "backend/core/api/app/routes/admin.py",
    "backend/core/api/app/routes/payments.py",
    "backend/core/directus/schemas/gift_cards.yml",
    "backend/scripts/create_reusable_gift_card.py",
    "backend/shared/python_utils/e2e_user_detection.py",
    "scripts/run-tests-worker.sh",
    "scripts/run-tests-sequential.sh",
    "scripts/openmates_cli_test_account.mjs",
)


def test_active_email_test_infrastructure_is_gmail_only() -> None:
    violations = []
    for relative_path in ACTIVE_EMAIL_PATHS:
        text = (REPO_ROOT / relative_path).read_text(encoding="utf-8")
        if "mailosaur" in text.lower():
            violations.append(relative_path)

    assert violations == [], f"Active email test paths still reference Mailosaur: {violations}"


def test_shared_email_helper_uses_provider_neutral_contract() -> None:
    helper = (REPO_ROOT / "frontend/apps/web_app/tests/signup-flow-helpers.ts").read_text(
        encoding="utf-8"
    )

    assert "waitForMessage" in helper
    assert "waitForMailosaurMessage" not in helper
    assert "createMailosaurClient" not in helper
    assert "MAILOSAUR_API_KEY" not in helper


def test_prod_smoke_card_uses_exact_mailbox_identity() -> None:
    schema = (REPO_ROOT / "backend/core/directus/schemas/gift_cards.yml").read_text(
        encoding="utf-8"
    )
    service = (
        REPO_ROOT / "backend/core/api/app/services/directus/gift_card_methods.py"
    ).read_text(encoding="utf-8")

    assert "allowed_email_identity_hash" in schema
    assert "Cards with only this field set fail closed" in schema
    assert "_email_identity_hash" in service
