import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const listeners = vi.hoisted(() => new Set<(entry: unknown) => void>());
vi.mock("../logCollector", () => ({
  logCollector: {
    onNewLog: (listener: (entry: unknown) => void) => listeners.add(listener),
    offNewLog: (listener: (entry: unknown) => void) => listeners.delete(listener),
    sanitizeContent: (message: string) => message.replace("person@example.test", "[EMAIL-REDACTED]"),
  },
}));
vi.mock("../../config/api", () => ({
  getApiEndpoint: (path: string) => path,
  apiEndpoints: {
    settings: { clientLogsEphemeral: "/v1/client-logs", debugLogs: "/v1/settings/debug-logs" },
    admin: { clientLogs: "/v1/admin/client-logs" },
    e2e: { clientLogs: "/e2e/client-logs" },
  },
}));

function warn(message = "Diagnostic warning") {
  for (const listener of listeners) listener({ timestamp: Date.now(), level: "warn", message });
}

beforeEach(() => {
  vi.resetModules();
  vi.useFakeTimers();
  listeners.clear();
  sessionStorage.clear();
  vi.stubGlobal("indexedDB", undefined);
});
afterEach(() => {
  vi.clearAllTimers();
  vi.useRealTimers();
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe("authenticated diagnostic uploads", () => {
  // contract-test: supporting surface=gui.web assertions=auth.session.lifecycle
  it.each([401, 403])("stops uploads after HTTP %s until a new authenticated start", async (status) => {
    const fetchMock = vi.fn().mockResolvedValue(new Response(null, { status }));
    vi.stubGlobal("fetch", fetchMock);
    const { clientLogForwarder } = await import("../clientLogForwarder");
    clientLogForwarder.startEphemeral();
    warn();
    await vi.advanceTimersByTimeAsync(10_000);
    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(clientLogForwarder.isRunning).toBe(false);
    warn();
    await vi.advanceTimersByTimeAsync(30_000);
    expect(fetchMock).toHaveBeenCalledTimes(1);
    fetchMock.mockResolvedValue(new Response(null, { status: 200 }));
    clientLogForwarder.startEphemeral();
    warn();
    await vi.advanceTimersByTimeAsync(10_000);
    expect(fetchMock).toHaveBeenCalledTimes(2);
  });

  // contract-test: supporting surface=gui.web assertions=auth.session.lifecycle
  it("retries a sanitized batch after a temporary server failure", async () => {
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(new Response(null, { status: 503 }))
      .mockResolvedValue(new Response(null, { status: 200 }));
    vi.stubGlobal("fetch", fetchMock);
    const { clientLogForwarder } = await import("../clientLogForwarder");
    clientLogForwarder.startEphemeral();
    warn("Diagnostic from person@example.test");
    await vi.advanceTimersByTimeAsync(20_000);
    expect(fetchMock).toHaveBeenCalledTimes(2);
    const body = JSON.parse(fetchMock.mock.calls[1][1].body);
    expect(body.logs[0].message).toBe("Diagnostic from [EMAIL-REDACTED]");
    expect(clientLogForwarder.isRunning).toBe(true);
  });

  // contract-test: supporting surface=gui.web assertions=auth.session.lifecycle
  it("does not overlap uploads or let an old rejection stop a new session", async () => {
    let resolveOld!: (response: Response) => void;
    const fetchMock = vi.fn().mockImplementationOnce(() => new Promise<Response>((resolve) => {
      resolveOld = resolve;
    })).mockResolvedValue(new Response(null, { status: 200 }));
    vi.stubGlobal("fetch", fetchMock);
    const { clientLogForwarder } = await import("../clientLogForwarder");
    clientLogForwarder.startEphemeral();
    warn();
    await vi.advanceTimersByTimeAsync(10_000);
    warn();
    await vi.advanceTimersByTimeAsync(10_000);
    expect(fetchMock).toHaveBeenCalledTimes(1);
    await clientLogForwarder.stopEphemeral(false);
    clientLogForwarder.startEphemeral();
    resolveOld(new Response(null, { status: 401 }));
    await vi.advanceTimersByTimeAsync(0);
    expect(clientLogForwarder.isRunning).toBe(true);
    warn("New session diagnostic");
    await vi.advanceTimersByTimeAsync(10_000);
    expect(fetchMock).toHaveBeenCalledTimes(2);
  });

  // contract-test: supporting surface=gui.web assertions=auth.session.lifecycle
  it("stops the durable admin queue after an auth rejection", async () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response(null, { status: 401 }));
    vi.stubGlobal("fetch", fetchMock);
    const { clientLogForwarder } = await import("../clientLogForwarder");
    clientLogForwarder.start();
    warn();
    await vi.advanceTimersByTimeAsync(5_000);
    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(clientLogForwarder.isRunning).toBe(false);
    warn();
    await vi.advanceTimersByTimeAsync(15_000);
    expect(fetchMock).toHaveBeenCalledTimes(1);
    fetchMock.mockResolvedValue(new Response(null, { status: 200 }));
    clientLogForwarder.start();
    warn("New account diagnostic");
    await vi.advanceTimersByTimeAsync(5_000);
    expect(JSON.parse(fetchMock.mock.calls[1][1].body).logs.map((entry: { message: string }) => entry.message))
      .toEqual(["New account diagnostic"]);
  });

  // contract-test: supporting surface=gui.web assertions=auth.session.lifecycle
  it("does not let an old admin rejection stop forwarding after re-login", async () => {
    let resolveOld!: (response: Response) => void;
    const fetchMock = vi.fn().mockImplementationOnce(() => new Promise<Response>((resolve) => {
      resolveOld = resolve;
    })).mockResolvedValue(new Response(null, { status: 200 }));
    vi.stubGlobal("fetch", fetchMock);
    const { clientLogForwarder } = await import("../clientLogForwarder");
    clientLogForwarder.start();
    warn();
    await vi.advanceTimersByTimeAsync(5_000);
    await clientLogForwarder.stop(false);
    clientLogForwarder.start();
    resolveOld(new Response(null, { status: 401 }));
    await vi.advanceTimersByTimeAsync(0);
    expect(clientLogForwarder.isRunning).toBe(true);
    warn("New session diagnostic");
    await vi.advanceTimersByTimeAsync(5_000);
    expect(fetchMock).toHaveBeenCalledTimes(2);
    expect(JSON.parse(fetchMock.mock.calls[1][1].body).logs.map((entry: { message: string }) => entry.message))
      .toEqual(["New session diagnostic"]);
  });
});
