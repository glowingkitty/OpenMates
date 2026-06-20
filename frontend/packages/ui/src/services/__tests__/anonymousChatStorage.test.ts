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

const mockChatSyncService = vi.hoisted(() => ({
  activeAITasks: new Map<string, { taskId: string; userMessageId: string }>(),
  dispatchEvent: vi.fn((_event: Event) => true),
}));

const mockAiTypingStore = vi.hoisted(() => ({
  setTyping: vi.fn(),
  clearTyping: vi.fn(),
  clearTypingForChat: vi.fn(),
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
vi.mock("../chatSyncService", () => ({ chatSyncService: mockChatSyncService }));
vi.mock("../../stores/aiTypingStore", () => ({ aiTypingStore: mockAiTypingStore }));
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
    headers: new Headers({ "content-type": "application/json" }),
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
    mockChatSyncService.activeAITasks.clear();
    mockChatSyncService.dispatchEvent.mockClear();
    mockAiTypingStore.setTyping.mockClear();
    mockAiTypingStore.clearTyping.mockClear();
    mockAiTypingStore.clearTypingForChat.mockClear();
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
      category: "general_knowledge",
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

  it("keeps the user message when the API echoes the client message ID", async () => {
    const storage = await loadStorage();
    const firstResponse = vi.fn(async (_url: string, init: RequestInit) => {
      const request = JSON.parse(init.body as string) as Record<string, unknown>;
      return {
        ok: true,
        status: 200,
        headers: new Headers({ "content-type": "application/json" }),
        json: async () => ({
          messageId: request.client_message_id,
          assistant: "Echoed ID answer",
          category: "general_knowledge",
          modelName: "test-model",
        }),
      };
    });
    vi.stubGlobal("fetch", firstResponse);

    const result = await storage.sendTextMessage({ markdown: "Question with echoed id" });
    const messages = await storage.getMessagesForChat(result.chat.chat_id);

    expect(messages.map((message) => message.role)).toEqual(["system", "user", "assistant"]);
    expect(messages.find((message) => message.role === "user")?.content).toBe("Question with echoed id");
    expect(messages.find((message) => message.role === "assistant")?.content).toBe("Echoed ID answer");
    expect(messages.find((message) => message.role === "assistant")?.message_id).not.toBe(
      messages.find((message) => message.role === "user")?.message_id,
    );
  });

  it("emits the regular chat sync streaming lifecycle for anonymous responses", async () => {
    mockAnonymousFetch({
      messageId: "assistant-message",
      assistant: "Streaming anonymous answer",
      category: "general_knowledge",
      modelName: "test-model",
    });
    const storage = await loadStorage();

    await storage.sendTextMessage({ markdown: "Use the normal pipeline" });

    const events = mockChatSyncService.dispatchEvent.mock.calls.map(([event]) => event as CustomEvent);
    expect(events.map((event) => event.type)).toEqual(
      expect.arrayContaining(["aiTaskInitiated", "chatUpdated", "aiTypingStarted", "aiMessageChunk"]),
    );

    const taskEvent = events.find((event) => event.type === "aiTaskInitiated");
    expect(taskEvent?.detail).toEqual(expect.objectContaining({ status: "processing_started" }));

    const typingEvent = events.find((event) => event.type === "aiTypingStarted");
    expect(typingEvent?.detail).toEqual(expect.objectContaining({
      message_id: "assistant-message",
      category: "general_knowledge",
      model_name: "test-model",
    }));
    expect(mockAiTypingStore.setTyping).toHaveBeenCalledWith(
      expect.stringMatching(/^anonymous-/),
      expect.any(String),
      "assistant-message",
      "general_knowledge",
      "test-model",
      null,
      null,
      ["sparkles"],
    );

    const chunkEvents = events.filter((event) => event.type === "aiMessageChunk");
    expect(chunkEvents.length).toBeGreaterThanOrEqual(1);
    expect(chunkEvents[chunkEvents.length - 1]?.detail).toEqual(expect.objectContaining({
      type: "ai_message_chunk",
      message_id: "assistant-message",
      full_content_so_far: "Streaming anonymous answer",
      is_final_chunk: true,
      model_name: "test-model",
    }));
    expect(mockAiTypingStore.clearTypingForChat).toHaveBeenCalledWith(expect.stringMatching(/^anonymous-/));
  });

  it("orders same-second anonymous request history by conversation turn", async () => {
    const fetchMock = mockAnonymousFetch({ messageId: "assistant-message", assistant: "First answer" });
    const storage = await loadStorage();
    const first = await storage.sendTextMessage({ markdown: "First question" });
    const storedMessages = mockDbState.messages.get(first.chat.chat_id) ?? [];
    const systemMessage = storedMessages.find((message) => message.role === "system");
    const userMessage = storedMessages.find((message) => message.role === "user");
    const assistantMessage = storedMessages.find((message) => message.role === "assistant");
    expect(systemMessage).toBeTruthy();
    expect(userMessage).toBeTruthy();
    expect(assistantMessage).toBeTruthy();
    mockDbState.messages.set(first.chat.chat_id, [assistantMessage!, userMessage!, systemMessage!]);

    await storage.sendTextMessage({ markdown: "Second question", currentChatId: first.chat.chat_id });

    const secondRequest = requestBody(fetchMock, 1);
    expect(secondRequest.message_history).toEqual([
      expect.objectContaining({ role: "user", content: "First question" }),
      expect.objectContaining({ role: "assistant", content: "First answer" }),
    ]);
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
      headers: new Headers({ "content-type": "application/json" }),
      json: async () => ({ messageId: "assistant-after-failure", assistant: "Recovered" }),
    });
    await storage.sendTextMessage({ markdown: "Try again", currentChatId: chat.chat_id });
    const retryRequest = requestBody(fetchMock, 1);
    expect(retryRequest.message_history).toEqual([]);
  });
});
