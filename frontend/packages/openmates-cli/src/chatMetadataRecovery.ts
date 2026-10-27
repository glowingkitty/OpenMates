/** Client-only metadata recovery. Durable discovery carries no generated plaintext. */
import { randomUUID } from 'node:crypto';
import { deriveChatCompletionRecoveryKeypair, openChatMetadataRecoveryEnvelope,
  encryptWithAesGcmCombined, type ChatCompletionRecoveryEnvelope } from './crypto.js';
import type { OpenMatesWsClient } from './ws.js';

export interface MetadataChatKey { key: Uint8Array; wrappedKey: string }
export interface MetadataReceipt {
  job_id: string; chat_id: string; stage: 'initial' | 'postprocessing';
  versions: Record<string, number>; encrypted_metadata: Record<string, string>;
}
/** A delayed server receipt cannot repaint metadata already advanced locally. */
export function filterMetadataReceiptForCurrentVersions(
  receipt: MetadataReceipt, currentRows: Array<Record<string, unknown> | undefined>,
): MetadataReceipt | null {
  const metadataVersion = Math.max(0, ...currentRows.map(row => Number(row?.metadata_v ?? 0)));
  const titleVersion = Math.max(0, ...currentRows.map(row => Number(row?.title_v ?? 0)));
  if ((receipt.versions.metadata_v ?? -1) < metadataVersion) return null;
  const accepted = { ...receipt.encrypted_metadata };
  if ((receipt.versions.title_v ?? -1) < titleVersion) delete accepted.encrypted_title;
  if (!Object.keys(accepted).length) return null;
  return { ...receipt, encrypted_metadata: accepted,
    versions: { ...receipt.versions, title_v: Math.max(receipt.versions.title_v ?? 0, titleVersion) } };
}

interface Job {
  job_id: string; chat_id: string; task_id: string;
  stage: 'initial' | 'postprocessing'; chat_key_version: number;
}
const fields: Record<string, string> = { title: 'encrypted_title', summary: 'encrypted_chat_summary',
  category: 'encrypted_category', icon: 'encrypted_icon' };

export function registerChatMetadataRecovery(options: {
  ws: OpenMatesWsClient; ownerId: string; ownerCurrent: () => boolean;
  resolveKey: (chatId: string) => Promise<MetadataChatKey | null>;
  apply: (receipt: MetadataReceipt) => Promise<void>;
}) {
  const pending = new Map<string, Job>();
  const live = new Map<string, MetadataChatKey>();
  let stopped = false;
  let work = Promise.resolve();
  const current = () => !stopped && options.ownerCurrent() && options.ws.isOpen();
  const exchange = async (type: string, payload: Record<string, unknown>, response: string, jobId: string) => {
    const requestId = randomUUID();
    const waiting = options.ws.waitForMessage(response, raw => {
      const frame = raw as Record<string, unknown>;
      return frame.request_id === requestId && frame.job_id === jobId;
    }, 20_000);
    void waiting.catch(() => {});
    if (!current()) throw new Error('Metadata recovery owner changed');
    await options.ws.sendAsync(type, { ...payload, protocol_version: 1, request_id: requestId, job_id: jobId });
    const frame = (await waiting).payload as Record<string, unknown>;
    if (!current()) throw new Error('Metadata recovery owner changed');
    return frame;
  };
  const recover = async (job: Job) => {
    if (!current()) return;
    const chatKey = live.get(job.chat_id) ?? await options.resolveKey(job.chat_id);
    if (!chatKey || !current()) return; // Cold sync provides the wrapper before retrying.
    const claim = await exchange('metadata_job_claim', {}, 'metadata_job_claimed', job.job_id);
    if (claim.chat_id !== job.chat_id || claim.task_id !== job.task_id || claim.stage !== job.stage
      || claim.chat_key_version !== job.chat_key_version) throw new Error('Metadata claim identity mismatch');
    if (claim.state !== 'AVAILABLE') { pending.delete(job.job_id); return; }
    if (typeof claim.sealed_payload !== 'string' || claim.sealed_payload.length > 100_000) throw new Error('Invalid metadata envelope');
    const pair = await deriveChatCompletionRecoveryKeypair(Buffer.from(chatKey.key).toString("base64url"), job.chat_id, job.chat_key_version);
    const metadata = await openChatMetadataRecoveryEnvelope(JSON.parse(claim.sealed_payload) as ChatCompletionRecoveryEnvelope, {
      ownerId: options.ownerId, chatId: job.chat_id, taskId: job.task_id, jobId: job.job_id,
      stage: job.stage, keyVersion: job.chat_key_version, recoveryPrivateKey: pair.privateKey,
    });
    const encrypted: Record<string, string> = {};
    for (const [field, value] of Object.entries(metadata)) encrypted[fields[field]!] = await encryptWithAesGcmCombined(value, chatKey.key);
    if (!Array.isArray(claim.encrypted_fields)
      || [...claim.encrypted_fields].sort().join(',') !== Object.keys(encrypted).sort().join(',')) throw new Error('Metadata encrypted fields mismatch');
    const receipt = await exchange('metadata_job_persist', { chat_key_version: job.chat_key_version,
      wrapped_chat_key: chatKey.wrappedKey, encrypted_metadata: encrypted }, 'metadata_job_persisted', job.job_id);
    if (receipt.chat_id !== job.chat_id || receipt.stage !== job.stage
      || !['TERMINAL', 'SUPERSEDED'].includes(String(receipt.state))
      || !receipt.versions || typeof receipt.versions !== 'object'
      || Object.keys(receipt.versions).sort().join(',') !== 'metadata_v,title_v'
      || Object.entries(receipt.versions).some(([key, value]) => !['title_v', 'metadata_v'].includes(key)
        || !Number.isSafeInteger(value) || Number(value) < 0)
      || !receipt.encrypted_metadata || typeof receipt.encrypted_metadata !== 'object'
      || Object.entries(receipt.encrypted_metadata).some(([key, value]) => !Object.values(fields).includes(key)
        || typeof value !== 'string')) throw new Error('Invalid metadata receipt');
    await options.apply(receipt as unknown as MetadataReceipt);
    pending.delete(job.job_id);
  };
  const flush = () => {
    work = work.then(async () => {
      for (const job of [...pending.values()]) {
        if (!current()) return;
        try { await recover(job); } catch { /* Keep durable job pending; metadata cannot fail the reply. */ }
      }
    });
    return work;
  };
  const remove = options.ws.onMessageType<{ jobs?: Job[] }>('metadata_jobs_available', frame => {
    if (!frame || !Array.isArray(frame.jobs) || frame.jobs.length > 100) return;
    for (const job of frame.jobs) {
      if (!job || typeof job.job_id !== 'string' || typeof job.chat_id !== 'string' || typeof job.task_id !== 'string'
        || !['initial', 'postprocessing'].includes(job.stage) || !Number.isSafeInteger(job.chat_key_version)
        || job.chat_key_version < 1 || pending.size >= 100) continue;
      pending.set(job.job_id, job);
    }
    void flush();
  });
  options.ws.onClose(() => { stopped = true; pending.clear(); live.clear(); remove(); });
  return { flush, setLiveChat(chatId: string, key: MetadataChatKey) { live.set(chatId, key); void flush(); } };
}
