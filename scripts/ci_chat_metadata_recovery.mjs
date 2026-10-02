/** Real isolated WS/CMS metadata recovery, synthetic sealed worker output, no AI. */
import assert from 'node:assert/strict';
import { createHash, randomBytes, randomUUID, createPrivateKey, createPublicKey, diffieHellman,
  hkdfSync, createCipheriv, createDecipheriv } from 'node:crypto';
import { readFileSync } from 'node:fs';
import { platform, release } from 'node:os';
import path from 'node:path';
import { createRequire } from 'node:module';
import { pathToFileURL } from 'node:url';
const source = path.resolve(process.argv[2]);
if (process.env.GITHUB_ACTIONS !== 'true' || process.env.RUNNER_ENVIRONMENT !== 'github-hosted'
  || process.env.CI_TEST_MODE !== 'e2e') throw new Error('Metadata endpoint proof requires isolated GitHub E2E');
const profile = JSON.parse(readFileSync(path.join(source, 'test-results/ci-private/compose.json'), 'utf8'));
const runtime = profile.services.api.environment;
const require = createRequire(path.join(source, 'frontend/packages/openmates-cli/package.json'));
const WebSocket = require('ws');
const { OpenMatesClient } = await import(pathToFileURL(path.join(source, 'frontend/packages/openmates-cli/dist/index.js')));
const { encryptBytesWithAesGcm, encryptWithAesGcmCombined } = await import(pathToFileURL(path.join(source, 'frontend/packages/openmates-cli/src/crypto.ts')));
const client = new OpenMatesClient({ apiUrl: 'http://localhost:8000' });
const user = await client.whoAmI();
const session = client.getSession();
const ownerHash = createHash('sha256').update(user.id).digest('hex');
const privateKey = (bytes) => createPrivateKey({ key: Buffer.concat([Buffer.from('302e020100300506032b656e04220420', 'hex'), bytes]), format: 'der', type: 'pkcs8' });
const rawPublic = (key) => createPublicKey(key).export({ format: 'der', type: 'spki' }).subarray(-32);
const hash = value => createHash('sha256').update(value).digest();
const prefix = value => { const bytes = Buffer.from(value), count = Buffer.alloc(4); count.writeUInt32BE(bytes.length); return Buffer.concat([count, bytes]); };
const aadFor = ({ owner_id, chat_id, task_id, job_id, stage }) => Buffer.concat([
  Buffer.from('OMCM1'), ...[owner_id, chat_id, task_id, job_id, stage].map(prefix), Buffer.from([0, 0, 0, 1]),
]);
async function http(url, { method = 'GET', body, token, internal } = {}) {
  const response = await fetch(url, { method, headers: { 'Content-Type': 'application/json',
    ...(token ? { Authorization: `Bearer ${token}` } : {}), ...(internal ? { 'X-Internal-Service-Token': internal } : {}) },
    ...(body === undefined ? {} : { body: JSON.stringify(body) }) });
  assert.ok(response.ok, `Fixture/protocol HTTP ${response.status}`);
  return response.status === 204 ? null : (await response.json()).data;
}
const login = await http('http://localhost:8055/auth/login', { method: 'POST', body: {
  email: runtime.DATABASE_ADMIN_EMAIL, password: runtime.DATABASE_ADMIN_PASSWORD, mode: 'json',
} });
const adminToken = login.access_token;
const admin = (collection, options = {}) => http(`http://localhost:8055/items/${collection}`, { ...options, token: adminToken });
const operation = (operation, data) => http('http://localhost:8055/chat-recovery-transaction', {
  method: 'POST', internal: runtime.INTERNAL_API_SHARED_TOKEN, body: { operation, data },
});
const chatId = randomUUID(), taskId = randomUUID(), preflightId = randomUUID(), turnId = randomUUID();
const userMessageId = randomUUID(), assistantMessageId = randomUUID();
const chatKey = randomBytes(32), keyInfo = Buffer.concat([prefix(chatId), Buffer.from([0, 0, 0, 1])]);
const recoveryPrivate = privateKey(Buffer.from(hkdfSync('sha256', chatKey, hash('openmates:chat-recovery:v1'), keyInfo, 32)));
const wrapped = await encryptBytesWithAesGcm(chatKey, Buffer.from(session.masterKeyExportedB64, 'base64'));
const now = Math.floor(Date.now() / 1000);
const sockets = [];
let ownerSocket;
async function connect(capable) {
  const query = new URLSearchParams({ sessionId: randomUUID(), token: session.wsToken || '',
    ...(capable ? { client_capabilities: 'chat_metadata_recovery' } : {}) });
  const ws = new WebSocket(`ws://localhost:8000/v1/ws?${query}`, { headers: {
    Origin: 'http://localhost:5173', 'User-Agent': `OpenMates CLI/0.1 (${platform()} ${release()})`,
    Cookie: Object.entries(session.cookies).map(([key, value]) => `${key}=${value}`).join('; '),
  } });
  const frames = [], waiters = [];
  ws.on('message', bytes => {
    let message; try { message = JSON.parse(bytes.toString()); } catch { return; }
    if (message.type === 'ping') ws.send(JSON.stringify({ type: 'pong', payload: {} }));
    frames.push(message);
    for (const waiter of [...waiters]) if (waiter.matches(message)) {
      clearTimeout(waiter.timeout); waiters.splice(waiters.indexOf(waiter), 1); waiter.resolve(message);
    }
  });
  await new Promise((resolve, reject) => { ws.once('open', resolve); ws.once('error', reject); });
  const wait = matches => {
    const existing = frames.find(matches); if (existing) return Promise.resolve(existing);
    return new Promise((resolve, reject) => {
      const waiter = { matches, resolve, timeout: setTimeout(() => {
        waiters.splice(waiters.indexOf(waiter), 1); reject(new Error('Metadata protocol response timeout'));
      }, 30000) }; waiters.push(waiter);
    });
  };
  const exchange = async (type, payload, responseType) => {
    const request_id = randomUUID();
    const response = wait(message => message.payload?.request_id === request_id
      && [responseType, 'error'].includes(message.type));
    ws.send(JSON.stringify({ type, payload: { ...payload, request_id } }));
    return response;
  };
  const socket = { ws, wait, exchange, frames }; sockets.push(socket); return socket;
}
function seal(stage, metadata) {
  const jobId = randomUUID(), identity = { owner_id: user.id, chat_id: chatId, task_id: taskId, job_id: jobId, stage, key_version: 1 };
  const aad = aadFor(identity), ephemeral = privateKey(randomBytes(32));
  const secret = diffieHellman({ privateKey: ephemeral, publicKey: createPublicKey(recoveryPrivate) });
  const envelopeKey = Buffer.from(hkdfSync('sha256', secret, hash('openmates:chat-recovery-envelope:v1'), hash(aad), 32));
  const nonce = randomBytes(12), cipher = createCipheriv('aes-256-gcm', envelopeKey, nonce);
  cipher.setAAD(aad);
  const ciphertext = Buffer.concat([cipher.update(JSON.stringify({ ...identity, metadata })), cipher.final(), cipher.getAuthTag()]);
  return { job_id: jobId, protocol_version: 1, hashed_user_id: ownerHash, chat_id: chatId,
    task_id: taskId, inference_task_id: taskId, preflight_id: preflightId, chat_key_version: 1,
    stage, source_metadata_v: 0, generated_at: new Date().toISOString(), encrypted_fields: Object.keys(metadata).map(field => ({
      title: 'encrypted_title', summary: 'encrypted_chat_summary', category: 'encrypted_category', icon: 'encrypted_icon',
    })[field]).sort(), sealed_payload: JSON.stringify({ v: 1, epk: rawPublic(ephemeral).toString('base64url'),
      nonce: nonce.toString('base64url'), ciphertext: ciphertext.toString('base64url') }) };
}
function open(claim) {
  const envelope = JSON.parse(claim.sealed_payload);
  const ephemeral = createPublicKey({ key: Buffer.concat([Buffer.from('302a300506032b656e032100', 'hex'), Buffer.from(envelope.epk, 'base64url')]), format: 'der', type: 'spki' });
  const secret = diffieHellman({ privateKey: recoveryPrivate, publicKey: ephemeral });
  const aad = aadFor({ owner_id: user.id, chat_id: claim.chat_id, task_id: claim.task_id, job_id: claim.job_id, stage: claim.stage });
  const key = Buffer.from(hkdfSync('sha256', secret, hash('openmates:chat-recovery-envelope:v1'), hash(aad), 32));
  const ciphertext = Buffer.from(envelope.ciphertext, 'base64url'), decipher = createDecipheriv('aes-256-gcm', key, Buffer.from(envelope.nonce, 'base64url'));
  decipher.setAAD(aad); decipher.setAuthTag(ciphertext.subarray(-16));
  return JSON.parse(Buffer.concat([decipher.update(ciphertext.subarray(0, -16)), decipher.final()])).metadata;
}
async function recover(job, editTitle) {
  const claim = await ownerSocket.exchange('metadata_job_claim', { protocol_version: 1, job_id: job.job_id }, 'metadata_job_claimed');
  assert.equal(claim.type, 'metadata_job_claimed');
  const metadata = open(claim.payload), encrypted = {};
  for (const [field, value] of Object.entries(metadata)) encrypted[({ title: 'encrypted_title', summary: 'encrypted_chat_summary', category: 'encrypted_category', icon: 'encrypted_icon' })[field]] = await encryptWithAesGcmCombined(value, chatKey);
  if (editTitle) {
    const stored = ownerSocket.wait(frame => frame.type === 'post_processing_metadata_stored' && frame.payload.chat_id === chatId);
    ownerSocket.ws.send(JSON.stringify({ type: 'update_post_processing_metadata', payload: {
      chat_id: chatId, encrypted_title: editTitle, encrypted_chat_key: wrapped,
      manual_update: true, title_changed: true, versions: { title_v: 1, metadata_v: 1 },
    } }));
    const editReceipt = await stored;
    assert.ok(editReceipt.payload.versions.title_v > 1);
  }
  const payload = { protocol_version: 1, job_id: job.job_id, chat_key_version: 1, wrapped_chat_key: wrapped, encrypted_metadata: encrypted };
  const persisted = await ownerSocket.exchange('metadata_job_persist', payload, 'metadata_job_persisted');
  assert.equal(persisted.type, 'metadata_job_persisted');
  assert.equal(persisted.payload.state, 'TERMINAL');
  const replay = await ownerSocket.exchange('metadata_job_persist', payload, 'metadata_job_persisted');
  assert.equal(replay.type, 'metadata_job_persisted');
  assert.deepEqual(replay.payload.versions, persisted.payload.versions);
  return persisted.payload;
}
try {
  await admin('chats', { method: 'POST', body: { id: chatId, hashed_user_id: ownerHash,
    encrypted_chat_key: wrapped, encrypted_title: '', title_v: 0, metadata_v: 0, messages_v: 2,
    created_at: now, updated_at: now, last_edited_overall_timestamp: now, is_private: true } });
  await admin('chat_turn_preflights', { method: 'POST', body: { id: preflightId, hashed_user_id: ownerHash,
    chat_id: chatId, turn_id: turnId, user_message_id: userMessageId, device_hash: 'isolated-fixture', chat_key_version: 1,
    wrapped_chat_key: wrapped, recovery_public_key: rawPublic(recoveryPrivate).toString('base64url'),
    encrypted_user_digest: 'a'.repeat(64), inference_commitment: 'b'.repeat(64), commitment_version: 1,
    expected_messages_v: 0, committed_messages_v: 1, state: 'TERMINAL', inference_task_id: taskId,
    prepared_at: new Date().toISOString(), expires_at: new Date(Date.now() + 86400000).toISOString() } });
  await admin('messages', { method: 'POST', body: [
    { id: userMessageId, client_message_id: userMessageId, chat_id: chatId, hashed_user_id: ownerHash,
      role: 'user', encrypted_content: await encryptWithAesGcmCombined('Synthetic user question', chatKey), created_at: now, updated_at: now },
    { id: assistantMessageId, client_message_id: assistantMessageId, chat_id: chatId,
      role: 'assistant', encrypted_content: await encryptWithAesGcmCombined('Synthetic completed assistant answer', chatKey), created_at: now, updated_at: now },
  ] });
  // No pubsub events are sent: the origin disconnects before metadata exists.
  const origin = await connect(false); origin.ws.close();
  const initial = seal('initial', { title: 'Synthetic initial title', category: 'technology', icon: 'cpu' });
  const final = seal('postprocessing', { title: 'Synthetic final title', summary: 'Synthetic completed summary', category: 'technology', icon: 'cpu' });
  await operation('create_metadata_job', initial); await operation('create_metadata_job', final);
  ownerSocket = await connect(true);
  const available = await ownerSocket.wait(frame => frame.type === 'metadata_jobs_available'
    && frame.payload.jobs.some(job => job.job_id === initial.job_id));
  assert.ok(available.payload.jobs.some(job => job.job_id === final.job_id));
  const initialReceipt = await recover(initial);
  assert.equal(initialReceipt.versions.metadata_v, 1);
  const ownerTitle = await encryptWithAesGcmCombined('Owner changed title', chatKey);
  const finalReceipt = await recover(final, ownerTitle);
  assert.equal(finalReceipt.encrypted_metadata.encrypted_title, undefined);
  const persistedChat = await admin(`chats/${chatId}`);
  assert.equal(persistedChat.encrypted_title, ownerTitle);
  assert.equal(persistedChat.encrypted_chat_summary, finalReceipt.encrypted_metadata.encrypted_chat_summary);
  const row = await admin(`chat_metadata_recovery_jobs/${final.job_id}`);
  assert.equal(row.sealed_payload, null);
  const oldClient = await connect(false);
  const unavailable = await oldClient.exchange('metadata_job_claim', { protocol_version: 1, job_id: final.job_id }, 'metadata_job_claimed');
  assert.equal(unavailable.type, 'error'); assert.equal(unavailable.payload.code, 'metadata_capability_required');
  process.stdout.write(JSON.stringify({ discovery_after_disconnect: true, encrypted_commit: true,
    repeated_replay_idempotent: true, owner_edit_preserved: true, sealed_payload_removed: true,
    older_client_capability_guard: true, inference_calls: 0 }));
} finally {
  sockets.forEach(socket => socket.ws.close());
  await operation('invalidate_deletion', { protocol_version: 1, hashed_user_id: ownerHash, scope: 'chat', chat_id: chatId }).catch(() => {});
  await admin('messages', { method: 'DELETE', body: [userMessageId, assistantMessageId] }).catch(() => {});
  await admin(`chats/${chatId}`, { method: 'DELETE' }).catch(() => {});
}
