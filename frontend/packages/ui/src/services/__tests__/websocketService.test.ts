// frontend/packages/ui/src/services/__tests__/websocketService.test.ts
// Regression coverage for low-level WebSocket message routing.
// Some server events can arrive during cold boot before ChatSync registers its
// handlers. These tests guard the tiny replay buffer used for recovery jobs so
// encrypted completion recovery does not lose an availability announcement.

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { webSocketService } from "../websocketService";
import * as wsTracing from "../tracing/wsSpans";

afterEach(() => {
  vi.restoreAllMocks();
});

describe("webSocketService early message replay", () => {
  beforeEach(() => {
    webSocketService.clearHandlers("recovery_jobs_available");
    (webSocketService as unknown as { earlyMessagesByType: Map<string, unknown[]> })
      .earlyMessagesByType
      .clear();
  });

  // contract-test: direct surface=gui.web assertions=chats.sync.key-gated-recovery,chats.completion.recovery-takeover
  it("replays buffered recovery availability once when the handler registers", async () => {
    const payload = { jobs: [{ job_id: "job-1" }] };
    (webSocketService as unknown as {
      bufferEarlyMessage: (messageType: string, payload: unknown) => void;
    }).bufferEarlyMessage("recovery_jobs_available", payload);

    const handler = vi.fn();
    webSocketService.on("recovery_jobs_available", handler);

    await vi.waitFor(() => {
      expect(handler).toHaveBeenCalledWith(payload);
    });
    expect(handler).toHaveBeenCalledTimes(1);

    const laterHandler = vi.fn();
    webSocketService.on("recovery_jobs_available", laterHandler);
    await Promise.resolve();

    expect(laterHandler).not.toHaveBeenCalled();
    webSocketService.off("recovery_jobs_available", handler);
    webSocketService.off("recovery_jobs_available", laterHandler);
  });
});

describe("webSocketService recovery protocol errors", () => {
  // contract-test: supporting surface=gui.web assertions=chats.completion.lease-fenced
  it("does not emit a global server error for retryable recovery version conflicts", () => {
    const consoleDebug = vi.spyOn(console, "debug").mockImplementation(() => undefined);
    const consoleError = vi.spyOn(console, "error").mockImplementation(() => undefined);
    const handlers = (webSocketService as unknown as {
      messageHandlers: Map<string, Array<(payload: unknown) => void>>;
    }).messageHandlers.get("error");

    expect(handlers?.length).toBeGreaterThan(0);
    handlers?.[0]?.({
      code: "version_conflict",
      job_id: "job-1",
      request_id: "request-1",
      message: "Encrypted completion recovery was rejected.",
    });

    expect(consoleDebug).toHaveBeenCalledWith(
      "[WebSocketService] Received retryable recovery protocol error:",
      expect.objectContaining({ code: "version_conflict" }),
    );
    expect(consoleError).not.toHaveBeenCalledWith(
      "[WebSocketService] Received error message from server:",
      expect.anything(),
    );
  });

  // contract-test: supporting surface=gui.web assertions=chats.completion.lease-fenced
  it("does not emit a global server error for retryable recovery lease conflicts", () => {
    const consoleDebug = vi.spyOn(console, "debug").mockImplementation(() => undefined);
    const consoleError = vi.spyOn(console, "error").mockImplementation(() => undefined);
    const handlers = (webSocketService as unknown as {
      messageHandlers: Map<string, Array<(payload: unknown) => void>>;
    }).messageHandlers.get("error");

    handlers?.[0]?.({
      code: "lease_conflict",
      job_id: "job-1",
      request_id: "request-1",
      message: "Encrypted completion recovery was rejected.",
    });

    expect(consoleDebug).toHaveBeenCalledWith(
      "[WebSocketService] Received retryable recovery protocol error:",
      expect.objectContaining({ code: "lease_conflict" }),
    );
    expect(consoleError).not.toHaveBeenCalledWith(
      "[WebSocketService] Received error message from server:",
      expect.anything(),
    );
  });

  // contract-test: supporting surface=gui.web assertions=chats.completion.lease-fenced
  it("does not emit a global server error for stale recovery jobs", () => {
    const consoleDebug = vi.spyOn(console, "debug").mockImplementation(() => undefined);
    const consoleError = vi.spyOn(console, "error").mockImplementation(() => undefined);
    const handlers = (webSocketService as unknown as {
      messageHandlers: Map<string, Array<(payload: unknown) => void>>;
    }).messageHandlers.get("error");

    handlers?.[0]?.({
      code: "recovery_job_not_found",
      job_id: "job-1",
      request_id: "request-1",
      message: "Recovery job is no longer available.",
    });

    expect(consoleDebug).toHaveBeenCalledWith(
      "[WebSocketService] Received retryable recovery protocol error:",
      expect.objectContaining({ code: "recovery_job_not_found" }),
    );
    expect(consoleError).not.toHaveBeenCalledWith(
      "[WebSocketService] Received error message from server:",
      expect.anything(),
    );
  });

  // contract-test: supporting surface=gui.web assertions=chats.completion.lease-fenced
  it("does not emit a global server error for stale legacy recovery persistence", () => {
    const consoleDebug = vi.spyOn(console, "debug").mockImplementation(() => undefined);
    const consoleError = vi.spyOn(console, "error").mockImplementation(() => undefined);
    const handlers = (webSocketService as unknown as {
      messageHandlers: Map<string, Array<(payload: unknown) => void>>;
    }).messageHandlers.get("error");

    handlers?.[0]?.({
      code: "recovery_persistence_required",
      message: "This saved-chat completion must use encrypted recovery persistence.",
    });

    expect(consoleDebug).toHaveBeenCalledWith(
      "[WebSocketService] Received retryable recovery protocol error:",
      expect.objectContaining({ code: "recovery_persistence_required" }),
    );
    expect(consoleError).not.toHaveBeenCalledWith(
      "[WebSocketService] Received error message from server:",
      expect.anything(),
    );
  });
});

describe("webSocketService message dispatch", () => {
  // contract-test: supporting surface=gui.web assertions=chats.message.identity-idempotent
  it("rejects instead of silently dropping a message when the socket changes during tracing", async () => {
    const service = webSocketService as unknown as {
      ws: { readyState: number; send: ReturnType<typeof vi.fn> } | null;
    };
    const socket = { readyState: WebSocket.OPEN, send: vi.fn() };
    service.ws = socket;
    vi.spyOn(wsTracing, "withActiveWsSpan").mockImplementation(async (_name, callback) => {
      service.ws = null;
      return callback();
    });

    await expect(webSocketService.sendMessage("chat_turn_preflight", {})).rejects.toThrow(
      "WebSocket changed before message dispatch",
    );
    expect(socket.send).not.toHaveBeenCalled();
  });
});
