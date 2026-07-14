/*
 * OpenMates CLI WebSocket transport.
 *
 * Purpose: send/receive chat sync events over the same protocol as web clients.
 * Architecture: thin wrapper around ws with typed envelope helpers.
 * Architecture doc: docs/architecture/openmates-cli.md
 * Security: auth token is passed via query params as supported by backend auth_ws.
 * Tests: exercised indirectly via CLI chat command tests and manual runs.
 */

import { createRequire } from "node:module";
import type { IncomingMessage } from "node:http";

const require = createRequire(import.meta.url);
const WebSocket = require("ws");

type RawData = Buffer | ArrayBuffer | Buffer[];

export interface WsEnvelope<T = unknown> {
  type: string;
  payload: T;
}

/** Streaming event dispatched for each chunk or lifecycle event. */
export interface StreamEvent {
  /** Event type. */
  kind: "typing" | "chunk" | "done";
  /** Cumulative content so far (only on chunk/done). */
  content: string;
  /** AI category (e.g. "general_knowledge"). */
  category: string | null;
  /** Human-readable model name. */
  modelName: string | null;
}

export interface SendEmbedDataFrame {
  embed_id: string;
  type?: string;
  content?: string;
  status?: string;
  text_preview?: string;
  chat_id?: string;
  message_id?: string;
  user_id?: string;
  embed_ids?: string[];
  parent_embed_id?: string | null;
  task_id?: string;
  version_number?: number;
  file_path?: string;
  content_hash?: string;
  text_length_chars?: number;
  is_private?: boolean;
  is_shared?: boolean;
  createdAt?: number;
  updatedAt?: number;
  version_history_rows?: Array<{
    embed_id: string;
    version_number: number;
    snapshot?: string;
    patch?: string;
    created_at?: number;
  }>;
}

export type SubChatEventType =
  | "spawn_sub_chats"
  | "sub_chat_progress"
  | "sub_chat_confirmation_required"
  | "sub_chat_confirmation_resolved"
  | "awaiting_sub_chats_completion"
  | "sub_chat_completed"
  | "awaiting_user_input";

export interface SubChatEvent {
  type: SubChatEventType;
  payload: Record<string, unknown>;
}

export interface AppSettingsMemoriesRequestEvent {
  requestId: string | null;
  chatId: string;
  requestedKeys: string[];
  payload: Record<string, unknown>;
}

export interface TaskProposalEvent {
  title: string;
  description?: string | null;
  status?: "backlog" | "todo" | "in_progress" | "blocked" | "done";
  assignee_type?: "ai" | "user";
}

export interface TaskUpdateProposalEvent {
  task_id: string;
  title?: string | null;
  description?: string | null;
  status?: "backlog" | "todo" | "in_progress" | "blocked" | "done" | null;
  assignee_type?: "ai" | "user" | null;
}

export interface TaskEventFrame {
  event_id: string;
  chat_id: string;
  task_id: string;
  short_id?: string | null;
  event_type: string;
  title?: string | null;
  status?: string | null;
  reason?: string | null;
  created_at?: number | null;
  task_update_job_id?: string | null;
}

export interface PendingTaskUpdateJobFrame {
  job_id: string;
  task_id: string;
  chat_id?: string | null;
  revision: number;
  task_key_version: number;
  expires_at: number;
}

interface AvailableRecoveryJobFrame {
  job_id: string;
  chat_id: string;
  turn_id: string;
  assistant_message_id: string;
  chat_key_version: number;
}

const SUB_CHAT_EVENT_TYPES = new Set<string>([
  "spawn_sub_chats",
  "sub_chat_progress",
  "sub_chat_confirmation_required",
  "sub_chat_confirmation_resolved",
  "awaiting_sub_chats_completion",
  "sub_chat_completed",
  "awaiting_user_input",
]);

const SUB_CHAT_PARENT_STATUS_MESSAGE =
  "I've started the sub-chats and will continue once they finish.";
const SUB_CHAT_COMPLETION_TIMEOUT_MS = 10 * 60_000;
const CLIENT_UPDATE_REQUIRED_GUIDANCE =
  "OpenMates CLI update required. Run `openmates upgrade` and retry.";
const TASK_STATUSES = new Set(["backlog", "todo", "in_progress", "blocked", "done"]);
const TASK_ASSIGNEES = new Set(["ai", "user"]);

export class WebSocketProtocolError extends Error {
  readonly code: string;

  constructor(code: string, message: string) {
    super(message);
    this.name = "WebSocketProtocolError";
    this.code = code;
  }
}

function websocketProtocolError(envelope: WsEnvelope): Error | null {
  const payload = envelope.payload && typeof envelope.payload === "object"
    ? envelope.payload as Record<string, unknown>
    : {};
  const code = envelope.type === "client_update_required"
    ? envelope.type
    : envelope.type === "error" && typeof payload.code === "string"
      ? payload.code
      : null;
  if (code === "client_update_required") {
    return new WebSocketProtocolError(code, CLIENT_UPDATE_REQUIRED_GUIDANCE);
  }
  if (envelope.type === "error") {
    return new WebSocketProtocolError(
      code ?? "websocket_error",
      typeof payload.message === "string" ? payload.message : "Unknown WebSocket error",
    );
  }
  return null;
}

function errorFrameBelongsToAiResponse(
  envelope: WsEnvelope<Record<string, unknown>>,
  userMessageId: string,
  chatId: string,
  recoveryTurnId?: string | null,
): boolean {
  if (envelope.type === "client_update_required") return true;
  if (envelope.type !== "error") return true;
  const payload = envelope.payload && typeof envelope.payload === "object"
    ? envelope.payload as Record<string, unknown>
    : {};
  let scoped = false;
  const errorChatId = typeof payload.chat_id === "string" ? payload.chat_id : null;
  if (errorChatId) {
    scoped = true;
    if (errorChatId !== chatId) return false;
  }
  const errorMessageId = typeof payload.user_message_id === "string"
    ? payload.user_message_id
    : typeof payload.userMessageId === "string"
      ? payload.userMessageId
      : typeof payload.message_id === "string"
        ? payload.message_id
        : null;
  if (errorMessageId) {
    scoped = true;
    if (errorMessageId !== userMessageId) return false;
  }
  const errorTurnId = typeof payload.turn_id === "string" ? payload.turn_id : null;
  if (errorTurnId) {
    scoped = true;
    if (recoveryTurnId !== errorTurnId) return false;
  }
  if (typeof payload.job_id === "string") {
    scoped = true;
  }
  return !scoped || Boolean(errorChatId || errorMessageId || errorTurnId);
}

function parseTaskProposals(value: unknown): TaskProposalEvent[] {
  if (!Array.isArray(value)) return [];
  return value.flatMap((item): TaskProposalEvent[] => {
    if (!item || typeof item !== "object" || Array.isArray(item)) return [];
    const raw = item as Record<string, unknown>;
    if (typeof raw.title !== "string" || raw.title.trim().length === 0) return [];
    const proposal: TaskProposalEvent = { title: raw.title };
    if (typeof raw.description === "string" || raw.description === null) proposal.description = raw.description;
    if (typeof raw.status === "string" && TASK_STATUSES.has(raw.status)) proposal.status = raw.status as TaskProposalEvent["status"];
    if (typeof raw.assignee_type === "string" && TASK_ASSIGNEES.has(raw.assignee_type)) proposal.assignee_type = raw.assignee_type as TaskProposalEvent["assignee_type"];
    return [proposal];
  });
}

function parseTaskUpdateProposals(value: unknown): TaskUpdateProposalEvent[] {
  if (!Array.isArray(value)) return [];
  return value.flatMap((item): TaskUpdateProposalEvent[] => {
    if (!item || typeof item !== "object" || Array.isArray(item)) return [];
    const raw = item as Record<string, unknown>;
    if (typeof raw.task_id !== "string" || raw.task_id.trim().length === 0) return [];
    const proposal: TaskUpdateProposalEvent = { task_id: raw.task_id };
    if (typeof raw.title === "string" || raw.title === null) proposal.title = raw.title;
    if (typeof raw.description === "string" || raw.description === null) proposal.description = raw.description;
    if ((typeof raw.status === "string" && TASK_STATUSES.has(raw.status)) || raw.status === null) proposal.status = raw.status as TaskUpdateProposalEvent["status"];
    if ((typeof raw.assignee_type === "string" && TASK_ASSIGNEES.has(raw.assignee_type)) || raw.assignee_type === null) proposal.assignee_type = raw.assignee_type as TaskUpdateProposalEvent["assignee_type"];
    return [proposal];
  });
}

function parseTaskEvent(value: unknown): TaskEventFrame | null {
  if (!value || typeof value !== "object" || Array.isArray(value)) return null;
  const raw = value as Record<string, unknown>;
  if (typeof raw.event_id !== "string" || typeof raw.chat_id !== "string") return null;
  if (typeof raw.task_id !== "string" || typeof raw.event_type !== "string") return null;
  const event: TaskEventFrame = {
    event_id: raw.event_id,
    chat_id: raw.chat_id,
    task_id: raw.task_id,
    event_type: raw.event_type,
  };
  if (typeof raw.short_id === "string" || raw.short_id === null) event.short_id = raw.short_id;
  if (typeof raw.title === "string" || raw.title === null) event.title = raw.title;
  if (typeof raw.status === "string" || raw.status === null) event.status = raw.status;
  if (typeof raw.reason === "string" || raw.reason === null) event.reason = raw.reason;
  if (typeof raw.created_at === "number" || raw.created_at === null) event.created_at = raw.created_at;
  if (typeof raw.task_update_job_id === "string" || raw.task_update_job_id === null) event.task_update_job_id = raw.task_update_job_id;
  return event;
}

function parsePendingTaskUpdateJobs(value: unknown): PendingTaskUpdateJobFrame[] {
  if (!Array.isArray(value)) return [];
  return value.flatMap((item): PendingTaskUpdateJobFrame[] => {
    if (!item || typeof item !== "object" || Array.isArray(item)) return [];
    const raw = item as Record<string, unknown>;
    if (typeof raw.job_id !== "string" || typeof raw.task_id !== "string") return [];
    if (typeof raw.revision !== "number" || typeof raw.task_key_version !== "number" || typeof raw.expires_at !== "number") return [];
    const job: PendingTaskUpdateJobFrame = {
      job_id: raw.job_id,
      task_id: raw.task_id,
      revision: raw.revision,
      task_key_version: raw.task_key_version,
      expires_at: raw.expires_at,
    };
    if (typeof raw.chat_id === "string" || raw.chat_id === null) job.chat_id = raw.chat_id;
    return [job];
  });
}

function parseAvailableRecoveryJobs(value: unknown): AvailableRecoveryJobFrame[] {
  if (!Array.isArray(value)) return [];
  return value.flatMap((item): AvailableRecoveryJobFrame[] => {
    if (!item || typeof item !== "object" || Array.isArray(item)) return [];
    const raw = item as Record<string, unknown>;
    if (
      typeof raw.job_id !== "string" ||
      typeof raw.chat_id !== "string" ||
      typeof raw.turn_id !== "string" ||
      typeof raw.assistant_message_id !== "string" ||
      typeof raw.chat_key_version !== "number"
    ) return [];
    return [{
      job_id: raw.job_id,
      chat_id: raw.chat_id,
      turn_id: raw.turn_id,
      assistant_message_id: raw.assistant_message_id,
      chat_key_version: raw.chat_key_version,
    }];
  });
}

export class OpenMatesWsClient {
  private readonly socket: InstanceType<typeof WebSocket>;
  private readonly passiveTaskUpdateJobs = new Map<string, PendingTaskUpdateJobFrame>();
  private activeResponseCollectors = 0;

  constructor(options: {
    apiUrl: string;
    sessionId: string;
    wsToken: string | null;
    refreshToken: string | null;
    userAgent?: string;
    cookies?: Record<string, string>;
  }) {
    const wsBase = options.apiUrl.replace(/^http/, "ws").replace(/\/$/, "");
    // Use || (not ??) so empty-string wsToken falls through to refreshToken.
    // create_ws_token() returns "" when INTERNAL_API_SHARED_TOKEN is unset.
    const token = options.wsToken || options.refreshToken || "";
    const query = new URLSearchParams({
      sessionId: options.sessionId,
      token,
      client_capabilities: "task_update_jobs",
    });
    // Pass the same User-Agent as the HTTP login call so the device fingerprint
    // hash (SHA256(OS:Country:UserID)) matches the one registered at login time.
    // Also forward cookies — Node.js ws library doesn't auto-send HTTP cookies,
    // so the backend's cookie-based auth path needs them explicitly.
    const wsHeaders: Record<string, string> = {};
    if (options.userAgent) {
      wsHeaders["User-Agent"] = options.userAgent;
    }
    if (options.cookies) {
      const cookieStr = Object.entries(options.cookies)
        .map(([k, v]) => `${k}=${v}`)
        .join("; ");
      if (cookieStr) {
        wsHeaders.Cookie = cookieStr;
      }
    }
    this.socket = new WebSocket(`${wsBase}/v1/ws?${query.toString()}`, {
      headers: wsHeaders,
    });
    this.socket.on("message", (rawData: RawData) => {
      if (this.activeResponseCollectors > 0) return;
      this.bufferPassiveTaskUpdateJobs(rawData);
    });
  }

  async open(timeoutMs = 10_000): Promise<void> {
    await new Promise<void>((resolve, reject) => {
      const timeout = setTimeout(
        () => reject(new Error("WebSocket open timeout")),
        timeoutMs,
      );
      this.socket.once("open", () => {
        clearTimeout(timeout);
        resolve();
      });
      this.socket.once("error", (error: Error) => {
        clearTimeout(timeout);
        reject(error);
      });
      // ws library emits 'unexpected-response' when the server returns a non-101
      // status. When this listener exists, ws does NOT emit the generic 'error'
      // event for the upgrade failure, so there is no double-reject risk.
      this.socket.once("unexpected-response", (_req: unknown, res: IncomingMessage) => {
        clearTimeout(timeout);
        if (res.statusCode === 401 || res.statusCode === 403) {
          reject(
            new Error(
              "Session expired or invalid. Please run `openmates login` to re-authenticate.",
            ),
          );
        } else {
          reject(
            new Error(`Unexpected server response: ${res.statusCode}`),
          );
        }
      });
    });
  }

  close(): void {
    this.socket.close();
  }

  send(type: string, payload: unknown): void {
    this.socket.send(JSON.stringify({ type, payload }));
  }

  sendAsync(type: string, payload: unknown): Promise<void> {
    return new Promise((resolve, reject) => {
      this.socket.send(JSON.stringify({ type, payload }), (error?: Error) => {
        if (error) reject(error);
        else resolve();
      });
    });
  }

  private bufferPassiveTaskUpdateJobs(rawData: RawData): void {
    try {
      const parsed = JSON.parse(rawData.toString()) as WsEnvelope<Record<string, unknown>>;
      if (parsed.type !== "task_update_jobs_available") return;
      const payload = (parsed.payload ?? {}) as Record<string, unknown>;
      for (const job of parsePendingTaskUpdateJobs(payload.jobs)) {
        this.passiveTaskUpdateJobs.set(job.job_id, job);
      }
    } catch {
      // Ignore non-JSON frames.
    }
  }

  private drainPassiveTaskUpdateJobs(): PendingTaskUpdateJobFrame[] {
    const jobs = [...this.passiveTaskUpdateJobs.values()];
    this.passiveTaskUpdateJobs.clear();
    return jobs;
  }

  waitForMessage(
    expectedType: string,
    predicate?: (payload: unknown) => boolean,
    timeoutMs = 20_000,
  ): Promise<WsEnvelope> {
    return new Promise<WsEnvelope>((resolve, reject) => {
      const seenTypes = new Set<string>();
      let predicateMisses = 0;
      const onMessage = (rawData: RawData) => {
        try {
          const parsed = JSON.parse(rawData.toString()) as WsEnvelope;
          if (typeof parsed.type === "string") seenTypes.add(parsed.type);
          const protocolError = websocketProtocolError(parsed);
          if (protocolError) {
            cleanup();
            reject(protocolError);
            return;
          }
          if (parsed.type !== expectedType) {
            return;
          }
          if (predicate && !predicate(parsed.payload)) {
            predicateMisses += 1;
            return;
          }
          cleanup();
          resolve(parsed);
        } catch {
          // Ignore non-JSON frames.
        }
      };

      const onError = (error: Error) => {
        cleanup();
        reject(error);
      };

      const onClose = () => {
        cleanup();
        reject(new Error("WebSocket closed while waiting for message"));
      };

      const timeout = setTimeout(() => {
        cleanup();
        const observed = [...seenTypes].sort().join(", ") || "none";
        reject(
          new Error(
            `Timeout waiting for '${expectedType}' ` +
              `(seen types: ${observed}; predicate misses: ${predicateMisses})`,
          ),
        );
      }, timeoutMs);

      const cleanup = () => {
        clearTimeout(timeout);
        this.socket.off("message", onMessage);
        this.socket.off("error", onError);
        this.socket.off("close", onClose);
      };

      this.socket.on("message", onMessage);
      this.socket.on("error", onError);
      this.socket.on("close", onClose);
    });
  }

  /**
   * Collect all frames until `terminatorType` arrives (or timeout).
   * Returns every frame received before the terminator, in order.
   * Used by ensureSynced to consume the full phased-sync event stream.
   */
  collectMessages(terminatorType: string, timeoutMs = 90_000): Promise<WsEnvelope[]> {
    return new Promise<WsEnvelope[]>((resolve, reject) => {
      const collected: WsEnvelope[] = [];

      const onMessage = (rawData: RawData) => {
        try {
          const parsed = JSON.parse(rawData.toString()) as WsEnvelope;
          const protocolError = websocketProtocolError(parsed);
          if (protocolError) {
            cleanup();
            reject(protocolError);
            return;
          }
          if (parsed.type === terminatorType) {
            cleanup();
            resolve(collected);
            return;
          }
          collected.push(parsed);
        } catch {
          // ignore non-JSON frames
        }
      };

      const onError = (error: Error) => { cleanup(); reject(error); };
      const onClose = () => { cleanup(); resolve(collected); };
      const timeout = setTimeout(() => {
        cleanup();
        reject(new Error(`Timeout waiting for '${terminatorType}'`));
      }, timeoutMs);

      const cleanup = () => {
        clearTimeout(timeout);
        this.socket.off("message", onMessage);
        this.socket.off("error", onError);
        this.socket.off("close", onClose);
      };

      this.socket.on("message", onMessage);
      this.socket.on("error", onError);
      this.socket.on("close", onClose);
    });
  }

  /**
   * Collect the AI response for a sent message.
   *
   * The server has two delivery paths:
   *
   * 1. Active-chat path (chat is set as active on this device via set_active_chat):
   *    Sends incremental `ai_message_update` frames with `full_content_so_far`.
   *    The final frame has `is_final_chunk: true`.
   *
   * 2. Background path (chat is not marked active — the CLI default unless we
   *    explicitly call set_active_chat first):
   *    Sends a single `ai_background_response_completed` frame with `full_content`
   *    and the user_message_id. No incremental chunks.
   *
   * We listen for both simultaneously and resolve on whichever arrives first.
   */
  /** Result from collectAiResponse including metadata from the stream. */
  collectAiResponse(
    userMessageId: string,
    chatId: string,
    options?: {
      timeoutMs?: number;
      asyncEmbedWaitMs?: number;
      onStream?: (event: StreamEvent) => void;
      onSubChatEvent?: (event: SubChatEvent) => void | Promise<void>;
      onAppSettingsMemoriesRequest?: (
        event: AppSettingsMemoriesRequestEvent,
      ) => void | Promise<void>;
      recoveryTurnId?: string | null;
    },
  ): Promise<{
    status: "completed" | "waiting_for_user";
    messageId: string | null;
    taskId: string | null;
    content: string;
    category: string | null;
    modelName: string | null;
    followUpSuggestions: string[];
    newChatSuggestions: string[];
    taskProposals: TaskProposalEvent[];
    taskUpdateProposals: TaskUpdateProposalEvent[];
    taskEvents: TaskEventFrame[];
    pendingTaskUpdateJobs: PendingTaskUpdateJobFrame[];
    embeds: SendEmbedDataFrame[];
    subChatEvents: SubChatEvent[];
    recoveryJobId: string | null;
  }> {
    const timeoutMs = options?.timeoutMs ?? 90_000;
    const onStream = options?.onStream;
    const asyncEmbedWaitMs = options?.asyncEmbedWaitMs ?? 120_000;

    return new Promise((resolve, reject) => {
      let latestContent = "";
      let messageId: string | null = null;
      let taskId: string | null = null;
      let category: string | null = null;
      let modelName: string | null = null;
      let recoveryJobId: string | null = null;
      let followUpSuggestions: string[] = [];
      let newChatSuggestions: string[] = [];
      let taskProposals: TaskProposalEvent[] = [];
      let taskUpdateProposals: TaskUpdateProposalEvent[] = [];
      const taskEvents: TaskEventFrame[] = [];
      this.activeResponseCollectors += 1;
      let pendingTaskUpdateJobs: PendingTaskUpdateJobFrame[] = this.drainPassiveTaskUpdateJobs();
      const mergePendingTaskUpdateJobs = (jobs: PendingTaskUpdateJobFrame[]) => {
        const byId = new Map(pendingTaskUpdateJobs.map((job) => [job.job_id, job]));
        for (const job of jobs) byId.set(job.job_id, job);
        pendingTaskUpdateJobs = [...byId.values()];
      };
      const subChatEvents: SubChatEvent[] = [];
      const pendingSubChatHandlers = new Set<Promise<void>>();
      const pendingMemoryRequestHandlers = new Set<Promise<void>>();
      const embeds = new Map<string, SendEmbedDataFrame>();
      const processingEmbedIds = new Set<string>();
      let waitingForUserPayload: Record<string, unknown> | null = null;
      // Track whether the AI response is done so we can wait for post-processing.
      let aiResponseDone = false;
      let postProcessingDone = false;
      // Post-processing metadata arrives up to ~10 s after the AI response.
      // We wait a short window for it so follow-up suggestions are available.
      const POST_PROCESSING_WINDOW_MS = 12_000;
      let postProcessingTimer: ReturnType<typeof setTimeout> | null = null;
      let asyncEmbedTimer: ReturnType<typeof setTimeout> | null = null;

      const startTimeout = (ms: number) =>
        setTimeout(() => {
          cleanup();
          reject(new Error("Timed out waiting for AI response"));
        }, ms);
      let timeout = startTimeout(timeoutMs);
      let awaitingSubChatsCompletion = false;

      const resetTimeout = (ms: number) => {
        clearTimeout(timeout);
        timeout = startTimeout(ms);
      };

      const capture = (p: Record<string, unknown>) => {
        if (typeof p.message_id === "string" && p.message_id)
          messageId = p.message_id;
        if (typeof p.task_id === "string" && p.task_id) taskId = p.task_id;
        if (typeof p.category === "string" && p.category) category = p.category;
        if (typeof p.model_name === "string" && p.model_name)
          modelName = p.model_name;
        if (
          typeof p.recovery_job_id === "string"
          && p.recovery_job_id
          && p.recovery_protocol_version === 1
        )
          recoveryJobId = p.recovery_job_id;
      };

      const extractMessageContent = (message: Record<string, unknown>): string => {
        if (typeof message.content === "string") return message.content;
        const content = message.content;
        if (!content || typeof content !== "object") return "";
        try {
          const root = content as {
            content?: Array<{ content?: Array<{ text?: unknown }> }>;
          };
          const text = root.content?.[0]?.content?.[0]?.text;
          return typeof text === "string" ? text : "";
        } catch {
          return "";
        }
      };

      const finishPostProcessingWait = () => {
        postProcessingDone = true;
        maybeResolve();
      };

      const maybeResolve = () => {
        if (waitingForUserPayload) {
          if (pendingSubChatHandlers.size > 0) return;
          cleanup();
          resolve({
            status: "waiting_for_user",
            messageId,
            taskId,
            content: latestContent,
            category,
            modelName,
            followUpSuggestions,
            newChatSuggestions,
            taskProposals,
            taskUpdateProposals,
            taskEvents,
            pendingTaskUpdateJobs,
            embeds: [...embeds.values()],
            subChatEvents,
            recoveryJobId,
          });
          return;
        }
        if (!aiResponseDone || !postProcessingDone) return;
        if (options?.recoveryTurnId && !recoveryJobId) return;
        if (pendingSubChatHandlers.size > 0) return;
        if (pendingMemoryRequestHandlers.size > 0) return;
        if (processingEmbedIds.size > 0 && !asyncEmbedTimer) {
          asyncEmbedTimer = setTimeout(() => {
            cleanup();
            resolve({
              status: "completed",
              messageId,
              taskId,
              content: latestContent,
              category,
              modelName,
              followUpSuggestions,
              newChatSuggestions,
              taskProposals,
              taskUpdateProposals,
              taskEvents,
              pendingTaskUpdateJobs,
              embeds: [...embeds.values()],
              subChatEvents,
              recoveryJobId,
            });
          }, asyncEmbedWaitMs);
          return;
        }
        if (processingEmbedIds.size > 0) return;
        cleanup();
        resolve({
          status: "completed",
          messageId,
          taskId,
          content: latestContent,
          category,
          modelName,
          followUpSuggestions,
          newChatSuggestions,
          taskProposals,
          taskUpdateProposals,
          taskEvents,
          pendingTaskUpdateJobs,
          embeds: [...embeds.values()],
          subChatEvents,
          recoveryJobId,
        });
      };

      const handleSubChatEvent = (type: string, p: Record<string, unknown>) => {
        const eventPayload =
          p.payload && typeof p.payload === "object" && !Array.isArray(p.payload)
            ? (p.payload as Record<string, unknown>)
            : p;
        const eventChatId =
          type === "awaiting_user_input" && typeof eventPayload.parent_id === "string"
            ? eventPayload.parent_id
            : typeof eventPayload.chat_id === "string"
              ? eventPayload.chat_id
              : typeof eventPayload.parent_id === "string"
                ? eventPayload.parent_id
                : null;
        if (eventChatId && eventChatId !== chatId) return;

        const event = { type: type as SubChatEventType, payload: eventPayload };
        subChatEvents.push(event);
        if (type === "awaiting_user_input") {
          waitingForUserPayload = eventPayload;
          messageId = typeof eventPayload.message_id === "string" ? eventPayload.message_id : messageId;
          taskId = typeof eventPayload.task_id === "string" ? eventPayload.task_id : taskId;
          latestContent = typeof eventPayload.question === "string" ? eventPayload.question : latestContent;
          postProcessingDone = true;
        }
        if (type === "awaiting_sub_chats_completion") {
          awaitingSubChatsCompletion = true;
          resetTimeout(SUB_CHAT_COMPLETION_TIMEOUT_MS);
        }
        const handler = options?.onSubChatEvent;
        if (!handler) return;

        const pending = Promise.resolve(handler(event));
        pendingSubChatHandlers.add(pending);
        pending
          .catch((error: unknown) => {
            cleanup();
            reject(error instanceof Error ? error : new Error(String(error)));
          })
          .finally(() => {
            pendingSubChatHandlers.delete(pending);
            maybeResolve();
          });
      };

      const handleAppSettingsMemoriesRequest = (p: Record<string, unknown>) => {
        const eventChatId = typeof p.chat_id === "string" ? p.chat_id : null;
        if (eventChatId !== chatId) return;

        const handler = options?.onAppSettingsMemoriesRequest;
        if (!handler) return;

        resetTimeout(timeoutMs);
        const requestedKeys = Array.isArray(p.requested_keys)
          ? (p.requested_keys as unknown[]).filter(
              (key): key is string => typeof key === "string" && key.length > 0,
            )
          : [];
        const event: AppSettingsMemoriesRequestEvent = {
          requestId: typeof p.request_id === "string" ? p.request_id : null,
          chatId: eventChatId,
          requestedKeys,
          payload: p,
        };

        const pending = Promise.resolve(handler(event));
        pendingMemoryRequestHandlers.add(pending);
        pending
          .catch((error: unknown) => {
            cleanup();
            reject(error instanceof Error ? error : new Error(String(error)));
          })
          .finally(() => {
            pendingMemoryRequestHandlers.delete(pending);
            maybeResolve();
          });
      };

      // Called once AI response is done. Start a short window to wait for
      // post_processing_metadata which may carry follow-up suggestions.
      const scheduleResolve = (content: string) => {
        if (
          awaitingSubChatsCompletion &&
          content.trim().startsWith(SUB_CHAT_PARENT_STATUS_MESSAGE)
        ) {
          latestContent = "";
          return;
        }
        aiResponseDone = true;
        latestContent = content;
        clearTimeout(timeout);
        // Start the post-processing window — resolve early if we get suggestions.
        postProcessingTimer = setTimeout(finishPostProcessingWait, POST_PROCESSING_WINDOW_MS);
      };

      const onMessage = (rawData: RawData) => {
        try {
          const parsed = JSON.parse(rawData.toString()) as WsEnvelope<
            Record<string, unknown>
          >;
          const p = (parsed.payload ?? {}) as Record<string, unknown>;
          const type = parsed.type;

          const protocolError = websocketProtocolError(parsed);
          if (protocolError) {
            if (!errorFrameBelongsToAiResponse(parsed, userMessageId, chatId, options?.recoveryTurnId)) {
              return;
            }
            cleanup();
            reject(protocolError);
            return;
          }

          if (SUB_CHAT_EVENT_TYPES.has(type)) {
            handleSubChatEvent(type, p);
            return;
          }

          if (type === "request_app_settings_memories") {
            handleAppSettingsMemoriesRequest(p);
            return;
          }

          if (type === "send_embed_data") {
            const embedPayload = (p.payload && typeof p.payload === "object"
              ? p.payload
              : p) as Record<string, unknown>;
            if (typeof embedPayload.chat_id === "string" && embedPayload.chat_id !== chatId) {
              return;
            }
            const embedId = embedPayload.embed_id;
            if (typeof embedId === "string" && embedId) {
              const status = typeof embedPayload.status === "string" ? embedPayload.status : "finished";
              embeds.set(embedId, embedPayload as unknown as SendEmbedDataFrame);
              if (status === "processing") {
                processingEmbedIds.add(embedId);
              } else {
                processingEmbedIds.delete(embedId);
              }
              maybeResolve();
            }
            return;
          }

          if (type === "task_event") {
            const event = parseTaskEvent(p);
            if (!event || event.chat_id !== chatId) return;
            taskEvents.push(event);
            maybeResolve();
            return;
          }

          if (type === "task_update_jobs_available") {
            mergePendingTaskUpdateJobs(parsePendingTaskUpdateJobs(p.jobs));
            maybeResolve();
            return;
          }

          if (type === "recovery_jobs_available") {
            const job = parseAvailableRecoveryJobs(p.jobs).find(
              (candidate) =>
                candidate.chat_id === chatId &&
                (!options?.recoveryTurnId || candidate.turn_id === options.recoveryTurnId),
            );
            if (!job) return;
            recoveryJobId = job.job_id;
            messageId = job.assistant_message_id;
            if (aiResponseDone) maybeResolve();
            else scheduleResolve(latestContent);
            return;
          }

          // Active-chat streaming: incremental chunks
          if (type === "ai_message_update") {
            const msgId = p.user_message_id ?? p.userMessageId;
            if (msgId !== userMessageId && p.chat_id !== chatId) return;
            capture(p);
            if (typeof p.full_content_so_far === "string") {
              latestContent = p.full_content_so_far;
            }
            if (p.is_final_chunk === true) {
              onStream?.({
                kind: "done",
                content: latestContent,
                category,
                modelName,
              });
              scheduleResolve(latestContent);
            } else {
              onStream?.({
                kind: "chunk",
                content: latestContent,
                category,
                modelName,
              });
            }
            return;
          }

          // Background path: single completion event
          if (type === "ai_background_response_completed") {
            const msgId = p.user_message_id ?? p.userMessageId;
            if (msgId && msgId !== userMessageId && p.chat_id !== chatId) return;
            if (!msgId && p.chat_id !== chatId) return;
            capture(p);
            const content =
              typeof p.full_content === "string"
                ? p.full_content
                : latestContent;
            onStream?.({ kind: "done", content, category, modelName });
            scheduleResolve(content);
            return;
          }

          // Fallback path: the server may broadcast a completed assistant
          // message via chat_message_added even when stream frames were missed.
          if (type === "chat_message_added") {
            if (p.chat_id !== chatId) return;
            const rawMessage = p.message;
            if (!rawMessage || typeof rawMessage !== "object") return;
            const message = rawMessage as Record<string, unknown>;
            if (message.role !== "assistant") return;
            const content = extractMessageContent(message);
            if (!content) return;
            capture(message);
            if (typeof message.category === "string" && message.category) {
              category = message.category;
            }
            if (typeof message.model_name === "string" && message.model_name) {
              modelName = message.model_name;
            }
            onStream?.({ kind: "done", content, category, modelName });
            scheduleResolve(content);
            return;
          }

          // Typing started — fires before content chunks arrive
          if (type === "ai_typing_started") {
            capture(p);
            onStream?.({
              kind: "typing",
              content: "",
              category,
              modelName,
            });
            return;
          }

          // Server post-processing carries plain suggestions; the CLI then
          // encrypts and stores them via post_processing_metadata below.
          // Mirrors: chatSyncServiceHandlersAI.ts handlePostProcessingCompletedImpl()
          if (type === "post_processing_completed" || type === "post_processing_metadata") {
            if (p.chat_id !== chatId) return;
            const rawSuggestions = p.follow_up_request_suggestions;
            if (Array.isArray(rawSuggestions) && rawSuggestions.length > 0) {
              followUpSuggestions = (rawSuggestions as unknown[]).filter(
                (s): s is string => typeof s === "string" && s.length > 0,
              );
            }
            const rawNewChatSuggestions = p.new_chat_request_suggestions;
            if (Array.isArray(rawNewChatSuggestions) && rawNewChatSuggestions.length > 0) {
              newChatSuggestions = (rawNewChatSuggestions as unknown[]).filter(
                (s): s is string => typeof s === "string" && s.length > 0,
              );
            }
            taskProposals = parseTaskProposals(p.task_proposals);
            taskUpdateProposals = parseTaskUpdateProposals(p.task_update_proposals);
            // If AI response already done, resolve immediately with suggestions.
            if (aiResponseDone) {
              if (postProcessingTimer) {
                clearTimeout(postProcessingTimer);
                postProcessingTimer = null;
              }
              finishPostProcessingWait();
            }
            return;
          }
        } catch {
          // Ignore malformed frames.
        }
      };

      const onError = (error: Error) => {
        cleanup();
        reject(error);
      };
      const onClose = () => {
        // If AI response already completed, close is not an error — resolve with what we have.
        if (aiResponseDone) {
          cleanup();
          resolve({
            status: "completed",
            messageId,
            taskId,
            content: latestContent,
            category,
            modelName,
            followUpSuggestions,
            newChatSuggestions,
            taskProposals,
            taskUpdateProposals,
            taskEvents,
            pendingTaskUpdateJobs,
            embeds: [...embeds.values()],
            subChatEvents,
            recoveryJobId,
          });
          return;
        }
        cleanup();
        reject(new Error("WebSocket closed while waiting for AI response"));
      };

      const cleanup = () => {
        clearTimeout(timeout);
        if (postProcessingTimer) {
          clearTimeout(postProcessingTimer);
          postProcessingTimer = null;
        }
        if (asyncEmbedTimer) {
          clearTimeout(asyncEmbedTimer);
          asyncEmbedTimer = null;
        }
        this.socket.off("message", onMessage);
        this.socket.off("error", onError);
        this.socket.off("close", onClose);
        this.activeResponseCollectors = Math.max(0, this.activeResponseCollectors - 1);
      };

      this.socket.on("message", onMessage);
      this.socket.on("error", onError);
      this.socket.on("close", onClose);
    });
  }
}
