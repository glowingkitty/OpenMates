import { describe, expect, it } from 'vitest';
import { FastAdmissionJournalGate, isRetainedFastAdmissionSnapshot } from '../fastAdmissionJournal';

const identity = {
  chatId: 'chat-a', messageId: 'message-a', turnId: 'turn-a', requestId: 'context-a',
  committedMessagesVersion: 1,
};

describe('one-frame turn recovery journal', () => {
  // contract-test: supporting surface=gui.web assertions=message-input.send.ownership,chats.message.identity-idempotent
  it('retains the exact journal through early confirmation and incomplete context', () => {
    const gate = new FastAdmissionJournalGate(identity);
    expect(gate.acceptConfirmation({ chat_id: 'chat-a', message_id: 'message-a', new_messages_v: 1 })).toBe(false);
    expect(gate.acceptContextAck({ chat_id: 'chat-a', message_id: 'message-a', turn_id: 'turn-a',
      request_id: 'context-a', phase: 'routing', status: 'accepted' })).toBe(false);
    expect(gate.acceptContextAck({ chat_id: 'chat-a', message_id: 'message-a', turn_id: 'other',
      request_id: 'context-a', phase: 'details', status: 'accepted' })).toBe(false);
    expect(gate.acceptContextAck({ chat_id: 'chat-a', message_id: 'message-a', turn_id: 'turn-a',
      request_id: 'context-a', phase: 'details', status: 'rejected' })).toBe(false);
    expect(gate.acceptContextAck({ chat_id: 'chat-a', message_id: 'message-a', turn_id: 'turn-a',
      request_id: 'context-a', phase: 'details', status: 'duplicate' })).toBe(true);
  });

  // contract-test: supporting surface=gui.web assertions=message-input.send.ownership,chats.message.identity-idempotent
  it('also waits for the authoritative message confirmation after both context phases', () => {
    const gate = new FastAdmissionJournalGate(identity);
    for (const phase of ['routing', 'details']) {
      expect(gate.acceptContextAck({ chat_id: 'chat-a', message_id: 'message-a', turn_id: 'turn-a',
        request_id: 'context-a', phase, status: 'accepted' })).toBe(false);
    }
    expect(gate.acceptConfirmation({ chat_id: 'chat-a', message_id: 'message-a', new_messages_v: 2 })).toBe(false);
    expect(gate.acceptConfirmation({ chat_id: 'chat-a', message_id: 'message-a', new_messages_v: 1 })).toBe(true);
  });

  // contract-test: supporting surface=gui.web assertions=message-input.send.ownership,chats.message.identity-idempotent
  it('recognizes an interrupted admission for exact-ID replay after a crash', () => {
    const snapshot = {
      chat_id: 'chat-a', message_id: 'message-a',
      payload: { chat_id: 'chat-a', message_id: 'message-a',
        inference_request: { chat_id: 'chat-a', client_context_pending: true,
          client_context_request_id: 'context-a' } },
    };
    expect(isRetainedFastAdmissionSnapshot(snapshot, 'chat-a', 'message-a')).toBe(true);
    expect(isRetainedFastAdmissionSnapshot(snapshot, 'chat-b', 'message-a')).toBe(false);
    expect(isRetainedFastAdmissionSnapshot(snapshot, 'chat-a', 'message-b')).toBe(false);
    expect(isRetainedFastAdmissionSnapshot({ ...snapshot,
      payload: { ...snapshot.payload, inference_request: { chat_id: 'chat-a' } },
    }, 'chat-a', 'message-a')).toBe(false);
  });
});
