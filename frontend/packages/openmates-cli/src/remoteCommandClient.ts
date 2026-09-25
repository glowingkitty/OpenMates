/** Origin-side review and encryption for Project-confined remote commands. */
import { webcrypto } from "node:crypto";
import { chmodSync, existsSync, lstatSync, mkdirSync, readFileSync, renameSync, writeFileSync } from "node:fs";
import { join } from "node:path";

import { decryptWithAesGcmCombined, encryptWithAesGcmCombined } from "./crypto.js";
import type { OpenMatesClient } from "./client.js";
import type { OpenMatesWsClient } from "./ws.js";
import type { RemoteCommandPolicy } from "./remoteCommandPermissions.js";
import {
  loadRemoteCommandPermissions,
  remoteCommandPresetDigest,
  type ActiveRemoteCommandPresetGrant,
} from "./remoteCommandPermissions.js";
import { resolveStateDir } from "./storage.js";

const cryptoApi = globalThis.crypto ?? webcrypto;
const IDENTIFIER = /^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$/;
const PRESET_GRANTS_FILE = "remote-command-preset-grants.json";
const MAX_COMPLETION_CHARS = 24_000;
const OMISSION_MARKER = "\n\n[... terminal output omitted ...]\n\n";

export interface RemoteCommandExplanation {
  summary: string;
  effects: string[];
  risks: string[];
  uncertainty: string[];
}

export interface RemoteCommandReview {
  protocol_version: 1;
  execution_id: string;
  chat_id: string;
  project_id: string;
  source_id: string;
  state: "REVIEW_REQUIRED";
  created_at: number;
  review_expires_at: number;
  review_token: string;
  approval_requirement: "one_run" | "one_run_or_preset";
  command: RemoteCommandPolicy;
  explanation: RemoteCommandExplanation;
}

export type RemoteCommandApprovalChoice =
  | { kind: "one_run" }
  | { kind: "preset"; preset_id: string; definition_digest: string };

export interface PortableRemoteCommandRequest {
  protocol_version: 1;
  execution_id: string;
  chat_id: string;
  project_id: string;
  source_id: string;
  policy: RemoteCommandPolicy;
  approval: RemoteCommandApprovalChoice;
}

export interface DecryptedRemoteCommandEvent {
  execution_id: string;
  sequence: number;
  event_kind: "status" | "output" | "output_truncated" | "terminal";
  status: "authorizing" | "running" | "succeeded" | "failed" | "stopped" | "timed_out";
  payload: Record<string, unknown>;
}

export interface RemoteCommandOutputSelection {
  text: string;
  coverage: "full" | "selected_excerpt";
  sequence_gap: boolean;
  upstream_truncated: boolean;
  omitted_chars: number;
}

export class RemoteCommandOutputAccumulator {
  #lastSequence = -1;
  #text = "";
  #inputChars = 0;
  #sequenceGap = false;
  #upstreamTruncated = false;

  add(event: DecryptedRemoteCommandEvent): "accepted" | "duplicate" {
    if (event.sequence <= this.#lastSequence) return "duplicate";
    if (event.sequence !== this.#lastSequence + 1) this.#sequenceGap = true;
    this.#lastSequence = event.sequence;
    if (event.event_kind === "output_truncated" || terminalPayloadWasTruncated(event)) this.#upstreamTruncated = true;
    if (event.event_kind !== "output" || typeof event.payload.text !== "string") return "accepted";
    const value = normalizeTerminalText(event.payload.text);
    this.#inputChars += value.length;
    this.#text += value;
    if (this.#text.length > MAX_COMPLETION_CHARS * 2) {
      const half = Math.floor((MAX_COMPLETION_CHARS - OMISSION_MARKER.length) / 2);
      this.#text = `${this.#text.slice(0, half)}${OMISSION_MARKER}${this.#text.slice(-half)}`;
    }
    return "accepted";
  }

  selection(): RemoteCommandOutputSelection {
    if (this.#text.length <= MAX_COMPLETION_CHARS && this.#inputChars <= MAX_COMPLETION_CHARS && !this.#sequenceGap && !this.#upstreamTruncated) {
      return { text: this.#text, coverage: "full", sequence_gap: false, upstream_truncated: false, omitted_chars: 0 };
    }
    const half = Math.max(0, Math.floor((MAX_COMPLETION_CHARS - OMISSION_MARKER.length) / 2));
    const text = this.#text.length <= MAX_COMPLETION_CHARS
      ? this.#text
      : `${this.#text.slice(0, half)}${OMISSION_MARKER}${this.#text.slice(-half)}`;
    return {
      text,
      coverage: "selected_excerpt",
      sequence_gap: this.#sequenceGap,
      upstream_truncated: true,
      omitted_chars: Math.max(0, this.#inputChars - text.length + (text.includes(OMISSION_MARKER) ? OMISSION_MARKER.length : 0)),
    };
  }
}

export function listRemoteCommandPresetGrants(): ActiveRemoteCommandPresetGrant[] {
  const path = join(resolveStateDir(), PRESET_GRANTS_FILE);
  if (!existsSync(path)) return [];
  const stat = lstatSync(path);
  if (!stat.isFile() || stat.isSymbolicLink() || (stat.mode & 0o077) !== 0) throw new Error("Remote command preset grant store is not private");
  const parsed = JSON.parse(readFileSync(path, "utf8")) as { grants?: unknown };
  if (!Array.isArray(parsed.grants)) throw new Error("Invalid remote command preset grant store");
  return parsed.grants.map((value) => {
    const item = record(value, "remote command preset grant");
    return {
      project_id: identifier(item.project_id, "project_id"),
      preset_id: identifier(item.preset_id, "preset_id"),
      definition_digest: typeof item.definition_digest === "string" && /^[a-f0-9]{64}$/i.test(item.definition_digest)
        ? item.definition_digest : fail("invalid preset definition digest"),
      enabled: item.enabled === true ? true : fail("invalid preset grant state"),
    };
  });
}

export function enableRemoteCommandPreset(projectId: string, projectRoot: string, presetId: string): ActiveRemoteCommandPresetGrant {
  identifier(projectId, "project_id");
  identifier(presetId, "preset_id");
  const permissions = loadRemoteCommandPermissions(projectRoot);
  if (!permissions) throw new Error("This Project source has no .openmates/permissions.yml file");
  const grant: ActiveRemoteCommandPresetGrant = {
    project_id: projectId,
    preset_id: presetId,
    definition_digest: remoteCommandPresetDigest(permissions, presetId),
    enabled: true,
  };
  const grants = listRemoteCommandPresetGrants().filter((item) => item.project_id !== projectId || item.preset_id !== presetId);
  writePresetGrants([...grants, grant]);
  return grant;
}

export function disableRemoteCommandPreset(projectId: string, presetId: string): void {
  identifier(projectId, "project_id");
  identifier(presetId, "preset_id");
  writePresetGrants(listRemoteCommandPresetGrants().filter((item) => item.project_id !== projectId || item.preset_id !== presetId));
}

export function renderRemoteCommandReview(review: RemoteCommandReview): string {
  const command = review.command;
  const resources = [
    `Source access: ${command.source_access}`,
    `Writable profiles: ${command.writable_profiles.join(", ") || "none"}`,
    `Network profile: ${command.network_profile ?? "none"}`,
    `Credential profiles: ${command.credential_profiles.join(", ") || "none"}`,
  ];
  return [
    "Remote Project command review",
    `Explanation: ${safe(review.explanation.summary)}`,
    ...review.explanation.effects.map((item) => `Effect: ${safe(item)}`),
    ...review.explanation.risks.map((item) => `Risk: ${safe(item)}`),
    ...review.explanation.uncertainty.map((item) => `Uncertainty: ${safe(item)}`),
    `Command argv: ${JSON.stringify(command.argv.map(safe))}`,
    `Working directory: ${safe(command.cwd)}`,
    `Mode: ${command.mode}`,
    `Deadline: ${command.deadline_ms} ms`,
    `Approval: ${review.approval_requirement === "one_run" ? "explicit one-run approval required" : "one-run or enabled preset"}`,
    ...resources,
  ].join("\n");
}

export async function prepareRemoteCommandApproval(
  reviewValue: unknown,
  projectKey: Uint8Array,
  approval: RemoteCommandApprovalChoice,
): Promise<Record<string, unknown>> {
  const review = validateRemoteCommandReview(reviewValue);
  assertProjectKey(projectKey);
  validateApproval(approval);
  if (review.approval_requirement === "one_run" && approval.kind !== "one_run") {
    throw new Error("this command requires explicit one-run approval");
  }
  const portableRequest: PortableRemoteCommandRequest = {
    protocol_version: 1,
    execution_id: review.execution_id,
    chat_id: review.chat_id,
    project_id: review.project_id,
    source_id: review.source_id,
    policy: review.command,
    approval,
  };
  const plaintext = canonicalPortableRemoteCommandRequest(portableRequest);
  const encryptedRequest = await encryptWithAesGcmCombined(plaintext, projectKey);
  const requestDigest = await remoteCommandPortableRequestDigest(projectKey, portableRequest);
  return {
    protocol_version: 1,
    execution_id: review.execution_id,
    chat_id: review.chat_id,
    project_id: review.project_id,
    source_id: review.source_id,
    review_token: review.review_token,
    encrypted_request: encryptedRequest,
    request_digest: requestDigest,
    approval,
  };
}

export async function decryptRemoteCommandEvent(
  value: unknown,
  projectKey: Uint8Array,
): Promise<DecryptedRemoteCommandEvent> {
  const event = record(value, "remote command event");
  const executionId = identifier(event.execution_id, "execution_id");
  const sequence = integer(event.sequence, "sequence");
  const eventKind = oneOf(event.event_kind, ["status", "output", "output_truncated", "terminal"] as const, "event_kind");
  const status = oneOf(event.status, ["authorizing", "running", "succeeded", "failed", "stopped", "timed_out"] as const, "status");
  if (typeof event.encrypted_event !== "string" || !event.encrypted_event) throw new Error("invalid encrypted remote command event");
  assertProjectKey(projectKey);
  const plaintext = await decryptWithAesGcmCombined(event.encrypted_event, projectKey);
  if (!plaintext) throw new Error("remote command event authentication failed");
  const payload = record(JSON.parse(plaintext), "decrypted remote command event");
  if (payload.execution_id !== executionId || payload.sequence !== sequence || payload.event_kind !== eventKind || payload.status !== status) {
    throw new Error("remote command event identity mismatch");
  }
  const terminalStatuses = new Set(["succeeded", "failed", "stopped", "timed_out"]);
  if ((eventKind === "terminal") !== terminalStatuses.has(status)) throw new Error("remote command terminal status mismatch");
  if (typeof payload.text === "string") payload.text = normalizeTerminalText(payload.text);
  if (typeof payload.error_message === "string") payload.error_message = normalizeTerminalText(payload.error_message);
  return { execution_id: executionId, sequence, event_kind: eventKind, status, payload };
}

export function registerRemoteCommandOriginClient(options: {
  client: OpenMatesClient;
  ws: OpenMatesWsClient;
  chatId: string;
  onReview?: (review: RemoteCommandReview) => RemoteCommandApprovalChoice | null | undefined | Promise<RemoteCommandApprovalChoice | null | undefined>;
  onEvent?: (event: DecryptedRemoteCommandEvent) => void | Promise<void>;
}) {
  let closed = false;
  const projectKeys = new Map<string, Uint8Array>();
  const executions = new Map<string, { review: RemoteCommandReview; output: RemoteCommandOutputAccumulator; completionSent: boolean }>();
  const keyFor = async (projectId: string): Promise<Uint8Array> => {
    const focus = await options.client.getActiveProjectFocus(options.chatId);
    if (focus?.project_id !== projectId) throw new Error("remote command Project focus is not active");
    const cached = projectKeys.get(projectId);
    if (cached) return cached;
    const context = { teamId: focus.team_id, personal: !focus.team_id };
    const detail = await options.client.getProject(projectId, context);
    const key = await options.client.decryptProjectKey(detail.project, context);
    projectKeys.set(projectId, key);
    return key;
  };
  const reviewOff = options.ws.onMessageType("remote_command_review_required", (payload) => {
    void (async () => {
      const frame = record(payload, "remote command review");
      const review = validateRemoteCommandReview(payload);
      if (closed || review.chat_id !== options.chatId) return;
      executions.set(review.execution_id, { review, output: new RemoteCommandOutputAccumulator(), completionSent: false });
      if (!options.onReview) return;
      const approval = await options.onReview(review);
      if (approval === undefined) {
        options.ws.notifyRemoteCommandReviewDeferred({
          chat_id: review.chat_id,
          execution_id: review.execution_id,
          ...(typeof frame.message_id === "string" ? { message_id: frame.message_id } : {}),
        });
        return;
      }
      if (approval === null) {
        await options.ws.sendAsync("remote_command_reject", rejectPayload(review));
        return;
      }
      await options.ws.sendAsync("remote_command_prepare", await prepareRemoteCommandApproval(review, await keyFor(review.project_id), approval));
    })().catch(() => {});
  });
  const eventOff = options.ws.onMessageType("remote_command_event", (payload) => {
    void (async () => {
      const item = record(payload, "remote command event");
      if (closed || item.chat_id !== options.chatId || typeof item.project_id !== "string") return;
      const executionId = typeof item.execution_id === "string" ? item.execution_id : "";
      const execution = executions.get(executionId);
      if (!execution || execution.review.project_id !== item.project_id || execution.review.source_id !== item.source_id) return;
      const event = await decryptRemoteCommandEvent(item, await keyFor(item.project_id));
      if (execution.output.add(event) === "duplicate") return;
      await options.onEvent?.(event);
      if (event.event_kind === "terminal" && !execution.completionSent) {
        execution.completionSent = true;
        const selection = execution.output.selection();
        const modelText = selection.sequence_gap
          ? `[Incomplete terminal output: one or more event sequences were unavailable.]\n${selection.text}`
          : selection.text;
        await options.ws.sendAsync("remote_command_origin_completion", {
          protocol_version: 1,
          execution_id: execution.review.execution_id,
          chat_id: execution.review.chat_id,
          project_id: execution.review.project_id,
          result_status: event.status,
          model_text: modelText,
          upstream_truncated: selection.upstream_truncated,
          ...(selection.upstream_truncated ? { omitted_chars: selection.omitted_chars } : {}),
        });
      }
    })().catch(() => {});
  });
  const stop = () => { closed = true; projectKeys.clear(); executions.clear(); reviewOff(); eventOff(); };
  options.ws.onClose(stop);
  return stop;
}

function rejectPayload(review: RemoteCommandReview): Record<string, unknown> {
  return {
    protocol_version: 1, execution_id: review.execution_id, chat_id: review.chat_id,
    project_id: review.project_id, review_token: review.review_token,
  };
}

export function validateRemoteCommandReview(value: unknown): RemoteCommandReview {
  const item = record(value, "remote command review");
  if (item.protocol_version !== 1 || item.state !== "REVIEW_REQUIRED") throw new Error("invalid remote command review protocol");
  const command = record(item.command, "remote command policy") as unknown as RemoteCommandPolicy;
  if (!Array.isArray(command.argv) || command.argv.length === 0 || command.argv.some((part) => typeof part !== "string" || !part || part.includes("\0"))) {
    throw new Error("invalid remote command argv");
  }
  if (typeof command.cwd !== "string" || command.cwd.startsWith("/") || command.cwd.split("/").includes("..")) throw new Error("invalid remote command cwd");
  oneOf(command.mode, ["foreground", "background"] as const, "mode");
  oneOf(command.source_access, ["read_only", "read_write"] as const, "source_access");
  if (!Number.isSafeInteger(command.deadline_ms) || command.deadline_ms < 100 || command.deadline_ms > 86_400_000) throw new Error("invalid remote command deadline");
  if (!Array.isArray(command.writable_profiles) || !Array.isArray(command.credential_profiles)) throw new Error("invalid remote command resource profiles");
  const explanation = record(item.explanation, "remote command explanation");
  return {
    protocol_version: 1,
    execution_id: identifier(item.execution_id, "execution_id"),
    chat_id: identifier(item.chat_id, "chat_id"),
    project_id: identifier(item.project_id, "project_id"),
    source_id: identifier(item.source_id, "source_id"),
    state: "REVIEW_REQUIRED",
    created_at: integer(item.created_at, "created_at"),
    review_expires_at: integer(item.review_expires_at, "review_expires_at"),
    review_token: typeof item.review_token === "string" && item.review_token.length >= 32 ? item.review_token : fail("invalid review token"),
    approval_requirement: oneOf(item.approval_requirement, ["one_run", "one_run_or_preset"] as const, "approval requirement"),
    command,
    explanation: {
      summary: text(explanation.summary, "explanation summary"),
      effects: textArray(explanation.effects, "explanation effects"),
      risks: textArray(explanation.risks, "explanation risks"),
      uncertainty: textArray(explanation.uncertainty, "explanation uncertainty"),
    },
  };
}

export function canonicalPortableRemoteCommandRequest(request: PortableRemoteCommandRequest): string {
  return JSON.stringify({
    protocol_version: 1,
    execution_id: request.execution_id,
    chat_id: request.chat_id,
    project_id: request.project_id,
    source_id: request.source_id,
    policy: {
      argv: request.policy.argv,
      cwd: request.policy.cwd,
      mode: request.policy.mode,
      source_access: request.policy.source_access,
      deadline_ms: request.policy.deadline_ms,
      writable_profiles: request.policy.writable_profiles,
      network_profile: request.policy.network_profile,
      credential_profiles: request.policy.credential_profiles,
    },
    approval: request.approval.kind === "one_run" ? { kind: "one_run" } : {
      kind: "preset", preset_id: request.approval.preset_id, definition_digest: request.approval.definition_digest,
    },
  });
}

export async function remoteCommandPortableRequestDigest(projectKey: Uint8Array, request: PortableRemoteCommandRequest): Promise<string> {
  assertProjectKey(projectKey);
  const identity = JSON.stringify(["openmates-remote-command-request-v1", canonicalPortableRemoteCommandRequest(request)]);
  const key = await cryptoApi.subtle.importKey("raw", new Uint8Array(projectKey).buffer, { name: "HMAC", hash: "SHA-256" }, false, ["sign"]);
  const digest = await cryptoApi.subtle.sign("HMAC", key, new TextEncoder().encode(identity));
  return Buffer.from(digest).toString("base64url");
}

function validateApproval(value: RemoteCommandApprovalChoice): void {
  if (value.kind === "one_run") return;
  if (!IDENTIFIER.test(value.preset_id) || !/^[a-f0-9]{64}$/i.test(value.definition_digest)) throw new Error("invalid remote command preset approval");
}

function writePresetGrants(grants: ActiveRemoteCommandPresetGrant[]): void {
  const directory = resolveStateDir();
  mkdirSync(directory, { recursive: true, mode: 0o700 });
  chmodSync(directory, 0o700);
  const path = join(directory, PRESET_GRANTS_FILE);
  if (existsSync(path) && lstatSync(path).isSymbolicLink()) throw new Error("Remote command preset grant store cannot be a symbolic link");
  const temporary = `${path}.${process.pid}.tmp`;
  writeFileSync(temporary, `${JSON.stringify({ version: 1, grants }, null, 2)}\n`, { mode: 0o600, flag: "wx" });
  renameSync(temporary, path);
  chmodSync(path, 0o600);
}

function safe(value: string): string {
  // Security boundary: these patterns deliberately match terminal control bytes and ANSI sequences.
  // eslint-disable-next-line no-control-regex
  return value.replace(/[\u0000-\u0008\u000b\u000c\u000e-\u001f\u007f\u202a-\u202e\u2066-\u2069]/g, (character) => `\\u${(character.codePointAt(0) ?? 0).toString(16).padStart(4, "0")}`);
}
function normalizeTerminalText(value: string): string {
  /* eslint-disable no-control-regex -- ANSI/OSC sanitization must explicitly match terminal control bytes. */
  return value
    .replace(/\u001b\][^\u0007\u001b]*(?:\u0007|\u001b\\)/g, "")
    .replace(/\u001b\[[0-?]*[ -/]*[@-~]/g, "")
    .replace(/[\u202a-\u202e\u2066-\u2069]/g, "")
    .replace(/[\u0000-\u0008\u000b\u000c\u000e-\u001f\u007f]/g, "");
  /* eslint-enable no-control-regex */
}
function terminalPayloadWasTruncated(event: DecryptedRemoteCommandEvent): boolean {
  if (event.event_kind !== "terminal") return false;
  const job = event.payload.job;
  const selection = event.payload.output_selection;
  return Boolean(
    job && typeof job === "object" && !Array.isArray(job) && (job as Record<string, unknown>).output_truncated === true
  ) || Boolean(
    selection && typeof selection === "object" && !Array.isArray(selection)
      && ((selection as Record<string, unknown>).upstream_truncated === true
        || (selection as Record<string, unknown>).source_excerpt_truncated === true
        || (selection as Record<string, unknown>).coverage === "selected_excerpt")
  );
}
function record(value: unknown, name: string): Record<string, unknown> { if (!value || typeof value !== "object" || Array.isArray(value)) throw new Error(`invalid ${name}`); return value as Record<string, unknown>; }
function identifier(value: unknown, name: string): string { if (typeof value !== "string" || !IDENTIFIER.test(value)) throw new Error(`invalid ${name}`); return value; }
function integer(value: unknown, name: string): number { if (!Number.isSafeInteger(value) || Number(value) < 0) throw new Error(`invalid ${name}`); return Number(value); }
function text(value: unknown, name: string): string { if (typeof value !== "string" || value.length > 16_384) throw new Error(`invalid ${name}`); return value; }
function textArray(value: unknown, name: string): string[] { if (!Array.isArray(value) || value.some((item) => typeof item !== "string" || item.length > 16_384)) throw new Error(`invalid ${name}`); return value as string[]; }
function oneOf<T extends string>(value: unknown, choices: readonly T[], name: string): T { if (typeof value !== "string" || !choices.includes(value as T)) throw new Error(`invalid ${name}`); return value as T; }
function assertProjectKey(value: Uint8Array): void { if (!(value instanceof Uint8Array) || value.byteLength !== 32) throw new Error("Project key must be 32 bytes"); }
function fail(message: string): never { throw new Error(message); }
