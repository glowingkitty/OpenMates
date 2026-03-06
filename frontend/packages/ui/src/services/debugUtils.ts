/**
 * Debug Utilities for Chat / Embed Inspection
 *
 * Exposes a unified `window.debug` namespace for debugging via the browser console.
 * All operations are read-only — they never modify IndexedDB or any store state.
 * For admin users, embed inspection includes a privacy-safe field inventory and anomaly detection.
 *
 * Usage in browser console:
 *   window.debug()                         — quick client health check
 *   window.debug.help()                    — show all available commands
 *   await window.debug.chat('chat-id')     — copyable chat inspection report
 *   await window.debug.embed('embed-id')   — copyable embed inspection report
 *   await window.debug.decrypt('embed-id') — decrypt and show raw embed content
 *   await window.debug.chats()             — list all chats with consistency check
 *   await window.debug.message('msg-id')   — raw message data
 *   window.debug.logs(20)                  — last N console logs (filter: logs(20, 'error'))
 *   window.debug.errors(50)                — last N errors+warnings (survives noise)
 *   await window.debug.state()             — current store state snapshot
 *
 * Architecture context: See docs/architecture/embed-encryption.md
 */

// Database constants (must match db.ts)
const DB_NAME = "chats_db";
const CHATS_STORE = "chats";
const MESSAGES_STORE = "messages";
const EMBEDS_STORE = "embeds";
const EMBED_KEYS_STORE = "embed_keys";
const NEW_CHAT_SUGGESTIONS_STORE = "new_chat_suggestions";
const APP_SETTINGS_MEMORIES_STORE = "app_settings_memories";

// Field inventory constants
const MAX_FIELD_INVENTORY_ITEMS = 30;
const MAX_ANOMALIES_PER_EMBED = 5;
const MIN_VALID_TIMESTAMP_YEAR = 2025;
const MAX_HEALTH_ITEMS_TO_SHOW = 8;
const HEALTHY_BANNER_COLOR = "#16a34a";
const UNHEALTHY_BANNER_COLOR = "#dc2626";
const HEALTH_BANNER_STYLE = "font-weight: 700; font-size: 13px;";

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

function parseTimestampForHealth(value: unknown): Date | null {
  if (value === null || value === undefined || value === "") return null;

  if (typeof value === "number") {
    const seconds = value > 1_000_000_000_000 ? value / 1000 : value;
    const date = new Date(seconds * 1000);
    return Number.isNaN(date.getTime()) ? null : date;
  }

  if (typeof value === "string") {
    const trimmed = value.trim();
    if (!trimmed) return null;
    if (/^\d+$/.test(trimmed)) {
      const asNumber = Number(trimmed);
      const seconds = asNumber > 1_000_000_000_000 ? asNumber / 1000 : asNumber;
      const date = new Date(seconds * 1000);
      return Number.isNaN(date.getTime()) ? null : date;
    }

    const date = new Date(trimmed);
    return Number.isNaN(date.getTime()) ? null : date;
  }

  return null;
}

function collectTimestampIssue(
  label: string,
  value: unknown,
  issues: string[],
): void {
  if (value === null || value === undefined || value === "") return;

  const parsed = parseTimestampForHealth(value);
  if (!parsed) {
    issues.push(`${label} timestamp is malformed: ${String(value)}`);
    return;
  }

  if (parsed.getUTCFullYear() < MIN_VALID_TIMESTAMP_YEAR) {
    issues.push(
      `${label} timestamp is before ${MIN_VALID_TIMESTAMP_YEAR}: ${parsed.toISOString()}`,
    );
  }
}

function buildClientChatHealthSummary(params: {
  chatMeta: Record<string, unknown> | undefined;
  messages: Record<string, unknown>[];
  embeds: Record<string, unknown>[];
  embedKeys: Record<string, unknown>[];
  embedDecodeHealth?: { checkedCount: number; failedCount: number };
}): { isHealthy: boolean; issues: string[]; warnings: string[] } {
  const issues: string[] = [];
  const warnings: string[] = [];
  const { chatMeta, messages, embeds, embedKeys, embedDecodeHealth } = params;

  if (!chatMeta) {
    issues.push("chat metadata missing in IndexedDB");
  } else {
    collectTimestampIssue("chat.created_at", chatMeta.created_at, issues);
    collectTimestampIssue("chat.updated_at", chatMeta.updated_at, issues);
    collectTimestampIssue(
      "chat.last_message_timestamp",
      chatMeta.last_message_timestamp,
      issues,
    );
    collectTimestampIssue(
      "chat.last_edited_overall_timestamp",
      chatMeta.last_edited_overall_timestamp,
      issues,
    );

    const messagesV = Number(chatMeta.messages_v || 0);
    if (messagesV !== messages.length) {
      issues.push(
        `messages_v (${messagesV}) does not match actual message count (${messages.length})`,
      );
    }
  }

  let missingMessageContent = 0;
  for (const message of messages) {
    collectTimestampIssue("message.created_at", message.created_at, issues);
    const role = String(message.role || "");
    const hasAnyContent = Boolean(message.encrypted_content || message.content);
    if ((role === "user" || role === "assistant") && !hasAnyContent) {
      missingMessageContent += 1;
    }
  }
  if (missingMessageContent > 0) {
    issues.push(
      `${missingMessageContent} user/assistant messages missing content`,
    );
  }

  let embedsInError = 0;
  let finishedEmbedsMissingContent = 0;
  let rootEmbedsCount = 0;
  for (const embed of embeds) {
    collectTimestampIssue("embed.createdAt", embed.createdAt, issues);
    collectTimestampIssue("embed.updatedAt", embed.updatedAt, issues);

    const status = String(embed.status || "").toLowerCase();
    if (status === "error") embedsInError += 1;
    if (!embed.parent_embed_id) rootEmbedsCount += 1;

    const hasAnyContent = Boolean(
      embed.encrypted_content || embed.content || embed.data,
    );
    if (status === "finished" && !hasAnyContent) {
      finishedEmbedsMissingContent += 1;
    }
  }

  if (embedsInError > 0) {
    warnings.push(`${embedsInError} embed(s) are currently in error status`);
  }
  if (finishedEmbedsMissingContent > 0) {
    issues.push(
      `${finishedEmbedsMissingContent} finished embed(s) missing content payload`,
    );
  }

  if (rootEmbedsCount > 0 && embedKeys.length === 0) {
    issues.push("root embeds exist but no embed keys are stored for this chat");
  }

  if (embedDecodeHealth && embedDecodeHealth.checkedCount > 0) {
    if (embedDecodeHealth.failedCount > 0) {
      issues.push(
        `${embedDecodeHealth.failedCount}/${embedDecodeHealth.checkedCount} checked embeds failed client-side decryption/decoding`,
      );
    }
  }

  return { isHealthy: issues.length === 0, issues, warnings };
}

type EmbedDecodeAttempt = {
  embed: Record<string, unknown>;
  embedId: string;
  decoded: Record<string, unknown> | null;
  error: string | null;
  keyDebug: EmbedKeyDebugInfo | null;
};

type EmbedKeyDebugInfo = {
  total: number;
  keyTypes: Record<string, number>;
  minEncryptedKeyLength: number;
  maxEncryptedKeyLength: number;
};

function buildEmbedKeyDebugMap(
  embedKeys: Record<string, unknown>[],
): Record<string, EmbedKeyDebugInfo> {
  const keyMap: Record<string, EmbedKeyDebugInfo> = {};

  for (const key of embedKeys) {
    const hashedEmbedId = String(key.hashed_embed_id || "");
    if (!hashedEmbedId) continue;

    if (!keyMap[hashedEmbedId]) {
      keyMap[hashedEmbedId] = {
        total: 0,
        keyTypes: {},
        minEncryptedKeyLength: Number.MAX_SAFE_INTEGER,
        maxEncryptedKeyLength: 0,
      };
    }

    const entry = keyMap[hashedEmbedId];
    const keyType = String(key.key_type || "unknown");
    const encryptedKeyLength = String(key.encrypted_embed_key || "").length;

    entry.total += 1;
    entry.keyTypes[keyType] = (entry.keyTypes[keyType] || 0) + 1;
    entry.minEncryptedKeyLength = Math.min(
      entry.minEncryptedKeyLength,
      encryptedKeyLength,
    );
    entry.maxEncryptedKeyLength = Math.max(
      entry.maxEncryptedKeyLength,
      encryptedKeyLength,
    );
  }

  for (const value of Object.values(keyMap)) {
    if (value.minEncryptedKeyLength === Number.MAX_SAFE_INTEGER) {
      value.minEncryptedKeyLength = 0;
    }
  }

  return keyMap;
}

async function collectClientEmbedDecodeHealth(
  embeds: Record<string, unknown>[],
  maxChecks: number,
  embedKeyDebugByHashedEmbedId: Record<string, EmbedKeyDebugInfo>,
): Promise<{
  checkedCount: number;
  decodedCount: number;
  failedCount: number;
  attempts: EmbedDecodeAttempt[];
  globalError: string | null;
}> {
  const attempts: EmbedDecodeAttempt[] = [];
  if (maxChecks <= 0 || embeds.length === 0) {
    return {
      checkedCount: 0,
      decodedCount: 0,
      failedCount: 0,
      attempts,
      globalError: null,
    };
  }

  try {
    const { resolveEmbed, decodeToonContent } = await import("./embedResolver");

    let checkedCount = 0;
    let decodedCount = 0;
    let failedCount = 0;

    for (let i = 0; i < Math.min(maxChecks, embeds.length); i++) {
      const embed = embeds[i];
      const embedId = String(embed.embed_id || embed.contentRef || "").replace(
        /^embed:/,
        "",
      );
      const status = String(embed.status || "").toLowerCase();
      const hasAnyContent = Boolean(
        embed.encrypted_content || embed.content || embed.data,
      );

      if (
        !embedId ||
        !hasAnyContent ||
        (status !== "finished" && status !== "activated")
      ) {
        continue;
      }

      checkedCount += 1;

      try {
        const hashedEmbedId = await computeSHA256(embedId);
        const keyDebug = embedKeyDebugByHashedEmbedId[hashedEmbedId] || null;

        const resolved = await resolveEmbed(embedId);
        if (!resolved?.content) {
          failedCount += 1;
          attempts.push({
            embed,
            embedId,
            decoded: null,
            error: "resolved embed has no content",
            keyDebug,
          });
          continue;
        }

        const decoded = await decodeToonContent(resolved.content);
        if (decoded && typeof decoded === "object") {
          decodedCount += 1;
          attempts.push({
            embed,
            embedId,
            decoded: decoded as Record<string, unknown>,
            error: null,
            keyDebug,
          });
        } else {
          failedCount += 1;
          attempts.push({
            embed,
            embedId,
            decoded: null,
            error: "decoded content is empty or invalid",
            keyDebug,
          });
        }
      } catch (error) {
        failedCount += 1;
        attempts.push({
          embed,
          embedId,
          decoded: null,
          error: error instanceof Error ? error.message : String(error),
          keyDebug: null,
        });
      }
    }

    return {
      checkedCount,
      decodedCount,
      failedCount,
      attempts,
      globalError: null,
    };
  } catch (error) {
    return {
      checkedCount: 0,
      decodedCount: 0,
      failedCount: 0,
      attempts,
      globalError: error instanceof Error ? error.message : String(error),
    };
  }
}

function buildClientEmbedHealthSummary(params: {
  embed: Record<string, unknown> | undefined;
  childEmbeds: Array<Record<string, unknown> | undefined>;
}): { isHealthy: boolean; issues: string[]; warnings: string[] } {
  const issues: string[] = [];
  const warnings: string[] = [];
  const { embed, childEmbeds } = params;

  if (!embed) {
    issues.push("embed record not found in IndexedDB");
    return { isHealthy: false, issues, warnings };
  }

  collectTimestampIssue("embed.createdAt", embed.createdAt, issues);
  collectTimestampIssue("embed.updatedAt", embed.updatedAt, issues);

  const embedStatus = String(embed.status || "").toLowerCase();
  if (embedStatus === "error") issues.push("embed status is error");
  else if (embedStatus === "processing")
    warnings.push("embed is still processing");

  const hasAnyContent = Boolean(
    embed.encrypted_content || embed.content || embed.data,
  );
  if (!hasAnyContent) {
    issues.push("embed has no encrypted_content/content/data payload");
  }

  let childMissing = 0;
  let childErrors = 0;
  for (const child of childEmbeds) {
    if (!child) {
      childMissing += 1;
      continue;
    }
    collectTimestampIssue("child_embed.createdAt", child.createdAt, issues);
    collectTimestampIssue("child_embed.updatedAt", child.updatedAt, issues);
    if (String(child.status || "").toLowerCase() === "error") {
      childErrors += 1;
    }
  }

  if (childMissing > 0) {
    issues.push(
      `${childMissing} child embed record(s) referenced but missing locally`,
    );
  }
  if (childErrors > 0) {
    warnings.push(
      `${childErrors} child embed(s) are currently in error status`,
    );
  }

  return { isHealthy: issues.length === 0, issues, warnings };
}

function logHealthCheckBanner(
  subject: "CHAT" | "EMBED",
  isHealthy: boolean,
): void {
  const color = isHealthy ? HEALTHY_BANNER_COLOR : UNHEALTHY_BANNER_COLOR;
  const status = isHealthy ? "HEALTHY" : "ISSUES DETECTED";
  const icon = isHealthy ? "🟢" : "🔴";
  console.log(
    `%c${icon} CLIENT ${subject} HEALTH CHECK: ${status}`,
    `${HEALTH_BANNER_STYLE} color: ${color};`,
  );
}

function logFailedEmbedDecryptionBanner(attempts: EmbedDecodeAttempt[]): void {
  const failedAttempts = attempts.filter((attempt) => !attempt.decoded);
  if (failedAttempts.length === 0) return;

  console.error(
    `%c🔴 EMBED DECRYPTION FAILURES (${failedAttempts.length})`,
    "font-weight: 700; font-size: 13px; color: #dc2626;",
  );

  for (const failed of failedAttempts) {
    const keyInfo = failed.keyDebug
      ? `keys=${failed.keyDebug.total} types=${JSON.stringify(failed.keyDebug.keyTypes)} enc_len=${failed.keyDebug.minEncryptedKeyLength}-${failed.keyDebug.maxEncryptedKeyLength}`
      : "keys=unknown";
    console.error(
      `%c  • embed=${failed.embedId} error=${failed.error || "unknown"} ${keyInfo}`,
      "color: #ef4444; font-weight: 600;",
    );
  }
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

// ============================================================================
// CHAT FIELD DECRYPTION FOR DEBUG REPORTS
// ============================================================================

/** Result of attempting to decrypt a single encrypted field */
type FieldDecryptResult = {
  field: string;
  success: boolean;
  /** First 40 chars of decrypted value (or error message) */
  preview: string;
};

/** Overall decryption report for a chat */
type ChatDecryptionReport = {
  chatKeyAvailable: boolean;
  chatKeyFingerprint: string;
  /** Full 64-char hex representation of the 32-byte chat key */
  chatKeyFull?: string;
  chatKeySource: "cache" | "unwrapped" | "none";
  metadataFields: FieldDecryptResult[];
  messageFields: {
    messageIndex: number;
    role: string;
    success: boolean;
    error?: string;
  }[];
};

/**
 * Attempt to decrypt all encrypted fields on a chat for debug inspection.
 * Returns a structured report of what succeeded and what failed.
 */
async function attemptChatDecryption(
  chatId: string,
  chatMeta: Record<string, unknown> | undefined,
  messages: Record<string, unknown>[],
): Promise<ChatDecryptionReport> {
  const report: ChatDecryptionReport = {
    chatKeyAvailable: false,
    chatKeyFingerprint: "N/A",
    chatKeySource: "none",
    metadataFields: [],
    messageFields: [],
  };

  if (!chatMeta) return report;

  // Step 1: Obtain the chat key
  let chatKey: Uint8Array | null = null;
  try {
    const { chatDB } = await import("./db");
    chatKey = chatDB.getChatKey(chatId);
    if (chatKey) {
      report.chatKeySource = "cache";
    }
  } catch {
    // chatDB not available
  }

  // If not in cache, try to unwrap from encrypted_chat_key
  if (!chatKey && chatMeta.encrypted_chat_key) {
    try {
      const { decryptChatKeyWithMasterKey } = await import("./cryptoService");
      chatKey = await decryptChatKeyWithMasterKey(
        chatMeta.encrypted_chat_key as string,
      );
      if (chatKey) {
        report.chatKeySource = "unwrapped";
      }
    } catch {
      // Master key not available
    }
  }

  if (!chatKey) {
    report.chatKeyAvailable = false;
    report.chatKeyFingerprint = "N/A (no key available)";
    return report;
  }

  report.chatKeyAvailable = true;
  // Full 32-byte hex key — shown by default; callers can pass hideKeys=true to mask it
  const keyHexFull = Array.from(chatKey)
    .map((b) => b.toString(16).padStart(2, "0"))
    .join("");
  report.chatKeyFull = keyHexFull;
  const keyHexShort = keyHexFull.slice(0, 16);
  report.chatKeyFingerprint = `${keyHexShort}... (${chatKey.length} bytes, source: ${report.chatKeySource})`;

  // Step 2: Try decrypting each chat metadata field
  const { decryptWithChatKey } = await import("./cryptoService");

  const encryptedMetadataFields: Array<{ field: string; key: string }> = [
    { field: "Title", key: "encrypted_title" },
    { field: "Category", key: "encrypted_category" },
    { field: "Icon", key: "encrypted_icon" },
    { field: "Summary", key: "encrypted_chat_summary" },
    { field: "Tags", key: "encrypted_chat_tags" },
    { field: "Draft", key: "encrypted_draft_md" },
    {
      field: "Follow-up Suggestions",
      key: "encrypted_follow_up_request_suggestions",
    },
    { field: "Active Focus ID", key: "encrypted_active_focus_id" },
  ];

  for (const { field, key } of encryptedMetadataFields) {
    const encryptedValue = chatMeta[key] as string | undefined;
    if (!encryptedValue) {
      // Field not present — not an error, just absent
      continue;
    }

    try {
      const decrypted = await decryptWithChatKey(encryptedValue, chatKey, {
        chatId,
        fieldName: field,
      });
      if (decrypted !== null) {
        const preview =
          decrypted.length > 40
            ? decrypted.substring(0, 40) + "..."
            : decrypted;
        report.metadataFields.push({ field, success: true, preview });
      } else {
        report.metadataFields.push({
          field,
          success: false,
          preview: "decryption returned null",
        });
      }
    } catch (error) {
      report.metadataFields.push({
        field,
        success: false,
        preview: error instanceof Error ? error.message : String(error),
      });
    }
  }

  // Step 3: Try decrypting message content
  for (let i = 0; i < messages.length; i++) {
    const msg = messages[i];
    const role = (msg.role as string) || "unknown";
    const encryptedContent = msg.encrypted_content as string | undefined;

    if (!encryptedContent) {
      // Message has plaintext content or no content at all
      if (msg.content) {
        report.messageFields.push({ messageIndex: i + 1, role, success: true });
      }
      continue;
    }

    try {
      const decrypted = await decryptWithChatKey(encryptedContent, chatKey, {
        chatId,
        fieldName: `message[${i}].content`,
      });
      report.messageFields.push({
        messageIndex: i + 1,
        role,
        success: decrypted !== null,
        error: decrypted === null ? "decryption returned null" : undefined,
      });
    } catch (error) {
      report.messageFields.push({
        messageIndex: i + 1,
        role,
        success: false,
        error: error instanceof Error ? error.message : String(error),
      });
    }
  }

  return report;
}

/**
 * Inspect a chat and generate a formatted text report.
 *
 * By default, healthy chats show a concise summary. Unhealthy chats show full details.
 * Use { verbose: true } to always show the full report.
 *
 * Usage in console:
 *   await window.debug.chat('chat-id')                         — concise if healthy
 *   await window.debug.chat('chat-id', { verbose: true })      — always full report
 *   await window.debug.chat('chat-id', { download: true })     — download as .txt (always verbose)
 *
 * @param chatId - The chat ID to inspect
 * @param options - Optional configuration
 * @param options.download - If true, downloads report as a text file (default: false)
 * @param options.verbose - If true, always shows full report (default: false)
 * @returns The formatted report string
 */
export async function inspectChat(
  chatId: string,
  options: { download?: boolean; verbose?: boolean; hideKeys?: boolean } = {},
): Promise<string> {
  const forceVerbose = options.verbose || options.download || false;
  const hideKeys = options.hideKeys ?? false;
  const db = await openDB();

  // ---- Gather all data ----
  const chatMeta = await getFromStore<Record<string, unknown>>(
    db,
    CHATS_STORE,
    chatId,
  );

  const messages = await getAllFromIndex<Record<string, unknown>>(
    db,
    MESSAGES_STORE,
    "chat_id",
    chatId,
  );

  const hashedChatId = await computeSHA256(chatId);
  const chatEmbeds = await getAllFromIndex<Record<string, unknown>>(
    db,
    EMBEDS_STORE,
    "hashed_chat_id",
    hashedChatId,
  );

  const chatEmbedKeys = await getAllFromIndex<Record<string, unknown>>(
    db,
    EMBED_KEYS_STORE,
    "hashed_chat_id",
    hashedChatId,
  );
  const totalEmbedKeysCount = await getStoreCount(db, EMBED_KEYS_STORE);
  const embedKeyDebugByHashedEmbedId = buildEmbedKeyDebugMap(chatEmbedKeys);

  chatEmbeds.sort(
    (a, b) => ((b.createdAt as number) || 0) - ((a.createdAt as number) || 0),
  );
  const showCount = Math.min(10, chatEmbeds.length);
  const embedDecodeHealth = await collectClientEmbedDecodeHealth(
    chatEmbeds,
    showCount,
    embedKeyDebugByHashedEmbedId,
  );

  db.close();

  // ---- Attempt decryption of chat fields and messages ----
  messages.sort((a, b) => (a.created_at as number) - (b.created_at as number));
  const decryptionReport = await attemptChatDecryption(
    chatId,
    chatMeta,
    messages,
  );

  // ---- Build health summary (now includes decryption results) ----
  const metaDecryptFailed = decryptionReport.metadataFields.filter(
    (f) => !f.success,
  ).length;
  const metaDecryptTotal = decryptionReport.metadataFields.length;
  const msgDecryptFailed = decryptionReport.messageFields.filter(
    (f) => !f.success,
  ).length;
  const msgDecryptTotal = decryptionReport.messageFields.length;

  const healthSummary = buildClientChatHealthSummary({
    chatMeta,
    messages,
    embeds: chatEmbeds,
    embedKeys: chatEmbedKeys,
    embedDecodeHealth: {
      checkedCount: embedDecodeHealth.checkedCount,
      failedCount: embedDecodeHealth.failedCount,
    },
  });

  // Add decryption failures to health issues
  if (!decryptionReport.chatKeyAvailable && chatMeta?.encrypted_chat_key) {
    healthSummary.issues.push(
      "chat key could not be obtained (master key unavailable or decryption failed)",
    );
    healthSummary.isHealthy = false;
  }
  if (metaDecryptFailed > 0) {
    healthSummary.issues.push(
      `${metaDecryptFailed}/${metaDecryptTotal} chat metadata fields failed to decrypt`,
    );
    healthSummary.isHealthy = false;
  }
  if (msgDecryptFailed > 0) {
    healthSummary.issues.push(
      `${msgDecryptFailed}/${msgDecryptTotal} messages failed to decrypt`,
    );
    healthSummary.isHealthy = false;
  }

  // ---- Build report ----
  const lines: string[] = [];

  // ------ CONCISE DEFAULT REPORT ------
  // Single-line header
  const createdStr = chatMeta
    ? formatTimestamp(chatMeta.created_at as number)
    : "N/A";
  lines.push(`CHAT ${chatId}  |  ${createdStr}`);
  const keyDisplay = decryptionReport.chatKeyAvailable
    ? hideKeys
      ? `${decryptionReport.chatKeyFingerprint} [pass hideKeys:false to show full key]`
      : `${decryptionReport.chatKeyFull ?? decryptionReport.chatKeyFingerprint} (${(decryptionReport.chatKeyFull?.length ?? 0) / 2} bytes, source: ${decryptionReport.chatKeySource})`
    : decryptionReport.chatKeyFingerprint;
  lines.push(`Key: ${keyDisplay}`);

  // Health status — single line summary
  if (healthSummary.isHealthy) {
    lines.push("");
    lines.push("🟢 HEALTHY");
  } else {
    const issueSummaries: string[] = [];
    for (const issue of healthSummary.issues) {
      issueSummaries.push(issue);
    }
    lines.push("");
    lines.push(`🔴 ISSUES DETECTED (${healthSummary.issues.length}):`);
    for (const issue of issueSummaries.slice(0, MAX_HEALTH_ITEMS_TO_SHOW)) {
      lines.push(`   • ${issue}`);
    }
    if (issueSummaries.length > MAX_HEALTH_ITEMS_TO_SHOW) {
      lines.push(
        `   • ... and ${issueSummaries.length - MAX_HEALTH_ITEMS_TO_SHOW} more`,
      );
    }
  }
  if (healthSummary.warnings.length > 0) {
    for (const w of healthSummary.warnings.slice(0, 3)) {
      lines.push(`   ⚠ ${w}`);
    }
  }

  // Metadata decryption table + chat state side-by-side
  lines.push("");
  lines.push("METADATA");

  // All encrypted fields with decrypt status
  const encryptedFieldDefs: Array<{
    label: string;
    key: string;
    shortLabel: string;
  }> = [
    { label: "Title", key: "encrypted_title", shortLabel: "Title" },
    { label: "Category", key: "encrypted_category", shortLabel: "Category" },
    { label: "Icon", key: "encrypted_icon", shortLabel: "Icon" },
    { label: "Summary", key: "encrypted_chat_summary", shortLabel: "Summary" },
    { label: "Tags", key: "encrypted_chat_tags", shortLabel: "Tags" },
    {
      label: "Follow-up Suggestions",
      key: "encrypted_follow_up_request_suggestions",
      shortLabel: "Follow-up",
    },
    {
      label: "Draft",
      key: "encrypted_draft_md",
      shortLabel: "Draft",
    },
    {
      label: "Active Focus ID",
      key: "encrypted_active_focus_id",
      shortLabel: "Focus",
    },
  ];

  if (chatMeta) {
    for (const fd of encryptedFieldDefs) {
      const encValue = chatMeta[fd.key] as string | undefined;
      if (!encValue) {
        lines.push(`  · ${fd.shortLabel.padEnd(12)} (not present)`);
        continue;
      }
      // Find matching decryption result
      const decResult = decryptionReport.metadataFields.find(
        (f) => f.field === fd.label,
      );
      if (decResult) {
        if (decResult.success) {
          const preview =
            decResult.preview.length > 30
              ? decResult.preview.substring(0, 30) + "..."
              : decResult.preview;
          lines.push(`  🟢 ${fd.shortLabel.padEnd(12)} "${preview}"`);
        } else {
          lines.push(`  🔴 ${fd.shortLabel.padEnd(12)} DECRYPT FAILED`);
        }
      } else {
        // Encrypted data present but no decrypt attempt (key unavailable)
        lines.push(
          `  🔴 ${fd.shortLabel.padEnd(12)} encrypted (${encValue.length} chars, KEY UNAVAILABLE)`,
        );
      }
    }

    // Chat state on separate compact lines
    const messagesV = (chatMeta.messages_v as number) || 0;
    const titleV = (chatMeta.title_v as number) || 0;
    lines.push("");
    lines.push("  State:");
    lines.push(
      `    messages_v=${messagesV}  title_v=${titleV}  private=${chatMeta.is_private ?? false}  shared=${chatMeta.is_shared ?? false}  hidden=${chatMeta.is_hidden ?? false}  pinned=${chatMeta.pinned ?? false}`,
    );
  } else {
    lines.push("  ❌ Chat NOT FOUND in IndexedDB");
  }

  // Messages table
  lines.push("");
  lines.push(`MESSAGES (${messages.length})`);

  if (messages.length > 0) {
    lines.push(
      `  ${"#".padStart(3)}  ${"Role".padEnd(10)} ${"Created".padEnd(28)} ${"Decrypt".padEnd(9)} Message ID`,
    );
    messages.forEach((msg, i) => {
      const role = (msg.role as string) || "unknown";
      const created = formatTimestamp(msg.created_at as number);
      const msgId = (msg.message_id as string) || (msg.id as string) || "N/A";

      // Decrypt status
      const msgDecrypt = decryptionReport.messageFields.find(
        (m) => m.messageIndex === i + 1,
      );
      let decryptStatus: string;
      if (msg.content && !msg.encrypted_content) {
        decryptStatus = "· plain";
      } else if (msgDecrypt) {
        decryptStatus = msgDecrypt.success ? "🟢 OK" : "🔴 FAIL";
      } else if (!msg.encrypted_content && !msg.content) {
        decryptStatus = "· empty";
      } else {
        decryptStatus = "? N/A";
      }

      lines.push(
        `  ${(i + 1).toString().padStart(3)}  ${role.padEnd(10)} ${created.padEnd(28)} ${decryptStatus.padEnd(9)} ${msgId}`,
      );
    });
  } else {
    lines.push("  (none)");
  }

  // Embeds table
  lines.push("");
  lines.push(`EMBEDS (${chatEmbeds.length})  |  Keys: ${chatEmbedKeys.length}`);

  if (chatEmbeds.length > 0) {
    lines.push(
      `  ${"#".padStart(3)}  ${"Role".padEnd(7)} ${"Type".padEnd(16)} ${"Status".padEnd(10)} ${"Decrypt".padEnd(9)} ${"App/Skill".padEnd(24)} ${"Created".padEnd(28)} Embed ID`,
    );

    // Build maps from embedId to decode results for quick lookup
    const embedDecodeMap = new Map<string, boolean>();
    const embedDecodedContentMap = new Map<string, Record<string, unknown>>();
    for (const attempt of embedDecodeHealth.attempts) {
      embedDecodeMap.set(attempt.embedId, !!attempt.decoded);
      if (attempt.decoded) {
        embedDecodedContentMap.set(attempt.embedId, attempt.decoded);
      }
    }

    const embedShowCount = Math.min(15, chatEmbeds.length);
    for (let i = 0; i < embedShowCount; i++) {
      const embed = chatEmbeds[i];
      const embedId =
        (embed.embed_id as string) || (embed.contentRef as string) || "N/A";
      const cleanEmbedId = embedId.replace(/^embed:/, "");
      const type = (embed.type as string) || "unknown";
      const status = (embed.status as string) || "N/A";

      // Decrypt status from embed decode health
      let decryptStatus: string;
      if (embedDecodeMap.has(cleanEmbedId)) {
        decryptStatus = embedDecodeMap.get(cleanEmbedId) ? "🟢 OK" : "🔴 FAIL";
      } else if (embed.content || embed.data) {
        decryptStatus = "· plain";
      } else if (!embed.encrypted_content) {
        decryptStatus = "· empty";
      } else {
        decryptStatus = "- skip";
      }

      // Embed role: parent (has children), child (has parent), or regular
      const hasChildren =
        embed.embed_ids &&
        Array.isArray(embed.embed_ids) &&
        (embed.embed_ids as string[]).length > 0;
      const hasParent = !!embed.parent_embed_id;
      const embedRole = hasChildren
        ? "parent"
        : hasParent
          ? "child"
          : "regular";
      const childCount = hasChildren
        ? `[${(embed.embed_ids as string[]).length}ch]`
        : "";

      // App and skill info — read from decoded TOON content (not raw record, since it's encrypted)
      const decodedContent = embedDecodedContentMap.get(cleanEmbedId);
      const appId = (decodedContent?.app_id as string) || "";
      const skillId = (decodedContent?.skill_id as string) || "";
      const appSkill =
        appId && skillId ? `${appId}/${skillId}` : appId || skillId || "—";

      // Created date
      const embedCreated = formatTimestamp(embed.createdAt as number);

      lines.push(
        `  ${(i + 1).toString().padStart(3)}  ${(embedRole + childCount).padEnd(7)} ${type.padEnd(16)} ${status.padEnd(10)} ${decryptStatus.padEnd(9)} ${appSkill.padEnd(24)} ${embedCreated.padEnd(28)} ${cleanEmbedId}`,
      );
    }

    if (chatEmbeds.length > embedShowCount) {
      lines.push(`  ... ${chatEmbeds.length - embedShowCount} more`);
    }
  } else {
    lines.push("  (none)");
  }

  // Footer
  lines.push("");
  lines.push(
    `💡 verbose: await window.debug.chat("${chatId.substring(0, 8)}...", {verbose: true})`,
  );

  // If verbose: append all the extra detail sections
  if (forceVerbose) {
    lines.push("");
    lines.push("─".repeat(80));
    lines.push("VERBOSE DETAILS");
    lines.push("─".repeat(80));

    if (chatMeta) {
      lines.push("");
      lines.push("  Timestamps:");
      lines.push(
        `    Created At:              ${formatTimestamp(chatMeta.created_at as number)}`,
      );
      lines.push(
        `    Updated At:              ${formatTimestamp(chatMeta.updated_at as number)}`,
      );
      lines.push(
        `    Last Message TS:         ${formatTimestamp(chatMeta.last_message_timestamp as number)}`,
      );
      lines.push(
        `    Last Edited Overall TS:  ${formatTimestamp(chatMeta.last_edited_overall_timestamp as number)}`,
      );

      lines.push("");
      lines.push(`  User ID:     ${chatMeta.user_id}`);
      lines.push(
        `  DB:          ${DB_NAME} v${await openDB().then((d) => {
          const v = d.version;
          d.close();
          return v;
        })}`,
      );

      lines.push("");
      lines.push("  Encrypted Field Sizes:");
      for (const fd of encryptedFieldDefs) {
        const encValue = chatMeta[fd.key] as string | undefined;
        if (encValue) {
          lines.push(
            `    ${fd.shortLabel.padEnd(16)} ${encValue.length} chars`,
          );
        }
      }
      if (chatMeta.encrypted_chat_key) {
        lines.push(
          `    ${"Chat Key".padEnd(16)} ${(chatMeta.encrypted_chat_key as string).length} chars`,
        );
      }
    }

    // Verbose message details
    if (messages.length > 0) {
      lines.push("");
      lines.push("  Message Details:");
      messages.forEach((msg, i) => {
        const role = (msg.role as string) || "unknown";
        const clientMsgId =
          (msg.client_message_id as string) ||
          (msg.message_id as string) ||
          (msg.id as string);
        const hasEncrypted = !!msg.encrypted_content;
        const hasContent = !!msg.content;
        const contentLen = hasEncrypted
          ? (msg.encrypted_content as string).length
          : hasContent
            ? (msg.content as string).length
            : 0;

        lines.push(
          `    ${(i + 1).toString().padStart(3)}. [${role}] client_id=${truncate(clientMsgId, 30)}  content=${contentLen} chars${msg.status ? `  status=${msg.status}` : ""}`,
        );
      });
    }

    // Verbose embed details
    if (chatEmbeds.length > 0) {
      lines.push("");
      lines.push(`  Hashed Chat ID: ${hashedChatId.substring(0, 24)}...`);

      // Distributions
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

      // Embed keys detail
      if (chatEmbedKeys.length > 0) {
        const keyTypeCount: Record<string, number> = {};
        for (const key of chatEmbedKeys) {
          const keyType = (key.key_type as string) || "unknown";
          keyTypeCount[keyType] = (keyTypeCount[keyType] || 0) + 1;
        }
        lines.push(
          `  Embed Key Types: ${JSON.stringify(keyTypeCount)} (${totalEmbedKeysCount} total in DB)`,
        );
      }

      // Admin-only: decode embeds and show field inventory
      const isAdmin = await isCurrentUserAdmin();
      if (isAdmin && !embedDecodeHealth.globalError) {
        lines.push("");
        lines.push("  EMBED FIELD INVENTORY (admin-only):");
        const allAnomalies: string[] = [];
        for (
          let index = 0;
          index < embedDecodeHealth.attempts.length;
          index++
        ) {
          const attempt = embedDecodeHealth.attempts[index];
          if (!attempt.decoded) continue;
          const inventory = buildFieldInventory(attempt.decoded);
          const anomalies = detectEmbedAnomalies(
            attempt.decoded,
            attempt.embed,
          );
          allAnomalies.push(...anomalies);
          lines.push("");
          lines.push(
            `    ${(index + 1).toString().padStart(2)}. embed-${truncate(attempt.embedId, 12)}:`,
          );
          lines.push(...formatFieldInventoryLines(inventory, anomalies));
        }
        if (allAnomalies.length > 0) {
          lines.push(`  Total anomalies: ${allAnomalies.length}`);
        }
      }
    }

    // Version consistency (verbose only — issues already surfaced in health line)
    const messagesVVerbose = chatMeta
      ? (chatMeta.messages_v as number) || 0
      : 0;
    lines.push("");
    lines.push(
      `  Version Check: messages_v=${messagesVVerbose} actual=${messages.length}`,
    );
  }

  lines.push("");

  const report = lines.join("\n");

  logHealthCheckBanner("CHAT", healthSummary.isHealthy);
  if (!healthSummary.isHealthy) {
    logFailedEmbedDecryptionBanner(embedDecodeHealth.attempts);
  }

  // Fetch server-side sync status — awaited so the result is included in the returned string
  // (used by SettingsReportIssue to include server sync data in bug reports)
  const syncResp = await fetchServerSyncStatus([chatId]);
  const serverStatus = syncResp?.chats?.[0];
  const syncLines = formatServerChatSync(serverStatus);
  const serverSyncBlock =
    "\n\n─────────────────────────────────────────────\n" +
    "🌐 SERVER SYNC\n" +
    syncLines.join("\n");

  const fullReport = report + serverSyncBlock;

  console.log(fullReport);

  if (options.download) {
    const blob = new Blob([fullReport], { type: "text/plain" });
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

  return fullReport;
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
  options: { download?: boolean; hideKeys?: boolean } = {},
): Promise<string> {
  const hideKeys = options.hideKeys ?? false;
  const db = await openDB();
  const lines: string[] = [];

  // Get embed directly from store by ID
  // IMPORTANT: IndexedDB embeds are stored with contentRef key "embed:{embed_id}"
  const contentRef = `embed:${embedId}`;
  const embed = await getFromStore<Record<string, unknown>>(
    db,
    EMBEDS_STORE,
    contentRef,
  );

  // Get child embeds
  const childEmbedRecords: Array<Record<string, unknown> | undefined> = [];
  if (embed?.embed_ids && Array.isArray(embed.embed_ids)) {
    for (const childId of embed.embed_ids as string[]) {
      const childRecord = await getFromStore<Record<string, unknown>>(
        db,
        EMBEDS_STORE,
        `embed:${childId}`,
      );
      childEmbedRecords.push(childRecord);
    }
  }

  // Get embed key info
  const hashedEmbedId = embed ? await computeSHA256(embedId) : "";
  const embedKeys = hashedEmbedId
    ? await getAllFromIndex<Record<string, unknown>>(
        db,
        EMBED_KEYS_STORE,
        "hashed_embed_id",
        hashedEmbedId,
      )
    : [];

  db.close();

  // Try to resolve and decode embed content for decryption check
  let decoded: Record<string, unknown> | null = null;
  let decryptOk = false;
  let decryptError = "";
  if (embed) {
    try {
      const { resolveEmbed, decodeToonContent } =
        await import("./embedResolver");
      const resolvedEmbed = await resolveEmbed(embedId);
      if (resolvedEmbed?.content) {
        const result = await decodeToonContent(resolvedEmbed.content);
        if (result && typeof result === "object") {
          decoded = result as Record<string, unknown>;
          decryptOk = true;
        } else {
          decryptError = "decoded content is empty or invalid";
        }
      } else {
        decryptError = resolvedEmbed
          ? "resolved embed has no content"
          : "could not resolve embed";
      }
    } catch (e) {
      decryptError = e instanceof Error ? e.message : String(e);
    }
  }

  // Build health summary
  const embedHealthSummary = buildClientEmbedHealthSummary({
    embed,
    childEmbeds: childEmbedRecords,
  });
  // Add decryption failure to health
  const status = String(embed?.status || "").toLowerCase();
  if (
    !decryptOk &&
    embed &&
    (status === "finished" || status === "activated") &&
    embed.encrypted_content
  ) {
    embedHealthSummary.issues.push("embed content failed to decrypt");
    embedHealthSummary.isHealthy = false;
  }
  // Check for missing app_id/skill_id on app_skill_use
  const embedType = (embed?.type as string) || "";
  if (decryptOk && decoded && embedType === "app-skill-use") {
    if (!decoded.app_id) {
      embedHealthSummary.issues.push("missing app_id in decoded content");
      embedHealthSummary.isHealthy = false;
    }
    if (!decoded.skill_id) {
      embedHealthSummary.issues.push("missing skill_id in decoded content");
      embedHealthSummary.isHealthy = false;
    }
  }

  // Header
  const createdStr = embed ? formatTimestamp(embed.createdAt as number) : "N/A";
  lines.push(`EMBED ${embedId}  |  ${createdStr}`);

  // Role
  const hasChildren =
    embed?.embed_ids &&
    Array.isArray(embed.embed_ids) &&
    (embed.embed_ids as string[]).length > 0;
  const hasParent = !!embed?.parent_embed_id;
  const embedRole = hasChildren
    ? `parent [${(embed!.embed_ids as string[]).length} children]`
    : hasParent
      ? "child"
      : "regular";
  lines.push(
    `Role: ${embedRole}${hasParent ? `  |  Parent: ${embed!.parent_embed_id}` : ""}`,
  );

  // Key info
  const keyInfo =
    embedKeys.length > 0
      ? `${embedKeys.length} key(s)${
          hideKeys
            ? ""
            : ` — types: ${JSON.stringify(
                Object.fromEntries(
                  embedKeys.reduce((m, k) => {
                    const t = String(k.key_type || "?");
                    m.set(t, (m.get(t) || 0) + 1);
                    return m;
                  }, new Map<string, number>()),
                ),
              )}`
        }`
      : "no keys stored";
  lines.push(`Keys: ${keyInfo}`);

  // Health status
  if (embedHealthSummary.isHealthy) {
    lines.push("");
    lines.push("🟢 HEALTHY");
  } else {
    lines.push("");
    lines.push(`🔴 ISSUES DETECTED (${embedHealthSummary.issues.length}):`);
    for (const issue of embedHealthSummary.issues.slice(
      0,
      MAX_HEALTH_ITEMS_TO_SHOW,
    )) {
      lines.push(`   • ${issue}`);
    }
  }
  if (embedHealthSummary.warnings.length > 0) {
    for (const w of embedHealthSummary.warnings.slice(0, 3)) {
      lines.push(`   ⚠ ${w}`);
    }
  }

  // Embed data
  lines.push("");
  lines.push("EMBED DATA");
  if (embed) {
    lines.push(`  Type:               ${embed.type || "N/A"}`);
    lines.push(`  Status:             ${embed.status || "N/A"}`);
    lines.push(`  Hashed Chat ID:     ${embed.hashed_chat_id || "N/A"}`);
    lines.push(`  Encryption Mode:    ${embed.encryption_mode || "N/A"}`);
    lines.push("");
    lines.push("  Content Fields:");
    lines.push(
      `    ${embed.encrypted_content ? "✅" : "❌"} encrypted_content ${embed.encrypted_content ? `(${(embed.encrypted_content as string).length} chars)` : ""}`,
    );
    const hasContent = embed.content;
    lines.push(
      `    ${hasContent ? "✅" : "❌"} content (TOON) ${hasContent ? `(${typeof hasContent === "string" ? (hasContent as string).length : "object"})` : ""}`,
    );
    lines.push(
      `    ${embed.data ? "✅" : "❌"} data ${embed.data ? `(${typeof embed.data === "string" ? (embed.data as string).length : "object"})` : ""}`,
    );

    // Decrypt status
    lines.push("");
    lines.push("  Decryption:");
    if (decryptOk && decoded) {
      lines.push("    🟢 Decrypt: OK");
      // Show decoded key fields
      const appId = (decoded.app_id as string) || "N/A";
      const skillId = (decoded.skill_id as string) || "N/A";
      const query = (decoded.query as string) || "N/A";
      const provider = (decoded.provider as string) || "N/A";
      const decodedStatus = (decoded.status as string) || "N/A";
      lines.push(`    app_id:      ${appId}`);
      lines.push(`    skill_id:    ${skillId}`);
      lines.push(`    query:       ${truncate(query, 60)}`);
      lines.push(`    provider:    ${provider}`);
      lines.push(`    status:      ${decodedStatus}`);
      if (decoded.results && Array.isArray(decoded.results)) {
        lines.push(
          `    results:     ${(decoded.results as unknown[]).length} items`,
        );
      }
      if (decoded.embed_ids && Array.isArray(decoded.embed_ids)) {
        lines.push(
          `    embed_ids:   ${(decoded.embed_ids as unknown[]).length} items`,
        );
      }
      // Show other fields count
      const knownFields = [
        "app_id",
        "skill_id",
        "query",
        "provider",
        "status",
        "task_id",
        "results",
        "embed_ids",
        "result_count",
      ];
      const otherFields = Object.keys(decoded).filter(
        (k) => !knownFields.includes(k),
      );
      if (otherFields.length > 0) {
        lines.push(`    other:       ${otherFields.join(", ")}`);
      }
    } else if (
      embed.encrypted_content &&
      (status === "finished" || status === "activated")
    ) {
      lines.push(`    🔴 Decrypt: FAILED — ${decryptError || "unknown error"}`);
    } else if (!embed.encrypted_content) {
      lines.push("    · no encrypted content to decrypt");
    } else {
      lines.push(`    · status=${status}, not attempting decrypt`);
    }
  } else {
    lines.push("  ❌ Embed NOT FOUND in IndexedDB");
  }

  // Children
  if (hasChildren) {
    lines.push("");
    lines.push(`CHILDREN (${(embed!.embed_ids as string[]).length})`);
    for (let i = 0; i < (embed!.embed_ids as string[]).length; i++) {
      const childId = (embed!.embed_ids as string[])[i];
      const child = childEmbedRecords[i];
      const childStatus = child ? (child.status as string) || "?" : "NOT FOUND";
      const childHasContent = child
        ? !!(child.encrypted_content || child.content || child.data)
        : false;
      lines.push(
        `  ${(i + 1).toString().padStart(3)}  ${childStatus.padEnd(10)} ${childHasContent ? "✅ content" : "❌ no content"}  ${childId}`,
      );
    }
  }

  // In-memory cache status (brief)
  try {
    const { embedStore } = await import("./embedStore");
    const inMemoryEmbed = await embedStore.get(contentRef);
    lines.push("");
    lines.push(
      `Memory cache:  ${inMemoryEmbed ? "✅ present" : "❌ not cached"}`,
    );
  } catch {
    lines.push("");
    lines.push("Memory cache:  unavailable");
  }

  lines.push("");

  const report = lines.join("\n");

  logHealthCheckBanner("EMBED", embedHealthSummary.isHealthy);

  // Fetch server-side sync status — awaited so the result is included in the returned string
  const embedSyncResp = await fetchServerSyncStatus(undefined, [embedId]);
  const embedServerStatus = embedSyncResp?.embeds?.[0];
  const embedSyncLines = formatServerEmbedSync(embedServerStatus);
  const embedServerSyncBlock =
    "\n\n─────────────────────────────────────────────\n" +
    "🌐 SERVER SYNC\n" +
    embedSyncLines.join("\n");

  const fullReport = report + embedServerSyncBlock;

  console.log(fullReport);

  if (options.download) {
    const blob = new Blob([fullReport], { type: "text/plain" });
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

  return fullReport;
}

// ============================================================================
// USER DEBUG
// ============================================================================

/**
 * Inspect current user profile and auth state with health checks.
 *
 * Usage in console:
 *   await window.debug.user()
 */
async function debugUser(): Promise<void> {
  const lines: string[] = [];
  const issues: string[] = [];

  // Auth state
  let isAuth = false;
  let isInit = false;
  try {
    const { get } = await import("svelte/store");
    const { authStore } = await import("../stores/authState");
    const auth = get(authStore) as unknown as Record<string, unknown> | null;
    isAuth = (auth?.isAuthenticated as boolean) ?? false;
    isInit = (auth?.isInitialized as boolean) ?? false;
    if (!isAuth) issues.push("user is NOT authenticated");
    if (!isInit) issues.push("auth store is NOT initialized");
  } catch {
    issues.push("auth store unavailable");
  }

  // Master key health check
  let masterKeyOk = false;
  try {
    const { getKeyFromStorage, encryptWithMasterKey } =
      await import("./cryptoService");
    const masterKey = await getKeyFromStorage();
    if (masterKey) {
      try {
        const testEnc = await encryptWithMasterKey("debug_test");
        masterKeyOk = testEnc !== null && testEnc.length > 0;
        if (!masterKeyOk)
          issues.push("master key present but encrypt test FAILED");
      } catch {
        issues.push("master key present but encrypt test threw error");
      }
    } else {
      issues.push("master key NOT available (locked or not initialized)");
    }
  } catch {
    issues.push("cryptoService unavailable");
  }

  // User profile
  let profile: Record<string, unknown> | null = null;
  try {
    const { get } = await import("svelte/store");
    const { userProfile } = await import("../stores/userProfile");
    profile = get(userProfile) as unknown as Record<string, unknown> | null;
    if (!profile) {
      issues.push("user profile not loaded");
    } else {
      if (!profile.user_id) issues.push("user_id is null");
      if (!profile.last_sync_timestamp)
        issues.push("last_sync_timestamp is 0/null — never synced");
    }
  } catch {
    issues.push("userProfile store unavailable");
  }

  // ─── Health at top ───
  lines.push("USER PROFILE & AUTH STATE");
  lines.push("─".repeat(80));
  if (issues.length === 0) {
    lines.push("🟢 HEALTHY");
  } else {
    lines.push(`🔴 ISSUES (${issues.length}):`);
    for (const iss of issues) lines.push(`   • ${iss}`);
  }

  // ─── Auth state ───
  lines.push("");
  lines.push("Auth:");
  lines.push(`  ${isAuth ? "🟢" : "🔴"} isAuthenticated = ${isAuth}`);
  lines.push(`  ${isInit ? "🟢" : "🔴"} isInitialized   = ${isInit}`);
  lines.push(
    `  ${masterKeyOk ? "🟢" : "🔴"} master key       = ${masterKeyOk ? "UNLOCKED (encrypt test OK)" : "LOCKED / UNAVAILABLE"}`,
  );

  // ─── Profile ───
  if (profile) {
    lines.push("");
    lines.push("Profile:");
    lines.push(`  user_id:           ${profile.user_id ?? "null"}`);
    lines.push(`  username:          ${profile.username ?? "?"}`);
    lines.push(`  is_admin:          ${profile.is_admin ?? false}`);
    lines.push(`  credits:           ${profile.credits ?? 0}`);
    lines.push(`  language:          ${profile.language ?? "null"}`);
    lines.push(`  timezone:          ${profile.timezone ?? "null"}`);
    lines.push(`  currency:          ${profile.currency || "null"}`);
    lines.push(`  darkmode:          ${profile.darkmode ?? false}`);
    lines.push(`  tfa_enabled:       ${profile.tfa_enabled ?? false}`);
    lines.push(`  last_opened:       ${profile.last_opened ?? "?"}`);
    lines.push(
      `  last_sync_ts:      ${profile.last_sync_timestamp ?? 0}` +
        (profile.last_sync_timestamp
          ? ` (${new Date((profile.last_sync_timestamp as number) * 1000).toISOString().replace("T", " ").replace("Z", " UTC")})`
          : ""),
    );
    lines.push(
      `  push_notif:        ${profile.push_notification_enabled ?? false}`,
    );
    lines.push(
      `  email_notif:       ${profile.email_notifications_enabled ?? false}`,
    );
    lines.push(
      `  auto_delete_days:  ${profile.auto_delete_chats_after_days ?? "null (never)"}`,
    );

    // Recommended apps
    if (
      profile.top_recommended_apps &&
      Array.isArray(profile.top_recommended_apps)
    ) {
      lines.push("");
      lines.push(
        `Top recommended apps (${(profile.top_recommended_apps as string[]).length}):  ${(profile.top_recommended_apps as string[]).join(", ")}`,
      );
    }

    // AI model preferences
    lines.push("");
    lines.push("AI model preferences:");
    lines.push(
      `  default_simple:    ${profile.default_ai_model_simple ?? "auto"}`,
    );
    lines.push(
      `  default_complex:   ${profile.default_ai_model_complex ?? "auto"}`,
    );
    const disabledModels = profile.disabled_ai_models as string[] | undefined;
    if (disabledModels && disabledModels.length > 0) {
      lines.push(`  disabled_models:   ${disabledModels.join(", ")}`);
    } else {
      lines.push("  disabled_models:   (none)");
    }
  }

  console.log(lines.join("\n"));
}

// ============================================================================
// DAILY INSPIRATIONS DEBUG
// ============================================================================

/**
 * Inspect daily inspirations store state with health checks.
 *
 * Usage in console:
 *   await window.debug.dailyInspirations()
 */
async function debugDailyInspirations(): Promise<void> {
  const lines: string[] = [];
  const issues: string[] = [];

  let stateObj: {
    inspirations: Array<Record<string, unknown>>;
    currentIndex: number;
    phase1Empty: boolean;
    isPersonalized: boolean;
  } | null = null;

  try {
    const { get } = await import("svelte/store");
    const { dailyInspirationStore } =
      await import("../stores/dailyInspirationStore");
    stateObj = get(dailyInspirationStore) as unknown as typeof stateObj;
  } catch (e) {
    issues.push(`store unavailable: ${e}`);
  }

  // Pre-compute health issues
  if (stateObj) {
    if (!stateObj.isPersonalized && stateObj.inspirations.length > 0) {
      issues.push("inspirations are public defaults only (not personalized)");
    }
    for (const ins of stateObj.inspirations) {
      const insId = ((ins.inspiration_id as string) || "?").slice(0, 8);
      if (!ins.video) issues.push(`inspiration ${insId}... has no video`);
      if (!ins.generated_at)
        issues.push(`inspiration ${insId}... missing generated_at`);
    }
  }

  // ─── Header ───
  lines.push("DAILY INSPIRATIONS");
  lines.push("─".repeat(80));

  if (!stateObj) {
    console.log(lines.join("\n"));
    return;
  }

  // ─── Store state ───
  lines.push("");
  lines.push(`Count:          ${stateObj.inspirations.length} (max 3)`);
  lines.push(`currentIndex:   ${stateObj.currentIndex}`);
  lines.push(`phase1Empty:    ${stateObj.phase1Empty}`);
  lines.push(`isPersonalized: ${stateObj.isPersonalized}`);

  if (stateObj.inspirations.length === 0) {
    lines.push("");
    lines.push("(no inspirations loaded)");
  } else {
    // Lazy-import modules needed for the assistant-message check
    let chatDBModule: null | (typeof import("./db"))["chatDB"] = null;
    let decryptWithChatKeyFn:
      | null
      | (typeof import("./cryptoService"))["decryptWithChatKey"] = null;
    let decryptChatKeyWithMasterKeyFn:
      | null
      | (typeof import("./cryptoService"))["decryptChatKeyWithMasterKey"] =
      null;
    try {
      const [dbMod, cryptoMod] = await Promise.all([
        import("./db"),
        import("./cryptoService"),
      ]);
      chatDBModule = dbMod.chatDB;
      decryptWithChatKeyFn = cryptoMod.decryptWithChatKey;
      decryptChatKeyWithMasterKeyFn = cryptoMod.decryptChatKeyWithMasterKey;
    } catch {
      // Non-fatal — assistant message check will be skipped
    }

    for (let i = 0; i < stateObj.inspirations.length; i++) {
      const ins = stateObj.inspirations[i] as Record<string, unknown>;
      const isCurrent = i === stateObj.currentIndex;
      // is_opened: the user clicked the banner and created a chat.
      // "viewed" (banner entered viewport) is tracked in Redis only — not visible client-side.
      const openedLabel = ins.is_opened
        ? "chat opened"
        : "not opened (click to start chat)";
      const genDate = ins.generated_at
        ? new Date((ins.generated_at as number) * 1000)
            .toISOString()
            .replace("T", " ")
            .replace("Z", " UTC")
        : "N/A";

      lines.push("");
      lines.push(
        `Inspiration ${i + 1}${isCurrent ? " ◀ current" : ""} — ${openedLabel}`,
      );
      lines.push(`  id:             ${ins.inspiration_id as string}`);
      const phrase = (ins.phrase as string) || "";
      lines.push(
        `  phrase:         ${phrase.length > 70 ? phrase.slice(0, 70) + "..." : phrase}`,
      );
      lines.push(`  title:          ${ins.title || "(not set)"}`);
      lines.push(`  category:       ${ins.category}`);
      lines.push(`  content_type:   ${ins.content_type}`);
      lines.push(`  generated_at:   ${genDate}`);
      lines.push(`  embed_id:       ${ins.embed_id || "null"}`);
      if (ins.opened_chat_id) {
        lines.push(`  opened_chat_id: ${ins.opened_chat_id as string}`);
      }

      // Embed resolve check
      if (ins.embed_id) {
        try {
          const { resolveEmbed } = await import("./embedResolver");
          const resolved = await resolveEmbed(ins.embed_id as string);
          lines.push(
            `  embed_resolve:  ${resolved ? "🟢 OK" : "🔴 NOT FOUND"}`,
          );
        } catch {
          lines.push("  embed_resolve:  🔴 ERROR");
        }
      }

      const video = ins.video as Record<string, unknown> | null;
      if (video) {
        lines.push(`  video:`);
        lines.push(`    youtube_id:   ${video.youtube_id}`);
        const vTitle = (video.title as string) || "?";
        lines.push(
          `    title:        ${vTitle.length > 60 ? vTitle.slice(0, 60) + "..." : vTitle}`,
        );
        lines.push(`    channel:      ${video.channel_name || "?"}`);
        lines.push(
          `    duration:     ${video.duration_seconds != null ? video.duration_seconds + "s" : "?"}`,
        );
      } else {
        lines.push("  video:          null");
      }

      const followUpArr = Array.isArray(ins.follow_up_suggestions)
        ? (ins.follow_up_suggestions as string[])
        : [];
      lines.push(
        `  follow_up:      ${followUpArr.length} suggestion(s)${followUpArr.length === 0 ? " (persisted after reload; LLM-gen only in current session)" : ""}`,
      );
      const resp = ins.assistant_response as string | undefined;
      lines.push(
        `  assistant_resp: ${resp ? resp.length + " chars" : "(not set)"}`,
      );

      // ── Assistant message verification for opened inspirations ──────────────
      // Check that the first message in the created chat:
      //   1. Is set (not null/empty)
      //   2. Is NOT equal to the raw assistant_response alone when the inspiration
      //      has a video (it should contain the assistant_response + embed reference block).
      //      If they are equal, the embed reference was not appended — that's a bug.
      //   3. Has messages_v > 1 (messages_v is set to 1 at chat creation time; if it
      //      still equals 1 the chat was created but no assistant message was added).
      if (
        ins.is_opened &&
        ins.opened_chat_id &&
        chatDBModule &&
        decryptWithChatKeyFn &&
        decryptChatKeyWithMasterKeyFn
      ) {
        try {
          await chatDBModule.init();
          const chatId = ins.opened_chat_id as string;
          const chat = await chatDBModule.getChat(chatId);
          if (!chat) {
            lines.push(
              `  assistant_msg:  🔴 chat ${chatId.slice(0, 8)}... NOT FOUND in IndexedDB`,
            );
          } else {
            const messagesV = (chat as unknown as Record<string, unknown>)
              .messages_v as number | undefined;
            if (messagesV !== undefined && messagesV <= 1) {
              // messages_v is initialized to 1 at chat creation. It increments each time a
              // new message is added. If still 1, no messages have been added after creation.
              lines.push(
                `  assistant_msg:  🔴 messages_v=${messagesV} — chat created but no messages added yet (or assistant message not written)`,
              );
            } else {
              // Get the chat key (from cache first, then unwrap from encrypted_chat_key)
              let chatKey: Uint8Array | null = chatDBModule.getChatKey(chatId);
              if (!chatKey) {
                const chatMeta = chat as unknown as Record<string, unknown>;
                if (chatMeta.encrypted_chat_key) {
                  chatKey = await decryptChatKeyWithMasterKeyFn(
                    chatMeta.encrypted_chat_key as string,
                  );
                }
              }
              // Try to read the first assistant message in the chat
              const allMessages = await chatDBModule.getMessagesForChat(chatId);
              const firstAssistant = (
                allMessages as unknown as Array<Record<string, unknown>> | null
              )?.find((m) => m.role === "assistant");
              if (!firstAssistant) {
                lines.push(
                  `  assistant_msg:  🔴 no assistant message found in chat (messages_v=${messagesV})`,
                );
              } else {
                // Try decrypting the message content
                const encContent = firstAssistant.encrypted_content as
                  | string
                  | null;
                if (!encContent) {
                  lines.push(
                    `  assistant_msg:  🟡 message has no encrypted_content (cleartext or not yet written)`,
                  );
                } else if (!chatKey) {
                  lines.push(
                    `  assistant_msg:  🟡 chat key unavailable — cannot decrypt to verify content`,
                  );
                } else {
                  const decrypted = await decryptWithChatKeyFn(
                    encContent,
                    chatKey,
                    {
                      chatId,
                      fieldName: "first_assistant_message",
                    },
                  );
                  if (!decrypted) {
                    lines.push(
                      `  assistant_msg:  🔴 decryption failed for first assistant message`,
                    );
                  } else {
                    const hasEmbed =
                      decrypted.includes('"type"') &&
                      decrypted.includes('"embed_id"');
                    const equalsRawCta =
                      resp && decrypted.trim() === resp.trim();
                    if (video && equalsRawCta) {
                      // Message equals bare assistant_response but there's a video — embed block is missing
                      lines.push(
                        `  assistant_msg:  🔴 BUG: equals bare CTA text only — embed reference block MISSING (${decrypted.length} chars)`,
                      );
                      issues.push(
                        `inspiration ${(ins.inspiration_id as string).slice(0, 8)}... chat msg = bare CTA (embed block missing)`,
                      );
                    } else if (video && !hasEmbed) {
                      lines.push(
                        `  assistant_msg:  🟡 ${decrypted.length} chars — no embed JSON block found (may be legacy format)`,
                      );
                    } else {
                      lines.push(
                        `  assistant_msg:  🟢 OK (${decrypted.length} chars${hasEmbed ? ", embed block present" : ""})`,
                      );
                    }
                  }
                }
              }
            }
          }
        } catch (checkErr) {
          lines.push(`  assistant_msg:  🟡 check error: ${checkErr}`);
        }
      }
    }
  }
  // Re-run health summary after per-inspiration checks (issues array may have grown)
  lines.push("");
  if (issues.length === 0) {
    lines.push("🟢 Daily inspirations: HEALTHY");
  } else {
    lines.push(`🔴 Daily inspirations: ${issues.length} issue(s)`);
    for (const iss of issues) lines.push(`   • ${iss}`);
  }
  lines.push("");
  lines.push(
    "Note: 'not opened' = user has not clicked the banner to start a chat.",
  );
  lines.push(
    "      'viewed' (banner in viewport) is tracked server-side only (Redis).",
  );

  console.log(lines.join("\n"));
}

// ============================================================================
// NEW CHAT SUGGESTIONS DEBUG
// ============================================================================

/**
 * Inspect new chat suggestions in IndexedDB with decryption health check.
 *
 * Usage in console:
 *   await window.debug.newChatSuggestions()
 *   await window.debug.newChatSuggestions({ hideKeys: true })
 */
async function debugNewChatSuggestions(
  opts: { hideKeys?: boolean } = {},
): Promise<void> {
  void opts; // reserved for future use
  const lines: string[] = [];
  const issues: string[] = [];

  let suggestions: Record<string, unknown>[] = [];
  let decryptOk = 0;
  let decryptFail = 0;
  let masterKeyAvailable = false;

  try {
    const db = await openDB();
    suggestions = await getAllFromStore<Record<string, unknown>>(
      db,
      NEW_CHAT_SUGGESTIONS_STORE,
    );
    db.close();

    // Sort by created_at descending
    suggestions.sort(
      (a, b) =>
        ((b.created_at as number) || 0) - ((a.created_at as number) || 0),
    );

    // Try to decrypt each suggestion
    let decryptWithMasterKey: null | ((s: string) => Promise<string | null>) =
      null;
    try {
      const mod = await import("./cryptoService");
      decryptWithMasterKey = mod.decryptWithMasterKey as (
        s: string,
      ) => Promise<string | null>;
      if (decryptWithMasterKey && suggestions.length > 0) {
        masterKeyAvailable = true;
      }
    } catch {
      masterKeyAvailable = false;
    }

    // Attempt decryption on all
    const decryptedPreviews: (string | null)[] = [];
    for (const s of suggestions) {
      const encValue = (s.encrypted_suggestion as string) || "";
      if (decryptWithMasterKey && encValue) {
        try {
          const decrypted = await decryptWithMasterKey(encValue);
          if (decrypted !== null) {
            decryptOk++;
            decryptedPreviews.push(
              decrypted.length > 50
                ? decrypted.slice(0, 50) + "..."
                : decrypted,
            );
          } else {
            decryptFail++;
            decryptedPreviews.push(null);
          }
        } catch {
          decryptFail++;
          decryptedPreviews.push(null);
        }
      } else {
        decryptedPreviews.push(null);
      }
    }

    // Health
    if (!masterKeyAvailable && suggestions.length > 0) {
      issues.push(
        "master key not available — cannot verify suggestions are decryptable",
      );
    }
    if (decryptFail > 0) {
      issues.push(
        `${decryptFail}/${decryptOk + decryptFail} suggestions failed to decrypt`,
      );
    }
    if (suggestions.length > 45) {
      issues.push(
        `suggestion count (${suggestions.length}) is near the 50-item cap`,
      );
    }

    // ─── Header + health at top ───
    lines.push("NEW CHAT SUGGESTIONS");
    lines.push("─".repeat(80));
    if (issues.length === 0) {
      lines.push(
        `🟢 HEALTHY (${suggestions.length} suggestions, ${decryptOk} decrypted OK)`,
      );
    } else {
      lines.push(`🔴 ISSUES (${issues.length}):`);
      for (const iss of issues) lines.push(`   • ${iss}`);
    }

    lines.push("");
    lines.push(`Count in IndexedDB:  ${suggestions.length} (max 50)`);
    lines.push(
      `Master key:          ${masterKeyAvailable ? "🟢 UNLOCKED" : "🔴 LOCKED / UNAVAILABLE"}`,
    );

    if (suggestions.length > 0) {
      lines.push("");
      lines.push(
        `${"#".padStart(3)}  ${"Created".padEnd(28)} ${"Chat ID".padEnd(36)} ${"Decrypt".padEnd(9)} Preview`,
      );
      for (let i = 0; i < suggestions.length; i++) {
        const s = suggestions[i];
        const createdAt = formatTimestamp(s.created_at as number);
        const chatId = (s.chat_id as string) || "N/A";
        const encValue = (s.encrypted_suggestion as string) || "";
        const isHidden = s.is_hidden ? " [hidden]" : "";
        const preview = decryptedPreviews[i];

        let decryptInfo: string;
        if (preview !== null) {
          decryptInfo = `🟢 OK    "${preview}"`;
        } else if (!encValue) {
          decryptInfo = "· empty";
        } else if (!masterKeyAvailable) {
          decryptInfo = `? N/A   (${encValue.length} chars enc)`;
        } else {
          decryptInfo = `🔴 FAIL  (${encValue.length} chars enc)`;
        }

        lines.push(
          `${(i + 1).toString().padStart(3)}  ${createdAt.padEnd(28)} ${chatId}${isHidden}  ${decryptInfo}`,
        );
      }
    }
  } catch (e) {
    issues.push(`error reading IndexedDB: ${e}`);
    lines.push("NEW CHAT SUGGESTIONS");
    lines.push("─".repeat(80));
    lines.push(`🔴 ISSUES (${issues.length}):`);
    for (const iss of issues) lines.push(`   • ${iss}`);
  }

  console.log(lines.join("\n"));
}

// ============================================================================
// INITIALIZATION - Expose unified window.debug namespace
// ============================================================================

/**
 * Run a quick client-side health check and print a summary to the console.
 * This is what `window.debug()` calls by default (no arguments).
 *
 * Checks:
 *  - IndexedDB connectivity (chats, messages, embeds, keys counts)
 *  - Auth state, master key, admin status
 *  - Admin log forwarder status (running, flush success/failure stats)
 *  - Active chat store state
 *  - Last 5 console errors from logCollector
 */
async function runClientHealthCheck(): Promise<void> {
  const allIssues: string[] = [];
  const allOk: string[] = [];

  // 1. IndexedDB connectivity
  let chatCount = 0;
  let msgCount = 0;
  let embedCount = 0;
  let keyCount = 0;
  let suggCount = 0;
  try {
    const db = await openDB();
    chatCount = await getStoreCount(db, CHATS_STORE);
    msgCount = await getStoreCount(db, MESSAGES_STORE);
    embedCount = await getStoreCount(db, EMBEDS_STORE);
    keyCount = await getStoreCount(db, EMBED_KEYS_STORE);
    try {
      suggCount = await getStoreCount(db, NEW_CHAT_SUGGESTIONS_STORE);
    } catch {
      suggCount = -1; // store may not exist
    }
    db.close();
    allOk.push(
      `IndexedDB: chats=${chatCount}, messages=${msgCount}, embeds=${embedCount}, keys=${keyCount}, suggestions=${suggCount >= 0 ? suggCount : "N/A"}`,
    );
  } catch (e) {
    allIssues.push(`IndexedDB FAILED: ${e}`);
  }

  // 2. Auth + master key
  try {
    const { get } = await import("svelte/store");
    const { authStore } = await import("../stores/authState");
    const auth = get(authStore) as unknown as Record<string, unknown> | null;
    const isAuth = (auth?.isAuthenticated as boolean) ?? false;
    if (isAuth) {
      allOk.push("Auth: authenticated");
    } else {
      allIssues.push("Auth: NOT authenticated");
    }
  } catch {
    allIssues.push("Auth store unavailable");
  }

  try {
    const { getKeyFromStorage } = await import("./cryptoService");
    const masterKey = await getKeyFromStorage();
    if (masterKey) {
      allOk.push("Master key: UNLOCKED");
    } else {
      allIssues.push("Master key: LOCKED / unavailable");
    }
  } catch {
    allIssues.push("Master key: unavailable");
  }

  // 2b. Admin status + log forwarder health
  try {
    const { get } = await import("svelte/store");
    const { userProfile } = await import("../stores/userProfile");
    const profile = get(userProfile) as unknown as Record<
      string,
      unknown
    > | null;
    const isAdmin = !!profile?.is_admin;

    if (isAdmin) {
      allOk.push("Admin: YES (is_admin=true)");

      // Check log forwarder status — only relevant for admins
      try {
        const { clientLogForwarder } = await import("./clientLogForwarder");
        const status = clientLogForwarder.getStatus();

        if (status.isRunning) {
          const flushInfo =
            status.totalFlushAttempts > 0
              ? `flushes=${status.successfulFlushes}ok/${status.failedFlushes}fail of ${status.totalFlushAttempts} total`
              : "no flushes yet";
          const lastStatus =
            status.lastFlushStatus !== null
              ? `, last HTTP ${status.lastFlushStatus}`
              : "";
          const lastErr = status.lastFlushError
            ? `, lastError="${status.lastFlushError}"`
            : "";
          const firstFlush = status.firstFlushAttempted
            ? ""
            : " (first flush NOT yet attempted)";

          if (status.failedFlushes === 0 && status.successfulFlushes > 0) {
            allOk.push(
              `Log forwarder: RUNNING (tab=${status.tabId}, ${flushInfo}${lastStatus}${firstFlush})`,
            );
          } else if (
            status.failedFlushes > 0 &&
            status.successfulFlushes === 0
          ) {
            allIssues.push(
              `Log forwarder: RUNNING but ALL flushes FAILED (tab=${status.tabId}, ${flushInfo}${lastStatus}${lastErr})`,
            );
          } else if (status.failedFlushes > 0) {
            allIssues.push(
              `Log forwarder: RUNNING with some failures (tab=${status.tabId}, ${flushInfo}${lastStatus}${lastErr})`,
            );
          } else {
            // Running but no flushes attempted yet (just started)
            allOk.push(
              `Log forwarder: RUNNING (tab=${status.tabId}, buffer=${status.bufferSize}${firstFlush})`,
            );
          }
        } else {
          allIssues.push(
            "Log forwarder: NOT RUNNING (start() was never called or stop() was called)",
          );
        }
      } catch {
        allIssues.push("Log forwarder: unable to check status");
      }
    } else {
      allOk.push("Admin: no (log forwarder not applicable)");
    }
  } catch {
    // non-critical — userProfile store may not be available
  }

  // 3. Active chat store
  try {
    const { get } = await import("svelte/store");
    const { activeChatStore } = await import("../stores/activeChatStore");
    const state = get(activeChatStore) as unknown as Record<
      string,
      unknown
    > | null;
    const activeChatId = state?.activeChatId ?? null;
    allOk.push(`Active chat: ${activeChatId ? activeChatId : "none"}`);
  } catch {
    // non-critical
  }

  // 4. Attempt decryption of ALL chats — metadata + messages
  let decryptChatsFailed = 0;
  let decryptChatsOk = 0;
  const failedChatDetails: { chatId: string; failedFields: string[] }[] = [];
  let failedEmbedDetails: { embedId: string; error: string }[] = [];
  try {
    const db2 = await openDB();
    const allChats = await getAllFromStore<Record<string, unknown>>(
      db2,
      CHATS_STORE,
    );
    const allMessages = await getAllFromStore<Record<string, unknown>>(
      db2,
      MESSAGES_STORE,
    );
    db2.close();

    const messagesByChatId: Record<string, Record<string, unknown>[]> = {};
    for (const msg of allMessages) {
      const cid = msg.chat_id as string;
      if (!messagesByChatId[cid]) messagesByChatId[cid] = [];
      messagesByChatId[cid].push(msg);
    }

    for (const chatMeta of allChats) {
      const chatId = chatMeta.chat_id as string;
      const msgs = messagesByChatId[chatId] || [];
      try {
        const report = await attemptChatDecryption(chatId, chatMeta, msgs);
        if (report.chatKeyAvailable) {
          const failedFields: string[] = [];
          for (const f of report.metadataFields) {
            if (!f.success) failedFields.push(f.field);
          }
          for (const m of report.messageFields) {
            if (!m.success) failedFields.push(`msg[${m.messageIndex}]`);
          }
          if (failedFields.length > 0) {
            decryptChatsFailed++;
            failedChatDetails.push({ chatId, failedFields });
          } else {
            decryptChatsOk++;
          }
        }
      } catch {
        // skip
      }
    }

    if (decryptChatsFailed === 0) {
      allOk.push(`Chat decryption: all ${decryptChatsOk} chats OK`);
    } else {
      allIssues.push(
        `Chat decryption: ${decryptChatsFailed} chat(s) have decrypt failures`,
      );
    }
  } catch (e) {
    allIssues.push(`Chat decryption check failed: ${e}`);
  }

  // 5. Embed decryption — ALL finished encrypted embeds (no sampling)
  try {
    const db3 = await openDB();
    const allEmbeds = await getAllFromStore<Record<string, unknown>>(
      db3,
      EMBEDS_STORE,
    );
    const allEmbedKeys = await getAllFromStore<Record<string, unknown>>(
      db3,
      EMBED_KEYS_STORE,
    );
    db3.close();

    const embedKeyDebug = buildEmbedKeyDebugMap(allEmbedKeys);
    const finishedEmbeds = allEmbeds.filter((e) => {
      const s = String(e.status || "").toLowerCase();
      return (s === "finished" || s === "activated") && !!e.encrypted_content;
    });

    if (finishedEmbeds.length > 0) {
      const embedDecodeResult = await collectClientEmbedDecodeHealth(
        finishedEmbeds,
        finishedEmbeds.length,
        embedKeyDebug,
      );

      if (embedDecodeResult.failedCount === 0) {
        allOk.push(
          `Embed decryption: ${embedDecodeResult.decodedCount}/${embedDecodeResult.checkedCount} ALL OK`,
        );
      } else {
        allIssues.push(
          `Embed decryption: ${embedDecodeResult.failedCount}/${embedDecodeResult.checkedCount} FAILED`,
        );
        // Collect failed embed details for the detail section
        failedEmbedDetails = embedDecodeResult.attempts
          .filter((a) => a.error !== null)
          .map((a) => ({ embedId: a.embedId, error: a.error || "unknown" }));
      }
    } else {
      allOk.push("Embed decryption: no finished encrypted embeds to check");
    }
  } catch (e) {
    allIssues.push(`Embed decryption check failed: ${e}`);
  }

  // 6. New chat suggestions decryption
  try {
    const db4 = await openDB();
    const suggestions = await getAllFromStore<Record<string, unknown>>(
      db4,
      NEW_CHAT_SUGGESTIONS_STORE,
    );
    db4.close();

    if (suggestions.length > 0) {
      let suggOk = 0;
      let suggFail = 0;
      try {
        const { decryptWithMasterKey } = await import("./cryptoService");
        for (const s of suggestions) {
          const enc = (s.encrypted_suggestion as string) || "";
          if (!enc) continue;
          try {
            const d = await decryptWithMasterKey(enc);
            if (d !== null) suggOk++;
            else suggFail++;
          } catch {
            suggFail++;
          }
        }
        if (suggFail === 0) {
          allOk.push(`Suggestions decrypt: all ${suggOk} OK`);
        } else {
          allIssues.push(
            `Suggestions decrypt: ${suggFail}/${suggOk + suggFail} FAILED`,
          );
        }
      } catch {
        allIssues.push("Suggestions decrypt: master key unavailable");
      }
    }
  } catch {
    // store may not exist, non-critical
  }

  // 7. Daily inspirations health
  try {
    const { get } = await import("svelte/store");
    const { dailyInspirationStore } =
      await import("../stores/dailyInspirationStore");
    const state = get(dailyInspirationStore) as unknown as {
      inspirations: Array<Record<string, unknown>>;
      isPersonalized: boolean;
    };
    const count = state.inspirations.length;
    if (count === 0) {
      allOk.push("Daily inspirations: 0 loaded");
    } else {
      const missing = state.inspirations.filter((i) => !i.video).length;
      if (missing > 0) {
        allIssues.push(`Daily inspirations: ${missing}/${count} missing video`);
      } else {
        allOk.push(
          `Daily inspirations: ${count} loaded${state.isPersonalized ? " (personalized)" : " (defaults)"}`,
        );
      }
    }
  } catch {
    // non-critical
  }

  // 8. Settings & memories decryption health
  try {
    const db5 = await openDB();
    const settingsEntries = await getAllFromStore<Record<string, unknown>>(
      db5,
      APP_SETTINGS_MEMORIES_STORE,
    );
    db5.close();

    if (settingsEntries.length > 0) {
      let smOk = 0;
      let smFail = 0;
      try {
        const { decryptWithMasterKey } = await import("./cryptoService");
        for (const entry of settingsEntries) {
          const enc = (entry.encrypted_item_json as string) || "";
          if (!enc) {
            smFail++;
            continue;
          }
          try {
            const d = await decryptWithMasterKey(enc);
            if (d !== null) smOk++;
            else smFail++;
          } catch {
            smFail++;
          }
        }
        if (smFail === 0) {
          allOk.push(`Settings & memories decrypt: all ${smOk} OK`);
        } else {
          allIssues.push(
            `Settings & memories decrypt: ${smFail}/${smOk + smFail} FAILED`,
          );
        }
      } catch {
        allIssues.push("Settings & memories decrypt: master key unavailable");
      }
    } else {
      allOk.push("Settings & memories: 0 entries");
    }
  } catch {
    // store may not exist, non-critical
  }

  // 9. Console error/warn logs
  let errorLogCount = 0;
  try {
    const { logCollector } = await import("./logCollector");
    const errors = logCollector
      .getErrorLogs()
      .filter(
        (e: { level: string }) => e.level === "error" || e.level === "warn",
      );
    errorLogCount = errors.length;
    if (errors.length === 0) {
      allOk.push("Console: no errors/warnings");
    } else {
      allIssues.push(`Console: ${errors.length} error/warning log(s)`);
    }
  } catch {
    // non-critical
  }

  // 10. Server sync status — batch check all local chats against server
  // We collect all local chat IDs, then send them in batches of SERVER_SYNC_BATCH_SIZE.
  // Any chat that is found locally but missing on the server (or has version mismatch) is flagged.
  const serverSyncIssues: string[] = [];
  try {
    const db6 = await openDB();
    const allChatsForSync = await getAllFromStore<Record<string, unknown>>(
      db6,
      CHATS_STORE,
    );
    db6.close();

    if (allChatsForSync.length > 0) {
      // Build batches
      const allChatIds = allChatsForSync
        .map((c) => c.chat_id as string)
        .filter(Boolean);
      const batches: string[][] = [];
      for (let i = 0; i < allChatIds.length; i += SERVER_SYNC_BATCH_SIZE) {
        batches.push(allChatIds.slice(i, i + SERVER_SYNC_BATCH_SIZE));
      }

      // Build local messages_v map for comparison
      const localMsgVMap: Record<string, number> = {};
      const localMsgCountMap: Record<string, number> = {};
      for (const c of allChatsForSync) {
        const cid = c.chat_id as string;
        if (cid) {
          localMsgVMap[cid] = (c.messages_v as number) || 0;
        }
      }
      // Count local messages per chat
      const db7 = await openDB();
      const allMsgsForSync = await getAllFromStore<Record<string, unknown>>(
        db7,
        MESSAGES_STORE,
      );
      db7.close();
      for (const m of allMsgsForSync) {
        const cid = m.chat_id as string;
        if (cid) localMsgCountMap[cid] = (localMsgCountMap[cid] || 0) + 1;
      }

      // Fetch server sync status in batches
      let driftCount = 0;
      let missingCount = 0;
      let checkedCount = 0;
      const driftDetails: string[] = [];

      for (const batch of batches) {
        const syncResp = await fetchServerSyncStatus(batch);
        if (!syncResp) break; // Server unreachable — stop checking

        for (const serverChat of syncResp.chats) {
          checkedCount++;
          const localMsgV = localMsgVMap[serverChat.chat_id] ?? null;
          const localMsgCount = localMsgCountMap[serverChat.chat_id] ?? 0;

          if (!serverChat.found) {
            missingCount++;
            driftDetails.push(
              `  🔴 chat ${serverChat.chat_id.substring(0, 12)}... NOT on server`,
            );
            continue;
          }

          // Check client vs server messages_v drift
          const serverMsgV = serverChat.db_messages_v ?? null;
          if (
            localMsgV !== null &&
            serverMsgV !== null &&
            localMsgV !== serverMsgV
          ) {
            driftCount++;
            driftDetails.push(
              `  🔴 chat ${serverChat.chat_id.substring(0, 12)}... client_messages_v=${localMsgV} ≠ server_messages_v=${serverMsgV}`,
            );
          }

          // Server-side DB consistency
          if (serverChat.db_consistent === false) {
            driftCount++;
            driftDetails.push(
              `  🔴 chat ${serverChat.chat_id.substring(0, 12)}... server DB inconsistent: messages=${serverChat.db_message_count} ≠ messages_v=${serverChat.db_messages_v}`,
            );
          }

          // Local vs server message count
          if (
            serverChat.db_message_count !== undefined &&
            localMsgCount !== serverChat.db_message_count
          ) {
            driftCount++;
            driftDetails.push(
              `  🔴 chat ${serverChat.chat_id.substring(0, 12)}... local_msg_count=${localMsgCount} ≠ server_msg_count=${serverChat.db_message_count}`,
            );
          }
        }

        // Also report any server-side errors
        for (const err of syncResp.errors) {
          serverSyncIssues.push(`Server sync error: ${err}`);
        }
      }

      if (checkedCount > 0) {
        if (driftCount === 0 && missingCount === 0) {
          allOk.push(`Server sync: all ${checkedCount} chats in sync`);
        } else {
          const parts: string[] = [];
          if (driftCount > 0) parts.push(`${driftCount} drift`);
          if (missingCount > 0) parts.push(`${missingCount} missing`);
          allIssues.push(
            `Server sync: ${parts.join(", ")} (of ${checkedCount} checked)`,
          );
          for (const detail of driftDetails.slice(0, 10)) {
            serverSyncIssues.push(detail);
          }
          if (driftDetails.length > 10) {
            serverSyncIssues.push(`  ... and ${driftDetails.length - 10} more`);
          }
        }
      } else {
        // All batches returned null (server unreachable)
        allOk.push("Server sync: unavailable (offline or not authenticated)");
      }
    }
  } catch (e) {
    allOk.push(`Server sync: check failed (${e})`);
  }

  // ═══════════════════════════════════════════════════════════════
  // OUTPUT
  // ═══════════════════════════════════════════════════════════════
  const isHealthy = allIssues.length === 0;
  const banner = isHealthy
    ? "🟢 CLIENT HEALTH: ALL OK"
    : `🔴 CLIENT HEALTH: ${allIssues.length} ISSUE(S)`;

  console.log(
    `%c${banner}`,
    `${HEALTH_BANNER_STYLE} color: ${isHealthy ? HEALTHY_BANNER_COLOR : UNHEALTHY_BANNER_COLOR};`,
  );

  // Print checks that passed (concise)
  for (const ok of allOk) {
    console.log(`  🟢 ${ok}`);
  }

  // Print issues with details
  if (allIssues.length > 0) {
    for (const issue of allIssues) {
      console.log(`  🔴 ${issue}`);
    }

    // Detail: failed chat IDs
    if (failedChatDetails.length > 0) {
      console.log("");
      console.log(
        `%c  Failed chats (${failedChatDetails.length}):`,
        "font-weight: 600; color: #dc2626;",
      );
      for (const { chatId, failedFields } of failedChatDetails.slice(0, 10)) {
        console.log(`    🔴 ${chatId} — ${failedFields.join(", ")}`);
      }
      if (failedChatDetails.length > 10) {
        console.log(`    ... and ${failedChatDetails.length - 10} more`);
      }
    }

    // Detail: failed embed IDs
    if (failedEmbedDetails.length > 0) {
      console.log("");
      console.log(
        `%c  Failed embeds (${failedEmbedDetails.length}):`,
        "font-weight: 600; color: #dc2626;",
      );
      for (const { embedId, error } of failedEmbedDetails.slice(0, 20)) {
        console.log(`    🔴 ${embedId} — ${error}`);
      }
      if (failedEmbedDetails.length > 20) {
        console.log(`    ... and ${failedEmbedDetails.length - 20} more`);
      }
    }

    // Detail: error + warning logs (last 100)
    if (errorLogCount > 0) {
      try {
        const { logCollector } = await import("./logCollector");
        const MAX_HEALTH_CHECK_LOGS = 100;
        const errorsAndWarnings = logCollector
          .getErrorLogs()
          .slice(-MAX_HEALTH_CHECK_LOGS);
        if (errorsAndWarnings.length > 0) {
          console.log("");
          console.log(
            `%c  Recent errors/warnings (${errorsAndWarnings.length}):`,
            "font-weight: 600; color: #dc2626;",
          );
          for (const e of errorsAndWarnings) {
            const icon = e.level === "error" ? "🔴" : "🟡";
            console.log(`    ${icon} [${e.level}] ${e.message}`);
          }
        }
      } catch {
        // skip
      }
    }
  }

  // Server sync issue details
  if (serverSyncIssues.length > 0) {
    console.log("");
    console.log("%c  Server sync issues:", "font-weight: 600; color: #dc2626;");
    for (const issue of serverSyncIssues) {
      console.log(issue);
    }
  }

  console.log("");
  console.info(
    "%c💡 Tip:%c type window.debug.help() to see all available commands",
    "color: #888; font-weight: bold",
    "color: #888",
  );
}

/**
 * Show all available debug commands.
 */
function showDebugHelp(): void {
  console.info(
    "%c🔧 window.debug — unified debug namespace%c\n\n" +
      "  window.debug()                            — quick client health check\n" +
      "  window.debug.help()                       — show this help\n\n" +
      "  Chat / Message:\n" +
      '  await window.debug.chat("id")             — concise report (full details if issues found)\n' +
      '  await window.debug.chat("id", {verbose: true})   — always show full details\n' +
      '  await window.debug.chat("id", {download: true})  — download report as .txt\n' +
      '  await window.debug.chatVerbose("id")      — verbose console dump\n' +
      "  await window.debug.chats()                — list all chats + consistency check\n" +
      '  await window.debug.message("id")          — raw message data\n\n' +
      "  Embeds:\n" +
      '  await window.debug.embed("id")            — embed inspection report\n' +
      '  await window.debug.embed("id", {download: true})  — download embed report\n' +
      '  await window.debug.decrypt("embedId")     — decrypt & show embed content\n\n' +
      "  Downloads:\n" +
      '  await window.debug.download("chat", "id") — download chat report as .txt\n' +
      '  await window.debug.download("embed", "id")— download embed report as .txt\n\n' +
      "  User / Suggestions / Inspirations / Settings:\n" +
      "  await window.debug.user()                 — user profile, auth state, encryption key health\n" +
      "  await window.debug.dailyInspirations()    — daily inspirations store state and health\n" +
      "  await window.debug.newChatSuggestions()   — new chat suggestions (decrypt all + health)\n" +
      "  await window.debug.settingsAndMemories() — app settings & memories (decrypt all + health)\n\n" +
      "  Keys / Encryption:\n" +
      "  All commands show full IDs and keys by default.\n" +
      "  Pass { hideKeys: true } to mask keys, e.g. debug.chat(id, {hideKeys:true})\n\n" +
      "  Diagnostics:\n" +
      "  window.debug.logs(n?, level?)             — show last N logs (default 20), filter by level\n" +
      "  window.debug.errors(n?)                   — show last N errors+warnings (default 50)\n" +
      "  window.debug.state()                      — dump current store state summary\n",
    "color: #4CAF50; font-weight: bold; font-size: 14px;",
    "color: #ccc; font-size: 12px;",
  );
}

/**
 * Initialize debug utilities and expose unified `window.debug` namespace.
 * Called once when the module is imported.
 *
 * Usage in browser console (all read-only):
 *   window.debug()                             — quick health check
 *   window.debug.help()                        — show all commands
 *   await window.debug.chat("chat-id")         — inspect a chat
 *   await window.debug.embed("embed-id")       — inspect an embed
 *   await window.debug.decrypt("embed-id")     — decrypt an embed
 */
// ============================================================================
// SETTINGS & MEMORIES DEBUG
// ============================================================================

/**
 * Inspect app settings and memories in IndexedDB with decryption health check.
 * Shows all entries grouped by app, verifies decrypt with master key,
 * and reports any failures.
 *
 * Usage in console:
 *   await window.debug.settingsAndMemories()
 */
async function debugSettingsAndMemories(): Promise<void> {
  const lines: string[] = [];
  const issues: string[] = [];

  let entries: Record<string, unknown>[] = [];
  let decryptOk = 0;
  let decryptFail = 0;
  const failedEntries: { id: string; appId: string; error: string }[] = [];
  let masterKeyAvailable = false;

  try {
    const db = await openDB();
    entries = await getAllFromStore<Record<string, unknown>>(
      db,
      APP_SETTINGS_MEMORIES_STORE,
    );
    db.close();
  } catch (e) {
    issues.push(`Failed to read IndexedDB store: ${e}`);
  }

  // Try to decrypt each entry
  if (entries.length > 0) {
    let decryptWithMasterKey: null | ((s: string) => Promise<string | null>) =
      null;
    try {
      const mod = await import("./cryptoService");
      decryptWithMasterKey = mod.decryptWithMasterKey as (
        s: string,
      ) => Promise<string | null>;
      masterKeyAvailable = true;
    } catch {
      masterKeyAvailable = false;
    }

    if (!masterKeyAvailable) {
      issues.push(
        "master key not available — cannot verify entries are decryptable",
      );
    } else {
      for (const entry of entries) {
        const enc = (entry.encrypted_item_json as string) || "";
        const entryId = String(entry.id || "?");
        const appId = String(entry.app_id || "?");
        if (!enc) {
          decryptFail++;
          failedEntries.push({
            id: entryId,
            appId,
            error: "empty encrypted_item_json",
          });
          continue;
        }
        try {
          const d = await decryptWithMasterKey!(enc);
          if (d !== null) {
            decryptOk++;
          } else {
            decryptFail++;
            failedEntries.push({
              id: entryId,
              appId,
              error: "decrypt returned null",
            });
          }
        } catch (e) {
          decryptFail++;
          failedEntries.push({ id: entryId, appId, error: String(e) });
        }
      }
    }
  }

  // Health checks
  if (decryptFail > 0) {
    issues.push(
      `${decryptFail}/${decryptOk + decryptFail} entries failed to decrypt`,
    );
  }

  // ─── Header + health at top ───
  lines.push("SETTINGS & MEMORIES");
  lines.push("═".repeat(60));
  lines.push("");

  if (issues.length === 0) {
    lines.push("🟢 Settings & Memories: HEALTHY");
  } else {
    lines.push(`🔴 Settings & Memories: ${issues.length} issue(s)`);
    for (const issue of issues) {
      lines.push(`   🔴 ${issue}`);
    }
  }
  lines.push("");

  // ─── Summary ───
  lines.push(`Total entries in IDB: ${entries.length}`);
  lines.push(
    `Master key available: ${masterKeyAvailable ? "🟢 yes" : "🔴 no"}`,
  );
  if (masterKeyAvailable && entries.length > 0) {
    lines.push(`Decrypt OK: ${decryptOk}  |  Decrypt FAILED: ${decryptFail}`);
  }
  lines.push("");

  // ─── Group by app_id ───
  const byApp: Record<string, Record<string, unknown>[]> = {};
  for (const entry of entries) {
    const appId = String(entry.app_id || "unknown");
    if (!byApp[appId]) byApp[appId] = [];
    byApp[appId].push(entry);
  }

  if (Object.keys(byApp).length > 0) {
    lines.push("Entries by app:");
    lines.push("─".repeat(60));

    for (const [appId, appEntries] of Object.entries(byApp)) {
      const types = new Set(appEntries.map((e) => String(e.item_type || "?")));
      lines.push(
        `  ${appId}: ${appEntries.length} entries (types: ${Array.from(types).join(", ")})`,
      );
    }
    lines.push("");
  }

  // ─── Failed entries ───
  if (failedEntries.length > 0) {
    lines.push("Failed entries:");
    lines.push("─".repeat(60));
    for (const { id, appId, error } of failedEntries.slice(0, 20)) {
      lines.push(`  🔴 ${id} (app: ${appId}) — ${error}`);
    }
    if (failedEntries.length > 20) {
      lines.push(`  ... and ${failedEntries.length - 20} more`);
    }
    lines.push("");
  }

  // Print
  console.log(lines.join("\n"));
}

// ============================================================================
// SERVER SYNC STATUS
// ============================================================================

/**
 * Server-side sync status for a chat returned by /v1/debug/sync.
 * Only version numbers, counts and cache presence — NO encrypted content.
 */
interface ServerChatSyncStatus {
  chat_id: string;
  found: boolean;
  db_message_count?: number;
  db_messages_v?: number;
  db_embed_count?: number;
  cache_present: boolean;
  cache_messages_v?: number;
  db_consistent?: boolean;
  db_cache_consistent?: boolean;
}

/**
 * Server-side sync status for an embed returned by /v1/debug/sync.
 */
interface ServerEmbedSyncStatus {
  embed_id: string;
  found: boolean;
  db_status?: string;
  db_key_count?: number;
  db_chat_key_count?: number;
  db_master_key_count?: number;
}

interface ServerSyncResponse {
  success: boolean;
  chats: ServerChatSyncStatus[];
  embeds: ServerEmbedSyncStatus[];
  errors: string[];
}

/** Maximum items per batch in /v1/debug/sync — must match backend MAX_BATCH_SIZE */
const SERVER_SYNC_BATCH_SIZE = 20;

/**
 * Fetch server-side sync status for a batch of chat IDs or embed IDs.
 *
 * Uses the JWT session cookie (same as all other user-facing API calls).
 * Returns null if the request fails (network error, 401, etc.) — callers
 * degrade gracefully and show "server status unavailable".
 */
async function fetchServerSyncStatus(
  chatIds?: string[],
  embedIds?: string[],
): Promise<ServerSyncResponse | null> {
  try {
    const { getApiEndpoint } = await import("../config/api");
    const body: { chat_ids?: string[]; embed_ids?: string[] } = {};
    if (chatIds && chatIds.length > 0)
      body.chat_ids = chatIds.slice(0, SERVER_SYNC_BATCH_SIZE);
    if (embedIds && embedIds.length > 0)
      body.embed_ids = embedIds.slice(0, SERVER_SYNC_BATCH_SIZE);

    const response = await fetch(getApiEndpoint("/v1/debug/sync"), {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      credentials: "include",
      body: JSON.stringify(body),
    });

    if (!response.ok) {
      // 401 = not authenticated, 422 = validation error — expected in some states
      if (response.status !== 401 && response.status !== 422) {
        console.debug(`[debug] /v1/debug/sync returned ${response.status}`);
      }
      return null;
    }

    return (await response.json()) as ServerSyncResponse;
  } catch (e) {
    console.debug("[debug] /v1/debug/sync unavailable:", e);
    return null;
  }
}

/**
 * Format a server chat sync status block for inclusion in the chat inspection report.
 */
function formatServerChatSync(
  serverStatus: ServerChatSyncStatus | undefined,
): string[] {
  if (!serverStatus)
    return ["  ⚠ Server status unavailable (offline or not authenticated)"];

  const lines: string[] = [];

  if (!serverStatus.found) {
    lines.push(
      "  🔴 NOT FOUND on server (not synced yet, or belongs to another user)",
    );
    return lines;
  }

  // DB state
  const dbMsgCount = serverStatus.db_message_count ?? "?";
  const dbMsgV = serverStatus.db_messages_v ?? "?";
  const dbEmbedCount = serverStatus.db_embed_count ?? "?";
  lines.push(
    `  DB: messages=${dbMsgCount}  messages_v=${dbMsgV}  embeds=${dbEmbedCount}`,
  );

  // Cache state
  if (serverStatus.cache_present) {
    const cacheMsgV = serverStatus.cache_messages_v ?? "?";
    lines.push(`  Cache: PRESENT  messages_v=${cacheMsgV}`);
  } else {
    lines.push("  Cache: MISSING (chat not in Redis)");
  }

  // Consistency flags
  const dbConsistent = serverStatus.db_consistent;
  const cacheConsistent = serverStatus.db_cache_consistent;

  if (dbConsistent === false) {
    lines.push(
      `  🔴 DB INCONSISTENT: actual messages (${dbMsgCount}) ≠ messages_v (${dbMsgV})`,
    );
  } else if (dbConsistent === true) {
    lines.push("  🟢 DB consistent");
  }

  if (serverStatus.cache_present) {
    if (cacheConsistent === false) {
      lines.push(
        `  🔴 CACHE STALE: DB messages_v (${dbMsgV}) ≠ cache messages_v (${serverStatus.cache_messages_v ?? "?"})`,
      );
    } else if (cacheConsistent === true) {
      lines.push("  🟢 Cache in sync with DB");
    }
  }

  return lines;
}

/**
 * Format a server embed sync status block for inclusion in the embed inspection report.
 */
function formatServerEmbedSync(
  serverStatus: ServerEmbedSyncStatus | undefined,
): string[] {
  if (!serverStatus)
    return ["  ⚠ Server status unavailable (offline or not authenticated)"];

  const lines: string[] = [];

  if (!serverStatus.found) {
    lines.push("  🔴 NOT FOUND on server");
    return lines;
  }

  const status = serverStatus.db_status ?? "unknown";
  const totalKeys = serverStatus.db_key_count ?? "?";
  const chatKeys = serverStatus.db_chat_key_count ?? "?";
  const masterKeys = serverStatus.db_master_key_count ?? "?";

  lines.push(`  DB status: ${status}`);
  lines.push(
    `  Keys: total=${totalKeys}  chat-type=${chatKeys}  master-type=${masterKeys}`,
  );

  if (serverStatus.db_key_count === 0) {
    lines.push("  🔴 NO KEYS on server — embed can only be decrypted locally");
  } else if (serverStatus.db_chat_key_count === 0) {
    lines.push("  ⚠ No chat-type keys — cross-device decrypt may fail");
  } else if (serverStatus.db_master_key_count === 0) {
    lines.push("  ⚠ No master-type keys — recovery decrypt may fail");
  } else {
    lines.push("  🟢 Keys present (chat-type + master-type)");
  }

  return lines;
}

export function initDebugUtils(): void {
  if (typeof window === "undefined") return;

  // Main callable: window.debug() → health check
  const debugFn = () => void runClientHealthCheck();

  // Attach subcommands directly on the function object
  Object.assign(debugFn, {
    /** Show all available commands */
    help: showDebugHelp,

    /** Generate a copyable chat inspection report */
    chat: (
      chatId: string,
      opts: { download?: boolean; verbose?: boolean } = {},
    ) => inspectChat(chatId, opts),

    /** Verbose console dump of a chat (all messages, all fields) */
    chatVerbose: (chatId: string) => debugChat(chatId),

    /** List all chats with consistency check */
    chats: () => debugAllChats(),

    /** Get raw message data by ID */
    message: (messageId: string) => debugGetMessage(messageId),

    /** Generate a copyable embed inspection report */
    embed: (embedId: string, opts: { download?: boolean } = {}) =>
      inspectEmbed(embedId, opts),

    /** Decrypt and show raw embed content */
    decrypt: async (embedId: string) => {
      const { embedStore } = await import("./embedStore");
      return embedStore.debugGetDecryptedEmbed(embedId);
    },

    /** Shorthand: download a chat or embed report as .txt */
    download: (type: "chat" | "embed", id: string) => {
      if (type === "chat") return inspectChat(id, { download: true });
      if (type === "embed") return inspectEmbed(id, { download: true });
      console.error(`Unknown type "${type}". Use "chat" or "embed".`);
    },

    /**
     * Show last N console logs, optionally filtered by level.
     * @param n - Max entries (default 20)
     * @param level - Filter: "error", "warn", "info", "log", "debug" (default: all)
     */
    logs: async (n = 20, level?: string) => {
      const { logCollector } = await import("./logCollector");
      type LogLevel = "log" | "info" | "warn" | "error" | "debug";
      const validLevels: LogLevel[] = ["log", "info", "warn", "error", "debug"];
      const filterLevel =
        level && validLevels.includes(level as LogLevel)
          ? (level as LogLevel)
          : undefined;
      const entries = logCollector.getLogs(n, filterLevel);
      if (entries.length === 0) {
        console.log(
          filterLevel
            ? `No ${filterLevel}-level logs captured yet.`
            : "No logs captured yet.",
        );
        return;
      }
      const label = filterLevel
        ? `📋 Last ${entries.length} ${filterLevel.toUpperCase()} log(s)`
        : `📋 Last ${entries.length} console log(s)`;
      console.group(label);
      for (const entry of entries) {
        const ts = new Date(entry.timestamp)
          .toISOString()
          .replace("T", " ")
          .slice(0, 23);
        const lvl = entry.level.toUpperCase().padEnd(5);
        console.log(`[${ts}] ${lvl}`, entry.message);
      }
      console.groupEnd();
      return entries;
    },

    /**
     * Shortcut: show last N errors + warnings from the dedicated error buffer.
     * These entries survive even when the main buffer is full of routine noise.
     * @param n - Max entries (default 50)
     */
    errors: async (n = 50) => {
      const { logCollector } = await import("./logCollector");
      const entries = logCollector.getErrorLogs(n);
      if (entries.length === 0) {
        console.log("No errors or warnings captured yet.");
        return;
      }
      console.group(`🔴 Last ${entries.length} error/warn log(s)`);
      for (const entry of entries) {
        const ts = new Date(entry.timestamp)
          .toISOString()
          .replace("T", " ")
          .slice(0, 23);
        const lvl = entry.level.toUpperCase().padEnd(5);
        // Use console.warn/error for visual distinction in the browser console
        if (entry.level === "error") {
          console.error(`[${ts}] ${lvl}`, entry.message);
        } else {
          console.warn(`[${ts}] ${lvl}`, entry.message);
        }
      }
      console.groupEnd();
      return entries;
    },

    /** Dump a summary of current store state */
    state: async () => {
      const { get } = await import("svelte/store");
      const summary: Record<string, unknown> = {};

      try {
        const { activeChatStore } = await import("../stores/activeChatStore");
        summary.activeChat = get(activeChatStore);
      } catch {
        summary.activeChat = "unavailable";
      }

      try {
        const { authStore } = await import("../stores/authState");
        const auth = get(authStore) as unknown as Record<
          string,
          unknown
        > | null;
        summary.auth = {
          isAuthenticated: auth?.isAuthenticated ?? null,
          isInitialized: auth?.isInitialized ?? null,
        };
      } catch {
        summary.auth = "unavailable";
      }

      try {
        const { userProfile } = await import("../stores/userProfile");
        const profile = get(userProfile) as unknown as Record<
          string,
          unknown
        > | null;
        summary.user = {
          id: profile?.id ?? null,
          role: profile?.role ?? null,
        };
      } catch {
        summary.user = "unavailable";
      }

      console.log("📊 Store state snapshot:", summary);
      return summary;
    },

    /** Inspect user profile and auth state with health checks */
    user: () => debugUser(),

    /** Inspect daily inspirations store state */
    dailyInspirations: () => debugDailyInspirations(),

    /** Inspect new chat suggestions in IndexedDB with decryption health check */
    newChatSuggestions: (opts?: { hideKeys?: boolean }) =>
      debugNewChatSuggestions(opts),

    /** Inspect app settings and memories with decryption health check */
    settingsAndMemories: () => debugSettingsAndMemories(),
  });

  (window as unknown as Record<string, unknown>).debug = debugFn;

  console.info(
    "%c🔧 Debug utilities loaded%c — type %cwindow.debug()%c for health check, %cwindow.debug.help()%c for all commands",
    "color: #4CAF50; font-weight: bold",
    "color: #888",
    "color: #60a5fa; font-family: monospace",
    "color: #888",
    "color: #60a5fa; font-family: monospace",
    "color: #888",
  );

  // ─── Admin-only auto-execution hooks ───────────────────────────────────────
  // Auto-run debug reports for admin users on specific events:
  //   - Chat opened → window.debug.chat(chatId)
  //   - AI response completed → window.debug.chat(chatId)
  //   - Embed opened fullscreen → window.debug.embed(embedId)
  // Reports use console.groupCollapsed to avoid spamming the console.
  void setupAdminAutoExecution();
}

/**
 * Sets up admin-only auto-execution of debug reports on specific events.
 * Only activates if the current user is an admin. Uses collapsed console groups
 * so auto-reports don't clutter the console but are available for inspection.
 */
async function setupAdminAutoExecution(): Promise<void> {
  // Gate: only activate for admin users
  const isAdmin = await isCurrentUserAdmin();
  if (!isAdmin) return;

  // Debounce timer to avoid duplicate auto-reports when multiple events fire
  // for the same chat/embed in quick succession
  const AUTO_EXEC_DEBOUNCE_MS = 1500;
  let lastAutoChatId: string | null = null;
  let lastAutoChatTime = 0;
  let lastAutoEmbedId: string | null = null;
  let lastAutoEmbedTime = 0;

  /**
   * Auto-run inspectChat in a collapsed console group.
   * Skips if the same chatId was auto-reported within the debounce window.
   */
  async function autoInspectChat(
    chatId: string,
    trigger: string,
  ): Promise<void> {
    const now = Date.now();
    if (
      chatId === lastAutoChatId &&
      now - lastAutoChatTime < AUTO_EXEC_DEBOUNCE_MS
    ) {
      return; // Skip duplicate within debounce window
    }
    lastAutoChatId = chatId;
    lastAutoChatTime = now;

    console.groupCollapsed(
      `%c🔍 [auto] debug.chat %c${trigger}%c — ${chatId}`,
      "color: #60a5fa",
      "color: #888; font-style: italic",
      "color: #60a5fa",
    );
    try {
      await inspectChat(chatId);
    } catch (e) {
      console.error("[auto] debug.chat failed:", e);
    }
    console.groupEnd();
  }

  /**
   * Auto-run inspectEmbed in a collapsed console group.
   * Skips if the same embedId was auto-reported within the debounce window.
   */
  async function autoInspectEmbed(embedId: string): Promise<void> {
    const now = Date.now();
    if (
      embedId === lastAutoEmbedId &&
      now - lastAutoEmbedTime < AUTO_EXEC_DEBOUNCE_MS
    ) {
      return; // Skip duplicate within debounce window
    }
    lastAutoEmbedId = embedId;
    lastAutoEmbedTime = now;

    console.groupCollapsed(
      `%c🔍 [auto] debug.embed %c— ${embedId}`,
      "color: #60a5fa",
      "color: #60a5fa",
    );
    try {
      await inspectEmbed(embedId);
    } catch (e) {
      console.error("[auto] debug.embed failed:", e);
    }
    console.groupEnd();
  }

  // ─── Hook 1: Chat opened (activeChatStore subscription) ─────────────────
  try {
    const { activeChatStore } = await import("../stores/activeChatStore");
    let isFirstValue = true;
    activeChatStore.subscribe((chatId: string | null) => {
      // Skip the initial subscription value (store emits current value on subscribe)
      if (isFirstValue) {
        isFirstValue = false;
        return;
      }
      if (chatId) {
        void autoInspectChat(chatId, "chat opened");
      }
    });
  } catch (e) {
    console.warn("[debug:auto] Failed to subscribe to activeChatStore:", e);
  }

  // ─── Hook 2: AI response completed (aiTaskEnded event) ─────────────────
  try {
    const { chatSyncService } = await import("./chatSyncService");
    chatSyncService.addEventListener("aiTaskEnded", ((
      event: CustomEvent<{ chatId: string; status?: string }>,
    ) => {
      const { chatId, status } = event.detail;
      if (status === "completed" && chatId) {
        // Small delay to allow final message/embed state to settle in IDB
        const AI_SETTLE_DELAY_MS = 800;
        setTimeout(() => {
          void autoInspectChat(chatId, "AI completed");
        }, AI_SETTLE_DELAY_MS);
      }
    }) as EventListener);
  } catch (e) {
    console.warn("[debug:auto] Failed to listen for aiTaskEnded:", e);
  }

  // ─── Hook 3: Embed opened fullscreen (document embedfullscreen event) ──
  try {
    document.addEventListener("embedfullscreen", ((
      event: CustomEvent<{ embedId?: string }>,
    ) => {
      const embedId = event.detail?.embedId;
      if (embedId) {
        void autoInspectEmbed(embedId);
      }
    }) as EventListener);
  } catch (e) {
    console.warn("[debug:auto] Failed to listen for embedfullscreen:", e);
  }

  console.info(
    "%c🔍 Admin auto-debug active%c — chat/embed reports auto-run on open, AI completion, and embed fullscreen",
    "color: #4CAF50; font-weight: bold",
    "color: #888",
  );
}
