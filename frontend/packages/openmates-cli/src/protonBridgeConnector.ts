/*
 * Proton Mail Bridge local connector primitives.
 *
 * Purpose: detect/start Proton Bridge and keep Bridge credentials local to the CLI.
 * Architecture: online-only connected-account connector; cloud receives status only.
 * Security: Bridge IMAP/SMTP secrets stay in process memory and are redacted from output.
 * Spec: docs/specs/proton-bridge-cli-connector/spec.yml
 * Tests: frontend/packages/openmates-cli/tests/protonBridgeConnector*.test.ts
 */

import { spawn, type ChildProcessWithoutNullStreams } from "node:child_process";
import { existsSync } from "node:fs";
import { connect as connectTcp, type Socket } from "node:net";
import { platform as nodePlatform } from "node:os";
import { stdin, stderr } from "node:process";
import { createInterface } from "node:readline/promises";
import { randomUUID } from "node:crypto";
import { setTimeout as sleep } from "node:timers/promises";
import type { LocalConnectorRequestFrame, OpenMatesWsClient } from "./ws.js";

export const PROTON_BRIDGE_PROVIDER_ID = "protonmail_bridge";
export const PROTON_BRIDGE_APP_ID = "mail";
export const PROTON_WRITE_DELAY_SECONDS = 30;
const DEFAULT_HEARTBEAT_INTERVAL_MS = 25_000;
const DEFAULT_IMAP_TIMEOUT_MS = 5_000;
const IMAP_COMMAND_TIMEOUT_MS = 15_000;
const SMTP_COMMAND_TIMEOUT_MS = 15_000;
const MACOS_BRIDGE_BINARY = "/Applications/Proton Mail Bridge.app/Contents/MacOS/Proton Mail Bridge";
const CREDENTIAL_FLAG_RE = /^--(?:bridge-password|password|imap-password|smtp-password|proton-password|access-token|refresh-token)(?:=|$)/;
const CREDENTIAL_KEY_RE = /\b(?:bridge[_ -]?password|proton[_ -]?password|imap[_ -]?password|smtp[_ -]?password|access[_ -]?token|refresh[_ -]?token|password)\b/gi;
const CREDENTIAL_VALUE_RE = /(\b(?:bridge[_ -]?password|proton[_ -]?password|imap[_ -]?password|smtp[_ -]?password|access[_ -]?token|refresh[_ -]?token|password)\b\s*[:=]\s*)([^\s,;]+)/gi;

export type ProtonConnectorPlatform = "darwin" | "linux";

export interface ProtonBridgeCommand {
  command: string;
  args: string[];
  shouldStart: boolean;
  installGuidance?: string;
}

export interface ProtonBridgeCredentials {
  accountLabel?: string;
  imapHost: string;
  imapPort: number;
  imapUsername: string;
  imapPassword: string;
  smtpHost?: string;
  smtpPort?: number;
  smtpUsername?: string;
  smtpPassword?: string;
}

export interface ProtonLocalConnectorRegistration {
  provider_id: typeof PROTON_BRIDGE_PROVIDER_ID;
  app_id: typeof PROTON_BRIDGE_APP_ID;
  connector_instance_id: string;
  label: string;
  capabilities: string[];
  execution_mode: "local_connector";
  status: "online";
  metadata: {
    bridge_host: "localhost";
    bridge_transport: "imap_smtp";
    capabilities: string[];
    write_delay_seconds?: number;
  };
}

export interface ProtonLocalConnectorClient {
  registerLocalConnectedAccountConnector(input: ProtonLocalConnectorRegistration): Promise<{
    connected_account_id: string;
    connector_session_id: string;
    heartbeat_interval_ms?: number;
  }>;
  sendLocalConnectedAccountConnectorHeartbeat(input: {
    connector_session_id: string;
    connected_account_id: string;
    status: "online" | "offline";
    capabilities: string[];
    health_summary?: Record<string, unknown>;
  }): Promise<Record<string, unknown>>;
  completeLocalConnectedAccountConnectorRequest?(input: {
    connector_session_id: string;
    connected_account_id: string;
    request_id: string;
    status: "ok" | "error" | "cancelled";
    result?: Record<string, unknown>;
    error_code?: string;
    error_message?: string;
  }): Promise<Record<string, unknown>>;
  openLocalConnectorWebSocket?: () => Promise<OpenMatesWsClient>;
}

export interface ProtonBridgeConnectorDeps {
  platform?: ProtonConnectorPlatform;
  exists?: (path: string) => boolean;
  findExecutable?: (name: string) => string | null;
  hasHomebrew?: () => boolean;
  spawnBridge?: (command: string, args: string[]) => ProtonBridgeProcess;
  captureBridgeInfo?: () => Promise<string>;
  promptBridgeCredentials?: () => Promise<ProtonBridgeCredentials>;
  confirmWriteMode?: (warning: string) => Promise<boolean>;
  validateImap?: (credentials: ProtonBridgeCredentials) => Promise<void>;
  searchImap?: (credentials: ProtonBridgeCredentials, arguments_: Record<string, unknown>) => Promise<Record<string, unknown>[]>;
  sendSmtp?: (credentials: ProtonBridgeCredentials, payload: Record<string, unknown>) => Promise<Record<string, unknown>>;
  heartbeatOnce?: boolean;
  localRequestOnce?: boolean;
  stdout?: Pick<typeof console, "log">;
  stderr?: Pick<typeof console, "error">;
  connectorInstanceId?: string;
}

export interface ProtonBridgeProcess {
  startedByOpenMates: boolean;
  stop: () => Promise<void> | void;
}

export interface ProtonConnectorRunOptions {
  write?: boolean;
  flags?: Record<string, string | boolean>;
}

export interface DelayedSendJob<T = unknown> {
  id: string;
  status: "queued" | "cancelled" | "delivered";
  deliverAt: number;
  undoDisabledReason?: string;
  payload?: T;
}

export function rejectProtonCredentialFlags(argsOrFlags: string[] | Record<string, string | boolean>): void {
  const flags = Array.isArray(argsOrFlags)
    ? argsOrFlags
    : Object.keys(argsOrFlags).map((key) => `--${key}`);
  const rejected = flags.find((flag) => CREDENTIAL_FLAG_RE.test(flag));
  if (rejected) {
    throw new Error(`${rejected.split("=")[0]} is not allowed. Bridge credentials must be read privately from Proton Bridge or a hidden prompt.`);
  }
}

export function redactProtonBridgeSecrets(text: string): string {
  return text.replace(CREDENTIAL_VALUE_RE, "$1<redacted>");
}

export function containsCredentialLikeField(value: unknown): boolean {
  return containsCredentialLikeKey(value);
}

export function resolveProtonBridgeCommand(deps: ProtonBridgeConnectorDeps = {}): ProtonBridgeCommand {
  const platform = deps.platform ?? normalizePlatform(nodePlatform());
  const exists = deps.exists ?? existsSync;
  const findExecutable = deps.findExecutable ?? defaultFindExecutable;

  if (platform === "darwin") {
    if (exists(MACOS_BRIDGE_BINARY)) {
      return { command: MACOS_BRIDGE_BINARY, args: ["-c"], shouldStart: true };
    }
    return {
      command: MACOS_BRIDGE_BINARY,
      args: ["-c"],
      shouldStart: false,
      installGuidance: buildProtonBridgeInstallGuidance("darwin", deps.hasHomebrew?.() ?? findExecutable("brew") !== null),
    };
  }

  const linuxBinary = findExecutable("protonmail-bridge");
  if (linuxBinary) {
    return { command: linuxBinary, args: ["-c"], shouldStart: true };
  }
  return {
    command: "protonmail-bridge",
    args: ["-c"],
    shouldStart: false,
    installGuidance: buildProtonBridgeInstallGuidance("linux"),
  };
}

export function buildProtonBridgeInstallGuidance(platform: ProtonConnectorPlatform, hasHomebrew = false): string {
  if (platform === "darwin") {
    const brewLine = hasHomebrew ? "Run: brew install --cask proton-mail-bridge" : "Install Homebrew or download Proton Mail Bridge from Proton's official website.";
    return [
      "Proton Mail Bridge is required for local Proton Mail access.",
      brewLine,
      "After installing, run `openmates connect-account proton` again.",
    ].join("\n");
  }
  return [
    "Proton Mail Bridge is required for local Proton Mail access.",
    "For Debian/Ubuntu, follow Proton's official DEB instructions: https://proton.me/support/installing-bridge-linux-deb-file",
    "Current Proton DEB example: wget https://proton.me/download/bridge/protonmail-bridge_3.22.0-1_amd64.deb && sudo apt install ./protonmail-bridge_3.22.0-1_amd64.deb",
    "For RPM or Arch/PKGBUILD systems, use Proton's current Bridge download/support page and verify the package before installing.",
    "Package versions change, so prefer Proton's current support page over hardcoded stale package names.",
    "Bridge also requires a supported Linux keychain such as secret-service/GNOME Keyring or pass.",
    "After installing, run `openmates connect-account proton` again.",
  ].join("\n");
}

export function buildProtonConnectorStartupMessage(writeMode: boolean): string {
  const lines = [
    "Proton Mail Bridge connector starting in read-only mode by default.",
    "OpenMates Proton access is active only while this command keeps running.",
    "For long-lived use, run this command inside screen, tmux, or zellij.",
  ];
  if (writeMode) {
    lines.push(buildProtonWriteWarning());
  }
  return lines.join("\n");
}

export function buildProtonWriteWarning(): string {
  return [
    "Write mode warning: OpenMates can submit outbound Proton Mail through local Bridge while this connector runs.",
    `Every send is queued for ${PROTON_WRITE_DELAY_SECONDS} seconds so you can undo before delivery. After delivery, OpenMates cannot recall the email.`,
  ].join("\n");
}

export function parseProtonBridgeInfo(output: string): ProtonBridgeCredentials {
  const sections = splitBridgeInfoSections(output);
  const imap = sections.get("imap") ?? sections.get("imap settings") ?? new Map<string, string>();
  const smtp = sections.get("smtp") ?? sections.get("smtp settings") ?? new Map<string, string>();
  const all = sections.get("all") ?? new Map<string, string>();
  const accountLabel = firstValue(all, "email", "address", "account", "username");
  const imapHost = firstValue(imap, "address", "host", "server") ?? firstValue(all, "imap address", "imap host");
  const imapPort = parsePort(firstValue(imap, "port") ?? firstValue(all, "imap port"), "IMAP");
  const imapUsername = firstValue(imap, "username", "login") ?? firstValue(all, "imap username", "username");
  const imapPassword = firstValue(imap, "password") ?? firstValue(all, "imap password", "password");

  if (!imapHost || !imapUsername || !imapPassword) {
    throw new Error("Could not read Bridge IMAP credentials from Proton Bridge info output.");
  }

  const credentials: ProtonBridgeCredentials = {
    accountLabel,
    imapHost,
    imapPort,
    imapUsername,
    imapPassword,
  };
  const smtpHost = firstValue(smtp, "address", "host", "server") ?? firstValue(all, "smtp address", "smtp host");
  const smtpPortText = firstValue(smtp, "port") ?? firstValue(all, "smtp port");
  const smtpUsername = firstValue(smtp, "username", "login") ?? firstValue(all, "smtp username");
  const smtpPassword = firstValue(smtp, "password") ?? firstValue(all, "smtp password");
  if (smtpHost) credentials.smtpHost = smtpHost;
  if (smtpPortText) credentials.smtpPort = parsePort(smtpPortText, "SMTP");
  if (smtpUsername) credentials.smtpUsername = smtpUsername;
  if (smtpPassword) credentials.smtpPassword = smtpPassword;
  validateProtonBridgeCredentials(credentials);
  return credentials;
}

export function validateProtonBridgeCredentials(credentials: ProtonBridgeCredentials): void {
  assertLocalBridgeHost(credentials.imapHost, "IMAP");
  if (credentials.smtpHost) assertLocalBridgeHost(credentials.smtpHost, "SMTP");
  if (!Number.isInteger(credentials.imapPort) || credentials.imapPort <= 0 || credentials.imapPort > 65_535) {
    throw new Error("Bridge IMAP port must be a valid TCP port.");
  }
  if (credentials.smtpPort !== undefined && (!Number.isInteger(credentials.smtpPort) || credentials.smtpPort <= 0 || credentials.smtpPort > 65_535)) {
    throw new Error("Bridge SMTP port must be a valid TCP port.");
  }
}

export async function validateProtonBridgeImap(credentials: ProtonBridgeCredentials, timeoutMs = DEFAULT_IMAP_TIMEOUT_MS): Promise<void> {
  validateProtonBridgeCredentials(credentials);
  await new Promise<void>((resolve, reject) => {
    const socket = connectTcp({ host: credentials.imapHost, port: credentials.imapPort });
    const timer = setTimeout(() => {
      socket.destroy();
      reject(new Error("Timed out connecting to local Proton Bridge IMAP."));
    }, timeoutMs);
    socket.once("connect", () => {
      clearTimeout(timer);
      socket.end();
      resolve();
    });
    socket.once("error", (error) => {
      clearTimeout(timer);
      reject(new Error(`Could not connect to local Proton Bridge IMAP: ${redactProtonBridgeSecrets(error.message)}`));
    });
  });
}

export function createProtonLocalConnectorRegistration(params: {
  connectorInstanceId: string;
  credentials: ProtonBridgeCredentials;
  write: boolean;
}): ProtonLocalConnectorRegistration {
  validateProtonBridgeCredentials(params.credentials);
  return {
    provider_id: PROTON_BRIDGE_PROVIDER_ID,
    app_id: PROTON_BRIDGE_APP_ID,
    connector_instance_id: params.connectorInstanceId,
    label: params.credentials.accountLabel || "Proton Mail",
    capabilities: params.write ? ["read", "write"] : ["read"],
    execution_mode: "local_connector",
    status: "online",
    metadata: {
      bridge_host: "localhost",
      bridge_transport: "imap_smtp",
      capabilities: params.write ? ["read", "write"] : ["read"],
      ...(params.write ? { write_delay_seconds: PROTON_WRITE_DELAY_SECONDS } : {}),
    },
  };
}

export async function runProtonBridgeConnector(
  client: ProtonLocalConnectorClient,
  options: ProtonConnectorRunOptions = {},
  deps: ProtonBridgeConnectorDeps = {},
): Promise<{ connectedAccountId: string; connectorSessionId: string; capabilities: string[] }> {
  rejectProtonCredentialFlags(options.flags ?? {});
  const stdout = deps.stdout ?? console;
  const stderr = deps.stderr ?? console;
  const write = options.write === true;

  stdout.log(buildProtonConnectorStartupMessage(write));
  if (write) {
    const confirmed = await (deps.confirmWriteMode ?? defaultConfirmWriteMode)(buildProtonWriteWarning());
    if (!confirmed) throw new Error("Proton write mode was not enabled because confirmation was declined.");
  }

  const bridgeCommand = resolveProtonBridgeCommand(deps);
  if (!bridgeCommand.shouldStart) {
    throw new Error(bridgeCommand.installGuidance ?? "Proton Mail Bridge is not installed.");
  }

  const bridge = (deps.spawnBridge ?? startProtonBridgeProcess)(bridgeCommand.command, bridgeCommand.args);
  let registration;
  const abortController = new AbortController();
  try {
    const credentials = deps.captureBridgeInfo
      ? parseProtonBridgeInfo(await deps.captureBridgeInfo())
      : deps.promptBridgeCredentials
        ? await deps.promptBridgeCredentials()
        : await captureOrPromptBridgeCredentials(bridgeCommand.command, bridgeCommand.args);
    validateProtonBridgeCredentials(credentials);
    await (deps.validateImap ?? validateProtonBridgeImap)(credentials);
    registration = await client.registerLocalConnectedAccountConnector(createProtonLocalConnectorRegistration({
      connectorInstanceId: deps.connectorInstanceId ?? randomUUID(),
      credentials,
      write,
    }));
    const capabilities = write ? ["read", "write"] : ["read"];
    if (deps.heartbeatOnce === true) {
      await heartbeatLoop(client, {
        connectorSessionId: registration.connector_session_id,
        connectedAccountId: registration.connected_account_id,
        capabilities,
        heartbeatIntervalMs: registration.heartbeat_interval_ms ?? DEFAULT_HEARTBEAT_INTERVAL_MS,
        once: true,
      });
      return {
        connectedAccountId: registration.connected_account_id,
        connectorSessionId: registration.connector_session_id,
        capabilities,
      };
    }
    await Promise.race([
      heartbeatLoop(client, {
        connectorSessionId: registration.connector_session_id,
        connectedAccountId: registration.connected_account_id,
        capabilities,
        heartbeatIntervalMs: registration.heartbeat_interval_ms ?? DEFAULT_HEARTBEAT_INTERVAL_MS,
        once: false,
        signal: abortController.signal,
      }),
      localConnectorRequestLoop(client, {
        connectorSessionId: registration.connector_session_id,
        connectedAccountId: registration.connected_account_id,
        capabilities,
        credentials,
        searchImap: deps.searchImap ?? searchProtonBridgeImap,
        sendSmtp: deps.sendSmtp ?? sendProtonBridgeSmtp,
        signal: abortController.signal,
        once: deps.localRequestOnce === true,
      }),
    ]);
    return {
      connectedAccountId: registration.connected_account_id,
      connectorSessionId: registration.connector_session_id,
      capabilities,
    };
  } catch (error) {
    stderr.error(redactProtonBridgeSecrets(error instanceof Error ? error.message : String(error)));
    throw error;
  } finally {
    abortController.abort();
    if (registration) {
      await client.sendLocalConnectedAccountConnectorHeartbeat({
        connector_session_id: registration.connector_session_id,
        connected_account_id: registration.connected_account_id,
        status: "offline",
        capabilities: write ? ["read", "write"] : ["read"],
        health_summary: { exit: "connector_stopped" },
      }).catch(() => undefined);
    }
    if (bridge.startedByOpenMates) {
      await bridge.stop();
    }
  }
}

export class ProtonDelayedSendQueue<T = unknown> {
  private readonly jobs = new Map<string, DelayedSendJob<T> & { timer?: NodeJS.Timeout }>();
  private readonly delayMs: number;

  constructor(delayMs = PROTON_WRITE_DELAY_SECONDS * 1000) {
    this.delayMs = delayMs;
  }

  queue(payload: T, deliver: (payload: T) => Promise<void> | void, now = Date.now()): DelayedSendJob<T> {
    const id = randomUUID();
    const job: DelayedSendJob<T> & { timer?: NodeJS.Timeout } = {
      id,
      status: "queued",
      deliverAt: now + this.delayMs,
      payload,
    };
    job.timer = setTimeout(async () => {
      if (job.status !== "queued") return;
      const payload = job.payload;
      if (payload === undefined) return;
      try {
        await deliver(payload);
        job.status = "delivered";
        job.undoDisabledReason = "OpenMates cannot recall Proton Mail after SMTP delivery.";
      } catch {
        job.status = "cancelled";
        job.undoDisabledReason = "Delivery failed before OpenMates received a confirmation.";
      } finally {
        job.payload = undefined;
      }
    }, this.delayMs);
    this.jobs.set(id, job);
    return stripTimer(job);
  }

  undo(id: string): DelayedSendJob<T> {
    const job = this.jobs.get(id);
    if (!job) throw new Error("Delayed send job was not found.");
    if (job.status === "delivered") {
      job.undoDisabledReason = "OpenMates cannot recall Proton Mail after SMTP delivery.";
      return stripTimer(job);
    }
    if (job.status === "queued") {
      if (job.timer) clearTimeout(job.timer);
      job.status = "cancelled";
      job.payload = undefined;
    }
    return stripTimer(job);
  }

  get(id: string): DelayedSendJob<T> | undefined {
    const job = this.jobs.get(id);
    return job ? stripTimer(job) : undefined;
  }

  clear(): void {
    for (const job of this.jobs.values()) {
      if (job.timer) clearTimeout(job.timer);
      job.payload = undefined;
    }
    this.jobs.clear();
  }
}

async function localConnectorRequestLoop(
  client: ProtonLocalConnectorClient,
  params: {
    connectorSessionId: string;
    connectedAccountId: string;
    capabilities: string[];
    credentials: ProtonBridgeCredentials;
    searchImap: (credentials: ProtonBridgeCredentials, arguments_: Record<string, unknown>) => Promise<Record<string, unknown>[]>;
    sendSmtp: (credentials: ProtonBridgeCredentials, payload: Record<string, unknown>) => Promise<Record<string, unknown>>;
    signal: AbortSignal;
    once: boolean;
  },
): Promise<void> {
  if (!client.openLocalConnectorWebSocket || !client.completeLocalConnectedAccountConnectorRequest) {
    await waitForAbort(params.signal);
    return;
  }
  const ws = await client.openLocalConnectorWebSocket();
  const sendQueue = new ProtonDelayedSendQueue<Record<string, unknown>>();
  let resolveOnce: (() => void) | null = null;
  const onceHandled = new Promise<void>((resolve) => {
    resolveOnce = resolve;
  });
  const removeListener = ws.onLocalConnectorRequest((request) => {
    void handleLocalConnectorRequest(client, request, params, sendQueue).finally(() => {
      if (params.once) resolveOnce?.();
    });
  });
  try {
    await (params.once ? Promise.race([onceHandled, waitForAbort(params.signal)]) : waitForAbort(params.signal));
  } finally {
    removeListener();
    sendQueue.clear();
    ws.close();
  }
}

async function handleLocalConnectorRequest(
  client: ProtonLocalConnectorClient,
  request: LocalConnectorRequestFrame,
  params: {
    connectorSessionId: string;
    connectedAccountId: string;
    capabilities: string[];
    credentials: ProtonBridgeCredentials;
    searchImap: (credentials: ProtonBridgeCredentials, arguments_: Record<string, unknown>) => Promise<Record<string, unknown>[]>;
    sendSmtp: (credentials: ProtonBridgeCredentials, payload: Record<string, unknown>) => Promise<Record<string, unknown>>;
  },
  sendQueue: ProtonDelayedSendQueue<Record<string, unknown>>,
): Promise<void> {
  if (
    request.connector_session_id !== params.connectorSessionId ||
    request.connected_account_id !== params.connectedAccountId ||
    !client.completeLocalConnectedAccountConnectorRequest
  ) {
    return;
  }
  const complete = async (input: {
    status: "ok" | "error" | "cancelled";
    result?: Record<string, unknown>;
    error_code?: string;
    error_message?: string;
  }) => {
    await client.completeLocalConnectedAccountConnectorRequest!({
      connector_session_id: params.connectorSessionId,
      connected_account_id: params.connectedAccountId,
      request_id: request.request_id,
      ...input,
    });
  };
  try {
    const arguments_ = request.arguments && typeof request.arguments === "object" ? request.arguments : {};
    if (containsCredentialLikeKey(arguments_)) {
      await complete({ status: "error", error_code: "credential_fields_not_allowed", error_message: "Local connector request contained forbidden credential fields." });
      return;
    }
    if (request.action === "mail.search") {
      const messages = await params.searchImap(params.credentials, arguments_);
      await complete({ status: "ok", result: { messages } });
      return;
    }
    if (request.action === "mail.send") {
      if (!params.capabilities.includes("write")) {
        await complete({ status: "error", error_code: "write_not_enabled", error_message: "Proton connector write mode is not enabled." });
        return;
      }
      const queued = sendQueue.queue(arguments_, async (payload) => {
        try {
          const receipt = await params.sendSmtp(params.credentials, payload);
          await complete({ status: "ok", result: { ...receipt, delayed_send_job_id: queued.id } });
        } catch (error) {
          await complete({
            status: "error",
            error_code: "smtp_delivery_failed",
            error_message: redactProtonBridgeSecrets(error instanceof Error ? error.message : String(error)),
          });
        }
      });
      return;
    }
    await complete({ status: "error", error_code: "unsupported_action", error_message: `Unsupported local connector action: ${request.action}` });
  } catch (error) {
    await complete({
      status: "error",
      error_code: "local_connector_request_failed",
      error_message: redactProtonBridgeSecrets(error instanceof Error ? error.message : String(error)),
    });
  }
}

async function waitForAbort(signal: AbortSignal): Promise<void> {
  if (signal.aborted) return;
  await new Promise<void>((resolve) => {
    signal.addEventListener("abort", () => resolve(), { once: true });
  });
}

async function searchProtonBridgeImap(
  credentials: ProtonBridgeCredentials,
  arguments_: Record<string, unknown>,
): Promise<Record<string, unknown>[]> {
  const query = typeof arguments_.query === "string" ? arguments_.query.trim() : "";
  const mailbox = typeof arguments_.mailbox === "string" && arguments_.mailbox.trim() ? arguments_.mailbox.trim() : "INBOX";
  const limit = clampLimit(arguments_.limit);
  const imap = await openTextSocket(credentials.imapHost, credentials.imapPort, IMAP_COMMAND_TIMEOUT_MS);
  try {
    await imap.readUntil((text) => /^\* OK/im.test(text));
    await imap.command(`LOGIN ${quoteImap(credentials.imapUsername)} ${quoteImap(credentials.imapPassword)}`);
    await imap.command(`SELECT ${quoteImap(mailbox)}`);
    const searchResponse = await imap.command(query ? `SEARCH CHARSET UTF-8 TEXT ${quoteImap(query)}` : "SEARCH ALL");
    const ids = parseImapSearchIds(searchResponse).slice(-limit).reverse();
    const messages: Record<string, unknown>[] = [];
    for (const id of ids) {
      const fetchResponse = await imap.command(`FETCH ${id} (BODY.PEEK[HEADER.FIELDS (FROM SUBJECT DATE MESSAGE-ID)] BODY.PEEK[TEXT]<0.500>)`);
      messages.push(parseImapFetchMessage(fetchResponse, id, credentials));
    }
    return messages;
  } finally {
    await imap.command("LOGOUT").catch(() => undefined);
    imap.close();
  }
}

async function sendProtonBridgeSmtp(
  credentials: ProtonBridgeCredentials,
  payload: Record<string, unknown>,
): Promise<Record<string, unknown>> {
  if (!credentials.smtpHost || !credentials.smtpPort) {
    throw new Error("Bridge SMTP settings are required for Proton write mode.");
  }
  const to = normalizeRecipients(payload.to);
  if (to.length === 0) throw new Error("SMTP send requires at least one recipient.");
  const subject = typeof payload.subject === "string" ? payload.subject.slice(0, 300) : "";
  const bodyText = typeof payload.body_text === "string"
    ? payload.body_text
    : typeof payload.body === "string"
      ? payload.body
      : "";
  const from = credentials.smtpUsername || credentials.imapUsername;
  const messageId = `<om-${randomUUID()}@local.openmates>`;
  const smtp = await openTextSocket(credentials.smtpHost, credentials.smtpPort, SMTP_COMMAND_TIMEOUT_MS);
  try {
    await smtp.readUntil((text) => /^220[ -]/m.test(text));
    await smtp.rawCommand("EHLO openmates.local", (text) => /^250\s/m.test(text), /^250[ -]/m);
    const auth = Buffer.from(`\0${credentials.smtpUsername || credentials.imapUsername}\0${credentials.smtpPassword || credentials.imapPassword}`).toString("base64");
    try {
      await smtp.rawCommand(`AUTH PLAIN ${auth}`, (text) => /^235[ -]/m.test(text), /^235[ -]/m);
    } catch {
      throw new Error("Local SMTP authentication failed.");
    }
    await smtp.rawCommand(`MAIL FROM:<${from}>`, (text) => /^250[ -]/m.test(text), /^250[ -]/m);
    for (const recipient of to) {
      await smtp.rawCommand(`RCPT TO:<${recipient}>`, (text) => /^250[ -]/m.test(text), /^250[ -]/m);
    }
    await smtp.rawCommand("DATA", (text) => /^354[ -]/m.test(text), /^354[ -]/m);
    await smtp.rawCommand(`${buildSmtpMessage({ from, to, subject, bodyText, messageId })}\r\n.`, (text) => /^250[ -]/m.test(text), /^250[ -]/m);
    await smtp.rawCommand("QUIT", (text) => /^221[ -]/m.test(text), /^221[ -]/m).catch(() => undefined);
    return { provider: PROTON_BRIDGE_PROVIDER_ID, message_id: messageId, delivered: true };
  } finally {
    smtp.close();
  }
}

function clampLimit(value: unknown): number {
  const parsed = typeof value === "number" ? value : Number.parseInt(String(value ?? "10"), 10);
  if (!Number.isFinite(parsed)) return 10;
  return Math.max(1, Math.min(Math.floor(parsed), 50));
}

function parseImapSearchIds(response: string): string[] {
  const match = response.match(/^\* SEARCH\s+(.*)$/im);
  if (!match) return [];
  return match[1].trim().split(/\s+/).filter((id) => /^\d+$/.test(id));
}

function parseImapFetchMessage(response: string, id: string, credentials: ProtonBridgeCredentials): Record<string, unknown> {
  const from = redactLocalAccountText(firstHeader(response, "From") || "", credentials);
  const subject = redactLocalAccountText(firstHeader(response, "Subject") || "", credentials).slice(0, 300);
  const date = firstHeader(response, "Date") || null;
  const messageId = firstHeader(response, "Message-ID") || null;
  const snippet = redactLocalAccountText(extractImapSnippet(response), credentials).slice(0, 1_000);
  return {
    uid: id,
    from,
    subject,
    date,
    message_id: messageId,
    snippet,
  };
}

function firstHeader(response: string, name: string): string | null {
  const match = response.match(new RegExp(`^${name}:\\s*(.*)$`, "im"));
  return match ? match[1].trim() : null;
}

function extractImapSnippet(response: string): string {
  return response
    .split(/\r?\n/)
    .filter((line) => !/^\*|^A\d+|^(From|Subject|Date|Message-ID):/i.test(line.trim()))
    .join(" ")
    .replace(/\s+/g, " ")
    .trim();
}

function quoteImap(value: string): string {
  return `"${value.replace(/\\/g, "\\\\").replace(/"/g, '\\"')}"`;
}

function redactLocalAccountText(value: string, credentials: ProtonBridgeCredentials): string {
  let redacted = value;
  for (const secret of [credentials.imapPassword, credentials.smtpPassword, credentials.imapUsername, credentials.smtpUsername]) {
    if (secret) redacted = redacted.replaceAll(secret, secret.includes("@") ? "<account>" : "<redacted>");
  }
  return redacted;
}

function normalizeRecipients(value: unknown): string[] {
  const items = Array.isArray(value) ? value : typeof value === "string" ? [value] : [];
  return items
    .filter((item): item is string => typeof item === "string")
    .map((item) => item.trim())
    .filter((item) => /^[^\s@<>]+@[^\s@<>]+\.[^\s@<>]+$/.test(item))
    .slice(0, 20);
}

function buildSmtpMessage(params: { from: string; to: string[]; subject: string; bodyText: string; messageId: string }): string {
  const headers = [
    `Message-ID: ${params.messageId}`,
    `Date: ${new Date().toUTCString()}`,
    `From: ${params.from}`,
    `To: ${params.to.join(", ")}`,
    `Subject: ${params.subject.replace(/\r?\n/g, " ")}`,
    "MIME-Version: 1.0",
    "Content-Type: text/plain; charset=utf-8",
  ];
  return `${headers.join("\r\n")}\r\n\r\n${dotStuff(params.bodyText)}`;
}

function dotStuff(value: string): string {
  return value.replace(/\r?\n/g, "\r\n").replace(/^\./gm, "..");
}

function containsCredentialLikeKey(value: unknown): boolean {
  if (!value || typeof value !== "object") return false;
  if (Array.isArray(value)) return value.some(containsCredentialLikeKey);
  for (const [key, child] of Object.entries(value as Record<string, unknown>)) {
    CREDENTIAL_KEY_RE.lastIndex = 0;
    if (CREDENTIAL_KEY_RE.test(key)) return true;
    if (containsCredentialLikeKey(child)) return true;
  }
  return false;
}

async function openTextSocket(host: string, port: number, timeoutMs: number): Promise<{
  command: (command: string, expected?: RegExp) => Promise<string>;
  rawCommand: (command: string, done: (text: string) => boolean, expected?: RegExp) => Promise<string>;
  readUntil: (done: (text: string) => boolean) => Promise<string>;
  close: () => void;
}> {
  const socket = connectTcp({ host, port });
  socket.setEncoding("utf8");
  let buffer = "";
  socket.on("data", (chunk) => {
    buffer += String(chunk);
  });
  await new Promise<void>((resolve, reject) => {
    const timer = setTimeout(() => {
      socket.destroy();
      reject(new Error(`Timed out connecting to ${host}:${port}.`));
    }, timeoutMs);
    socket.once("connect", () => {
      clearTimeout(timer);
      resolve();
    });
    socket.once("error", (error) => {
      clearTimeout(timer);
      reject(error);
    });
  });
  let tagCounter = 0;
  const readUntil = async (done: (text: string) => boolean): Promise<string> => waitForSocketText(socket, () => buffer, done, timeoutMs);
  return {
    readUntil,
    command: async (command: string, expected?: RegExp) => {
      const tag = `A${String(++tagCounter).padStart(4, "0")}`;
      const marker = new RegExp(`^${tag}\\s+`, "m");
      buffer = "";
      socket.write(`${tag} ${command}\r\n`);
      const response = await waitForSocketText(socket, () => buffer, (text) => marker.test(text), timeoutMs);
      if (expected && !expected.test(response)) {
        throw new Error(`Local mail command failed: ${redactProtonBridgeSecrets(response.split(/\r?\n/).slice(-2).join(" "))}`);
      }
      if (!expected && new RegExp(`^${tag}\\s+(?:NO|BAD)`, "im").test(response)) {
        throw new Error(`Local mail command failed: ${redactProtonBridgeSecrets(response.split(/\r?\n/).slice(-2).join(" "))}`);
      }
      return response;
    },
    rawCommand: async (command: string, done: (text: string) => boolean, expected?: RegExp) => {
      buffer = "";
      socket.write(`${command}\r\n`);
      const response = await waitForSocketText(socket, () => buffer, done, timeoutMs);
      if (expected && !expected.test(response)) {
        throw new Error(`Local mail command failed: ${redactProtonBridgeSecrets(response.split(/\r?\n/).slice(-2).join(" "))}`);
      }
      return response;
    },
    close: () => socket.destroy(),
  };
}

async function waitForSocketText(
  socket: Socket,
  getBuffer: () => string,
  done: (text: string) => boolean,
  timeoutMs: number,
): Promise<string> {
  return await new Promise<string>((resolve, reject) => {
    const timer = setTimeout(() => cleanup(() => reject(new Error("Timed out waiting for local mail server response."))), timeoutMs);
    const check = () => {
      const text = getBuffer();
      if (done(text)) cleanup(() => resolve(text));
    };
    const onData = () => check();
    const onError = (error: Error) => cleanup(() => reject(error));
    const cleanup = (finish: () => void) => {
      clearTimeout(timer);
      socket.off("data", onData);
      socket.off("error", onError);
      finish();
    };
    socket.on("data", onData);
    socket.on("error", onError);
    check();
  });
}

function startProtonBridgeProcess(command: string, args: string[]): ProtonBridgeProcess {
  const child: ChildProcessWithoutNullStreams = spawn(command, args, { stdio: "pipe" });
  child.stdout.on("data", () => undefined);
  child.stderr.on("data", () => undefined);
  return {
    startedByOpenMates: true,
    stop: async () => {
      if (child.exitCode !== null || child.killed) return;
      child.kill("SIGTERM");
      await Promise.race([
        new Promise<void>((resolve) => child.once("exit", () => resolve())),
        sleep(2_000).then(() => {
          if (child.exitCode === null && !child.killed) child.kill("SIGKILL");
        }),
      ]);
    },
  };
}

async function heartbeatLoop(
  client: ProtonLocalConnectorClient,
  params: {
    connectorSessionId: string;
    connectedAccountId: string;
    capabilities: string[];
    heartbeatIntervalMs: number;
    once: boolean;
    signal?: AbortSignal;
  },
): Promise<void> {
  await client.sendLocalConnectedAccountConnectorHeartbeat({
    connector_session_id: params.connectorSessionId,
    connected_account_id: params.connectedAccountId,
    status: "online",
    capabilities: params.capabilities,
    health_summary: { imap: "ok" },
  });
  if (params.once) return;
  while (true) {
    try {
      await sleep(params.heartbeatIntervalMs, undefined, { signal: params.signal });
    } catch (error) {
      if (params.signal?.aborted) return;
      throw error;
    }
    await client.sendLocalConnectedAccountConnectorHeartbeat({
      connector_session_id: params.connectorSessionId,
      connected_account_id: params.connectedAccountId,
      status: "online",
      capabilities: params.capabilities,
      health_summary: { imap: "ok" },
    });
  }
}

function splitBridgeInfoSections(output: string): Map<string, Map<string, string>> {
  const sections = new Map<string, Map<string, string>>([["all", new Map()]]);
  let current = sections.get("all")!;
  for (const rawLine of output.split(/\r?\n/)) {
    const line = rawLine.trim();
    if (!line) continue;
    const lower = normalizeKey(line.replace(/:$/, ""));
    if (/^(imap|imap settings|smtp|smtp settings)$/i.test(line.replace(/:$/, ""))) {
      current = new Map<string, string>();
      sections.set(lower, current);
      continue;
    }
    const separator = line.indexOf(":") >= 0 ? line.indexOf(":") : line.indexOf("=");
    if (separator <= 0) continue;
    const key = normalizeKey(line.slice(0, separator));
    const value = line.slice(separator + 1).trim();
    current.set(key, value);
    sections.get("all")!.set(key, value);
  }
  return sections;
}

function firstValue(map: Map<string, string>, ...keys: string[]): string | undefined {
  for (const key of keys) {
    const value = map.get(normalizeKey(key));
    if (value) return value;
  }
  return undefined;
}

function normalizeKey(key: string): string {
  return key.trim().toLowerCase().replace(/\s+/g, " ").replace(/_/g, " ");
}

function parsePort(value: string | undefined, label: string): number {
  if (!value) throw new Error(`Missing Bridge ${label} port.`);
  const parsed = Number.parseInt(value, 10);
  if (!Number.isInteger(parsed)) throw new Error(`Bridge ${label} port is invalid.`);
  return parsed;
}

function assertLocalBridgeHost(host: string, label: string): void {
  const normalized = host.toLowerCase().replace(/^\[|\]$/g, "");
  if (!["localhost", "127.0.0.1", "::1"].includes(normalized)) {
    throw new Error(`Bridge ${label} host must be localhost, not ${host}.`);
  }
}

function normalizePlatform(platform: NodeJS.Platform): ProtonConnectorPlatform {
  if (platform === "darwin" || platform === "linux") return platform;
  throw new Error("Proton Bridge connector supports macOS and Linux only.");
}

function defaultFindExecutable(name: string): string | null {
  const paths = (process.env.PATH ?? "").split(process.platform === "win32" ? ";" : ":");
  for (const directory of paths) {
    const candidate = `${directory}/${name}`;
    if (candidate !== `/${name}` && existsSync(candidate)) return candidate;
  }
  return null;
}

async function defaultConfirmWriteMode(): Promise<boolean> {
  throw new Error("Interactive Proton write-mode confirmation is unavailable in this runtime.");
}

async function captureOrPromptBridgeCredentials(command: string, args: string[]): Promise<ProtonBridgeCredentials> {
  try {
    return parseProtonBridgeInfo(await captureProtonBridgeInfo(command, args));
  } catch {
    return promptProtonBridgeCredentials();
  }
}

async function captureProtonBridgeInfo(command: string, args: string[]): Promise<string> {
  return await new Promise<string>((resolve, reject) => {
    const child = spawn(command, args, { stdio: "pipe" });
    let output = "";
    let errorOutput = "";
    const timer = setTimeout(() => {
      child.kill("SIGTERM");
      reject(new Error("Timed out reading Proton Bridge info."));
    }, 10_000);
    child.stdout.on("data", (chunk) => {
      output += chunk.toString();
    });
    child.stderr.on("data", (chunk) => {
      errorOutput += chunk.toString();
    });
    child.once("error", (error) => {
      clearTimeout(timer);
      reject(error);
    });
    child.once("exit", () => {
      clearTimeout(timer);
      if (output.trim()) resolve(output);
      else reject(new Error(redactProtonBridgeSecrets(errorOutput || "Proton Bridge info produced no output.")));
    });
    child.stdin.write("info\nquit\n");
    child.stdin.end();
  });
}

async function promptProtonBridgeCredentials(): Promise<ProtonBridgeCredentials> {
  const rl = createInterface({ input: stdin, output: stderr });
  try {
    const imapHost = (await rl.question("Bridge IMAP host [127.0.0.1]: ")).trim() || "127.0.0.1";
    const imapPort = parsePort((await rl.question("Bridge IMAP port: ")).trim(), "IMAP");
    const imapUsername = (await rl.question("Bridge IMAP username: ")).trim();
    rl.close();
    const imapPassword = await promptHidden("Bridge IMAP password: ");
    const credentials = { imapHost, imapPort, imapUsername, imapPassword };
    validateProtonBridgeCredentials(credentials);
    return credentials;
  } finally {
    rl.close();
  }
}

async function promptHidden(prompt: string): Promise<string> {
  if (!stdin.isTTY || typeof stdin.setRawMode !== "function") {
    throw new Error("Hidden Bridge credential prompt requires an interactive terminal.");
  }
  stderr.write(prompt);
  const wasRaw = stdin.isRaw === true;
  stdin.setRawMode(true);
  stdin.resume();
  return await new Promise<string>((resolve, reject) => {
    let value = "";
    const onData = (chunk: Buffer) => {
      const text = chunk.toString("utf8");
      for (const char of text) {
        if (char === "\u0003") {
          cleanup();
          reject(new Error("Bridge credential prompt cancelled."));
          return;
        }
        if (char === "\r" || char === "\n") {
          cleanup();
          stderr.write("\n");
          resolve(value);
          return;
        }
        if (char === "\u007f" || char === "\b") {
          value = value.slice(0, -1);
        } else {
          value += char;
        }
      }
    };
    const cleanup = () => {
      stdin.off("data", onData);
      stdin.setRawMode(wasRaw);
    };
    stdin.on("data", onData);
  });
}

function stripTimer<T>(job: DelayedSendJob<T> & { timer?: NodeJS.Timeout }): DelayedSendJob<T> {
  const { timer: _timer, ...publicJob } = job;
  return publicJob;
}
