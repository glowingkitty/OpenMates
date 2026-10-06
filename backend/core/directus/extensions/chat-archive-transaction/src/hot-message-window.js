/* Internal fixed ciphertext projection; API callers authorize owner/Team scope. */
import { ArchiveProtocolError } from './operations.js';

export const HOT_MESSAGE_FIELDS = ["id", "client_message_id", "chat_id", "encrypted_content", "role", "encrypted_sender_name", "encrypted_category", "encrypted_model_name", "encrypted_thinking_content", "encrypted_thinking_signature", "has_thinking", "thinking_token_count", "encrypted_pii_mappings", "user_message_id", "created_at"];
const KEYS = new Set(['chat_id', 'direction', 'limit', 'cursor_timestamp',
  'cursor_message_id', 'lower_bound_timestamp']);
const ID = `COALESCE(NULLIF(client_message_id, ''), id::text) COLLATE "C"`;
function requireWindow(condition) {
  if (!condition) throw new ArchiveProtocolError('invalid_hot_message_window', 400);
}
function timestamp(value) { return Number.isSafeInteger(value); }

export async function readHotMessageWindow(trx, data) {
  requireWindow(data && Object.keys(data).every(key => KEYS.has(key))
    && typeof data.chat_id === 'string' && data.chat_id.length > 0 && data.chat_id.length <= 256
    && ['latest', 'before', 'after'].includes(data.direction)
    && Number.isSafeInteger(data.limit) && data.limit >= 1 && data.limit <= 101);
  const cursor = data.cursor_timestamp;
  const messageId = data.cursor_message_id;
  const lower = data.lower_bound_timestamp;
  requireWindow((cursor == null || timestamp(cursor)) && (lower == null || timestamp(lower))
    && (messageId == null || (typeof messageId === 'string' && messageId.length <= 256))
    && (data.direction === 'latest' ? cursor == null && !messageId : cursor != null));
  const after = data.direction === 'after';
  const order = after ? 'ASC' : 'DESC';
  const clauses = ['chat_id = ?'];
  const bindings = [data.chat_id];
  if (cursor != null) {
    if (messageId) {
      clauses.push(`(created_at, ${ID}) ${after ? '>' : '<'} (?, ?::text COLLATE "C")`);
      bindings.push(cursor, messageId);
    } else {
      // Preserve existing timestamp-only cursors: before is inclusive, after strict.
      clauses.push(`created_at ${after ? '>' : '<='} ?`);
      bindings.push(cursor);
    }
  }
  if (lower != null) { clauses.push('created_at > ?'); bindings.push(lower); }
  const result = await trx.raw(`SELECT ${HOT_MESSAGE_FIELDS.join(', ')} FROM messages
    WHERE ${clauses.join(' AND ')}
    ORDER BY created_at ${order}, ${ID} ${order}
    LIMIT ?`, [...bindings, data.limit]);
  const messages = result.rows || result[0];
  if (!Array.isArray(messages) || messages.length > data.limit)
    throw new ArchiveProtocolError('hot_message_window_query_failed', 503);
  return { messages };
}
