/*
 * OpenMates CLI WebSocket transport.
 *
 * Purpose: send/receive chat sync events over the same protocol as web clients.
 * Architecture: thin wrapper around ws with typed envelope helpers.
 * Architecture doc: docs/architecture/openmates-cli.md
 * Security: auth token is passed via query params as supported by backend auth_ws.
 * Tests: exercised indirectly via CLI chat command tests and manual runs.
 */

import WebSocket, { type RawData } from "ws";

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

export class OpenMatesWsClient {
  private readonly socket: WebSocket;

  constructor(options: {
    apiUrl: string;
    sessionId: string;
    wsToken: string | null;
    refreshToken: string | null;
    userAgent?: string;
  }) {
    const wsBase = options.apiUrl.replace(/^http/, "ws").replace(/\/$/, "");
    const token = options.wsToken ?? options.refreshToken ?? "";
    const query = new URLSearchParams({
      sessionId: options.sessionId,
      token,
    });
    // Pass the same User-Agent as the HTTP login call so the device fingerprint
    // hash (SHA256(OS:Country:UserID)) matches the one registered at login time.
    const wsHeaders: Record<string, string> = {};
    if (options.userAgent) {
      wsHeaders["User-Agent"] = options.userAgent;
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
      this.socket.once("error", (error) => {
        clearTimeout(timeout);
        reject(error);
      });
    });
  }

  close(): void {
    this.socket.close();
  }

  send(type: string, payload: unknown): void {
    this.socket.send(JSON.stringify({ type, payload }));
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
      onStream?: (event: StreamEvent) => void;
    },
  ): Promise<{
    content: string;
    category: string | null;
    modelName: string | null;
    followUpSuggestions: string[];
  }> {
    const timeoutMs = options?.timeoutMs ?? 90_000;
    const onStream = options?.onStream;

    return new Promise((resolve, reject) => {
      let latestContent = "";
      let category: string | null = null;
      let modelName: string | null = null;
      let followUpSuggestions: string[] = [];
      // Track whether the AI response is done so we can wait for post-processing.
      let aiResponseDone = false;
      // Post-processing metadata arrives up to ~10 s after the AI response.
      // We wait a short window for it so follow-up suggestions are available.
      const POST_PROCESSING_WINDOW_MS = 12_000;
      let postProcessingTimer: ReturnType<typeof setTimeout> | null = null;

      const timeout = setTimeout(() => {
        cleanup();
        reject(new Error("Timed out waiting for AI response"));
      }, timeoutMs);

      const capture = (p: Record<string, unknown>) => {
        if (typeof p.category === "string" && p.category) category = p.category;
        if (typeof p.model_name === "string" && p.model_name)
          modelName = p.model_name;
      };

      // Called once AI response is done. Start a short window to wait for
      // post_processing_metadata which may carry follow-up suggestions.
      const scheduleResolve = (content: string) => {
        aiResponseDone = true;
        latestContent = content;
        // Start the post-processing window — resolve early if we get suggestions.
        postProcessingTimer = setTimeout(() => {
          cleanup();
          resolve({
            content: latestContent,
            category,
            modelName,
            followUpSuggestions,
          });
        }, POST_PROCESSING_WINDOW_MS);
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

          // Active-chat streaming: incremental chunks
          if (type === "ai_message_update") {
            const msgId = p.user_message_id ?? p.userMessageId;
            if (msgId !== userMessageId) return;
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
            if (msgId && msgId !== userMessageId) return;
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
              cleanup();
              resolve({
                content: latestContent,
                category,
                modelName,
                followUpSuggestions,
              });
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
            content: latestContent,
            category,
            modelName,
            followUpSuggestions,
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
