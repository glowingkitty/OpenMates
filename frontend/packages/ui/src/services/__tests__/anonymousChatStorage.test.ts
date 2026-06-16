// frontend/packages/ui/src/services/__tests__/anonymousChatStorage.test.ts
// Unit tests for anonymous free-usage chat local storage.
// Anonymous chats are privacy-sensitive because logged-out text must stay local,
// encrypted in localStorage, and recover only while the tab session key exists.
// The server receives only the current plaintext turn and local message history.

import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("../../config/api", () => ({
  getApiEndpoint: (path: string) => `https://api.test${path}`,
}));

const FEATURE_NOTICE = "You are using free anonymous credits.";

vi.mock("../../i18n/translations", () => ({
  text: {
    subscribe: (run: (translate: (key: string) => string) => void) => {
      run((key: string) => key === "chat.anonymous_free_usage.feature_notice" ? FEATURE_NOTICE : `[T:${key}]`);
      return () => undefined;
    },
  },
}));

async function loadStorage() {
  const module = await import("../anonymousChatStorage");
  return module.anonymousChatStorage;
}

function mockAnonymousFetch(response: Record<string, unknown>, ok = true, status = 200) {
  const fetchMock = vi.fn(async () => ({
    ok,
    status,
    json: async () => response,
  }));
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

describe("anonymousChatStorage", () => {
  beforeEach(() => {
    vi.resetModules();
    vi.restoreAllMocks();
    localStorage.clear();
    sessionStorage.clear();
  });

  it("encrypts anonymous chats locally and reloads them while the session key exists", async () => {
    const fetchMock = mockAnonymousFetch({
      messageId: "assistant-message",
      assistant: "Hello from anonymous chat",
      category: "ai",
      modelName: "test-model",
    });
    const storage = await loadStorage();

    const result = await storage.sendTextMessage({ markdown: "Hello anonymously" });

    expect(result.chat.is_anonymous).toBe(true);
    expect(result.assistantMessage.content).toBe("Hello from anonymous chat");
    expect(fetchMock).toHaveBeenCalledTimes(1);
    const request = JSON.parse((fetchMock.mock.calls[0][1] as RequestInit).body as string);
    expect(request.plaintext_message).toBe("Hello anonymously");
    expect(request.message_history).toEqual([]);

    const encryptedPayload = localStorage.getItem("openmates_anonymous_chats_v1");
    expect(encryptedPayload).toBeTruthy();
    expect(encryptedPayload).not.toContain("Hello anonymously");
    expect(encryptedPayload).not.toContain("Hello from anonymous chat");
    expect(encryptedPayload).not.toContain(FEATURE_NOTICE);

    vi.resetModules();
    const reloadedStorage = await loadStorage();
    const messages = await reloadedStorage.getMessagesForChat(result.chat.chat_id);
    expect(messages.map((message) => message.content)).toEqual([
      FEATURE_NOTICE,
      "Hello anonymously",
      "Hello from anonymous chat",
    ]);
    expect(messages[0].role).toBe("system");
  });

  it("keeps the feature notice out of anonymous request history", async () => {
    const fetchMock = mockAnonymousFetch({ messageId: "assistant-message", assistant: "First answer" });
    const storage = await loadStorage();
    const first = await storage.sendTextMessage({ markdown: "First question" });

    await storage.sendTextMessage({ markdown: "Second question", currentChatId: first.chat.chat_id });

    expect(fetchMock).toHaveBeenCalledTimes(2);
    const secondRequest = JSON.parse((fetchMock.mock.calls[1][1] as RequestInit).body as string);
    expect(secondRequest.message_history).toEqual([
      expect.objectContaining({ role: "user", content: "First question" }),
      expect.objectContaining({ role: "assistant", content: "First answer" }),
    ]);
    expect(JSON.stringify(secondRequest.message_history)).not.toContain(FEATURE_NOTICE);
  });

  it("purges anonymous ciphertext when the tab session key is missing", async () => {
    localStorage.setItem("openmates_anonymous_chats_v1", JSON.stringify({ iv: "abc", data: "def" }));
    const storage = await loadStorage();

    await storage.init();

    expect(localStorage.getItem("openmates_anonymous_chats_v1")).toBeNull();
    expect(await storage.getAllChats()).toEqual([]);
  });

  it("marks the local user message failed when the anonymous request is rejected", async () => {
    const fetchMock = mockAnonymousFetch({ detail: { message: "Create an account to keep using OpenMates." } }, false, 429);
    const storage = await loadStorage();

    await expect(storage.sendTextMessage({ markdown: "Try anonymous chat" })).rejects.toThrow(
      "Create an account to keep using OpenMates.",
    );

    const [chat] = await storage.getAllChats();
    const messages = await storage.getMessagesForChat(chat.chat_id);
    expect(messages).toHaveLength(2);
    expect(messages[0].role).toBe("system");
    expect(messages[1].content).toBe("Try anonymous chat");
    expect(messages[1].status).toBe("failed");

    fetchMock.mockResolvedValueOnce({
      ok: true,
      status: 200,
      json: async () => ({ messageId: "assistant-after-failure", assistant: "Recovered" }),
    });
    await storage.sendTextMessage({ markdown: "Try again", currentChatId: chat.chat_id });
    const retryRequest = JSON.parse((fetchMock.mock.calls[1][1] as RequestInit).body as string);
    expect(retryRequest.message_history).toEqual([]);
  });
});
