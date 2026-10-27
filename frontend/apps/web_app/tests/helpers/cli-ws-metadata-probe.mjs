/** Test-only Node preload: bounded metadata observed before real WS dispatch.
 * No SDK implementation, payload contents, credentials or raw identities leave
 * the CLI process. Probe failures never replace or suppress the original emit.
 */
import { EventEmitter } from 'node:events';
import { createHash } from 'node:crypto';
import { appendFileSync } from 'node:fs';
import { performance } from 'node:perf_hooks';

export const PROBE_PROTOCOL = 1;
export const MAX_RECORDS = 1024;
export const MAX_BYTES = 256 * 1024;
const MAX_INPUT_BYTES = 2 * 1024 * 1024;
const MAX_ITEMS = 50;
const FRAME_TYPES = new Set([
  'ai_task_initiated', 'ai_typing_started', 'ai_typing_ended',
  'ai_message_chunk', 'ai_message_update', 'ai_background_response_completed',
  'ai_task_error', 'pending_ai_response', 'chat_message_added',
  'post_processing_completed', 'post_processing_metadata', 'send_embed_data',
  'recovery_jobs_available', 'recovery_job_claimed', 'recovery_job_persisted',
  'recovery_outputs_available', 'recovery_outputs_discovery_complete',
  'recovery_output_ready', 'recovery_output_status_ready',
  'recovery_output_persisted', 'recovery_output_summary_persisted',
  'recovery_output_embed_acknowledged', 'recovery_output_checkpoint_acknowledged',
  'store_embed_confirmed', 'store_embed_diff_confirmed', 'error'
]);
const STATUSES = new Set([
  'processing', 'finished', 'error', 'queued', 'running', 'completed', 'disabled',
  'pending', 'failed', 'cancelled', 'canceled', 'waiting_for_user', 'ready'
]);
const STATES = new Set([
  'PENDING', 'AVAILABLE', 'READY', 'CLAIMED', 'LEASED', 'SEALED', 'ACKNOWLEDGED',
  'TERMINAL', 'EXPIRED', 'FAILED'
]);
const OUTPUT_KINDS = new Set(['message', 'embed', 'diff', 'summary', 'checkpoint']);
// Output names and input reads are fixed; never enumerate/copy payload keys.
const IDENTITIES = [
  ['chat_h', 'chat_id'], ['chat_camel_h', 'chatId'],
  ['root_chat_h', 'root_chat_id'], ['target_chat_h', 'target_chat_id'],
  ['user_message_h', 'user_message_id'], ['user_message_camel_h', 'userMessageId'],
  ['turn_h', 'turn_id'], ['recovery_turn_h', 'recovery_turn_id'],
  ['message_h', 'message_id'], ['assistant_message_h', 'assistant_message_id'],
  ['job_h', 'job_id'], ['recovery_job_h', 'recovery_job_id'],
  ['embed_h', 'embed_id'], ['parent_h', 'parent_embed_id'], ['task_h', 'task_id'],
  ['record_h', 'record_id'], ['subject_h', 'subject_id']
];
const object = value => value !== null && typeof value === 'object' && !Array.isArray(value);
const identity = value => typeof value === 'string' && value.length > 0 && value.length <= 512;
const hash = value => createHash('sha256').update(value).digest('hex').slice(0, 16);

function fields(value) {
  const result = {};
  for (const [output, input] of IDENTITIES) {
    if (identity(value[input])) result[output] = hash(value[input]);
  }
  if (typeof value.is_final_chunk === 'boolean') result.final = value.is_final_chunk;
  if (typeof value.recovery_provisional === 'boolean') result.provisional = value.recovery_provisional;
  result.has_job = identity(value.job_id) || identity(value.recovery_job_id);
  result.has_turn = identity(value.turn_id) || identity(value.recovery_turn_id);
  result.protocol_present = value.protocol_version !== undefined || value.recovery_protocol_version !== undefined;
  result.protocol_v1 = value.protocol_version === 1 || value.recovery_protocol_version === 1;
  if (STATUSES.has(value.status)) result.status = value.status;
  if (STATES.has(value.state)) result.state = value.state;
  if (OUTPUT_KINDS.has(value.output_kind)) result.output_kind = value.output_kind;
  return result;
}

/** Return only an allowlisted metadata record, or nothing for other traffic. */
export function metadataForFrame(raw) {
  let bytes;
  if (typeof raw === 'string') {
    if (Buffer.byteLength(raw) > MAX_INPUT_BYTES) return undefined;
    bytes = raw;
  } else if (Buffer.isBuffer(raw)) {
    if (raw.length > MAX_INPUT_BYTES) return undefined;
    bytes = raw.toString('utf8');
  } else if (raw instanceof ArrayBuffer) {
    if (raw.byteLength > MAX_INPUT_BYTES) return undefined;
    bytes = Buffer.from(raw).toString('utf8');
  } else {
    return undefined;
  }
  let frame;
  try { frame = JSON.parse(bytes); } catch { return undefined; }
  if (!object(frame) || !FRAME_TYPES.has(frame.type)) return undefined;
  const payload = object(frame.payload) ? frame.payload : frame;
  const record = { probe_protocol: PROBE_PROTOCOL, kind: 'frame', frame_type: frame.type, payload: fields(payload) };
  if (frame.type === 'send_embed_data' && object(payload.payload)) record.embed = fields(payload.payload);
  if (frame.type === 'chat_message_added' && object(payload.message)) record.message = fields(payload.message);
  let remaining = MAX_ITEMS;
  for (const key of ['jobs', 'outputs']) {
    if (!Array.isArray(payload[key])) continue;
    const selected = payload[key].slice(0, remaining);
    record[key] = selected.filter(object).map(fields);
    remaining -= selected.length;
    if (payload[key].length > selected.length) record.items_truncated = true;
  }
  return record;
}

/** Reserve space for an explicit terminal marker within both hard bounds. */
export function createBoundedRecordWriter(appendLine) {
  let records = 0;
  let bytes = 0;
  let stopped = false;
  const marker = JSON.stringify({ probe_protocol: PROBE_PROTOCOL, kind: 'truncated' }) + '\n';
  const markerBytes = Buffer.byteLength(marker);
  return record => {
    if (stopped) return;
    const line = JSON.stringify(record) + '\n';
    const size = Buffer.byteLength(line);
    if (records >= MAX_RECORDS - 1 || bytes + size + markerBytes > MAX_BYTES) {
      stopped = true;
      appendLine(marker);
      return;
    }
    try { appendLine(line); }
    catch (error) { stopped = true; throw error; }
    records += 1;
    bytes += size;
  };
}

/** Injectable prototype/sink make dispatch transparency executable in unit tests. */
export function installCliWsMetadataProbe({ emitterPrototype = EventEmitter.prototype, appendLine }) {
  const original = emitterPrototype.emit;
  const write = createBoundedRecordWriter(appendLine);
  const startedAt = performance.now();
  const socketOrdinals = new WeakMap();
  let nextSocketOrdinal = 0;
  try { write({ probe_protocol: PROBE_PROTOCOL, kind: 'installed' }); } catch { /* Observability only. */ }
  function observedEmit(event, ...args) {
    try {
      // Identify the actual ws EventEmitter, regardless of package bundling.
      if (event === 'message' && this?._receiver && this?._socket && typeof this.send === 'function') {
        const record = metadataForFrame(args[0]);
        if (record) {
          if (!socketOrdinals.has(this)) socketOrdinals.set(this, ++nextSocketOrdinal);
          record.socket_ordinal = socketOrdinals.get(this);
          record.elapsed_ms = Math.max(0, Math.round(performance.now() - startedAt));
          write(record);
        }
      }
    } catch { /* Parsing, getters and disk failures must not affect dispatch. */ }
    // Keep the original outside the observer's catch: its exceptions propagate.
    return Reflect.apply(original, this, [event, ...args]);
  }
  emitterPrototype.emit = observedEmit;
  return () => { if (emitterPrototype.emit === observedEmit) emitterPrototype.emit = original; };
}

// Enabled only for the one process explicitly given this spec-owned protocol.
if (process.env.OPENMATES_E2E_WS_TRACE_FILE && process.env.OPENMATES_E2E_WS_TRACE_PROTOCOL === '1') {
  try {
    const traceFile = process.env.OPENMATES_E2E_WS_TRACE_FILE;
    installCliWsMetadataProbe({ appendLine: line => appendFileSync(traceFile, line, { mode: 0o600 }) });
  } catch { /* A preload probe never prevents the real CLI from starting. */ }
}
