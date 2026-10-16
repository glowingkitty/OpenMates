import { parseAgentContextEvent } from './agentContextEvents';
import type { AppliedMemory, MemoriesLoadedEvent } from './loadedMemoryReceipt';

export interface MemoryAssociationMessage {
  id: string;
  role: string;
  content?: unknown;
  original_message?: { content?: unknown; user_message_id?: string | null; chat_id?: string | null } | null;
}
export interface PendingMemoryAssistant { taskId: string; userMessageId: string; chatId?: string | null }

/** Resolve receipts against the complete ordered history, before virtualizing rows. */
export function associateLoadedMemories(
  messages: readonly MemoryAssociationMessage[], pending?: PendingMemoryAssistant | null,
): { byAssistantId: Map<string, AppliedMemory[]>; attachedReceiptIds: Set<string> } {
  const byAssistantId = new Map<string, AppliedMemory[]>();
  const attachedReceiptIds = new Set<string>();
  const assistants = messages.filter((message) => message.role === 'assistant');
  const candidateFor = (event: MemoriesLoadedEvent, receipt: MemoryAssociationMessage, index: number): MemoryAssociationMessage | undefined => {
    const sameChat = (candidate: MemoryAssociationMessage) => !receipt.original_message?.chat_id
      || !candidate.original_message?.chat_id
      || candidate.original_message.chat_id === receipt.original_message.chat_id;
    const sameUser = (candidate: MemoryAssociationMessage) => !event.user_message_id
      || !candidate.original_message?.user_message_id
      || candidate.original_message.user_message_id === event.user_message_id;
    if (event.assistant_message_id) {
      const exact = assistants.find((candidate) => candidate.id === event.assistant_message_id);
      return exact && sameChat(exact) && sameUser(exact) ? exact : undefined;
    }
    if (event.user_message_id) {
      const matches = assistants.filter((candidate) => candidate.original_message?.user_message_id === event.user_message_id && sameChat(candidate));
      return matches.length === 1 ? matches[0] : undefined;
    }
    // Legacy receipts have no server identity. Never infer across a user-turn boundary.
    let first = index;
    while (first > 0 && messages[first - 1].role !== 'user') first--;
    if (first === 0 && messages[0]?.role !== 'user') return undefined;
    let last = index + 1;
    while (last < messages.length && messages[last].role !== 'user') last++;
    const matches = messages.slice(first, last).filter((candidate) => candidate.role === 'assistant' && sameChat(candidate));
    return matches.length === 1 ? matches[0] : undefined;
  };
  messages.forEach((receipt, index) => {
    if (receipt.role !== 'system') return;
    const event = parseAgentContextEvent(receipt.original_message?.content ?? receipt.content);
    if (event?.type !== 'memories_loaded') return;
    const candidate = candidateFor(event, receipt, index);
    const pendingMatches = pending && !candidate && (
      event.assistant_message_id === pending.taskId
      || (!event.assistant_message_id && event.user_message_id === pending.userMessageId)
    ) && (!event.user_message_id || event.user_message_id === pending.userMessageId)
      && (!receipt.original_message?.chat_id || !pending.chatId || receipt.original_message.chat_id === pending.chatId);
    const targetId = candidate?.id ?? (pendingMatches ? pending!.taskId : undefined);
    if (!targetId) return;
    attachedReceiptIds.add(receipt.id);
    const current = byAssistantId.get(targetId) ?? [];
    for (const memory of event.memories) {
      if (!current.some((existing) => existing.id === memory.id && existing.revision === memory.revision)) current.push(memory);
    }
    byAssistantId.set(targetId, current);
  });
  return { byAssistantId, attachedReceiptIds };
}
