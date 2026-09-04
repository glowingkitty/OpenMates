/**
 * Tests for send handler classification rules.
 *
 * These keep existing chats with saved history on the append path when users
 * send follow-up messages. Draft state can point at the active chat, but that
 * must not make ActiveChat treat a normal follow-up as a brand-new chat.
 */
import { describe, expect, it, vi } from 'vitest';
import {
  isDraftOnlyChatMissingDurableKey,
  isUnsupportedTeamIncognitoContext,
  shouldAwaitAITaskStart,
  shouldDispatchDraftChatAsNewChat,
} from './sendClassification';

vi.mock('../../../utils/platform', () => ({
  isDesktop: vi.fn(() => true),
}));

vi.mock('../utils', () => ({
  hasActualContent: vi.fn(() => true),
  vibrateMessageField: vi.fn(),
}));

vi.mock('../../../stores/authStore', () => ({
  authStore: readableStore({ isAuthenticated: true }),
}));

vi.mock('../../../stores/demoModeStore', () => ({
  demoMode: readableStore(false),
}));

function readableStore<T>(value: T) {
  return {
    subscribe(run: (current: T) => void) {
      run(value);
      return () => undefined;
    },
  };
}

describe('isDraftOnlyChatMissingDurableKey', () => {
  // contract-test: direct surface=gui.web assertions=message-input.send.ownership,assistant-speech.preference.chat-scoped-default-off
  it('treats an active voice draft with only an in-memory key as a new chat', () => {
    expect(isDraftOnlyChatMissingDurableKey({
      draftChatId: 'chat-1',
      chatIdToUse: 'chat-1',
      existingChat: { messages_v: 0, encrypted_chat_key: null },
    })).toBe(true);
  });

  // contract-test: supporting surface=gui.web assertions=message-input.send.ownership,assistant-speech.preference.chat-scoped-default-off
  it('keeps a draft with a wrapped key on the existing-chat path', () => {
    expect(isDraftOnlyChatMissingDurableKey({
      draftChatId: 'chat-1',
      chatIdToUse: 'chat-1',
      existingChat: { messages_v: 0, encrypted_chat_key: 'wrapped-chat-key' },
    })).toBe(false);
  });
});

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

  // contract-test: direct surface=gui.web assertions=message-input.send.ownership,assistant-speech.preference.chat-scoped-default-off
  it('dispatches newChat when a voice draft is already the active chat', () => {
    expect(shouldDispatchDraftChatAsNewChat({
      currentChatId: 'chat-1',
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

describe('shouldAwaitAITaskStart', () => {
  // contract-test: direct surface=gui.web assertions=teams.chat.encrypted-until-invoked
  it('does not show AI processing for an ordinary authenticated Team message', () => {
    expect(shouldAwaitAITaskStart({
      authenticated: true,
      teamId: 'team-1',
      invokesTeamAI: false,
    })).toBe(false);
  });

  // contract-test: supporting surface=gui.web assertions=teams.chat.encrypted-until-invoked
  it.each([
    { authenticated: true, teamId: null, invokesTeamAI: false },
    { authenticated: true, teamId: 'team-1', invokesTeamAI: true },
  ])('waits for an AI task when the send can invoke AI', (args) => {
    expect(shouldAwaitAITaskStart(args)).toBe(true);
  });

  // contract-test: supporting surface=gui.web assertions=teams.chat.encrypted-until-invoked
  it('does not wait for an AI task for anonymous sends', () => {
    expect(shouldAwaitAITaskStart({
      authenticated: false,
      teamId: null,
      invokesTeamAI: false,
    })).toBe(false);
  });
});

describe('createKeyboardHandlingExtension', () => {
  // contract-test: direct surface=gui.web assertions=message-input.send.ownership,message-input.drafts.preview-persistence
  it('lets plain Enter insert a newline instead of dispatching send events', async () => {
    const { createKeyboardHandlingExtension } = await import('./sendHandlers');
    const fakeEditor = {
      view: {
        dom: { dispatchEvent: vi.fn() },
        state: {
          selection: {
            $anchor: { pos: 1 },
            $head: { pos: 1 },
          },
        },
      },
    };
    const extension = createKeyboardHandlingExtension();
    const shortcuts = extension.config.addKeyboardShortcuts?.call({
      editor: fakeEditor,
    });

    const handled = shortcuts?.Enter({ editor: fakeEditor });

    expect(handled).toBe(false);
    expect(fakeEditor.view.dom.dispatchEvent).not.toHaveBeenCalled();
  });
});
