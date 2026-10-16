import { describe, expect, it, vi } from 'vitest';
import { canShareChat } from '../chatSharing';

vi.mock('../../demo_chats/convertToChat', () => ({
  isPublicChat: (chatId: string) => chatId === 'example-public',
}));

describe('chat sharing eligibility', () => {
  // contract-test: supporting surface=gui.web assertions=billing.anonymous.local-only-content
  it('rejects private guest, incognito and anonymous chats including stale authenticated state', () => {
    expect(canShareChat(null, true)).toBe(false);
    expect(canShareChat({ chat_id: 'private' }, false)).toBe(false);
    expect(canShareChat({ chat_id: 'private', is_incognito: true }, true)).toBe(false);
    expect(canShareChat({ chat_id: 'private', is_anonymous: true }, true)).toBe(false);
    expect(canShareChat({ chat_id: 'anonymous-local' }, true)).toBe(false);
    expect(canShareChat({ chat_id: 'private', anonymous_encrypted_chat_key: 'tab-wrapper' }, true)).toBe(false);
  });

  // contract-test: supporting surface=gui.web assertions=public-example-chats.navigation.static-public-link,chat-share-settings.readonly-viewer-controls
  it('preserves static public links, shared recipients and authenticated private sharing', () => {
    expect(canShareChat({ chat_id: 'example-public' }, false)).toBe(true);
    expect(canShareChat({ chat_id: 'shared', is_shared_by_others: true }, false)).toBe(true);
    expect(canShareChat({ chat_id: 'private' }, true)).toBe(true);
    expect(canShareChat({ chat_id: 'anonymous-promoted', is_anonymous: false, encrypted_chat_key: 'account-wrapper' }, true)).toBe(true);
    expect(canShareChat({ chat_id: 'anonymous-promoted', is_shared_by_others: true }, false)).toBe(true);
  });
});
