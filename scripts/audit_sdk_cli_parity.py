#!/usr/bin/env python3
"""Audit CLI-to-SDK parity coverage.

Purpose: keep npm and pip SDK parity from drifting behind CLI commands.
Architecture: source-level audit over CLI command markers and SDK facade methods.
Security: destructive SDK methods must stay explicit and programmatic, not prompts.
Tests: scripts/tests/test_sdk_parity_instructions.py.
Spec: docs/specs/sdk-cli-parity-v1/spec.yml.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re
import sys


ROOT = Path(__file__).resolve().parents[1]
CLI_TS = ROOT / "frontend/packages/openmates-cli/src/cli.ts"
CLI_CLIENT_TS = ROOT / "frontend/packages/openmates-cli/src/client.ts"
SDK_TS = ROOT / "frontend/packages/openmates-cli/src/sdk.ts"
SDK_PY = ROOT / "packages/openmates-python/openmates/sdk.py"
GENERATED_TS = ROOT / "frontend/packages/openmates-cli/src/generated/appSkills.ts"
GENERATED_PY = ROOT / "packages/openmates-python/openmates/generated/app_skills.py"


EXCLUSION_REASONS = {
    "cli-auth-session": "CLI pair-auth/session lifecycle is not API-key SDK behavior.",
    "cli-terminal-tui": "Terminal rendering is CLI-only.",
    "server-ops": "Self-host server operations stay CLI-only.",
    "cli-self-update": "CLI package-manager self-update behavior stays CLI-only.",
    "project-support-info": "Voluntary project support information is a local/public link helper, not SDK API behavior.",
    "e2e-provisioning": "Local test-account artifact tooling stays CLI-only.",
    "local-remote-access": "Local Project source bridge commands operate on user-approved local paths and stay CLI-only.",
    "local-connected-account-setup": "Local connected-account setup supervises user-machine processes and credential prompts, so setup stays CLI-only.",
    "browser-high-risk": "Browser-only or high-risk account/security flow.",
}


TOP_LEVEL_CLASSIFICATION = {
    "help": "cli-terminal-tui",
    "login": "cli-auth-session",
    "signup": "browser-high-risk",
    "logout": "cli-auth-session",
    "whoami": "account.info",
    "chats": "chats.*",
    "drafts": "drafts.*",
    "apps": "apps.<generated>.<skill>",
    "mentions": "mentions via app/focus/memory metadata",
    "embeds": "embeds.*",
    "settings": "account/settings/billing/notifications/memories/reminders.*; newsletter stays CLI-only",
    "connected-accounts": "connectedAccounts.import / connected_accounts.import_account",
    "connect-account": "local-connected-account-setup",
    "learning-mode": "learningMode.* / learning_mode.*",
    "inspirations": "inspirations.list",
    "newchatsuggestions": "newChatSuggestions.list / new_chat_suggestions.list",
    "feedback": "feedback.assistantResponse / feedback.assistant_response",
    "benchmark": "benchmark.*",
    "workflows": "workflows.*",
    "tasks": "tasks.*",
    "remote-access": "local-remote-access",
    "support": "project-support-info",
    "update": "cli-self-update",
    "upgrade": "cli-self-update",
    "version": "cli-self-update",
    "server": "server-ops",
    "docs": "docs.*",
    "e2e": "e2e-provisioning",
}

OPTIONAL_TOP_LEVEL_COMMANDS = {
    "tasks",
}


@dataclass(frozen=True)
class ParityEntry:
    cli_marker: str
    npm: str
    pip: str


@dataclass(frozen=True)
class WorkflowTemplateTransportEntry:
    cli_client: str
    npm: str
    pip: str


PARITY_ENTRIES = [
    ParityEntry('command === "whoami"', "account.info", "account.info"),
    ParityEntry('subcommand === "list"', "chats.list", "chats.list"),
    ParityEntry('subcommand === "search"', "chats.search", "chats.search"),
    ParityEntry('subcommand === "show"', "chats.load", "chats.load"),
    ParityEntry('subcommand === "download"', "chats.export", "chats.export"),
    ParityEntry('subcommand === "delete"', "chats.delete", "chats.delete"),
    ParityEntry('subcommand === "share"', "chats.share", "chats.share"),
    ParityEntry('subcommand === "incognito"', "chats.incognito", "chats.incognito"),
    ParityEntry("openmates drafts list", "drafts.list", "drafts.list"),
    ParityEntry("openmates drafts get", "drafts.get", "drafts.get"),
    ParityEntry('matches(tokens, ["account", "timezone", "set"])', "account.setTimezone", "account.set_timezone"),
    ParityEntry('matches(tokens, ["account", "interests", "list"])', "account.listInterests", "account.list_interests"),
    ParityEntry('matches(tokens, ["account", "interests", "set"])', "account.setInterests", "account.set_interests"),
    ParityEntry('matches(tokens, ["account", "interests", "clear"])', "account.clearInterests", "account.clear_interests"),
    ParityEntry('matches(tokens, ["account", "export", "manifest"])', "account.exportManifest", "account.export_manifest"),
    ParityEntry('matches(tokens, ["account", "export", "data"])', "account.exportData", "account.export_data"),
    ParityEntry('matches(tokens, ["account", "username", "set"])', "account.setUsername", "account.set_username"),
    ParityEntry('matches(tokens, ["account", "storage", "overview"])', "account.storageOverview", "account.storage_overview"),
    ParityEntry('matches(tokens, ["account", "storage", "files"])', "account.storageFiles", "account.storage_files"),
    ParityEntry('matches(tokens, ["account", "storage", "delete"])', "account.deleteStorage", "account.delete_storage"),
    ParityEntry('matches(tokens, ["interface", "language", "set"])', "settings.setLanguage", "settings.set_language"),
    ParityEntry('matches(tokens, ["interface", "dark-mode", "set"])', "settings.setDarkMode", "settings.set_dark_mode"),
    ParityEntry('matches(tokens, ["interface", "font", "set"])', "settings.setFont", "settings.set_font"),
    ParityEntry('matches(tokens, ["ai", "models", "set-defaults"])', "settings.setModelDefaults", "settings.set_model_defaults"),
    ParityEntry('matches(tokens, ["privacy", "auto-delete", "chats", "set"])', "settings.setChatAutoDelete", "settings.set_chat_auto_delete"),
    ParityEntry('matches(tokens, ["privacy", "debug-logs", "share"])', "settings.shareDebugLogs", "settings.share_debug_logs"),
    ParityEntry('matches(tokens, ["developers", "api-keys", "list"])', "apiKeys.list", "api_keys.list"),
    ParityEntry('matches(tokens, ["developers", "api-keys", "create"])', "apiKeys.create", "api_keys.create"),
    ParityEntry('matches(tokens, ["developers", "api-keys", "revoke"])', "apiKeys.revoke", "api_keys.revoke"),
    ParityEntry('matches(tokens, ["billing", "overview"])', "billing.overview", "billing.overview"),
    ParityEntry('matches(tokens, ["billing", "usage"])', "billing.usage", "billing.usage"),
    ParityEntry('matches(tokens, ["billing", "usage", "export"])', "billing.usageExport", "billing.usage_export"),
    ParityEntry('matches(tokens, ["billing", "buy-credits", "bank-transfer"])', "billing.createBankTransferOrder", "billing.create_bank_transfer_order"),
    ParityEntry('matches(tokens, ["billing", "invoices", "list"])', "billing.listInvoices", "billing.list_invoices"),
    ParityEntry('matches(tokens, ["billing", "gift-card", "redeem"])', "billing.redeemGiftCard", "billing.redeem_gift_card"),
    ParityEntry('matches(tokens, ["notifications", "status"])', "notifications.status", "notifications.status"),
    ParityEntry('matches(tokens, ["notifications", "list"])', "notifications.list", "notifications.list"),
    ParityEntry('matches(tokens, ["reminders", "list"])', "reminders.list", "reminders.list"),
    ParityEntry('subcommand === "memories"', "memories.list", "memories.list"),
    ParityEntry('subcommand === "status"', "learningMode.status", "learning_mode.status"),
    ParityEntry('subcommand === "enable"', "learningMode.enable", "learning_mode.enable"),
    ParityEntry('subcommand === "disable"', "learningMode.disable", "learning_mode.disable"),
    ParityEntry('subcommand !== "import"', "connectedAccounts.import", "connected_accounts.import_account"),
    ParityEntry('openmates inspirations', "inspirations.list", "inspirations.list"),
    ParityEntry('openmates newchatsuggestions', "newChatSuggestions.list", "new_chat_suggestions.list"),
    ParityEntry('assistant-response', "feedback.assistantResponse", "feedback.assistant_response"),
    ParityEntry('printBenchmarkHelp', "benchmark.run", "benchmark.run"),
    ParityEntry('openmates workflows list', "workflows.list", "workflows.list"),
    ParityEntry('openmates workflows capabilities', "workflows.capabilities", "workflows.capabilities"),
    ParityEntry('openmates workflows validate --file workflow.yml', "workflows.validateYaml", "workflows.validate_yaml"),
    ParityEntry('openmates workflows create --file workflow.yml', "workflows.createFromYaml", "workflows.create_from_yaml"),
    ParityEntry('openmates workflows update <workflow-id> --file workflow.yml', "workflows.updateFromYaml", "workflows.update_from_yaml"),
    ParityEntry('openmates workflows show', "workflows.get", "workflows.get"),
    ParityEntry('openmates workflows create', "workflows.create", "workflows.create"),
    ParityEntry('openmates workflows enable', "workflows.enable", "workflows.enable"),
    ParityEntry('openmates workflows disable', "workflows.disable", "workflows.disable"),
    ParityEntry('openmates workflows run', "workflows.run", "workflows.run"),
    ParityEntry('openmates workflows runs', "workflows.runs", "workflows.runs"),
    ParityEntry('openmates workflows run-show', "workflows.runDetail", "workflows.run_detail"),
    ParityEntry('openmates workflows run-cancel', "workflows.cancelRun", "workflows.cancel_run"),
    ParityEntry('openmates workflows respond', "workflows.respond", "workflows.respond"),
    ParityEntry('openmates workflows delete', "workflows.delete", "workflows.delete"),
    ParityEntry('subcommand === "list"', "docs.list", "docs.list"),
    ParityEntry('subcommand === "search"', "docs.search", "docs.search"),
    ParityEntry('subcommand === "show"', "docs.show", "docs.show"),
    ParityEntry('subcommand === "download"', "docs.download", "docs.download"),
    ParityEntry('openmates embeds show', "embeds.show", "embeds.show"),
    ParityEntry('openmates embeds share', "embeds.share", "embeds.share"),
    ParityEntry('openmates embeds versions list', "embeds.versions", "embeds.versions"),
]


# These endpoints are intentionally transport-only until a shared client-side
# crypto format exists for creating a user-facing workflow share URL.
WORKFLOW_TEMPLATE_TRANSPORT_ENTRIES = [
    WorkflowTemplateTransportEntry(
        "getPublicWorkflowTemplateProjection",
        "getPublicTemplateProjection",
        "get_public_template_projection",
    ),
    WorkflowTemplateTransportEntry(
        "revokeWorkflowTemplateProjection",
        "revokeTemplateProjection",
        "revoke_template_projection",
    ),
    WorkflowTemplateTransportEntry(
        "unrevokeWorkflowTemplateProjection",
        "unrevokeTemplateProjection",
        "unrevoke_template_projection",
    ),
    WorkflowTemplateTransportEntry(
        "completeImportedWorkflowBinding",
        "completeImportedBinding",
        "complete_imported_binding",
    ),
]


def npm_method_exists(source: str, dotted: str) -> bool:
    namespace, method = dotted.split(".", 1)
    return f"readonly {namespace}:" in source and re.search(rf"async {re.escape(method)}\s*\(", source) is not None


def pip_method_exists(source: str, dotted: str) -> bool:
    namespace, method = dotted.split(".", 1)
    return f"self.{namespace} =" in source and re.search(rf"def {re.escape(method)}\s*\(", source) is not None


def method_exists(source: str, method: str, *, is_async: bool) -> bool:
    if is_async:
        return re.search(rf"async {re.escape(method)}\s*\(", source) is not None
    return re.search(rf"def {re.escape(method)}\s*\(", source) is not None


def main() -> int:
    cli = CLI_TS.read_text(encoding="utf-8")
    cli_client = CLI_CLIENT_TS.read_text(encoding="utf-8")
    sdk_ts = SDK_TS.read_text(encoding="utf-8")
    sdk_py = SDK_PY.read_text(encoding="utf-8")
    generated_ts = GENERATED_TS.read_text(encoding="utf-8")
    generated_py = GENERATED_PY.read_text(encoding="utf-8")
    failures: list[str] = []

    top_level_commands = set(re.findall(r'(?<![A-Za-z_])command === "([a-z0-9-]+)"', cli))
    unclassified = top_level_commands - TOP_LEVEL_CLASSIFICATION.keys()
    if unclassified:
        failures.append(f"Unclassified CLI command(s): {', '.join(sorted(unclassified))}")

    for command, classification in TOP_LEVEL_CLASSIFICATION.items():
        if command not in top_level_commands and command != "help" and command not in OPTIONAL_TOP_LEVEL_COMMANDS:
            failures.append(f"Classified CLI command missing from cli.ts: {command}")
        if classification in EXCLUSION_REASONS and not EXCLUSION_REASONS[classification]:
            failures.append(f"Excluded command {command} has empty reason {classification}")

    for entry in PARITY_ENTRIES:
        if entry.cli_marker not in cli:
            failures.append(f"CLI marker missing for parity entry: {entry.cli_marker}")
        if not npm_method_exists(sdk_ts, entry.npm):
            failures.append(f"Missing npm SDK method: {entry.npm}")
        if not pip_method_exists(sdk_py, entry.pip):
            failures.append(f"Missing pip SDK method: {entry.pip}")

    for entry in WORKFLOW_TEMPLATE_TRANSPORT_ENTRIES:
        if not method_exists(cli_client, entry.cli_client, is_async=True):
            failures.append(f"Missing CLI workflow template transport method: {entry.cli_client}")
        if not method_exists(sdk_ts, entry.npm, is_async=True):
            failures.append(f"Missing npm workflow template transport method: {entry.npm}")
        if not method_exists(sdk_py, entry.pip, is_async=False):
            failures.append(f"Missing pip workflow template transport method: {entry.pip}")

    if "class WebAppSkills" not in generated_ts or "async search" not in generated_ts:
        failures.append("Generated npm app-skill methods are missing web.search")
    if "class ImagesAppSkills" not in generated_ts or "async generate" not in generated_ts:
        failures.append("Generated npm app-skill methods are missing images.generate")
    if "class WebAppSkills" not in generated_py or "def search" not in generated_py:
        failures.append("Generated pip app-skill methods are missing web.search")
    if "class ImagesAppSkills" not in generated_py or "def generate" not in generated_py:
        failures.append("Generated pip app-skill methods are missing images.generate")
    if re.search(r"\brun\s*\(", sdk_ts) and "runAppSkill" not in sdk_ts:
        failures.append("Public generic npm apps.run appears to be present")
    if re.search(r"def run\s*\(", generated_py):
        failures.append("Public generic pip apps.run appears to be present")

    if failures:
        for failure in failures:
            print(f"sdk-cli-parity: {failure}", file=sys.stderr)
        return 1

    print(
        "sdk-cli-parity: "
        f"{len(PARITY_ENTRIES)} command entries and "
        f"{len(WORKFLOW_TEMPLATE_TRANSPORT_ENTRIES)} workflow template transport entries checked"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
