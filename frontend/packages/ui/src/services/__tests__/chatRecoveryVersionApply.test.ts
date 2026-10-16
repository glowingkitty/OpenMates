import { describe, expect, it } from 'vitest';
import type { Chat } from '../../types/chat';
import { chatAfterRecoveredReply } from '../chatRecoveryVersionApply';

const baseline = {
  chat_id: 'chat-a', encrypted_title: null, messages_v: 2, title_v: 0,
  last_edited_overall_timestamp: 10, unread_count: 0, created_at: 1, updated_at: 10,
} as Chat;

describe('recovered reply version apply', () => {
  // contract-test: supporting surface=gui.web assertions=chats.completion.lease-fenced,chats.message.identity-idempotent
  it('keeps a newer local chat and metadata while the barrier uses the exact predecessor ACK', () => {
    const newer = { ...baseline, messages_v: 8, title_v: 4, encrypted_title: 'newer', updated_at: 80 };
    expect(chatAfterRecoveredReply(newer, baseline, 3, 30)).toEqual(newer);
  });

  // contract-test: supporting surface=gui.web assertions=chats.completion.lease-fenced
  it('applies a newer committed version without clobbering unrelated current fields', () => {
    const current = { ...baseline, title_v: 4, encrypted_title: 'current' };
    expect(chatAfterRecoveredReply(current, baseline, 3, 30)).toMatchObject({
      messages_v: 3, title_v: 4, encrypted_title: 'current',
      last_edited_overall_timestamp: 30, updated_at: 30,
    });
  });
});
