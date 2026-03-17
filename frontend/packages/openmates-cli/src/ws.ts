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

  collectAiResponse(
    userMessageId: string,
    timeoutMs = 90_000,
  ): Promise<string> {
    return new Promise<string>((resolve, reject) => {
      let lastChunk = "";
      const timeout = setTimeout(() => {
        cleanup();
        reject(new Error("Timed out waiting for AI response"));
      }, timeoutMs);

      const onMessage = (rawData: RawData) => {
        try {
          const parsed = JSON.parse(rawData.toString()) as WsEnvelope<
            Record<string, unknown>
          >;
          const payload = parsed.payload ?? {};

          if (parsed.type === "error") {
            cleanup();
            const message =
              typeof payload.message === "string"
                ? payload.message
                : "Unknown chat error";
            reject(new Error(message));
            return;
          }

          if (
            parsed.type === "ai_message_chunk" &&
            payload &&
            payload.user_message_id === userMessageId &&
            typeof payload.full_content_so_far === "string"
          ) {
            lastChunk = payload.full_content_so_far;
            return;
          }

          if (
            parsed.type === "ai_response_completed" &&
            payload &&
            payload.user_message_id === userMessageId
          ) {
            cleanup();
            resolve(lastChunk);
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
        cleanup();
        reject(new Error("WebSocket closed while waiting for AI response"));
      };

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
}
