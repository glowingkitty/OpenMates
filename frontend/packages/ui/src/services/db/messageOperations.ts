// frontend/packages/ui/src/services/db/messageOperations.ts
// Handles message CRUD operations for the ChatDatabase class.
// These operations are extracted from db.ts for better code organization.
//
// This module contains:
// - Message saving (single and batch)
// - Message retrieval (by ID, by chat, all messages)
// - Message deletion
// - Duplicate detection and cleanup
// - Message status priority handling

import type { Message } from "../../types/chat";

// Type for ChatDatabase instance to avoid circular import
// Only includes properties/methods needed by this module
interface ChatDatabaseInstance {
  db: IDBDatabase | null;
  init(): Promise<void>;
  getTransaction(
    storeNames: string | string[],
    mode: IDBTransactionMode,
  ): Promise<IDBTransaction>;

  // Message encryption/decryption methods (from chatKeyManagement)
  encryptMessageFields(message: Message, chatId: string): Promise<Message>;
  decryptMessageFields(message: Message, chatId: string): Promise<Message>;
}

// Store name constant (must match the one in db.ts)
const MESSAGES_STORE_NAME = "messages";

// ============================================================================
// MESSAGE STATUS PRIORITY
// ============================================================================

/**
 * Status priority map for determining which message version to keep
 * Higher priority means the message has progressed further in its lifecycle
 */
const STATUS_PRIORITY: Record<string, number> = {
  sending: 1,
  waiting_for_internet: 1,
  processing: 2,
  streaming: 2,
  waiting_for_user: 2.3, // Higher than streaming/processing, lower than failed - chat paused for user action
  failed: 2.5,
  synced: 3,
};

/**
 * Determines if a new message should update an existing message.
 *
 * Rules:
 * - Always allow streaming -> streaming updates (content grows over time).
 * - Otherwise, allow updates only when status priority increases.
 */
export function shouldUpdateMessage(
  existing: Message,
  incoming: Message,
): boolean {
  // Streaming chunks must be able to update the same message id.
  if (existing.status === "streaming" && incoming.status === "streaming") {
    return true;
  }

  const existingPriority = STATUS_PRIORITY[existing.status] ?? 0;
  const incomingPriority = STATUS_PRIORITY[incoming.status] ?? 0;

  return incomingPriority > existingPriority;
}

/**
 * Returns true if the incoming encrypted record adds encrypted fields that are missing on the existing record.
 * This is important for placeholder messages (e.g. assistant message created before first chunk arrives).
 */
export function hasNewEncryptedFields(
  existing: Message,
  incomingEncrypted: Message,
): boolean {
  const pairs: Array<[keyof Message, keyof Message]> = [
    ["encrypted_content", "encrypted_content"],
    ["encrypted_sender_name", "encrypted_sender_name"],
    ["encrypted_category", "encrypted_category"],
    ["encrypted_model_name", "encrypted_model_name"],
    // Thinking content/signature must be persisted even if status doesn't advance.
    ["encrypted_thinking_content", "encrypted_thinking_content"],
    ["encrypted_thinking_signature", "encrypted_thinking_signature"],
  ];

  return pairs.some(([existingKey, incomingKey]) => {
    const existingValue = existing[existingKey];
    const incomingValue = incomingEncrypted[incomingKey];
    return !existingValue && !!incomingValue;
  });
}

// ============================================================================
// DUPLICATE DETECTION
// ============================================================================

/**
 * Determines if two messages are content duplicates (same logical message, different IDs)
 *
 * CRITICAL: For assistant messages, we also check if the message_id matches the task_id pattern
 * to avoid false positives when the same response is saved with different IDs from different sources.
 */
export function isContentDuplicate(
  existing: Message,
  incoming: Message,
): boolean {
  // Must be same chat, role, and have similar content
  if (
    existing.chat_id !== incoming.chat_id ||
    existing.role !== incoming.role
  ) {
    return false;
  }

  // For assistant messages, if message_ids are different but both look like task IDs (UUIDs),
  // and content matches, they might be the same message from different sync sources.
  // However, we should be more careful - only treat as duplicate if encrypted_content matches
  // AND timestamps are very close (within 1 minute for assistant messages to account for streaming delays)
  const isAssistantMessage =
    existing.role === "assistant" && incoming.role === "assistant";
  const timeThreshold = isAssistantMessage ? 60 : 300; // 1 minute for assistant, 5 minutes for user

  // Check if content is similar (for encrypted content, we compare the encrypted strings)
  // CRITICAL: encrypted_content comparison is the most reliable way to detect duplicates
  // since it's based on the actual encrypted content, not plaintext which might have embed references
  const contentMatch =
    existing.encrypted_content === incoming.encrypted_content;

  // Check if timestamps are close (within threshold) - messages from different sync sources
  const timeDiff = Math.abs(existing.created_at - incoming.created_at);
  const timeMatch = timeDiff < timeThreshold;

  // Check if sender names match (for user messages)
  // For assistant messages, sender_name is typically null/undefined, so this check is less relevant
  const senderMatch =
    existing.encrypted_sender_name === incoming.encrypted_sender_name ||
    (existing.role === "assistant" && incoming.role === "assistant");

  const isDuplicate = contentMatch && timeMatch && senderMatch;

  if (isDuplicate && isAssistantMessage) {
    console.debug(
      `[ChatDatabase] Detected potential duplicate assistant message: ` +
        `existing=${existing.message_id}, incoming=${incoming.message_id}, ` +
        `timeDiff=${timeDiff}s, contentMatch=${contentMatch}`,
    );
  }

  return isDuplicate;
}

/**
 * Finds content-based duplicates (same content but different message_id)
 * This handles cases where the same logical message has different IDs from different sync sources
 */
export async function findContentDuplicate(
  dbInstance: ChatDatabaseInstance,
  message: Message,
  transaction?: IDBTransaction,
): Promise<Message | null> {
  try {
    // Get all messages for the same chat
    const chatMessages = await getMessagesForChat(
      dbInstance,
      message.chat_id,
      transaction,
    );

    // Look for messages with same content, role, and similar timestamp
    for (const existingMessage of chatMessages) {
      if (existingMessage.message_id === message.message_id) {
        continue; // Skip same message_id
      }

      // Check if it's the same logical message based on content and timing
      if (isContentDuplicate(existingMessage, message)) {
        return existingMessage;
      }
    }

    return null;
  } catch (error) {
    console.error("[ChatDatabase] Error finding content duplicate:", error);
    return null;
  }
}

// ============================================================================
// MESSAGE CRUD OPERATIONS
// ============================================================================

/**
 * Get a single message by ID
 */
export async function getMessage(
  dbInstance: ChatDatabaseInstance,
  message_id: string,
  transaction?: IDBTransaction,
): Promise<Message | null> {
  await dbInstance.init();
  const currentTransaction =
    transaction ||
    (await dbInstance.getTransaction(MESSAGES_STORE_NAME, "readonly"));
  return new Promise((resolve, reject) => {
    const store = currentTransaction.objectStore(MESSAGES_STORE_NAME);
    const request = store.get(message_id);

    request.onsuccess = () => {
      const encryptedMessage = request.result;
      if (!encryptedMessage) {
        resolve(null);
        return;
      }
      // Decrypt message before returning (zero-knowledge architecture)
      // CRITICAL FIX: await decryption operation since decryptMessageFields is now async
      (async () => {
        try {
          const decryptedMessage = await dbInstance.decryptMessageFields(
            encryptedMessage,
            encryptedMessage.chat_id,
          );
          resolve(decryptedMessage);
        } catch (error) {
          console.error(
            `[ChatDatabase] Error decrypting message ${message_id}:`,
            error,
          );
          reject(error);
        }
      })();
    };
    request.onerror = () => {
      console.error(
        `[ChatDatabase] Error getting message ${message_id}:`,
        request.error,
      );
      reject(request.error);
    };
  });
}

/**
 * Get all messages for a specific chat
 */
export async function getMessagesForChat(
  dbInstance: ChatDatabaseInstance,
  chat_id: string,
  transaction?: IDBTransaction,
): Promise<Message[]> {
  await dbInstance.init();
  const currentTransaction =
    transaction ||
    (await dbInstance.getTransaction(MESSAGES_STORE_NAME, "readonly"));
  return new Promise((resolve, reject) => {
    const store = currentTransaction.objectStore(MESSAGES_STORE_NAME);
    const index = store.index("chat_id_created_at"); // Use compound index for fetching and sorting
    const request = index.getAll(
      IDBKeyRange.bound([chat_id, -Infinity], [chat_id, Infinity]),
    ); // Get all for chat_id, sorted by created_at

    request.onsuccess = async () => {
      const encryptedMessages = request.result || [];
      // Decrypt all messages before returning (zero-knowledge architecture)
      // CRITICAL FIX: await all decryption operations since decryptMessageFields is now async
      const decryptedMessages = await Promise.all(
        encryptedMessages.map((msg) =>
          dbInstance.decryptMessageFields(msg, chat_id),
        ),
      );
      resolve(decryptedMessages);
    };
    request.onerror = () => {
      console.error(
        `[ChatDatabase] Error getting messages for chat ${chat_id}:`,
        request.error,
      );
      reject(request.error);
    };
  });
}

/**
 * Get only the last message for a chat (efficient for sidebar display)
 * This avoids decrypting all messages when we only need the last one
 */
export async function getLastMessageForChat(
  dbInstance: ChatDatabaseInstance,
  chat_id: string,
  transaction?: IDBTransaction,
): Promise<Message | null> {
  await dbInstance.init();
  const currentTransaction =
    transaction ||
    (await dbInstance.getTransaction(MESSAGES_STORE_NAME, "readonly"));
  return new Promise((resolve, reject) => {
    const store = currentTransaction.objectStore(MESSAGES_STORE_NAME);
    const index = store.index("chat_id_created_at");
    // Use openCursor with 'prev' direction to get the last message (highest created_at)
    const request = index.openCursor(
      IDBKeyRange.bound([chat_id, -Infinity], [chat_id, Infinity]),
      "prev",
    );

    request.onsuccess = async () => {
      const cursor = request.result;
      if (cursor) {
        // Found the last message - decrypt and return it
        const encryptedMessage = cursor.value;
        try {
          const decryptedMessage = await dbInstance.decryptMessageFields(
            encryptedMessage,
            chat_id,
          );
          resolve(decryptedMessage);
        } catch (error) {
          console.error(
            `[ChatDatabase] Error decrypting last message for chat ${chat_id}:`,
            error,
          );
          resolve(null);
        }
      } else {
        // No messages found
        resolve(null);
      }
    };
    request.onerror = () => {
      console.error(
        `[ChatDatabase] Error getting last message for chat ${chat_id}:`,
        request.error,
      );
      reject(request.error);
    };
  });
}

/**
 * Get all messages from the database
 * Used for retrying pending messages when connection is restored
 * Can be called during init() (via cleanupDuplicateMessages) or after init()
 * @param dbInstance The ChatDatabase instance
 * @param duringInit If true, uses direct transaction instead of getTransaction (to avoid init deadlock)
 * @returns Promise resolving to array of all messages
 */
export async function getAllMessages(
  dbInstance: ChatDatabaseInstance,
  duringInit: boolean = false,
): Promise<Message[]> {
  // Only call init() if not already during init (to avoid deadlock)
  if (!duringInit) {
    await dbInstance.init();
  }

  if (!dbInstance.db) {
    throw new Error("Database not initialized");
  }

  // Use appropriate transaction method based on context
  const transaction = duringInit
    ? dbInstance.db.transaction(MESSAGES_STORE_NAME, "readonly")
    : await dbInstance.getTransaction(MESSAGES_STORE_NAME, "readonly");

  return new Promise((resolve, reject) => {
    const store = transaction.objectStore(MESSAGES_STORE_NAME);
    const request = store.getAll();

    request.onsuccess = async () => {
      const encryptedMessages = request.result || [];
      // Decrypt all messages before returning (zero-knowledge architecture)
      // CRITICAL FIX: await all decryption operations since decryptMessageFields is now async
      const decryptedMessages = await Promise.all(
        encryptedMessages.map((msg) =>
          dbInstance.decryptMessageFields(msg, msg.chat_id),
        ),
      );
      resolve(decryptedMessages);
    };
    request.onerror = () => {
      console.error(
        "[ChatDatabase] Error getting all messages:",
        request.error,
      );
      reject(request.error);
    };
  });
}

/**
 * Save a single message to the database
 * Handles duplicate detection and status priority
 */
export async function saveMessage(
  dbInstance: ChatDatabaseInstance,
  message: Message,
  transaction?: IDBTransaction,
): Promise<void> {
  await dbInstance.init();

  const usesExternalTransaction = !!transaction;
  console.debug(
    `[ChatDatabase] saveMessage called for ${message.message_id} (chat: ${message.chat_id}, role: ${message.role}, status: ${message.status}, external tx: ${usesExternalTransaction})`,
  );

  // DEFENSIVE: Validate message has required fields
  if (!message.message_id) {
    console.error(
      `[ChatDatabase] ❌ Cannot save message without message_id:`,
      message,
    );
    throw new Error("Message must have a message_id");
  }
  if (!message.chat_id) {
    console.error(
      `[ChatDatabase] ❌ Cannot save message without chat_id:`,
      message,
    );
    throw new Error("Message must have a chat_id");
  }

  // CRITICAL FIX: Do all async work BEFORE checking transaction state
  // Encrypt message content before storing in IndexedDB (zero-knowledge architecture)
  const encryptedMessage = await dbInstance.encryptMessageFields(
    message,
    message.chat_id,
  );

  // CRITICAL FIX: Check existing messages WITHOUT using the transaction (to avoid expiration)
  // We'll check for duplicates using a separate read-only transaction
  let existingMessage: Message | null = null;
  let contentDuplicate: Message | null = null;

  try {
    // Use a separate read-only transaction to check for duplicates
    const checkTransaction = await dbInstance.getTransaction(
      MESSAGES_STORE_NAME,
      "readonly",
    );
    existingMessage = await getMessage(
      dbInstance,
      message.message_id,
      checkTransaction,
    );

    if (!existingMessage) {
      contentDuplicate = await findContentDuplicate(
        dbInstance,
        message,
        checkTransaction,
      );
    }
  } catch (checkError) {
    // If check fails, continue anyway (will handle duplicate on put)
    console.warn(
      `[ChatDatabase] Could not check for duplicates for ${message.message_id}:`,
      checkError,
    );
  }

  // Handle duplicates based on check results
  if (existingMessage) {
    const shouldUpdateDueToNewEncryptedFields = hasNewEncryptedFields(
      existingMessage,
      encryptedMessage,
    );
    // Only update if the new message has higher priority status
    if (
      shouldUpdateMessage(existingMessage, message) ||
      shouldUpdateDueToNewEncryptedFields
    ) {
      if (
        shouldUpdateDueToNewEncryptedFields &&
        existingMessage.status === message.status
      ) {
        console.info(
          `[ChatDatabase] ✅ Updating existing message to fill missing encrypted fields: ${message.message_id} (status: ${message.status})`,
        );
      } else {
        console.info(
          `[ChatDatabase] ✅ DUPLICATE PREVENTED - Updating existing message with higher priority status: ${message.message_id} (${existingMessage.status} -> ${message.status})`,
        );
      }
    } else {
      console.info(
        `[ChatDatabase] ✅ DUPLICATE PREVENTED - Message ${message.message_id} already exists with equal/higher priority status (${existingMessage.status}), skipping save`,
      );
      return Promise.resolve();
    }
  } else if (contentDuplicate) {
    console.warn(
      `[ChatDatabase] ⚠️ CONTENT DUPLICATE DETECTED - Found duplicate with different message_id: ${contentDuplicate.message_id} -> ${message.message_id}`,
    );
    // Update the existing message with higher priority status if applicable
    if (shouldUpdateMessage(contentDuplicate, message)) {
      console.info(
        `[ChatDatabase] ✅ DUPLICATE PREVENTED - Updating content duplicate with higher priority: ${contentDuplicate.message_id} (${contentDuplicate.status} -> ${message.status})`,
      );
      // Delete the old message - use a separate transaction
      try {
        const deleteTransaction = await dbInstance.getTransaction(
          MESSAGES_STORE_NAME,
          "readwrite",
        );
        await deleteMessage(
          dbInstance,
          contentDuplicate.message_id,
          deleteTransaction,
        );
      } catch (deleteError) {
        console.warn(
          `[ChatDatabase] Could not delete duplicate message ${contentDuplicate.message_id}:`,
          deleteError,
        );
      }
    } else {
      console.info(
        `[ChatDatabase] ✅ DUPLICATE PREVENTED - Content duplicate has equal/higher priority (${contentDuplicate.status}), skipping ${message.message_id}`,
      );
      return Promise.resolve();
    }
  } else {
    console.debug(
      `[ChatDatabase] No existing message found for ${message.message_id}, will insert as new`,
    );
  }

  const putEncryptedMessage = (
    currentTransaction: IDBTransaction,
    resolveOnComplete: boolean,
  ): Promise<void> => {
    return new Promise((resolve, reject) => {
      const store = currentTransaction.objectStore(MESSAGES_STORE_NAME);
      const request = store.put(encryptedMessage); // Store encrypted message

      request.onsuccess = () => {
        console.debug(
          `[ChatDatabase] ✅ Encrypted message saved/updated successfully (queued): ${message.message_id} (chat: ${message.chat_id})`,
        );
        if (!resolveOnComplete) {
          resolve();
        }
      };
      request.onerror = () => {
        console.error(
          `[ChatDatabase] ❌ Error in message store.put operation for ${message.message_id}:`,
          request.error,
        );
        reject(request.error);
      };

      if (resolveOnComplete) {
        currentTransaction.oncomplete = () => {
          console.debug(
            `[ChatDatabase] ✅ Transaction for saveMessage completed successfully for message: ${message.message_id}`,
          );
          resolve();
        };
        currentTransaction.onerror = () => {
          console.error(
            `[ChatDatabase] ❌ Transaction for saveMessage failed for message: ${message.message_id}, Error:`,
            currentTransaction.error,
          );
          reject(currentTransaction.error);
        };
      }
    });
  };

  const isInvalidStateError = (error: unknown): boolean => {
    return (
      error instanceof Error &&
      (error.name === "InvalidStateError" ||
        error.message.includes("transaction"))
    );
  };

  const saveWithRetry = async (): Promise<void> => {
    // CRITICAL FIX: Check if external transaction is still active before using it
    if (usesExternalTransaction && transaction) {
      try {
        // Try to access the transaction's mode - if it throws, the transaction is finished
        void transaction.mode;
        if (transaction.error !== null) {
          throw new Error(`Transaction has error: ${transaction.error}`);
        }
      } catch (error) {
        console.warn(
          `[ChatDatabase] External transaction is no longer active for message ${message.message_id}, creating new transaction:`,
          error,
        );
        const newTransaction = await dbInstance.getTransaction(
          MESSAGES_STORE_NAME,
          "readwrite",
        );
        return putEncryptedMessage(newTransaction, true);
      }
    }

    const currentTransaction =
      transaction ||
      (await dbInstance.getTransaction(MESSAGES_STORE_NAME, "readwrite"));

    // CRITICAL FIX: Check transaction state one more time right before using it
    try {
      await putEncryptedMessage(currentTransaction, !usesExternalTransaction);
    } catch (error) {
      // Transaction is no longer active (InvalidStateError or similar)
      if (isInvalidStateError(error)) {
        console.warn(
          `[ChatDatabase] Transaction is no longer active for message ${message.message_id}, creating new transaction:`,
          error,
        );
        const newTransaction = await dbInstance.getTransaction(
          MESSAGES_STORE_NAME,
          "readwrite",
        );
        await putEncryptedMessage(newTransaction, true);
      } else {
        // Some other error - rethrow it
        console.error(
          `[ChatDatabase] Unexpected error in saveMessage for message ${message.message_id}:`,
          error,
        );
        throw error;
      }
    }
  };

  await saveWithRetry();
}

/**
 * Batch save multiple messages efficiently in a single transaction
 * This method prevents transaction auto-commit issues by:
 * 1. Checking for duplicates BEFORE creating the transaction
 * 2. Encrypting all messages BEFORE creating the transaction
 * 3. Queuing all put operations synchronously (no await between them)
 *
 * @param dbInstance The ChatDatabase instance
 * @param messages Array of messages to save
 * @returns Promise that resolves when all messages are saved
 */
export async function batchSaveMessages(
  dbInstance: ChatDatabaseInstance,
  messages: Message[],
): Promise<void> {
  await dbInstance.init();

  if (messages.length === 0) {
    return Promise.resolve();
  }

  console.debug(
    `[ChatDatabase] batchSaveMessages: Processing ${messages.length} messages`,
  );

  // Step 1: Validate all messages have required fields
  const validMessages: Message[] = [];
  for (const message of messages) {
    if (!message.message_id) {
      console.error(
        `[ChatDatabase] ❌ Skipping message without message_id:`,
        message,
      );
      continue;
    }
    if (!message.chat_id) {
      console.error(
        `[ChatDatabase] ❌ Skipping message without chat_id:`,
        message,
      );
      continue;
    }
    validMessages.push(message);
  }

  if (validMessages.length === 0) {
    console.warn(`[ChatDatabase] No valid messages to save after validation`);
    return Promise.resolve();
  }

  // Step 2: Check for duplicates by fetching all existing messages in a single transaction
  // CRITICAL FIX: Use individual read transactions for each check to avoid transaction auto-commit
  // Since each check is quick, this is more reliable than trying to keep one transaction alive
  const messagesToSkip = new Set<string>();
  const existingMessagesMap = new Map<string, Message>();

  // First, get all existing messages by their IDs using individual quick transactions
  // This avoids the transaction auto-commit issue
  const existingMessageChecks = await Promise.all(
    validMessages.map(async (message) => {
      try {
        // Create a fresh read transaction for each check - quick and safe
        const checkTransaction = await dbInstance.getTransaction(
          MESSAGES_STORE_NAME,
          "readonly",
        );
        const existingMessage = await getMessage(
          dbInstance,
          message.message_id,
          checkTransaction,
        );
        return { message, existingMessage };
      } catch (checkError) {
        console.warn(
          `[ChatDatabase] batchSaveMessages: Could not check for existing message ${message.message_id}, will save anyway:`,
          checkError,
        );
        return { message, existingMessage: null };
      }
    }),
  );

  // Process duplicate checks in memory
  for (const { message, existingMessage } of existingMessageChecks) {
    if (existingMessage) {
      existingMessagesMap.set(message.message_id, existingMessage);

      // Check if we should update
      if (shouldUpdateMessage(existingMessage, message)) {
        console.debug(
          `[ChatDatabase] batchSaveMessages: Will update existing message ${message.message_id} with higher priority`,
        );
        // Will save below - don't skip
      } else {
        console.debug(
          `[ChatDatabase] batchSaveMessages: Skipping ${message.message_id} - already exists with equal/higher priority`,
        );
        messagesToSkip.add(message.message_id);
      }
    } else {
      // Check for content duplicates only if message doesn't exist by ID
      // Note: Content duplicate checking is expensive, so we skip it in batch operations
      // Duplicate cleanup will handle content duplicates later
      // For now, we'll save the message and let duplicate cleanup handle it
    }
  }

  // Step 3: Encrypt all messages that need to be saved (BEFORE creating write transaction)
  const messagesToEncrypt = validMessages.filter(
    (msg) => !messagesToSkip.has(msg.message_id),
  );
  const encryptionPromises = messagesToEncrypt.map(async (message) => {
    const encrypted = await dbInstance.encryptMessageFields(
      message,
      message.chat_id,
    );
    return { message, encrypted };
  });

  const preparedMessages = await Promise.all(encryptionPromises);

  if (preparedMessages.length === 0) {
    console.debug(
      `[ChatDatabase] batchSaveMessages: No messages to save after duplicate checking`,
    );
    return Promise.resolve();
  }

  // Step 4: Create write transaction and queue all operations synchronously
  let writeTransaction: IDBTransaction;
  try {
    writeTransaction = await dbInstance.getTransaction(
      MESSAGES_STORE_NAME,
      "readwrite",
    );
  } catch (error) {
    console.error(
      `[ChatDatabase] batchSaveMessages: Error creating transaction:`,
      error,
    );
    throw error;
  }

  return new Promise((resolve, reject) => {
    const store = writeTransaction.objectStore(MESSAGES_STORE_NAME);

    // Queue all put operations synchronously (no await between them)
    // This keeps the transaction active until all operations are queued
    const requests: IDBRequest[] = [];
    for (const { encrypted } of preparedMessages) {
      const request = store.put(encrypted);
      requests.push(request);
    }

    console.debug(
      `[ChatDatabase] batchSaveMessages: Queued ${requests.length} put operations in transaction`,
    );

    // Wait for transaction to complete
    writeTransaction.oncomplete = () => {
      console.debug(
        `[ChatDatabase] batchSaveMessages: Transaction completed successfully for ${requests.length} messages`,
      );
      resolve();
    };

    writeTransaction.onerror = () => {
      console.error(
        `[ChatDatabase] batchSaveMessages: Transaction error:`,
        writeTransaction.error,
      );
      reject(writeTransaction.error);
    };

    writeTransaction.onabort = () => {
      console.error(`[ChatDatabase] batchSaveMessages: Transaction aborted`);
      reject(new Error("Transaction aborted"));
    };

    // Check for any request errors
    for (const request of requests) {
      request.onerror = () => {
        console.error(
          `[ChatDatabase] batchSaveMessages: Request error for message:`,
          request.error,
        );
        // Don't reject here - let transaction error handler handle it
      };
    }
  });
}

/**
 * Delete a specific message by message_id
 * NOTE: Can be called during init() cleanup, so may need to handle uninitialized DB
 */
export async function deleteMessage(
  dbInstance: ChatDatabaseInstance,
  message_id: string,
  transaction?: IDBTransaction,
): Promise<void> {
  return new Promise((resolve, reject) => {
    if (!dbInstance.db) {
      reject(new Error("Database not initialized"));
      return;
    }

    const currentTransaction =
      transaction ||
      dbInstance.db.transaction(MESSAGES_STORE_NAME, "readwrite");
    const store = currentTransaction.objectStore(MESSAGES_STORE_NAME);
    const request = store.delete(message_id);

    request.onsuccess = () => {
      console.debug("[ChatDatabase] Message deleted successfully:", message_id);
      resolve();
    };
    request.onerror = () => {
      console.error("[ChatDatabase] Error deleting message:", request.error);
      reject(request.error);
    };

    if (!transaction) {
      currentTransaction.oncomplete = () => resolve();
      currentTransaction.onerror = () => reject(currentTransaction.error);
    }
  });
}

// ============================================================================
// DUPLICATE CLEANUP
// ============================================================================

/**
 * Clean up duplicate messages by keeping the one with highest priority status
 * This method should be called during initialization to clean up existing duplicates
 */
export async function cleanupDuplicateMessages(
  dbInstance: ChatDatabaseInstance,
): Promise<void> {
  // NOTE: Do NOT call dbInstance.init() here! This method is called FROM init()
  // and calling it again would create a deadlock waiting for itself to finish.
  console.debug("[ChatDatabase] Starting duplicate message cleanup...");

  try {
    // Get all messages grouped by chat
    // Pass duringInit=true since this is called from init()
    const allMessages = await getAllMessages(dbInstance, true);
    const messagesByChat = new Map<string, Message[]>();

    // Group messages by chat_id
    allMessages.forEach((msg) => {
      if (!messagesByChat.has(msg.chat_id)) {
        messagesByChat.set(msg.chat_id, []);
      }
      messagesByChat.get(msg.chat_id)!.push(msg);
    });

    let duplicatesRemoved = 0;

    // Process each chat's messages for duplicates
    const chatIds = Array.from(messagesByChat.keys());
    for (const chatId of chatIds) {
      const messages = messagesByChat.get(chatId)!;
      const processedMessages = new Set<string>();

      for (let i = 0; i < messages.length; i++) {
        const currentMessage = messages[i];

        if (processedMessages.has(currentMessage.message_id)) {
          continue; // Already processed
        }

        // Find all duplicates of this message (same message_id or content duplicates)
        const duplicates = [currentMessage];

        for (let j = i + 1; j < messages.length; j++) {
          const otherMessage = messages[j];

          if (processedMessages.has(otherMessage.message_id)) {
            continue; // Already processed
          }

          // Check for exact message_id match or content duplicate
          if (
            currentMessage.message_id === otherMessage.message_id ||
            isContentDuplicate(currentMessage, otherMessage)
          ) {
            duplicates.push(otherMessage);
            processedMessages.add(otherMessage.message_id);
          }
        }

        if (duplicates.length > 1) {
          console.debug(
            `[ChatDatabase] Found ${duplicates.length} duplicates for message ${currentMessage.message_id} in chat ${chatId}`,
          );

          // Find the message with highest priority status
          const statusPriority: Record<string, number> = {
            sending: 1,
            delivered: 2,
            synced: 3,
          };

          const bestMessage = duplicates.reduce((best, current) => {
            const bestPriority = statusPriority[best.status] || 0;
            const currentPriority = statusPriority[current.status] || 0;
            return currentPriority > bestPriority ? current : best;
          });

          // Delete all duplicates except the best one
          const toDelete = duplicates.filter((msg) => msg !== bestMessage);
          for (const duplicate of toDelete) {
            await deleteMessage(dbInstance, duplicate.message_id);
            duplicatesRemoved++;
          }

          console.debug(
            `[ChatDatabase] Kept message ${bestMessage.message_id} with status '${bestMessage.status}', removed ${toDelete.length} duplicates`,
          );
        }

        processedMessages.add(currentMessage.message_id);
      }
    }

    console.debug(
      `[ChatDatabase] Duplicate cleanup completed. Removed ${duplicatesRemoved} duplicate messages.`,
    );
  } catch (error) {
    console.error("[ChatDatabase] Error during duplicate cleanup:", error);
  }
}
