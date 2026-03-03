/**
 * Debug Utilities for Chat Data Inspection
 *
 * These utilities are exposed to the global window object for debugging via the browser console.
 * They allow inspecting IndexedDB chat data, messages, and sync status.
 * For admin users, embed inspection includes a privacy-safe field inventory
 * (field names, types, sizes — no actual content values) and anomaly detection.
 *
 * Usage in browser console (all read-only):
 *   await window.inspectChat('chat-id')    - Generate copyable inspection report (recommended)
 *   await window.debugChat('chat-id')      - Inspect a specific chat (verbose console output)
 *   await window.debugAllChats()           - List all chats with consistency check
 *   await window.debugGetMessage('msg-id') - Get raw message data
 *
 * Architecture context: See docs/architecture/embed-encryption.md
 * IMPORTANT: These utilities are for development/debugging only.
 * They should not be used in production code paths.
 */

// Database constants (must match db.ts)
const DB_NAME = "chats_db";
const CHATS_STORE = "chats";
const MESSAGES_STORE = "messages";
const EMBEDS_STORE = "embeds";
const EMBED_KEYS_STORE = "embed_keys";

// Field inventory constants
const MAX_FIELD_INVENTORY_ITEMS = 30;
const MAX_ANOMALIES_PER_EMBED = 5;

/**
 * Compute SHA256 hash of a string
 * Matches the implementation in message_parsing/utils.ts
 */
async function computeSHA256(content: string): Promise<string> {
  const encoder = new TextEncoder();
  const data = encoder.encode(content);
  const hashBuffer = await crypto.subtle.digest("SHA-256", data);
  const hashArray = Array.from(new Uint8Array(hashBuffer));
  return hashArray.map((b) => b.toString(16).padStart(2, "0")).join("");
}

/**
 * Open the IndexedDB database
 */
async function openDB(): Promise<IDBDatabase> {
  return new Promise((resolve, reject) => {
    const request = indexedDB.open(DB_NAME);
    request.onerror = () => reject(request.error);
    request.onsuccess = () => resolve(request.result);
  });
}

/**
 * Get a value from an object store by key
 */
async function getFromStore<T>(
  db: IDBDatabase,
  storeName: string,
  key: string,
): Promise<T | undefined> {
  return new Promise((resolve, reject) => {
    const tx = db.transaction(storeName, "readonly");
    const store = tx.objectStore(storeName);
    const request = store.get(key);
    request.onerror = () => reject(request.error);
    request.onsuccess = () => resolve(request.result);
  });
}

/**
 * Get all values from an object store using an index
 */
async function getAllFromIndex<T>(
  db: IDBDatabase,
  storeName: string,
  indexName: string,
  key: IDBValidKey,
): Promise<T[]> {
  return new Promise((resolve, reject) => {
    const tx = db.transaction(storeName, "readonly");
    const store = tx.objectStore(storeName);
    const index = store.index(indexName);
    const request = index.getAll(key);
    request.onerror = () => reject(request.error);
    request.onsuccess = () => resolve(request.result || []);
  });
}

/**
 * Get all items from an object store
 */
async function getAllFromStore<T>(
  db: IDBDatabase,
  storeName: string,
): Promise<T[]> {
  return new Promise((resolve, reject) => {
    const tx = db.transaction(storeName, "readonly");
    const store = tx.objectStore(storeName);
    const request = store.getAll();
    request.onerror = () => reject(request.error);
    request.onsuccess = () => resolve(request.result || []);
  });
}

/**
 * Get count of all items in an object store
 */
async function getStoreCount(
  db: IDBDatabase,
  storeName: string,
): Promise<number> {
  return new Promise((resolve, reject) => {
    const tx = db.transaction(storeName, "readonly");
    const store = tx.objectStore(storeName);
    const request = store.count();
    request.onerror = () => reject(request.error);
    request.onsuccess = () => resolve(request.result || 0);
  });
}

// ============================================================================
// PRIVACY-SAFE FIELD INVENTORY (improvement C)
// ============================================================================

/**
 * Check if the current user is an admin.
 * Uses dynamic import to avoid circular dependencies.
 */
async function isCurrentUserAdmin(): Promise<boolean> {
  try {
    const { get } = await import("svelte/store");
    const { userProfile } = await import("../stores/userProfile");
    const profile = get(userProfile);
    return profile?.is_admin === true;
  } catch {
    return false;
  }
}

/**
 * Describe a value's type and size without exposing actual content.
 * Only structural info: "str(142)", "list(5)", "dict(3 keys)", "int(42)", "bool(true)", "null"
 */
function describeValue(value: unknown): string {
  if (value === null || value === undefined) return "null";
  if (typeof value === "boolean") return `bool(${value})`;
  if (typeof value === "number")
    return Number.isInteger(value) ? `int(${value})` : `float(${value})`;
  if (typeof value === "string") return `str(${value.length})`;
  if (Array.isArray(value)) return `list(${value.length})`;
  if (typeof value === "object")
    return `dict(${Object.keys(value as Record<string, unknown>).length} keys)`;
  return typeof value;
}

/**
 * Build a privacy-safe field inventory from decoded TOON content.
 * Shows field names, types, and sizes — NO actual content values
 * (except for key metadata fields like app_id, skill_id, status).
 */
function buildFieldInventory(decoded: Record<string, unknown>): {
  keyMetadata: Record<string, unknown>;
  fieldTypes: Record<string, string>;
  totalFields: number;
} {
  const keyMetadataFields = [
    "app_id",
    "skill_id",
    "status",
    "type",
    "query",
    "provider",
    "result_count",
    "language",
    "filename",
    "title",
  ];

  const keyMetadata: Record<string, unknown> = {};
  for (const field of keyMetadataFields) {
    if (field in decoded) {
      keyMetadata[field] = decoded[field];
    }
  }

  const fieldTypes: Record<string, string> = {};
  let count = 0;
  for (const [key, value] of Object.entries(decoded)) {
    if (count >= MAX_FIELD_INVENTORY_ITEMS) break;
    fieldTypes[key] = describeValue(value);
    count++;
  }

  return {
    keyMetadata,
    fieldTypes,
    totalFields: Object.keys(decoded).length,
  };
}

/**
 * Detect anomalies in decoded embed content.
 * Returns a list of warning strings.
 */
function detectEmbedAnomalies(
  decoded: Record<string, unknown>,
  embed: Record<string, unknown>,
): string[] {
  const anomalies: string[] = [];

  // Stale status check
  const status = decoded.status as string | undefined;
  if (status && status !== "finished" && status !== "activated") {
    anomalies.push(`status="${status}" (expected "finished")`);
  }

  // result_count vs embed_ids mismatch
  const embedIds = decoded.embed_ids;
  const resultCount = decoded.result_count;
  if (Array.isArray(embedIds) && resultCount !== undefined) {
    const count =
      typeof resultCount === "number"
        ? resultCount
        : parseInt(String(resultCount), 10);
    if (!isNaN(count) && count !== embedIds.length) {
      anomalies.push(
        `result_count=${count} but embed_ids has ${embedIds.length} entries`,
      );
    }
  }

  // Missing chat key on embed (checked from IndexedDB embed record)
  if (!embed.encrypted_content && !embed.content && !embed.data) {
    anomalies.push("Embed has no content (encrypted, plaintext, or data)");
  }

  // Missing expected fields for app_skill_use type
  const embedType = (decoded.type as string) || (embed.type as string);
  if (embedType === "app_skill_use") {
    if (!decoded.app_id)
      anomalies.push("Missing app_id on app_skill_use embed");
    if (!decoded.skill_id)
      anomalies.push("Missing skill_id on app_skill_use embed");
  }

  return anomalies.slice(0, MAX_ANOMALIES_PER_EMBED);
}

/**
 * Format field inventory and anomalies as text lines for a report.
 */
function formatFieldInventoryLines(
  inventory: {
    keyMetadata: Record<string, unknown>;
    fieldTypes: Record<string, string>;
    totalFields: number;
  },
  anomalies: string[],
): string[] {
  const lines: string[] = [];

  // Key metadata values (safe to show)
  const metaEntries = Object.entries(inventory.keyMetadata);
  if (metaEntries.length > 0) {
    lines.push("         Key Metadata:");
    for (const [key, value] of metaEntries) {
      const display =
        typeof value === "string" && value.length > 60
          ? value.substring(0, 57) + "..."
          : String(value ?? "null");
      lines.push(`           ${key.padEnd(20)} = ${display}`);
    }
  }

  // Field types (privacy-safe)
  lines.push(`         Fields (${inventory.totalFields} total):`);
  const typeEntries = Object.entries(inventory.fieldTypes);
  for (const [key, typeDesc] of typeEntries) {
    if (key in inventory.keyMetadata) continue; // Already shown above
    lines.push(`           ${key.padEnd(20)} : ${typeDesc}`);
  }
  if (inventory.totalFields > MAX_FIELD_INVENTORY_ITEMS) {
    lines.push(
      `           ... and ${inventory.totalFields - MAX_FIELD_INVENTORY_ITEMS} more fields`,
    );
  }

  // Anomalies
  if (anomalies.length > 0) {
    lines.push("         Anomalies:");
    for (const a of anomalies) {
      lines.push(`           * ${a}`);
    }
  }

  return lines;
}

// ============================================================================
// DEBUG FUNCTIONS EXPOSED TO WINDOW
// ============================================================================

interface ChatDebugInfo {
  chat_id: string;
  messages_v: number;
  title_v: number;
  draft_v: number;
  last_message_timestamp?: number;
  last_edited_overall_timestamp?: number;
  created_at?: number;
  updated_at?: number;
  has_encrypted_title: boolean;
  has_encrypted_chat_key: boolean;
  raw_metadata: Record<string, unknown>;
}

interface MessageDebugInfo {
  message_id: string;
  chat_id: string;
  role: string;
  created_at: number;
  created_at_formatted: string;
  has_content: boolean;
  has_encrypted_content: boolean;
  status?: string;
}

interface DebugChatResult {
  chat_id: string;
  found: boolean;
  chat_metadata: ChatDebugInfo | null;
  messages: {
    total_count: number;
    role_distribution: Record<string, number>;
    items: MessageDebugInfo[];
  };
  embeds: {
    total_count: number;
  };
  version_analysis: {
    messages_v: number;
    actual_message_count: number;
    is_consistent: boolean;
    discrepancy: string;
  };
}

/**
 * Debug a specific chat - inspect metadata, messages, and consistency
 *
 * Usage in console:
 *   await window.debugChat('your-chat-id-here')
 */
export async function debugChat(chatId: string): Promise<DebugChatResult> {
  console.log("🔍 Opening IndexedDB...");
  const db = await openDB();

  console.log("✅ Database opened:", db.name, "version:", db.version);
  console.log("📦 Object stores:", Array.from(db.objectStoreNames));

  // Get chat metadata
  const chatMeta = await getFromStore<Record<string, unknown>>(
    db,
    CHATS_STORE,
    chatId,
  );

  console.log("\n📋 CHAT METADATA:");
  let chatDebugInfo: ChatDebugInfo | null = null;

  if (chatMeta) {
    chatDebugInfo = {
      chat_id: chatMeta.chat_id as string,
      messages_v: (chatMeta.messages_v as number) || 0,
      title_v: (chatMeta.title_v as number) || 0,
      draft_v: (chatMeta.draft_v as number) || 0,
      last_message_timestamp: chatMeta.last_message_timestamp as
        | number
        | undefined,
      last_edited_overall_timestamp: chatMeta.last_edited_overall_timestamp as
        | number
        | undefined,
      created_at: chatMeta.created_at as number | undefined,
      updated_at: chatMeta.updated_at as number | undefined,
      has_encrypted_title: !!chatMeta.encrypted_title,
      has_encrypted_chat_key: !!chatMeta.encrypted_chat_key,
      raw_metadata: chatMeta,
    };

    console.log("  - chat_id:", chatDebugInfo.chat_id);
    console.log("  - messages_v:", chatDebugInfo.messages_v);
    console.log("  - title_v:", chatDebugInfo.title_v);
    console.log("  - draft_v:", chatDebugInfo.draft_v);
    console.log(
      "  - last_message_timestamp:",
      chatDebugInfo.last_message_timestamp,
    );
    console.log(
      "  - last_edited_overall_timestamp:",
      chatDebugInfo.last_edited_overall_timestamp,
    );
    console.log("  - has_encrypted_title:", chatDebugInfo.has_encrypted_title);
    console.log(
      "  - has_encrypted_chat_key:",
      chatDebugInfo.has_encrypted_chat_key,
    );
    console.log("  Full metadata:", chatMeta);
  } else {
    console.log("  ❌ Chat NOT FOUND in IndexedDB");
  }

  // Get all messages for the chat
  const messages = await getAllFromIndex<Record<string, unknown>>(
    db,
    MESSAGES_STORE,
    "chat_id",
    chatId,
  );

  console.log("\n💬 MESSAGES:");
  console.log("  Total count:", messages.length);

  const roleCount: Record<string, number> = {};
  const messageItems: MessageDebugInfo[] = [];

  if (messages.length > 0) {
    // Sort by created_at for display
    messages.sort(
      (a, b) => (a.created_at as number) - (b.created_at as number),
    );

    messages.forEach((msg, i) => {
      const role = (msg.role as string) || "unknown";
      roleCount[role] = (roleCount[role] || 0) + 1;

      const created_at = msg.created_at as number;
      const messageInfo: MessageDebugInfo = {
        message_id: msg.message_id as string,
        chat_id: msg.chat_id as string,
        role,
        created_at,
        created_at_formatted: new Date(created_at * 1000).toISOString(),
        has_content: !!msg.content,
        has_encrypted_content: !!msg.encrypted_content,
        status: msg.status as string | undefined,
      };
      messageItems.push(messageInfo);

      console.log(
        `  ${i + 1}. [${role}] message_id: ${messageInfo.message_id}`,
      );
      console.log(`     created_at: ${messageInfo.created_at_formatted}`);
      console.log(`     has content: ${messageInfo.has_content}`);
      console.log(
        `     has encrypted_content: ${messageInfo.has_encrypted_content}`,
      );
    });

    console.log("\n  Role distribution:", roleCount);
    console.log("\n  Raw messages array:", messages);
  } else {
    console.log("  ❌ No messages found for this chat");
  }

  // Get embeds for this chat using hashed_chat_id index
  const hashedChatId = await computeSHA256(chatId);
  const chatEmbeds = await getAllFromIndex<Record<string, unknown>>(
    db,
    EMBEDS_STORE,
    "hashed_chat_id",
    hashedChatId,
  );
  const totalEmbedsCount = await getStoreCount(db, EMBEDS_STORE);

  console.log("\n🖼️ EMBEDS:");
  console.log("  Chat embeds count:", chatEmbeds.length);
  console.log("  Total embeds in DB:", totalEmbedsCount);
  console.log("  Hashed chat ID:", hashedChatId.substring(0, 24) + "...");

  if (chatEmbeds.length > 0) {
    const typeCount: Record<string, number> = {};
    for (const embed of chatEmbeds) {
      const type = (embed.type as string) || "unknown";
      typeCount[type] = (typeCount[type] || 0) + 1;
    }
    console.log("  Type distribution:", typeCount);
    console.log("  Raw embeds:", chatEmbeds);
  }

  db.close();

  // Analyze version consistency
  const messagesV = chatDebugInfo?.messages_v || 0;
  const actualMessageCount = messages.length;
  // Note: messages_v increments for each message, but can have gaps
  // A consistent state would have messages_v >= message count
  // An inconsistent state is when messages_v is much higher than message count
  const isConsistent = messagesV <= actualMessageCount + 1; // Allow 1 buffer for in-progress
  const discrepancy = isConsistent
    ? "✅ Versions appear consistent"
    : `⚠️ VERSION MISMATCH: messages_v=${messagesV} but only ${actualMessageCount} messages in IndexedDB!`;

  console.log("\n📊 VERSION ANALYSIS:");
  console.log("  messages_v:", messagesV);
  console.log("  actual_message_count:", actualMessageCount);
  console.log("  Status:", discrepancy);

  const result: DebugChatResult = {
    chat_id: chatId,
    found: !!chatMeta,
    chat_metadata: chatDebugInfo,
    messages: {
      total_count: messages.length,
      role_distribution: roleCount,
      items: messageItems,
    },
    embeds: {
      total_count: chatEmbeds.length,
    },
    version_analysis: {
      messages_v: messagesV,
      actual_message_count: actualMessageCount,
      is_consistent: isConsistent,
      discrepancy,
    },
  };

  console.log("\n📦 Full result object:", result);
  return result;
}

/**
 * Debug all chats - get overview of all chats in IndexedDB
 *
 * Usage in console:
 *   await window.debugAllChats()
 */
export async function debugAllChats(): Promise<{
  total_chats: number;
  total_messages: number;
  chats: Array<{
    chat_id: string;
    messages_v: number;
    actual_messages: number;
    is_consistent: boolean;
  }>;
}> {
  console.log("🔍 Loading all chats from IndexedDB...");
  const db = await openDB();

  const allChats = await getAllFromStore<Record<string, unknown>>(
    db,
    CHATS_STORE,
  );
  const allMessages = await getAllFromStore<Record<string, unknown>>(
    db,
    MESSAGES_STORE,
  );

  console.log(
    `\n📋 Found ${allChats.length} chats and ${allMessages.length} messages total`,
  );

  // Group messages by chat_id
  const messagesByChatId: Record<string, number> = {};
  for (const msg of allMessages) {
    const chatId = msg.chat_id as string;
    messagesByChatId[chatId] = (messagesByChatId[chatId] || 0) + 1;
  }

  const chatSummaries = allChats.map((chat) => {
    const chatId = chat.chat_id as string;
    const messagesV = (chat.messages_v as number) || 0;
    const actualMessages = messagesByChatId[chatId] || 0;
    const isConsistent = messagesV <= actualMessages + 1;

    return {
      chat_id: chatId,
      messages_v: messagesV,
      actual_messages: actualMessages,
      is_consistent: isConsistent,
    };
  });

  // Log inconsistent chats
  const inconsistentChats = chatSummaries.filter((c) => !c.is_consistent);
  if (inconsistentChats.length > 0) {
    console.log("\n⚠️ INCONSISTENT CHATS:");
    inconsistentChats.forEach((c) => {
      console.log(
        `  - ${c.chat_id}: messages_v=${c.messages_v}, actual=${c.actual_messages}`,
      );
    });
  } else {
    console.log("\n✅ All chats have consistent message counts");
  }

  db.close();

  const result = {
    total_chats: allChats.length,
    total_messages: allMessages.length,
    chats: chatSummaries,
  };

  console.log("\n📦 Full result:", result);
  return result;
}

/**
 * Get raw message data for a specific message ID
 *
 * Usage in console:
 *   await window.debugGetMessage('message-id-here')
 */
export async function debugGetMessage(
  messageId: string,
): Promise<Record<string, unknown> | null> {
  const db = await openDB();
  const message = await getFromStore<Record<string, unknown>>(
    db,
    MESSAGES_STORE,
    messageId,
  );
  db.close();

  if (message) {
    console.log("📧 Message found:", message);
  } else {
    console.log("❌ Message not found");
  }

  return message || null;
}

// ============================================================================
// INSPECT CHAT - Single copyable report output
// ============================================================================

/**
 * Format a Unix timestamp (seconds) to ISO string
 */
function formatTimestamp(ts: number | undefined): string {
  if (!ts) return "N/A";
  return new Date(ts * 1000)
    .toISOString()
    .replace("T", " ")
    .replace("Z", " UTC");
}

/**
 * Truncate a string to a max length with ellipsis
 */
function truncate(str: string | undefined, maxLen: number): string {
  if (!str) return "N/A";
  if (str.length <= maxLen) return str;
  return str.substring(0, maxLen - 3) + "...";
}

/**
 * Inspect a chat and generate a formatted text report
 *
 * This function produces a single, easy-to-copy text report similar to the
 * backend inspect_chat.py script. The report can be printed to console or
 * downloaded as a text file.
 *
 * Usage in console:
 *   await window.inspectChat('chat-id')                    - Print report to console
 *   await window.inspectChat('chat-id', { download: true }) - Download as .txt file
 *
 * @param chatId - The chat ID to inspect
 * @param options - Optional configuration
 * @param options.download - If true, downloads report as a text file (default: false)
 * @returns The formatted report string
 */
export async function inspectChat(
  chatId: string,
  options: { download?: boolean } = {},
): Promise<string> {
  const db = await openDB();
  const lines: string[] = [];
  const separator = "=".repeat(100);
  const thinSeparator = "-".repeat(100);

  // Header
  lines.push("");
  lines.push(separator);
  lines.push("CLIENT CHAT INSPECTION REPORT (IndexedDB)");
  lines.push(separator);
  lines.push(`Chat ID: ${chatId}`);
  lines.push(`Generated at: ${new Date().toISOString()}`);
  lines.push(`Database: ${db.name} v${db.version}`);
  lines.push(`Object stores: ${Array.from(db.objectStoreNames).join(", ")}`);
  lines.push(separator);

  // Get chat metadata
  const chatMeta = await getFromStore<Record<string, unknown>>(
    db,
    CHATS_STORE,
    chatId,
  );

  lines.push("");
  lines.push(thinSeparator);
  lines.push("CHAT METADATA");
  lines.push(thinSeparator);

  if (chatMeta) {
    const messagesV = (chatMeta.messages_v as number) || 0;
    const titleV = (chatMeta.title_v as number) || 0;
    const draftV = (chatMeta.draft_v as number) || 0;

    lines.push(`  Chat ID:                     ${chatMeta.chat_id}`);
    lines.push(
      `  User ID:                     ${truncate(chatMeta.user_id as string, 40)}`,
    );
    lines.push(
      `  Created At:                  ${formatTimestamp(chatMeta.created_at as number)}`,
    );
    lines.push(
      `  Updated At:                  ${formatTimestamp(chatMeta.updated_at as number)}`,
    );
    lines.push(
      `  Last Message TS:             ${formatTimestamp(chatMeta.last_message_timestamp as number)}`,
    );
    lines.push(
      `  Last Edited Overall TS:      ${formatTimestamp(chatMeta.last_edited_overall_timestamp as number)}`,
    );
    lines.push("");
    lines.push(`  Messages Version (messages_v): ${messagesV}`);
    lines.push(`  Title Version (title_v):       ${titleV}`);
    lines.push(`  Draft Version (draft_v):       ${draftV}`);
    lines.push(
      `  Unread Count:                  ${chatMeta.unread_count ?? "N/A"}`,
    );
    lines.push(`  Pinned:                        ${chatMeta.pinned ?? false}`);
    lines.push("");
    lines.push(
      `  Is Private:                  ${chatMeta.is_private ?? false}`,
    );
    lines.push(`  Is Shared:                   ${chatMeta.is_shared ?? false}`);
    lines.push(`  Is Hidden:                   ${chatMeta.is_hidden ?? false}`);
    lines.push(
      `  Is Hidden Candidate:         ${chatMeta.is_hidden_candidate ?? false}`,
    );
    lines.push("");
    lines.push("  Encrypted Fields Present:");
    lines.push(
      `    ${chatMeta.encrypted_title ? "✓" : "✗"} Title ${chatMeta.encrypted_title ? `(${(chatMeta.encrypted_title as string).length} chars)` : ""}`,
    );
    lines.push(
      `    ${chatMeta.encrypted_chat_key ? "✓" : "✗"} Chat Key ${chatMeta.encrypted_chat_key ? `(${(chatMeta.encrypted_chat_key as string).length} chars)` : ""}`,
    );
    lines.push(
      `    ${chatMeta.encrypted_chat_summary ? "✓" : "✗"} Summary ${chatMeta.encrypted_chat_summary ? `(${(chatMeta.encrypted_chat_summary as string).length} chars)` : ""}`,
    );
    lines.push(
      `    ${chatMeta.encrypted_chat_tags ? "✓" : "✗"} Tags ${chatMeta.encrypted_chat_tags ? `(${(chatMeta.encrypted_chat_tags as string).length} chars)` : ""}`,
    );
    lines.push(
      `    ${chatMeta.encrypted_icon ? "✓" : "✗"} Icon ${chatMeta.encrypted_icon ? `(${(chatMeta.encrypted_icon as string).length} chars)` : ""}`,
    );
    lines.push(
      `    ${chatMeta.encrypted_category ? "✓" : "✗"} Category ${chatMeta.encrypted_category ? `(${(chatMeta.encrypted_category as string).length} chars)` : ""}`,
    );
    lines.push(
      `    ${chatMeta.encrypted_draft_md ? "✓" : "✗"} Draft ${chatMeta.encrypted_draft_md ? `(${(chatMeta.encrypted_draft_md as string).length} chars)` : ""}`,
    );
    lines.push(
      `    ${chatMeta.encrypted_follow_up_request_suggestions ? "✓" : "✗"} Follow-up Suggestions ${chatMeta.encrypted_follow_up_request_suggestions ? `(${(chatMeta.encrypted_follow_up_request_suggestions as string).length} chars)` : ""}`,
    );
    lines.push(
      `    ${chatMeta.encrypted_active_focus_id ? "✓" : "✗"} Active Focus ID ${chatMeta.encrypted_active_focus_id ? `(${(chatMeta.encrypted_active_focus_id as string).length} chars)` : ""}`,
    );

    // Attempt to decrypt active focus ID for display
    if (chatMeta.encrypted_active_focus_id) {
      try {
        const { chatDB } = await import("./db");
        const chatKey = chatDB.getChatKey(chatId);
        if (chatKey) {
          const { decryptWithChatKey } = await import("./cryptoService");
          const decryptedFocusId = await decryptWithChatKey(
            chatMeta.encrypted_active_focus_id as string,
            chatKey,
          );
          lines.push(`  Active Focus Mode:           ${decryptedFocusId}`);
        }
      } catch {
        lines.push(`  Active Focus Mode:           (decryption failed)`);
      }
    }
  } else {
    lines.push("  ❌ Chat NOT FOUND in IndexedDB");
  }

  // Get all messages for the chat
  const messages = await getAllFromIndex<Record<string, unknown>>(
    db,
    MESSAGES_STORE,
    "chat_id",
    chatId,
  );

  // Sort by created_at
  messages.sort((a, b) => (a.created_at as number) - (b.created_at as number));

  lines.push("");
  lines.push(thinSeparator);
  lines.push(`MESSAGES - Total: ${messages.length}`);
  lines.push(thinSeparator);

  // Calculate role distribution
  const roleCount: Record<string, number> = {};
  for (const msg of messages) {
    const role = (msg.role as string) || "unknown";
    roleCount[role] = (roleCount[role] || 0) + 1;
  }

  lines.push(`  Role Distribution: ${JSON.stringify(roleCount)}`);
  lines.push("");
  lines.push(`  Showing ${messages.length} messages:`);
  lines.push("");

  if (messages.length > 0) {
    messages.forEach((msg, i) => {
      const role = (msg.role as string) || "unknown";
      const roleIcon =
        role === "user" ? "👤" : role === "assistant" ? "🤖" : "❓";
      const created = formatTimestamp(msg.created_at as number);
      // Use client_message_id for display as that's what the UI references
      const clientMsgId =
        (msg.client_message_id as string) ||
        (msg.message_id as string) ||
        (msg.id as string);
      const serverId = (msg.id as string) || "N/A";

      lines.push(
        `    ${(i + 1).toString().padStart(2)}. ${roleIcon} [${role.padEnd(9)}] ${created}`,
      );
      lines.push(
        `       Server ID: ${truncate(serverId, 12)}  Client ID: ${truncate(clientMsgId, 30)}`,
      );

      // Content status
      const hasContent = !!msg.content;
      const hasEncrypted = !!msg.encrypted_content;
      const contentLen = hasEncrypted
        ? (msg.encrypted_content as string).length
        : hasContent
          ? (msg.content as string).length
          : 0;
      lines.push(
        `       Content: ${hasEncrypted ? "✓ encrypted" : hasContent ? "✓ plaintext" : "✗ missing"} (${contentLen} chars)`,
      );

      // Model info for assistant messages
      if (role === "assistant" && msg.encrypted_model) {
        lines.push(`       Model: ✓ (encrypted)`);
      }

      // Status if present
      if (msg.status) {
        lines.push(`       Status: ${msg.status}`);
      }
    });
  } else {
    lines.push("  ❌ No messages found for this chat");
  }

  // Get embeds for this chat using hashed_chat_id index
  // Embeds are linked to chats via hashed_chat_id (SHA256 hash of chat_id) for privacy
  const hashedChatId = await computeSHA256(chatId);
  const chatEmbeds = await getAllFromIndex<Record<string, unknown>>(
    db,
    EMBEDS_STORE,
    "hashed_chat_id",
    hashedChatId,
  );
  const totalEmbedsCount = await getStoreCount(db, EMBEDS_STORE);

  lines.push("");
  lines.push(thinSeparator);
  lines.push(
    `EMBEDS - Total: ${chatEmbeds.length} (${totalEmbedsCount} total in DB)`,
  );
  lines.push(thinSeparator);
  lines.push(`  Hashed Chat ID: ${hashedChatId.substring(0, 24)}...`);

  if (chatEmbeds.length > 0) {
    // Collect statistics
    const statusCount: Record<string, number> = {};
    const typeCount: Record<string, number> = {};
    for (const embed of chatEmbeds) {
      const status = (embed.status as string) || "unknown";
      const type = (embed.type as string) || "unknown";
      statusCount[status] = (statusCount[status] || 0) + 1;
      typeCount[type] = (typeCount[type] || 0) + 1;
    }
    lines.push(`  Status Distribution: ${JSON.stringify(statusCount)}`);
    lines.push(`  Type Distribution: ${JSON.stringify(typeCount)}`);

    // Sort by createdAt descending (most recent first)
    chatEmbeds.sort(
      (a, b) => ((b.createdAt as number) || 0) - ((a.createdAt as number) || 0),
    );

    // Show first few embeds
    const showCount = Math.min(10, chatEmbeds.length);
    lines.push("");
    lines.push(
      `  Showing ${showCount} of ${chatEmbeds.length} embeds (most recent first):`,
    );
    lines.push("");

    for (let i = 0; i < showCount; i++) {
      const embed = chatEmbeds[i];
      const embedId =
        (embed.embed_id as string) || (embed.contentRef as string);
      const type = (embed.type as string) || "unknown";
      const status = (embed.status as string) || "N/A";
      const hasEncryptedContent = !!embed.encrypted_content;
      const hasPlainContent = !!embed.content || !!embed.data;
      const createdAt = formatTimestamp(embed.createdAt as number);

      lines.push(
        `    ${(i + 1).toString().padStart(2)}. [${type.padEnd(15)}] ${truncate(embedId, 45)}`,
      );
      lines.push(`       Status: ${status} | Created: ${createdAt}`);
      lines.push(
        `       Content: ${hasEncryptedContent ? "✓ encrypted" : hasPlainContent ? "✓ plaintext" : "✗ missing"}`,
      );

      // Show app/skill metadata for app-skill-use embeds
      if (embed.app_id || embed.skill_id) {
        lines.push(
          `       App: ${embed.app_id || "N/A"} | Skill: ${embed.skill_id || "N/A"}`,
        );
      }

      // Show child embed_ids if present
      if (
        embed.embed_ids &&
        Array.isArray(embed.embed_ids) &&
        embed.embed_ids.length > 0
      ) {
        lines.push(
          `       Child Embeds: ${(embed.embed_ids as string[]).length} (${(
            embed.embed_ids as string[]
          )
            .slice(0, 3)
            .map((id) => truncate(id, 12))
            .join(
              ", ",
            )}${(embed.embed_ids as string[]).length > 3 ? "..." : ""})`,
        );
      }
    }

    if (chatEmbeds.length > showCount) {
      lines.push("");
      lines.push(`    ... and ${chatEmbeds.length - showCount} more embeds`);
    }

    // Admin-only: decode embeds and show field inventory (improvement C)
    const isAdmin = await isCurrentUserAdmin();
    if (isAdmin) {
      lines.push("");
      lines.push(thinSeparator);
      lines.push("EMBED FIELD INVENTORY (admin-only, privacy-safe)");
      lines.push(thinSeparator);

      try {
        const { resolveEmbed, decodeToonContent } =
          await import("./embedResolver");
        let decodedCount = 0;
        let failedCount = 0;
        const allAnomalies: string[] = [];

        for (let i = 0; i < Math.min(showCount, chatEmbeds.length); i++) {
          const embed = chatEmbeds[i];
          const embedId =
            (embed.embed_id as string) || (embed.contentRef as string);
          if (!embedId) continue;

          const resolved = await resolveEmbed(embedId);
          if (resolved?.content) {
            try {
              const decoded = await decodeToonContent(resolved.content);
              if (decoded && typeof decoded === "object") {
                decodedCount++;
                const decodedObj = decoded as Record<string, unknown>;
                const inventory = buildFieldInventory(decodedObj);
                const anomalies = detectEmbedAnomalies(decodedObj, embed);
                allAnomalies.push(...anomalies);

                lines.push("");
                lines.push(
                  `    ${(i + 1).toString().padStart(2)}. embed-${truncate(embedId, 12)}:`,
                );
                lines.push(...formatFieldInventoryLines(inventory, anomalies));
              } else {
                failedCount++;
              }
            } catch {
              failedCount++;
            }
          } else {
            failedCount++;
          }
        }

        lines.push("");
        lines.push(
          `  Summary: ${decodedCount} decoded, ${failedCount} failed/unavailable`,
        );
        if (allAnomalies.length > 0) {
          lines.push(`  Total anomalies found: ${allAnomalies.length}`);
        } else {
          lines.push("  No anomalies detected");
        }
      } catch (e) {
        lines.push(`  Error generating field inventory: ${e}`);
      }
    }
  } else {
    lines.push("");
    lines.push("  No embeds found for this chat");
    lines.push("  (Embeds are queried by hashed_chat_id index)");
  }

  // Also show embed keys for this chat
  const chatEmbedKeys = await getAllFromIndex<Record<string, unknown>>(
    db,
    EMBED_KEYS_STORE,
    "hashed_chat_id",
    hashedChatId,
  );
  const totalEmbedKeysCount = await getStoreCount(db, EMBED_KEYS_STORE);

  lines.push("");
  lines.push(thinSeparator);
  lines.push(
    `EMBED KEYS - Total: ${chatEmbedKeys.length} for this chat (${totalEmbedKeysCount} total in DB)`,
  );
  lines.push(thinSeparator);

  if (chatEmbedKeys.length > 0) {
    const keyTypeCount: Record<string, number> = {};
    for (const key of chatEmbedKeys) {
      const keyType = (key.key_type as string) || "unknown";
      keyTypeCount[keyType] = (keyTypeCount[keyType] || 0) + 1;
    }
    lines.push(`  Key Type Distribution: ${JSON.stringify(keyTypeCount)}`);
    lines.push(`  (Keys enable decryption of embed content)`);
  } else {
    lines.push("  No embed keys found for this chat");
  }

  // Version consistency analysis
  const messagesV = chatMeta ? (chatMeta.messages_v as number) || 0 : 0;
  const actualMessageCount = messages.length;

  lines.push("");
  lines.push(thinSeparator);
  lines.push("VERSION CONSISTENCY CHECK");
  lines.push(thinSeparator);
  lines.push(`  Messages Version (messages_v): ${messagesV}`);
  lines.push(`  Actual Message Count:          ${actualMessageCount}`);

  // Check consistency - if messages_v is 0 but there are messages, that's suspicious
  // Also if messages_v is much higher than actual count, messages may be missing
  if (messagesV === 0 && actualMessageCount > 0) {
    lines.push(
      `  ⚠️  INCONSISTENT: messages_v is 0 but ${actualMessageCount} messages exist!`,
    );
    lines.push(`     This suggests sync metadata wasn't updated properly.`);
  } else if (messagesV > actualMessageCount + 1) {
    lines.push(
      `  ⚠️  POSSIBLE MISSING MESSAGES: messages_v=${messagesV} but only ${actualMessageCount} in IndexedDB`,
    );
  } else {
    lines.push(`  ✅ Versions appear consistent`);
  }

  // Footer
  lines.push("");
  lines.push(separator);
  lines.push("END OF CLIENT REPORT");
  lines.push(separator);
  lines.push("");

  db.close();

  const report = lines.join("\n");

  // Output to console as a single string for easy copying
  console.log(report);

  // Optionally download as file
  if (options.download) {
    const blob = new Blob([report], { type: "text/plain" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `chat_inspection_${chatId}_${Date.now()}.txt`;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
    console.log("📥 Report downloaded!");
  }

  return report;
}

// ============================================================================
// EMBED INSPECTION
// ============================================================================

/**
 * Inspect a specific embed by its embed_id
 * Retrieves embed data from IndexedDB and in-memory cache
 *
 * @param embedId - The embed_id to inspect
 * @param options - Optional configuration
 * @param options.download - If true, downloads report as a text file (default: false)
 * @returns The formatted report string
 *
 * Usage in browser console:
 *   await window.inspectEmbed('embed-uuid')
 *   await window.inspectEmbed('embed-uuid', { download: true })
 */
export async function inspectEmbed(
  embedId: string,
  options: { download?: boolean } = {},
): Promise<string> {
  const db = await openDB();
  const lines: string[] = [];
  const separator = "=".repeat(100);
  const thinSeparator = "-".repeat(100);

  // Header
  lines.push("");
  lines.push(separator);
  lines.push("CLIENT EMBED INSPECTION REPORT (IndexedDB)");
  lines.push(separator);
  lines.push(`Embed ID: ${embedId}`);
  lines.push(`Generated at: ${new Date().toISOString()}`);
  lines.push(`Database: ${db.name} v${db.version}`);
  lines.push(separator);

  // Get embed directly from store by ID
  // IMPORTANT: IndexedDB embeds are stored with contentRef key "embed:{embed_id}"
  // so we need to use the prefixed key for lookup
  const contentRef = `embed:${embedId}`;
  const embed = await getFromStore<Record<string, unknown>>(
    db,
    EMBEDS_STORE,
    contentRef,
  );

  lines.push("");
  lines.push(thinSeparator);
  lines.push("EMBED DATA (IndexedDB)");
  lines.push(thinSeparator);

  if (embed) {
    lines.push(`  Embed ID:           ${embed.embed_id || embedId}`);
    lines.push(`  Type:               ${embed.type || "N/A"}`);
    lines.push(`  Status:             ${embed.status || "N/A"}`);
    lines.push(`  App ID:             ${embed.app_id || "N/A"}`);
    lines.push(`  Skill ID:           ${embed.skill_id || "N/A"}`);
    lines.push(`  Query:              ${embed.query || "N/A"}`);
    lines.push(`  Provider:           ${embed.provider || "N/A"}`);
    lines.push(
      `  Hashed Chat ID:     ${embed.hashed_chat_id ? truncate(embed.hashed_chat_id as string, 30) : "N/A"}`,
    );
    lines.push(
      `  Created At:         ${formatTimestamp(embed.createdAt as number)}`,
    );
    lines.push(
      `  Updated At:         ${formatTimestamp(embed.updatedAt as number)}`,
    );
    lines.push("");
    lines.push("  Content Fields Present:");
    lines.push(
      `    ${embed.encrypted_content ? "✓" : "✗"} Encrypted Content ${embed.encrypted_content ? `(${(embed.encrypted_content as string).length} chars)` : ""}`,
    );
    lines.push(
      `    ${embed.content ? "✓" : "✗"} Content (TOON) ${embed.content ? `(${typeof embed.content === "string" ? (embed.content as string).length : "object"})` : ""}`,
    );
    lines.push(
      `    ${embed.data ? "✓" : "✗"} Data ${embed.data ? `(${typeof embed.data === "string" ? (embed.data as string).length : "object"})` : ""}`,
    );

    // Show embed_ids if present (for app_skill_use embeds that have child embeds)
    if (embed.embed_ids && Array.isArray(embed.embed_ids)) {
      lines.push("");
      lines.push(
        `  Child Embed IDs (${(embed.embed_ids as string[]).length}):`,
      );
      for (const childId of embed.embed_ids as string[]) {
        lines.push(`    - ${childId}`);
      }
    }

    // Show raw data structure (limited to avoid huge output)
    lines.push("");
    lines.push("  Raw Data (truncated):");
    const rawJson = JSON.stringify(embed, null, 2);
    const truncatedJson =
      rawJson.length > 2000
        ? rawJson.substring(0, 2000) + "\n... [truncated]"
        : rawJson;
    for (const line of truncatedJson.split("\n")) {
      lines.push(`    ${line}`);
    }
  } else {
    lines.push("  ❌ Embed NOT FOUND in IndexedDB");
    lines.push("");
    lines.push("  Possible reasons:");
    lines.push('    1. Embed is still "processing" (stored in memory only)');
    lines.push("    2. Embed ID is incorrect");
    lines.push("    3. Embed was never stored for this chat");
  }

  // Try to get from in-memory cache (embedStore)
  lines.push("");
  lines.push(thinSeparator);
  lines.push("IN-MEMORY CACHE STATUS");
  lines.push(thinSeparator);

  try {
    // Dynamic import to avoid circular dependencies
    const { embedStore } = await import("./embedStore");
    // embedStore.get() expects contentRef format "embed:{embed_id}"
    const inMemoryEmbed = await embedStore.get(contentRef);

    if (inMemoryEmbed) {
      lines.push(`  ✓ Found in embedStore memory cache`);
      lines.push(`  Status:             ${inMemoryEmbed.status || "N/A"}`);
      lines.push(`  Has Content:        ${inMemoryEmbed.content ? "✓" : "✗"}`);
      lines.push(
        `  Has Encrypted:      ${inMemoryEmbed.encrypted_content ? "✓" : "✗"}`,
      );
    } else {
      lines.push(`  ✗ NOT found in embedStore memory cache`);
    }
  } catch (e) {
    lines.push(`  ⚠️ Could not check in-memory cache: ${e}`);
  }

  // Try to resolve and decode the embed content
  lines.push("");
  lines.push(thinSeparator);
  lines.push("RESOLVED & DECODED CONTENT");
  lines.push(thinSeparator);

  try {
    const { resolveEmbed, decodeToonContent } = await import("./embedResolver");
    const resolvedEmbed = await resolveEmbed(embedId);

    if (resolvedEmbed) {
      lines.push(`  ✓ Resolved embed successfully`);
      lines.push(`  Resolved Status:    ${resolvedEmbed.status || "N/A"}`);

      if (resolvedEmbed.content) {
        try {
          const decoded = await decodeToonContent(resolvedEmbed.content);
          if (decoded) {
            lines.push("");
            lines.push("  Decoded TOON Content:");
            lines.push(`    app_id:           ${decoded.app_id || "N/A"}`);
            lines.push(`    skill_id:         ${decoded.skill_id || "N/A"}`);
            lines.push(`    query:            ${decoded.query || "N/A"}`);
            lines.push(`    provider:         ${decoded.provider || "N/A"}`);
            lines.push(`    status:           ${decoded.status || "N/A"}`);
            lines.push(`    task_id:          ${decoded.task_id || "N/A"}`);

            // Show results count if present
            if (decoded.results && Array.isArray(decoded.results)) {
              lines.push(
                `    results:          ${(decoded.results as unknown[]).length} items`,
              );
            }

            // Show other fields
            const knownFields = [
              "app_id",
              "skill_id",
              "query",
              "provider",
              "status",
              "task_id",
              "results",
            ];
            const otherFields = Object.keys(decoded).filter(
              (k) => !knownFields.includes(k),
            );
            if (otherFields.length > 0) {
              lines.push(`    other fields:     ${otherFields.join(", ")}`);
            }

            // Admin-only: privacy-safe field inventory + anomaly detection (improvement C)
            const isAdmin = await isCurrentUserAdmin();
            if (isAdmin) {
              const decodedObj = decoded as Record<string, unknown>;
              const inventory = buildFieldInventory(decodedObj);
              const anomalies = detectEmbedAnomalies(decodedObj, embed || {});

              lines.push("");
              lines.push("  FIELD INVENTORY (admin-only, privacy-safe):");
              lines.push(`    Total fields: ${inventory.totalFields}`);

              // Field type descriptions
              for (const [key, typeDesc] of Object.entries(
                inventory.fieldTypes,
              )) {
                if (key in inventory.keyMetadata) continue;
                lines.push(`    ${key.padEnd(22)} : ${typeDesc}`);
              }
              if (inventory.totalFields > MAX_FIELD_INVENTORY_ITEMS) {
                lines.push(
                  `    ... and ${inventory.totalFields - MAX_FIELD_INVENTORY_ITEMS} more fields`,
                );
              }

              if (anomalies.length > 0) {
                lines.push("");
                lines.push("  ANOMALIES:");
                for (const a of anomalies) {
                  lines.push(`    * ${a}`);
                }
              } else {
                lines.push("");
                lines.push("  No anomalies detected");
              }
            }
          } else {
            lines.push("  Could not decode TOON content");
          }
        } catch (decodeError) {
          lines.push(`  Error decoding content: ${decodeError}`);
        }
      } else {
        lines.push("  Resolved embed has no content field");
      }
    } else {
      lines.push(`  Could not resolve embed`);
    }
  } catch (e) {
    lines.push(`  Error resolving embed: ${e}`);
  }

  // Footer
  lines.push("");
  lines.push(separator);
  lines.push("END OF EMBED REPORT");
  lines.push(separator);
  lines.push("");

  db.close();

  const report = lines.join("\n");

  // Output to console as a single string for easy copying
  console.log(report);

  // Optionally download as file
  if (options.download) {
    const blob = new Blob([report], { type: "text/plain" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `embed_inspection_${embedId}_${Date.now()}.txt`;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
    console.log("📥 Report downloaded!");
  }

  return report;
}

// ============================================================================
// INITIALIZATION - Expose to window object
// ============================================================================

/**
 * Initialize debug utilities and expose to window object
 * Called once when the module is imported
 */
export function initDebugUtils(): void {
  if (typeof window !== "undefined") {
    // Expose read-only debug functions to window for console access
    (window as unknown as Record<string, unknown>).inspectChat = inspectChat;
    (window as unknown as Record<string, unknown>).inspectEmbed = inspectEmbed;
    (window as unknown as Record<string, unknown>).debugChat = debugChat;
    (window as unknown as Record<string, unknown>).debugAllChats =
      debugAllChats;
    (window as unknown as Record<string, unknown>).debugGetMessage =
      debugGetMessage;

    console.info(
      "%c🔧 Debug utilities loaded!%c\n" +
        "Available commands (read-only):\n" +
        '  • await window.inspectChat("chat-id") - Generate copyable inspection report\n' +
        '  • await window.inspectChat("chat-id", {download: true}) - Download report as .txt\n' +
        '  • await window.inspectEmbed("embed-id") - Generate embed inspection report\n' +
        '  • await window.debugChat("chat-id") - Verbose console output\n' +
        "  • await window.debugAllChats() - List all chats with consistency check\n" +
        '  • await window.debugGetMessage("message-id") - Get raw message data',
      "color: #4CAF50; font-weight: bold; font-size: 14px;",
      "color: #888; font-size: 12px;",
    );
  }
}
