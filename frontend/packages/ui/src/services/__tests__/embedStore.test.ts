import { describe, it, expect, beforeEach, vi } from 'vitest';
import { EmbedStore } from '../embedStore';
import * as cryptoService from '../cryptoService';
import type { EmbedStoreEntry } from '../../message_parsing/types';

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

describe('EmbedStore uploaded file search metadata', () => {
  beforeEach(() => {
    vi.restoreAllMocks();
    vi.clearAllMocks();
  });

  it('can derive a code filename from encrypted local embed content without file_path', async () => {
    const store = new EmbedStore();
    const embedKey = new Uint8Array([1, 2, 3, 4]);
    vi.spyOn(store, 'getEmbedKey').mockResolvedValue(embedKey);
    vi.spyOn(cryptoService, 'decryptWithEmbedKey').mockResolvedValue(
      JSON.stringify({ filename: 'example.ts', language: 'typescript' }),
    );

    const entry: EmbedStoreEntry = {
      contentRef: 'embed:code-file-1',
      type: 'code-code',
      createdAt: 1,
      updatedAt: 1,
      embed_id: 'code-file-1',
      encrypted_content: '<encrypted>',
      hashed_chat_id: 'hashed-chat',
    };

    const names = await (store as unknown as {
      getSearchableFileNames(entry: EmbedStoreEntry): Promise<string[]>;
    }).getSearchableFileNames(entry);

    expect(names).toContain('example.ts');
    expect(cryptoService.decryptWithEmbedKey).toHaveBeenCalledWith(
      '<encrypted>',
      embedKey,
    );
  });

  it('keeps decrypted filename searchable when generic metadata exists', async () => {
    const store = new EmbedStore();
    vi.spyOn(store, 'getEmbedKey').mockResolvedValue(new Uint8Array([1, 2, 3, 4]));
    vi.spyOn(cryptoService, 'decryptWithEmbedKey').mockResolvedValue(
      JSON.stringify({ filename: 'upload_to_api_video.sh' }),
    );

    const entry: EmbedStoreEntry = {
      contentRef: 'embed:code-file-1',
      type: 'code-code',
      createdAt: 1,
      updatedAt: 1,
      embed_id: 'code-file-1',
      encrypted_content: '<encrypted>',
      hashed_chat_id: 'hashed-chat',
      metadata: { title: 'Code file' },
    };

    const names = await (store as unknown as {
      getSearchableFileNames(entry: EmbedStoreEntry): Promise<string[]>;
    }).getSearchableFileNames(entry);

    expect(names).not.toContain('Code file');
    expect(names).toContain('upload_to_api_video.sh');
  });

  it('allows encrypted shared embed rows to be inspected for upload filenames', () => {
    const store = new EmbedStore();
    const entry: EmbedStoreEntry = {
      contentRef: 'embed:shared-code-file',
      type: 'app-skill-use',
      createdAt: 1,
      updatedAt: 1,
      embed_id: 'shared-code-file',
      encrypted_content: '<encrypted-content>',
      encrypted_type: '<encrypted-type>',
      hashed_chat_id: 'hashed-chat',
    };

    const hasEvidence = (store as unknown as {
      hasUploadSearchEvidence(entry: EmbedStoreEntry): boolean;
    }).hasUploadSearchEvidence(entry);

    expect(hasEvidence).toBe(true);
  });

  it('does not treat web-search documents as uploaded-file candidates', () => {
    const store = new EmbedStore();
    const entry: EmbedStoreEntry = {
      contentRef: 'embed:web-result-1',
      type: 'docs-doc',
      createdAt: 1,
      updatedAt: 1,
      embed_id: 'web-result-1',
      encrypted_content: '<encrypted>',
      metadata: { title: 'Woher stammt Japans Name? | Blog japanwelt.de' },
    };

    const hasEvidence = (store as unknown as {
      hasUploadSearchEvidence(entry: EmbedStoreEntry): boolean;
    }).hasUploadSearchEvidence(entry);

    expect(hasEvidence).toBe(false);
  });
});

describe('EmbedStore.resolveByRefDeep', () => {
  beforeEach(() => {
    vi.restoreAllMocks();
    vi.clearAllMocks();
  });

  it('repairs video source quote refs that use a YouTube video ID', async () => {
    const store = new EmbedStore();

    vi.spyOn(store as unknown as {
      collectAllRefRepairCandidatesFromCache(): string[];
    }, 'collectAllRefRepairCandidatesFromCache').mockReturnValue([
      'video-embed-id',
    ]);
    vi.spyOn(store as unknown as {
      collectAllRefRepairCandidatesFromIndexedDb(): Promise<string[]>;
    }, 'collectAllRefRepairCandidatesFromIndexedDb').mockResolvedValue([]);
    vi.spyOn(store, 'get').mockResolvedValue({
      contentRef: 'embed:video-embed-id',
      type: 'video',
      status: 'finished',
      content: JSON.stringify({
        video_id: 'vS-gfLhxYDg',
        title: 'Sample YouTube video',
      }),
      embed_id: 'video-embed-id',
    } as Record<string, unknown>);

    await expect(store.resolveByRefDeep('vS-gfLhxYDg')).resolves.toBe(
      'video-embed-id',
    );
    expect(store.resolveByRef('vS-gfLhxYDg')).toBe('video-embed-id');
    expect(store.resolveAppIdByRef('vS-gfLhxYDg')).toBe('videos');
  });
});
