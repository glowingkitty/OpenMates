#!/usr/bin/env python3
"""Audit the runtime-health no-spend and fail-closed implementation contract.

The audit is intentionally static and fast enough for focused CI use. It checks
that host monitoring, strict deployment mode, paid-call denial, and webhook
egress controls cannot silently disappear during later refactors.
Spec: docs/specs/post-update-runtime-health-alerting/spec.yml.
Update completion spec: docs/specs/post-update-completion-email/spec.yml.
"""

from __future__ import annotations

from pathlib import Path
import re
import sys


ROOT = Path(__file__).resolve().parents[1]
VERIFIER = ROOT / "backend/scripts/runtime_health_verifier.py"
SERVER_MODE = ROOT / "backend/core/api/app/utils/server_mode.py"
SERVER_HEALTH = ROOT / "frontend/packages/openmates-cli/src/serverHealth.ts"
SERVER = ROOT / "frontend/packages/openmates-cli/src/server.ts"
SERVER_UPDATE_STATE = ROOT / "frontend/packages/openmates-cli/src/serverUpdateState.ts"
SERVER_PLANNING = ROOT / "frontend/packages/openmates-cli/src/serverPlanning.ts"
CORE_COMPOSE = ROOT / "backend/core/docker-compose.yml"


def require_markers(path: Path, markers: tuple[str, ...], errors: list[str]) -> None:
    if not path.is_file():
        errors.append(f"missing required file: {path.relative_to(ROOT)}")
        return
    source = path.read_text(encoding="utf-8")
    for marker in markers:
        if marker not in source:
            errors.append(f"{path.relative_to(ROOT)} missing contract marker: {marker}")


def main() -> int:
    errors: list[str] = []
    require_markers(
        SERVER_MODE,
        ("OPENMATES_DEPLOYMENT_MODE", "resolve_runtime_deployment_mode", "official_cloud", "self_host"),
        errors,
    )
    if SERVER_HEALTH.is_file():
        source = SERVER_HEALTH.read_text(encoding="utf-8")
        sender = source[source.find("export async function sendGenericWebhook"):source.find("export async function sendDiscordWebhook")]
        for marker in ("signRuntimeWebhookPayload", "httpsRequest", "lookup:", "randomUUID"):
            if marker not in sender:
                errors.append(f"production generic webhook sender missing replay/egress control: {marker}")

    if CORE_COMPOSE.is_file():
        compose_source = CORE_COMPOSE.read_text(encoding="utf-8")
        for service in ("api", "task-worker", "task-scheduler", "app-ai-worker"):
            match = re.search(rf"(?ms)^  {re.escape(service)}:\n(.*?)(?=^  [A-Za-z0-9_-]+:\n|\Z)", compose_source)
            block = match.group(0) if match else ""
            for marker in ("OPENMATES_DEPLOYMENT_MODE", "OPENMATES_CLOUD_OVERLAY_PACKAGE"):
                if marker not in block:
                    errors.append(f"{service} missing deployment witness: {marker}")
    require_markers(
        VERIFIER,
        ("GLOBAL_DEADLINE_SECONDS", "core.chat_plumbing", "billing.stripe_account_read", "execute_checks"),
        errors,
    )
    require_markers(
        SERVER_HEALTH,
        (
            "followRedirects",
            "private",
            "linkLocal",
            "X-OpenMates-Signature",
            "sha256",
            "consecutiveFailures",
            "Server update complete",
            "selectUpdateSourceLink",
            "deliverUpdateCompletionEmail",
            "email_not_configured",
            "idempotencyKey",
            "duplicate_parameter",
            "isBrevoAcceptedResponse",
            "delivery_identity_invalid",
            "retry_budget_exhausted",
        ),
        errors,
    )
    require_markers(
        SERVER,
        (
            "runUpdateCompletionEmailGate",
            'updateMode: "image"',
            'updateMode: "source"',
            "completionEmailDelivery",
            'step: completion.updateStatus === "success" ? "complete" : "completion-email"',
            "org.opencontainers.image.version",
            "org.opencontainers.image.revision",
            "git remote get-url origin",
            "git branch -r --contains",
            "Continuous update iteration degraded",
            "acquireServerUpdateLock",
            "completionEmailPendingAt",
        ),
        errors,
    )
    require_markers(
        SERVER_UPDATE_STATE,
        ("renameSync", 'openSync(lockPath, "wx"', 'join(stateDir, "server-update.lock")', "invalid_update_status", "already running"),
        errors,
    )
    if SERVER.is_file():
        server_source = SERVER.read_text(encoding="utf-8")
        update_start = server_source.find("async function serverUpdate")
        update_end = server_source.find("async function serverTest", update_start)
        update_source = server_source[update_start:update_end]
        if update_source.count("runUpdateCompletionEmailGate({") != 2:
            errors.append("image and source update modes must each run exactly one completion-email gate")
        if update_source.count('if (completion.updateStatus === "degraded")') != 2:
            errors.append("image and source update modes must each degrade after completion-email failure")
        if "process.exit(" in update_source:
            errors.append("server update must not call process.exit while the installation lock is held")
        for match in re.finditer(r"runUpdateCompletionEmailGate\(\{", update_source):
            preceding = update_source[max(0, match.start() - 6000):match.start()]
            if "maybeRunQuickServerTest" not in preceding:
                errors.append("completion-email gate must run after the optional quick server test")
    require_markers(
        SERVER_PLANNING,
        ("planRuntimeMonitoringServices", "Persistent=true", "runtime-monitor"),
        errors,
    )

    if VERIFIER.is_file():
        verifier_source = VERIFIER.read_text(encoding="utf-8")
        for forbidden in (
            "check_all_providers",
            "_get_provider_client",
            "PaymentIntent.create",
            "Checkout.Session.create",
        ):
            if forbidden in verifier_source:
                errors.append(f"runtime verifier contains paid or mutating path: {forbidden}")

    if errors:
        print("Runtime health contract audit failed:", file=sys.stderr)
        for error in errors:
            print(f"- {error}", file=sys.stderr)
        return 1

    print("Runtime health contract audit passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
