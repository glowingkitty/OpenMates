/* Atomic, owner-scoped workflow head/version/trigger/undo publication. */
import { randomUUID } from 'node:crypto';

const OWNER_RE = /^user_sha256:[0-9a-f]{64}$/;
const SHA_RE = /^sha256:[0-9a-f]{64}$/;
const OP_RE = /^[A-Za-z0-9._:-]{1,160}$/;
const REF_RE = /^vault:\/\/workflows\/[A-Za-z0-9_/-]+$/;
const TABLES = {
  heads: 'workflows', versions: 'workflow_versions', triggers: 'workflow_triggers',
  blobs: 'workflow_encrypted_blobs', mutations: 'workflow_input_mutations',
  receipts: 'workflow_authoring_operations',
};

export class AuthoringError extends Error {
  constructor(status, code) { super(code); this.status = status; this.code = code; }
}
const fail = (status, code) => { throw new AuthoringError(status, code); };
const object = (value) => {
  if (!value || typeof value !== 'object' || Array.isArray(value)) fail(400, 'invalid_request');
  return value;
};
const string = (value, max = 255) => {
  if (typeof value !== 'string' || !value || Buffer.byteLength(value, 'utf8') > max) fail(400, 'invalid_request');
  return value;
};
const integer = (value) => {
  if (!Number.isSafeInteger(value) || value < 0 || value > 2_147_483_647) fail(400, 'invalid_request');
  return value;
};
const jsonValue = (value) => typeof value === 'string' ? JSON.parse(value) : value;

function identity(raw) {
  const body = object(raw);
  if (!OWNER_RE.test(string(body.owner_hash, 80))
      || !OP_RE.test(string(body.operation_id, 160))
      || (body.request_hash !== undefined && !SHA_RE.test(string(body.request_hash, 72)))) fail(400, 'invalid_request');
  return body;
}

function receiptResult(row) {
  return { operation_id: row.operation_id, owner_hash: row.hashed_user_id,
    request_hash: row.request_hash, outcomes: jsonValue(row.outcomes_json) };
}

async function receipt(database, raw) {
  const body = identity(raw);
  const row = await database(TABLES.receipts).where({ operation_id: body.operation_id }).first();
  if (!row) return { found: false };
  if (row.hashed_user_id !== body.owner_hash || row.request_hash !== body.request_hash) fail(409, 'operation_conflict');
  return { found: true, ...receiptResult(row) };
}

async function operation(database, raw) {
  const body = identity(raw);
  const row = await database(TABLES.receipts).where({ operation_id: body.operation_id }).first();
  if (!row || row.hashed_user_id !== body.owner_hash) return { found: false };
  const mutations = await database(TABLES.mutations)
    .where({ operation_id: body.operation_id, hashed_user_id: body.owner_hash }).orderBy('created_at', 'asc');
  return { found: true, ...receiptResult(row), mutations };
}

function validateWrite(write, owner) {
  object(write);
  const workflowId = string(write.workflow_id);
  const record = object(write.record);
  if (record.id !== workflowId || record.owner_hash !== owner || record.hashed_team_id) fail(400, 'invalid_owner');
  const expected = write.expected_version;
  if (expected !== null) integer(expected);
  const version = integer(record.version);
  if (version !== (expected === null ? 1 : expected + 1)) fail(400, 'invalid_version');
  if (!Array.isArray(record.versions) || !record.versions.length || record.versions.length > 100) fail(400, 'invalid_versions');
  if (!record.versions.some((entry) => entry.id === record.current_version_id
    && entry.encrypted_graph_ref === record.encrypted_graph_ref
    && entry.encrypted_graph_checksum === record.encrypted_graph_checksum)) fail(400, 'invalid_versions');
  if (write.trigger !== null) {
    const trigger = object(write.trigger);
    if (trigger.workflow_id !== workflowId || trigger.owner_hash !== owner
        || trigger.version_id !== record.current_version_id) fail(400, 'invalid_trigger');
  }
  return { workflowId, record, expected, trigger: write.trigger };
}

function addRef(refs, ref, checksum = null) {
  if (ref === null || ref === undefined) return;
  if (!REF_RE.test(string(ref, 512))) fail(400, 'invalid_blob_ref');
  if (checksum !== null && !SHA_RE.test(string(checksum, 72))) fail(400, 'invalid_blob_checksum');
  const earlier = refs.get(ref);
  if (earlier && checksum && earlier !== checksum) fail(400, 'blob_checksum_conflict');
  refs.set(ref, checksum || earlier || null);
}

async function verifyRefs(trx, owner, writes, mutations, blobs) {
  const refs = new Map();
  for (const { record, trigger } of writes) {
    for (const name of ['title', 'description', 'category', 'icon', 'graph']) {
      addRef(refs, record[`encrypted_${name}_ref`], record[`encrypted_${name}_checksum`] || null);
    }
    for (const version of record.versions) addRef(refs, version.encrypted_graph_ref, version.encrypted_graph_checksum);
    if (trigger) for (const name of ['schedule_config', 'event_predicate', 'webhook_config', 'required_start_input_schema']) {
      addRef(refs, trigger[`encrypted_${name}_ref`]);
    }
  }
  for (const mutation of mutations) {
    addRef(refs, mutation.encrypted_before_ref, mutation.encrypted_before_checksum);
    addRef(refs, mutation.encrypted_after_ref, mutation.encrypted_after_checksum);
  }
  const staged = new Map();
  for (const blob of blobs) {
    object(blob);
    if (!REF_RE.test(string(blob.ref, 512)) || blob.owner_hash !== owner
        || !SHA_RE.test(string(blob.checksum, 72)) || !string(blob.ciphertext, 2 * 1024 * 1024)) fail(400, 'invalid_blob');
    if (staged.has(blob.ref)) fail(400, 'duplicate_blob');
    staged.set(blob.ref, blob);
  }
  const missing = [];
  for (const [ref, checksum] of refs) {
    const blob = staged.get(ref);
    if (blob) {
      if (checksum && blob.checksum !== checksum) fail(400, 'blob_checksum_conflict');
    } else missing.push(ref);
  }
  if (missing.length) {
    const rows = await trx(TABLES.blobs).whereIn('ref', missing).select('ref', 'hashed_user_id', 'checksum');
    const found = new Map(rows.map((row) => [row.ref, row]));
    for (const ref of missing) {
      const row = found.get(ref);
      if (!row || row.hashed_user_id !== owner || (refs.get(ref) && row.checksum !== refs.get(ref))) fail(409, 'blob_reference_conflict');
    }
  }
  return refs;
}

function headRow(record) {
  return {
    id: record.id, workflow_id: record.id, hashed_user_id: record.owner_hash,
    hashed_team_id: record.hashed_team_id || null,
    encrypted_title: record.encrypted_title_ref, encrypted_description: record.encrypted_description_ref || null,
    encrypted_category: record.encrypted_category_ref || null, encrypted_icon: record.encrypted_icon_ref || null,
    encrypted_slug: record.encrypted_slug || null, slug_lookup_hash: record.slug_lookup_hash || null,
    status: record.status, enabled: Boolean(record.enabled), lifecycle: record.lifecycle || 'persisted',
    source: record.source || 'manual', source_chat_id: record.source_chat_id || null,
    created_by_assistant: Boolean(record.created_by_assistant), auto_delete_at: record.auto_delete_at || null,
    kept_at: record.kept_at || null, version: record.version, current_version_id: record.current_version_id,
    trigger_type: record.trigger_type || record.trigger_summary || null, trigger_summary: record.trigger_summary || null,
    next_run_at: record.next_run_at || null, last_run_id: record.last_run_id || null,
    last_run_status: record.last_run_status || null, run_content_retention: record.run_content_retention || null,
    deleted_at: record.status === 'deleted' ? record.updated_at : null,
    record_json: JSON.stringify(record), created_at: record.created_at, updated_at: record.updated_at,
  };
}

function triggerRow(trigger) {
  if (!trigger) return null;
  return {
    trigger_id: trigger.trigger_id, workflow_id: trigger.workflow_id, version_id: trigger.version_id,
    hashed_user_id: trigger.owner_hash, owner_user_id: trigger.owner_user_id,
    hashed_project_id: trigger.hashed_project_id || null, trigger_type: trigger.trigger_type,
    source: trigger.source || null, event_type: trigger.event_type || null,
    encrypted_schedule_config_ref: trigger.encrypted_schedule_config_ref || null,
    encrypted_event_predicate_ref: trigger.encrypted_event_predicate_ref || null,
    encrypted_webhook_config_ref: trigger.encrypted_webhook_config_ref || null,
    encrypted_required_start_input_schema_ref: trigger.encrypted_required_start_input_schema_ref || null,
    enabled: Boolean(trigger.enabled), next_run_at: trigger.next_run_at || null,
    claim_status: trigger.claim_status || null, claim_token_hash: trigger.claim_token_hash || null,
    claim_generation: trigger.claim_generation || 0, claimed_at: trigger.claimed_at || null,
    claim_expires_at: trigger.claim_expires_at || null,
    created_at: trigger.created_at, updated_at: trigger.updated_at,
  };
}

async function commit(database, raw) {
  const body = identity(raw);
  if (!SHA_RE.test(string(body.request_hash, 72)) || !Array.isArray(body.writes)
      || body.writes.length < 1 || body.writes.length > 32 || !Array.isArray(body.blobs)
      || body.blobs.length > 512 || !Array.isArray(body.mutations)
      || body.mutations.length !== body.writes.length || !Array.isArray(body.outcomes)
      || body.outcomes.length !== body.writes.length
      || !Array.isArray(body.obsolete_refs || []) || (body.obsolete_refs || []).length > 512) fail(400, 'invalid_request');
  const writes = body.writes.map((write) => validateWrite(write, body.owner_hash));
  if (new Set(writes.map((write) => write.workflowId)).size !== writes.length) fail(400, 'duplicate_target');
  const slugs = writes.map((write) => write.record.slug_lookup_hash).filter(Boolean);
  if (new Set(slugs).size !== slugs.length) fail(409, 'slug_conflict');
  for (let index = 0; index < writes.length; index += 1) {
    const mutation = object(body.mutations[index]);
    const outcome = object(body.outcomes[index]);
    if (mutation.operation_id !== body.operation_id || mutation.hashed_user_id !== body.owner_hash
        || mutation.target_id !== writes[index].workflowId || mutation.target_type !== 'workflow'
        || outcome.workflow_id !== writes[index].workflowId || outcome.version !== writes[index].record.version
        || outcome.after_ref !== mutation.encrypted_after_ref) fail(400, 'invalid_mutation');
  }
  return database.transaction(async (trx) => {
    await trx.raw('SELECT pg_advisory_xact_lock(hashtext(?))', [`workflow-authoring:${body.operation_id}`]);
    const priorReceipt = await trx(TABLES.receipts).where({ operation_id: body.operation_id }).first();
    if (priorReceipt) {
      if (priorReceipt.hashed_user_id !== body.owner_hash || priorReceipt.request_hash !== body.request_hash) fail(409, 'operation_conflict');
      return receiptResult(priorReceipt);
    }
    if (body.undo_of_operation_id) {
      if (!OP_RE.test(string(body.undo_of_operation_id, 160))) fail(400, 'invalid_undo');
      const original = await trx(TABLES.receipts).where({ operation_id: body.undo_of_operation_id,
        hashed_user_id: body.owner_hash }).forUpdate().first();
      if (!original) fail(409, 'undo_conflict');
      const originalRows = await trx(TABLES.mutations).where({ operation_id: body.undo_of_operation_id,
        hashed_user_id: body.owner_hash }).forUpdate();
      const originalOutcomes = jsonValue(original.outcomes_json);
      if (originalRows.length !== writes.length || originalRows.some((row) => row.undone_at !== null)) fail(409, 'undo_conflict');
      if (!Array.isArray(originalOutcomes) || originalOutcomes.length !== writes.length
          || writes.some((write) => !originalOutcomes.some((outcome) => outcome.workflow_id === write.workflowId
            && outcome.version === write.expected))) fail(409, 'undo_conflict');
      if (new Set(originalRows.map((row) => row.target_id)).size !== writes.length
          || originalRows.some((row) => !writes.some((write) => write.workflowId === row.target_id))) fail(409, 'undo_conflict');
    }
    const locked = new Map();
    for (const write of [...writes].sort((a, b) => a.workflowId.localeCompare(b.workflowId))) {
      const row = await trx(TABLES.heads).where({ workflow_id: write.workflowId }).forUpdate().first();
      if (write.expected === null) {
        if (row) fail(409, 'head_conflict');
      } else if (!row || row.hashed_user_id !== body.owner_hash || row.hashed_team_id
          || Number(row.version) !== write.expected) fail(409, 'head_conflict');
      locked.set(write.workflowId, row);
    }
    const liveRefs = await verifyRefs(trx, body.owner_hash, writes, body.mutations, body.blobs);
    const obsoleteRefs = body.obsolete_refs || [];
    if (obsoleteRefs.some((ref) => !REF_RE.test(string(ref, 512)) || liveRefs.has(ref))) fail(400, 'invalid_obsolete_ref');
    for (const blob of body.blobs) await trx(TABLES.blobs).insert({
      id: randomUUID(), ref: blob.ref, hashed_user_id: body.owner_hash, kind: blob.kind,
      ciphertext: blob.ciphertext, checksum: blob.checksum, vault_key_ref: blob.vault_key_ref || null,
      key_version: blob.key_version || null, expires_at: blob.expires_at || null, created_at: blob.created_at,
    });
    for (const write of writes) {
      const current = locked.get(write.workflowId);
      // Runs update these fields without changing the authoring version. Keep
      // their latest values when a run and an edit overlap.
      if (current) {
        const currentRecord = jsonValue(current.record_json) || {};
        write.record.last_run_id = current.last_run_id || null;
        write.record.last_run_status = current.last_run_status || null;
        write.record.updated_at = Math.max(write.record.updated_at, Number(current.updated_at) || 0);
        if (currentRecord.encrypted_delivery_key_ref) write.record.encrypted_delivery_key_ref = currentRecord.encrypted_delivery_key_ref;
      }
      for (const version of write.record.versions) {
        const existing = await trx(TABLES.versions).where({ version_id: version.id }).first();
        if (existing) {
          if (existing.workflow_id !== write.workflowId || existing.hashed_user_id !== body.owner_hash
              || existing.encrypted_graph_secrets !== version.encrypted_graph_ref) fail(409, 'version_conflict');
          if (version.pruned_at !== null && version.pruned_at !== undefined && existing.pruned_at !== version.pruned_at) {
            await trx(TABLES.versions).where({ id: existing.id }).update({ pruned_at: version.pruned_at });
          }
        } else {
          await trx(TABLES.versions).insert({
            id: randomUUID(), version_id: version.id, workflow_id: write.workflowId,
            hashed_user_id: body.owner_hash, version_number: version.version_number || 1,
            graph_json: JSON.stringify({ encrypted_graph_ref: version.encrypted_graph_ref }),
            graph_hash: version.encrypted_graph_checksum, encrypted_graph_secrets: version.encrypted_graph_ref,
            created_by_client: version.created_by_client || write.record.source || 'system',
            restored_from_version_id: version.restored_from_version_id || null,
            pruned_at: version.pruned_at || null, created_at: version.created_at || write.record.created_at,
          });
        }
      }
      if (write.record.status === 'deleted') await clearWebsiteState(trx,write.workflowId,body.owner_hash);
      const head = headRow(write.record);
      if (current) {
        delete head.id;
        await trx(TABLES.heads).where({ id: current.id }).update(head);
      } else await trx(TABLES.heads).insert(head);
      const existingTrigger = await trx(TABLES.triggers).where({ workflow_id: write.workflowId }).forUpdate().first();
      if (existingTrigger && existingTrigger.hashed_user_id !== body.owner_hash) fail(409, 'trigger_conflict');
      const trigger = triggerRow(write.trigger);
      if (existingTrigger) {
        const sameDefinition = trigger && existingTrigger.version_id === trigger.version_id
          && existingTrigger.trigger_type === trigger.trigger_type
          && ['encrypted_schedule_config_ref', 'encrypted_event_predicate_ref',
            'encrypted_webhook_config_ref', 'encrypted_required_start_input_schema_ref']
            .every((field) => (existingTrigger[field] || null) === (trigger[field] || null));
        // A claimed occurrence already has a pinned run. Replacing its trigger
        // would make the worker's claim token or recurrence advance stale.
        if (existingTrigger.claim_status === 'claimed' && !sameDefinition) fail(409, 'trigger_claim_conflict');
        if (trigger) {
          for (const field of ['claim_status', 'claim_token_hash', 'claim_generation',
            'claimed_at', 'claim_expires_at']) trigger[field] = existingTrigger[field];
          if (sameDefinition && trigger.trigger_type === 'schedule') {
            const explicitlyEnabling = current && !current.enabled && write.record.enabled;
            if (trigger.enabled && !existingTrigger.enabled && !explicitlyEnabling) {
              trigger.enabled = false;
            }
            if (!trigger.enabled) trigger.next_run_at = null;
            else if (existingTrigger.enabled && !explicitlyEnabling) {
              trigger.next_run_at = existingTrigger.next_run_at;
            }
          }
        }
      }
      if (trigger && existingTrigger) await trx(TABLES.triggers).where({ id: existingTrigger.id }).update(trigger);
      else if (trigger) await trx(TABLES.triggers).insert({ id: randomUUID(), ...trigger });
      else if (existingTrigger) await trx(TABLES.triggers).where({ id: existingTrigger.id }).delete();
    }
    for (const row of body.mutations) await trx(TABLES.mutations).insert(row);
    if (obsoleteRefs.length) await trx(TABLES.blobs)
      .where({ hashed_user_id: body.owner_hash }).whereIn('ref', obsoleteRefs).delete();
    if (body.undo_of_operation_id) await trx(TABLES.mutations)
      .where({ operation_id: body.undo_of_operation_id, hashed_user_id: body.owner_hash })
      .update({ undone_at: Math.floor(Date.now() / 1000) });
    const operationRow = {
      id: randomUUID(), operation_id: body.operation_id, hashed_user_id: body.owner_hash,
      request_hash: body.request_hash, session_id: body.session_id || null,
      undo_of_operation_id: body.undo_of_operation_id || null,
      outcomes_json: JSON.stringify(body.outcomes), created_at: Math.floor(Date.now() / 1000),
    };
    await trx(TABLES.receipts).insert(operationRow);
    return receiptResult(operationRow);
  });
}

async function updateRunStatus(database, raw) {
  const body = object(raw);
  if (!OWNER_RE.test(string(body.owner_hash, 80))) fail(400, 'invalid_owner');
  const workflowId = string(body.workflow_id);
  const runId = string(body.run_id);
  const status = string(body.status, 64);
  const updatedAt = integer(body.updated_at);
  return database.transaction(async (trx) => {
    const current = await trx(TABLES.heads).where({ workflow_id: workflowId,
      hashed_user_id: body.owner_hash }).forUpdate().first();
    if (!current || current.status === 'deleted') fail(404, 'workflow_not_found');
    const record = jsonValue(current.record_json);
    record.last_run_id = runId;
    record.last_run_status = status;
    record.updated_at = Math.max(Number(record.updated_at) || 0, updatedAt);
    await trx(TABLES.heads).where({ id: current.id }).update({
      last_run_id: runId, last_run_status: status, updated_at: record.updated_at,
      record_json: JSON.stringify(record),
    });
    return { updated: true };
  });
}

const LEGACY_METADATA_FIELDS = [
  'binding_requirements', 'completed_binding_requirements', 'lifecycle',
  'auto_delete_at', 'kept_at', 'status', 'enabled', 'updated_at',
];
const HEAD_CONTENT_FIELDS = [
  'current_version_id', 'encrypted_graph_ref', 'encrypted_graph_checksum',
  'encrypted_title_ref', 'encrypted_title_checksum', 'encrypted_description_ref',
  'encrypted_description_checksum', 'encrypted_category_ref', 'encrypted_category_checksum',
  'encrypted_icon_ref', 'encrypted_icon_checksum', 'encrypted_slug', 'slug_lookup_hash',
];

async function clearWebsiteState(trx, workflowId, owner) {
  const rows = await trx('workflow_website_state').where({workflow_id:workflowId,hashed_user_id:owner});
  const refs = rows.map(row=>row.encrypted_ref);
  await trx('workflow_website_state').where({workflow_id:workflowId,hashed_user_id:owner}).delete();
  if (refs.length) await trx(TABLES.blobs).where({hashed_user_id:owner}).whereIn('ref',refs).delete();
  // Workflow deletion fences all its still-undelivered messages, including retries.
  const deliveries = await trx('workflow_chat_deliveries').where({workflow_id:workflowId,hashed_user_id:owner.replace(/^user_sha256:/,'')});
  for (const delivery of deliveries) if (!delivery.client_persisted_at && !['acknowledged','cancelled','expired'].includes(delivery.status)) {
    await trx('workflow_chat_deliveries').where({id:delivery.id}).update({status:'cancelled',encrypted_payload:'',claim_generation:Number(delivery.claim_generation || 0)+1,claim_token_hash:null,revision:Number(delivery.revision || 0)+1});
  }
}

async function updateLegacyHead(database, raw) {
  const body = object(raw);
  if (!OWNER_RE.test(string(body.owner_hash, 80))) fail(400, 'invalid_owner');
  const workflowId = string(body.workflow_id);
  const expected = integer(body.expected_version);
  if (expected < 1) fail(400, 'invalid_version');
  const candidate = object(body.record);
  if (candidate.id !== workflowId || candidate.owner_hash !== body.owner_hash) fail(400, 'invalid_owner');
  return database.transaction(async (trx) => {
    const head = await trx(TABLES.heads).where({ workflow_id: workflowId }).forUpdate().first();
    if (!head || head.hashed_user_id !== body.owner_hash
        || (head.hashed_team_id || null) !== (candidate.hashed_team_id || null)
        || Number(head.version) !== expected) fail(409, 'head_conflict');
    const current = jsonValue(head.record_json);
    if (!current || HEAD_CONTENT_FIELDS.some((field) => (current[field] || null) !== (candidate[field] || null))) {
      fail(409, 'head_content_conflict');
    }
    const updated = { ...current };
    for (const field of LEGACY_METADATA_FIELDS) {
      if (Object.hasOwn(candidate, field)) updated[field] = candidate[field];
    }
    updated.version = expected + 1;
    updated.updated_at = Math.max(Number(updated.updated_at) || 0, Number(head.updated_at) || 0);
    await trx(TABLES.heads).where({ id: head.id }).update({
      status: updated.status, enabled: Boolean(updated.enabled), lifecycle: updated.lifecycle || 'persisted',
      auto_delete_at: updated.auto_delete_at || null, kept_at: updated.kept_at || null,
      deleted_at: updated.status === 'deleted' ? updated.updated_at : null,
      version: updated.version, updated_at: updated.updated_at,
      record_json: JSON.stringify(updated),
    });
    if (updated.status === 'deleted') await clearWebsiteState(trx,workflowId,body.owner_hash);
    return { record: updated };
  });
}

async function expireTemporary(database, raw, chatOwned = false) {
  const body = object(raw);
  if (!OWNER_RE.test(string(body.owner_hash, 80))) fail(400, 'invalid_owner');
  const workflowId = string(body.workflow_id);
  const expected = integer(body.expected_version);
  const cutoff = integer(body.cutoff);
  const sourceChatId = chatOwned ? string(body.source_chat_id) : null;
  return database.transaction(async (trx) => {
    const head = await trx(TABLES.heads).where({ workflow_id: workflowId }).forUpdate().first();
    if (!head || head.hashed_user_id !== body.owner_hash
        || (head.hashed_team_id || null) !== (body.hashed_team_id || null)
        || Number(head.version) !== expected) fail(409, 'head_conflict');
    const record = jsonValue(head.record_json);
    if (chatOwned) {
      if (!record || record.lifecycle !== 'chat_embed' || record.source_chat_id !== sourceChatId
          || record.auto_delete_at !== null || record.enabled || head.hashed_team_id) fail(409, 'chat_purge_conflict');
    } else if (!record || record.lifecycle !== 'temporary' || !Number.isSafeInteger(record.auto_delete_at)
        || record.auto_delete_at > cutoff) fail(409, 'expiration_conflict');
    const triggers = await trx(TABLES.triggers).where({ workflow_id: workflowId }).forUpdate();
    const runs = await trx('workflow_runs').where({ workflow_id: workflowId }).forUpdate();
    const mutations = await trx(TABLES.mutations).where({ target_type: 'workflow',
      target_id: workflowId, hashed_user_id: body.owner_hash }).forUpdate();
    if (triggers.some((row) => row.hashed_user_id !== body.owner_hash)
        || runs.some((row) => row.hashed_user_id !== body.owner_hash)) fail(409, 'owner_conflict');
    const refs = new Set();
    for (const field of ['encrypted_title_ref', 'encrypted_description_ref', 'encrypted_category_ref',
      'encrypted_icon_ref', 'encrypted_graph_ref']) if (record[field]) refs.add(record[field]);
    if (chatOwned && head.encrypted_delivery_key_ref) refs.add(head.encrypted_delivery_key_ref);
    for (const version of record.versions || []) if (version.encrypted_graph_ref) refs.add(version.encrypted_graph_ref);
    for (const trigger of triggers) for (const field of ['encrypted_schedule_config_ref',
      'encrypted_event_predicate_ref', 'encrypted_webhook_config_ref', 'encrypted_required_start_input_schema_ref']) {
      if (trigger[field]) refs.add(trigger[field]);
    }
    for (const run of runs) {
      const runRecord = jsonValue(run.record_json) || {};
      if (runRecord.encrypted_content_ref) refs.add(runRecord.encrypted_content_ref);
      if (chatOwned) for (const field of ['encrypted_input', 'encrypted_invocation_ref', 'encrypted_output_summary']) {
        if (run[field]?.startsWith?.('vault://workflows/')) refs.add(run[field]);
      }
    }
    for (const mutation of mutations) {
      if (mutation.encrypted_before_ref) refs.add(mutation.encrypted_before_ref);
      if (mutation.encrypted_after_ref) refs.add(mutation.encrypted_after_ref);
    }
    for (const operationId of new Set(mutations.map((row) => row.operation_id).filter(Boolean))) {
      const receipt = await trx(TABLES.receipts).where({ operation_id: operationId,
        hashed_user_id: body.owner_hash }).forUpdate().first();
      if (!receipt) continue;
      const outcomes = jsonValue(receipt.outcomes_json);
      if (!Array.isArray(outcomes)) fail(409, 'receipt_conflict');
      for (const outcome of outcomes) if (outcome.workflow_id === workflowId) {
        outcome.after_ref = null;
        outcome.expired = true;
      }
      await trx(TABLES.receipts).where({ id: receipt.id }).update({ outcomes_json: JSON.stringify(outcomes) });
    }
    await trx(TABLES.mutations).where({ target_type: 'workflow', target_id: workflowId,
      hashed_user_id: body.owner_hash }).delete();
    await trx(TABLES.triggers).where({ workflow_id: workflowId }).delete();
    await clearWebsiteState(trx,workflowId,body.owner_hash);
    if (chatOwned) {
      await trx('workflow_chat_deliveries').where({workflow_id:workflowId,
        hashed_user_id:body.owner_hash.replace(/^user_sha256:/,'')}).delete();
      await trx('workflow_delivery_history').where({workflow_id:workflowId,hashed_user_id:body.owner_hash}).delete();
    }
    await trx('workflow_runs').where({ workflow_id: workflowId }).delete();
    await trx(TABLES.versions).where({ workflow_id: workflowId }).delete();
    await trx(TABLES.heads).where({ id: head.id }).delete();
    if (refs.size) await trx(TABLES.blobs).where({ hashed_user_id: body.owner_hash }).whereIn('ref', [...refs]).delete();
    return chatOwned ? { purged: true } : { expired: true };
  });
}

async function pruneMutationSnapshots(database, raw) {
  const body = object(raw);
  const cutoff = integer(body.cutoff);
  const owner = body.owner_hash;
  if (owner !== null && owner !== undefined && !OWNER_RE.test(string(owner, 80))) fail(400, 'invalid_owner');
  return database.transaction(async (trx) => {
    let query = trx(TABLES.mutations).where('created_at', '<=', cutoff).whereNotNull('operation_id');
    if (owner) query = query.where({ hashed_user_id: owner });
    const candidates = await query.orderBy('created_at', 'asc').limit(100);
    let pruned = 0;
    for (const operationId of new Set(candidates.map((row) => row.operation_id))) {
      const candidate = candidates.find((row) => row.operation_id === operationId);
      const ownerHash = candidate.hashed_user_id;
      const receipt = await trx(TABLES.receipts).where({ operation_id: operationId,
        hashed_user_id: ownerHash }).forUpdate().first();
      const rows = await trx(TABLES.mutations).where({ operation_id: operationId,
        hashed_user_id: ownerHash }).forUpdate();
      if (!rows.length || rows.some((row) => Number(row.created_at) > cutoff)) continue;
      const refs = new Set();
      for (const row of rows) {
        if (row.encrypted_before_ref) refs.add(row.encrypted_before_ref);
        if (row.encrypted_after_ref) refs.add(row.encrypted_after_ref);
      }
      if (receipt) {
        const outcomes = jsonValue(receipt.outcomes_json);
        if (!Array.isArray(outcomes)) fail(409, 'receipt_conflict');
        for (const outcome of outcomes) {
          outcome.after_ref = null;
          outcome.expired = true;
        }
        await trx(TABLES.receipts).where({ id: receipt.id }).update({ outcomes_json: JSON.stringify(outcomes) });
      }
      await trx(TABLES.mutations).where({ operation_id: operationId,
        hashed_user_id: ownerHash }).delete();
      if (refs.size) await trx(TABLES.blobs).where({ hashed_user_id: ownerHash }).whereIn('ref', [...refs]).delete();
      pruned += rows.length;
    }
    return { pruned };
  });
}

export async function executeAuthoring(database, path, body) {
  if (path === '/health') return { status: 'ok', protocol_version: 1 };
  if (path === '/receipt') return receipt(database, body);
  if (path === '/operation') return operation(database, body);
  if (path === '/run-status') return updateRunStatus(database, body);
  if (path === '/legacy-head') return updateLegacyHead(database, body);
  if (path === '/expire-temporary') return expireTemporary(database, body);
  if (path === '/purge-chat-embed') return expireTemporary(database, body, true);
  if (path === '/prune-mutations') return pruneMutationSnapshots(database, body);
  if (path === '/') return commit(database, body);
  fail(404, 'unknown_operation');
}
