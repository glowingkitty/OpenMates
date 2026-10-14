/* Internal-only encrypted embed continuation. UUID comparisons are typed SQL:
 * Directus REST intentionally does not support _lt/_gt on UUID schema fields.
 * The API caller derives these scopes from its existing authorization checks.
 */
import { ProtocolError } from './operations.js';

const EMBED_FIELDS = 'id,embed_id,hashed_embed_id,hashed_chat_id,hashed_message_id,hashed_task_id,encrypted_type,status,hashed_user_id,app_id,skill_id,hashed_team_id,workspace_origin,root_embed_id,is_private,is_shared,shared_with_users,embed_ids,encrypted_content,encrypted_text_preview,parent_embed_id,version_number,encrypted_diff,file_path,content_hash,encryption_mode,vault_key_id,created_at,updated_at'.split(',');
const KEY_FIELDS = 'id,hashed_embed_id,key_type,hashed_chat_id,hashed_project_id,hashed_team_id,encrypted_embed_key,hashed_user_id,created_at'.split(',');
const HASH = /^[0-9a-f]{64}$/;
const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/;
const MAX_RAW_BYTES = 256 * 1024 * 1024;
const invalid = () => { throw new ProtocolError(400, 'invalid_scoped_read'); };
const hash = (value) => { if (typeof value !== 'string' || !HASH.test(value)) invalid(); return value; };
const uuid = (value) => { if (typeof value !== 'string' || !UUID.test(value)) invalid(); return value; };
function fields(body, allowed, required = allowed) {
  if (Object.keys(body).some((key) => !allowed.includes(key)) || required.some((key) => !(key in body))) invalid();
}
function hashes(value, max) {
  if (!Array.isArray(value) || !value.length || value.length > max) invalid();
  const result = value.map(hash);
  if (new Set(result).size !== result.length) invalid();
  return result;
}

export async function readScopedEmbedPage(database, body) {
  if (!body || typeof body !== 'object' || Array.isArray(body)) invalid();
  let query;
  let limit;
  if (body.operation === 'embed_window') {
    fields(body, ['operation', 'hashed_chat_id', 'before_created_at', 'before_id']);
    const chatHash = hash(body.hashed_chat_id);
    const id = uuid(body.before_id);
    const timestamp = body.before_created_at;
    if (!Number.isSafeInteger(timestamp) || timestamp < 0 || timestamp > 2_147_483_647) invalid();
    query = database('embeds').select(EMBED_FIELDS).where('hashed_chat_id', chatHash)
      .andWhere(function () {
        this.where('created_at', '<', timestamp).orWhere(function () {
          this.where('created_at', timestamp).andWhere('id', '<', id);
        });
      }).orderBy('created_at', 'desc').orderBy('id', 'desc');
    limit = 31;
  } else if (body.operation === 'embed_key_window') {
    fields(body, ['operation', 'hashed_chat_id', 'hashed_user_id', 'hashed_embed_ids', 'include_master_keys', 'after_id']);
    const chatHash = hash(body.hashed_chat_id);
    const selected = hashes(body.hashed_embed_ids, 30);
    const after = uuid(body.after_id);
    if (typeof body.include_master_keys !== 'boolean') invalid();
    const owner = body.include_master_keys ? hash(body.hashed_user_id) : null;
    if (!body.include_master_keys && body.hashed_user_id !== null) invalid();
    query = database('embed_keys').select(KEY_FIELDS).whereIn('hashed_embed_id', selected)
      .andWhere(function () {
        this.where(function () { this.where('key_type', 'chat').andWhere('hashed_chat_id', chatHash); });
        if (owner) this.orWhere(function () { this.where('key_type', 'master').andWhere('hashed_user_id', owner); });
      }).andWhere('id', '>', after).orderBy('id', 'asc');
    limit = 61;
  } else if (body.operation === 'complete_embeds' || body.operation === 'complete_embed_keys') {
    const keys = body.operation === 'complete_embed_keys';
    const chatScope = 'hashed_chat_id' in body;
    fields(body, ['operation', chatScope ? 'hashed_chat_id' : 'hashed_embed_ids', 'after_id', ...(keys ? ['key_type'] : [])]);
    const after = uuid(body.after_id);
    query = database(keys ? 'embed_keys' : 'embeds').select(keys ? KEY_FIELDS : EMBED_FIELDS);
    if (chatScope) query.where('hashed_chat_id', hash(body.hashed_chat_id));
    else query.whereIn('hashed_embed_id', hashes(body.hashed_embed_ids, 20));
    if (keys) {
      // Complete master exports follow hashes discovered from chat-scoped keys.
      if (body.key_type !== (chatScope ? 'chat' : 'master')) invalid();
      query.andWhere('key_type', body.key_type);
    }
    query.andWhere('id', '>', after).orderBy('id', 'asc');
    limit = 20;
  } else invalid();
  const rows = await query.limit(limit);
  if (!Array.isArray(rows) || rows.length > limit) throw new ProtocolError(500, 'scoped_read_unavailable');
  // Fail closed rather than returning a successful partial export. Interactive
  // API byte caps and exact oversized-row fallbacks remain at the caller.
  if (Buffer.byteLength(JSON.stringify(rows), 'utf8') > MAX_RAW_BYTES) {
    throw new ProtocolError(413, 'scoped_read_too_large');
  }
  return rows;
}
