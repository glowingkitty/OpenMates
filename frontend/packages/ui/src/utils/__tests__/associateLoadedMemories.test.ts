import { describe, expect, it } from 'vitest';
import { associateLoadedMemories, type MemoryAssociationMessage } from '../associateLoadedMemories';

const memory = { id: 'app:diagrams:type-flowchart', title: 'Diagram Design: Flowchart', source: 'app' as const,
  app_id: 'diagrams', revision: 'b'.repeat(64), body: 'Use clear direction.' };
const user = (id: string): MemoryAssociationMessage => ({ id, role: 'user', original_message: { chat_id: 'chat-one' } });
const assistant = (id: string, userId: string): MemoryAssociationMessage => ({ id, role: 'assistant', original_message: { user_message_id: userId, chat_id: 'chat-one' } });
const receipt = (id: string, ids: Record<string, string> = {}): MemoryAssociationMessage => ({ id, role: 'system', original_message: {
  chat_id: 'chat-one', content: JSON.stringify({ type: 'memories_loaded', set_key: 'a'.repeat(64), count: 1, memories: [memory], ...ids }),
} });

describe('associateLoadedMemories', () => {
  // contract-test: supporting surface=gui.web assertions=app-memories.transparency.loaded-set,chat-processing-feedback.completed-processing-summary
  it('attaches late and out-of-order receipts by exact assistant ID', () => {
    const result = associateLoadedMemories([receipt('r2', { assistant_message_id: 'a2', user_message_id: 'u2' }), user('u1'),
      assistant('a1', 'u1'), user('u2'), assistant('a2', 'u2')]);
    expect(result.byAssistantId.get('a2')).toEqual([memory]);
    expect(result.byAssistantId.has('a1')).toBe(false);
    expect(result.attachedReceiptIds.has('r2')).toBe(true);
  });

  // contract-test: supporting surface=gui.web assertions=app-memories.transparency.loaded-set
  it('keeps conflicting identities, wrong chats, and ambiguous continuations orphaned', () => {
    const messages = [user('u1'), assistant('a1', 'u1'), assistant('a1-cont', 'u1'),
      receipt('conflict', { assistant_message_id: 'a1', user_message_id: 'u2' }),
      receipt('ambiguous', { user_message_id: 'u1' }),
      { ...receipt('other-chat', { assistant_message_id: 'a1' }), original_message: { ...receipt('other-chat').original_message, chat_id: 'chat-two' } }];
    const result = associateLoadedMemories(messages);
    expect(result.attachedReceiptIds.size).toBe(0);
  });

  // contract-test: supporting surface=gui.web assertions=app-memories.transparency.loaded-set
  it('attaches legacy receipts only to one assistant inside the same user turn', () => {
    const result = associateLoadedMemories([user('u1'), receipt('early'), assistant('a1', 'u1'),
      user('u2'), assistant('a2', 'u2'), assistant('a2-cont', 'u2'), receipt('ambiguous'),
      user('u3'), receipt('orphan')]);
    expect(result.byAssistantId.get('a1')).toEqual([memory]);
    expect([...result.attachedReceiptIds]).toEqual(['early']);
  });

  // contract-test: supporting surface=gui.web assertions=app-memories.transparency.loaded-set
  it('attaches an identified receipt to a pending assistant before its row exists', () => {
    const result = associateLoadedMemories([user('u1'), receipt('pending', { assistant_message_id: 'task-1', user_message_id: 'u1' })],
      { taskId: 'task-1', userMessageId: 'u1', chatId: 'chat-one' });
    expect(result.byAssistantId.get('task-1')).toEqual([memory]);
    expect(result.attachedReceiptIds.has('pending')).toBe(true);
  });

  // contract-test: supporting surface=gui.web assertions=app-memories.transparency.loaded-set
  it('does not attach a pending task when the receipt names another user turn', () => {
    const result = associateLoadedMemories([user('u1'), receipt('contradictory', { assistant_message_id: 'task-1', user_message_id: 'u2' })],
      { taskId: 'task-1', userMessageId: 'u1', chatId: 'chat-one' });
    expect(result.byAssistantId.size).toBe(0);
    expect(result.attachedReceiptIds.size).toBe(0);
  });
});
