// contract-test-file: tooling
import assert from 'node:assert/strict';
import test from 'node:test';
import { createHash } from 'node:crypto';
import { mkdtempSync, readFileSync, rmSync, statSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { spawnSync } from 'node:child_process';
import {
  MAX_BYTES, MAX_RECORDS, createBoundedRecordWriter,
  installCliWsMetadataProbe, metadataForFrame
} from './cli-ws-metadata-probe.mjs';

const digest = value => createHash('sha256').update(value).digest('hex').slice(0, 16);
const frame = payload => Buffer.from(JSON.stringify({ type: 'ai_message_update', payload }));

test('allowlisted metadata hashes identity and never copies sensitive values or unknown fields', () => {
  const canaries = ['PRIVATE-CONTENT', 'PRIVATE-TOON', 'PRIVATE-URL', 'PRIVATE-COOKIE',
    'PRIVATE-TOKEN', 'PRIVATE-AES', 'PRIVATE-SOURCE', 'PRIVATE-UNKNOWN-STATUS', 'PRIVATE-KEY-NAME'];
  const raw = frame({ chat_id: 'owner-chat', user_message_id: 'owner-user-message',
    turn_id: 'owner-turn', message_id: 'assistant-message', task_id: 'task', recovery_job_id: 'job',
    is_final_chunk: true, recovery_provisional: false, recovery_protocol_version: 1,
    full_content_so_far: canaries[0], content: canaries[1], url: canaries[2], cookie: canaries[3],
    token: canaries[4], aes_key: canaries[5], sources: [canaries[6]], status: canaries[7],
    [canaries[8]]: 'do not enumerate keys' });
  const metadata = metadataForFrame(raw);
  assert.deepEqual(metadata, { probe_protocol: 1, kind: 'frame', frame_type: 'ai_message_update', payload: {
    chat_h: digest('owner-chat'), user_message_h: digest('owner-user-message'),
    turn_h: digest('owner-turn'), message_h: digest('assistant-message'), recovery_job_h: digest('job'),
    task_h: digest('task'), final: true, provisional: false, has_job: true, has_turn: true,
    protocol_present: true, protocol_v1: true
  } });
  const serialized = JSON.stringify(metadata);
  for (const canary of [...canaries, 'owner-chat', 'owner-user-message', 'owner-turn', 'assistant-message']) {
    assert.equal(serialized.includes(canary), false, canary);
  }
  assert.equal(metadataForFrame(JSON.stringify({ type: 'PRIVATE-UNKNOWN-FRAME', payload: {} })), undefined);
  assert.equal(metadataForFrame('not json'), undefined);
  assert.equal(metadataForFrame(null), undefined);
  assert.equal(metadataForFrame(' '.repeat(2 * 1024 * 1024 + 1)), undefined);
});

test('nested embed/message metadata and bounded recovery items preserve only fixed enums and hashes', () => {
  const nested = metadataForFrame(JSON.stringify({ type: 'send_embed_data', payload: { payload: {
    embed_id: 'embed', parent_embed_id: 'parent', status: 'finished', content: 'PRIVATE-EMBED-CONTENT',
    type: 'PRIVATE-UNRECOGNIZED-EMBED-TYPE', source_url: 'PRIVATE-SOURCE-URL'
  } } }));
  assert.equal(nested.embed.embed_h, digest('embed'));
  assert.equal(nested.embed.parent_h, digest('parent'));
  assert.equal(nested.embed.status, 'finished');
  assert.equal(JSON.stringify(nested).includes('PRIVATE-'), false);
  const message = metadataForFrame(JSON.stringify({ type: 'chat_message_added', payload: { message: {
    message_id: 'message', chat_id: 'chat', content: 'PRIVATE-MESSAGE'
  } } }));
  assert.equal(message.message.message_h, digest('message'));
  const jobs = Array.from({ length: 30 }, (_, i) => ({ job_id: `job-${i}`, state: 'CLAIMED', sealed_payload: 'PRIVATE-SEALED' }));
  const outputs = Array.from({ length: 30 }, (_, i) => ({ record_id: `record-${i}`, subject_id: `subject-${i}`,
    output_kind: 'embed', state: 'ACKNOWLEDGED', unknown: 'PRIVATE-UNKNOWN' }));
  const recovery = metadataForFrame(JSON.stringify({ type: 'recovery_outputs_available', payload: { jobs, outputs } }));
  assert.equal(recovery.jobs.length, 30);
  assert.equal(recovery.outputs.length, 20);
  assert.equal(recovery.items_truncated, true);
  assert.equal(recovery.outputs[0].output_kind, 'embed');
  assert.equal(recovery.outputs[0].state, 'ACKNOWLEDGED');
  assert.equal(JSON.stringify(recovery).includes('PRIVATE-'), false);
});

test('observation precedes dispatch and preserves original receiver, argument identities and return value exactly once', () => {
  const lines = [];
  const calls = [];
  const result = Symbol('original result');
  const prototype = { emit(...args) { calls.push({ receiver: this, args, observed: lines.length }); return result; } };
  const original = prototype.emit;
  const restore = installCliWsMetadataProbe({ emitterPrototype: prototype, appendLine: line => lines.push(line) });
  const ws = Object.assign(Object.create(prototype), { _receiver: {}, _socket: {}, send() {} });
  const payload = frame({ message_id: 'message', is_final_chunk: true });
  const binary = { unchanged: true };
  assert.equal(ws.emit('message', payload, binary), result);
  assert.equal(calls.length, 1);
  assert.equal(calls[0].receiver, ws);
  assert.equal(calls[0].args[0], 'message');
  assert.equal(calls[0].args[1], payload);
  assert.equal(calls[0].args[2], binary);
  assert.equal(calls[0].observed, 2, 'installed and frame records precede the original dispatch');
  const ordinary = Object.create(prototype);
  assert.equal(ordinary.emit('message', payload), result);
  assert.equal(calls.length, 2);
  assert.equal(lines.length, 2, 'other EventEmitters are not observed');
  const otherWs = Object.assign(Object.create(prototype), { _receiver: {}, _socket: {}, send() {} });
  assert.equal(ws.emit('message', payload, binary), result);
  assert.equal(otherWs.emit('message', payload, binary), result);
  const observed = lines.map(line => JSON.parse(line)).filter(record => record.kind === 'frame');
  assert.deepEqual(observed.map(record => record.socket_ordinal), [1, 1, 2]);
  assert.ok(observed.every(record => Number.isInteger(record.elapsed_ms) && record.elapsed_ms >= 0));
  assert.ok(observed.every((record, index) => index === 0 || record.elapsed_ms >= observed[index - 1].elapsed_ms));
  assert.equal(calls.length, 4);
  assert.equal(JSON.parse(payload.toString()).socket_ordinal, undefined, 'the original frame is not mutated');
  restore();
  assert.equal(prototype.emit, original);
});

test('observer failures never suppress dispatch or swallow/replace the original exception', () => {
  const originalError = new Error('original listener failure');
  let calls = 0;
  const prototype = { emit() { calls += 1; throw originalError; } };
  const restore = installCliWsMetadataProbe({ emitterPrototype: prototype,
    appendLine() { throw new Error('diagnostic disk failure'); } });
  const ws = Object.assign(Object.create(prototype), { _receiver: {}, _socket: {}, send() {} });
  assert.throws(() => ws.emit('message', frame({ is_final_chunk: true })), error => error === originalError);
  assert.equal(calls, 1);
  Object.defineProperty(ws, '_receiver', { get() { throw new Error('observer getter failure'); } });
  assert.throws(() => ws.emit('message', frame({})), error => error === originalError);
  assert.equal(calls, 2);
  restore();
});

test('a failed diagnostic write disables later writes while the original emitter still returns normally', () => {
  let writes = 0;
  let calls = 0;
  const prototype = { emit() { calls += 1; return false; } };
  const restore = installCliWsMetadataProbe({ emitterPrototype: prototype,
    appendLine() { writes += 1; throw new Error('diagnostic sink unavailable'); } });
  const ws = Object.assign(Object.create(prototype), { _receiver: {}, _socket: {}, send() {} });
  for (let i = 0; i < 3; i += 1) assert.equal(ws.emit('message', frame({})), false);
  assert.equal(writes, 1);
  assert.equal(calls, 3);
  restore();
});

test('both hard output limits reserve an explicit truncation marker and stop further writes', () => {
  const small = [];
  const writer = createBoundedRecordWriter(line => small.push(line));
  for (let i = 0; i < MAX_RECORDS + 10; i += 1) writer({ probe_protocol: 1, kind: 'frame' });
  assert.equal(small.length, MAX_RECORDS);
  assert.equal(JSON.parse(small.at(-1)).kind, 'truncated');
  assert.ok(Buffer.byteLength(small.join('')) <= MAX_BYTES);

  const large = [];
  const largeWriter = createBoundedRecordWriter(line => large.push(line));
  const metadata = metadataForFrame(JSON.stringify({ type: 'recovery_outputs_available', payload: {
    outputs: Array.from({ length: 50 }, (_, i) => ({ record_id: `record-${i}`, subject_id: `subject-${i}`,
      chat_id: 'chat', root_chat_id: 'root', target_chat_id: 'target', turn_id: 'turn',
      message_id: 'message', task_id: 'task', embed_id: 'embed', parent_embed_id: 'parent',
      job_id: 'job', output_kind: 'embed', state: 'ACKNOWLEDGED' }))
  } }));
  for (let i = 0; i < 100; i += 1) largeWriter(metadata);
  assert.ok(large.length < MAX_RECORDS, 'the byte bound triggers independently');
  assert.ok(Buffer.byteLength(large.join('')) <= MAX_BYTES);
  assert.equal(JSON.parse(large.at(-1)).kind, 'truncated');
});

test('actual Node preload writes private metadata while preserving existing Node options and stdout', () => {
  const home = mkdtempSync(join(tmpdir(), 'cli-ws-probe-unit-'));
  const traceFile = join(home, 'trace.jsonl');
  try {
    const preload = new URL('./cli-ws-metadata-probe.mjs', import.meta.url).href;
    const program = `import { EventEmitter } from 'node:events';
      const socket = Object.assign(new EventEmitter(), { _receiver: {}, _socket: {}, send() {} });
      socket.on('message', data => { if (!data.includes('PRIVATE-CANARY')) throw new Error('dispatch changed'); });
      socket.emit('message', JSON.stringify({type:'ai_message_update',payload:{chat_id:'chat',full_content_so_far:'PRIVATE-CANARY',is_final_chunk:true}}));
      console.log('original stdout');`;
    const result = spawnSync(process.execPath, ['--input-type=module', '-e', program], {
      encoding: 'utf8', env: { ...process.env,
        NODE_OPTIONS: `${process.env.NODE_OPTIONS || ''} --max-old-space-size=128 --import=${preload}`.trim(),
        OPENMATES_E2E_WS_TRACE_FILE: traceFile, OPENMATES_E2E_WS_TRACE_PROTOCOL: '1'
      }
    });
    assert.equal(result.status, 0, result.stderr);
    assert.equal(result.stdout, 'original stdout\n');
    const trace = readFileSync(traceFile, 'utf8');
    assert.equal(trace.includes('PRIVATE-CANARY'), false);
    assert.deepEqual(trace.trim().split('\n').map(line => JSON.parse(line).kind), ['installed', 'frame']);
    assert.equal(statSync(traceFile).mode & 0o777, 0o600);
  } finally { rmSync(home, { recursive: true, force: true }); }
});
