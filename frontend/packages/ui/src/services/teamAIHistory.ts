/** Full, ephemeral Team transcript for an explicitly invoked AI turn. */
import { getApiEndpoint, storageArchiveFetch } from "../config/api";
import type { Message } from "../types/chat";
import { decryptWithChatKey } from "./encryption/MessageEncryptor";

type Cursor = { created_at: number; message_id: string };
type EncryptedRow = {
  message_id: string;
  chat_id: string;
  role: Message["role"];
  created_at: number;
  encrypted_content: string;
  encrypted_sender_name?: string;
};
type Window = {
  chat_id: string;
  messages: Array<EncryptedRow | string>;
  has_more_before: boolean;
  start_cursor: Cursor | null;
  oversized_message_cursor?: Cursor | null;
  server_message_count?: number | null;
};

/** Ordinary Team sends never read/decrypt local history. */
export async function loadLocalSavedHistoryForSend(
  chatId: string,
  teamId: string | null | undefined,
  readMessages: (chatId: string) => Promise<Message[]>,
): Promise<Message[]> {
  if (teamId) return [];
  const messages = await readMessages(chatId);
  return messages.length > 1 ? messages : [];
}

/** Local pending turns must not silently disappear from an AI invocation. */
export function assertNoOmittedTeamTurns(
  localMessages: Message[],
  serverHistory: Message[],
  currentMessageId: string,
): void {
  const authoritativeIds = new Set(serverHistory.map((message) => message.message_id));
  for (const message of localMessages) {
    if (message.message_id !== currentMessageId && message.status !== "synced"
        && !authoritativeIds.has(message.message_id)) {
      throw new Error("Team AI history has an unsent or unconfirmed local turn");
    }
  }
}

function parseRow(raw: EncryptedRow | string, chatId: string): EncryptedRow {
  const row: unknown = typeof raw === "string" ? JSON.parse(raw) : raw;
  if (!row || typeof row !== "object") throw new Error("Team history contains an invalid row");
  const value = row as Partial<EncryptedRow> & { client_message_id?: string };
  const id = value.message_id || value.client_message_id;
  if (!id || value.chat_id !== chatId || !["user", "assistant", "system"].includes(value.role ?? "")
      || typeof value.created_at !== "number" || !Number.isSafeInteger(value.created_at)
      || typeof value.encrypted_content !== "string"
      || !value.encrypted_content) throw new Error("Team history row identity or ciphertext is invalid");
  return { ...value, message_id: id } as EncryptedRow;
}

function assertCursor(cursor: Cursor | null | undefined): asserts cursor is Cursor {
  if (!cursor || !Number.isSafeInteger(cursor.created_at) || typeof cursor.message_id !== "string"
      || !cursor.message_id) throw new Error("Team history continuation cursor is invalid");
}

/** The server must authorize every page against this exact Team, including oversized rows. */
export async function loadTeamAIHistory(params: {
  chatId: string;
  teamId: string;
  currentMessageId: string;
  chatKey: Uint8Array;
  assertScope: () => void;
  /** Set only for a freshly created local chat whose first user row is current. */
  allowMissingInitialChat?: boolean;
}): Promise<Message[]> {
  const { chatId, teamId, currentMessageId, chatKey, assertScope } = params;
  if (!chatId || !teamId || !chatKey.length) throw new Error("Team history requires an authorized Team chat key");
  const rows = new Map<string, EncryptedRow>();
  let cursor: Cursor | null = null;
  let expectedCount: number | null = null;
  for (;;) {
    assertScope();
    const query = new URLSearchParams({
      team_id: teamId, direction: cursor ? "before" : "latest", limit: "100",
      respect_compression_boundary: "false",
    });
    if (cursor) {
      query.set("before_timestamp", String(cursor.created_at));
      query.set("before_message_id", cursor.message_id);
    }
    const response = await storageArchiveFetch(getApiEndpoint(
      `/v1/chats/${encodeURIComponent(chatId)}/messages/window?${query}`
    ), { credentials: "include", cache: "no-store" });
    assertScope();
    if (response.status === 404 && !cursor && rows.size === 0 && params.allowMissingInitialChat) {
      return [];
    }
    if (!response.ok) throw new Error(`Team history read failed: ${response.status}`);
    const page = await response.json() as Window;
    assertScope();
    if (page.chat_id !== chatId || !Array.isArray(page.messages)
        || typeof page.has_more_before !== "boolean") throw new Error("Team history page is invalid");
    if (typeof page.server_message_count === "number"
        && Number.isSafeInteger(page.server_message_count) && page.server_message_count >= 0) {
      if (expectedCount !== null && expectedCount !== page.server_message_count) {
        throw new Error("Team history changed while loading");
      }
      expectedCount = page.server_message_count!;
    }
    const pageRows = page.messages.map((raw) => parseRow(raw, chatId));
    if (page.oversized_message_cursor) {
      const oversized = page.oversized_message_cursor;
      assertCursor(oversized);
      const exactQuery = new URLSearchParams({ team_id: teamId });
      const exactResponse = await storageArchiveFetch(getApiEndpoint(
        `/v1/chats/${encodeURIComponent(chatId)}/messages/${encodeURIComponent(oversized.message_id)}?${exactQuery}`
      ), { credentials: "include", cache: "no-store" });
      assertScope();
      if (!exactResponse.ok) throw new Error(`Team history oversized row failed: ${exactResponse.status}`);
      const exact = await exactResponse.json() as { message?: EncryptedRow | string };
      assertScope();
      if (!exact.message) throw new Error("Team history oversized row is missing");
      const row = parseRow(exact.message, chatId);
      if (row.message_id !== oversized.message_id || row.created_at !== oversized.created_at) {
        throw new Error("Team history oversized row identity mismatch");
      }
      pageRows.push(row);
    }
    if (pageRows.length === 0 && page.has_more_before) throw new Error("Team history page made no progress");
    for (const row of pageRows) {
      const prior = rows.get(row.message_id);
      if (prior && (prior.created_at !== row.created_at || prior.encrypted_content !== row.encrypted_content)) {
        throw new Error("Team history returned conflicting message identities");
      }
      rows.set(row.message_id, row);
    }
    if (!page.has_more_before) break;
    // The byte bound can select zero rows and nominate one exact oversized
    // message. In that shape start_cursor is null; its exact cursor advances.
    const nextCursor = page.start_cursor ?? page.oversized_message_cursor;
    assertCursor(nextCursor);
    if (cursor && (nextCursor.created_at > cursor.created_at
        || (nextCursor.created_at === cursor.created_at
          && nextCursor.message_id >= cursor.message_id))) {
      throw new Error("Team history cursor did not advance");
    }
    cursor = nextCursor;
  }
  // The current message may already exist on a retry; the canonical outbound
  // content is appended by buildTeamMessageTransport exactly once.
  if (expectedCount !== null && rows.size !== expectedCount) {
    throw new Error("Team history is incomplete");
  }
  const ordered = [...rows.values()].filter((row) => row.message_id !== currentMessageId)
    .sort((a, b) => a.created_at - b.created_at || a.message_id.localeCompare(b.message_id));
  const history: Message[] = [];
  for (const row of ordered) {
    assertScope();
    const content = await decryptWithChatKey(row.encrypted_content, chatKey,
      { chatId, fieldName: "content" });
    if (typeof content !== "string") throw new Error("Team history content could not be decrypted");
    let senderName: string | undefined;
    if (row.encrypted_sender_name) {
      senderName = await decryptWithChatKey(row.encrypted_sender_name, chatKey,
        { chatId, fieldName: "sender_name" });
      if (!senderName) throw new Error("Team history sender could not be decrypted");
    } else if (row.role === "user") {
      throw new Error("Team history sender attribution is missing");
    }
    assertScope();
    history.push({ message_id: row.message_id, chat_id: chatId, role: row.role,
      created_at: row.created_at, status: "synced", content, sender_name: senderName ?? row.role });
  }
  assertScope();
  return history;
}
