import { describe, it, expect, beforeEach, vi } from 'vitest';
import { EmbedStore } from '../embedStore';
import * as cryptoService from '../cryptoService';

describe('EmbedStore.getEmbedKey', () => {
  beforeEach(() => {
    vi.restoreAllMocks();
    vi.clearAllMocks();
    (crypto.subtle.digest as any) = vi.fn(async () => new Uint8Array([1, 2, 3, 4]).buffer);
  });

  it('reuses the parent embed key for child embeds', async () => {
    const store = new EmbedStore();

    const expectedKey = new Uint8Array([9, 8, 7, 6]);
    vi.spyOn(cryptoService, 'unwrapEmbedKeyWithMasterKey').mockResolvedValue(expectedKey);

    vi.spyOn(store, 'getRawEntry').mockImplementation(async (contentRef: string) => {
      if (contentRef === 'embed:child-embed') {
        return { parent_embed_id: 'parent-embed', embed_ids: undefined };
      }
      return { parent_embed_id: undefined, embed_ids: undefined };
    });

    vi.spyOn(store, 'getEmbedKeyEntries').mockResolvedValue([
      {
        hashed_embed_id: 'hashed-parent',
        key_type: 'master',
        hashed_chat_id: null,
        encrypted_embed_key: 'wrapped-parent-key',
        hashed_user_id: 'hashed-user',
        created_at: 0
      }
    ]);

    const key1 = await store.getEmbedKey('child-embed', 'hashed-chat');
    expect(key1).toBe(expectedKey);

    const key2 = await store.getEmbedKey('child-embed', 'hashed-chat');
    expect(key2).toBe(expectedKey);

    expect(cryptoService.unwrapEmbedKeyWithMasterKey).toHaveBeenCalledTimes(1);
  });

  it('guards against cycles in parent_embed_id chains', async () => {
    const store = new EmbedStore();

    vi.spyOn(store, 'getRawEntry').mockImplementation(async (contentRef: string) => {
      if (contentRef === 'embed:a') return { parent_embed_id: 'b', embed_ids: undefined };
      if (contentRef === 'embed:b') return { parent_embed_id: 'a', embed_ids: undefined };
      return { parent_embed_id: undefined, embed_ids: undefined };
    });
    vi.spyOn(store, 'getEmbedKeyEntries').mockResolvedValue([]);

    const key = await store.getEmbedKey('a', 'hashed-chat');
    expect(key).toBeNull();
  });
});
