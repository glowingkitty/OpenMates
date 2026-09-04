/**
 * Host-owned runtime health state and notification policy for managed servers.
 * State is intentionally independent of containers so a host watchdog can
 * detect stale or missing verifier runs. Payloads contain stable check IDs and
 * sanitized reasons only; secrets and raw provider responses are excluded.
 * Spec: docs/specs/post-update-runtime-health-alerting/spec.yml.
 */

import dnsModule, { promises as dns } from "node:dns";
import { createHmac, randomUUID } from "node:crypto";
import { promises as fs } from "node:fs";
import { isIP } from "node:net";
import { request as httpsRequest, type RequestOptions } from "node:https";
import { request as httpRequest } from "node:http";
import path from "node:path";
import type { ServerRole } from "./serverPlanning.js";

const INCIDENT_FAILURE_THRESHOLD = 2;
const STORAGE_CRITICAL_AFTER_MS = 60 * 60 * 1000;
const STALE_AFTER_MS = 15 * 60 * 1000;
const HEARTBEAT_AFTER_MS = 24 * 60 * 60 * 1000;
const OPERATIONAL_REPORT_STALE_AFTER_MS = 26 * 60 * 60 * 1000;
const ALLOWED_WEBHOOK_PORTS = new Set([443]);
const IMMEDIATE_FAILURE_CLASSES = new Set(["credential", "configuration", "config", "critical_availability"]);
const WEBHOOK_EGRESS_POLICY = { followRedirects: false, denyAddressClasses: ["private", "linkLocal"] } as const;
const BREVO_API_HOST = "api.brevo.com";
const BREVO_REQUEST_TIMEOUT_MS = 10_000;
const BREVO_IDEMPOTENCY_TTL_MS = 30 * 60 * 1000;
const DELIVERY_ID_PATTERN = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;
const OPENMATES_REPOSITORY_PATH = "/glowingkitty/OpenMates/";

export type RuntimeIncidentState = {
  consecutiveFailures: number;
  incidentOpen: boolean;
  incidentOpenedAt?: string;
  lastCheckAt?: string;
  lastSuccessAt?: string;
  lastNotificationAt?: string;
  lastHeartbeatAt?: string;
  lastFailureClass?: string;
  criticalEscalatedAt?: string;
  checks?: Record<string, {
    consecutiveFailures: number;
    incidentOpen: boolean;
    incidentOpenedAt?: string;
    lastCheckAt?: string;
    lastSuccessAt?: string;
    lastFailureClass?: string;
    criticalEscalatedAt?: string;
  }>;
};

export type RuntimeNotificationDecision = {
  kind: "incident" | "recovery" | "heartbeat" | "stale";
  send: boolean;
  reason: string;
};

export type RuntimeCheckOutcome = {
  status: "passed" | "failed";
  failureClass?: string;
};

export type RuntimeNotificationPayload = {
  role: ServerRole;
  kind: RuntimeNotificationDecision["kind"] | "post_update_failed" | "service_unhealthy" | "critical" | "monitor_stale" | "recovered" | "daily_heartbeat" | "delivery_test";
  occurredAt: string;
  environment: OperationalEnvironment;
  serverName: string;
  deploymentMode: "official_cloud" | "self_host";
  version: string;
  checkIds: string[];
  checkDetails?: Array<{ id: string; failureClass?: string; reason?: string }>;
  sanitizedReason: string;
};

export type RuntimeNotificationDelivery = {
  channel: "email" | "discord" | "webhook";
  status: "delivered" | "exhausted";
  attempts: number;
  sanitizedReason?: string;
};

export type RuntimeNotificationConfig = {
  email?: { apiKey: string; from: string; to: string };
  discordWebhookUrl?: string;
  genericWebhook?: { url: string; secret: string; allowLocalDevelopmentFixture?: boolean };
};

export type UpdateSourceLink = {
  kind: "release" | "pull_request" | "commit" | "source";
  url: string;
};

export type UpdateCompletionPayload = {
  deliveryId: string;
  updateMode: "image" | "source";
  installedVersion: string;
  role: ServerRole;
  completedAt: string;
  source: UpdateSourceLink;
};

export type UpdateCompletionEmailDelivery = {
  status: "accepted" | "failed" | "unavailable";
  attempts: number;
  sanitizedReason?: string;
};

export type UpdateCompletionOutcome = {
  updateStatus: "success" | "degraded";
  exitCode: 0 | 1;
  delivery: UpdateCompletionEmailDelivery;
};

export type UpdateCompletionDeliveryPlan =
  | { action: "send"; deliveryId?: string; pendingAt?: string; previousAttempts?: number }
  | { action: "reuse_accepted"; deliveryId: string; attempts: number }
  | { action: "blocked"; deliveryId?: string; pendingAt?: string; reason: "update_status_unreadable" | "delivery_identity_invalid" | "idempotency_window_expired" | "retry_budget_exhausted" };

export type OperationalEnvironment = "development" | "production" | "self_host";

export type OperationalMonitoringPlan = {
  environment: OperationalEnvironment;
  configurationStatus: "ready" | "missing_admin_email" | "email_service_unavailable";
  emailEnabled: boolean;
  discordEnabled: boolean;
  scheduleEnabled: boolean;
  digestServiceName: string;
  digestTimerName: string;
  watchdogServiceName: string;
  watchdogTimerName: string;
  digestUnit: string;
  digestTimer: string;
  watchdogUnit: string;
  watchdogTimer: string;
};

export type OperationalReportState = {
  incidentOpen: boolean;
  lastAcceptedReportAt?: string;
  incidentOpenedAt?: string;
  monitoringStartedAt?: string;
};

export type OperationalReportEvent = {
  type: "operational_report_stale" | "operational_report_recovered";
  reason: string;
};

export type OperationalDeliveryReceipt = {
  environment: OperationalEnvironment;
  reportId: string;
  reportSha256: string;
  channel: "email" | "discord";
  state: "queued" | "accepted" | "failed" | "unavailable";
  attemptCount: number;
  occurredAt: string;
  sanitizedFailureClass?: string;
  destinationSource?: string;
  fallbackUsed?: boolean;
};

export function planOperationalMonitoring(options: {
  environment: OperationalEnvironment;
  role: ServerRole;
  installPath: string;
  adminEmail?: string;
  emailServiceAvailable: boolean;
  discordConfigured: boolean;
  executablePath?: string;
}): OperationalMonitoringPlan {
  const emailEnabled = Boolean(options.adminEmail?.trim()) && options.emailServiceAvailable;
  const configurationStatus = !options.adminEmail?.trim()
    ? "missing_admin_email"
    : options.emailServiceAvailable
      ? "ready"
      : "email_service_unavailable";
  const unitPrefix = `openmates-${options.role}-operational-report`;
  const commandPrefix = `${options.executablePath ?? "openmates"} server monitoring`;
  const selectedChannels = [emailEnabled ? "email" : null, options.discordConfigured ? "discord" : null]
    .filter(Boolean)
    .join(",");
  return {
    environment: options.environment,
    configurationStatus,
    emailEnabled,
    discordEnabled: options.discordConfigured,
    scheduleEnabled: emailEnabled || options.discordConfigured,
    digestServiceName: `${unitPrefix}.service`,
    digestTimerName: `${unitPrefix}.timer`,
    watchdogServiceName: `${unitPrefix}-watchdog.service`,
    watchdogTimerName: `${unitPrefix}-watchdog.timer`,
    digestUnit: [
      "[Unit]",
      "Description=OpenMates daily operational report",
      "[Service]",
      "Type=oneshot",
      `WorkingDirectory=${options.installPath}`,
      `ExecStart=${commandPrefix} digest --role ${options.role} --channel ${selectedChannels}`,
      "",
    ].join("\n"),
    digestTimer: [
      "[Unit]",
      "Description=OpenMates daily operational report timer",
      "[Timer]",
      "OnCalendar=*-*-* 08:30:00 UTC",
      "Persistent=true",
      `Unit=${unitPrefix}.service`,
      "[Install]",
      "WantedBy=timers.target",
      "",
    ].join("\n"),
    watchdogUnit: [
      "[Unit]",
      "Description=OpenMates operational report watchdog",
      "[Service]",
      "Type=oneshot",
      `WorkingDirectory=${options.installPath}`,
      `ExecStart=${commandPrefix} report-watchdog --role ${options.role}`,
      "",
    ].join("\n"),
    watchdogTimer: [
      "[Unit]",
      "Description=OpenMates operational report watchdog timer",
      "[Timer]",
      "OnUnitActiveSec=5m",
      "Persistent=true",
      `Unit=${unitPrefix}-watchdog.service`,
      "[Install]",
      "WantedBy=timers.target",
      "",
    ].join("\n"),
  };
}

export function evaluateOperationalReportFreshness(
  state: OperationalReportState | undefined,
  now: Date,
): { state: OperationalReportState; event: OperationalReportEvent | null } {
  const current = state ?? { incidentOpen: false };
  const lastAccepted = current.lastAcceptedReportAt ? Date.parse(current.lastAcceptedReportAt) : 0;
  const monitoringStarted = current.monitoringStartedAt ? Date.parse(current.monitoringStartedAt) : now.getTime();
  const stale = lastAccepted
    ? now.getTime() - lastAccepted > OPERATIONAL_REPORT_STALE_AFTER_MS
    : now.getTime() - monitoringStarted > OPERATIONAL_REPORT_STALE_AFTER_MS;
  if (stale && !current.incidentOpen) {
    return {
      state: { ...current, incidentOpen: true, incidentOpenedAt: now.toISOString() },
      event: { type: "operational_report_stale", reason: "daily_report_stale" },
    };
  }
  if (!stale && current.incidentOpen) {
    return {
      state: { ...current, incidentOpen: false, incidentOpenedAt: undefined },
      event: { type: "operational_report_recovered", reason: "daily_report_fresh" },
    };
  }
  return { state: current, event: null };
}

export function buildOperationalDeliveryReceipt(input: OperationalDeliveryReceipt): OperationalDeliveryReceipt {
  return {
    environment: input.environment,
    reportId: input.reportId,
    reportSha256: input.reportSha256,
    channel: input.channel,
    state: input.state,
    attemptCount: input.attemptCount,
    occurredAt: input.occurredAt,
    ...(input.sanitizedFailureClass ? { sanitizedFailureClass: input.sanitizedFailureClass } : {}),
    ...(input.destinationSource ? { destinationSource: input.destinationSource } : {}),
    ...(input.fallbackUsed !== undefined ? { fallbackUsed: input.fallbackUsed } : {}),
  };
}

function safePublicUpdateSourceLink(kind: UpdateSourceLink["kind"], rawUrl?: string | null): UpdateSourceLink | null {
  if (!rawUrl) return null;
  try {
    const url = new URL(rawUrl);
    if (url.protocol !== "https:" || url.hostname !== "github.com" || !url.pathname.startsWith(OPENMATES_REPOSITORY_PATH)) {
      return null;
    }
    return { kind, url: url.toString() };
  } catch {
    return null;
  }
}

export function selectUpdateSourceLink(links: {
  releaseUrl?: string | null;
  pullRequestUrl?: string | null;
  commitUrl?: string | null;
  sourceUrl?: string | null;
}): UpdateSourceLink | null {
  return safePublicUpdateSourceLink("release", links.releaseUrl)
    ?? safePublicUpdateSourceLink("pull_request", links.pullRequestUrl)
    ?? safePublicUpdateSourceLink("commit", links.commitUrl)
    ?? safePublicUpdateSourceLink("source", links.sourceUrl);
}

export function buildUpdateCompletionEmail(payload: UpdateCompletionPayload): { subject: string; textContent: string; headers: { idempotencyKey: string } } {
  return {
    subject: "Server update complete",
    headers: { idempotencyKey: payload.deliveryId },
    textContent: [
      "OpenMates server update completed successfully.",
      `Mode: ${payload.updateMode}`,
      `Version: ${payload.installedVersion}`,
      `Role: ${payload.role}`,
      `Completed: ${payload.completedAt}`,
      `Source (${payload.source.kind}): ${payload.source.url}`,
    ].join("\n"),
  };
}

export function buildUpdateCompletionOutcome(delivery: UpdateCompletionEmailDelivery): UpdateCompletionOutcome {
  return {
    updateStatus: delivery.status === "accepted" ? "success" : "degraded",
    exitCode: delivery.status === "accepted" ? 0 : 1,
    delivery,
  };
}

export function isBrevoIdempotencyDuplicate(status: number, responseBody: string, payload?: Record<string, unknown>): boolean {
  if (status !== 400 || !payload?.headers || typeof payload.headers !== "object" || !("idempotencyKey" in payload.headers)) {
    return false;
  }
  try {
    return (JSON.parse(responseBody) as { code?: unknown }).code === "duplicate_parameter";
  } catch {
    return false;
  }
}

export function planUpdateCompletionDelivery(input: {
  previousStatus: Record<string, unknown>;
  updateMode: UpdateCompletionPayload["updateMode"];
  installedVersion: string;
  continuousUpdate: boolean;
  now: Date;
}): UpdateCompletionDeliveryPlan {
  if (input.previousStatus.statusReadError === "invalid_update_status") {
    return { action: "blocked", reason: "update_status_unreadable" };
  }
  const rawPreviousDelivery = input.previousStatus.completionEmailDelivery;
  const previousDelivery = rawPreviousDelivery && typeof rawPreviousDelivery === "object" && !Array.isArray(rawPreviousDelivery)
    ? rawPreviousDelivery as Record<string, unknown>
    : undefined;
  const sameInstalledArtifact = input.previousStatus.updateMode === input.updateMode
    && input.previousStatus.installedVersion === input.installedVersion;
  const deliveryId = typeof input.previousStatus.completionEmailDeliveryId === "string"
    && DELIVERY_ID_PATTERN.test(input.previousStatus.completionEmailDeliveryId)
    ? input.previousStatus.completionEmailDeliveryId
    : undefined;
  if (input.continuousUpdate && sameInstalledArtifact && previousDelivery?.status === "accepted") {
    const attempts = previousDelivery.attempts;
    const completedAt = typeof input.previousStatus.completedAt === "string"
      ? Date.parse(input.previousStatus.completedAt)
      : Number.NaN;
    const sourceLink = typeof input.previousStatus.sourceLink === "string"
      ? safePublicUpdateSourceLink("source", input.previousStatus.sourceLink)
      : null;
    if (!deliveryId || !Number.isInteger(attempts) || Number(attempts) < 1 || Number(attempts) > 3
      || !Number.isFinite(completedAt) || !sourceLink) {
      return { action: "blocked", reason: "delivery_identity_invalid" };
    }
    return { action: "reuse_accepted", deliveryId, attempts: Number(attempts) };
  }
  const hasAttemptedUnavailableDelivery = previousDelivery?.status === "unavailable"
    && Number.isInteger(previousDelivery.attempts)
    && Number(previousDelivery.attempts) > 0;
  if (sameInstalledArtifact && (previousDelivery?.status === "pending" || previousDelivery?.status === "failed" || hasAttemptedUnavailableDelivery)) {
    const previousAttempts = previousDelivery.attempts;
    const pendingAtValue = typeof input.previousStatus.completionEmailPendingAt === "string"
      ? input.previousStatus.completionEmailPendingAt
      : undefined;
    const pendingAt = pendingAtValue
      ? Date.parse(pendingAtValue)
      : Number.NaN;
    if (!deliveryId || !Number.isInteger(previousAttempts) || Number(previousAttempts) < 0 || Number(previousAttempts) > 3) {
      return { action: "blocked", reason: "delivery_identity_invalid" };
    }
    if (!Number.isFinite(pendingAt) || input.now.getTime() - pendingAt >= BREVO_IDEMPOTENCY_TTL_MS) {
      return { action: "blocked", deliveryId, pendingAt: pendingAtValue, reason: "idempotency_window_expired" };
    }
    if (Number(previousAttempts) >= 3) {
      return { action: "blocked", deliveryId, pendingAt: pendingAtValue, reason: "retry_budget_exhausted" };
    }
    return { action: "send", deliveryId, pendingAt: pendingAtValue, previousAttempts: Number(previousAttempts) };
  }
  return { action: "send" };
}

export async function probeRuntimeEmailService(
  config: NonNullable<RuntimeNotificationConfig["email"]>,
): Promise<boolean> {
  try {
    await requestBrevo("/v3/account", "GET", config.apiKey);
    return true;
  } catch {
    return false;
  }
}

export function buildBrevoRequestOptions(
  pathName: string,
  method: "GET" | "POST",
  apiKey: string,
  body?: string,
): RequestOptions {
  return {
    protocol: "https:",
    hostname: BREVO_API_HOST,
    servername: BREVO_API_HOST,
    port: 443,
    path: pathName,
    method,
    family: 4,
    lookup: (hostname, options, callback) => dnsModule.lookup(hostname, { ...options, family: 4 }, callback),
    headers: {
      "api-key": apiKey,
      ...(body ? { "content-type": "application/json", "Content-Length": Buffer.byteLength(body) } : {}),
    },
    timeout: BREVO_REQUEST_TIMEOUT_MS,
  };
}

export function isBrevoAcceptedResponse(pathName: string, method: "GET" | "POST", status: number, responseBody: string): boolean {
  if (status < 200 || status >= 300) return false;
  if (method !== "POST" || pathName !== "/v3/smtp/email") return true;
  try {
    const messageId = (JSON.parse(responseBody) as { messageId?: unknown }).messageId;
    return typeof messageId === "string" && messageId.trim().length > 0;
  } catch {
    return false;
  }
}

async function requestBrevo(
  pathName: string,
  method: "GET" | "POST",
  apiKey: string,
  payload?: Record<string, unknown>,
): Promise<void> {
  const body = payload ? JSON.stringify(payload) : undefined;
  await new Promise<void>((resolve, reject) => {
    const request = httpsRequest(buildBrevoRequestOptions(pathName, method, apiKey, body), (response) => {
      let responseBytes = 0;
      const chunks: Buffer[] = [];
      response.on("data", (chunk: Buffer) => {
        responseBytes += chunk.length;
        if (responseBytes > 64 * 1024) request.destroy(new Error("brevo_response_too_large"));
        else chunks.push(chunk);
      });
      response.on("end", () => {
        const status = response.statusCode ?? 0;
        const responseBody = Buffer.concat(chunks).toString("utf8");
        if (isBrevoAcceptedResponse(pathName, method, status, responseBody)) resolve();
        else if (isBrevoIdempotencyDuplicate(status, responseBody, payload)) resolve();
        else reject(new Error(`brevo_delivery_failed:${status}`));
      });
    });
    request.on("timeout", () => request.destroy(new Error("brevo_delivery_timeout")));
    request.on("error", reject);
    request.end(body);
  });
}

export async function readOperationalReportState(installDir: string, role: ServerRole): Promise<OperationalReportState> {
  const statePath = path.join(installDir, ".openmates", "runtime-health", `${role}-operational-report.json`);
  try {
    return JSON.parse(await fs.readFile(statePath, "utf8")) as OperationalReportState;
  } catch (error) {
    if ((error as NodeJS.ErrnoException).code === "ENOENT") return { incidentOpen: false, monitoringStartedAt: new Date().toISOString() };
    throw error;
  }
}

export async function writeOperationalReportState(
  installDir: string,
  role: ServerRole,
  state: OperationalReportState,
): Promise<void> {
  const stateDir = path.join(installDir, ".openmates", "runtime-health");
  const statePath = path.join(stateDir, `${role}-operational-report.json`);
  const temporaryPath = `${statePath}.${process.pid}.tmp`;
  await fs.mkdir(stateDir, { recursive: true, mode: 0o700 });
  await fs.writeFile(temporaryPath, `${JSON.stringify(state, null, 2)}\n`, { mode: 0o600 });
  await fs.rename(temporaryPath, statePath);
  await fs.chmod(statePath, 0o600);
}

export function initialRuntimeIncidentState(): RuntimeIncidentState {
  return { consecutiveFailures: 0, incidentOpen: false };
}

export function evaluateRuntimeIncident(
  state: RuntimeIncidentState,
  outcome: RuntimeCheckOutcome,
  now: Date,
): { state: RuntimeIncidentState; notification: RuntimeNotificationDecision | null } {
  const timestamp = now.toISOString();
  if (outcome.status === "passed") {
    const wasOpen = state.incidentOpen;
    const next = {
      ...state,
      consecutiveFailures: 0,
      incidentOpen: false,
      incidentOpenedAt: undefined,
      criticalEscalatedAt: undefined,
      lastCheckAt: timestamp,
      lastSuccessAt: timestamp,
    };
    if (wasOpen) {
      next.lastNotificationAt = timestamp;
      return { state: next, notification: { kind: "recovery", send: true, reason: "required_checks_recovered" } };
    }
    return { state: next, notification: null };
  }

  const consecutiveFailures = state.consecutiveFailures + 1;
  const immediate = IMMEDIATE_FAILURE_CLASSES.has(outcome.failureClass ?? "");
  const shouldOpen = !state.incidentOpen && (immediate || consecutiveFailures >= INCIDENT_FAILURE_THRESHOLD);
  const next: RuntimeIncidentState = {
    ...state,
    consecutiveFailures,
    incidentOpen: state.incidentOpen || shouldOpen,
    incidentOpenedAt: shouldOpen ? timestamp : state.incidentOpenedAt,
    lastCheckAt: timestamp,
    lastFailureClass: outcome.failureClass,
  };
  if (shouldOpen) {
    next.lastNotificationAt = timestamp;
    return {
      state: next,
      notification: { kind: "incident", send: true, reason: immediate ? "credential_or_configuration_failure" : "consecutive_failures" },
    };
  }
  return { state: next, notification: null };
}

export function evaluateRuntimeWatchdog(
  state: RuntimeIncidentState,
  now: Date,
): { state: RuntimeIncidentState; notification: RuntimeNotificationDecision | null } {
  const lastCheck = state.lastCheckAt ? Date.parse(state.lastCheckAt) : 0;
  if (lastCheck && now.getTime() - lastCheck <= STALE_AFTER_MS) return { state, notification: null };
  if (state.incidentOpen && state.lastFailureClass === "stale") return { state, notification: null };
  const timestamp = now.toISOString();
  return {
    state: {
      ...state,
      incidentOpen: true,
      incidentOpenedAt: state.incidentOpenedAt ?? timestamp,
      lastFailureClass: "stale",
      lastNotificationAt: timestamp,
    },
    notification: { kind: "stale", send: true, reason: "runtime_verifier_stale" },
  };
}

export function evaluateRuntimeHeartbeat(
  state: RuntimeIncidentState,
  now: Date,
): { state: RuntimeIncidentState; notification: RuntimeNotificationDecision | null } {
  if (state.incidentOpen || !state.lastSuccessAt) return { state, notification: null };
  const baseline = state.lastHeartbeatAt ? Date.parse(state.lastHeartbeatAt) : Date.parse(state.lastSuccessAt);
  if (now.getTime() - baseline < HEARTBEAT_AFTER_MS) return { state, notification: null };
  const timestamp = now.toISOString();
  return {
    state: { ...state, lastHeartbeatAt: timestamp, lastNotificationAt: timestamp },
    notification: { kind: "heartbeat", send: true, reason: "daily_runtime_health_green" },
  };
}

export async function readRuntimeIncidentState(installDir: string, role: ServerRole): Promise<RuntimeIncidentState> {
  const statePath = path.join(installDir, ".openmates", "runtime-health", `${role}.json`);
  try {
    return JSON.parse(await fs.readFile(statePath, "utf8")) as RuntimeIncidentState;
  } catch (error) {
    if ((error as NodeJS.ErrnoException).code === "ENOENT") return initialRuntimeIncidentState();
    throw error;
  }
}

export async function writeRuntimeIncidentState(installDir: string, role: ServerRole, state: RuntimeIncidentState): Promise<void> {
  const stateDir = path.join(installDir, ".openmates", "runtime-health");
  const statePath = path.join(stateDir, `${role}.json`);
  const temporaryPath = `${statePath}.${process.pid}.tmp`;
  await fs.mkdir(stateDir, { recursive: true, mode: 0o700 });
  await fs.writeFile(temporaryPath, `${JSON.stringify(state, null, 2)}\n`, { mode: 0o600 });
  await fs.rename(temporaryPath, statePath);
  await fs.chmod(statePath, 0o600);
}

function isPrivateAddress(address: string): boolean {
  const normalized = address.toLowerCase();
  const mappedMatch = normalized.match(/^(?:::ffff:|(?:0:){5}ffff:|::)([0-9a-f]{1,4}):([0-9a-f]{1,4})$/);
  if (mappedMatch) {
    const high = Number.parseInt(mappedMatch[1], 16);
    const low = Number.parseInt(mappedMatch[2], 16);
    return isPrivateAddress(`${high >> 8}.${high & 255}.${low >> 8}.${low & 255}`);
  }
  if (normalized.startsWith("::ffff:")) return isPrivateAddress(normalized.slice(7));
  if (normalized === "::" || normalized === "::1" || normalized === "0:0:0:0:0:0:0:1") return true;
  if (/^(fc|fd|fe8|fe9|fea|feb|ff)/.test(normalized) || normalized.startsWith("2001:db8:")) return true;
  const octets = address.split(".").map(Number);
  if (octets.length !== 4 || octets.some(Number.isNaN)) return false;
  return octets[0] === 10
    || octets[0] === 127
    || (octets[0] === 169 && octets[1] === 254)
    || (octets[0] === 172 && octets[1] >= 16 && octets[1] <= 31)
    || (octets[0] === 192 && octets[1] === 168)
    || (octets[0] === 192 && octets[1] === 0)
    || (octets[0] === 192 && octets[1] === 0 && octets[2] === 2)
    || (octets[0] === 100 && octets[1] >= 64 && octets[1] <= 127)
    || (octets[0] === 198 && (octets[1] === 18 || octets[1] === 19 || (octets[1] === 51 && octets[2] === 100)))
    || (octets[0] === 203 && octets[1] === 0 && octets[2] === 113)
    || octets[0] === 0
    || octets[0] >= 224;
}

async function resolveGenericWebhookTarget(
  rawUrl: string,
  allowLocalDevelopmentFixture = false,
): Promise<{ url: URL; addresses: Array<{ address: string; family: number }> }> {
  const url = new URL(rawUrl);
  const localFixture = allowLocalDevelopmentFixture && url.protocol === "http:" && ["127.0.0.1", "::1", "localhost"].includes(url.hostname);
  if ((!localFixture && url.protocol !== "https:") || url.username || url.password || url.hash) throw new Error("webhook_target_not_allowed");
  const port = url.port ? Number(url.port) : 443;
  if ((!localFixture && !ALLOWED_WEBHOOK_PORTS.has(port)) || (localFixture && port < 1024)) throw new Error("webhook_target_not_allowed");
  const addresses = isIP(url.hostname)
    ? [{ address: url.hostname, family: isIP(url.hostname) }]
    : await dns.lookup(url.hostname, { all: true, verbatim: true, hints: dnsModule.ADDRCONFIG });
  if (!addresses.length || (!localFixture && addresses.some(({ address }) => isPrivateAddress(address)))) throw new Error("webhook_target_not_allowed");
  return { url, addresses };
}

export async function validateGenericWebhookTarget(rawUrl: string): Promise<URL> {
  return (await resolveGenericWebhookTarget(rawUrl)).url;
}

export async function sendGenericWebhook(
  target: string,
  secret: string,
  payload: RuntimeNotificationPayload,
  allowLocalDevelopmentFixture = false,
): Promise<void> {
  const { url, addresses } = await resolveGenericWebhookTarget(target, allowLocalDevelopmentFixture);
  const timestamp = new Date().toISOString();
  const eventId = randomUUID();
  const signed = signRuntimeWebhookPayload(payload as unknown as Record<string, unknown>, secret, timestamp, eventId);
  const selected = addresses[0];
  await new Promise<void>((resolve, reject) => {
    const requestFunction = url.protocol === "https:" ? httpsRequest : httpRequest;
    const request = requestFunction({
      protocol: url.protocol,
      hostname: url.hostname,
      ...(url.protocol === "https:" ? { servername: url.hostname } : {}),
      port: url.port ? Number(url.port) : url.protocol === "https:" ? 443 : 80,
      path: `${url.pathname}${url.search}`,
      method: "POST",
      headers: { ...signed.headers, "Content-Length": Buffer.byteLength(signed.body) },
      timeout: 10_000,
      lookup: (_hostname, _options, callback) => callback(null, selected.address, selected.family),
    }, (response) => {
      let responseBytes = 0;
      response.on("data", (chunk: Buffer) => {
        responseBytes += chunk.length;
        if (responseBytes > 64 * 1024) request.destroy(new Error("webhook_response_too_large"));
      });
      response.on("end", () => {
        const status = response.statusCode ?? 0;
        if (status >= 200 && status < 300) resolve();
        else reject(new Error(`webhook_delivery_failed:${status}`));
      });
    });
    request.on("timeout", () => request.destroy(new Error("webhook_delivery_timeout")));
    request.on("error", reject);
    request.end(signed.body);
  });
}

export async function sendDiscordWebhook(target: string, payload: RuntimeNotificationPayload): Promise<void> {
  const url = new URL(target);
  if (url.protocol !== "https:" || url.hostname !== "discord.com" || !url.pathname.startsWith("/api/webhooks/")) {
    throw new Error("discord_webhook_target_not_allowed");
  }
  const response = await fetch(url, {
    method: "POST",
    redirect: "error",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ content: `[OpenMates ${payload.environment.toUpperCase()} ${payload.serverName} ${payload.role}] ${payload.kind}: ${payload.sanitizedReason}` }),
    signal: AbortSignal.timeout(10_000),
  });
  if (!response.ok) throw new Error(`discord_delivery_failed:${response.status}`);
}

function runtimeCheckAction(checkId: string): string {
  if (checkId === "billing.health_freshness") {
    return "Review Stripe readiness, repair the configured destination, then rerun `openmates server verify --json`.";
  }
  return "Inspect the named service and rerun `openmates server verify --json`.";
}

export function buildRuntimeEmail(payload: RuntimeNotificationPayload): { subject: string; textContent: string } {
  const status = payload.kind === "recovery" || payload.kind === "recovered"
    ? "recovered"
    : payload.kind === "daily_heartbeat"
      ? "healthy"
      : payload.kind === "delivery_test"
        ? "notification test"
        : "degraded";
  const details: Array<{ id: string; failureClass?: string; reason?: string }> = payload.checkDetails?.length
    ? payload.checkDetails
    : payload.checkIds.map((id) => ({ id, reason: payload.sanitizedReason }));
  const checkSections = details.map((check) => [
    `Check: ${check.id}`,
    `Failure class: ${check.failureClass ?? "not_reported"}`,
    `Reason: ${check.reason ?? payload.sanitizedReason}`,
    `Next action: ${runtimeCheckAction(check.id)}`,
  ].join("\n"));

  return {
    subject: `[${payload.environment.toUpperCase()}] OpenMates ${payload.role} ${status}: ${payload.checkIds.join(", ") || payload.kind}`,
    textContent: [
      "OpenMates runtime health alert",
      "",
      `Environment: ${payload.environment}`,
      `Server: ${payload.serverName}`,
      `Deployment: ${payload.deploymentMode}`,
      `Role: ${payload.role}`,
      `Version: ${payload.version}`,
      `Event: ${payload.kind}`,
      `Status: ${status}`,
      `Detected: ${payload.occurredAt}`,
      "",
      ...checkSections,
    ].join("\n"),
  };
}

export async function sendRuntimeEmail(
  config: NonNullable<RuntimeNotificationConfig["email"]>,
  payload: RuntimeNotificationPayload,
): Promise<void> {
  const email = buildRuntimeEmail(payload);
  await requestBrevo("/v3/smtp/email", "POST", config.apiKey, {
    sender: { email: config.from },
    to: [{ email: config.to }],
    subject: email.subject,
    textContent: email.textContent,
  });
}

export async function sendUpdateCompletionEmail(
  config: NonNullable<RuntimeNotificationConfig["email"]>,
  payload: UpdateCompletionPayload,
): Promise<void> {
  const email = buildUpdateCompletionEmail(payload);
  await requestBrevo("/v3/smtp/email", "POST", config.apiKey, {
    sender: { email: config.from },
    to: [{ email: config.to }],
    subject: email.subject,
    textContent: email.textContent,
    headers: email.headers,
  });
}

async function deliverWithRetries(channel: RuntimeNotificationDelivery["channel"], send: () => Promise<void>): Promise<RuntimeNotificationDelivery> {
  for (let attempt = 1; attempt <= 3; attempt += 1) {
    try {
      await send();
      return { channel, status: "delivered", attempts: attempt };
    } catch {
      if (attempt < 3) await new Promise((resolve) => setTimeout(resolve, 250 * 2 ** (attempt - 1)));
    }
  }
  return { channel, status: "exhausted", attempts: 3, sanitizedReason: "delivery_failed" };
}

export async function deliverUpdateCompletionEmail(
  config: RuntimeNotificationConfig["email"],
  payload: UpdateCompletionPayload,
  send: (config: NonNullable<RuntimeNotificationConfig["email"]>, payload: UpdateCompletionPayload) => Promise<void> = sendUpdateCompletionEmail,
  previousAttempts = 0,
  onAttempt?: (attempts: number) => void,
): Promise<UpdateCompletionEmailDelivery> {
  if (!config) return { status: "unavailable", attempts: previousAttempts, sanitizedReason: "email_not_configured" };
  for (let attempts = previousAttempts + 1; attempts <= 3; attempts += 1) {
    onAttempt?.(attempts);
    try {
      await send(config, payload);
      return { status: "accepted", attempts };
    } catch {
      if (attempts < 3) await new Promise((resolve) => setTimeout(resolve, 250 * 2 ** (attempts - 1)));
    }
  }
  return { status: "failed", attempts: Math.max(previousAttempts, 3), sanitizedReason: "delivery_failed" };
}

export async function deliverRuntimeNotification(
  config: RuntimeNotificationConfig,
  payload: RuntimeNotificationPayload,
): Promise<RuntimeNotificationDelivery[]> {
  const deliveries: Array<Promise<RuntimeNotificationDelivery>> = [];
  if (config.email) deliveries.push(deliverWithRetries("email", () => sendRuntimeEmail(config.email!, payload)));
  if (config.discordWebhookUrl) deliveries.push(deliverWithRetries("discord", () => sendDiscordWebhook(config.discordWebhookUrl!, payload)));
  if (config.genericWebhook) {
    deliveries.push(deliverWithRetries("webhook", () => sendGenericWebhook(
      config.genericWebhook!.url,
      config.genericWebhook!.secret,
      payload,
      config.genericWebhook!.allowLocalDevelopmentFixture,
    )));
  }
  return Promise.all(deliveries);
}

export type RuntimeCheckResult = { id: string; status: "passed" | "failed" | "skipped"; failureClass?: string; required?: boolean };
export type RuntimeHealthEvent = { type: "service_unhealthy" | "service_critical" | "recovered"; checkId: string };

export function applyRuntimeCheckResults(
  state: RuntimeIncidentState | undefined,
  results: RuntimeCheckResult[],
  timestamp: string,
): { state: RuntimeIncidentState; events: RuntimeHealthEvent[] } {
  const current = state ?? initialRuntimeIncidentState();
  const checks = { ...(current.checks ?? {}) };
  const events: RuntimeHealthEvent[] = [];
  for (const result of results) {
    const checkState = checks[result.id] ?? { consecutiveFailures: 0, incidentOpen: false };
    if (result.status === "skipped" && result.failureClass === "not_configured") {
      checks[result.id] = {
        consecutiveFailures: 0,
        incidentOpen: false,
        lastCheckAt: timestamp,
        lastFailureClass: "not_configured",
      };
      continue;
    }
    if (result.status === "skipped" && result.failureClass === "dependency_failed" && result.required === false) {
      continue;
    }
    const evaluated = evaluateRuntimeIncident(
      checkState,
      { status: result.status === "passed" ? "passed" : "failed", failureClass: result.failureClass },
      new Date(timestamp),
    );
    const nextCheckState = {
      consecutiveFailures: evaluated.state.consecutiveFailures,
      incidentOpen: evaluated.state.incidentOpen,
      incidentOpenedAt: evaluated.state.incidentOpenedAt,
      lastCheckAt: evaluated.state.lastCheckAt,
      lastSuccessAt: evaluated.state.lastSuccessAt,
      lastFailureClass: evaluated.state.lastFailureClass,
      criticalEscalatedAt: evaluated.state.criticalEscalatedAt,
    };
    if (
      result.id === "core.object_storage"
      && result.status === "failed"
      && nextCheckState.incidentOpen
      && nextCheckState.incidentOpenedAt
      && !nextCheckState.criticalEscalatedAt
      && Date.parse(timestamp) - Date.parse(nextCheckState.incidentOpenedAt) >= STORAGE_CRITICAL_AFTER_MS
    ) {
      nextCheckState.criticalEscalatedAt = timestamp;
      events.push({ type: "service_critical", checkId: result.id });
    }
    checks[result.id] = nextCheckState;
    if (evaluated.notification?.kind === "incident") events.push({ type: "service_unhealthy", checkId: result.id });
    if (evaluated.notification?.kind === "recovery") events.push({ type: "recovered", checkId: result.id });
  }
  const values = Object.values(checks);
  const incidentOpen = values.some((check) => check.incidentOpen);
  return {
    state: {
      ...current,
      checks,
      consecutiveFailures: Math.max(0, ...values.map((check) => check.consecutiveFailures)),
      incidentOpen,
      incidentOpenedAt: values.find((check) => check.incidentOpen)?.incidentOpenedAt,
      lastCheckAt: timestamp,
      lastSuccessAt: incidentOpen ? current.lastSuccessAt : timestamp,
      lastFailureClass: values.find((check) => check.incidentOpen)?.lastFailureClass,
      lastNotificationAt: events.length ? timestamp : current.lastNotificationAt,
    },
    events,
  };
}

export function signRuntimeWebhookPayload(
  payload: Record<string, unknown>,
  secret: string,
  timestamp: string,
  eventId: string,
): { body: string; headers: Record<string, string> } {
  const body = JSON.stringify(payload);
  const canonical = `${timestamp}.${eventId}.${body}`;
  return {
    body,
    headers: {
      "Content-Type": "application/json",
      "X-OpenMates-Timestamp": timestamp,
      "X-OpenMates-Event-Id": eventId,
      "X-OpenMates-Signature": `sha256=${createHmac("sha256", secret).update(canonical).digest("hex")}`,
    },
  };
}

export async function validateRuntimeWebhookDestination(rawUrl: string, resolvedAddresses?: string[]): Promise<URL> {
  void WEBHOOK_EGRESS_POLICY;
  const url = new URL(rawUrl);
  if (url.protocol !== "https:" || url.username || url.password || url.hash) throw new Error("webhook_target_not_allowed");
  const port = url.port ? Number(url.port) : 443;
  if (!ALLOWED_WEBHOOK_PORTS.has(port) || url.hostname === "localhost") throw new Error("webhook_target_not_allowed");
  const addresses = resolvedAddresses?.map((address) => ({ address })) ?? (isIP(url.hostname)
    ? [{ address: url.hostname, family: isIP(url.hostname) }]
    : await dns.lookup(url.hostname, { all: true, verbatim: true, hints: dnsModule.ADDRCONFIG }));
  if (!addresses.length || addresses.some(({ address }) => isPrivateAddress(address))) throw new Error("webhook_target_not_allowed");
  return url;
}
