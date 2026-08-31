// frontend/packages/ui/src/services/__tests__/chatModelSelection.test.ts
// Contract tests for encrypted, owner-scoped chat model selections.
// Durable records must contain only Format D ciphertext, while the service keeps
// versioned local-first state per user and chat. The tests use injected adapters
// so they define the service boundary without depending on browser storage.
// Architecture: contracts/features/ai-model-routing/contract.yml

import { describe, expect, it, vi } from "vitest";

import { createChatModelSelectionService } from "../chatModelSelection";

const ALICE = "alice";
const BOB = "bob";
const CHAT_ID = "shared-chat";
const FLASH_MODEL = "google/gemini-3.7-flash";
const SONNET_MODEL = "anthropic/claude-sonnet-5";
const FLASH_MODEL_PAYLOAD = JSON.stringify({ mode: "exact", model: FLASH_MODEL });

type EncryptedSelection = {
  ciphertext: string;
  version: number;
};

function createAdapters(shared?: {
  ciphertexts: Map<string, string>;
  remote: Map<string, EncryptedSelection>;
}) {
  const local = new Map<string, EncryptedSelection>();
  const remote = shared?.remote ?? new Map<string, EncryptedSelection>();
  const ciphertexts = shared?.ciphertexts ?? new Map<string, string>();
  const key = (userId: string, chatId: string) => `${userId}:${chatId}`;
  const encrypt = vi.fn(async (plaintext: string) => {
    const ciphertext = `format-d-ciphertext-${ciphertexts.size + 1}`;
    ciphertexts.set(ciphertext, plaintext);
    return ciphertext;
  });
  const decrypt = vi.fn(async (ciphertext: string) => ciphertexts.get(ciphertext) ?? null);
  const writeLocal = vi.fn(async (userId: string, chatId: string, record: EncryptedSelection) => {
    local.set(key(userId, chatId), record);
  });
  const readLocal = vi.fn(async (userId: string, chatId: string) => local.get(key(userId, chatId)) ?? null);
  const compareAndSetRemote = vi.fn(async (
    userId: string,
    chatId: string,
    expectedVersion: number,
    record: EncryptedSelection,
  ) => {
    const current = remote.get(key(userId, chatId));
    if ((current?.version ?? 0) !== expectedVersion) return null;
    remote.set(key(userId, chatId), record);
    return record;
  });
  const readRemote = vi.fn(async (userId: string, chatId: string) => remote.get(key(userId, chatId)) ?? null);

  return {
    encryption: { encrypt, decrypt },
    local: { read: readLocal, write: writeLocal },
    remote: { read: readRemote, compareAndSet: compareAndSetRemote },
    calls: { encrypt, decrypt, readLocal, writeLocal, readRemote, compareAndSetRemote },
    shared: { ciphertexts, remote },
  };
}

describe("chat model selection", () => {
  // contract-test: direct surface=gui.web assertions=ai-model-routing.chat-selection.encrypted-user-chat-scope
  it("writes Format D ciphertext to versioned local state before owner/chat CAS sync", async () => {
    const adapters = createAdapters();
    const selections = createChatModelSelectionService(adapters);

    await selections.select({ userId: ALICE, chatId: CHAT_ID, selection: FLASH_MODEL });

    expect(adapters.calls.encrypt).toHaveBeenCalledWith(FLASH_MODEL_PAYLOAD);
    expect(adapters.calls.writeLocal).toHaveBeenCalledWith(ALICE, CHAT_ID, {
      ciphertext: "format-d-ciphertext-1",
      version: 1,
    });
    expect(adapters.calls.compareAndSetRemote).toHaveBeenCalledWith(ALICE, CHAT_ID, 0, {
      ciphertext: "format-d-ciphertext-1",
      version: 1,
    });
    expect(adapters.calls.writeLocal.mock.invocationCallOrder[0]).toBeLessThan(
      adapters.calls.compareAndSetRemote.mock.invocationCallOrder[0],
    );
    expect(JSON.stringify(adapters.calls.compareAndSetRemote.mock.calls)).not.toContain(FLASH_MODEL);
  });

  // contract-test: direct surface=gui.web assertions=ai-model-routing.chat-selection.encrypted-user-chat-scope
  it("restores an owner selection on another device without exposing it to another participant", async () => {
    const deviceAAdapters = createAdapters();
    const deviceBAdapters = createAdapters(deviceAAdapters.shared);
    const deviceA = createChatModelSelectionService(deviceAAdapters);
    const deviceB = createChatModelSelectionService(deviceBAdapters);

    await deviceA.select({ userId: ALICE, chatId: CHAT_ID, selection: SONNET_MODEL });

    await expect(deviceB.restore({ userId: ALICE, chatId: CHAT_ID })).resolves.toBe(SONNET_MODEL);
    await expect(deviceB.restore({ userId: BOB, chatId: CHAT_ID })).resolves.toBe("auto");
    expect(deviceBAdapters.calls.readLocal).toHaveBeenCalledWith(ALICE, CHAT_ID);
    expect(deviceBAdapters.calls.readRemote).toHaveBeenCalledWith(ALICE, CHAT_ID);
    expect(deviceBAdapters.calls.readRemote).toHaveBeenCalledWith(BOB, CHAT_ID);
  });

  // contract-test: direct surface=gui.web assertions=ai-model-routing.chat-selection.encrypted-user-chat-scope
  it("retries a fresh-device selection against the current remote version", async () => {
    const deviceAAdapters = createAdapters();
    const deviceBAdapters = createAdapters(deviceAAdapters.shared);
    const deviceA = createChatModelSelectionService(deviceAAdapters);
    const deviceB = createChatModelSelectionService(deviceBAdapters);

    await deviceA.select({ userId: ALICE, chatId: CHAT_ID, selection: SONNET_MODEL });

    await expect(deviceB.select({ userId: ALICE, chatId: CHAT_ID, selection: FLASH_MODEL })).resolves.toBe(FLASH_MODEL);
    await expect(deviceA.restore({ userId: ALICE, chatId: CHAT_ID })).resolves.toBe(FLASH_MODEL);
    expect(deviceBAdapters.calls.compareAndSetRemote).toHaveBeenNthCalledWith(1, ALICE, CHAT_ID, 0, {
      ciphertext: "format-d-ciphertext-2",
      version: 1,
    });
    expect(deviceBAdapters.calls.compareAndSetRemote).toHaveBeenNthCalledWith(2, ALICE, CHAT_ID, 1, {
      ciphertext: "format-d-ciphertext-2",
      version: 2,
    });
  });

  // contract-test: direct surface=gui.web assertions=ai-model-routing.chat-selection.encrypted-user-chat-scope
  it("keeps an exact chat selection when the send path reads it", async () => {
    const adapters = createAdapters();
    const selections = createChatModelSelectionService(adapters);

    await selections.select({ userId: ALICE, chatId: CHAT_ID, selection: FLASH_MODEL });

    expect(selections.selectionForSend({ userId: ALICE, chatId: CHAT_ID })).toBe(FLASH_MODEL);
    expect(selections.selectionForSend({ userId: ALICE, chatId: CHAT_ID })).toBe(FLASH_MODEL);
  });
});
