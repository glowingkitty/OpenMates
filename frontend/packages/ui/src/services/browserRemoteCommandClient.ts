/** Browser origin-side review and decryption for Project-confined commands. */
import { decryptWithEmbedKey, encryptWithEmbedKey } from "./cryptoService";
import {
  getActiveProjectFocus,
  getProject,
  listProjectSources,
} from "./projectService";
import {
  bindRemoteCommandStop,
  recordRemoteCommandEvent,
  requestRemoteCommandApproval,
  setRemoteCommandStatus,
} from "../stores/remoteCommandApprovalStore";

const IDENTIFIER = /^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$/;
const MAX_COMPLETION_CHARS = 24_000;
const OMISSION_MARKER = "\n\n[... terminal output omitted ...]\n\n";

export interface RemoteCommandPolicy {
  argv: string[];
  cwd: string;
  mode: "foreground" | "background";
  source_access: "read_only" | "read_write";
  deadline_ms: number;
  writable_profiles: string[];
  network_profile: string | null;
  credential_profiles: string[];
}

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

export type RemoteCommandReviewDisplay = Omit<RemoteCommandReview, "review_token">;

export interface DecryptedRemoteCommandEvent {
  execution_id: string;
  sequence: number;
  event_kind: "status" | "output" | "output_truncated" | "terminal";
  status:
    | "authorizing"
    | "running"
    | "succeeded"
    | "failed"
    | "stopped"
    | "timed_out";
  payload: Record<string, unknown>;
}

interface PortableRemoteCommandRequest {
  protocol_version: 1;
  execution_id: string;
  chat_id: string;
  project_id: string;
  source_id: string;
  policy: RemoteCommandPolicy;
  approval: { kind: "one_run" };
}

export interface BrowserRemoteCommandTransport {
  send(event: string, payload: Record<string, unknown>): Promise<void>;
}

export interface BrowserRemoteCommandClientOptions {
  transport: BrowserRemoteCommandTransport;
  isActiveChat(chatId: string): boolean;
  requestApproval?: (
    review: RemoteCommandReviewDisplay,
    labels: { projectName: string; sourceName: string },
  ) => Promise<boolean>;
}

interface OutputSelection {
  text: string;
  sequenceGap: boolean;
  upstreamTruncated: boolean;
  omittedChars: number;
}

class OutputAccumulator {
  private lastSequence = -1;
  private text = "";
  private inputChars = 0;
  private sequenceGap = false;
  private upstreamTruncated = false;

  add(event: DecryptedRemoteCommandEvent): boolean {
    if (event.sequence <= this.lastSequence) return false;
    if (event.sequence !== this.lastSequence + 1) this.sequenceGap = true;
    this.lastSequence = event.sequence;
    if (
      event.event_kind === "output_truncated" ||
      terminalPayloadWasTruncated(event)
    )
      this.upstreamTruncated = true;
    if (event.event_kind !== "output" || typeof event.payload.text !== "string")
      return true;
    const value = normalizeTerminalText(event.payload.text);
    this.inputChars += value.length;
    this.text += value;
    if (this.text.length > MAX_COMPLETION_CHARS * 2) {
      const half = Math.floor(
        (MAX_COMPLETION_CHARS - OMISSION_MARKER.length) / 2,
      );
      this.text = `${this.text.slice(0, half)}${OMISSION_MARKER}${this.text.slice(-half)}`;
    }
    return true;
  }

  selection(): OutputSelection {
    const half = Math.max(
      0,
      Math.floor((MAX_COMPLETION_CHARS - OMISSION_MARKER.length) / 2),
    );
    const text =
      this.text.length <= MAX_COMPLETION_CHARS
        ? this.text
        : `${this.text.slice(0, half)}${OMISSION_MARKER}${this.text.slice(-half)}`;
    const truncated =
      this.inputChars > MAX_COMPLETION_CHARS ||
      this.sequenceGap ||
      this.upstreamTruncated;
    return {
      text,
      sequenceGap: this.sequenceGap,
      upstreamTruncated: truncated,
      omittedChars: Math.max(
        0,
        this.inputChars -
          text.length +
          (text.includes(OMISSION_MARKER) ? OMISSION_MARKER.length : 0),
      ),
    };
  }
}

export function createBrowserRemoteCommandClient(
  options: BrowserRemoteCommandClientOptions,
) {
  let stopped = false;
  const projectContexts = new Map<
    string,
    { key: Uint8Array; projectName: string; sources: Map<string, string> }
  >();
  const executions = new Map<
    string,
    {
      review: RemoteCommandReview;
      output: OutputAccumulator;
      completionSent: boolean;
      removeStop: () => void;
    }
  >();

  const requireActiveFocus = async (review: RemoteCommandReview) => {
    if (stopped || !options.isActiveChat(review.chat_id)) fail("chat_inactive");
    const focus = await getActiveProjectFocus(review.chat_id);
    if (focus?.project_id !== review.project_id) fail("project_focus_required");
    return focus;
  };

  const contextFor = async (review: RemoteCommandReview) => {
    if (stopped) fail("client_stopped");
    const cached = projectContexts.get(review.project_id);
    if (cached) return cached;
    const focus = await requireActiveFocus(review);
    const project = await getProject(review.project_id, { teamId: focus.team_id });
    const sources = await listProjectSources(project, { teamId: focus.team_id });
    const context = {
      key: project.projectKey,
      projectName: project.name || review.project_id,
      sources: new Map(
        sources.map((source) => [
          source.source_id,
          source.displayName || source.source_id,
        ]),
      ),
    };
    projectContexts.set(review.project_id, context);
    return context;
  };

  const sendStop = async (review: RemoteCommandReview): Promise<void> => {
    if (stopped) return;
    await options.transport.send("remote_command_stop", {
      protocol_version: 1,
      execution_id: review.execution_id,
      chat_id: review.chat_id,
      project_id: review.project_id,
    });
  };

  const review = async (value: unknown): Promise<void> => {
    const parsed = validateRemoteCommandReview(value);
    if (stopped || !options.isActiveChat(parsed.chat_id)) return;
    const projectContext = await contextFor(parsed);
    const previous = executions.get(parsed.execution_id);
    previous?.removeStop();
    const execution = {
      review: parsed,
      output: new OutputAccumulator(),
      completionSent: false,
      removeStop: bindRemoteCommandStop(parsed.execution_id, () => sendStop(parsed)),
    };
    executions.set(parsed.execution_id, execution);
    const accepted = await (
      options.requestApproval ?? requestRemoteCommandApproval
    )(displayReview(parsed), {
      projectName: projectContext.projectName,
      sourceName:
        projectContext.sources.get(parsed.source_id) ?? parsed.source_id,
    });
    if (stopped || !options.isActiveChat(parsed.chat_id)) return;
    if (!accepted) {
      await options.transport.send("remote_command_reject", rejectPayload(parsed));
      return;
    }
    setRemoteCommandStatus(parsed.execution_id, "preparing");
    await requireActiveFocus(parsed);
    const projectKey = (await contextFor(parsed)).key;
    await options.transport.send(
      "remote_command_prepare",
      await prepareRemoteCommandApproval(parsed, projectKey),
    );
  };

  const event = async (value: unknown): Promise<void> => {
    const item = record(value, "remote command event");
    const executionId = identifier(item.execution_id, "execution_id");
    const execution = executions.get(executionId);
    if (!execution || stopped) return;
    if (
      item.chat_id !== execution.review.chat_id ||
      item.project_id !== execution.review.project_id ||
      item.source_id !== execution.review.source_id
    )
      fail("remote command event scope mismatch");
    const decrypted = await decryptRemoteCommandEvent(
      item,
      (await contextFor(execution.review)).key,
    );
    if (!execution.output.add(decrypted)) return;
    const selection = execution.output.selection();
    recordRemoteCommandEvent(
      execution.review.chat_id,
      decrypted,
      selection.text,
    );
    if (decrypted.event_kind !== "terminal" || execution.completionSent) return;
    execution.completionSent = true;
    const modelText = selection.sequenceGap
      ? `[Incomplete terminal output: one or more event sequences were unavailable.]\n${selection.text}`
      : selection.text;
    await options.transport.send("remote_command_origin_completion", {
      protocol_version: 1,
      execution_id: execution.review.execution_id,
      chat_id: execution.review.chat_id,
      project_id: execution.review.project_id,
      result_status: decrypted.status,
      model_text: modelText,
      upstream_truncated: selection.upstreamTruncated,
      ...(selection.upstreamTruncated
        ? { omitted_chars: selection.omittedChars }
        : {}),
    });
  };

  const response = (kind: string, value: unknown): void => {
    const item = record(value, "remote command response");
    const executionId = identifier(item.execution_id, "execution_id");
    if (!executions.has(executionId)) return;
    if (kind === "remote_command_error") {
      setRemoteCommandStatus(
        executionId,
        "error",
        typeof item.code === "string" ? item.code : "remote_command_failed",
      );
      return;
    }
    const statusByState: Record<string, Parameters<typeof setRemoteCommandStatus>[1]> = {
      WAITING_FOR_EXECUTOR: "waiting_for_executor",
      STOP_REQUESTED: "stop_requested",
      REJECTED: "rejected",
      TERMINAL:
        item.result_status === "stopped"
          ? "stopped"
          : item.result_status === "timed_out"
            ? "timed_out"
            : item.result_status === "failed"
              ? "failed"
              : "succeeded",
    };
    if (typeof item.state === "string" && statusByState[item.state])
      setRemoteCommandStatus(executionId, statusByState[item.state]);
  };

  const stop = (): void => {
    if (stopped) return;
    stopped = true;
    for (const execution of executions.values()) execution.removeStop();
    executions.clear();
    projectContexts.clear();
  };

  const owns = (value: unknown): boolean => {
    if (stopped || !value || typeof value !== "object" || Array.isArray(value))
      return false;
    const item = value as Record<string, unknown>;
    if (typeof item.execution_id !== "string" || typeof item.chat_id !== "string")
      return false;
    const execution = executions.get(item.execution_id);
    return Boolean(
      execution &&
        execution.review.chat_id === item.chat_id &&
        (!item.project_id || item.project_id === execution.review.project_id),
    );
  };

  return { review, event, response, owns, stop };
}

export async function prepareRemoteCommandApproval(
  reviewValue: unknown,
  projectKey: Uint8Array,
): Promise<Record<string, unknown>> {
  const review = validateRemoteCommandReview(reviewValue);
  assertProjectKey(projectKey);
  const portable: PortableRemoteCommandRequest = {
    protocol_version: 1,
    execution_id: review.execution_id,
    chat_id: review.chat_id,
    project_id: review.project_id,
    source_id: review.source_id,
    policy: review.command,
    approval: { kind: "one_run" },
  };
  const encryptedRequest = await encryptWithEmbedKey(
    canonicalPortableRemoteCommandRequest(portable),
    projectKey,
  );
  return {
    protocol_version: 1,
    execution_id: review.execution_id,
    chat_id: review.chat_id,
    project_id: review.project_id,
    source_id: review.source_id,
    review_token: review.review_token,
    encrypted_request: encryptedRequest,
    request_digest: await remoteCommandPortableRequestDigest(projectKey, portable),
    approval: { kind: "one_run" },
  };
}

export async function decryptRemoteCommandEvent(
  value: unknown,
  projectKey: Uint8Array,
): Promise<DecryptedRemoteCommandEvent> {
  const item = record(value, "remote command event");
  const executionId = identifier(item.execution_id, "execution_id");
  const sequence = integer(item.sequence, "sequence");
  const eventKind = oneOf(
    item.event_kind,
    ["status", "output", "output_truncated", "terminal"] as const,
    "event_kind",
  );
  const status = oneOf(
    item.status,
    ["authorizing", "running", "succeeded", "failed", "stopped", "timed_out"] as const,
    "status",
  );
  if (typeof item.encrypted_event !== "string" || !item.encrypted_event)
    fail("invalid encrypted remote command event");
  assertProjectKey(projectKey);
  const plaintext = await decryptWithEmbedKey(item.encrypted_event, projectKey);
  if (!plaintext) fail("remote command event authentication failed");
  const payload = record(JSON.parse(plaintext), "decrypted remote command event");
  if (
    payload.execution_id !== executionId ||
    payload.sequence !== sequence ||
    payload.event_kind !== eventKind ||
    payload.status !== status
  )
    fail("remote command event identity mismatch");
  const terminal = new Set(["succeeded", "failed", "stopped", "timed_out"]);
  if ((eventKind === "terminal") !== terminal.has(status))
    fail("remote command terminal status mismatch");
  if (typeof payload.text === "string")
    payload.text = normalizeTerminalText(payload.text);
  if (typeof payload.error_message === "string")
    payload.error_message = normalizeTerminalText(payload.error_message);
  return { execution_id: executionId, sequence, event_kind: eventKind, status, payload };
}

export function validateRemoteCommandReview(value: unknown): RemoteCommandReview {
  const item = record(value, "remote command review");
  if (item.protocol_version !== 1 || item.state !== "REVIEW_REQUIRED")
    fail("invalid remote command review protocol");
  const commandValue = record(item.command, "remote command policy");
  const argv = textArray(commandValue.argv, "argv", 128);
  if (argv.length === 0 || argv.some((part) => !part || part.includes("\0")))
    fail("invalid remote command argv");
  const cwd = text(commandValue.cwd, "cwd", 1024);
  if (!cwd || cwd.startsWith("/") || cwd.replace(/\\/g, "/").split("/").includes(".."))
    fail("invalid remote command cwd");
  const writableProfiles = textArray(
    commandValue.writable_profiles,
    "writable_profiles",
    32,
  );
  const credentialProfiles = textArray(
    commandValue.credential_profiles,
    "credential_profiles",
    32,
  );
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
    review_token:
      typeof item.review_token === "string" && item.review_token.length >= 32
        ? item.review_token
        : fail("invalid review token"),
    approval_requirement: oneOf(
      item.approval_requirement,
      ["one_run", "one_run_or_preset"] as const,
      "approval_requirement",
    ),
    command: {
      argv,
      cwd,
      mode: oneOf(commandValue.mode, ["foreground", "background"] as const, "mode"),
      source_access: oneOf(
        commandValue.source_access,
        ["read_only", "read_write"] as const,
        "source_access",
      ),
      deadline_ms: boundedInteger(commandValue.deadline_ms, 100, 86_400_000),
      writable_profiles: writableProfiles,
      network_profile:
        commandValue.network_profile === null
          ? null
          : text(commandValue.network_profile, "network_profile", 128),
      credential_profiles: credentialProfiles,
    },
    explanation: {
      summary: text(explanation.summary, "summary", 16_384),
      effects: textArray(explanation.effects, "effects", 128, 16_384),
      risks: textArray(explanation.risks, "risks", 128, 16_384),
      uncertainty: textArray(explanation.uncertainty, "uncertainty", 128, 16_384),
    },
  };
}

export function canonicalPortableRemoteCommandRequest(
  request: PortableRemoteCommandRequest,
): string {
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
    approval: { kind: "one_run" },
  });
}

async function remoteCommandPortableRequestDigest(
  projectKey: Uint8Array,
  request: PortableRemoteCommandRequest,
): Promise<string> {
  assertProjectKey(projectKey);
  const identity = JSON.stringify([
    "openmates-remote-command-request-v1",
    canonicalPortableRemoteCommandRequest(request),
  ]);
  const key = await crypto.subtle.importKey(
    "raw",
    new Uint8Array(projectKey),
    { name: "HMAC", hash: "SHA-256" },
    false,
    ["sign"],
  );
  const digest = new Uint8Array(
    await crypto.subtle.sign("HMAC", key, new TextEncoder().encode(identity)),
  );
  let binary = "";
  for (const byte of digest) binary += String.fromCharCode(byte);
  return btoa(binary).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
}

function displayReview(review: RemoteCommandReview): RemoteCommandReviewDisplay {
  const { review_token: _reviewToken, ...display } = review;
  return structuredClone(display);
}

function rejectPayload(review: RemoteCommandReview): Record<string, unknown> {
  return {
    protocol_version: 1,
    execution_id: review.execution_id,
    chat_id: review.chat_id,
    project_id: review.project_id,
    review_token: review.review_token,
  };
}

function terminalPayloadWasTruncated(event: DecryptedRemoteCommandEvent): boolean {
  if (event.event_kind !== "terminal") return false;
  const job = event.payload.job;
  const selection = event.payload.output_selection;
  return Boolean(
    job &&
      typeof job === "object" &&
      !Array.isArray(job) &&
      (job as Record<string, unknown>).output_truncated === true,
  ) || Boolean(
    selection &&
      typeof selection === "object" &&
      !Array.isArray(selection) &&
      ((selection as Record<string, unknown>).upstream_truncated === true ||
        (selection as Record<string, unknown>).source_excerpt_truncated === true ||
        (selection as Record<string, unknown>).coverage === "selected_excerpt"),
  );
}

function normalizeTerminalText(value: string): string {
  /* eslint-disable no-control-regex -- terminal escape/control removal is deliberate. */
  return value
    .replace(/\u001b\][^\u0007\u001b]*(?:\u0007|\u001b\\)/g, "")
    .replace(/\u001b\[[0-?]*[ -/]*[@-~]/g, "")
    .replace(/[\u202a-\u202e\u2066-\u2069]/g, "")
    .replace(/[\u0000-\u0008\u000b\u000c\u000e-\u001f\u007f]/g, "");
  /* eslint-enable no-control-regex */
}

function record(value: unknown, name: string): Record<string, unknown> {
  if (!value || typeof value !== "object" || Array.isArray(value))
    fail(`invalid ${name}`);
  return value as Record<string, unknown>;
}

function identifier(value: unknown, name: string): string {
  if (typeof value !== "string" || !IDENTIFIER.test(value)) fail(`invalid ${name}`);
  return value;
}

function integer(value: unknown, name: string): number {
  if (!Number.isSafeInteger(value) || Number(value) < 0) fail(`invalid ${name}`);
  return Number(value);
}

function boundedInteger(value: unknown, minimum: number, maximum: number): number {
  const parsed = integer(value, "integer");
  if (parsed < minimum || parsed > maximum) fail("invalid bounded integer");
  return parsed;
}

function text(value: unknown, name: string, maximum: number): string {
  if (typeof value !== "string" || value.length > maximum) fail(`invalid ${name}`);
  return value;
}

function textArray(
  value: unknown,
  name: string,
  maximumItems: number,
  maximumLength = 128,
): string[] {
  if (
    !Array.isArray(value) ||
    value.length > maximumItems ||
    value.some((item) => typeof item !== "string" || item.length > maximumLength)
  )
    fail(`invalid ${name}`);
  return value as string[];
}

function oneOf<T extends string>(
  value: unknown,
  choices: readonly T[],
  name: string,
): T {
  if (typeof value !== "string" || !choices.includes(value as T))
    fail(`invalid ${name}`);
  return value as T;
}

function assertProjectKey(value: Uint8Array): void {
  if (!(value instanceof Uint8Array) || value.byteLength !== 32)
    fail("Project key must be 32 bytes");
}

function fail(message: string): never {
  throw new Error(message);
}
