// Tests for new-message cards: a reply seen in its open chat is never announced later,
// and a card for the chat now on screen is dismissed (voice-call product videos).
import { describe, expect, it, vi } from 'vitest';
import { writable } from 'svelte/store';

vi.mock('../../stores/userProfile', () => ({ userProfile: writable({ user_id: 'owner-1' }) }));

import { announceChatMessageOnce } from '../chatMessageNotificationReceipt';
import { chatNotificationIdsForVisibleChat } from '../chatNotificationVisibility';

describe('chat message notifications', () => {
  // contract-test: supporting surface=gui.web assertions=notifications.delivery.idempotent,video-call.chat.transcripts
  it('never announces a reply that was first seen in its open chat', () => {
    expect(announceChatMessageOnce('call-chat', 'reply-1', true)).toBe(false);
    // Later, another chat is open and sync delivers the same reply again.
    expect(announceChatMessageOnce('call-chat', 'reply-1', false)).toBe(false);
  });

  // contract-test: supporting surface=gui.web assertions=notifications.delivery.idempotent,video-call.chat.transcripts
  it('announces a background reply once', () => {
    expect(announceChatMessageOnce('other-chat', 'reply-2', false)).toBe(true);
    expect(announceChatMessageOnce('other-chat', 'reply-2', false)).toBe(false);
  });

  // contract-test: supporting surface=gui.web assertions=notifications.delivery.idempotent,video-call.chat.transcripts
  it('selects only live chat cards of the visible chat for dismissal', () => {
    const notifications = [
      { id: 'a', type: 'chat_message', chatId: 'open' },
      { id: 'b', type: 'chat_message', chatId: 'open', isExiting: true },
      { id: 'c', type: 'chat_message', chatId: 'elsewhere' },
      { id: 'd', type: 'info', chatId: 'open' },
    ];
    expect(chatNotificationIdsForVisibleChat(notifications, 'open')).toEqual(['a']);
    expect(chatNotificationIdsForVisibleChat(notifications, null)).toEqual([]);
  });
});
