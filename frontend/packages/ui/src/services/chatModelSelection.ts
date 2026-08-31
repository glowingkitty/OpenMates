// frontend/packages/ui/src/services/chatModelSelection.ts
// Local-first chat model selection service for the AI routing contract.
// The service keeps decrypted values in memory only, writes encrypted records
// before remote sync, and scopes every operation to an authenticated user/chat.
// Architecture: contracts/features/ai-model-routing/contract.yml

import {
  decryptWithMasterKey,
  encryptWithMasterKey,
} from "./encryption/MetadataEncryptor";
import { webSocketService } from "./websocketService";

const AUTO_SELECTION = "auto";
const DATABASE_NAME = "openmates-chat-model-selections";
const DATABASE_VERSION = 1;
const STORE_NAME = "selections";
const REMOTE_REQUEST_TIMEOUT_MS = 10_000;

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
  receiveRemote: (request: {
    userId: string;
    chatId: string;
    record: EncryptedChatModelSelection;
  }) => Promise<ChatModelSelection>;
};

type StoredChatModelSelection = EncryptedChatModelSelection & {
  key: string;
  userId: string;
  chatId: string;
};

type PreferenceRecordPayload = {
  encrypted_selected_ai_model?: unknown;
  preference_v?: unknown;
};

type PreferenceResponsePayload = {
  chat_id?: unknown;
  preference?: PreferenceRecordPayload | null;
};

function selectionKey(userId: string, chatId: string): string {
  return `${userId}:${chatId}`;
}

function parseEncryptedRecord(
  payload: PreferenceRecordPayload | null | undefined,
): EncryptedChatModelSelection | null {
  if (!payload) return null;
  if (
    typeof payload.encrypted_selected_ai_model !== "string" ||
    typeof payload.preference_v !== "number"
  ) {
    throw new Error("Chat model selection response has an invalid shape");
  }
  return {
    ciphertext: payload.encrypted_selected_ai_model,
    version: payload.preference_v,
  };
}

function openSelectionDatabase(): Promise<IDBDatabase> {
  if (typeof indexedDB === "undefined") {
    return Promise.reject(new Error("IndexedDB is unavailable"));
  }

  return new Promise((resolve, reject) => {
    const request = indexedDB.open(DATABASE_NAME, DATABASE_VERSION);
    request.onupgradeneeded = () => {
      if (!request.result.objectStoreNames.contains(STORE_NAME)) {
        request.result.createObjectStore(STORE_NAME, { keyPath: "key" });
      }
    };
    request.onsuccess = () => resolve(request.result);
    request.onerror = () => reject(request.error ?? new Error("Could not open chat model selection database"));
  });
}

async function readLocalSelection(
  userId: string,
  chatId: string,
): Promise<EncryptedChatModelSelection | null> {
  const database = await openSelectionDatabase();
  try {
    return await new Promise((resolve, reject) => {
      const request = database
        .transaction(STORE_NAME, "readonly")
        .objectStore(STORE_NAME)
        .get(selectionKey(userId, chatId));
      request.onsuccess = () => {
        const stored = request.result as StoredChatModelSelection | undefined;
        resolve(stored ? { ciphertext: stored.ciphertext, version: stored.version } : null);
      };
      request.onerror = () => reject(request.error ?? new Error("Could not read chat model selection"));
    });
  } finally {
    database.close();
  }
}

async function writeLocalSelection(
  userId: string,
  chatId: string,
  record: EncryptedChatModelSelection,
): Promise<void> {
  const database = await openSelectionDatabase();
  try {
    await new Promise<void>((resolve, reject) => {
      const request = database
        .transaction(STORE_NAME, "readwrite")
        .objectStore(STORE_NAME)
        .put({ ...record, key: selectionKey(userId, chatId), userId, chatId });
      request.onsuccess = () => resolve();
      request.onerror = () => reject(request.error ?? new Error("Could not store chat model selection"));
    });
  } finally {
    database.close();
  }
}

function requestRemoteSelection(
  chatId: string,
  requestType: "get_chat_model_preference" | "update_chat_model_preference",
  requestPayload: Record<string, unknown>,
): Promise<EncryptedChatModelSelection | null> {
  return new Promise((resolve, reject) => {
    let settled = false;
    const finish = (
      result: EncryptedChatModelSelection | null,
      error?: Error,
    ) => {
      if (settled) return;
      settled = true;
      clearTimeout(timeout);
      webSocketService.off("chat_model_preference", handlePreference);
      webSocketService.off("chat_model_preference_updated", handlePreference);
      webSocketService.off("chat_model_preference_conflict", handleConflict);
      webSocketService.off("error", handleError);
      if (error) reject(error);
      else resolve(result);
    };
    const matchesChat = (payload: PreferenceResponsePayload) => payload.chat_id === chatId;
    const handlePreference = (payload: PreferenceResponsePayload) => {
      if (!matchesChat(payload)) return;
      try {
        finish(parseEncryptedRecord(payload.preference));
      } catch (error) {
        finish(null, error instanceof Error ? error : new Error(String(error)));
      }
    };
    const handleConflict = (payload: PreferenceResponsePayload) => {
      if (matchesChat(payload)) finish(null);
    };
    const handleError = (payload: { chat_id?: unknown; code?: unknown; message?: unknown }) => {
      if (payload.chat_id !== chatId) return;
      finish(
        null,
        new Error(typeof payload.message === "string" ? payload.message : String(payload.code ?? "Chat model selection sync failed")),
      );
    };
    const timeout = setTimeout(
      () => finish(null, new Error("Chat model selection sync timed out")),
      REMOTE_REQUEST_TIMEOUT_MS,
    );

    webSocketService.on("chat_model_preference", handlePreference);
    webSocketService.on("chat_model_preference_updated", handlePreference);
    webSocketService.on("chat_model_preference_conflict", handleConflict);
    webSocketService.on("error", handleError);
    void webSocketService.sendMessage(requestType, requestPayload).catch((error) => {
      finish(null, error instanceof Error ? error : new Error(String(error)));
    });
  });
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

      const retryRecord = { ciphertext, version: remoteRecord.version + 1 };
      await adapters.local.write(userId, chatId, retryRecord);
      const retryAccepted = await adapters.remote.compareAndSet(
        userId,
        chatId,
        remoteRecord.version,
        retryRecord,
      );
      if (!retryAccepted) {
        throw new Error("Chat model selection sync conflicted repeatedly");
      }
      return selection;
    },

    async restore({ userId, chatId }) {
      const key = selectionKey(userId, chatId);
      const localRecord = await adapters.local.read(userId, chatId);
      let remoteRecord: EncryptedChatModelSelection | null = null;
      try {
        remoteRecord = await adapters.remote.read(userId, chatId);
      } catch (error) {
        if (!localRecord) throw error;
      }

      const record =
        remoteRecord && (!localRecord || remoteRecord.version > localRecord.version)
          ? remoteRecord
          : localRecord;
      if (!record) {
        selections.set(key, AUTO_SELECTION);
        return AUTO_SELECTION;
      }

      const selection = await decryptRecord(adapters, record);
      selections.set(key, selection);
      if (record === remoteRecord) {
        await adapters.local.write(userId, chatId, record);
      }
      return selection;
    },

    selectionForSend({ userId, chatId }) {
      return selections.get(selectionKey(userId, chatId)) ?? AUTO_SELECTION;
    },

    async receiveRemote({ userId, chatId, record }) {
      const selection = await decryptRecord(adapters, record);
      selections.set(selectionKey(userId, chatId), selection);
      await adapters.local.write(userId, chatId, record);
      return selection;
    },
  };
}

const browserAdapters: ChatModelSelectionAdapters = {
  encryption: {
    async encrypt(plaintext) {
      const ciphertext = await encryptWithMasterKey(plaintext);
      if (!ciphertext) throw new Error("Could not encrypt chat model selection");
      return ciphertext;
    },
    decrypt: decryptWithMasterKey,
  },
  local: {
    read: readLocalSelection,
    write: writeLocalSelection,
  },
  remote: {
    async read(_userId, chatId) {
      return await requestRemoteSelection(chatId, "get_chat_model_preference", { chat_id: chatId });
    },
    async compareAndSet(_userId, chatId, expectedVersion, record) {
      return await requestRemoteSelection(chatId, "update_chat_model_preference", {
        chat_id: chatId,
        encrypted_selected_ai_model: record.ciphertext,
        expected_preference_v: expectedVersion,
      });
    },
  },
};

export const chatModelSelectionService = createChatModelSelectionService(browserAdapters);

export function registerChatModelSelectionSync(
  userId: string,
  onSelection: (chatId: string, selection: ChatModelSelection) => void,
): () => void {
  const handleSynced = async (payload: PreferenceResponsePayload) => {
    if (typeof payload.chat_id !== "string") return;
    const record = parseEncryptedRecord(payload.preference);
    if (!record) return;
    const selection = await chatModelSelectionService.receiveRemote({
      userId,
      chatId: payload.chat_id,
      record,
    });
    onSelection(payload.chat_id, selection);
  };
  webSocketService.on("chat_model_preference_synced", handleSynced);
  return () => webSocketService.off("chat_model_preference_synced", handleSynced);
}
