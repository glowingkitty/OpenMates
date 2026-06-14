#!/usr/bin/env python3
"""
Regression tests for static architecture source-anchor claims.

Static architecture claims verify source-truth anchors such as files, functions,
classes, route strings, schema fields, and config keys without relying on brittle
line numbers.

Architecture: docs/specs/architecture-docs-claim-coverage/spec.yml
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
MODULE_PATH = PROJECT_ROOT / "scripts" / "docs_static_claims.py"


def docAssertStatic(_claim_id: str) -> None:
    """Hardcoded marker helper for static documentation claims."""


def load_module():
    spec = importlib.util.spec_from_file_location("openmates_docs_static_claims", MODULE_PATH)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def test_static_claims_validate_files_functions_classes_routes_and_schema_fields(tmp_path):
    source = tmp_path / "backend" / "routes.py"
    write(
        source,
        "class AuthService:\n"
        "    pass\n\n"
        "def login_user():\n"
        "    return '/v1/auth/login'\n\n"
        "AUTH_FIELDS = ['encrypted_email', 'lookup_hash']\n",
    )
    doc = tmp_path / "docs" / "architecture" / "auth.md"
    write(
        doc,
        "---\n"
        "status: active\n"
        "claims:\n"
        "  - id: arch-auth-static-anchors\n"
        "    type: static\n"
        "    file: scripts/tests/test_architecture_static_claims.py\n"
        "    assertion: arch-auth-static-anchors\n"
        "    anchors:\n"
        "      - type: file_exists\n"
        "        path: backend/routes.py\n"
        "      - type: class\n"
        "        path: backend/routes.py\n"
        "        name: AuthService\n"
        "      - type: function\n"
        "        path: backend/routes.py\n"
        "        name: login_user\n"
        "      - type: route\n"
        "        path: backend/routes.py\n"
        "        value: /v1/auth/login\n"
        "      - type: schema_field\n"
        "        path: backend/routes.py\n"
        "        name: encrypted_email\n"
        "---\n"
        "# Auth\n",
    )
    docAssertStatic("arch-auth-static-anchors")
    module = load_module()

    result = module.validate_static_claims([doc], repo_root=tmp_path)

    assert result.errors == []
    assert result.checked_claims == 1
    assert result.checked_anchors == 5


def test_static_claims_fail_for_missing_anchor_and_line_number_links(tmp_path):
    source = tmp_path / "backend" / "routes.py"
    write(source, "def other():\n    pass\n")
    doc = tmp_path / "docs" / "architecture" / "auth.md"
    write(
        doc,
        "---\n"
        "status: active\n"
        "claims:\n"
        "  - id: arch-auth-missing-anchor\n"
        "    type: static\n"
        "    file: scripts/tests/test_architecture_static_claims.py\n"
        "    assertion: arch-auth-missing-anchor\n"
        "    anchors:\n"
        "      - type: function\n"
        "        path: backend/routes.py\n"
        "        name: login_user\n"
        "---\n"
        "# Auth\n\n"
        "[Bad line link](../../backend/routes.py#L10)\n",
    )
    docAssertStatic("arch-auth-missing-anchor")
    module = load_module()

    result = module.validate_static_claims([doc], repo_root=tmp_path)

    assert any("login_user" in error for error in result.errors)
    assert any("line-number link" in error for error in result.errors)


# BEGIN GENERATED ARCHITECTURE STATIC CLAIM MARKERS

def test_architecture_doc_static_claim_markers_are_declared():
    docAssertStatic("arch-accessibility-audit-source-1")
    docAssertStatic("arch-accessibility-audit-source-2")
    docAssertStatic("arch-ai-ai-model-selection-source-1")
    docAssertStatic("arch-ai-ai-model-selection-source-2")
    docAssertStatic("arch-ai-ai-model-selection-source-3")
    docAssertStatic("arch-ai-followup-suggestions-source-1")
    docAssertStatic("arch-ai-followup-suggestions-source-2")
    docAssertStatic("arch-ai-followup-suggestions-source-3")
    docAssertStatic("arch-ai-hallucination-mitigation-source-1")
    docAssertStatic("arch-ai-hallucination-mitigation-source-2")
    docAssertStatic("arch-ai-hallucination-mitigation-source-3")
    docAssertStatic("arch-ai-mates-source-1")
    docAssertStatic("arch-ai-mates-source-2")
    docAssertStatic("arch-ai-mates-source-3")
    docAssertStatic("arch-ai-preprocessing-model-comparison-source-1")
    docAssertStatic("arch-ai-preprocessing-model-comparison-source-2")
    docAssertStatic("arch-ai-preprocessing-model-comparison-source-3")
    docAssertStatic("arch-ai-thinking-models-source-1")
    docAssertStatic("arch-ai-thinking-models-source-2")
    docAssertStatic("arch-ai-thinking-models-source-3")
    docAssertStatic("arch-apps-action-confirmation-source-1")
    docAssertStatic("arch-apps-action-confirmation-source-2")
    docAssertStatic("arch-apps-app-skills-source-1")
    docAssertStatic("arch-apps-app-skills-source-2")
    docAssertStatic("arch-apps-app-skills-source-3")
    docAssertStatic("arch-platforms-cli-feature-parity-source-1")
    docAssertStatic("arch-platforms-cli-feature-parity-source-2")
    docAssertStatic("arch-platforms-cli-feature-parity-source-3")
    docAssertStatic("arch-platforms-cli-package-source-1")
    docAssertStatic("arch-platforms-cli-package-source-2")
    docAssertStatic("arch-platforms-cli-package-source-3")
    docAssertStatic("arch-apps-focus-modes-implementation-source-1")
    docAssertStatic("arch-apps-focus-modes-implementation-source-2")
    docAssertStatic("arch-apps-focus-modes-implementation-source-3")
    docAssertStatic("arch-apps-function-calling-source-1")
    docAssertStatic("arch-apps-function-calling-source-2")
    docAssertStatic("arch-apps-function-calling-source-3")
    docAssertStatic("arch-apps-rest-api-source-1")
    docAssertStatic("arch-apps-rest-api-source-2")
    docAssertStatic("arch-apps-rest-api-source-3")
    docAssertStatic("arch-colors-source-1")
    docAssertStatic("arch-colors-source-2")
    docAssertStatic("arch-core-account-backup-source-1")
    docAssertStatic("arch-core-account-backup-source-2")
    docAssertStatic("arch-core-account-backup-source-3")
    docAssertStatic("arch-core-account-recovery-source-1")
    docAssertStatic("arch-core-account-recovery-source-2")
    docAssertStatic("arch-core-account-recovery-source-3")
    docAssertStatic("arch-core-chat-encryption-implementation-source-1")
    docAssertStatic("arch-core-client-side-encryption-source-1")
    docAssertStatic("arch-core-client-side-encryption-source-2")
    docAssertStatic("arch-core-client-side-encryption-source-3")
    docAssertStatic("arch-core-delete-account-source-1")
    docAssertStatic("arch-core-delete-account-source-2")
    docAssertStatic("arch-core-delete-account-source-3")
    docAssertStatic("arch-core-passkeys-source-1")
    docAssertStatic("arch-core-passkeys-source-2")
    docAssertStatic("arch-core-passkeys-source-3")
    docAssertStatic("arch-core-security-source-1")
    docAssertStatic("arch-core-security-source-2")
    docAssertStatic("arch-core-security-source-3")
    docAssertStatic("arch-core-servers-source-1")
    docAssertStatic("arch-core-servers-source-2")
    docAssertStatic("arch-core-servers-source-3")
    docAssertStatic("arch-core-signup-and-auth-source-1")
    docAssertStatic("arch-data-device-sessions-source-1")
    docAssertStatic("arch-data-device-sessions-source-2")
    docAssertStatic("arch-data-sync-source-1")
    docAssertStatic("arch-data-translations-source-1")
    docAssertStatic("arch-data-translations-source-2")
    docAssertStatic("arch-data-translations-source-3")
    docAssertStatic("arch-frontend-accessibility-source-1")
    docAssertStatic("arch-frontend-accessibility-source-2")
    docAssertStatic("arch-frontend-accessibility-source-3")
    docAssertStatic("arch-frontend-daily-inspiration-source-1")
    docAssertStatic("arch-frontend-daily-inspiration-source-2")
    docAssertStatic("arch-frontend-daily-inspiration-source-3")
    docAssertStatic("arch-frontend-design-tokens-source-1")
    docAssertStatic("arch-frontend-design-tokens-source-2")
    docAssertStatic("arch-frontend-design-tokens-source-3")
    docAssertStatic("arch-frontend-docs-web-app-source-1")
    docAssertStatic("arch-frontend-docs-web-app-source-2")
    docAssertStatic("arch-frontend-docs-web-app-source-3")
    docAssertStatic("arch-frontend-native-apps-source-1")
    docAssertStatic("arch-frontend-native-apps-source-2")
    docAssertStatic("arch-frontend-native-apps-source-3")
    docAssertStatic("arch-frontend-web-app-source-1")
    docAssertStatic("arch-frontend-web-app-source-2")
    docAssertStatic("arch-frontend-web-app-source-3")
    docAssertStatic("arch-infrastructure-admin-console-log-forwarding-source-1")
    docAssertStatic("arch-infrastructure-admin-console-log-forwarding-source-2")
    docAssertStatic("arch-infrastructure-admin-console-log-forwarding-source-3")
    docAssertStatic("arch-infrastructure-analytics-source-1")
    docAssertStatic("arch-infrastructure-analytics-source-2")
    docAssertStatic("arch-infrastructure-analytics-source-3")
    docAssertStatic("arch-infrastructure-cronjobs-source-1")
    docAssertStatic("arch-infrastructure-cronjobs-source-2")
    docAssertStatic("arch-infrastructure-cronjobs-source-3")
    docAssertStatic("arch-infrastructure-developer-settings-source-1")
    docAssertStatic("arch-infrastructure-developer-settings-source-2")
    docAssertStatic("arch-infrastructure-developer-settings-source-3")
    docAssertStatic("arch-infrastructure-file-upload-pipeline-source-1")
    docAssertStatic("arch-infrastructure-file-upload-pipeline-source-2")
    docAssertStatic("arch-infrastructure-file-upload-pipeline-source-3")
    docAssertStatic("arch-infrastructure-health-checks-source-1")
    docAssertStatic("arch-infrastructure-health-checks-source-2")
    docAssertStatic("arch-infrastructure-health-checks-source-3")
    docAssertStatic("arch-infrastructure-linear-auto-processing-source-1")
    docAssertStatic("arch-infrastructure-linear-auto-processing-source-2")
    docAssertStatic("arch-infrastructure-linear-auto-processing-source-3")
    docAssertStatic("arch-infrastructure-logging-source-1")
    docAssertStatic("arch-infrastructure-logging-source-2")
    docAssertStatic("arch-infrastructure-logging-source-3")
    docAssertStatic("arch-infrastructure-status-page-source-1")
    docAssertStatic("arch-infrastructure-status-page-source-2")
    docAssertStatic("arch-infrastructure-status-page-source-3")
    docAssertStatic("arch-infrastructure-video-hosting-source-1")
    docAssertStatic("arch-infrastructure-video-hosting-source-2")
    docAssertStatic("arch-integrations-luma-source-1")
    docAssertStatic("arch-integrations-luma-source-2")
    docAssertStatic("arch-integrations-media-generation-source-1")
    docAssertStatic("arch-integrations-media-generation-source-2")
    docAssertStatic("arch-integrations-media-generation-source-3")
    docAssertStatic("arch-messaging-embed-diff-editing-source-1")
    docAssertStatic("arch-messaging-embed-diff-editing-source-2")
    docAssertStatic("arch-messaging-embed-diff-editing-source-3")
    docAssertStatic("arch-messaging-embeds-source-1")
    docAssertStatic("arch-messaging-embeds-source-2")
    docAssertStatic("arch-messaging-embeds-source-3")
    docAssertStatic("arch-messaging-message-input-field-source-1")
    docAssertStatic("arch-messaging-message-input-field-source-2")
    docAssertStatic("arch-messaging-message-input-field-source-3")
    docAssertStatic("arch-messaging-message-parsing-source-1")
    docAssertStatic("arch-messaging-message-parsing-source-2")
    docAssertStatic("arch-messaging-message-parsing-source-3")
    docAssertStatic("arch-messaging-message-previews-grouping-source-1")
    docAssertStatic("arch-messaging-message-previews-grouping-source-2")
    docAssertStatic("arch-messaging-message-previews-grouping-source-3")
    docAssertStatic("arch-messaging-message-processing-source-1")
    docAssertStatic("arch-messaging-message-processing-source-2")
    docAssertStatic("arch-messaging-message-processing-source-3")
    docAssertStatic("arch-payments-auto-topup-source-1")
    docAssertStatic("arch-payments-auto-topup-source-2")
    docAssertStatic("arch-payments-auto-topup-source-3")
    docAssertStatic("arch-payments-payment-processing-source-1")
    docAssertStatic("arch-payments-payment-processing-source-2")
    docAssertStatic("arch-payments-payment-processing-source-3")
    docAssertStatic("arch-phased-sync-handler-source-1")
    docAssertStatic("arch-phased-sync-handler-source-2")
    docAssertStatic("arch-phased-sync-handler-source-3")
    docAssertStatic("arch-platforms-apple-source-1")
    docAssertStatic("arch-platforms-apple-source-2")
    docAssertStatic("arch-platforms-apple-source-3")
    docAssertStatic("arch-platforms-cli-source-1")
    docAssertStatic("arch-platforms-cli-source-2")
    docAssertStatic("arch-platforms-cli-source-3")
    docAssertStatic("arch-platforms-web-app-source-1")
    docAssertStatic("arch-platforms-web-app-source-2")
    docAssertStatic("arch-platforms-web-app-source-3")
    docAssertStatic("arch-privacy-email-privacy-source-1")
    docAssertStatic("arch-privacy-email-privacy-source-2")
    docAssertStatic("arch-privacy-email-privacy-source-3")
    docAssertStatic("arch-privacy-pii-protection-source-1")
    docAssertStatic("arch-privacy-pii-protection-source-2")
    docAssertStatic("arch-privacy-pii-protection-source-3")
    docAssertStatic("arch-privacy-privacy-promises-source-1")
    docAssertStatic("arch-privacy-prompt-injection-source-1")
    docAssertStatic("arch-privacy-prompt-injection-source-2")
    docAssertStatic("arch-privacy-prompt-injection-source-3")
    docAssertStatic("arch-privacy-sensitive-data-redaction-source-1")
    docAssertStatic("arch-privacy-sensitive-data-redaction-source-2")
    docAssertStatic("arch-privacy-sensitive-data-redaction-source-3")
    docAssertStatic("arch-run-accessibility-weekly-source-1")
    docAssertStatic("arch-run-accessibility-weekly-source-2")
# END GENERATED ARCHITECTURE STATIC CLAIM MARKERS
