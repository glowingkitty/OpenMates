// @vitest-environment jsdom
import { mount, tick, unmount } from "svelte";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import ConfirmPair from "../SettingsSessionsConfirmPair.svelte";
import { pendingPairToken } from "../../../../stores/pairSessionStore";
import type { PairInfo } from "../../../../services/pairV2";

const mocks = vi.hoisted(() => ({
  request: vi.fn(),
  createApprover: vi.fn(),
  masterKey: vi.fn(),
}));
vi.mock("@repo/ui", async () => ({
  text: (await import("svelte/store")).writable((key: string) => key),
}));
vi.mock("../SecurityAuth.svelte", () => ({ default: {} }));
vi.mock("../../../../stores/pairSessionStore", async () => {
  const { writable } = await import("svelte/store");
  return {
    pendingPairToken: writable<string | null>(null),
    newlyPairedSession: writable(false),
  };
});
vi.mock("../../../../stores/userProfile", async () => ({
  userProfile: (await import("svelte/store")).writable({
    user_id: "synthetic-authorizer",
  }),
}));
vi.mock("../../../../stores/notificationStore", () => ({
  notificationStore: { success: vi.fn() },
}));
vi.mock("../../../../config/api", () => ({
  getApiEndpoint: (path: string) => path,
  apiEndpoints: { auth: { methods: "/methods" } },
}));
vi.mock("../../../../services/pairV2", () => ({
  pairRequest: mocks.request,
  PAIR_POLL_MS: 1500,
  pairExpired: (expiry: number) => expiry <= Date.now() / 1000,
  resolvePairEmailEnvelope: vi.fn(),
}));
vi.mock("../../../../services/cryptoService", () => ({
  getKeyFromStorage: mocks.masterKey,
  getEmailSalt: vi.fn(),
  getEmailDecryptedWithMasterKey: vi.fn(),
  uint8ArrayToBase64: vi.fn(),
}));
vi.mock("@repo/pairing-crypto", () => ({
  createPairContext: JSON.stringify,
  createPairApprover: mocks.createApprover,
  generateGrantSecret: vi.fn(),
}));

function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((complete) => {
    resolve = complete;
  });
  return { promise, resolve };
}
function pair(token: string): PairInfo {
  return {
    protocol_version: 2,
    token,
    session_id: `session-${token}`,
    receiver_token_hash: token.repeat(11).slice(0, 64),
    authorizer_user_id: "synthetic-authorizer",
    auto_logout_minutes: null,
    device_name: `Device ${token}`,
    expires_at: Math.floor(Date.now() / 1000) + 300,
  };
}
function approver(pin: string) {
  return {
    pin,
    abort: vi.fn(),
    receiveRequest: vi.fn(async () => "synthetic-response"),
    verifyFinish: vi.fn(async () => {}),
    encryptBundle: vi.fn(),
  };
}
async function flush() {
  for (let i = 0; i < 15; i++) await Promise.resolve();
  await tick();
}

describe("ConfirmPair request replacement", () => {
  let target: HTMLDivElement;
  let component: ReturnType<typeof mount>;
  beforeEach(() => {
    vi.useFakeTimers();
    mocks.request.mockReset();
    mocks.createApprover.mockReset();
    mocks.masterKey.mockReset();
    pendingPairToken.set("ABC346");
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => ({
        ok: true,
        json: async () => ({ has_password: true }),
      })),
    );
    mocks.request.mockImplementation(async (path: string) => {
      if (path.startsWith("/info/")) return pair(path.split("/").at(-1)!);
      if (path.startsWith("/approve/"))
        return { ...pair(path.split("/").at(-1)!), success: true };
      return { status: "approved", success: true };
    });
    mocks.createApprover.mockResolvedValue(approver("DEF468"));
    target = document.createElement("div");
    document.body.appendChild(target);
  });
  afterEach(async () => {
    if (component) await unmount(component);
    target.remove();
    vi.useRealTimers();
    vi.unstubAllGlobals();
  });
  async function start() {
    component = mount(ConfirmPair, { target });
    await flush();
  }
  async function allow() {
    target
      .querySelector<HTMLButtonElement>('[data-testid="pair-allow-button"]')!
      .click();
    await flush();
  }

  // contract-test: supporting surface=gui.web assertions=auth.pair-login.lifecycle
  it("ignores old info completion after a new token arrives", async () => {
    const oldInfo = deferred<PairInfo>();
    mocks.request.mockImplementation(async (path: string) =>
      path === "/info/ABC346" ? oldInfo.promise : pair("DEF468"),
    );
    await start();
    pendingPairToken.set("DEF468");
    await flush();
    expect(target.textContent).toContain("Device DEF468");
    oldInfo.resolve({ ...pair("ABC346"), expires_at: 0 });
    await flush();
    expect(target.textContent).toContain("Device DEF468");
    expect(target.textContent).not.toContain("pair_invalid_token");
    expect(
      target.querySelector('[data-testid="pair-allow-button"]'),
    ).not.toBeNull();
  });

  // contract-test: supporting surface=gui.web assertions=auth.pair-login.lifecycle
  it("ignores an old authentication-method error after the replacement confirms", async () => {
    const oldMethods = deferred<{ ok: boolean; json: () => Promise<object> }>();
    vi.stubGlobal(
      "fetch",
      vi
        .fn()
        .mockReturnValueOnce(oldMethods.promise)
        .mockResolvedValue({
          ok: true,
          json: async () => ({ has_password: true }),
        }),
    );
    await start();
    pendingPairToken.set("DEF468");
    await flush();
    expect(
      target.querySelector('[data-testid="pair-allow-button"]'),
    ).not.toBeNull();
    oldMethods.resolve({ ok: false, json: async () => ({}) });
    await flush();
    expect(target.textContent).toContain("Device DEF468");
    expect(target.textContent).not.toContain(
      "Could not load authentication methods",
    );
    expect(
      target.querySelector('[data-testid="pair-allow-button"]'),
    ).not.toBeNull();
  });

  // contract-test: supporting surface=gui.web assertions=auth.pair-login.lifecycle,auth.pair-login.single-use-zk
  it("cancels a late old approval using its captured token rather than the replacement token", async () => {
    const oldApproval = deferred<PairInfo & { success: boolean }>();
    const implementation = mocks.request.getMockImplementation()!;
    mocks.request.mockImplementation((path: string, options?: RequestInit) =>
      path === "/approve/ABC346"
        ? oldApproval.promise
        : implementation(path, options),
    );
    await start();
    await allow();
    pendingPairToken.set("DEF468");
    await flush();
    oldApproval.resolve({ ...pair("ABC346"), success: true });
    await flush();
    expect(mocks.request).toHaveBeenCalledWith("/ABC346", { method: "DELETE" });
    expect(mocks.request).not.toHaveBeenCalledWith("/DEF468", {
      method: "DELETE",
    });
    expect(mocks.createApprover).not.toHaveBeenCalled();
    expect(target.textContent).toContain("Device DEF468");
  });

  // contract-test: supporting surface=gui.web assertions=auth.pair-login.lifecycle,auth.pair-login.single-use-zk
  it("aborts an old asynchronous PAKE initializer without replacing the new PIN", async () => {
    const oldCreation = deferred<ReturnType<typeof approver>>();
    const old = approver("ABC346"),
      current = approver("DEF468");
    mocks.createApprover
      .mockImplementationOnce(() => oldCreation.promise)
      .mockResolvedValue(current);
    await start();
    await allow();
    pendingPairToken.set("DEF468");
    await flush();
    await allow();
    expect(
      target.querySelector('[data-testid="pair-pin-display"]')?.textContent,
    ).toContain("DEF 468");
    oldCreation.resolve(old);
    await flush();
    expect(old.abort).toHaveBeenCalledOnce();
    expect(current.abort).not.toHaveBeenCalled();
    expect(
      target.querySelector('[data-testid="pair-pin-display"]')?.textContent,
    ).toContain("DEF 468");
  });

  // contract-test: supporting surface=gui.web assertions=auth.pair-login.lifecycle,auth.pair-login.single-use-zk
  it("fences late old polling and does not clear the new in-flight polling guard", async () => {
    const oldPoll = deferred<{ status: string }>(),
      currentPoll = deferred<{ status: string }>();
    const old = approver("ABC346"),
      current = approver("DEF468");
    mocks.createApprover.mockResolvedValueOnce(old).mockResolvedValue(current);
    const implementation = mocks.request.getMockImplementation()!;
    mocks.request.mockImplementation((path: string, options?: RequestInit) =>
      path === "/authorizer/ABC346"
        ? oldPoll.promise
        : path === "/authorizer/DEF468"
          ? currentPoll.promise
          : implementation(path, options),
    );
    await start();
    await allow();
    await vi.advanceTimersByTimeAsync(1500);
    pendingPairToken.set("DEF468");
    await flush();
    await allow();
    await vi.advanceTimersByTimeAsync(1500);
    oldPoll.resolve({ status: "cancelled" });
    await flush();
    await vi.advanceTimersByTimeAsync(1500);
    expect(
      mocks.request.mock.calls.filter(
        ([path]) => path === "/authorizer/DEF468",
      ),
    ).toHaveLength(1);
    expect(old.abort).toHaveBeenCalledOnce();
    expect(
      target.querySelector('[data-testid="pair-pin-display"]')?.textContent,
    ).toContain("DEF 468");
    currentPoll.resolve({ status: "approved" });
    await flush();
  });

  // contract-test: supporting surface=gui.web assertions=auth.pair-login.single-use-zk,auth.pair-login.lifecycle
  it("does not send a PAKE response or export account keys after replacement during receiveRequest", async () => {
    const pendingResponse = deferred<string>();
    const old = approver("ABC346");
    old.receiveRequest.mockImplementation(() => pendingResponse.promise);
    mocks.createApprover.mockResolvedValue(old);
    const implementation = mocks.request.getMockImplementation()!;
    mocks.request.mockImplementation((path: string, options?: RequestInit) =>
      path === "/authorizer/ABC346"
        ? Promise.resolve({
            status: "request",
            receiver_request: "synthetic-ke1",
          })
        : implementation(path, options),
    );
    await start();
    await allow();
    await vi.advanceTimersByTimeAsync(1500);
    expect(old.receiveRequest).toHaveBeenCalledOnce();
    pendingPairToken.set("DEF468");
    await flush();
    pendingResponse.resolve("late-synthetic-response");
    await flush();
    expect(
      mocks.request.mock.calls.some(
        ([path]) => path.endsWith("/message") || path.startsWith("/authorize/"),
      ),
    ).toBe(false);
    expect(mocks.masterKey).not.toHaveBeenCalled();
    expect(target.textContent).toContain("Device DEF468");
  });

  // contract-test: supporting surface=gui.web assertions=auth.pair-login.single-use-zk,auth.pair-login.lifecycle
  it("does not build or authorize an old key bundle after replacement during PAKE final verification", async () => {
    const pendingFinish = deferred<void>();
    const old = approver("ABC346");
    old.verifyFinish.mockImplementation(() => pendingFinish.promise);
    mocks.createApprover.mockResolvedValue(old);
    let polls = 0;
    const implementation = mocks.request.getMockImplementation()!;
    mocks.request.mockImplementation((path: string, options?: RequestInit) =>
      path === "/authorizer/ABC346"
        ? Promise.resolve(
            ++polls === 1
              ? { status: "request", receiver_request: "synthetic-ke1" }
              : { status: "finish", receiver_finish: "synthetic-ke3" },
          )
        : implementation(path, options),
    );
    await start();
    await allow();
    await vi.advanceTimersByTimeAsync(1500);
    await flush();
    await vi.advanceTimersByTimeAsync(1500);
    expect(old.verifyFinish).toHaveBeenCalledOnce();
    pendingPairToken.set("DEF468");
    await flush();
    pendingFinish.resolve();
    await flush();
    expect(mocks.masterKey).not.toHaveBeenCalled();
    expect(
      mocks.request.mock.calls.some(
        ([path]) => path === "/account-check" || path.startsWith("/authorize/"),
      ),
    ).toBe(false);
    expect(target.textContent).toContain("Device DEF468");
  });
});
