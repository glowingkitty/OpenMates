import { describe, expect, it } from 'vitest';
import { validSavedPageSelector } from '../protocol';

const chatId = '11111111-1111-4111-8111-111111111111';
const cursor = { chatId, scope: 'a'.repeat(64), createdAt: 100, messageId: 'm-user' };

describe('saved page selector shaping', () => {
  // contract-test: supporting surface=gui.web assertions=sdk.client.thin-platform-boundary,chats.persistence.client-encrypted
  it('accepts a bounded limit and compression flag on cursor and anchor pages', () => {
    expect(validSavedPageSelector({ direction: 'before', cursor }, chatId)).toBe(true);
    expect(validSavedPageSelector({ direction: 'before', cursor, limit: 20, respectCompressionBoundary: false }, chatId)).toBe(true);
    expect(validSavedPageSelector({ direction: 'around', anchorMessageId: 'm-ai', respectCompressionBoundary: false }, chatId)).toBe(true);
  });

  // contract-test: supporting surface=gui.web assertions=sdk.client.thin-platform-boundary,chats.persistence.client-encrypted
  it('rejects out-of-range, mistyped and unknown shaping fields', () => {
    for (const limit of [0, 21, 1.5, '5', null]) expect(validSavedPageSelector({ direction: 'before', cursor, limit }, chatId)).toBe(false);
    expect(validSavedPageSelector({ direction: 'before', cursor, respectCompressionBoundary: 'no' }, chatId)).toBe(false);
    expect(validSavedPageSelector({ direction: 'before', cursor, extra: 1 }, chatId)).toBe(false);
    expect(validSavedPageSelector({ direction: 'latest', limit: 5 }, chatId)).toBe(false);
    expect(validSavedPageSelector({ direction: 'before', cursor: { ...cursor, chatId: '22222222-2222-4222-8222-222222222222' } }, chatId)).toBe(false);
  });
});
