/**
 * context_entry chat history events: the encrypted role:system message written when the
 * user saves a memory or workflow opened from a chat Recommendation ("Memory created: X").
 * The event JSON is built and parsed only by the Rust core; this module writes it with
 * the existing client-encrypted system message path and keeps presentation-only system
 * events (context_entry, voice_call) out of AI request history.
 * Flag-off builds (VITE_OPENMATES_RUST_CORE unset) never write or parse these events.
 * Plan: docs/plans/chat-recommendations/plan.yml (wire_contract.system_event)
 */
import type { Message } from '../types/chat';
import type { ChatRecommendationKind, ContextEntryHistoryEvent } from '../types/recommendations';
import { chatDB } from './db';
import { chatKeyManager } from './encryption/ChatKeyManager';
import { encryptWithChatKey } from './encryption/MessageEncryptor';
import { ensureChatKeySafeForWrite } from './chatKeyWriteGuard';
import { webSocketService } from './websocketService';
import { parseVoiceCallHistoryEvent } from './voiceCallLifecycleEvent';
import {
  RECOMMENDATIONS_IN_BUILD,
  resolveChatRecommendation,
  rustRecommendations,
} from './chatRecommendationsPersistence';
import { nowSeconds } from '../stores/chatRecommendationsStore';
import { workflowSidePanelSaved, type WorkflowSidePanelSaved } from '../stores/workflowSidePanelStore';

/** Stable id: one event per saved recommendation, idempotent across retries. */
export function contextEntryMessageId(recommendationId: string): string {
  return `context-entry-${recommendationId}`;
}

/** Rust-validated event, or null (flag off, not an event, or invalid). */
export async function parseContextEntryContent(content: string): Promise<ContextEntryHistoryEvent | null> {
  // Cheap pre-check keeps ordinary system rows off the Worker.
  if (!RECOMMENDATIONS_IN_BUILD || !content.includes('context_entry')) return null;
  const { parseContextEntryEvent } = await rustRecommendations();
  return parseContextEntryEvent(content);
}

export interface ContextEntrySaved {
  chatId: string;
  recommendationId: string;
  kind: ChatRecommendationKind;
  action: 'created' | 'updated';
  entryId: string;
  title: string;
}

async function writeContextEntryMessage(saved: ContextEntrySaved): Promise<void> {
  const { buildContextEntryEvent } = await rustRecommendations();
  const createdAt = nowSeconds();
  const content = await buildContextEntryEvent({
    schema_version: 1, type: 'context_entry', kind: saved.kind, action: saved.action,
    entry_id: saved.entryId, title: saved.title, created_at: createdAt,
  });
  const messageId = contextEntryMessageId(saved.recommendationId);
  const existing = await chatDB.getMessage(messageId);
  if (existing && existing.status !== 'sending') return;
  const key = await chatKeyManager.getKey(saved.chatId);
  if (!key || !(await ensureChatKeySafeForWrite(saved.chatId, key, 'context entry event'))) {
    throw new Error('context_entry_chat_key_unavailable');
  }
  const message = {
    message_id: messageId, chat_id: saved.chatId, role: 'system' as const, content,
    encrypted_content: await encryptWithChatKey(content, key),
    created_at: createdAt, status: 'sending' as const,
  };
  await chatDB.saveMessage(message);
  await webSocketService.sendMessage('chat_system_message_added', {
    chat_id: saved.chatId,
    message: { ...message, content: undefined, status: 'synced' },
  });
  const synced = { ...message, status: 'synced' as const };
  await chatDB.saveMessage(synced);
  const { chatSyncService } = await import('./chatSyncService');
  chatSyncService.dispatchEvent(new CustomEvent('chatUpdated', {
    detail: { chat_id: saved.chatId, type: 'system_message_added', newMessage: synced },
  }));
}

/**
 * After a successful save of an entry opened from a recommendation: removes the
 * recommendation (resolved) and adds the encrypted context_entry history event.
 */
export async function recordContextEntrySaved(saved: ContextEntrySaved): Promise<void> {
  if (!RECOMMENDATIONS_IN_BUILD) return;
  await resolveChatRecommendation(saved.chatId, saved.recommendationId);
  await writeContextEntryMessage(saved);
}

let handledWorkflowSave: WorkflowSidePanelSaved | null = null;

/**
 * Records each workflow saved from the side panel (once per save event, however many
 * subscribers mount). Returns the unsubscribe function.
 */
export function listenForWorkflowRecommendationSaves(): () => void {
  if (!RECOMMENDATIONS_IN_BUILD) return () => {};
  return workflowSidePanelSaved.subscribe((saved) => {
    if (!saved || saved === handledWorkflowSave) return;
    handledWorkflowSave = saved;
    void recordContextEntrySaved({
      chatId: saved.chatId, recommendationId: saved.recommendationId, kind: 'workflow',
      action: saved.action, entryId: saved.workflowId, title: saved.title,
    }).catch((error) => console.error('[Recommendations] Could not record the saved workflow in the chat', error));
  });
}

/**
 * History for an AI request without presentation-only system events (context_entry,
 * voice_call). Flag-off builds return the messages unchanged.
 */
export async function withoutPresentationOnlyEvents<T extends Pick<Message, 'role' | 'content'>>(
  messages: T[],
): Promise<T[]> {
  if (!RECOMMENDATIONS_IN_BUILD) return messages;
  const keep = await Promise.all(messages.map(async (message) => {
    if (message.role !== 'system' || typeof message.content !== 'string') return true;
    if (parseVoiceCallHistoryEvent(message.content)) return false;
    return !(await parseContextEntryContent(message.content));
  }));
  return messages.filter((_, index) => keep[index]);
}
