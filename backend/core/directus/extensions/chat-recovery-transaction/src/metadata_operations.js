/* Generated metadata has its own sealed contract. Assistant protocol 1 stays strict. */
const JOBS = 'chat_metadata_recovery_jobs';
const PREFLIGHTS = 'chat_turn_preflights';
const CHATS = 'chats';
const FIELDS = new Set(['encrypted_title', 'encrypted_chat_summary', 'encrypted_category', 'encrypted_icon']);
const STAGES = new Set(['initial', 'postprocessing']);
const json = (value) => typeof value === 'string' ? JSON.parse(value) : value;
const snapshot = (chat) => Object.fromEntries([...FIELDS].map((field) => [field, chat[field] ?? null]));

export function metadataOperations(h) {
  const { fail, exactKeys, string, uuid, integer, validateEnvelope, digest, ownedChat,
    JOB_TTL_MS, TOMBSTONE_TTL_MS } = h;
  const request = (raw, keys) => {
    const body = exactKeys(raw, new Set(['protocol_version', ...keys]), ['protocol_version', ...keys], 'invalid_metadata_request');
    if (body.protocol_version !== 1) fail(400, 'unsupported_metadata_protocol');
    return body;
  };
  const summary = (row) => ({ job_id: row.id, chat_id: row.chat_id, task_id: row.task_id,
    stage: row.stage, chat_key_version: row.chat_key_version, state: row.state });
  const owned = async (trx, body, now) => {
    let row = await trx(JOBS).where({ id: uuid(body.job_id, 'invalid_job_id') }).first();
    if (!row || row.hashed_user_id !== string(body.hashed_user_id, 'invalid_owner', 64)) fail(404, 'metadata_job_not_found');
    const chat = await ownedChat(trx, row.chat_id, row.hashed_user_id);
    row = await trx(JOBS).where({ id: row.id }).forUpdate().first();
    if (!row) fail(404, 'metadata_job_not_found');
    if (chat.hashed_team_id) fail(404, 'metadata_job_not_found');
    const preflight = await trx(PREFLIGHTS).where({ id: row.preflight_id }).first();
    if (!preflight || preflight.deletion_invalidated_at || preflight.hashed_user_id !== row.hashed_user_id
      || preflight.chat_id !== row.chat_id || preflight.chat_key_version !== row.chat_key_version
      || chat.encrypted_chat_key !== preflight.wrapped_chat_key) fail(409, 'metadata_key_mismatch');
    if (row.state === 'AVAILABLE' && new Date(row.expires_at) <= now) fail(410, 'metadata_job_expired');
    return { row, chat, preflight };
  };
  return {
    async create_metadata_job(database, raw, now) {
      const body = request(raw, ['job_id', 'hashed_user_id', 'chat_id', 'task_id', 'inference_task_id',
        'preflight_id', 'chat_key_version', 'stage', 'source_metadata_v', 'generated_at', 'encrypted_fields', 'sealed_payload']);
      const identity = {
        hashed_user_id: string(body.hashed_user_id, 'invalid_owner', 64),
        chat_id: uuid(body.chat_id, 'invalid_chat_id'), task_id: uuid(body.task_id, 'invalid_task_id'),
        inference_task_id: uuid(body.inference_task_id, 'invalid_task_id'),
        preflight_id: uuid(body.preflight_id, 'invalid_preflight_id'),
        chat_key_version: integer(body.chat_key_version, 'invalid_key_version'),
        stage: body.stage,
      };
      if (!STAGES.has(identity.stage) || identity.chat_key_version < 1) fail(400, 'invalid_metadata_stage');
      if (!Array.isArray(body.encrypted_fields) || !body.encrypted_fields.length
        || new Set(body.encrypted_fields).size !== body.encrypted_fields.length
        || body.encrypted_fields.some((field) => !FIELDS.has(field))) fail(400, 'invalid_metadata_fields');
      const fields = [...body.encrypted_fields].sort();
      const sourceVersion = integer(body.source_metadata_v, 'invalid_metadata_version');
      // Timestamp is created once by the inference worker before durable
      // admission, and is retained verbatim by its sealed-only retry. Arrival
      // order cannot make an older generation replace a newer continuation.
      const generatedAt = new Date(body.generated_at);
      if (typeof body.generated_at !== 'string' || !Number.isFinite(generatedAt.getTime())
        || generatedAt.toISOString() !== body.generated_at || generatedAt > now) fail(400, 'invalid_metadata_generation');
      if (generatedAt.getTime() + JOB_TTL_MS <= now.getTime()) fail(410, 'metadata_job_expired');
      const id = uuid(body.job_id, 'invalid_job_id');
      const sealed = validateEnvelope(body.sealed_payload);
      if (Buffer.byteLength(sealed, 'utf8') > 90 * 1024) fail(400, 'invalid_sealed_payload');
      return database.transaction(async (trx) => {
        // Serialize create/commit stages on the same chat. A retry can reseal
        // with fresh randomness; immutable identity retains the first envelope.
        const chat = await ownedChat(trx, identity.chat_id, identity.hashed_user_id);
        if (chat.hashed_team_id) fail(404, 'chat_not_found');
        const preflight = await trx(PREFLIGHTS).where({ id: identity.preflight_id }).first();
        if (!preflight || !['RUNNING', 'TERMINAL'].includes(preflight.state) || preflight.deletion_invalidated_at
          || preflight.hashed_user_id !== identity.hashed_user_id || preflight.chat_id !== identity.chat_id
          || preflight.inference_task_id !== identity.inference_task_id
          || preflight.chat_key_version !== identity.chat_key_version
          || chat.encrypted_chat_key !== preflight.wrapped_chat_key) fail(409, 'metadata_inference_mismatch');
        if (preflight.prepared_at && generatedAt < new Date(preflight.prepared_at)) fail(400, 'invalid_metadata_generation');
        const existing = await trx(JOBS).where({ id }).first();
        if (existing) {
          if (Object.entries(identity).some(([key, value]) => existing[key] !== value)
            || new Date(existing.generated_at).getTime() !== generatedAt.getTime()
            || JSON.stringify(json(existing.encrypted_fields)) !== JSON.stringify(fields)) fail(409, 'metadata_job_mismatch');
          return summary(existing);
        }
        const siblings = await trx(JOBS).where({ preflight_id: identity.preflight_id, chat_id: identity.chat_id,
          hashed_user_id: identity.hashed_user_id }).orderBy('created_at', 'asc').select(['baseline_fields', 'baseline_metadata_v', 'source_metadata_v', 'sequence']);
        const row = { id, ...identity, encrypted_fields: JSON.stringify(fields), sealed_payload: sealed,
          sealed_payload_digest: digest(sealed), baseline_fields: JSON.stringify(
            siblings[0] ? json(siblings[0].baseline_fields) : snapshot(chat)),
          sequence: Math.max(0, ...siblings.map((sibling) => sibling.sequence)) + 1,
          baseline_metadata_v: siblings[0]?.baseline_metadata_v ?? Math.max(chat.metadata_v ?? 0, chat.title_v ?? 0),
          source_metadata_v: siblings[0]?.source_metadata_v ?? sourceVersion,
          committed_fields: null, committed_metadata_v: null, committed_title_v: null,
          state: 'AVAILABLE', generated_at: generatedAt, created_at: now, expires_at: new Date(generatedAt.getTime() + JOB_TTL_MS) };
        await trx(JOBS).insert(row);
        return summary(row);
      });
    },
    async list_metadata_jobs(database, raw, now) {
      const body = request(raw, ['hashed_user_id']);
      const owner = string(body.hashed_user_id, 'invalid_owner', 64);
      const rows = await database(JOBS).where({ hashed_user_id: owner, state: 'AVAILABLE' })
        .andWhere('expires_at', '>', now).orderBy('created_at', 'asc').orderBy('id', 'asc')
        .limit(100).select(['id', 'chat_id', 'task_id', 'stage', 'chat_key_version', 'state']);
      return { jobs: rows.map(summary) };
    },
    async metadata_job_admitted(database, raw, now) {
      const body = request(raw, ['hashed_user_id', 'chat_id', 'task_id']);
      const row = await database(JOBS).where({ hashed_user_id: string(body.hashed_user_id, 'invalid_owner', 64),
        chat_id: uuid(body.chat_id, 'invalid_chat_id'), task_id: uuid(body.task_id, 'invalid_task_id') })
        .andWhere('expires_at', '>', now).first();
      return { admitted: !!row };
    },
    async claim_metadata_job(database, raw, now) {
      const body = request(raw, ['job_id', 'hashed_user_id']);
      return database.transaction(async (trx) => {
        const { row } = await owned(trx, body, now);
        return { ...summary(row), ...(row.state === 'AVAILABLE' ? { sealed_payload: row.sealed_payload,
          encrypted_fields: json(row.encrypted_fields) } : {}) };
      });
    },
    async persist_metadata_job(database, raw, now) {
      const body = request(raw, ['job_id', 'hashed_user_id', 'chat_key_version', 'wrapped_chat_key', 'encrypted_metadata']);
      const encrypted = exactKeys(body.encrypted_metadata, FIELDS, [], 'invalid_metadata_fields');
      for (const value of Object.values(encrypted)) string(value, 'invalid_metadata_ciphertext', 90 * 1024);
      const keyVersion = integer(body.chat_key_version, 'invalid_key_version');
      const wrappedKey = string(body.wrapped_chat_key, 'invalid_wrapped_chat_key', 4096);
      return database.transaction(async (trx) => {
        const { row, chat, preflight } = await owned(trx, body, now);
        if (keyVersion !== row.chat_key_version || wrappedKey !== preflight.wrapped_chat_key) fail(409, 'metadata_key_mismatch');
        const result = (state, fields = {}) => ({ ...summary({ ...row, state }),
          versions: { metadata_v: row.committed_metadata_v ?? chat.metadata_v ?? 0,
            title_v: row.committed_title_v ?? chat.title_v ?? 0 }, encrypted_metadata: fields });
        if (row.state !== 'AVAILABLE') return result(row.state, json(row.committed_fields) ?? {});
        const required = json(row.encrypted_fields);
        if (required.length !== Object.keys(encrypted).length || required.some((field) => !(field in encrypted))) fail(400, 'invalid_metadata_fields');
        const newerTurn = await trx(PREFLIGHTS).where({ chat_id: row.chat_id, hashed_user_id: row.hashed_user_id })
          .whereNull('deletion_invalidated_at').andWhere('committed_messages_v', '>', preflight.committed_messages_v).first();
        const siblings = await trx(JOBS).where({ chat_id: row.chat_id, preflight_id: row.preflight_id,
          hashed_user_id: row.hashed_user_id }).select(['stage', 'state', 'committed_fields', 'sequence', 'generated_at']);
        const isLater = (sibling) => new Date(sibling.generated_at) > new Date(row.generated_at)
          || (+new Date(sibling.generated_at) === +new Date(row.generated_at) && sibling.sequence > row.sequence);
        const laterCommitted = siblings.some((sibling) => sibling.state === 'TERMINAL'
          && (isLater(sibling) || (row.stage === 'initial' && sibling.stage === 'postprocessing')));
        const baseline = json(row.baseline_fields);
        const prior = siblings.filter((sibling) => sibling.state === 'TERMINAL' && !isLater(sibling)).map((sibling) => json(sibling.committed_fields) ?? {});
        const updates = {};
        if (!newerTurn && !laterCommitted && row.baseline_metadata_v <= row.source_metadata_v) {
          for (const [field, value] of Object.entries(encrypted)) {
            const current = chat[field] ?? null;
            if (current === baseline[field] || prior.some((fields) => fields[field] === current)) updates[field] = value;
          }
        }
        const applied = Object.keys(updates).length > 0;
        const metadataVersion = Math.max(chat.metadata_v ?? 0, chat.title_v ?? 0) + (applied ? 1 : 0);
        const titleVersion = (chat.title_v ?? 0) + ('encrypted_title' in updates ? 1 : 0);
        if (applied) {
          await trx(CHATS).where({ id: chat.id, hashed_user_id: row.hashed_user_id }).update({ ...updates,
            metadata_v: metadataVersion, title_v: titleVersion, updated_at: Math.floor(now.getTime() / 1000) });
        }
        const state = applied ? 'TERMINAL' : 'SUPERSEDED';
        await trx(JOBS).where({ id: row.id, state: 'AVAILABLE' }).update({ state, sealed_payload: null,
          sealed_payload_digest: null, committed_fields: JSON.stringify(updates), committed_metadata_v: metadataVersion,
          committed_title_v: titleVersion, completed_at: now,
          tombstone_expires_at: new Date(now.getTime() + TOMBSTONE_TTL_MS) });
        return { ...result(state, updates), versions: { metadata_v: metadataVersion, title_v: titleVersion } };
      });
    },
  };
}
