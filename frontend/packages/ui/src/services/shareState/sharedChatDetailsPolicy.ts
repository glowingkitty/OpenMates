// frontend/packages/ui/src/services/shareState/sharedChatDetailsPolicy.ts
// spec: specifications/surfaces/sdk#sdk.client.thin-platform-boundary
// Bounded-page validation rules of sharedChatDetailsService.ts (plans, tasks and
// sub-chats). The service fetches and decrypts; with VITE_OPENMATES_RUST_CORE=1
// the shared Rust core decides whether a public ciphertext page is well formed,
// contiguous and advancing (web_share_state). Failures throw the original Error text.

type Kind = "plans" | "tasks";
interface Cursor { timestamp: number; id: string }
interface Window { has_more_after?: boolean; end_cursor?: string | null; oversized_key_id?: string | null }

const OK = { ok: true } as const;
const MAX_WRAPPER_PAGES = 20;

/** True when `next` does not move strictly backwards from `cursor` (the page failed to advance). */
function notBefore(next: Cursor, cursor: Cursor): boolean {
  return next.timestamp > cursor.timestamp || (next.timestamp === cursor.timestamp && next.id >= cursor.id);
}

export function detailsCursorCheck(input: { kind: Kind; cursor?: Cursor | null }) {
  const { kind, cursor } = input;
  if (cursor && (!Number.isSafeInteger(cursor.timestamp) || cursor.timestamp < 0 || !cursor.id)) {
    throw new Error(`Shared ${kind} cursor was invalid`);
  }
  return OK;
}

export function detailsPageCheck(input: {
  kind: Kind; chat_id: string; cursor?: Cursor | null;
  page: {
    items_is_array: boolean;
    items?: Array<{ updated_at?: unknown; id?: unknown; primary_chat_id?: unknown }>;
    key_wrappers_is_array: boolean; has_more_before?: unknown; payload_bytes?: unknown;
    start_cursor?: Cursor | null; oversized_id?: string | null;
  };
}) {
  const { kind, chat_id: chatId, cursor, page } = input;
  if (!page.items_is_array || (page.items ?? []).length > 20 || !page.key_wrappers_is_array
    || typeof page.has_more_before !== "boolean" || !Number.isSafeInteger(page.payload_bytes)
    || Number(page.payload_bytes) < 0 || Number(page.payload_bytes) > 131_072) {
    throw new Error(`Shared ${kind} page was invalid`);
  }
  const items = page.items ?? [];
  const positions = items.map((item) => ({
    timestamp: item.updated_at as number,
    id: item.id as string,
    primaryChatId: item.primary_chat_id,
  }));
  if (positions.some((position, index) => !Number.isSafeInteger(position.timestamp)
    || typeof position.id !== "string" || !position.id
    || (position.primaryChatId != null && position.primaryChatId !== chatId)
    || (index > 0 && (position.timestamp < positions[index - 1].timestamp
      || (position.timestamp === positions[index - 1].timestamp && position.id <= positions[index - 1].id))))) {
    throw new Error(`Shared ${kind} page identities or order were invalid`);
  }
  const oldest = positions[0];
  if (items.length && (!page.start_cursor || page.start_cursor.timestamp !== oldest.timestamp
    || page.start_cursor.id !== oldest.id)) throw new Error(`Shared ${kind} page cursor was invalid`);
  if (page.has_more_before && !page.start_cursor && !page.oversized_id) {
    throw new Error(`Shared ${kind} page cannot advance`);
  }
  if (cursor && page.start_cursor && notBefore(page.start_cursor, cursor)) {
    throw new Error(`Shared ${kind} cursor did not advance`);
  }
  return OK;
}

export function detailsExactCheck(input: {
  kind: Kind; chat_id: string; id: string;
  exact: { has_item: boolean; key_wrappers_is_array: boolean; item_id?: unknown; updated_at?: unknown; primary_chat_id?: unknown };
}) {
  const { kind, chat_id: chatId, id, exact } = input;
  if (!exact.has_item || !exact.key_wrappers_is_array) throw new Error(`Shared ${kind} item was invalid`);
  if (exact.item_id !== id || !Number.isSafeInteger(exact.updated_at)
    || (exact.primary_chat_id != null && exact.primary_chat_id !== chatId)) {
    throw new Error(`Shared ${kind} item identity changed`);
  }
  return OK;
}

export function detailsOversizedAdvance(input: { kind: Kind; cursor?: Cursor | null; start_cursor?: Cursor | null }) {
  const { cursor, start_cursor: start } = input;
  if (cursor && start && notBefore(start, cursor)) {
    throw new Error(`Shared ${input.kind} oversized cursor did not advance`);
  }
  return OK;
}

export function detailsWrapperStep(input: { kind: Kind; window: Window }) {
  const { window } = input;
  if (window.oversized_key_id) return { param: "key_id", value: window.oversized_key_id };
  if (window.end_cursor) return { param: "after_key_id", value: window.end_cursor };
  throw new Error(`Shared ${input.kind} key cursor did not advance`);
}

export function detailsWrapperAdvance(input: {
  kind: Kind; window: Window; continuation: { key_wrappers_is_array: boolean; window?: Window | null };
}) {
  const { kind, window, continuation } = input;
  if (!continuation.key_wrappers_is_array || !continuation.window) {
    throw new Error(`Shared ${kind} key window was invalid`);
  }
  if (window.oversized_key_id) {
    return { window: { ...continuation.window, has_more_after: true,
      end_cursor: window.oversized_key_id, oversized_key_id: null } };
  }
  if (continuation.window.has_more_after
    && continuation.window.end_cursor === window.end_cursor
    && !continuation.window.oversized_key_id) {
    throw new Error(`Shared ${kind} key cursor did not advance`);
  }
  return { window: continuation.window };
}

export function detailsWrapperContinue(input: { window?: Window | null; count: number }): boolean {
  return !!(input.window?.has_more_after && input.count < MAX_WRAPPER_PAGES);
}

export function detailsWrapperDone(input: { kind: Kind; window?: Window | null }) {
  if (input.window?.has_more_after) {
    throw new Error(`Shared ${input.kind} key window exceeded the bounded retry limit`);
  }
  return OK;
}

/** Indexes of continuation wrappers whose id was not seen yet. */
export function detailsWrapperDedup(input: { seen: string[]; wrappers: Array<{ id?: string | null }> }): number[] {
  const seen = new Set(input.seen);
  const add: number[] = [];
  input.wrappers.forEach((wrapper, index) => {
    if (!wrapper.id || seen.has(wrapper.id)) return;
    seen.add(wrapper.id);
    add.push(index);
  });
  return add;
}

interface SubRow { id?: unknown; parent_id?: unknown; is_sub_chat?: unknown; created_at?: unknown }

function validSharedSubChat(row: unknown, parentId: string): boolean {
  if (!row || typeof row !== "object" || Array.isArray(row)) return false;
  const item = row as SubRow;
  return typeof item.id === "string" && item.id.length > 0
    && item.parent_id === parentId && item.is_sub_chat === true
    && Number.isSafeInteger(item.created_at) && Number(item.created_at) > 0;
}

export function subChatCursorCheck(input: { chat_id: string; before?: Cursor | null }) {
  const { chat_id: chatId, before } = input;
  if (!chatId || (before && (!Number.isSafeInteger(before.timestamp) || before.timestamp <= 0 || !before.id))) {
    throw new Error("Invalid shared subchat cursor.");
  }
  return OK;
}

export function subChatPageCheck(input: {
  chat_id: string;
  page: {
    items_is_array: boolean; rows?: unknown[]; has_more_before?: unknown; payload_bytes?: unknown;
    start_cursor?: unknown; oversized_id?: unknown;
  };
}) {
  const { chat_id: chatId, page } = input;
  const rows = page.rows ?? [];
  if (!page.items_is_array || rows.length > 20
    || typeof page.has_more_before !== "boolean"
    || !Number.isSafeInteger(page.payload_bytes) || Number(page.payload_bytes) < 0
    || Number(page.payload_bytes) > 131_072
    || rows.some((item) => !validSharedSubChat(item, chatId))) {
    throw new Error("Shared subchat page had invalid bounded metadata.");
  }
  if (page.oversized_id != null) {
    if (rows.length !== 0 || typeof page.oversized_id !== "string" || !page.oversized_id || !page.has_more_before) {
      throw new Error("Shared subchat oversized cursor was invalid.");
    }
    return { mode: "fetch_oversized" as const, id: page.oversized_id };
  }
  let cursor: Cursor | null = null;
  if (page.start_cursor != null) {
    const start = page.start_cursor as Record<string, unknown>;
    if (!Number.isSafeInteger(start.timestamp) || Number(start.timestamp) <= 0 || typeof start.id !== "string" || !start.id) {
      throw new Error("Shared subchat page cursor was invalid.");
    }
    cursor = { timestamp: start.timestamp as number, id: start.id };
  }
  return { mode: "items" as const, cursor };
}

export function subChatOversizedCheck(input: { chat_id: string; oversized_id: string; item: unknown }) {
  if (!validSharedSubChat(input.item, input.chat_id) || (input.item as SubRow).id !== input.oversized_id) {
    throw new Error("Shared oversized subchat identity did not match its cursor.");
  }
  const item = input.item as { created_at: number; id: string };
  return { cursor: { timestamp: item.created_at, id: item.id } };
}

export function subChatFinalCheck(input: {
  rows: Array<{ id: string; created_at: number }>; cursor?: Cursor | null; has_more_before: boolean; before?: Cursor | null;
}) {
  const { rows: items, cursor, before } = input;
  if (items.length && (!cursor || cursor.timestamp !== items[0].created_at || cursor.id !== items[0].id
    || items.some((item, index) => index > 0 && (item.created_at < items[index - 1].created_at
      || (item.created_at === items[index - 1].created_at && item.id <= items[index - 1].id))))) {
    throw new Error("Shared subchat page was not a contiguous chronological window.");
  }
  if (input.has_more_before && !cursor) throw new Error("Shared subchat page did not provide its next cursor.");
  if (before && cursor && notBefore(cursor, before)) {
    throw new Error("Shared subchat cursor did not advance.");
  }
  return OK;
}

export const DETAILS_OPS = {
  detailsCursorCheck, detailsPageCheck, detailsExactCheck, detailsOversizedAdvance,
  detailsWrapperStep, detailsWrapperAdvance, detailsWrapperContinue, detailsWrapperDone, detailsWrapperDedup,
  subChatCursorCheck, subChatPageCheck, subChatOversizedCheck, subChatFinalCheck,
};
