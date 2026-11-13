// frontend/packages/ui/src/services/shareState/sharedChatKeyPolicy.ts
// spec: specifications/surfaces/sdk#sdk.client.thin-platform-boundary
// Entry-building and read-mapping rules of sharedChatKeyStorage.ts. IndexedDB I/O
// and the raw key bytes stay in the storage module; with VITE_OPENMATES_RUST_CORE=1
// the shared Rust core decides (web_share_state), otherwise these rules run.

/** Metadata stored next to the key bytes (`saveSharedChatKey`). */
export function sharedKeyEntryMeta(input: { chat_id: string; share_url?: string | null; now_ms: number }) {
  return {
    chat_id: input.chat_id,
    created_at: Math.floor(input.now_ms / 1000),
    share_url: input.share_url ?? null,
  };
}

/** Exact share URL of a stored entry; an empty string reads as no URL. */
export function sharedKeyEntryUrl(input: { entry: { share_url?: string | null } | null }): string | null {
  return input.entry?.share_url || null;
}

/** Indexes of cursor rows that have both an id and key bytes. */
export function sharedKeyLoadable(input: { entries: Array<{ chat_id?: string | null; has_key: boolean }> }): number[] {
  const indexes: number[] = [];
  input.entries.forEach((entry, index) => {
    if (entry.chat_id && entry.has_key) indexes.push(index);
  });
  return indexes;
}

export const SHARED_KEY_OPS = { sharedKeyEntryMeta, sharedKeyEntryUrl, sharedKeyLoadable };
