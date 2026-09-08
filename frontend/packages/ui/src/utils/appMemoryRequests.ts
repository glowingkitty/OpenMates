/**
 * Shared memory-consent request identity and metadata for web and CLI.
 * Requests carry category metadata only; they never confer consent or contain
 * the selected memory plaintext. Each caller encrypts the resulting message.
 * Legacy duplicates are merged only in the local history projection.
 * Architecture: docs/architecture/pii-protection.md
 */

const REQUEST_TYPE = "app_settings_memories_request" as const;
const COUNT_SEMANTICS_VERSION = 1;

export interface MemoryRequestCategory {
  appId: string;
  itemType: string;
  entryCount: number | null;
}

export interface MemoryRequestContent {
  type: typeof REQUEST_TYPE;
  user_message_id: string;
  request_id: string;
  requested_keys: string[];
  categories: MemoryRequestCategory[];
  count_semantics_version?: number;
}

export function buildMemoryRequestMessage(params: {
  userMessageId: string;
  requestId: string;
  requestedKeys: string[];
  createdAt: number;
  entryCounts?: ReadonlyMap<string, number | null>;
}) {
  if (!params.requestId || !params.userMessageId) {
    throw new Error("Memory requests require stable request and user-message identities");
  }
  const keys = [...new Set(params.requestedKeys)].sort();
  const categories: MemoryRequestCategory[] = [];
  for (const key of keys) {
    const separator = key.indexOf("-");
    if (separator <= 0 || separator === key.length - 1) {
      throw new Error(`Invalid memory category key: ${key}`);
    }
    const count = params.entryCounts?.get(key);
    categories.push({
      appId: key.slice(0, separator),
      itemType: key.slice(separator + 1),
      entryCount: Number.isSafeInteger(count) && count! >= 0 ? count! : null,
    });
  }
  const content: MemoryRequestContent = {
    type: REQUEST_TYPE,
    user_message_id: params.userMessageId,
    request_id: params.requestId,
    requested_keys: keys,
    categories,
    count_semantics_version: COUNT_SEMANTICS_VERSION,
  };
  return {
    message_id: params.requestId,
    role: "system" as const,
    content: JSON.stringify(content),
    created_at: params.createdAt,
    user_message_id: params.userMessageId,
  };
}

export function parseMemoryRequest(content: unknown, clientMessageId?: string): MemoryRequestContent | null {
  if (typeof content !== "string") return null;
  let value: MemoryRequestContent;
  try { value = JSON.parse(content); } catch { return null; }
  if (!value || value.type !== REQUEST_TYPE || typeof value.request_id !== "string"
    || typeof value.user_message_id !== "string" || !Array.isArray(value.requested_keys)
    || !Array.isArray(value.categories) || value.categories.some(category => !category
      || typeof category.appId !== "string" || typeof category.itemType !== "string")
    || value.requested_keys.some(key => typeof key !== "string")) return null;
  const legacyCli = value.count_semantics_version === undefined && clientMessageId === value.request_id;
  return {
    ...value,
    categories: value.categories.map(category => ({
      ...category,
      // Old CLI writers used zero for every category, including unavailable counts.
      entryCount: legacyCli || !Number.isSafeInteger(category.entryCount) || category.entryCount! < 0
        ? null : category.entryCount,
    })),
  };
}

export function mergeMemoryRequests(first: MemoryRequestContent, second: MemoryRequestContent): MemoryRequestContent {
  if (first.request_id !== second.request_id || first.user_message_id !== second.user_message_id) {
    throw new Error("Cannot merge distinct memory consent requests");
  }
  const categories = new Map<string, MemoryRequestCategory>();
  for (const category of [...first.categories, ...second.categories]) {
    const key = `${category.appId}-${category.itemType}`;
    const previous = categories.get(key);
    // This merges available-entry snapshots only, never selected entries or decisions.
    // Known snapshots win over unknown ones; the larger known snapshot breaks ties
    // deterministically for historical clients with different local sync freshness.
    if (!previous || (category.entryCount !== null
      && (previous.entryCount === null || category.entryCount > previous.entryCount))) {
      categories.set(key, category);
    }
  }
  return {
    ...first,
    count_semantics_version: COUNT_SEMANTICS_VERSION,
    requested_keys: [...new Set([...first.requested_keys, ...second.requested_keys])].sort(),
    categories: [...categories.entries()].sort(([a], [b]) => a.localeCompare(b)).map(([, category]) => category),
  };
}

export function coalesceMemoryRequestMessages<T extends {
  role: string; content: string; clientMessageId?: string;
}>(messages: T[]): T[] {
  const result: T[] = [];
  const requests = new Map<string, { index: number; content: MemoryRequestContent }>();
  for (const message of messages) {
    const request = message.role === "system" ? parseMemoryRequest(message.content, message.clientMessageId) : null;
    if (!request) { result.push(message); continue; }
    const key = JSON.stringify([request.user_message_id, request.request_id]);
    const previous = requests.get(key);
    const merged = previous ? mergeMemoryRequests(previous.content, request) : request;
    const index = previous?.index ?? result.length;
    result[index] = { ...(result[index] ?? message), content: JSON.stringify(merged) };
    requests.set(key, { index, content: merged });
  }
  return result;
}
