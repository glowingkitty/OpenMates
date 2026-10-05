/** Persist authoritative context receipts using the existing client-encrypted chat path. */
import type { ChatSynchronizationService } from './chatSyncService';
import { parseAgentContextEvent } from '../utils/agentContextEvents';
import { chatDB } from './db';
import { chatKeyManager } from './encryption/ChatKeyManager';
import { encryptWithChatKey } from './encryption/MessageEncryptor';
import { ensureChatKeySafeForWrite } from './chatKeyWriteGuard';
import { webSocketService } from './websocketService';

export interface ChatContextAppliedPayload {
  chat_id: string;
  event: Record<string, unknown>;
}
const queues = new Map<string, Promise<void>>();
const uuid = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;

export function handleChatContextApplied(service: ChatSynchronizationService,
  payload: ChatContextAppliedPayload): Promise<void> {
  if (!payload || !uuid.test(payload.chat_id)) return Promise.resolve();
  const previous = queues.get(payload.chat_id) ?? Promise.resolve();
  const next = previous.catch(() => {}).then(() => apply(service, payload));
  queues.set(payload.chat_id, next);
  void next.finally(() => {
    if (queues.get(payload.chat_id) === next) queues.delete(payload.chat_id);
  }).catch(() => {});
  return next;
}

async function apply(service: ChatSynchronizationService, payload: ChatContextAppliedPayload): Promise<void> {
  const event = payload.event;
  if (!event || !parseAgentContextEvent(event) || event.chat_id !== payload.chat_id
    || typeof event.event_id !== 'string' || !uuid.test(event.event_id)
    || !Number.isSafeInteger(event.created_at) || Number(event.created_at) <= 0) return;
  const content = JSON.stringify(event);
  if (content.length > 100_000) return;
  const existing = await chatDB.getMessage(event.event_id);
  if (existing && (existing.status !== 'sending' || existing.chat_id !== payload.chat_id
    || existing.content !== content || !existing.encrypted_content)) return;
  const chat = await chatDB.getChat(payload.chat_id);
  const key = await chatKeyManager.getKey(payload.chat_id);
  if (!chat || !key || !(await ensureChatKeySafeForWrite(payload.chat_id, key, 'applied context receipt'))) return;
  const encryptedContent = existing?.encrypted_content ?? await encryptWithChatKey(content, key);
  // Recheck after asynchronous encryption: a concurrent synced device may have
  // persisted this same deterministic event ID already.
  const concurrent = await chatDB.getMessage(event.event_id);
  if (concurrent && concurrent.status !== 'sending') return;
  const message = { message_id: event.event_id, chat_id: payload.chat_id,
    role: 'system' as const, content, encrypted_content: encryptedContent,
    created_at: Number(event.created_at), status: 'sending' as const };
  await chatDB.saveMessage(message);
  await webSocketService.sendMessage('chat_system_message_added', { chat_id: payload.chat_id,
    message: { ...message, content: undefined, status: 'synced' } });
  const synced = { ...message, status: 'synced' as const };
  await chatDB.saveMessage(synced);
  service.dispatchEvent(new CustomEvent('chatUpdated', { detail: {
    chat_id: payload.chat_id, type: 'system_message_added', newMessage: synced,
  } }));
}
