/**
 * Tests for send handler classification rules.
 *
 * These keep existing chats with saved history on the append path when users
 * send follow-up messages. Draft state can point at the active chat, but that
 * must not make ActiveChat treat a normal follow-up as a brand-new chat.
 */
import { describe, expect, it } from 'vitest';
import {
  isUnsupportedTeamIncognitoContext,
  shouldDispatchDraftChatAsNewChat,
} from './sendClassification';

describe('shouldDispatchDraftChatAsNewChat', () => {
  // contract-test: supporting surface=gui.web assertions=message-input.send.ownership,chats.message.identity-idempotent
  it('does not dispatch newChat for an active existing chat with prior messages', () => {
    expect(shouldDispatchDraftChatAsNewChat({
      currentChatId: 'chat-1',
      draftChatId: 'chat-1',
      chatIdToUse: 'chat-1',
      existingChat: { messages_v: 4 },
      existingChatHasUsableKey: true,
    })).toBe(false);
  });

  // contract-test: supporting surface=gui.web assertions=message-input.send.ownership,chats.message.identity-idempotent
  it('does not dispatch newChat for an inactive existing chat with prior messages', () => {
    expect(shouldDispatchDraftChatAsNewChat({
      draftChatId: 'chat-1',
      chatIdToUse: 'chat-1',
      existingChat: { messages_v: 4 },
      existingChatHasUsableKey: true,
    })).toBe(false);
  });

  // contract-test: supporting surface=gui.web assertions=message-input.send.ownership,chat-navigation.draft-only.addressable
  it('dispatches newChat for a draft-only shell with a usable key', () => {
    expect(shouldDispatchDraftChatAsNewChat({
      draftChatId: 'chat-1',
      chatIdToUse: 'chat-1',
      existingChat: { messages_v: 0 },
      existingChatHasUsableKey: true,
    })).toBe(true);
  });

  // contract-test: supporting surface=gui.web assertions=message-input.send.ownership,chat-navigation.draft-only.addressable
  it('does not dispatch newChat when the draft chat id does not match', () => {
    expect(shouldDispatchDraftChatAsNewChat({
      draftChatId: 'chat-2',
      chatIdToUse: 'chat-1',
      existingChat: { messages_v: 0 },
      existingChatHasUsableKey: true,
    })).toBe(false);
  });
});

describe('isUnsupportedTeamIncognitoContext', () => {
  // contract-test: direct surface=gui.web assertions=teams.chat.encrypted-until-invoked,message-input.privacy-context
  it('rejects incognito sends while a Team context is active', () => {
    expect(isUnsupportedTeamIncognitoContext('team-1', true)).toBe(true);
  });

  // contract-test: supporting surface=gui.web assertions=teams.chat.encrypted-until-invoked,message-input.privacy-context
  it('allows Team and incognito sends when they are used separately', () => {
    expect(isUnsupportedTeamIncognitoContext('team-1', false)).toBe(false);
    expect(isUnsupportedTeamIncognitoContext(null, true)).toBe(false);
  });
});
