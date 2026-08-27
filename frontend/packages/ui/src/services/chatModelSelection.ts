// frontend/packages/ui/src/services/chatModelSelection.ts
// Local-first chat model selection service for the AI routing contract.
// The service keeps decrypted values in memory only, writes encrypted records
// before remote sync, and scopes every operation to an authenticated user/chat.
// Architecture: contracts/features/ai-model-routing/contract.yml

const AUTO_SELECTION = "auto";

export type ChatModelSelection = typeof AUTO_SELECTION | (string & {});

export type EncryptedChatModelSelection = {
  ciphertext: string;
  version: number;
};

type SerializedChatModelSelection =
  | { mode: "auto" }
  | { mode: "exact"; model: string };

export type ChatModelSelectionAdapters = {
  encryption: {
    encrypt: (plaintext: string) => Promise<string>;
    decrypt: (ciphertext: string) => Promise<string | null>;
  };
  local: {
    read: (
      userId: string,
      chatId: string,
    ) => Promise<EncryptedChatModelSelection | null>;
    write: (
      userId: string,
      chatId: string,
      record: EncryptedChatModelSelection,
    ) => Promise<void>;
  };
  remote: {
    read: (
      userId: string,
      chatId: string,
    ) => Promise<EncryptedChatModelSelection | null>;
    compareAndSet: (
      userId: string,
      chatId: string,
      expectedVersion: number,
      record: EncryptedChatModelSelection,
    ) => Promise<EncryptedChatModelSelection | null>;
  };
};

export type ChatModelSelectionService = {
  select: (request: {
    userId: string;
    chatId: string;
    selection: ChatModelSelection;
  }) => Promise<ChatModelSelection>;
  restore: (request: {
    userId: string;
    chatId: string;
  }) => Promise<ChatModelSelection>;
  selectionForSend: (request: {
    userId: string;
    chatId: string;
  }) => ChatModelSelection;
};

function selectionKey(userId: string, chatId: string): string {
  return `${userId}:${chatId}`;
}

function serializeSelection(selection: ChatModelSelection): string {
  const payload: SerializedChatModelSelection =
    selection === AUTO_SELECTION
      ? { mode: "auto" }
      : { mode: "exact", model: selection };
  return JSON.stringify(payload);
}

function parseSelection(plaintext: string): ChatModelSelection {
  let payload: unknown;
  try {
    payload = JSON.parse(plaintext);
  } catch {
    throw new Error("Chat model selection payload is not valid JSON");
  }

  if (
    typeof payload === "object" &&
    payload !== null &&
    "mode" in payload &&
    payload.mode === "auto"
  ) {
    return AUTO_SELECTION;
  }

  if (
    typeof payload === "object" &&
    payload !== null &&
    "mode" in payload &&
    payload.mode === "exact" &&
    "model" in payload &&
    typeof payload.model === "string" &&
    payload.model.length > 0
  ) {
    return payload.model;
  }

  throw new Error("Chat model selection payload has an invalid shape");
}

async function decryptRecord(
  adapters: ChatModelSelectionAdapters,
  record: EncryptedChatModelSelection,
): Promise<ChatModelSelection> {
  const plaintext = await adapters.encryption.decrypt(record.ciphertext);
  if (plaintext === null) {
    throw new Error("Chat model selection ciphertext could not be decrypted");
  }
  return parseSelection(plaintext);
}

export function createChatModelSelectionService(
  adapters: ChatModelSelectionAdapters,
): ChatModelSelectionService {
  const selections = new Map<string, ChatModelSelection>();

  return {
    async select({ userId, chatId, selection }) {
      const current = await adapters.local.read(userId, chatId);
      const expectedVersion = current?.version ?? 0;
      const ciphertext = await adapters.encryption.encrypt(
        serializeSelection(selection),
      );
      const record = { ciphertext, version: expectedVersion + 1 };
      const key = selectionKey(userId, chatId);

      selections.set(key, selection);
      await adapters.local.write(userId, chatId, record);

      const accepted = await adapters.remote.compareAndSet(
        userId,
        chatId,
        expectedVersion,
        record,
      );
      if (accepted) return selection;

      const remoteRecord = await adapters.remote.read(userId, chatId);
      if (!remoteRecord) {
        throw new Error("Chat model selection sync conflict could not be reconciled");
      }

      const remoteSelection = await decryptRecord(adapters, remoteRecord);
      selections.set(key, remoteSelection);
      await adapters.local.write(userId, chatId, remoteRecord);
      return remoteSelection;
    },

    async restore({ userId, chatId }) {
      const key = selectionKey(userId, chatId);
      const localRecord = await adapters.local.read(userId, chatId);
      if (localRecord) {
        const selection = await decryptRecord(adapters, localRecord);
        selections.set(key, selection);
        return selection;
      }

      const remoteRecord = await adapters.remote.read(userId, chatId);
      if (!remoteRecord) {
        selections.set(key, AUTO_SELECTION);
        return AUTO_SELECTION;
      }

      const selection = await decryptRecord(adapters, remoteRecord);
      selections.set(key, selection);
      await adapters.local.write(userId, chatId, remoteRecord);
      return selection;
    },

    selectionForSend({ userId, chatId }) {
      return selections.get(selectionKey(userId, chatId)) ?? AUTO_SELECTION;
    },
  };
}
