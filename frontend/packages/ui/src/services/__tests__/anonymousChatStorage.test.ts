// frontend/packages/ui/src/services/__tests__/anonymousChatStorage.test.ts
// Unit tests for anonymous free-usage chat storage. Anonymous chats must use
// normal chat/message IndexedDB operations with per-chat keys, not a parallel
// localStorage chat database. The server receives only plaintext turn history.

import { beforeEach, describe, expect, it, vi } from "vitest";
import type { Chat, Message } from "../../types/chat";

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

const mockDbState = vi.hoisted(() => ({
  chats: new Map<string, Chat>(),
  messages: new Map<string, Message[]>(),
}));

const mockKeyState = vi.hoisted(() => ({
  hasAnonymousSession: false,
  keys: new Map<string, Uint8Array>(),
}));

const mockChatDB = vi.hoisted(() => ({
  enableSkipOrphanDetection: vi.fn(),
  disableSkipOrphanDetection: vi.fn(),
  init: vi.fn(),
  getAllChats: vi.fn(async () => Array.from(mockDbState.chats.values())),
  getChat: vi.fn(async (chatId: string) => mockDbState.chats.get(chatId) ?? null),
  getMessagesForChat: vi.fn(async (chatId: string) =>
    (mockDbState.messages.get(chatId) ?? []).map((message) => ({ ...message })),
  ),
  addChat: vi.fn(async (chat: Chat) => {
    mockDbState.chats.set(chat.chat_id, { ...chat });
  }),
  saveMessage: vi.fn(async (message: Message) => {
    const messages = mockDbState.messages.get(message.chat_id) ?? [];
    const index = messages.findIndex((candidate) => candidate.message_id === message.message_id);
    if (index >= 0) {
      messages[index] = { ...message };
    } else {
      messages.push({ ...message });
    }
    mockDbState.messages.set(message.chat_id, messages);
  }),
  deleteChat: vi.fn(async (chatId: string) => {
    mockDbState.chats.delete(chatId);
    mockDbState.messages.delete(chatId);
  }),
}));

const mockChatKeyManager = vi.hoisted(() => ({
  createKeyForNewChat: vi.fn((chatId: string) => {
    const key = new Uint8Array([1, 2, 3, chatId.length]);
    mockKeyState.keys.set(chatId, key);
    return key;
  }),
  getKeySync: vi.fn((chatId: string) => mockKeyState.keys.get(chatId) ?? null),
  getKey: vi.fn(async (chatId: string) => mockKeyState.keys.get(chatId) ?? null),
  injectKey: vi.fn((chatId: string, key: Uint8Array) => {
    mockKeyState.keys.set(chatId, key);
    return true;
  }),
}));

vi.mock("../db", () => ({ chatDB: mockChatDB }));
vi.mock("../encryption/ChatKeyManager", () => ({ chatKeyManager: mockChatKeyManager }));
vi.mock("../cryptoService", () => ({
  encryptWithChatKey: vi.fn(async (value: string) => `encrypted:${value}`),
  decryptWithChatKey: vi.fn(async (value: string) => value.replace(/^encrypted:/, "")),
}));
vi.mock("../anonymousChatKeyWrapping", () => ({
  hasAnonymousSessionKey: vi.fn(() => mockKeyState.hasAnonymousSession),
  ensureAnonymousSessionKey: vi.fn(async () => {
    mockKeyState.hasAnonymousSession = true;
  }),
  clearAnonymousSessionKey: vi.fn(() => {
    mockKeyState.hasAnonymousSession = false;
  }),
  wrapAnonymousChatKey: vi.fn(async (key: Uint8Array) => `anonymous:${Array.from(key).join(",")}`),
  unwrapAnonymousChatKey: vi.fn(async (wrapped: string | null | undefined) => {
    if (!mockKeyState.hasAnonymousSession || !wrapped?.startsWith("anonymous:")) return null;
    return new Uint8Array(wrapped.slice("anonymous:".length).split(",").map(Number));
  }),
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

function createStorageMock(): Storage {
  const values = new Map<string, string>();
  return {
    get length() {
      return values.size;
    },
    clear: vi.fn(() => values.clear()),
    getItem: vi.fn((key: string) => values.get(key) ?? null),
    key: vi.fn((index: number) => Array.from(values.keys())[index] ?? null),
    removeItem: vi.fn((key: string) => values.delete(key)),
    setItem: vi.fn((key: string, value: string) => values.set(key, value)),
  };
}

function requestBody(fetchMock: ReturnType<typeof mockAnonymousFetch>, index: number) {
  const calls = fetchMock.mock.calls as unknown as Array<[string, RequestInit]>;
  return JSON.parse(calls[index][1].body as string) as Record<string, unknown>;
}

describe("anonymousChatStorage", () => {
  beforeEach(() => {
    vi.resetModules();
    vi.restoreAllMocks();
    const localStorageMock = createStorageMock();
    const sessionStorageMock = createStorageMock();
    Object.defineProperty(globalThis, "localStorage", { value: localStorageMock, configurable: true });
    Object.defineProperty(globalThis, "sessionStorage", { value: sessionStorageMock, configurable: true });
    Object.assign(window, {
      localStorage: localStorageMock,
      sessionStorage: sessionStorageMock,
      dispatchEvent: vi.fn(),
    });
    localStorage.clear();
    sessionStorage.clear();
    mockDbState.chats.clear();
    mockDbState.messages.clear();
    mockKeyState.keys.clear();
    mockKeyState.hasAnonymousSession = false;
    let uuidCounter = 0;
    vi.spyOn(crypto, "randomUUID").mockImplementation(() => {
      uuidCounter += 1;
      return `00000000-0000-4000-8000-${String(uuidCounter).padStart(12, "0")}` as ReturnType<Crypto["randomUUID"]>;
    });
  });

  it("stores anonymous chats in normal chatDB rows, not the legacy localStorage payload", async () => {
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
    expect(localStorage.getItem("openmates_anonymous_chats_v1")).toBeNull();
    expect(mockChatDB.addChat).toHaveBeenCalled();
    const storedChat = mockDbState.chats.get(result.chat.chat_id);
    expect(storedChat?.is_anonymous).toBe(true);
    expect(storedChat?.anonymous_encrypted_chat_key).toMatch(/^anonymous:/);
    expect(storedChat?.title).toBeUndefined();
    expect(storedChat?.encrypted_title).toBe("encrypted:Hello anonymously");

    const request = requestBody(fetchMock, 0);
    expect(request.plaintext_message).toBe("Hello anonymously");
    expect(request.message_history).toEqual([]);

    vi.resetModules();
    const reloadedStorage = await loadStorage();
    const messages = await reloadedStorage.getMessagesForChat(result.chat.chat_id);
    expect(messages.map((message) => message.content)).toEqual([
      FEATURE_NOTICE,
      "Hello anonymously",
      "Hello from anonymous chat",
    ]);
  });

  it("keeps the feature notice out of anonymous request history", async () => {
    const fetchMock = mockAnonymousFetch({ messageId: "assistant-message", assistant: "First answer" });
    const storage = await loadStorage();
    const first = await storage.sendTextMessage({ markdown: "First question" });

    await storage.sendTextMessage({ markdown: "Second question", currentChatId: first.chat.chat_id });

    expect(fetchMock).toHaveBeenCalledTimes(2);
    const secondRequest = requestBody(fetchMock, 1);
    expect(secondRequest.message_history).toEqual([
      expect.objectContaining({ role: "user", content: "First question" }),
      expect.objectContaining({ role: "assistant", content: "First answer" }),
    ]);
    expect(JSON.stringify(secondRequest.message_history)).not.toContain(FEATURE_NOTICE);
  });

  it("purges anonymous chat rows when the tab session key is missing", async () => {
    mockDbState.chats.set("anonymous-stale", {
      chat_id: "anonymous-stale",
      encrypted_title: "encrypted:Stale",
      anonymous_encrypted_chat_key: "anonymous:1,2,3",
      is_anonymous: true,
      messages_v: 0,
      title_v: 1,
      last_edited_overall_timestamp: 1,
      unread_count: 0,
      created_at: 1,
      updated_at: 1,
    });
    localStorage.setItem("openmates_anonymous_chats_v1", JSON.stringify({ iv: "abc", data: "def" }));
    const storage = await loadStorage();

    await storage.init();

    expect(localStorage.getItem("openmates_anonymous_chats_v1")).toBeNull();
    expect(await storage.getAllChats()).toEqual([]);
    expect(mockDbState.chats.has("anonymous-stale")).toBe(false);
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
    const retryRequest = requestBody(fetchMock, 1);
    expect(retryRequest.message_history).toEqual([]);
  });
});
