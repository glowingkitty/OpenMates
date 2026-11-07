// frontend/packages/ui/src/services/shareState/anonymousChatPolicy.ts
// spec: specifications/features/auth#auth.keys.client-wrapped
// Pure helpers of anonymousChatStorage.ts: next timestamp, assistant message id,
// chat title, streaming-adapter chunk ends, conversation rows and plain-field
// stripping. With VITE_OPENMATES_RUST_CORE=1 the shared Rust core decides
// (web_share_state); lengths and cut points are UTF-16 units and the service
// slices strings with the returned offsets. The message sort stays in the
// service: its comparator is not a total order (V8 TimSort dependent).

const STREAM_ADAPTER_MAX_CHUNKS = 18;

/** Next message timestamp: one after the latest message, never below the fallback. */
export function anonymousNextTimestamp(input: { created_ats: Array<number | null>; fallback: number }): number {
  const latestMessageTimestamp = input.created_ats.reduce<number>((latest, value) => {
    const createdAt = Number(value ?? 0);
    return Number.isFinite(createdAt) ? Math.max(latest, createdAt) : latest;
  }, 0);
  return latestMessageTimestamp > 0 ? Math.max(input.fallback, latestMessageTimestamp + 1) : input.fallback;
}

export function anonymousAssistantMessageId(input: {
  response_message_id?: string | null; streamed?: boolean; chat_id: string; user_message_id: string; new_uuid: string;
}): string {
  const created = `${input.chat_id.slice(-10)}-${input.new_uuid}`;
  const responseId = input.response_message_id;
  if (!responseId || responseId === input.user_message_id) return created;
  // Stream chunks are persisted under the server's message ID by ActiveChat.
  // Reuse that ID when saving the final response so reload cannot show both rows.
  if (input.streamed) return responseId;
  return responseId.startsWith(`${input.chat_id}-`) ? responseId : `${input.chat_id}-${responseId}`;
}

/** First non-blank line of the markdown without json fences, cut to 50 units (the original rule, byte for byte). */
export function anonymousTitle(input: { markdown: string }): string {
  const firstLine = input.markdown
    .replace(/```json[\s\S]*?```/g, "")
    .split("\n")
    .map((line) => line.trim())
    .find(Boolean);
  if (!firstLine) return "Anonymous chat";
  return firstLine.length > 50 ? `${firstLine.slice(0, 50)}...` : firstLine;
}

/** Replaces lone surrogates with U+FFFD (String.prototype.toWellFormed where available, else by hand). */
export function toWellFormedText(text: string): string {
  const native = (text as unknown as { toWellFormed?: () => string }).toWellFormed;
  if (typeof native === "function") return native.call(text);
  return text.replace(/[\ud800-\udbff](?![\udc00-\udfff])|(?<![\ud800-\udbff])[\udc00-\udfff]/g, "\ufffd");
}

/**
 * The title as it crosses the Rust boundary: JSON and Rust strings cannot carry a lone
 * surrogate, and the title is encrypted through TextEncoder, which writes U+FFFD for one.
 * Used for the parity vectors only; the flag-off page path keeps `anonymousTitle` unchanged.
 */
export function anonymousTitleWire(input: { markdown: string }): string {
  return toWellFormedText(anonymousTitle(input));
}

/** Prefix lengths of the progressive chunks of one streamed adapter response. */
export function anonymousChunkEnds(input: { length: number }): number[] {
  if (!input.length) return [0];
  const chunkCount = Math.min(STREAM_ADAPTER_MAX_CHUNKS, Math.max(1, Math.ceil(input.length / 48)));
  const chunkSize = Math.ceil(input.length / chunkCount);
  const ends: number[] = [];
  for (let end = chunkSize; end < input.length; end += chunkSize) ends.push(end);
  ends.push(input.length);
  return ends;
}

/** Indexes of non-failed user/assistant rows with non-blank text. */
export function anonymousConversationRows(input: {
  rows: Array<{ status?: string; role?: string; content?: unknown }>;
}): number[] {
  const indexes: number[] = [];
  input.rows.forEach((message, index) => {
    if (message.status !== "failed" && (message.role === "user" || message.role === "assistant")
      && typeof message.content === "string" && message.content.trim().length > 0) indexes.push(index);
  });
  return indexes;
}

/** Chat row without the plaintext fields that are re-derived from the encrypted ones. */
export function anonymousStripPlain(input: { chat: Record<string, unknown> }): Record<string, unknown> {
  const chatToStore = { ...input.chat };
  delete chatToStore.title;
  delete chatToStore.category;
  delete chatToStore.icon;
  delete chatToStore.chat_summary;
  return chatToStore;
}

export const ANONYMOUS_OPS = {
  anonymousNextTimestamp, anonymousAssistantMessageId, anonymousTitle,
  anonymousChunkEnds, anonymousConversationRows, anonymousStripPlain,
};
