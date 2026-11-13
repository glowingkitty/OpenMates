// frontend/packages/ui/src/stores/__tests__/activeChatStoreRustUrlPlan.test.ts
// Unit tests for activeChatStore when the shared Rust core plans the URL update.
//
// The core answers asynchronously, so the address bar keeps the previous chat for a moment.
// Bug this guards against: dismissing a draft-only chat cleared the store, the page read the
// not-yet-updated hash and reopened the chat the user had just closed.
//
// Architecture: frontend/packages/ui/src/stores/activeChatStore.ts

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { get } from "svelte/store";
import { planUrlUpdate, type UrlPlan, type UrlPlanFacts } from "../activeChatUrlPlan";

const locationMock = vi.hoisted(() => {
  const loc = { hash: "", pathname: "/", search: "" };
  (globalThis as Record<string, unknown>).window = {
    ...(globalThis as Record<string, unknown>).window as object,
    location: loc,
  };
  return loc;
});

/** Plans the core has been asked for and has not answered yet, oldest first. */
const pendingPlans = vi.hoisted(() => [] as Array<{ answer: () => void; reject: (error: Error) => void }>);

vi.mock("$app/environment", () => ({ browser: true }));
vi.mock("../../services/chatUrlService", () => ({ isOnSemanticChatPath: () => false }));
vi.mock("$app/navigation", () => ({
  replaceState: vi.fn((url: string) => {
    const hashIndex = url.indexOf("#");
    locationMock.hash = hashIndex === -1 ? "" : url.slice(hashIndex);
  }),
}));
vi.mock("../../services/rustCore/chatState/chatListUnitClient", () => ({
  // The TypeScript plan is the parity twin of the core's plan; only the timing differs here.
  chatStateCall: (_op: string, facts: UrlPlanFacts) =>
    new Promise<UrlPlan>((resolve, reject) =>
      pendingPlans.push({ answer: () => resolve(planUrlUpdate(facts)), reject })),
}));

async function loadRustStore() {
  vi.resetModules();
  return await import("../activeChatStore");
}

/** Lets the core answer the oldest outstanding plan. */
async function answerNextPlan() {
  await vi.waitFor(() => expect(pendingPlans.length).toBeGreaterThan(0));
  pendingPlans.shift()!.answer();
}

describe("activeChatStore with the Rust URL plan", () => {
  beforeEach(() => {
    vi.stubEnv("VITE_OPENMATES_RUST_CORE", "1");
    pendingPlans.length = 0;
    locationMock.hash = "";
    locationMock.pathname = "/";
    locationMock.search = "";
  });

  afterEach(() => vi.unstubAllEnvs());

  // contract-test: supporting surface=gui.web assertions=chat-navigation.draft-only.addressable
  it("does not report the closed chat while its hash is still in the address bar", async () => {
    locationMock.hash = "#chat-id=draft-chat";
    const { activeChatStore, activeChatUrlRevision } = await loadRustStore();
    expect(activeChatStore.getChatIdFromHash()).toBe("draft-chat");

    activeChatStore.clearActiveChat();
    expect(activeChatStore.get()).toBeNull();
    expect(locationMock.hash).toBe("#chat-id=draft-chat");
    expect(activeChatStore.getChatIdFromHash()).toBeNull();
    expect(get(activeChatUrlRevision)).toBe(0);

    await answerNextPlan();
    await vi.waitFor(() => expect(get(activeChatUrlRevision)).toBe(1));
    expect(locationMock.hash).toBe("");
    expect(activeChatStore.getChatIdFromHash()).toBeNull();
  });

  // contract-test: supporting surface=gui.web assertions=chat-navigation.draft-only.addressable
  it("reports the selected chat before the address bar has caught up", async () => {
    locationMock.hash = "#chat-id=chat-1";
    const { activeChatStore, activeChatUrlRevision } = await loadRustStore();

    activeChatStore.setActiveChat("chat-2");
    expect(locationMock.hash).toBe("#chat-id=chat-1");
    expect(activeChatStore.getChatIdFromHash()).toBe("chat-2");

    await answerNextPlan();
    await vi.waitFor(() => expect(get(activeChatUrlRevision)).toBe(1));
    expect(locationMock.hash).toBe("#chat-id=chat-2");
    expect(activeChatStore.getChatIdFromHash()).toBe("chat-2");
  });

  // contract-test: supporting surface=gui.web assertions=chat-navigation.draft-only.addressable
  it("follows the last selection until every queued plan is applied", async () => {
    locationMock.hash = "#chat-id=chat-1";
    const { activeChatStore, activeChatUrlRevision } = await loadRustStore();

    activeChatStore.clearActiveChat();
    activeChatStore.setActiveChat("chat-2");
    expect(activeChatStore.getChatIdFromHash()).toBe("chat-2");

    await answerNextPlan();
    await vi.waitFor(() => expect(locationMock.hash).toBe(""));
    expect(activeChatStore.getChatIdFromHash()).toBe("chat-2");
    expect(get(activeChatUrlRevision)).toBe(0);

    await answerNextPlan();
    await vi.waitFor(() => expect(get(activeChatUrlRevision)).toBe(1));
    expect(locationMock.hash).toBe("#chat-id=chat-2");
    expect(activeChatStore.getChatIdFromHash()).toBe("chat-2");
  });

  // contract-test: supporting surface=gui.web assertions=notifications.workflow-run.chat-target
  it("shows a kept Workflow completion target again once the plan is applied", async () => {
    const completionHash = "#chat-id=chat-1&message-id=message-1&delivery-id=delivery-1&workflow-id=workflow-1&run-id=run-1";
    locationMock.hash = completionHash;
    const { activeChatStore, activeChatUrlRevision } = await loadRustStore();

    activeChatStore.clearActiveChat();
    expect(activeChatStore.getChatIdFromHash()).toBeNull();

    await answerNextPlan();
    await vi.waitFor(() => expect(get(activeChatUrlRevision)).toBe(1));
    expect(locationMock.hash).toBe(completionHash);
    expect(activeChatStore.getChatIdFromHash()).toBe("chat-1");
  });

  // contract-test: supporting surface=gui.web assertions=chat-navigation.draft-only.addressable
  it("reads the real hash again when the core cannot answer", async () => {
    locationMock.hash = "#chat-id=chat-1";
    const { activeChatStore, activeChatUrlRevision } = await loadRustStore();
    const logged = vi.spyOn(console, "error").mockImplementation(() => undefined);

    activeChatStore.clearActiveChat();
    expect(activeChatStore.getChatIdFromHash()).toBeNull();
    await vi.waitFor(() => expect(pendingPlans.length).toBe(1));
    pendingPlans.shift()!.reject(new Error("shared core unavailable"));

    await vi.waitFor(() => expect(get(activeChatUrlRevision)).toBe(1));
    expect(logged).toHaveBeenCalledWith("[activeChatStore] Rust URL plan failed", expect.any(Error));
    expect(activeChatStore.getChatIdFromHash()).toBe("chat-1");
    logged.mockRestore();
  });
});
