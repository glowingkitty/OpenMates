// frontend/packages/ui/src/services/__tests__/embedPreviewBackfill.test.ts
// Unit tests for preview metadata backfill write eligibility.
// These assertions protect the owner/shared split without needing IndexedDB,
// WebSocket, or crypto mocks. Fullscreen backfill may be local for any viewer,
// but server sync is only eligible for writable owner copies.

import { describe, expect, it } from 'vitest';
import { canPersistPreviewBackfill, canStorePreviewBackfillLocally } from '../embedPreviewBackfill';

const writableEntry = {
  encrypted_content: 'encrypted-content',
  encrypted_type: 'encrypted-type',
  hashed_chat_id: 'hashed-chat',
  hashed_message_id: 'hashed-message',
  hashed_user_id: 'hashed-user',
};

describe('preview metadata backfill write guard', () => {
  it('allows local persistence for shared/read-only parent entries with decryptable content', () => {
    expect(canStorePreviewBackfillLocally({ ...writableEntry, is_shared: true })).toBe(true);
  });

  it('allows owner/write parent entries with complete encrypted routing metadata', () => {
    expect(canPersistPreviewBackfill(writableEntry)).toBe(true);
  });

  it('blocks shared/read-only parent entries from store_embed backfill sync', () => {
    expect(canPersistPreviewBackfill({ ...writableEntry, is_shared: true })).toBe(false);
  });

  it('blocks incomplete entries so local-only backfill cannot forge server routing metadata', () => {
    expect(canPersistPreviewBackfill({ ...writableEntry, hashed_user_id: undefined })).toBe(false);
    expect(canPersistPreviewBackfill({ ...writableEntry, encrypted_content: undefined })).toBe(false);
    expect(canPersistPreviewBackfill(null)).toBe(false);
  });
});
