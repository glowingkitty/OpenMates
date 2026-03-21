// frontend/packages/ui/src/services/db/chatKeyManagement.ts
// Handles chat key management operations for the ChatDatabase class.
// These operations are extracted from db.ts for better code organization.
//
// This module manages the in-memory cache of chat encryption keys and provides
// methods for encrypting/decrypting message fields using chat-specific keys.
// Chat keys are symmetric AES keys that are themselves encrypted with the user's
// master key for zero-knowledge architecture.

import type { Message, Chat } from "../../types/chat";
import {
  encryptWithChatKey,
  decryptWithChatKey,
  decryptChatKeyWithMasterKey,
} from "../cryptoService";
import { chatKeyManager } from "../encryption/ChatKeyManager";
import {
  isKnownDecryptionFailure,
  recordDecryptionFailure,
} from "./decryptionFailureCache";
import { get } from "svelte/store";
import { forcedLogoutInProgress } from "../../stores/signupState";
import { websocketStatus } from "../../stores/websocketStatusStore";

// ---------------------------------------------------------------------------
// Cached chat version map — populated during loadChatKeysFromDatabase cursor
// so startPhasedSync() can skip the expensive getAllChats() IDB read.
// ---------------------------------------------------------------------------
export interface ChatVersionEntry {
  messages_v: number;
  title_v: number;
  draft_v: number;
}

/** In-memory version map populated during bulk key loading. */
const cachedChatVersionMap = new Map<string, ChatVersionEntry>();

/**
 * Returns the version map collected during loadChatKeysFromDatabase().
 * If the map is empty, it means keys haven't been loaded yet (caller should fall back to IDB).
 */
export function getCachedChatVersionMap(): Map<string, ChatVersionEntry> {
  return cachedChatVersionMap;
}

/**
 * Clear the cached version map (e.g. on logout).
 */
export function clearCachedChatVersionMap(): void {
  cachedChatVersionMap.clear();
}

/**
 * Type for ChatDatabase instance to avoid circular import.
 * This interface defines the minimal required properties from ChatDatabase
 * that this module needs to access.
 *
 * NOTE: chatKeys (the legacy dual cache) has been removed. ChatKeyManager is now
 * the single source of truth for all chat keys.
 */
interface ChatDatabaseInstance {
  db: IDBDatabase | null;
  CHATS_STORE_NAME: string;
  getChat(chatId: string, transaction?: IDBTransaction): Promise<Chat | null>;
}

/**
 * Get chat key from ChatKeyManager (single source of truth).
 *
 * @param _dbInstance - Unused (kept for API compatibility during migration)
 * @param chatId - The ID of the chat
 * @returns The chat key if in memory, null otherwise
 */
export function getChatKey(
  _dbInstance: ChatDatabaseInstance,
  chatId: string,
): Uint8Array | null {
  return chatKeyManager.getKeySync(chatId);
}

/**
 * Set chat key — delegates entirely to ChatKeyManager (single source of truth).
 * The immutability guard prevents silently replacing an existing key with a different one.
 *
 * @param _dbInstance - Unused (kept for API compatibility during migration)
 * @param chatId - The ID of the chat
 * @param chatKey - The chat key to cache
 * @param source - Where this key came from (for provenance tracking)
 */
export function setChatKey(
  _dbInstance: ChatDatabaseInstance,
  chatId: string,
  chatKey: Uint8Array,
  source?: import("../encryption/ChatKeyManager").KeySource,
): void {
  chatKeyManager.injectKey(chatId, chatKey, source);
}

/**
 * Clear a single chat key. Delegates to ChatKeyManager.
 *
 * @param _dbInstance - Unused (kept for API compatibility)
 * @param chatId - The ID of the chat whose key should be cleared
 */
export function clearChatKey(
  _dbInstance: ChatDatabaseInstance,
  chatId: string,
): void {
  chatKeyManager.removeKey(chatId);
}

/**
 * Clear all chat keys. Delegates to ChatKeyManager.
 *
 * @param _dbInstance - Unused (kept for API compatibility)
 */
export function clearAllChatKeys(_dbInstance: ChatDatabaseInstance): void {
  chatKeyManager.clearAll();
  clearCachedChatVersionMap();
}

/**
 * @deprecated DEAD — never generates correct keys for existing chats.
 * Kept only so TypeScript doesn't break callers that haven't been migrated yet.
 * All callers should use chatKeyManager.createKeyForNewChat() or getKeySync().
 */
export function getOrGenerateChatKey(
  _dbInstance: ChatDatabaseInstance,
  chatId: string,
): Uint8Array {
  const existing = chatKeyManager.getKeySync(chatId);
  if (existing) return existing;
  console.error(
    `[chatKeyManagement] getOrGenerateChatKey() called for ${chatId} but key not in ChatKeyManager. ` +
      `This is a bug — key should have been loaded by initializeCrypto(). ` +
      `Refusing to silently generate a wrong key.`,
  );
  // Return a dummy key so TypeScript is happy, but log loud enough that this is found in review.
  // The actual encryption will fail when this wrong key is used.
  throw new Error(
    `[chatKeyManagement] No key for ${chatId} — call chatKeyManager.createKeyForNewChat() explicitly`,
  );
}

/**
 * Get chat key from ChatKeyManager, returning null if not loaded.
 *
 * @param _dbInstance - Unused (kept for API compatibility)
 * @param chatId - The ID of the chat
 */
export function getChatKeyOrNull(
  _dbInstance: ChatDatabaseInstance,
  chatId: string,
): Uint8Array | null {
  return chatKeyManager.getKeySync(chatId);
}

/**
 * Get or create chat key for the ORIGINATING device of a new chat.
 * Delegates to ChatKeyManager.createKeyForNewChat() so the key is
 * tracked with provenance 'created' and the immutability guard applies.
 *
 * @param _dbInstance - Unused (kept for API compatibility)
 * @param chatId - The ID of the chat
 */
export function getOrCreateChatKeyForOriginator(
  _dbInstance: ChatDatabaseInstance,
  chatId: string,
): Uint8Array {
  const existing = chatKeyManager.getKeySync(chatId);
  if (existing) return existing;
  return chatKeyManager.createKeyForNewChat(chatId);
}

/**
 * Load chat keys from database into cache.
 * This should be called when the database is initialized to load all chat keys.
 *
 * NOTE: This method must NOT call init() or any method that calls init() to avoid circular dependency
 *
 * @param dbInstance - Reference to the ChatDatabase instance
 */
export async function loadChatKeysFromDatabase(
  dbInstance: ChatDatabaseInstance,
): Promise<void> {
  // CRITICAL: Skip loading chat keys during forced logout (missing master key scenario)
  // This prevents errors when trying to decrypt chat keys without a master key
  if (get(forcedLogoutInProgress)) {
    console.debug(
      "[ChatDatabase] Skipping chat key loading during forced logout",
    );
    return;
  }

  // Don't call getAllChats() here as it calls init(), causing a circular dependency!
  // Instead, directly access the database that's already initialized
  if (!dbInstance.db) {
    console.warn(
      "[ChatDatabase] Database not initialized yet, skipping chat key loading",
    );
    return;
  }

  return new Promise((resolve) => {
    try {
      const transaction = dbInstance.db!.transaction(
        dbInstance.CHATS_STORE_NAME,
        "readonly",
      );
      const store = transaction.objectStore(dbInstance.CHATS_STORE_NAME);
      const request = store.openCursor();

      // CRITICAL FIX: Collect all chat keys to decrypt, then decrypt them after cursor is done
      // Cannot await inside cursor callback because transaction would finish before cursor.continue()
      const keysToDecrypt: Array<{ chatId: string; encryptedKey: string }> = [];

      // PERF: Clear + repopulate version map during this cursor pass so
      // startPhasedSync() can skip a separate getAllChats() IDB read.
      cachedChatVersionMap.clear();

      request.onsuccess = (event) => {
        const cursor = (event.target as IDBRequest<IDBCursorWithValue>).result;
        if (cursor) {
          const chat = cursor.value;
          if (
            chat.encrypted_chat_key &&
            !chatKeyManager.hasKey(chat.chat_id)
          ) {
            // Collect keys to decrypt after cursor is done
            keysToDecrypt.push({
              chatId: chat.chat_id,
              encryptedKey: chat.encrypted_chat_key,
            });
          }
          // PERF: Collect version info for startPhasedSync() delta checking
          cachedChatVersionMap.set(chat.chat_id, {
            messages_v: chat.messages_v || 0,
            title_v: chat.title_v || 0,
            draft_v: chat.draft_v || 0,
          });
          // Continue cursor synchronously (transaction must stay alive)
          cursor.continue();
        } else {
          // Cursor is done - now decrypt all collected keys in parallel batches
          // This happens after the transaction completes, which is fine
          (async () => {
            try {
              // Pre-fetch master key ONCE before the batch loop to avoid
              // N concurrent IndexedDB reads of the crypto database.
              // Without this, each decryptChatKeyWithMasterKey call opens its own
              // IDB connection, causing massive contention for stayLoggedIn=true users.
              const { getKeyFromStorage } = await import("../cryptoService");
              const prefetchedMasterKey = await getKeyFromStorage();
              if (!prefetchedMasterKey) {
                console.warn("[ChatDatabase] No master key available, skipping bulk key decryption");
                resolve();
                return;
              }

              const BATCH_SIZE = 20;
              for (
                let i = 0;
                i < keysToDecrypt.length;
                i += BATCH_SIZE
              ) {
                const batch = keysToDecrypt.slice(i, i + BATCH_SIZE);
                await Promise.all(
                  batch.map(({ chatId, encryptedKey }) =>
                    decryptChatKeyWithMasterKey(encryptedKey, prefetchedMasterKey)
                      .then((chatKey) => {
                        if (chatKey) {
                          chatKeyManager.injectKey(
                            chatId,
                            chatKey,
                            "bulk_init",
                          );
                        }
                      })
                      .catch((decryptError) => {
                        console.error(
                          `[ChatDatabase] Error decrypting chat key for ${chatId}:`,
                          decryptError,
                        );
                      }),
                  ),
                );
              }
              console.debug(
                `[ChatDatabase] Loaded ${keysToDecrypt.length} chat keys from database`,
              );
              resolve();
            } catch (error) {
              console.error(
                "[ChatDatabase] Error decrypting chat keys:",
                error,
              );
              resolve(); // Don't reject, just resolve to allow init to complete
            }
          })();
        }
      };

      request.onerror = () => {
        console.error(
          "[ChatDatabase] Error loading chat keys from database:",
          request.error,
        );
        resolve(); // Don't reject, just resolve to allow init to complete
      };
    } catch (error) {
      console.error("[ChatDatabase] Error in loadChatKeysFromDatabase:", error);
      resolve(); // Don't reject, just resolve to allow init to complete
    }
  });
}

/**
 * Get encrypted chat key for server storage (zero-knowledge architecture).
 * The server needs this to store the encrypted chat key in Directus for device sync.
 *
 * @param dbInstance - Reference to the ChatDatabase instance
 * @param chatId - The ID of the chat
 * @returns The encrypted chat key string, or null if not found
 */
export async function getEncryptedChatKey(
  dbInstance: ChatDatabaseInstance,
  chatId: string,
): Promise<string | null> {
  try {
    const chat = await dbInstance.getChat(chatId);
    const encryptedKey = chat?.encrypted_chat_key || null;
    if (!encryptedKey) {
      console.warn(
        `[ChatDatabase] No encrypted_chat_key found for chat ${chatId}:`,
        chat ? "exists but missing key" : "chat not found",
      );
    }
    return encryptedKey;
  } catch (error) {
    console.error(
      `[ChatDatabase] ❌ Error getting encrypted chat key for ${chatId}:`,
      error,
    );
    return null;
  }
}

/**
 * Encrypt message fields with chat-specific key for storage (removes plaintext).
 * EXCEPTION: Public chat messages (chatId starting with 'demo-' or 'legal-') are NOT encrypted
 * since they contain public template content that's the same for all users.
 *
 * CRITICAL: This function is async because encryptWithChatKey is async.
 * All callers must await this function to prevent storing Promises in IndexedDB.
 *
 * @param dbInstance - Reference to the ChatDatabase instance
 * @param message - The message to encrypt
 * @param chatId - The ID of the chat the message belongs to
 * @returns A copy of the message with encrypted fields and plaintext removed
 */
export async function encryptMessageFields(
  dbInstance: ChatDatabaseInstance,
  message: Message,
  chatId: string,
): Promise<Message> {
  // Skip encryption entirely for public chat messages (demo + legal) - they're public content
  if (chatId.startsWith("demo-") || chatId.startsWith("legal-")) {
    console.debug(
      `[ChatDatabase] Skipping message encryption for public chat: ${chatId}`,
    );
    // For public messages, store content in encrypted_content field (but not actually encrypted)
    const messageToStore = { ...message };
    if (message.content && !message.encrypted_content) {
      messageToStore.encrypted_content = message.content; // Store as plaintext
    }
    return messageToStore;
  }

  const encryptedMessage = { ...message };

  // Use ChatKeyManager: try sync cache first, then async load from IDB.
  // NEVER generate a random key — if key is unavailable, throw instead of silently corrupting data.
  let chatKey = chatKeyManager.getKeySync(chatId);
  if (!chatKey) {
    // Async fallback: try loading from IDB
    chatKey = await chatKeyManager.getKey(chatId);
  }
  if (!chatKey) {
    throw new Error(
      `[ChatKeyManager] Cannot encrypt message for chat ${chatId}: no chat key available. ` +
        `This prevents silent data corruption. The caller should ensure the key ` +
        `is loaded before calling encryptMessageFields().`,
    );
  }

  // CRITICAL FIX: await all async encryption calls to prevent storing Promises in IndexedDB
  // Encrypt content if present - ZERO-KNOWLEDGE: Remove plaintext content
  if (message.content) {
    // Content is now a markdown string (never Tiptap JSON on server!)
    const contentString =
      typeof message.content === "string"
        ? message.content
        : JSON.stringify(message.content);
    encryptedMessage.encrypted_content = await encryptWithChatKey(
      contentString,
      chatKey,
    );
  }
  // CRITICAL: Always remove plaintext content for zero-knowledge architecture
  // This ensures even undefined/null values are removed from storage
  delete encryptedMessage.content;

  // Encrypt sender_name if present - ZERO-KNOWLEDGE: Remove plaintext sender_name
  if (message.sender_name) {
    encryptedMessage.encrypted_sender_name = await encryptWithChatKey(
      message.sender_name,
      chatKey,
    );
  }
  // CRITICAL: Always remove plaintext sender_name for zero-knowledge architecture
  // This ensures even undefined/null values are removed from storage
  delete encryptedMessage.sender_name;

  // Encrypt category if present - ZERO-KNOWLEDGE: Remove plaintext category
  if (message.category) {
    encryptedMessage.encrypted_category = await encryptWithChatKey(
      message.category,
      chatKey,
    );
  }
  // CRITICAL: Always remove plaintext category for zero-knowledge architecture
  // This ensures even undefined/null values are removed from storage
  delete encryptedMessage.category;

  // Encrypt model_name if present - ZERO-KNOWLEDGE: Remove plaintext model_name
  if (message.model_name) {
    encryptedMessage.encrypted_model_name = await encryptWithChatKey(
      message.model_name,
      chatKey,
    );
  }
  // CRITICAL: Always remove plaintext model_name for zero-knowledge architecture
  delete encryptedMessage.model_name;

  // Encrypt thinking_content if present - ZERO-KNOWLEDGE: Remove plaintext thinking_content
  // Thinking content comes from thinking models (Gemini, Anthropic Claude, etc.)
  if (message.thinking_content) {
    encryptedMessage.encrypted_thinking_content = await encryptWithChatKey(
      message.thinking_content,
      chatKey,
    );
  }
  // CRITICAL: Always remove plaintext thinking_content for zero-knowledge architecture
  delete encryptedMessage.thinking_content;

  // Encrypt thinking_signature if present - ZERO-KNOWLEDGE: Remove plaintext thinking_signature
  // Signatures are used for multi-turn verification with thinking models
  if (message.thinking_signature) {
    encryptedMessage.encrypted_thinking_signature = await encryptWithChatKey(
      message.thinking_signature,
      chatKey,
    );
  }
  // CRITICAL: Always remove plaintext thinking_signature for zero-knowledge architecture
  delete encryptedMessage.thinking_signature;

  // Encrypt pii_mappings if present - ZERO-KNOWLEDGE: Remove plaintext pii_mappings
  // PII mappings store the relationship between placeholders and original values
  // for client-side restoration of anonymized data in message rendering
  if (message.pii_mappings && message.pii_mappings.length > 0) {
    const piiMappingsJson = JSON.stringify(message.pii_mappings);
    encryptedMessage.encrypted_pii_mappings = await encryptWithChatKey(
      piiMappingsJson,
      chatKey,
    );
  }
  // CRITICAL: Always remove plaintext pii_mappings for zero-knowledge architecture
  delete encryptedMessage.pii_mappings;

  return encryptedMessage;
}

/**
 * Get encrypted fields only (for dual-content approach - preserves original message).
 * CRITICAL: This function is async because encryptWithChatKey is async.
 * All callers must await this function to prevent storing Promises in IndexedDB.
 *
 * @param dbInstance - Reference to the ChatDatabase instance
 * @param message - The message whose fields should be encrypted
 * @param chatId - The ID of the chat the message belongs to
 * @returns Object containing only the encrypted field values
 */
export async function getEncryptedFields(
  dbInstance: ChatDatabaseInstance,
  message: Message,
  chatId: string,
): Promise<{
  encrypted_content?: string;
  encrypted_sender_name?: string;
  encrypted_category?: string;
  encrypted_model_name?: string;
  encrypted_thinking_content?: string;
  encrypted_thinking_signature?: string;
  encrypted_pii_mappings?: string;
}> {
  // Use ChatKeyManager: try sync cache first, then async load from IDB.
  // NEVER generate a random key — throw if key is unavailable.
  let chatKey = chatKeyManager.getKeySync(chatId);
  if (!chatKey) {
    chatKey = await chatKeyManager.getKey(chatId);
  }
  if (!chatKey) {
    throw new Error(
      `[ChatKeyManager] Cannot get encrypted fields for chat ${chatId}: no chat key available. ` +
        `The caller should ensure the key is loaded before calling getEncryptedFields().`,
    );
  }
  const encryptedFields: {
    encrypted_content?: string;
    encrypted_sender_name?: string;
    encrypted_category?: string;
    encrypted_model_name?: string;
    encrypted_thinking_content?: string;
    encrypted_thinking_signature?: string;
    encrypted_pii_mappings?: string;
  } = {};

  // CRITICAL FIX: await all async encryption calls to prevent storing Promises
  // Encrypt content if present
  if (message.content) {
    const contentString =
      typeof message.content === "string"
        ? message.content
        : JSON.stringify(message.content);
    encryptedFields.encrypted_content = await encryptWithChatKey(
      contentString,
      chatKey,
    );
  }

  // Encrypt sender_name if present
  if (message.sender_name) {
    encryptedFields.encrypted_sender_name = await encryptWithChatKey(
      message.sender_name,
      chatKey,
    );
  }

  // Encrypt category if present
  if (message.category) {
    encryptedFields.encrypted_category = await encryptWithChatKey(
      message.category,
      chatKey,
    );
  }

  // Encrypt model_name if present
  if (message.model_name) {
    encryptedFields.encrypted_model_name = await encryptWithChatKey(
      message.model_name,
      chatKey,
    );
  }

  // Encrypt thinking content/signature for thinking models (Gemini, Anthropic Claude, etc.)
  if (message.thinking_content) {
    encryptedFields.encrypted_thinking_content = await encryptWithChatKey(
      message.thinking_content,
      chatKey,
    );
  }
  if (message.thinking_signature) {
    encryptedFields.encrypted_thinking_signature = await encryptWithChatKey(
      message.thinking_signature,
      chatKey,
    );
  }

  // Encrypt PII mappings if present (user messages with PII detection)
  if (message.pii_mappings && message.pii_mappings.length > 0) {
    const piiMappingsJson = JSON.stringify(message.pii_mappings);
    encryptedFields.encrypted_pii_mappings = await encryptWithChatKey(
      piiMappingsJson,
      chatKey,
    );
  }

  return encryptedFields;
}

/**
 * Decrypt message fields with chat-specific key.
 * DEFENSIVE: Handles malformed encrypted content from incomplete message sync.
 * EXCEPTION: Public chat messages (chatId starting with 'demo-' or 'legal-') are NOT decrypted
 * since they're stored as plaintext (public template content).
 *
 * @param dbInstance - Reference to the ChatDatabase instance
 * @param message - The message to decrypt
 * @param chatId - The ID of the chat the message belongs to
 * @returns A copy of the message with decrypted fields and encrypted fields removed
 */
export async function decryptMessageFields(
  dbInstance: ChatDatabaseInstance,
  message: Message,
  chatId: string,
): Promise<Message> {
  // CRITICAL: Skip decryption entirely during forced logout (missing master key scenario)
  // This prevents errors when the app tries to decrypt chats that can't be decrypted anymore
  // because the master key is gone. The forced logout will navigate to demo-for-everyone.
  if (get(forcedLogoutInProgress)) {
    console.debug(
      `[ChatDatabase] Skipping message decryption during forced logout for chat: ${chatId}`,
    );
    return { ...message };
  }

  // Skip decryption when WebSocket is in error state (auth failures, etc.)
  // This prevents unnecessary decryption attempts when the user is being logged out
  const wsStatus = get(websocketStatus);
  if (wsStatus.status === "error") {
    console.debug(
      `[ChatDatabase] Skipping message decryption due to WebSocket error state for chat: ${chatId}`,
    );
    return { ...message };
  }

  // Skip decryption entirely for public chat messages (demo + legal) - they're stored as plaintext
  if (chatId.startsWith("demo-") || chatId.startsWith("legal-")) {
    console.debug(
      `[ChatDatabase] Skipping message decryption for public chat: ${chatId}`,
    );
    const messageToReturn = { ...message };
    // For public messages, encrypted_content is actually plaintext - copy to content field
    if (message.encrypted_content && !message.content) {
      messageToReturn.content = message.encrypted_content;
    }
    return messageToReturn;
  }

  const decryptedMessage = { ...message };
  // Use ChatKeyManager for key lookup (safe: returns null if unavailable)
  const chatKey = chatKeyManager.getKeySync(chatId);

  if (!chatKey) {
    const keyState = chatKeyManager.getState(chatId);
    const prov = chatKeyManager.getProvenance(chatId);
    console.error(
      `[CLIENT_DECRYPT] ❌ CRITICAL: No chat key found for chat ${chatId}, cannot decrypt message fields! ` +
        `Message ID: ${message.message_id}, Role: ${message.role}, Status: ${message.status}, ` +
        `Has encrypted_content: ${!!message.encrypted_content}, ` +
        `Encrypted content length: ${message.encrypted_content?.length || 0}, ` +
        `Key state: ${keyState}, Last provenance: ${prov ? `source=${prov.source} fp=${prov.keyFingerprint}` : "none"}`,
    );
    return decryptedMessage;
  }

  // Decrypt content if present
  if (message.encrypted_content) {
    if (isKnownDecryptionFailure(chatId, message.message_id, "content")) {
      // Skip — this message/field has permanently failed before with this key
      decryptedMessage.content =
        message.content || "[Content decryption failed]";
    } else {
      try {
        const decryptedContentString = await decryptWithChatKey(
          message.encrypted_content,
          chatKey,
          { chatId, fieldName: "content" },
        );
        if (decryptedContentString) {
          // Content is now a markdown string (never Tiptap JSON on server!)
          decryptedMessage.content = decryptedContentString;
          // Clear encrypted field
          delete decryptedMessage.encrypted_content;
        } else {
          // Decryption failed but didn't throw - encrypted_content might be malformed
          recordDecryptionFailure(chatId, message.message_id, "content");
          const prov = chatKeyManager.getProvenance(chatId);
          console.error(
            `[CLIENT_DECRYPT] ❌ Failed to decrypt content for message ${message.message_id} - ` +
              `encrypted_content present but decryption returned null. ` +
              `Key provenance: ${prov ? `source=${prov.source}, fp=${prov.keyFingerprint}, loaded=${new Date(prov.timestamp).toISOString()}` : "unknown"}. ` +
              `Message role: ${message.role}, status: ${message.status}, created_at: ${message.created_at}. ` +
              `This may indicate: key was rotated after message was encrypted, ` +
              `vault-encrypted content was sent instead of client-encrypted, ` +
              `or multi-tab auth disruption caused key regeneration.`,
          );
          // Keep encrypted field for debugging, set content to placeholder
          decryptedMessage.content =
            message.content || "[Content decryption failed]";
        }
      } catch (error) {
        // DEFENSIVE: Handle malformed encrypted_content (e.g., from messages with status 'sending' that never completed encryption)
        // Also handle database operation errors during logout (OperationError from IndexedDB)
        recordDecryptionFailure(chatId, message.message_id, "content");
        const errorMessage =
          error instanceof Error ? error.message : String(error);
        const isOperationError =
          errorMessage.includes("OperationError") ||
          errorMessage.includes("database");
        const logLevel = isOperationError ? "debug" : "error"; // Reduce noise for expected logout-related errors

        console[logLevel](
          `[CLIENT_DECRYPT] ${isOperationError ? "⚠️" : "❌ CRITICAL:"} Error decrypting content for message ${message.message_id} ` +
            `(role: ${message.role}, status: ${message.status}, chat: ${chatId}): ` +
            `${errorMessage}. ` +
            `Encrypted content length: ${message.encrypted_content?.length || 0}, ` +
            `Has plaintext fallback: ${!!message.content}. ` +
            `${isOperationError ? "This may be due to database operations during logout." : "This may indicate vault-encrypted content was sent instead of client-encrypted!"}`,
        );
        // If message already has plaintext content, use it (common for status='sending')
        if (message.content) {
          console.warn(
            `[CLIENT_DECRYPT] ⚠️ Using existing plaintext content for message ${message.message_id} - ` +
              `encryption may not have completed or content was stored incorrectly`,
          );
          decryptedMessage.content = message.content;
        } else {
          decryptedMessage.content = "[Content decryption failed]";
        }
        // Keep encrypted_content for debugging
      }
    }
  }

  // Decrypt remaining fields in parallel — all use the same chatKey and are independent.
  // Each field decryption is wrapped in its own try/catch to prevent one failure from blocking others.
  const fieldDecryptions: Promise<void>[] = [];

  // Helper to decrypt a field with failure caching
  const decryptField = (
    encryptedValue: string,
    fieldName: string,
    onSuccess: (val: string) => void,
    onFailure: () => void,
  ) => {
    if (isKnownDecryptionFailure(chatId, message.message_id, fieldName)) {
      onFailure();
      return;
    }
    fieldDecryptions.push(
      decryptWithChatKey(encryptedValue, chatKey, { chatId, fieldName })
        .then((val) => {
          if (val) {
            onSuccess(val);
          } else {
            recordDecryptionFailure(chatId, message.message_id, fieldName);
            onFailure();
          }
        })
        .catch((error) => {
          recordDecryptionFailure(chatId, message.message_id, fieldName);
          console.error(
            `[ChatDatabase] Error decrypting ${fieldName} for message ${message.message_id}:`,
            error,
          );
          onFailure();
        }),
    );
  };

  if (message.encrypted_sender_name) {
    decryptField(
      message.encrypted_sender_name,
      "sender_name",
      (val) => {
        decryptedMessage.sender_name = val;
        delete decryptedMessage.encrypted_sender_name;
      },
      () => {
        decryptedMessage.sender_name = message.sender_name || "Unknown";
      },
    );
  }

  if (message.encrypted_category) {
    decryptField(
      message.encrypted_category,
      "category",
      (val) => {
        decryptedMessage.category = val;
        delete decryptedMessage.encrypted_category;
      },
      () => {
        decryptedMessage.category = message.category || undefined;
      },
    );
  }

  if (message.encrypted_model_name) {
    decryptField(
      message.encrypted_model_name,
      "model_name",
      (val) => {
        decryptedMessage.model_name = val;
        delete decryptedMessage.encrypted_model_name;
      },
      () => {
        decryptedMessage.model_name = message.model_name || undefined;
      },
    );
  } else if (message.role === "assistant" && !decryptedMessage.model_name) {
    // We don't use a default fallback here anymore, to avoid showing model names for error messages
    // that were generated by the system rather than an actual LLM.
    decryptedMessage.model_name = undefined;
  }

  if (message.encrypted_thinking_content) {
    decryptField(
      message.encrypted_thinking_content,
      "thinking_content",
      (val) => {
        decryptedMessage.thinking_content = val;
        decryptedMessage.has_thinking = true;
        delete decryptedMessage.encrypted_thinking_content;
      },
      () => {
        decryptedMessage.thinking_content = undefined;
      },
    );
  }

  if (message.encrypted_thinking_signature) {
    decryptField(
      message.encrypted_thinking_signature,
      "thinking_signature",
      (val) => {
        decryptedMessage.thinking_signature = val;
        delete decryptedMessage.encrypted_thinking_signature;
      },
      () => {
        decryptedMessage.thinking_signature = undefined;
      },
    );
  }

  if (message.encrypted_pii_mappings) {
    decryptField(
      message.encrypted_pii_mappings,
      "pii_mappings",
      (val) => {
        decryptedMessage.pii_mappings = JSON.parse(val);
        delete decryptedMessage.encrypted_pii_mappings;
      },
      () => {
        decryptedMessage.pii_mappings = undefined;
      },
    );
  }

  await Promise.all(fieldDecryptions);

  return decryptedMessage;
}
