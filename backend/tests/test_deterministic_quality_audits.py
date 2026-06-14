# backend/tests/test_deterministic_quality_audits.py
#
# Unit coverage for deterministic quality/security audits under scripts/.
# These tests exercise pure audit functions with temporary fixtures so they do
# not depend on the current dirty worktree or staged git state.
# Architecture context: scripts/code_quality_guard.py

import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPTS_DIR = REPO_ROOT / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import audit_app_provider_contracts  # noqa: E402
import audit_opencode_automation_budget  # noqa: E402
import audit_playwright_determinism  # noqa: E402
import audit_sensitive_logging  # noqa: E402
import code_quality_guard  # noqa: E402
import run_provider_contracts  # noqa: E402


def test_playwright_audit_blocks_css_locator_and_timeout(tmp_path, monkeypatch) -> None:
    """Changed specs should not add class selectors or blind waits."""

    spec_root = tmp_path / "frontend" / "apps" / "web_app" / "tests"
    spec_root.mkdir(parents=True)
    spec = spec_root / "example.spec.ts"
    spec.write_text(
        "import { test } from '@playwright/test';\n"
        "test('bad', async ({ page }) => {\n"
        "  await page.locator('.save-button').click();\n"
        "  await page.waitForTimeout(1000);\n"
        "});\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(audit_playwright_determinism, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(audit_playwright_determinism, "SPEC_ROOT", spec_root)

    issues = audit_playwright_determinism.audit_paths([spec])

    assert len(issues) == 2
    assert any("CSS class selectors" in issue.message for issue in issues)
    assert any("waitForTimeout" in issue.message for issue in issues)


def test_playwright_audit_allows_explicit_wait_exception(tmp_path, monkeypatch) -> None:
    """Explicit allow markers keep unavoidable timing waits visible."""

    spec_root = tmp_path / "frontend" / "apps" / "web_app" / "tests"
    spec_root.mkdir(parents=True)
    spec = spec_root / "example.spec.ts"
    spec.write_text(
        "import { test } from '@playwright/test';\n"
        "test('allowed', async ({ page }) => {\n"
        "  // playwright-determinism: allow animation boundary\n"
        "  await page.waitForTimeout(200);\n"
        "  await page.getByTestId('save-button').click();\n"
        "});\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(audit_playwright_determinism, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(audit_playwright_determinism, "SPEC_ROOT", spec_root)

    assert audit_playwright_determinism.audit_paths([spec]) == []


def test_playwright_added_line_audit_allows_previous_line_marker() -> None:
    """Pre-commit added-line audit should honor the documented previous-line marker."""

    issues = audit_playwright_determinism.audit_added_lines(
        [
            ("frontend/apps/web_app/tests/example.spec.ts", 10, "// playwright-determinism: allow animation boundary"),
            ("frontend/apps/web_app/tests/example.spec.ts", 11, "await page.waitForTimeout(200);"),
        ]
    )

    assert issues == []


def test_playwright_reserved_spec_requires_real_serial_config(tmp_path, monkeypatch) -> None:
    """Comments mentioning serial should not satisfy reserved-account policy."""

    spec_root = tmp_path / "frontend" / "apps" / "web_app" / "tests"
    spec_root.mkdir(parents=True)
    spec = spec_root / "api-keys-flow.spec.ts"
    spec.write_text(
        "import { test } from '@playwright/test';\n"
        "// This should run serially, but is not configured.\n"
        "test('api keys', async () => {});\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(audit_playwright_determinism, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(audit_playwright_determinism, "SPEC_ROOT", spec_root)

    issues = audit_playwright_determinism.audit_reserved_account_specs([spec])

    assert len(issues) == 1
    assert "serial execution" in issues[0].message


def test_app_provider_audit_blocks_missing_provider_reference(tmp_path, monkeypatch) -> None:
    """App skill provider IDs should resolve to provider metadata or allowlisted virtual providers."""

    apps_root = tmp_path / "backend" / "apps"
    providers_root = tmp_path / "backend" / "providers"
    static_root = tmp_path / "frontend" / "packages" / "ui" / "static"
    app_dir = apps_root / "events"
    app_dir.mkdir(parents=True)
    providers_root.mkdir(parents=True)
    static_root.mkdir(parents=True)
    app_file = app_dir / "app.yml"
    app_file.write_text(
        "skills:\n"
        "  - id: search\n"
        "    providers:\n"
        "      - name: Missing Provider\n"
        "        id: missing_provider\n"
        "        no_api_key: true\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(audit_app_provider_contracts, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(audit_app_provider_contracts, "APPS_ROOT", apps_root)
    monkeypatch.setattr(audit_app_provider_contracts, "PROVIDERS_ROOT", providers_root)
    monkeypatch.setattr(audit_app_provider_contracts, "UI_STATIC_ROOT", static_root)

    issues = audit_app_provider_contracts.audit_paths([app_file])

    assert len(issues) == 1
    assert "missing backend/providers/missing_provider.yml" in issues[0].message


def test_app_provider_audit_validates_provider_icon_and_privacy(tmp_path, monkeypatch) -> None:
    """Provider YAML must include a valid HTTPS privacy policy and icon asset."""

    providers_root = tmp_path / "backend" / "providers"
    static_root = tmp_path / "frontend" / "packages" / "ui" / "static"
    providers_root.mkdir(parents=True)
    static_root.mkdir(parents=True)
    provider_file = providers_root / "demo.yml"
    provider_file.write_text(
        "provider_id: demo\n"
        "name: Demo\n"
        "description: Demo provider\n"
        "privacy_policy: http://example.com/privacy\n"
        "logo_svg: icons/missing.svg\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(audit_app_provider_contracts, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(audit_app_provider_contracts, "PROVIDERS_ROOT", providers_root)
    monkeypatch.setattr(audit_app_provider_contracts, "UI_STATIC_ROOT", static_root)

    issues = audit_app_provider_contracts.audit_paths([provider_file])

    assert any("missing frontend static asset" in issue.message for issue in issues)
    assert any("privacy_policy must use https" in issue.message for issue in issues)


def test_sensitive_logging_audit_blocks_payload_logging() -> None:
    """Security-sensitive logs should not include full tokens or payloads."""

    issues = audit_sensitive_logging.audit_added_lines(
        [("backend/core/api/app/routes/auth_routes/auth_login.py", 42, 'logger.info(f"login payload={payload} token={token}")')]
    )

    assert len(issues) == 1
    assert "sensitive data" in issues[0].message


def test_sensitive_logging_audit_allows_counts() -> None:
    """Counts and key lists are safe summaries for debugging."""

    issues = audit_sensitive_logging.audit_added_lines(
        [("backend/core/api/app/routes/auth_routes/auth_login.py", 42, 'logger.info(f"payload keys={list(payload.keys())}")')]
    )

    assert issues == []


def test_opencode_budget_audit_blocks_unbounded_permission_skip(tmp_path, monkeypatch) -> None:
    """Permission-skipping OpenCode automation needs budget and approval controls."""

    script = tmp_path / "scripts" / "unsafe.py"
    script.parent.mkdir(parents=True)
    script.write_text(
        "import subprocess\n"
        "subprocess.run(['opencode', 'run', '--dangerously-skip-permissions', 'fix auth'])\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(audit_opencode_automation_budget, "REPO_ROOT", tmp_path)

    issues = audit_opencode_automation_budget.audit_paths([script])

    assert any("timeout" in issue.message for issue in issues)
    assert any("human-approval" in issue.message for issue in issues)


def test_opencode_budget_audit_accepts_bounded_auto_fix_prompt(tmp_path, monkeypatch) -> None:
    """Prompts with no-subagent and verification rules pass the prompt audit."""

    prompts_root = tmp_path / "scripts" / "prompts"
    prompts_root.mkdir(parents=True)
    prompt = prompts_root / "auto-fix.md"
    prompt.write_text(
        "# Auto-fix\n"
        "Do not start subagents.\n"
        "Run no verification yourself; the controller handles verification.\n"
        "If auth or privacy changes are needed, set requires_human_approval.\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(audit_opencode_automation_budget, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(audit_opencode_automation_budget, "PROMPTS_ROOT", prompts_root)

    assert audit_opencode_automation_budget.audit_paths([prompt]) == []


def test_code_quality_guard_runs_new_domain_audits(monkeypatch) -> None:
    """The central hook should invoke domain audits only for relevant staged files."""

    monkeypatch.setattr(code_quality_guard, "_staged_files", lambda: ["frontend/apps/web_app/tests/example.spec.ts"])
    monkeypatch.setattr(
        code_quality_guard,
        "_added_lines_with_numbers",
        lambda: [("frontend/apps/web_app/tests/example.spec.ts", 3, "await page.locator('.bad').click();")],
    )
    monkeypatch.setattr(code_quality_guard, "_added_lines", lambda: [])
    monkeypatch.setattr(code_quality_guard, "_is_new_file", lambda _path: False)
    monkeypatch.setattr(code_quality_guard, "_staged_file_line_count", lambda _path: 10)
    monkeypatch.setattr(
        code_quality_guard.audit_playwright_determinism,
        "audit_reserved_account_specs",
        lambda _paths: [],
    )

    assert code_quality_guard.main() == 1


def test_code_quality_guard_does_not_full_scan_legacy_spec_lines(monkeypatch) -> None:
    """Touching a legacy spec should not block on old waits that were not added."""

    monkeypatch.setattr(code_quality_guard, "_staged_files", lambda: ["frontend/apps/web_app/tests/legacy.spec.ts"])
    monkeypatch.setattr(
        code_quality_guard,
        "_added_lines_with_numbers",
        lambda: [("frontend/apps/web_app/tests/legacy.spec.ts", 10, "test.describe.configure({ mode: 'serial' });")],
    )
    monkeypatch.setattr(code_quality_guard, "_added_lines", lambda: [])
    monkeypatch.setattr(code_quality_guard, "_is_new_file", lambda _path: False)
    monkeypatch.setattr(code_quality_guard, "_staged_file_line_count", lambda _path: 10)

    assert code_quality_guard.main() == 0


def test_provider_contract_notification_dispatches_once(tmp_path, monkeypatch) -> None:
    """Broken provider contracts should send one admin email and persist state."""

    calls = []

    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def read(self):
            return b"{}"

    def fake_urlopen(request, timeout):
        calls.append((request, timeout))
        return FakeResponse()

    state_path = tmp_path / "provider-contracts-email-state.json"
    monkeypatch.setattr(run_provider_contracts, "EMAIL_STATE_PATH", state_path)
    monkeypatch.setenv("INTERNAL_API_SHARED_TOKEN", "test-token")
    monkeypatch.setattr(run_provider_contracts.urllib.request, "urlopen", fake_urlopen)

    broken = [{"provider": "doctolib", "failed": 2, "errors": []}]

    assert run_provider_contracts._notify_broken_providers("2026-06-10", broken) == "dispatched"
    assert len(calls) == 1
    assert state_path.exists()


def test_provider_contract_notification_skips_duplicate_same_day(tmp_path, monkeypatch) -> None:
    """Manual reruns must not spam duplicate provider-health emails."""

    state_path = tmp_path / "provider-contracts-email-state.json"
    state_path.write_text(
        '{"date":"2026-06-10","broken_fingerprint":"doctolib"}',
        encoding="utf-8",
    )
    monkeypatch.setattr(run_provider_contracts, "EMAIL_STATE_PATH", state_path)
    monkeypatch.setenv("INTERNAL_API_SHARED_TOKEN", "test-token")

    def fail_urlopen(*_args, **_kwargs):
        raise AssertionError("duplicate notification should not dispatch")

    monkeypatch.setattr(run_provider_contracts.urllib.request, "urlopen", fail_urlopen)

    broken = [{"provider": "doctolib", "failed": 2, "errors": []}]

    assert run_provider_contracts._notify_broken_providers("2026-06-10", broken) == "already_notified"
