// A failed decryption belongs to one stored ciphertext, never to a message id.
//
// Regression (Flow 2 web proof): a streamed assistant reply was first stored with
// empty content; its empty plaintext was read as a failure and cached under the
// message id. Every later read of the finished reply, rewritten under the same id,
// returned "[Content decryption failed]", and the next turn sent that placeholder
// to the AI as the assistant's previous reply.

import { beforeEach, describe, expect, it, vi } from "vitest";

const plaintexts = new Map<string, string | null>();

vi.mock("../../cryptoService", () => ({
  base64ToUint8Array: vi.fn(),
  encryptWithChatKey: vi.fn(),
  decryptChatKeyWithMasterKey: vi.fn(),
  decryptWithChatKey: vi.fn(async (ciphertext: string) => plaintexts.get(ciphertext) ?? null),
}));

vi.mock("../../encryption/ChatKeyManager", () => ({
  chatKeyManager: {
    getKey: vi.fn(async () => new Uint8Array(32)),
    getProvenance: vi.fn(() => ({ source: "test", keyFingerprint: "fp-test", timestamp: 0 })),
    getState: vi.fn(() => "ready"),
  },
}));

import { decryptMessageFields } from "../chatKeyManagement";
import { clearDecryptionFailureCache } from "../decryptionFailureCache";
import type { Message } from "../../../types/chat";

const CHAT = "chat-garden";
const db = {} as Parameters<typeof decryptMessageFields>[0];

function storedReply(ciphertext: string): Message {
  return {
    message_id: "reply-1",
    chat_id: CHAT,
    role: "assistant",
    status: "synced",
    created_at: 1,
    encrypted_content: ciphertext,
  } as Message;
}

describe("decryptMessageFields failure cache", () => {
  beforeEach(() => {
    plaintexts.clear();
    clearDecryptionFailureCache();
  });

  // contract-test: supporting surface=gui.web assertions=chats.local-state.precedence
  it("reads an empty reply as empty content, not as a failure", async () => {
    plaintexts.set("cipher-empty-AAAAAAAAAAAAAAAAAAAAAAAA", "");
    const first = await decryptMessageFields(db, storedReply("cipher-empty-AAAAAAAAAAAAAAAAAAAAAAAA"), CHAT);
    expect(first.content).toBe("");

    plaintexts.set("cipher-full-BBBBBBBBBBBBBBBBBBBBBBBBB", "Here is the scope summary for the harvest log.");
    const finished = await decryptMessageFields(db, storedReply("cipher-full-BBBBBBBBBBBBBBBBBBBBBBBBB"), CHAT);
    expect(finished.content).toBe("Here is the scope summary for the harvest log.");
  });

  // contract-test: supporting surface=gui.web assertions=chats.local-state.precedence
  it("decrypts a rewritten row again after an earlier ciphertext failed", async () => {
    const broken = await decryptMessageFields(db, storedReply("cipher-broken-CCCCCCCCCCCCCCCCCCCCCCC"), CHAT);
    expect(broken.content).toBe("[Content decryption failed]");

    plaintexts.set("cipher-final-DDDDDDDDDDDDDDDDDDDDDDDD", "Final reply with the Specification.");
    const rewritten = await decryptMessageFields(db, storedReply("cipher-final-DDDDDDDDDDDDDDDDDDDDDDDD"), CHAT);
    expect(rewritten.content).toBe("Final reply with the Specification.");

    // The broken ciphertext itself stays cached as failed.
    plaintexts.set("cipher-broken-CCCCCCCCCCCCCCCCCCCCCCC", "should not be retried");
    const again = await decryptMessageFields(db, storedReply("cipher-broken-CCCCCCCCCCCCCCCCCCCCCCC"), CHAT);
    expect(again.content).toBe("[Content decryption failed]");
  });
});
