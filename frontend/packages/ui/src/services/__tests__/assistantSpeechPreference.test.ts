// frontend/packages/ui/src/services/__tests__/assistantSpeechPreference.test.ts
// Contract coverage for voice preference persistence around new-chat creation.
// Draft-only chats keep local intent until a wrapped chat key exists, while
// durable metadata writes carry that key so first-message processing can decrypt.
// Product implementation: frontend/packages/ui/src/services/assistantSpeechPreference.ts

import { beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({
  chatDB: {
    getChat: vi.fn(),
    updateChat: vi.fn(),
  },
  chatKeyManager: {
    getKey: vi.fn(),
  },
  decryptWithChatKey: vi.fn(),
  encryptWithChatKey: vi.fn(),
  handlers: new Map<string, (payload: unknown) => void>(),
  webSocketService: {
    on: vi.fn((type: string, handler: (payload: unknown) => void) => {
      mocks.handlers.set(type, handler);
    }),
    off: vi.fn((type: string) => {
      mocks.handlers.delete(type);
    }),
    sendMessage: vi.fn(),
  },
}));

vi.mock("../db", () => ({ chatDB: mocks.chatDB }));
vi.mock("../encryption/ChatKeyManager", () => ({ chatKeyManager: mocks.chatKeyManager }));
vi.mock("../encryption/MessageEncryptor", () => ({
  decryptWithChatKey: mocks.decryptWithChatKey,
  encryptWithChatKey: mocks.encryptWithChatKey,
}));
vi.mock("../websocketService", () => ({ webSocketService: mocks.webSocketService }));

import {
  getAssistantSpeechPreference,
  setAssistantSpeechPreference,
} from "../assistantSpeechPreference";

describe("assistant speech preference", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mocks.handlers.clear();
    mocks.chatDB.updateChat.mockResolvedValue(undefined);
    mocks.chatKeyManager.getKey.mockResolvedValue(new Uint8Array([1, 2, 3]));
    mocks.encryptWithChatKey.mockResolvedValue("encrypted-preference");
    mocks.webSocketService.sendMessage.mockImplementation(async () => {
      mocks.handlers.get("encrypted_metadata_stored")?.({
        chat_id: "chat-1",
        versions: { metadata_v: 1 },
      });
    });
  });

  // contract-test: direct surface=gui.web assertions=assistant-speech.preference.chat-scoped-default-off
  it("keeps voice intent local for a draft-only chat without a wrapped key", async () => {
    mocks.chatDB.getChat.mockResolvedValue({
      chat_id: "chat-1",
      messages_v: 0,
      encrypted_chat_key: null,
      encrypted_auto_speak_response: null,
    });

    await setAssistantSpeechPreference("chat-1", true);

    expect(mocks.chatKeyManager.getKey).not.toHaveBeenCalled();
    expect(mocks.webSocketService.sendMessage).not.toHaveBeenCalled();
    await expect(getAssistantSpeechPreference("chat-1")).resolves.toBe(true);
  });

  // contract-test: direct surface=gui.web assertions=assistant-speech.preference.chat-scoped-default-off
  it("includes the wrapped chat key in the first durable preference write", async () => {
    mocks.chatDB.getChat.mockResolvedValue({
      chat_id: "chat-1",
      messages_v: 1,
      title_v: 0,
      metadata_v: 0,
      last_edited_overall_timestamp: 1,
      encrypted_chat_key: "wrapped-chat-key",
      encrypted_auto_speak_response: null,
    });

    await setAssistantSpeechPreference("chat-1", true);

    expect(mocks.webSocketService.sendMessage).toHaveBeenCalledWith(
      "encrypted_chat_metadata",
      expect.objectContaining({
        chat_id: "chat-1",
        encrypted_chat_key: "wrapped-chat-key",
        encrypted_auto_speak_response: "encrypted-preference",
      }),
    );
  });
});
