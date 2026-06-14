#!/usr/bin/env python3
"""Behavioral assertions for architecture documentation claims.

Each test is intentionally lightweight and deterministic: it proves that a
documented architecture claim is grounded in source-of-truth files that still
exist and parse where a parser is available. Runtime-specific docs should add
additional focused unit/integration/Playwright assertions beside these.

Architecture: docs/specs/architecture-docs-claim-coverage/spec.yml
"""

from __future__ import annotations

import ast
import json
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]

CLAIM_SOURCES = {
    'arch-accessibility-audit-behavior': ['scripts/accessibility_audit.py', 'test-results/accessibility/'],
    'arch-ai-ai-model-selection-behavior': ['backend/apps/ai/app.yml', 'backend/apps/ai/utils/model_selector.py', 'backend/apps/ai/processing/preprocessor.py', 'backend/apps/ai/processing/main_processor.py', 'backend/providers/*.yml'],
    'arch-ai-followup-suggestions-behavior': ['backend/apps/ai/processing/postprocessor.py', 'backend/apps/ai/base_instructions.yml', 'backend/apps/ai/tasks/ask_skill_task.py', 'frontend/packages/ui/src/services/chatSyncServiceHandlersAI.ts', 'frontend/packages/ui/src/components/ActiveChat.svelte'],
    'arch-ai-hallucination-mitigation-behavior': ['backend/apps/ai/processing/url_validator.py', 'backend/apps/ai/tasks/stream_consumer.py', 'backend/apps/ai/base_instructions.yml', 'backend/apps/ai/processing/preprocessor.py', 'backend/apps/ai/processing/main_processor.py'],
    'arch-ai-mates-behavior': ['backend/apps/ai/mates/', 'backend/apps/ai/utils/mate_utils.py', 'backend/apps/ai/processing/preprocessor.py', 'frontend/packages/ui/src/components/enter_message/utils/mateHelpers.ts', 'frontend/packages/ui/src/styles/mates.css'],
    'arch-ai-preprocessing-model-comparison-behavior': ['backend/apps/ai/app.yml', 'backend/tests/test_model_comparison_mistral_vs_ministral.py', 'backend/providers/mistral.yml'],
    'arch-ai-thinking-models-behavior': ['backend/apps/ai/llm_providers/google_client.py', 'backend/apps/ai/llm_providers/types.py', 'backend/apps/ai/processing/main_processor.py', 'backend/apps/ai/tasks/stream_consumer.py', 'backend/apps/ai/utils/llm_utils.py'],
    'arch-apps-action-confirmation-behavior': ['backend/core/api/app/routes/apps_api.py', 'backend/apps/base_skill.py'],
    'arch-apps-app-skills-behavior': ['backend/apps/base_app.py', 'backend/apps/base_skill.py', 'backend/apps/base_app.yml', 'backend/apps/ai/processing/skill_executor.py', 'backend/shared/python_schemas/app_metadata_schemas.py'],
    'arch-platforms-cli-feature-parity-behavior': ['frontend/packages/openmates-cli/src/cli.ts', 'frontend/packages/openmates-cli/src/client.ts', 'frontend/packages/openmates-cli/src/mentions.ts', 'frontend/packages/openmates-cli/src/fileEmbed.ts', 'frontend/packages/ui/src/components/settings/settingsRoutes.ts'],
    'arch-platforms-cli-package-behavior': ['frontend/packages/openmates-cli/src/cli.ts', 'frontend/packages/openmates-cli/src/client.ts', 'frontend/packages/openmates-cli/src/crypto.ts', 'frontend/packages/openmates-cli/src/ws.ts', 'frontend/packages/openmates-cli/src/storage.ts'],
    'arch-apps-focus-modes-implementation-behavior': ['backend/apps/ai/processing/preprocessor.py', 'backend/apps/ai/processing/main_processor.py', 'backend/core/api/app/services/embed_service.py', 'backend/core/api/app/routes/handlers/websocket_handlers/focus_mode_deactivate_handler.py', 'frontend/packages/ui/src/components/embeds/FocusModeActivationEmbed.svelte'],
    'arch-apps-function-calling-behavior': ['backend/apps/ai/processing/main_processor.py', 'backend/apps/ai/processing/preprocessor.py', 'backend/apps/ai/processing/tool_generator.py', 'backend/apps/ai/base_instructions.yml', 'backend/apps/base_skill.py'],
    'arch-apps-rest-api-behavior': ['backend/core/api/app/routes/apps_api.py', 'backend/apps/base_skill.py', 'backend/apps/ai/processing/rate_limiting.py'],
    'arch-colors-behavior': ['frontend/packages/ui/src/tokens/sources/colors.yml', 'frontend/packages/ui/src/tokens/generated/theme.generated.css'],
    'arch-core-account-backup-behavior': ['frontend/packages/ui/src/services/accountExportService.ts', 'frontend/packages/ui/src/components/settings/account/SettingsExportAccount.svelte', 'frontend/packages/ui/src/components/settings/account/SettingsImportAccount.svelte', 'frontend/packages/ui/src/components/settings/notifications/SettingsBackupReminders.svelte'],
    'arch-core-account-recovery-behavior': ['backend/core/api/app/routes/auth_routes/auth_recovery.py', 'backend/core/api/app/schemas/auth_recovery.py', 'backend/core/api/app/tasks/email_tasks/recovery_account_email_task.py', 'frontend/packages/ui/src/components/AccountRecovery.svelte', 'frontend/packages/ui/src/components/PasswordAndTfaOtp.svelte'],
    'arch-core-client-side-encryption-behavior': ['frontend/packages/ui/src/services/cryptoService.ts', 'frontend/packages/ui/src/services/cryptoKeyStorage.ts', 'backend/core/api/app/utils/encryption.py', 'backend/core/api/app/routes/handlers/websocket_handlers/encrypted_chat_metadata_handler.py'],
    'arch-core-delete-account-behavior': ['backend/core/api/app/routes/settings.py', 'backend/core/api/app/tasks/user_cache_tasks.py', 'backend/core/api/app/services/compliance.py', 'backend/scripts/delete_user_account.py', 'frontend/packages/ui/src/components/settings/account/SettingsDeleteAccount.svelte'],
    'arch-core-passkeys-behavior': ['backend/core/api/app/routes/auth_routes/auth_passkey.py', 'frontend/packages/ui/src/services/cryptoService.ts', 'frontend/packages/ui/src/components/Login.svelte', 'frontend/packages/ui/src/components/signup/steps/secureaccount/SecureAccountTopContent.svelte', 'frontend/packages/ui/src/components/signup/steps/passkey/PasskeyRegistrationBottomContent.svelte'],
    'arch-core-security-behavior': ['backend/core/vault/**/*.py', 'backend/core/api/app/utils/encryption.py', 'frontend/packages/ui/src/services/cryptoService.ts', 'frontend/packages/ui/src/services/cryptoKeyStorage.ts', 'backend/core/api/app/routes/auth_routes/auth_login.py'],
    'arch-core-servers-behavior': ['backend/core/docker-compose.yml', 'backend/preview/docker-compose.preview.yml', 'deployment/dev_server/Caddyfile', 'docs/architecture/apps'],
    'arch-data-device-sessions-behavior': ['frontend/packages/ui/src/stores/authLoginLogoutActions.ts', 'frontend/packages/ui/src/stores/authSessionActions.ts'],
    'arch-data-translations-behavior': ['frontend/packages/ui/src/i18n/sources/', 'frontend/packages/ui/scripts/build-translations.js', 'frontend/packages/ui/package.json'],
    'arch-frontend-accessibility-behavior': ['scripts/accessibility_audit.py', 'scripts/run_accessibility_weekly.py', 'frontend/packages/ui/src/tokens/sources/colors.yml', 'frontend/packages/ui/src/styles/theme.css', 'frontend/packages/ui/src/actions/focusTrap.ts'],
    'arch-frontend-daily-inspiration-behavior': ['backend/apps/ai/daily_inspiration/generator.py', 'backend/apps/ai/daily_inspiration/video_processor.py', 'backend/apps/ai/daily_inspiration/schemas.py', 'backend/shared/config/corporate_channel_patterns.yml', 'frontend/packages/ui/src/components/DailyInspirationBanner.svelte'],
    'arch-frontend-design-tokens-behavior': ['frontend/packages/ui/src/tokens/sources/', 'frontend/packages/ui/src/tokens/generated/', 'frontend/packages/ui/scripts/build-tokens.js', 'frontend/packages/ui/scripts/audit-tokens.js', 'frontend/packages/ui/scripts/validate-token-usage.js'],
    'arch-frontend-docs-web-app-behavior': ['frontend/apps/web_app/scripts/process-docs.js', 'frontend/apps/web_app/scripts/vite-plugin-docs.js', 'frontend/apps/web_app/src/routes/docs/+layout.svelte', 'frontend/apps/web_app/src/routes/docs/+page.ts', 'frontend/apps/web_app/src/routes/docs/[...slug]/+page.svelte'],
    'arch-frontend-native-apps-behavior': ['apple/project.yml', 'apple/OpenMates/Sources/App/OpenMatesApp.swift', 'apple/OpenMates/Sources/Core/Networking/APIClient.swift', 'apple/OpenMates/Sources/Core/Crypto/CryptoManager.swift', 'apple/OpenMates/Sources/Features/Auth/ViewModels/AuthManager.swift'],
    'arch-frontend-web-app-behavior': ['frontend/apps/web_app/src/routes/+layout.svelte', 'frontend/apps/web_app/src/routes/+page.svelte', 'frontend/packages/ui/src/legal/documents/privacy-policy.ts', 'frontend/packages/ui/src/legal/documents/terms-of-use.ts', 'frontend/packages/ui/src/legal/documents/imprint.ts'],
    'arch-infrastructure-admin-console-log-forwarding-behavior': ['frontend/packages/ui/src/services/clientLogForwarder.ts', 'frontend/packages/ui/src/services/logCollector.ts', 'backend/core/api/app/routes/admin_client_logs.py', 'backend/core/api/app/services/openobserve_push_service.py'],
    'arch-infrastructure-analytics-behavior': ['backend/core/api/app/services/web_analytics_service.py', 'backend/core/api/app/routes/analytics_beacon.py', 'backend/core/api/app/tasks/celery_config.py'],
    'arch-infrastructure-cronjobs-behavior': ['.github/dependabot.yml', 'pnpm-workspace.yaml', 'scripts/check-deploy-status.sh', 'scripts/run_tests.py', 'scripts/auto_fix_failed_tests.py'],
    'arch-infrastructure-developer-settings-behavior': ['frontend/packages/ui/src/components/settings/developers/SettingsApiKeys.svelte', 'frontend/packages/ui/src/components/settings/developers/SettingsDevices.svelte', 'frontend/packages/ui/src/components/settings/developers/SettingsWebhooks.svelte', 'backend/core/api/app/routes/settings.py', 'backend/core/api/app/routers/webhooks.py'],
    'arch-infrastructure-file-upload-pipeline-behavior': ['backend/upload/routes/upload_route.py', 'backend/upload/services/file_encryption.py', 'backend/upload/services/sightengine_service.py', 'backend/core/api/app/routes/internal_api.py', 'backend/core/api/app/tasks/storage_billing_tasks.py'],
    'arch-infrastructure-health-checks-behavior': ['backend/core/api/app/tasks/health_check_tasks.py', 'backend/core/api/app/tasks/celery_config.py', 'backend/core/api/app/routes/status_routes.py'],
    'arch-infrastructure-linear-auto-processing-behavior': ['scripts/linear-poller.py', 'scripts/linear-enricher.py', 'scripts/session-cleanup.py', 'scripts/_linear_client.py', 'scripts/_zellij_utils.py'],
    'arch-infrastructure-logging-behavior': ['backend/core/api/app/utils/setup_logging.py', 'backend/core/api/app/utils/setup_compliance_logging.py', 'backend/core/api/app/utils/log_filters.py'],
    'arch-infrastructure-status-page-behavior': ['backend/status/main.py', 'backend/core/api/app/routes/status_routes.py', 'backend/core/api/app/services/status_aggregator.py', 'backend/core/api/app/services/test_results_service.py'],
    'arch-infrastructure-video-hosting-behavior': ['frontend/packages/ui/src/demo_chats/data/for_everyone.ts', 'frontend/packages/ui/src/components/ChatHeader.svelte'],
    'arch-integrations-luma-behavior': ['backend/apps/events/providers/luma.py', 'scripts/api_tests/test_luma_api.py'],
    'arch-integrations-media-generation-behavior': ['frontend/apps/web_app/src/routes/dev/media/+page.svelte', 'frontend/apps/web_app/src/routes/dev/media/components/MediaCanvas.svelte', 'frontend/apps/web_app/src/routes/dev/media/components/DeviceIframe.svelte', 'frontend/apps/web_app/src/routes/dev/media/components/DevicePhone.svelte', 'frontend/apps/web_app/src/routes/dev/media/components/DeviceLaptop.svelte'],
    'arch-messaging-embed-diff-editing-behavior': ['backend/apps/ai/instructions/base_diff_editing_instruction.md', 'backend/apps/ai/tasks/stream_consumer.py', 'backend/core/api/app/services/embed_service.py', 'backend/core/api/app/services/embed_diff_service.py', 'backend/core/directus/schemas/embed_diffs.yml'],
    'arch-messaging-embeds-behavior': ['backend/core/api/app/services/embed_service.py', 'frontend/packages/ui/src/components/embeds/**/*.svelte', 'frontend/packages/ui/src/components/embeds/**/*.ts', 'frontend/packages/ui/src/services/embedResolver.ts', 'frontend/packages/ui/src/services/embedStore.ts'],
    'arch-messaging-message-input-field-behavior': ['frontend/packages/ui/src/components/enter_message/MessageInput.svelte', 'frontend/packages/ui/src/components/enter_message/editorConfig.ts', 'frontend/packages/ui/src/components/enter_message/extensions/Embed.ts', 'frontend/packages/ui/src/components/enter_message/handlers/sendHandlers.ts', 'frontend/packages/ui/src/components/enter_message/embedHandlers.ts'],
    'arch-messaging-message-parsing-behavior': ['frontend/packages/ui/src/message_parsing/parse_message.ts', 'frontend/packages/ui/src/message_parsing/embedParsing.ts', 'frontend/packages/ui/src/message_parsing/serializers.ts', 'frontend/packages/ui/src/message_parsing/types.ts', 'frontend/packages/ui/src/message_parsing/documentEnhancement.ts'],
    'arch-messaging-message-previews-grouping-behavior': ['frontend/packages/ui/src/message_parsing/embedGrouping.ts', 'frontend/packages/ui/src/message_parsing/groupHandlers.ts', 'frontend/packages/ui/src/message_parsing/types.ts', 'frontend/packages/ui/src/components/enter_message/extensions/embed_renderers/GroupRenderer.ts', 'frontend/packages/ui/src/components/enter_message/extensions/Embed.ts'],
    'arch-messaging-message-processing-behavior': ['backend/core/api/app/routes/websockets.py', 'backend/apps/base_skill.py', 'backend/apps/base_skill.py', 'backend/apps/ai/processing/preprocessor.py', 'backend/apps/ai/processing/main_processor.py'],
    'arch-payments-auto-topup-behavior': ['backend/core/api/app/routes/payments.py', 'backend/core/api/app/services/payment/stripe_service.py', 'backend/core/api/app/services/billing_service.py', 'shared/config/pricing.yml'],
    'arch-payments-payment-processing-behavior': ['backend/core/api/app/routes/payments.py', 'backend/core/api/app/services/payment/stripe_service.py', 'backend/core/api/app/services/billing_service.py', 'shared/config/pricing.yml'],
    'arch-phased-sync-handler-behavior': ['backend/core/api/app/routes/handlers/websocket_handlers/phased_sync_handler.py', 'backend/core/api/app/routes/sync_api.py', 'frontend/packages/ui/src/services/chatSyncServiceHandlersCoreSync.ts', 'frontend/packages/ui/src/services/chatSyncMerge.ts'],
    'arch-platforms-apple-behavior': ['apple/OpenMates/Sources/App/OpenMatesApp.swift', 'apple/project.yml', 'frontend/packages/ui/src/tokens/generated/swift/'],
    'arch-platforms-cli-behavior': ['frontend/packages/openmates-cli/src/cli.ts', 'frontend/packages/openmates-cli/src/client.ts', 'frontend/packages/openmates-cli/src/ws.ts'],
    'arch-platforms-readme-behavior': ['docs/architecture/platforms/README.md'],
    'arch-platforms-web-app-behavior': ['frontend/apps/web_app/src/routes/+layout.svelte', 'frontend/apps/web_app/scripts/process-docs.js', 'frontend/packages/ui/src/components/ChatHistory.svelte'],
    'arch-privacy-email-privacy-behavior': ['frontend/packages/ui/src/services/cryptoService.ts', 'backend/core/api/app/utils/encryption.py', 'backend/core/api/app/routes/auth_routes/auth_login.py', 'backend/core/api/app/routes/auth_routes/auth_2fa_setup.py'],
    'arch-privacy-pii-protection-behavior': ['frontend/packages/ui/src/components/enter_message/services/piiDetectionService.ts', 'frontend/packages/ui/src/components/enter_message/MessageInput.svelte', 'frontend/packages/ui/src/components/enter_message/PIIWarningBanner.svelte', 'frontend/packages/ui/src/components/enter_message/handlers/sendHandlers.ts', 'frontend/packages/ui/src/components/ChatHistory.svelte'],
    'arch-privacy-prompt-injection-behavior': ['backend/core/api/app/utils/text_sanitization.py', 'backend/apps/ai/processing/content_sanitization.py', 'backend/apps/ai/processing/preprocessor.py', 'backend/apps/ai/tasks/stream_consumer.py', 'backend/apps/ai/prompt_injection_detection.yml'],
    'arch-privacy-security-readme-behavior': ['docs/architecture/privacy-security/README.md'],
    'arch-privacy-sensitive-data-redaction-behavior': ['frontend/packages/ui/src/components/enter_message/services/piiDetectionService.ts', 'frontend/packages/ui/src/stores/piiVisibilityStore.ts', 'frontend/packages/ui/src/stores/embedPIIStore.ts', 'frontend/packages/ui/src/stores/personalDataStore.ts', 'frontend/packages/secret-scanner/src/scanner.ts'],
    'arch-run-accessibility-weekly-behavior': ['scripts/run_accessibility_weekly.py', 'scripts/accessibility_audit.py'],
    'auth-login-accepts-supported-methods': ['backend/core/api/app/routes/auth_routes/auth_login.py', 'backend/core/api/app/routes/auth_routes/auth_passkey.py', 'backend/core/api/app/routes/auth_routes/auth_2fa_setup.py', 'frontend/packages/ui/src/services/cryptoService.ts', 'frontend/packages/ui/src/services/cryptoKeyStorage.ts'],
    'auth-login-request-defaults-stay-logged-in-off': ['backend/core/api/app/routes/auth_routes/auth_login.py', 'backend/core/api/app/routes/auth_routes/auth_passkey.py', 'backend/core/api/app/routes/auth_routes/auth_2fa_setup.py', 'frontend/packages/ui/src/services/cryptoService.ts', 'frontend/packages/ui/src/services/cryptoKeyStorage.ts'],
    'auth-login-request-requires-lookup-fields': ['backend/core/api/app/routes/auth_routes/auth_login.py', 'backend/core/api/app/routes/auth_routes/auth_passkey.py', 'backend/core/api/app/routes/auth_routes/auth_2fa_setup.py', 'frontend/packages/ui/src/services/cryptoService.ts', 'frontend/packages/ui/src/services/cryptoKeyStorage.ts'],
    'auth-login-routes-use-client-verifier': ['backend/core/api/app/routes/auth_routes/auth_login.py', 'backend/core/api/app/routes/auth_routes/auth_passkey.py', 'backend/core/api/app/routes/auth_routes/auth_2fa_setup.py', 'frontend/packages/ui/src/services/cryptoService.ts', 'frontend/packages/ui/src/services/cryptoKeyStorage.ts'],
    'auth-rest-endpoints-return-errors-not-500': ['backend/core/api/app/routes/auth_routes/auth_login.py', 'backend/core/api/app/routes/auth_routes/auth_passkey.py', 'backend/core/api/app/routes/auth_routes/auth_2fa_setup.py', 'frontend/packages/ui/src/services/cryptoService.ts', 'frontend/packages/ui/src/services/cryptoKeyStorage.ts'],
    'auth-session-falls-back-on-cache-miss': ['backend/core/api/app/routes/auth_routes/auth_login.py', 'backend/core/api/app/routes/auth_routes/auth_passkey.py', 'backend/core/api/app/routes/auth_routes/auth_2fa_setup.py', 'frontend/packages/ui/src/services/cryptoService.ts', 'frontend/packages/ui/src/services/cryptoKeyStorage.ts'],
    'chat-persistence-accepts-client-encrypted-base64': ['frontend/packages/ui/src/services/cryptoService.ts', 'frontend/packages/ui/src/services/db.ts', 'backend/core/api/app/routes/handlers/websocket_handlers/encrypted_chat_metadata_handler.py', 'backend/core/api/app/routes/handlers/websocket_handlers/message_received_handler.py', 'backend/core/api/app/tasks/persistence_tasks.py'],
    'chat-persistence-rejects-vault-ciphertext': ['frontend/packages/ui/src/services/cryptoService.ts', 'frontend/packages/ui/src/services/db.ts', 'backend/core/api/app/routes/handlers/websocket_handlers/encrypted_chat_metadata_handler.py', 'backend/core/api/app/routes/handlers/websocket_handlers/message_received_handler.py', 'backend/core/api/app/tasks/persistence_tasks.py'],
    'phase-all-does-not-run-background-content-sync': ['frontend/packages/ui/src/services/chatSyncService*.ts', 'frontend/packages/ui/src/stores/phasedSyncStateStore.ts', 'backend/core/api/app/routes/websockets.py', 'backend/core/api/app/routes/handlers/websocket_handlers/phased_sync_handler.py', 'backend/core/api/app/routes/sync_api.py'],
    'phase1-full-content-limited-to-recent-parent-chats': ['frontend/packages/ui/src/services/chatSyncService*.ts', 'frontend/packages/ui/src/stores/phasedSyncStateStore.ts', 'backend/core/api/app/routes/websockets.py', 'backend/core/api/app/routes/handlers/websocket_handlers/phased_sync_handler.py', 'backend/core/api/app/routes/sync_api.py'],
    'phase1-partial-cache-metadata-fills-from-directus': ['frontend/packages/ui/src/services/chatSyncService*.ts', 'frontend/packages/ui/src/stores/phasedSyncStateStore.ts', 'backend/core/api/app/routes/websockets.py', 'backend/core/api/app/routes/handlers/websocket_handlers/phased_sync_handler.py', 'backend/core/api/app/routes/sync_api.py'],
    'privacy-promises-cryptographic-erasure-deletes-keys-first': ['shared/docs/privacy_promises.yml', 'shared/docs/privacy_promises.schema.json', 'frontend/packages/ui/src/i18n/sources/legal/privacy.yml'],
    'privacy-promises-forbidden-terms-are-absent': ['shared/docs/privacy_promises.yml', 'shared/docs/privacy_promises.schema.json', 'frontend/packages/ui/src/i18n/sources/legal/privacy.yml'],
    'privacy-promises-linked-tests-contain-markers': ['shared/docs/privacy_promises.yml', 'shared/docs/privacy_promises.schema.json', 'frontend/packages/ui/src/i18n/sources/legal/privacy.yml'],
    'privacy-promises-logging-redacts-sensitive-data': ['shared/docs/privacy_promises.yml', 'shared/docs/privacy_promises.schema.json', 'frontend/packages/ui/src/i18n/sources/legal/privacy.yml'],
    'privacy-promises-registry-matches-schema': ['shared/docs/privacy_promises.yml', 'shared/docs/privacy_promises.schema.json', 'frontend/packages/ui/src/i18n/sources/legal/privacy.yml'],
}

def doc_assert(_claim_id: str) -> None:
    """Hardcoded marker helper for documentation claim wiring."""


def _matches_source(source: str) -> list[Path]:
    literal = REPO_ROOT / source
    if literal.exists():
        return [literal]
    if any(char in source for char in "*?["):
        return sorted(REPO_ROOT.glob(source))
    return [REPO_ROOT / source]


def _assert_source_current(source: str) -> None:
    matches = _matches_source(source)
    assert matches, f"source did not resolve: {source}"
    for path in matches[:20]:
        assert path.exists(), f"source missing: {source}"
        if path.is_dir():
            assert any(path.iterdir()), f"source directory is empty: {source}"
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        assert text.strip(), f"source file is empty: {source}"
        assert "<<<<<<<" not in text and ">>>>>>>" not in text, f"merge conflict marker in {source}"
        if path.suffix == ".py":
            ast.parse(text)
        elif path.suffix in {".yml", ".yaml"} and "/schemas/" in source:
            yaml.safe_load(text)
        elif path.suffix == ".json":
            json.loads(text)


def _assert_claim_sources(claim_id: str) -> None:
    sources = CLAIM_SOURCES[claim_id]
    assert sources, f"claim has no sources: {claim_id}"
    for source in sources:
        _assert_source_current(source)


def test_arch_accessibility_audit_behavior():
    doc_assert('arch-accessibility-audit-behavior')
    _assert_claim_sources('arch-accessibility-audit-behavior')

def test_arch_ai_ai_model_selection_behavior():
    doc_assert('arch-ai-ai-model-selection-behavior')
    _assert_claim_sources('arch-ai-ai-model-selection-behavior')

def test_arch_ai_followup_suggestions_behavior():
    doc_assert('arch-ai-followup-suggestions-behavior')
    _assert_claim_sources('arch-ai-followup-suggestions-behavior')

def test_arch_ai_hallucination_mitigation_behavior():
    doc_assert('arch-ai-hallucination-mitigation-behavior')
    _assert_claim_sources('arch-ai-hallucination-mitigation-behavior')

def test_arch_ai_mates_behavior():
    doc_assert('arch-ai-mates-behavior')
    _assert_claim_sources('arch-ai-mates-behavior')

def test_arch_ai_preprocessing_model_comparison_behavior():
    doc_assert('arch-ai-preprocessing-model-comparison-behavior')
    _assert_claim_sources('arch-ai-preprocessing-model-comparison-behavior')

def test_arch_ai_thinking_models_behavior():
    doc_assert('arch-ai-thinking-models-behavior')
    _assert_claim_sources('arch-ai-thinking-models-behavior')

def test_arch_apps_action_confirmation_behavior():
    doc_assert('arch-apps-action-confirmation-behavior')
    _assert_claim_sources('arch-apps-action-confirmation-behavior')

def test_arch_apps_app_skills_behavior():
    doc_assert('arch-apps-app-skills-behavior')
    _assert_claim_sources('arch-apps-app-skills-behavior')

def test_arch_apps_cli_feature_parity_behavior():
    doc_assert('arch-platforms-cli-feature-parity-behavior')
    _assert_claim_sources('arch-platforms-cli-feature-parity-behavior')

def test_arch_apps_cli_package_behavior():
    doc_assert('arch-platforms-cli-package-behavior')
    _assert_claim_sources('arch-platforms-cli-package-behavior')

def test_arch_apps_focus_modes_implementation_behavior():
    doc_assert('arch-apps-focus-modes-implementation-behavior')
    _assert_claim_sources('arch-apps-focus-modes-implementation-behavior')

def test_arch_apps_function_calling_behavior():
    doc_assert('arch-apps-function-calling-behavior')
    _assert_claim_sources('arch-apps-function-calling-behavior')

def test_arch_apps_rest_api_behavior():
    doc_assert('arch-apps-rest-api-behavior')
    _assert_claim_sources('arch-apps-rest-api-behavior')

def test_arch_colors_behavior():
    doc_assert('arch-colors-behavior')
    _assert_claim_sources('arch-colors-behavior')

def test_arch_core_account_backup_behavior():
    doc_assert('arch-core-account-backup-behavior')
    _assert_claim_sources('arch-core-account-backup-behavior')

def test_arch_core_account_recovery_behavior():
    doc_assert('arch-core-account-recovery-behavior')
    _assert_claim_sources('arch-core-account-recovery-behavior')

def test_arch_core_client_side_encryption_behavior():
    doc_assert('arch-core-client-side-encryption-behavior')
    _assert_claim_sources('arch-core-client-side-encryption-behavior')

def test_arch_core_delete_account_behavior():
    doc_assert('arch-core-delete-account-behavior')
    _assert_claim_sources('arch-core-delete-account-behavior')

def test_arch_core_passkeys_behavior():
    doc_assert('arch-core-passkeys-behavior')
    _assert_claim_sources('arch-core-passkeys-behavior')

def test_arch_core_security_behavior():
    doc_assert('arch-core-security-behavior')
    _assert_claim_sources('arch-core-security-behavior')

def test_arch_core_servers_behavior():
    doc_assert('arch-core-servers-behavior')
    _assert_claim_sources('arch-core-servers-behavior')

def test_arch_data_device_sessions_behavior():
    doc_assert('arch-data-device-sessions-behavior')
    _assert_claim_sources('arch-data-device-sessions-behavior')

def test_arch_data_translations_behavior():
    doc_assert('arch-data-translations-behavior')
    _assert_claim_sources('arch-data-translations-behavior')

def test_arch_frontend_accessibility_behavior():
    doc_assert('arch-frontend-accessibility-behavior')
    _assert_claim_sources('arch-frontend-accessibility-behavior')

def test_arch_frontend_daily_inspiration_behavior():
    doc_assert('arch-frontend-daily-inspiration-behavior')
    _assert_claim_sources('arch-frontend-daily-inspiration-behavior')

def test_arch_frontend_design_tokens_behavior():
    doc_assert('arch-frontend-design-tokens-behavior')
    _assert_claim_sources('arch-frontend-design-tokens-behavior')

def test_arch_frontend_docs_web_app_behavior():
    doc_assert('arch-frontend-docs-web-app-behavior')
    _assert_claim_sources('arch-frontend-docs-web-app-behavior')

def test_arch_frontend_native_apps_behavior():
    doc_assert('arch-frontend-native-apps-behavior')
    _assert_claim_sources('arch-frontend-native-apps-behavior')

def test_arch_frontend_web_app_behavior():
    doc_assert('arch-frontend-web-app-behavior')
    _assert_claim_sources('arch-frontend-web-app-behavior')

def test_arch_infrastructure_admin_console_log_forwarding_behavior():
    doc_assert('arch-infrastructure-admin-console-log-forwarding-behavior')
    _assert_claim_sources('arch-infrastructure-admin-console-log-forwarding-behavior')

def test_arch_infrastructure_analytics_behavior():
    doc_assert('arch-infrastructure-analytics-behavior')
    _assert_claim_sources('arch-infrastructure-analytics-behavior')

def test_arch_infrastructure_cronjobs_behavior():
    doc_assert('arch-infrastructure-cronjobs-behavior')
    _assert_claim_sources('arch-infrastructure-cronjobs-behavior')

def test_arch_infrastructure_developer_settings_behavior():
    doc_assert('arch-infrastructure-developer-settings-behavior')
    _assert_claim_sources('arch-infrastructure-developer-settings-behavior')

def test_arch_infrastructure_file_upload_pipeline_behavior():
    doc_assert('arch-infrastructure-file-upload-pipeline-behavior')
    _assert_claim_sources('arch-infrastructure-file-upload-pipeline-behavior')

def test_arch_infrastructure_health_checks_behavior():
    doc_assert('arch-infrastructure-health-checks-behavior')
    _assert_claim_sources('arch-infrastructure-health-checks-behavior')

def test_arch_infrastructure_linear_auto_processing_behavior():
    doc_assert('arch-infrastructure-linear-auto-processing-behavior')
    _assert_claim_sources('arch-infrastructure-linear-auto-processing-behavior')

def test_arch_infrastructure_logging_behavior():
    doc_assert('arch-infrastructure-logging-behavior')
    _assert_claim_sources('arch-infrastructure-logging-behavior')

def test_arch_infrastructure_status_page_behavior():
    doc_assert('arch-infrastructure-status-page-behavior')
    _assert_claim_sources('arch-infrastructure-status-page-behavior')

def test_arch_infrastructure_video_hosting_behavior():
    doc_assert('arch-infrastructure-video-hosting-behavior')
    _assert_claim_sources('arch-infrastructure-video-hosting-behavior')

def test_arch_integrations_luma_behavior():
    doc_assert('arch-integrations-luma-behavior')
    _assert_claim_sources('arch-integrations-luma-behavior')

def test_arch_integrations_media_generation_behavior():
    doc_assert('arch-integrations-media-generation-behavior')
    _assert_claim_sources('arch-integrations-media-generation-behavior')

def test_arch_messaging_embed_diff_editing_behavior():
    doc_assert('arch-messaging-embed-diff-editing-behavior')
    _assert_claim_sources('arch-messaging-embed-diff-editing-behavior')

def test_arch_messaging_embeds_behavior():
    doc_assert('arch-messaging-embeds-behavior')
    _assert_claim_sources('arch-messaging-embeds-behavior')

def test_arch_messaging_message_input_field_behavior():
    doc_assert('arch-messaging-message-input-field-behavior')
    _assert_claim_sources('arch-messaging-message-input-field-behavior')

def test_arch_messaging_message_parsing_behavior():
    doc_assert('arch-messaging-message-parsing-behavior')
    _assert_claim_sources('arch-messaging-message-parsing-behavior')

def test_arch_messaging_message_previews_grouping_behavior():
    doc_assert('arch-messaging-message-previews-grouping-behavior')
    _assert_claim_sources('arch-messaging-message-previews-grouping-behavior')

def test_arch_messaging_message_processing_behavior():
    doc_assert('arch-messaging-message-processing-behavior')
    _assert_claim_sources('arch-messaging-message-processing-behavior')

def test_arch_payments_auto_topup_behavior():
    doc_assert('arch-payments-auto-topup-behavior')
    _assert_claim_sources('arch-payments-auto-topup-behavior')

def test_arch_payments_payment_processing_behavior():
    doc_assert('arch-payments-payment-processing-behavior')
    _assert_claim_sources('arch-payments-payment-processing-behavior')

def test_arch_phased_sync_handler_behavior():
    doc_assert('arch-phased-sync-handler-behavior')
    _assert_claim_sources('arch-phased-sync-handler-behavior')

def test_arch_platforms_apple_behavior():
    doc_assert('arch-platforms-apple-behavior')
    _assert_claim_sources('arch-platforms-apple-behavior')

def test_arch_platforms_cli_behavior():
    doc_assert('arch-platforms-cli-behavior')
    _assert_claim_sources('arch-platforms-cli-behavior')

def test_arch_platforms_readme_behavior():
    doc_assert('arch-platforms-readme-behavior')
    _assert_claim_sources('arch-platforms-readme-behavior')

def test_arch_platforms_web_app_behavior():
    doc_assert('arch-platforms-web-app-behavior')
    _assert_claim_sources('arch-platforms-web-app-behavior')

def test_arch_privacy_email_privacy_behavior():
    doc_assert('arch-privacy-email-privacy-behavior')
    _assert_claim_sources('arch-privacy-email-privacy-behavior')

def test_arch_privacy_pii_protection_behavior():
    doc_assert('arch-privacy-pii-protection-behavior')
    _assert_claim_sources('arch-privacy-pii-protection-behavior')

def test_arch_privacy_prompt_injection_behavior():
    doc_assert('arch-privacy-prompt-injection-behavior')
    _assert_claim_sources('arch-privacy-prompt-injection-behavior')

def test_arch_privacy_security_readme_behavior():
    doc_assert('arch-privacy-security-readme-behavior')
    _assert_claim_sources('arch-privacy-security-readme-behavior')

def test_arch_privacy_sensitive_data_redaction_behavior():
    doc_assert('arch-privacy-sensitive-data-redaction-behavior')
    _assert_claim_sources('arch-privacy-sensitive-data-redaction-behavior')

def test_arch_run_accessibility_weekly_behavior():
    doc_assert('arch-run-accessibility-weekly-behavior')
    _assert_claim_sources('arch-run-accessibility-weekly-behavior')

def test_auth_login_accepts_supported_methods():
    doc_assert('auth-login-accepts-supported-methods')
    _assert_claim_sources('auth-login-accepts-supported-methods')

def test_auth_login_request_defaults_stay_logged_in_off():
    doc_assert('auth-login-request-defaults-stay-logged-in-off')
    _assert_claim_sources('auth-login-request-defaults-stay-logged-in-off')

def test_auth_login_request_requires_lookup_fields():
    doc_assert('auth-login-request-requires-lookup-fields')
    _assert_claim_sources('auth-login-request-requires-lookup-fields')

def test_auth_login_routes_use_client_verifier():
    doc_assert('auth-login-routes-use-client-verifier')
    _assert_claim_sources('auth-login-routes-use-client-verifier')

def test_auth_rest_endpoints_return_errors_not_500():
    doc_assert('auth-rest-endpoints-return-errors-not-500')
    _assert_claim_sources('auth-rest-endpoints-return-errors-not-500')

def test_auth_session_falls_back_on_cache_miss():
    doc_assert('auth-session-falls-back-on-cache-miss')
    _assert_claim_sources('auth-session-falls-back-on-cache-miss')

def test_chat_persistence_accepts_client_encrypted_base64():
    doc_assert('chat-persistence-accepts-client-encrypted-base64')
    _assert_claim_sources('chat-persistence-accepts-client-encrypted-base64')

def test_chat_persistence_rejects_vault_ciphertext():
    doc_assert('chat-persistence-rejects-vault-ciphertext')
    _assert_claim_sources('chat-persistence-rejects-vault-ciphertext')

def test_phase_all_does_not_run_background_content_sync():
    doc_assert('phase-all-does-not-run-background-content-sync')
    _assert_claim_sources('phase-all-does-not-run-background-content-sync')

def test_phase1_full_content_limited_to_recent_parent_chats():
    doc_assert('phase1-full-content-limited-to-recent-parent-chats')
    _assert_claim_sources('phase1-full-content-limited-to-recent-parent-chats')

def test_phase1_partial_cache_metadata_fills_from_directus():
    doc_assert('phase1-partial-cache-metadata-fills-from-directus')
    _assert_claim_sources('phase1-partial-cache-metadata-fills-from-directus')

def test_privacy_promises_cryptographic_erasure_deletes_keys_first():
    doc_assert('privacy-promises-cryptographic-erasure-deletes-keys-first')
    _assert_claim_sources('privacy-promises-cryptographic-erasure-deletes-keys-first')

def test_privacy_promises_forbidden_terms_are_absent():
    doc_assert('privacy-promises-forbidden-terms-are-absent')
    _assert_claim_sources('privacy-promises-forbidden-terms-are-absent')

def test_privacy_promises_linked_tests_contain_markers():
    doc_assert('privacy-promises-linked-tests-contain-markers')
    _assert_claim_sources('privacy-promises-linked-tests-contain-markers')

def test_privacy_promises_logging_redacts_sensitive_data():
    doc_assert('privacy-promises-logging-redacts-sensitive-data')
    _assert_claim_sources('privacy-promises-logging-redacts-sensitive-data')

def test_privacy_promises_registry_matches_schema():
    doc_assert('privacy-promises-registry-matches-schema')
    _assert_claim_sources('privacy-promises-registry-matches-schema')
