// frontend/packages/ui/src/services/__tests__/embedStoreImageRef.test.ts
// Regression coverage for child image-result ref registration.
// Search result children retain their own renderer identity even when their
// server storage envelope temporarily uses the parent app-skill type.
// Architecture: docs/architecture/messaging/message-parsing.md

import { beforeEach, describe, expect, it, vi } from 'vitest';
import { EmbedStore } from '../embedStore';

describe('EmbedStore image child ref indexing', () => {
  beforeEach(() => {
    vi.restoreAllMocks();
    vi.clearAllMocks();
  });

  // contract-test: supporting surface=gui.web assertions=web-search.surface-parity,chats.surface.semantic-parity
  it('indexes decrypted image children by their child type instead of the parent search skill', async () => {
    const store = new EmbedStore();
    const registerEmbedRef = vi.spyOn(store, 'registerEmbedRef');

    await store.putEncrypted(
      'embed:image-child-1',
      {
        embed_id: 'image-child-1',
        encrypted_content: '<encrypted>',
        status: 'finished',
      },
      'app_skill_use',
      JSON.stringify({
        type: 'image_result',
        app_id: 'images',
        skill_id: 'search',
        embed_ref: 'example.com-image-A1b',
        image_url: 'https://example.com/image.jpg',
      }),
    );

    expect(registerEmbedRef).toHaveBeenCalledWith(
      'example.com-image-A1b',
      'image-child-1',
      'images',
      'image_result',
      'image_result',
    );
    expect(store.resolveTypeByRef('example.com-image-A1b')).toBe('images-image-result');
    expect(store.resolveSkillIdByRef('example.com-image-A1b')).toBe('image_result');
  });
});
