// contract-test-file: infrastructure
import assert from 'node:assert/strict';
import { test } from 'node:test';
import { createCipheriv, createHash, createPrivateKey, createPublicKey, diffieHellman, hkdfSync, randomBytes, randomUUID } from 'node:crypto';
import { deriveChatCompletionRecoveryKeypair, openChatMetadataRecoveryEnvelope, decryptWithAesGcmCombined } from '../src/crypto.js';
import { registerChatMetadataRecovery, filterMetadataReceiptForCurrentVersions, type MetadataReceipt } from '../src/chatMetadataRecovery.js';
import type { OpenMatesWsClient } from '../src/ws.js';
const prefix = (value: string) => { const bytes = Buffer.from(value), count = Buffer.alloc(4); count.writeUInt32BE(bytes.length); return Buffer.concat([count, bytes]); };
const hash = (value: string | Uint8Array) => createHash('sha256').update(value).digest();
async function fixture(stage: 'initial' | 'postprocessing' = 'initial', base?: { identity: { ownerId: string; chatId: string; taskId: string }; key: Uint8Array }) {
  const ownerId = base?.identity.ownerId ?? randomUUID(), chatId = base?.identity.chatId ?? randomUUID(), taskId = base?.identity.taskId ?? randomUUID(), jobId = randomUUID();
  const key = Buffer.from(base?.key ?? randomBytes(32)), pair = await deriveChatCompletionRecoveryKeypair(key.toString("base64url"), chatId, 1);
  const identity = { ownerId, chatId, taskId, jobId, stage, keyVersion: 1 };
  const metadata = { title: 'Early title', summary: 'Early summary', category: 'technology', icon: 'cpu' };
  const seal = (payload: Record<string, unknown>) => {
    const aad = Buffer.concat([Buffer.from('OMCM1'), ...[ownerId, chatId, taskId, jobId, stage].map(prefix), Buffer.from([0, 0, 0, 1])]);
    const privateKey = createPrivateKey({ key: Buffer.concat([Buffer.from('302e020100300506032b656e04220420', 'hex'), randomBytes(32)]), format: 'der', type: 'pkcs8' });
    const publicKey = createPublicKey({ key: Buffer.concat([Buffer.from('302a300506032b656e032100', 'hex'), Buffer.from(pair.publicKey, 'base64url')]), format: 'der', type: 'spki' });
    const secret = diffieHellman({ privateKey, publicKey });
    const envelopeKey = Buffer.from(hkdfSync('sha256', secret, hash('openmates:chat-recovery-envelope:v1'), hash(aad), 32));
    const nonce = randomBytes(12), cipher = createCipheriv('aes-256-gcm', envelopeKey, nonce); cipher.setAAD(aad);
    const encrypted = Buffer.concat([cipher.update(JSON.stringify(payload)), cipher.final(), cipher.getAuthTag()]);
    return { v: 1, epk: createPublicKey(privateKey).export({ format: 'der', type: 'spki' }).subarray(-32).toString('base64url'), nonce: nonce.toString('base64url'), ciphertext: encrypted.toString('base64url') };
  };
  const payload = { owner_id: ownerId, chat_id: chatId, task_id: taskId, job_id: jobId, stage, key_version: 1, metadata };
  const envelope = seal(payload);
  const job = { job_id: jobId, chat_id: chatId, task_id: taskId, stage, chat_key_version: 1 };
  return { identity, key, pair, metadata, payload, seal, envelope, job };
}

// contract-test: supporting surface=cli assertions=chats.completion.independent-metadata
test('OMCM1 opens independent backend-compatible metadata and binds owner, stage, task and key version', async () => {
  const f = await fixture(); const options = { ...f.identity, recoveryPrivateKey: f.pair.privateKey };
  assert.deepEqual(await openChatMetadataRecoveryEnvelope(f.envelope, options), f.metadata);
  for (const changed of [{ ownerId: randomUUID() }, { taskId: randomUUID() }, { stage: 'postprocessing' as const }, { keyVersion: 2 }])
    await assert.rejects(openChatMetadataRecoveryEnvelope(f.envelope, { ...options, ...changed }));
  await assert.rejects(openChatMetadataRecoveryEnvelope(f.seal({ ...f.payload, task_id: randomUUID() }), options), /identity/);
  await assert.rejects(openChatMetadataRecoveryEnvelope(f.seal({ ...f.payload, metadata: { title: 'ok', content: 'forbidden' } }), options), /fields/);
  await assert.rejects(openChatMetadataRecoveryEnvelope(f.seal({ ...f.payload, metadata: { summary: 'x'.repeat(65536) } }), options), /size/);
});

// contract-test: supporting surface=cli assertions=chats.completion.independent-metadata
test('metadata recovery waits for cold-sync key then persists accepted encrypted fields with correlated receipts', async () => {
  const f = await fixture();
  const handlers = new Map<string, (frame: unknown) => void>();
  const waiting = new Map<string, { predicate: (frame: unknown) => boolean; resolve: (value: unknown) => void }>();
  const sent: Array<{ type: string; payload: Record<string, unknown> }> = [];
  const applied: MetadataReceipt[] = [];
  let keyReady = false;
  const ws = {
    isOpen: () => true, onClose: () => () => {},
    onMessageType(type: string, handler: (frame: unknown) => void) { handlers.set(type, handler); return () => handlers.delete(type); },
    waitForMessage(type: string, predicate: (frame: unknown) => boolean) {
      return new Promise(resolve => { waiting.set(type, { predicate, resolve }); });
    },
    async sendAsync(type: string, payload: Record<string, unknown>) {
      sent.push({ type, payload });
      const responseType = type === 'metadata_job_claim' ? 'metadata_job_claimed' : 'metadata_job_persisted';
      const response = type === 'metadata_job_claim' ? { ...f.job, state: 'AVAILABLE', sealed_payload: JSON.stringify(f.envelope),
        encrypted_fields: ['encrypted_title', 'encrypted_chat_summary', 'encrypted_category', 'encrypted_icon'] }
        : { ...f.job, state: 'TERMINAL', versions: { title_v: 3, metadata_v: 5 },
          encrypted_metadata: { encrypted_chat_summary: (payload.encrypted_metadata as Record<string, string>).encrypted_chat_summary } };
      const receipt = { ...response, request_id: payload.request_id };
      const waiter = waiting.get(responseType)!;
      assert.equal(waiter.predicate({ ...receipt, request_id: 'unrelated' }), false);
      assert.equal(waiter.predicate(receipt), true); waiter.resolve({ payload: receipt });
    },
  } as unknown as OpenMatesWsClient;
  const worker = registerChatMetadataRecovery({ ws, ownerId: f.identity.ownerId, ownerCurrent: () => true,
    resolveKey: async () => keyReady ? { key: f.key, wrappedKey: 'wrapped-key' } : null,
    apply: async receipt => { applied.push(receipt); } });
  handlers.get('metadata_jobs_available')!({ jobs: [f.job] }); await worker.flush();
  assert.equal(sent.length, 0, 'missing key leaves durable discovery pending');
  keyReady = true; await worker.flush();
  assert.deepEqual(sent.map(item => item.type), ['metadata_job_claim', 'metadata_job_persist']);
  const persisted = sent[1]!.payload;
  assert.equal(persisted.wrapped_chat_key, 'wrapped-key');
  assert.equal(await decryptWithAesGcmCombined((persisted.encrypted_metadata as Record<string, string>).encrypted_title!, f.key), f.metadata.title);
  assert.deepEqual(Object.keys(applied[0]!.encrypted_metadata), ['encrypted_chat_summary'], 'manual-edit title omitted by server never enters accepted local receipt');
  assert.deepEqual(applied[0]!.versions, { title_v: 3, metadata_v: 5 });
  await worker.flush(); assert.equal(sent.length, 2, 'completed job is not repeated');
  Object.assign(f, await fixture('postprocessing', f));
  handlers.get('metadata_jobs_available')!({ jobs: [f.job] }); await worker.flush();
  assert.equal(sent.length, 4, 'early metadata does not stop processing final metadata');
  assert.equal(applied[1]!.stage, 'postprocessing');
});


// contract-test: supporting surface=cli assertions=chats.completion.independent-metadata
test('a delayed metadata receipt cannot repaint a manual or newer cached update', async () => {
  const receipt: MetadataReceipt = { job_id: randomUUID(), chat_id: randomUUID(), stage: 'postprocessing',
    versions: { metadata_v: 2, title_v: 2 }, encrypted_metadata: {
      encrypted_title: 'generated-title-before-edit', encrypted_chat_summary: 'generated-summary-before-edit' } };
  const live = { metadata_v: 1, title_v: 1, encrypted_title: 'old-title', encrypted_chat_summary: 'old-summary' };
  const disk = { ...live };
  const callbacks: MetadataReceipt[] = [];
  let deliver!: (receipt: MetadataReceipt) => void;
  const delayed = new Promise<MetadataReceipt>(resolve => { deliver = resolve; });
  const apply = delayed.then(value => {
    const accepted = filterMetadataReceiptForCurrentVersions(value, [live, disk]);
    if (!accepted) return;
    Object.assign(live, accepted.encrypted_metadata, accepted.versions);
    Object.assign(disk, accepted.encrypted_metadata, accepted.versions);
    callbacks.push(accepted);
  });
  // The server committed the generated receipt, then a manual update arrived
  // on another socket before the delayed receipt reached this adapter.
  Object.assign(disk, { metadata_v: 3, title_v: 3, encrypted_title: 'owner-title', encrypted_chat_summary: 'newer-summary' });
  deliver(receipt); await apply;
  assert.equal(callbacks.length, 0);
  assert.equal(disk.encrypted_title, 'owner-title');
  assert.equal(disk.encrypted_chat_summary, 'newer-summary');
  assert.equal(live.metadata_v, 1, 'reject the receipt across both caches before mutating either');
});

// contract-test: supporting surface=cli assertions=chats.completion.independent-metadata
test('accepted summary refinement omits a title superseded locally and retains its newer version', () => {
  const receipt: MetadataReceipt = { job_id: randomUUID(), chat_id: randomUUID(), stage: 'postprocessing',
    versions: { metadata_v: 4, title_v: 2 }, encrypted_metadata: {
      encrypted_title: 'stale-title', encrypted_chat_summary: 'refined-summary' } };
  const accepted = filterMetadataReceiptForCurrentVersions(receipt, [{ metadata_v: 4, title_v: 3 }]);
  assert.deepEqual(accepted?.encrypted_metadata, { encrypted_chat_summary: 'refined-summary' });
  assert.deepEqual(accepted?.versions, { metadata_v: 4, title_v: 3 });
  assert.equal(receipt.encrypted_metadata.encrypted_title, 'stale-title', 'filtering never mutates the protocol receipt');
});
