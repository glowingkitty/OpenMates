import { webcrypto } from "node:crypto";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { Message } from "../../../types/chat";

vi.mock("../../cryptoService", () => ({
  base64ToUint8Array: (value: string) => Uint8Array.from(atob(value), c => c.charCodeAt(0)),
  uint8ArrayToBase64: (value: Uint8Array) => btoa(String.fromCharCode(...value)),
  encryptWithChatKey: async (value: string, key: Uint8Array) =>
    (await import("../../encryption/MessageEncryptor")).encryptWithChatKey(value, key),
}));
vi.mock("../../encryption/ChatKeyManager", () => ({
  chatKeyManager: { getKeySync: () => new Uint8Array(32).fill(7) },
}));
import { encryptMessageFields, getEncryptedFields } from "../chatKeyManagement";
import { decryptWithChatKey } from "../../encryption/MessageEncryptor";

const db = { db: null, CHATS_STORE_NAME: "chats", getChat: async () => null };

describe("empty interrupted reply encryption", () => {
  beforeEach(() => vi.stubGlobal("crypto", webcrypto));
  afterEach(() => vi.unstubAllGlobals());

  // contract-test: supporting surface=gui.web assertions=chats.completion.lease-fenced,chat-processing-feedback.turn-lifecycle
  it.each([getEncryptedFields, encryptMessageFields])("encrypts empty content for canonical and local persistence", async encrypt => {
    const message = { content: "", role: "assistant" } as Message;
    const encrypted = await encrypt(db, message, "private-chat");
    expect(encrypted.encrypted_content).toBeTruthy();
    expect(await decryptWithChatKey(encrypted.encrypted_content!, new Uint8Array(32).fill(7))).toBe("");
    expect(encrypted).not.toHaveProperty("content");
    expect(message.content).toBe("");
  });

  // contract-test: supporting surface=gui.web assertions=chats.completion.lease-fenced
  it.each([undefined, null])("keeps absent content absent: %s", async content => {
    const message = { content, role: "assistant" } as Message;
    expect(await getEncryptedFields(db, message, "private-chat")).not.toHaveProperty("encrypted_content");
    expect(await encryptMessageFields(db, message, "private-chat")).not.toHaveProperty("encrypted_content");
  });
});
