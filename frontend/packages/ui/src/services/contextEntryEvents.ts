/**
 * context_entry chat history events: the encrypted role:system message written when the
 * user saves a memory or workflow opened from a chat Recommendation ("Memory created: X").
 * The event JSON is built and parsed only by the Rust core; this module writes it with
 * the existing client-encrypted system message path and keeps presentation-only system
 * events (context_entry, voice_call, assistant Memory write undone markers) out of AI
 * request history. Assistant Memory write notices (source: assistant) are written by
 * the core job runner (rustCore/memory/memoryWriteJobRunner.ts) through storeSystemEvent.
 * Flag-off builds (VITE_OPENMATES_RUST_CORE unset) never write or parse these events.
 * Plan: docs/plans/chat-recommendations/plan.yml (wire_contract.system_event)
 */
import type { Message } from '../types/chat';
import type { ChatRecommendationKind, ContextEntryHistoryEvent, MemoryWriteUndoneEvent } from '../types/recommendations';
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

/** `type` of the hidden undone marker row (memory_write_jobs.rs). */
const MEMORY_WRITE_UNDONE_TYPE = 'memory_write_undone';

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

/** Rust-validated undone marker of an assistant Memory write, or null. */
export async function parseMemoryWriteUndoneContent(content: string): Promise<MemoryWriteUndoneEvent | null> {
  if (!RECOMMENDATIONS_IN_BUILD || !content.includes(MEMORY_WRITE_UNDONE_TYPE)) return null;
  const { parseMemoryWriteUndone } = await rustRecommendations();
  return parseMemoryWriteUndone(content);
}

/** Cheap pre-check of rows that may be context_entry events or undone markers. */
export function isContextEntryCandidateContent(content: string): boolean {
  return content.includes('"context_entry"') || content.includes(MEMORY_WRITE_UNDONE_TYPE);
}

/** Validated notices by message id, and the job ids whose assistant write was undone. */
export interface ContextEntryHistory {
  events: Record<string, ContextEntryHistoryEvent>;
  undoneJobIds: Set<string>;
}

/** Reads the context_entry notices and undone markers among candidate system rows. */
export async function readContextEntryHistory(rows: { id: string; content: string }[]): Promise<ContextEntryHistory> {
  const events: Record<string, ContextEntryHistoryEvent> = {};
  const undoneJobIds = new Set<string>();
  await Promise.all(rows.map(async ({ id, content }) => {
    const event = await parseContextEntryContent(content);
    if (event) { events[id] = event; return; }
    const marker = await parseMemoryWriteUndoneContent(content);
    if (marker) undoneJobIds.add(marker.job_id);
  }));
  return { events, undoneJobIds };
}

export interface ContextEntrySaved {
  chatId: string;
  recommendationId: string;
  kind: ChatRecommendationKind;
  action: 'created' | 'updated';
  entryId: string;
  title: string;
}

/** Optional linkage of a stored system event. */
export interface SystemEventLink {
  /** User message of the turn (assistant Memory write notices). */
  userMessageId?: string;
}

/**
 * Stores Rust-built system event `content` as an encrypted `role: system` message
 * (local first, then `chat_system_message_added`) and shows it in the open chat.
 * Idempotent per message id. Returns false when the message already existed.
 */
export async function storeSystemEvent(
  chatId: string, messageId: string, content: string, createdAt: number, link: SystemEventLink = {},
): Promise<boolean> {
  const existing = await chatDB.getMessage(messageId);
  if (existing && existing.status !== 'sending') return false;
  const key = await chatKeyManager.getKey(chatId);
  if (!key || !(await ensureChatKeySafeForWrite(chatId, key, 'context entry event'))) {
    throw new Error('context_entry_chat_key_unavailable');
  }
  const message = {
    message_id: messageId, chat_id: chatId, role: 'system' as const, content,
    encrypted_content: await encryptWithChatKey(content, key),
    created_at: createdAt, status: 'sending' as const,
    ...(link.userMessageId ? { user_message_id: link.userMessageId } : {}),
  };
  await chatDB.saveMessage(message);
  await webSocketService.sendMessage('chat_system_message_added', {
    chat_id: chatId,
    message: { ...message, content: undefined, status: 'synced' },
  });
  const synced = { ...message, status: 'synced' as const };
  await chatDB.saveMessage(synced);
  const { chatSyncService } = await import('./chatSyncService');
  chatSyncService.dispatchEvent(new CustomEvent('chatUpdated', {
    detail: { chat_id: chatId, type: 'system_message_added', newMessage: synced },
  }));
  return true;
}

async function writeContextEntryMessage(saved: ContextEntrySaved): Promise<void> {
  const { buildContextEntryEvent } = await rustRecommendations();
  const createdAt = nowSeconds();
  const content = await buildContextEntryEvent({
    schema_version: 1, type: 'context_entry', kind: saved.kind, action: saved.action,
    entry_id: saved.entryId, title: saved.title, created_at: createdAt,
  });
  await storeSystemEvent(saved.chatId, contextEntryMessageId(saved.recommendationId), content, createdAt);
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
    if (await parseMemoryWriteUndoneContent(message.content)) return false;
    return !(await parseContextEntryContent(message.content));
  }));
  return messages.filter((_, index) => keep[index]);
}
