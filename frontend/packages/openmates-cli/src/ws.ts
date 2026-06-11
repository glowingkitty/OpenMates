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

export class OpenMatesWsClient {
  private readonly socket: InstanceType<typeof WebSocket>;

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

  waitForMessage(
    expectedType: string,
    predicate?: (payload: unknown) => boolean,
    timeoutMs = 20_000,
  ): Promise<WsEnvelope> {
    return new Promise<WsEnvelope>((resolve, reject) => {
      const onMessage = (rawData: RawData) => {
        try {
          const parsed = JSON.parse(rawData.toString()) as WsEnvelope;
          if (parsed.type !== expectedType) {
            return;
          }
          if (predicate && !predicate(parsed.payload)) {
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
        reject(new Error(`Timeout waiting for '${expectedType}'`));
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
    },
  ): Promise<{
    messageId: string | null;
    taskId: string | null;
    content: string;
    category: string | null;
    modelName: string | null;
    followUpSuggestions: string[];
    embeds: SendEmbedDataFrame[];
    subChatEvents: SubChatEvent[];
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
      let followUpSuggestions: string[] = [];
      const subChatEvents: SubChatEvent[] = [];
      const pendingSubChatHandlers = new Set<Promise<void>>();
      const pendingMemoryRequestHandlers = new Set<Promise<void>>();
      const embeds = new Map<string, SendEmbedDataFrame>();
      const processingEmbedIds = new Set<string>();
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
        if (!aiResponseDone || !postProcessingDone) return;
        if (pendingSubChatHandlers.size > 0) return;
        if (pendingMemoryRequestHandlers.size > 0) return;
        if (processingEmbedIds.size > 0 && !asyncEmbedTimer) {
          asyncEmbedTimer = setTimeout(() => {
            cleanup();
            resolve({
              messageId,
              taskId,
              content: latestContent,
              category,
              modelName,
              followUpSuggestions,
              embeds: [...embeds.values()],
              subChatEvents,
            });
          }, asyncEmbedWaitMs);
          return;
        }
        if (processingEmbedIds.size > 0) return;
        cleanup();
        resolve({
          messageId,
          taskId,
          content: latestContent,
          category,
          modelName,
          followUpSuggestions,
          embeds: [...embeds.values()],
          subChatEvents,
        });
      };

      const handleSubChatEvent = (type: string, p: Record<string, unknown>) => {
        const eventPayload =
          p.payload && typeof p.payload === "object" && !Array.isArray(p.payload)
            ? (p.payload as Record<string, unknown>)
            : p;
        const eventChatId =
          typeof eventPayload.chat_id === "string"
            ? eventPayload.chat_id
            : typeof eventPayload.parent_id === "string"
              ? eventPayload.parent_id
              : null;
        if (eventChatId && eventChatId !== chatId) return;

        const event = { type: type as SubChatEventType, payload: eventPayload };
        subChatEvents.push(event);
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

          if (type === "error") {
            cleanup();
            reject(
              new Error(
                typeof p.message === "string"
                  ? p.message
                  : "Unknown chat error",
              ),
            );
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

          // Post-processing metadata — carries follow-up suggestions for this chat.
          // Arrives asynchronously after the AI response completes.
          // Mirrors: chatSyncServiceHandlersAI.ts handlePostProcessingMetadata()
          if (type === "post_processing_metadata") {
            if (p.chat_id !== chatId) return;
            const rawSuggestions = p.follow_up_request_suggestions;
            if (Array.isArray(rawSuggestions) && rawSuggestions.length > 0) {
              followUpSuggestions = (rawSuggestions as unknown[]).filter(
                (s): s is string => typeof s === "string" && s.length > 0,
              );
            }
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
            messageId,
            taskId,
            content: latestContent,
            category,
            modelName,
            followUpSuggestions,
            embeds: [...embeds.values()],
            subChatEvents,
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
      };

      this.socket.on("message", onMessage);
      this.socket.on("error", onError);
      this.socket.on("close", onClose);
    });
  }
}
