/** Recover committed voice artifacts independently of Live speech lifecycle. */
import type { ChatSynchronizationService } from './chatSyncService';
import { chatDB } from './db';
import { chatKeyManager } from './encryption/ChatKeyManager';
import { userDB } from './userDB';
import { userProfile } from '../stores/userProfile';
import { getWebSocketToken } from '../utils/cookies';
import { webSocketService } from './websocketService';
import { upsertCallArtifact } from './voiceCallMessages';

interface VoiceActionReceipt {
  request_id: string; call_id: string; chat_id: string; assistant_message_id: string;
  user_message_id: string; initiator_session_id: string; user_id: string;
  embed_refs: string[]; created_at: number;
}
interface PendingAction {
  receipt: VoiceActionReceipt; service: ChatSynchronizationService;
  requestedChat: boolean; running?: Promise<void>; retryRequested?: boolean;
}
const pending = new Map<string, PendingAction>();
const services = new WeakSet<ChatSynchronizationService>();
let keyListenerInstalled = false;
const identity = /^[A-Za-z0-9][A-Za-z0-9_:-]{7,127}$/;
function parseReceipt(value: unknown): VoiceActionReceipt | null {
  if (!value || typeof value !== 'object' || Array.isArray(value)) return null;
  const row = value as Record<string, unknown>;
  if (!['request_id', 'call_id', 'chat_id', 'assistant_message_id', 'user_message_id', 'user_id']
    .every((key) => typeof row[key] === 'string' && identity.test(row[key] as string)) ||
    typeof row.initiator_session_id !== 'string' || !/^[a-f0-9]{64}$/.test(row.initiator_session_id) ||
    !Number.isSafeInteger(row.created_at) || Number(row.created_at) <= 0 ||
    !Array.isArray(row.embed_refs) || !row.embed_refs.length || row.embed_refs.length > 128 ||
    !row.embed_refs.every((ref) => typeof ref === 'string' && /^[A-Za-z0-9_-]{1,128}$/.test(ref))) return null;
  return row as unknown as VoiceActionReceipt;
}
function ownsSession(receipt: VoiceActionReceipt): boolean {
  // HMAC WebSocket tokens carry the authenticated session hash as their first
  // segment. The server independently checks this same session on recovery/ACK.
  return getWebSocketToken()?.split(':')[0] === receipt.initiator_session_id;
}
function installListeners(service: ChatSynchronizationService): void {
  if (!services.has(service)) {
    services.add(service);
    service.addEventListener('chatUpdated', (event) => {
      const detail = (event as CustomEvent<{ chat_id?: string; newMessage?: unknown }>).detail;
      // Our own artifact writes emit newMessage. Retrying those notifications
      // would turn a permanent storage failure into a self-sustaining loop.
      if (detail?.chat_id && !detail.newMessage) void flush(detail.chat_id);
    });
    service.addEventListener('embedUpdated', (event) => {
      const id = (event as CustomEvent<{ embed_id?: string }>).detail?.embed_id;
      // A committed action can precede main-socket encrypted embed delivery,
      // including after Live has ended. Retry only receipts that need this ID.
      if (id) void Promise.allSettled([...pending.values()]
        .filter((job) => job.receipt.embed_refs.includes(id)).map(attempt));
    });
  }
  if (!keyListenerInstalled) {
    keyListenerInstalled = true;
    chatKeyManager.onKeyReady((chatId) => { void flush(chatId); });
    userProfile.subscribe(() => { void flush(); });
  }
}
async function flush(chatId?: string): Promise<void> {
  await Promise.allSettled([...pending.values()].filter((job) => !chatId || job.receipt.chat_id === chatId)
    .map((job) => attempt(job)));
}
function attempt(job: PendingAction): Promise<void> {
  if (job.running) { job.retryRequested = true; return job.running; }
  const work = persist(job);
  job.running = work;
  void work.finally(() => {
    if (job.running === work) job.running = undefined;
    if (job.retryRequested && pending.has(job.receipt.request_id)) {
      job.retryRequested = false;
      void attempt(job).catch(() => {});
    }
  }).catch(() => {});
  return work;
}
async function persist(job: PendingAction): Promise<void> {
  const receipt = job.receipt;
  if (!ownsSession(receipt)) { pending.delete(receipt.request_id); return; }
  const profile = await userDB.getUserProfile();
  if (!profile?.user_id) return; // Startup profile hydration will retry the receipt.
  if (profile.user_id !== receipt.user_id) { pending.delete(receipt.request_id); return; }
  const chat = await chatDB.getChat(receipt.chat_id);
  const key = chat ? await chatKeyManager.getKey(receipt.chat_id) : null;
  if (!chat || !key) {
    if (!job.requestedChat) {
      job.requestedChat = true;
      await job.service.requestChatContentBatch_FOR_HANDLERS_ONLY([receipt.chat_id]);
    }
    return;
  }
  if (chat.team_id || chat.chat_visibility === 'direct' ||
      chat.user_id && chat.user_id !== receipt.user_id) throw new Error('Voice action chat ownership mismatch');
  if (!ownsSession(receipt) || (await userDB.getUserProfile())?.user_id !== receipt.user_id) return;
  const proof = await upsertCallArtifact({ callId: receipt.call_id, chatId: receipt.chat_id,
    messageId: receipt.assistant_message_id, userMessageId: receipt.user_message_id,
    createdAt: receipt.created_at, embedRefs: receipt.embed_refs });
  if (!proof) throw new Error('Voice action encrypted storage was not confirmed');
  const hash = new Uint8Array(await crypto.subtle.digest('SHA-256', new TextEncoder().encode(proof.ciphertext)));
  const ciphertext_hash = [...hash].map((byte) => byte.toString(16).padStart(2, '0')).join('');
  if (!ownsSession(receipt) || (await userDB.getUserProfile())?.user_id !== receipt.user_id) return;
  await webSocketService.sendMessage('voice_action_completed_confirmed', {
    request_id: receipt.request_id, call_id: receipt.call_id, chat_id: receipt.chat_id,
    assistant_message_id: receipt.assistant_message_id, revision: proof.revision, ciphertext_hash,
  });
  pending.delete(receipt.request_id);
}

export async function handleVoiceActionCompleted(service: ChatSynchronizationService, value: unknown): Promise<void> {
  const receipt = parseReceipt(value);
  if (!receipt || !ownsSession(receipt)) return;
  installListeners(service);
  for (const [id, job] of pending) if (!ownsSession(job.receipt)) pending.delete(id);
  if (!pending.has(receipt.request_id) && pending.size >= 128) throw new Error('Voice action recovery capacity exceeded');
  const job = pending.get(receipt.request_id) ?? { receipt, service, requestedChat: false };
  pending.set(receipt.request_id, job);
  await attempt(job);
}
