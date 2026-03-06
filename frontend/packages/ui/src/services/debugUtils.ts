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
 *   window.debug.logs(20)                  — last N console logs
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

function appendHealthCheckSection(
  lines: string[],
  healthSummary: { isHealthy: boolean; issues: string[]; warnings: string[] },
  countsLine: string,
): void {
  lines.push("");
  lines.push("=".repeat(100));
  lines.push("HEALTH CHECK SUMMARY");
  lines.push("=".repeat(100));
  lines.push(
    healthSummary.isHealthy
      ? "🟢 HEALTH CHECK: HEALTHY"
      : "🔴 HEALTH CHECK: ISSUES DETECTED",
  );
  lines.push(`  Counts: ${countsLine}`);

  if (healthSummary.issues.length > 0) {
    lines.push("  Issues:");
    for (const issue of healthSummary.issues.slice(
      0,
      MAX_HEALTH_ITEMS_TO_SHOW,
    )) {
      lines.push(`   - ${issue}`);
    }
    if (healthSummary.issues.length > MAX_HEALTH_ITEMS_TO_SHOW) {
      lines.push(
        `   - ... and ${healthSummary.issues.length - MAX_HEALTH_ITEMS_TO_SHOW} more issue(s)`,
      );
    }
  }

  if (healthSummary.warnings.length > 0) {
    lines.push("  Warnings:");
    for (const warning of healthSummary.warnings.slice(
      0,
      MAX_HEALTH_ITEMS_TO_SHOW,
    )) {
      lines.push(`   - ${warning}`);
    }
  }
  lines.push("=".repeat(100));
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
  chatKeySource: "cache" | "unwrapped" | "none";
  metadataFields: FieldDecryptResult[];
  messageFields: { messageIndex: number; role: string; success: boolean; error?: string }[];
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
  // Show first 8 bytes of chat key as hex fingerprint (16 hex chars)
  const keyHex = Array.from(chatKey.slice(0, 8))
    .map((b) => b.toString(16).padStart(2, "0"))
    .join("");
  report.chatKeyFingerprint = `${keyHex}... (${chatKey.length} bytes, source: ${report.chatKeySource})`;

  // Step 2: Try decrypting each chat metadata field
  const { decryptWithChatKey } = await import("./cryptoService");

  const encryptedMetadataFields: Array<{ field: string; key: string }> = [
    { field: "Title", key: "encrypted_title" },
    { field: "Category", key: "encrypted_category" },
    { field: "Icon", key: "encrypted_icon" },
    { field: "Summary", key: "encrypted_chat_summary" },
    { field: "Tags", key: "encrypted_chat_tags" },
    { field: "Draft", key: "encrypted_draft_md" },
    { field: "Follow-up Suggestions", key: "encrypted_follow_up_request_suggestions" },
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
  options: { download?: boolean; verbose?: boolean } = {},
): Promise<string> {
  const forceVerbose = options.verbose || options.download || false;
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
  const decryptionReport = await attemptChatDecryption(chatId, chatMeta, messages);

  // ---- Build health summary (now includes decryption results) ----
  const metaDecryptFailed = decryptionReport.metadataFields.filter((f) => !f.success).length;
  const metaDecryptTotal = decryptionReport.metadataFields.length;
  const msgDecryptFailed = decryptionReport.messageFields.filter((f) => !f.success).length;
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
    healthSummary.issues.push("chat key could not be obtained (master key unavailable or decryption failed)");
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
  lines.push(
    `CHAT ${chatId}  |  ${createdStr}`,
  );
  lines.push(
    `Key: ${decryptionReport.chatKeyFingerprint}`,
  );

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
        lines.push(`  · ${fd.shortLabel.padEnd(12)} not present`);
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
          lines.push(
            `  ✓ ${fd.shortLabel.padEnd(12)} "${preview}"`,
          );
        } else {
          lines.push(
            `  ✗ ${fd.shortLabel.padEnd(12)} DECRYPT FAILED`,
          );
        }
      } else {
        // Encrypted data present but no decrypt attempt (key unavailable)
        lines.push(
          `  ? ${fd.shortLabel.padEnd(12)} encrypted (${encValue.length} chars, not decrypted)`,
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
      const msgId = (msg.id as string) || (msg.message_id as string) || "N/A";

      // Decrypt status
      const msgDecrypt = decryptionReport.messageFields.find(
        (m) => m.messageIndex === i + 1,
      );
      let decryptStatus: string;
      if (msg.content && !msg.encrypted_content) {
        decryptStatus = "· plain";
      } else if (msgDecrypt) {
        decryptStatus = msgDecrypt.success ? "✓ OK" : "✗ FAIL";
      } else if (!msg.encrypted_content && !msg.content) {
        decryptStatus = "· empty";
      } else {
        decryptStatus = "? N/A";
      }

      lines.push(
        `  ${(i + 1).toString().padStart(3)}  ${role.padEnd(10)} ${created.padEnd(28)} ${decryptStatus.padEnd(9)} ${truncate(msgId, 12)}`,
      );
    });
  } else {
    lines.push("  (none)");
  }

  // Embeds table
  lines.push("");
  lines.push(
    `EMBEDS (${chatEmbeds.length})  |  Keys: ${chatEmbedKeys.length}`,
  );

  if (chatEmbeds.length > 0) {
    lines.push(
      `  ${"#".padStart(3)}  ${"Type".padEnd(16)} ${"Status".padEnd(10)} ${"Decrypt".padEnd(9)} Embed ID`,
    );

    // Build a map from embedId to decode attempt result for quick lookup
    const embedDecodeMap = new Map<string, boolean>();
    for (const attempt of embedDecodeHealth.attempts) {
      embedDecodeMap.set(attempt.embedId, !!attempt.decoded);
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
        decryptStatus = embedDecodeMap.get(cleanEmbedId) ? "✓ OK" : "✗ FAIL";
      } else if (embed.content || embed.data) {
        decryptStatus = "· plain";
      } else if (!embed.encrypted_content) {
        decryptStatus = "· empty";
      } else {
        decryptStatus = "- skip";
      }

      // Child count suffix
      const childSuffix =
        embed.embed_ids && Array.isArray(embed.embed_ids) && (embed.embed_ids as string[]).length > 0
          ? `  [${(embed.embed_ids as string[]).length} children]`
          : "";

      lines.push(
        `  ${(i + 1).toString().padStart(3)}  ${type.padEnd(16)} ${status.padEnd(10)} ${decryptStatus.padEnd(9)} ${truncate(cleanEmbedId, 12)}${childSuffix}`,
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
      lines.push(`  DB:          ${DB_NAME} v${(await openDB().then((d) => { const v = d.version; d.close(); return v; }))}`);

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

  console.log(report);

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

  const embedHealthSummary = buildClientEmbedHealthSummary({
    embed,
    childEmbeds: childEmbedRecords,
  });
  appendHealthCheckSection(
    lines,
    embedHealthSummary,
    `child_embeds=${childEmbedRecords.length}`,
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

  logHealthCheckBanner("EMBED", embedHealthSummary.isHealthy);

  // Output full report to console as a single string for easy copying
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
// INITIALIZATION - Expose unified window.debug namespace
// ============================================================================

/**
 * Run a quick client-side health check and print a summary to the console.
 * This is what `window.debug()` calls by default (no arguments).
 *
 * Checks:
 *  - IndexedDB connectivity (chats, messages, embeds, keys counts)
 *  - Active chat store state
 *  - Last 5 console errors from logCollector
 */
async function runClientHealthCheck(): Promise<void> {
  console.group(
    "%c🔍 Client Health Check",
    "color: #4CAF50; font-weight: bold",
  );

  // 1. IndexedDB connectivity
  try {
    const db = await openDB();
    const chatCount = await getStoreCount(db, CHATS_STORE);
    const msgCount = await getStoreCount(db, MESSAGES_STORE);
    const embedCount = await getStoreCount(db, EMBEDS_STORE);
    const keyCount = await getStoreCount(db, EMBED_KEYS_STORE);
    db.close();
    console.log(
      `✅ IndexedDB OK — chats: ${chatCount}, messages: ${msgCount}, embeds: ${embedCount}, keys: ${keyCount}`,
    );
  } catch (e) {
    console.error(`❌ IndexedDB FAILED: ${e}`);
  }

  // 2. Active chat state (dynamic import to avoid circular deps)
  try {
    const { get } = await import("svelte/store");
    const { activeChatStore } = await import("../stores/activeChatStore");
    const state = get(activeChatStore) as unknown as Record<
      string,
      unknown
    > | null;
    if (state) {
      const activeChatId = state.activeChatId ?? null;
      console.log(
        `✅ Active chat store: ${activeChatId ? `chat ${activeChatId}` : "no active chat"}`,
      );
    } else {
      console.log("ℹ️  Active chat store: empty (no active chat)");
    }
  } catch {
    console.log("ℹ️  Active chat state unavailable");
  }

  // 3. Last N console errors from logCollector
  try {
    const { logCollector } = await import("./logCollector");
    const errors = logCollector
      .getLogs(100)
      .filter((e: { level: string }) => e.level === "error")
      .slice(-5);
    if (errors.length === 0) {
      console.log("✅ No recent console errors");
    } else {
      console.warn(`⚠️  Last ${errors.length} console error(s):`);
      for (const e of errors) {
        console.warn(`   [${e.level}] ${e.message}`);
      }
    }
  } catch {
    console.log("ℹ️  Log collector unavailable");
  }

  console.groupEnd();
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
      "  Diagnostics:\n" +
      "  window.debug.logs(n?)                     — show last N console logs (default 20)\n" +
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
export function initDebugUtils(): void {
  if (typeof window === "undefined") return;

  // Main callable: window.debug() → health check
  const debugFn = () => void runClientHealthCheck();

  // Attach subcommands directly on the function object
  Object.assign(debugFn, {
    /** Show all available commands */
    help: showDebugHelp,

    /** Generate a copyable chat inspection report */
    chat: (chatId: string, opts: { download?: boolean; verbose?: boolean } = {}) =>
      inspectChat(chatId, opts),

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

    /** Show last N console logs from logCollector (default 20) */
    logs: async (n = 20) => {
      const { logCollector } = await import("./logCollector");
      const entries = logCollector.getLogs(n);
      if (entries.length === 0) {
        console.log("No logs captured yet.");
        return;
      }
      console.group(`📋 Last ${entries.length} console log(s)`);
      for (const entry of entries) {
        const ts = new Date(entry.timestamp).toISOString();
        console.log(`[${ts}] [${entry.level}]`, entry.message);
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
}
