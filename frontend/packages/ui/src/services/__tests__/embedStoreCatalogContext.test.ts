// contract-test-file: supporting surface=gui.web assertions=web-search.surface-parity,chats.persistence.client-encrypted
import { describe, it, expect, beforeEach, vi } from 'vitest';
import { encode } from '@toon-format/toon';
import { EmbedStore } from '../embedStore';

const persisted = vi.hoisted(() => new Map<string, unknown>());
vi.mock('../db', () => ({
  chatDB: {
    getTransaction: vi.fn(async () => {
      const completeListeners: Array<() => void> = [];
      const transaction: {
        oncomplete?: () => void;
        addEventListener: (event: string, listener: () => void) => void;
        objectStore: () => { put: (entry: { contentRef: string }) => { onsuccess?: () => void } };
      } = {
        addEventListener: (_event, listener) => completeListeners.push(listener),
        objectStore: () => ({
          put: (entry) => {
            persisted.set(entry.contentRef, { ...entry });
            const request: { onsuccess?: () => void } = {};
            queueMicrotask(() => {
              request.onsuccess?.();
              completeListeners.forEach((listener) => listener());
              transaction.oncomplete?.();
            });
            return request;
          },
        }),
      };
      return transaction;
    }),
  },
}));
vi.mock('../cryptoService', () => ({
  encryptWithMasterKey: vi.fn(), decryptWithMasterKey: vi.fn(),
  unwrapEmbedKeyWithMasterKey: vi.fn(), unwrapEmbedKeyWithChatKey: vi.fn(),
  encryptWithEmbedKey: vi.fn(), decryptWithEmbedKey: vi.fn(),
}));
vi.mock('../encryption/ChatKeyManager', () => ({ chatKeyManager: {} }));

describe('EmbedStore catalog context', () => {
  beforeEach(() => {
    vi.restoreAllMocks();
    vi.clearAllMocks();
    persisted.clear();
  });

  // contract-test: supporting surface=gui.web assertions=web-search.surface-parity,chats.persistence.client-encrypted
  it('keeps canonical catalog fields through a single encrypted refresh without decryption', async () => {
    const store = new EmbedStore();
    const getEmbedKey = vi.spyOn(store, 'getEmbedKey');

    await store.putEncrypted(
      'embed:catalog-single',
      {
        embed_id: 'catalog-single',
        encrypted_content: '<encrypted>',
        app_id: 'web',
        skill_id: 'search',
      },
      'app_skill_use',
      undefined,
      undefined,
      { skipMetadataExtraction: true },
    );

    await expect(store.getRawEntry('embed:catalog-single')).resolves.toMatchObject({
      app_id: 'web',
      skill_id: 'search',
    });
    expect(persisted.get('embed:catalog-single')).toMatchObject({ app_id: 'web', skill_id: 'search' });
    expect(getEmbedKey).not.toHaveBeenCalled();
  });

  // contract-test: supporting surface=gui.web assertions=web-search.surface-parity,chats.persistence.client-encrypted
  it('reports encrypted content presence without exposing ciphertext in raw metadata', async () => {
    const store = new EmbedStore();
    await store.putEncrypted(
      'embed:catalog-sealed',
      { embed_id: 'catalog-sealed', encrypted_content: '<ciphertext>' },
      'app_skill_use', undefined, undefined, { skipMetadataExtraction: true },
    );
    await store.putEncrypted(
      'embed:catalog-unsealed',
      { embed_id: 'catalog-unsealed' },
      'app_skill_use', undefined, undefined, { skipMetadataExtraction: true },
    );

    const sealed = await store.getRawEntry('embed:catalog-sealed');
    const unsealed = await store.getRawEntry('embed:catalog-unsealed');
    expect(sealed?.has_encrypted_content).toBe(true);
    expect(unsealed?.has_encrypted_content).toBe(false);
    expect(sealed).not.toHaveProperty('encrypted_content');

    store.setInMemoryOnly('embed:catalog-legacy', { encrypted_content: '<ciphertext>' });
    const legacy = await store.getRawEntry('embed:catalog-legacy');
    expect(legacy?.has_encrypted_content).toBe(true);
    expect(legacy).not.toHaveProperty('encrypted_content');
  });

  // contract-test: supporting surface=gui.web assertions=web-search.surface-parity,chats.persistence.client-encrypted
  it('keeps explicit extracted catalog fields ahead of canonical fields', async () => {
    const store = new EmbedStore();
    await store.putEncrypted(
      'embed:catalog-explicit',
      {
        embed_id: 'catalog-explicit',
        encrypted_content: '<encrypted>',
        app_id: 'web',
        skill_id: 'search',
      },
      'app_skill_use',
      undefined,
      { app_id: 'events', skill_id: 'calendar' },
      { skipMetadataExtraction: true },
    );

    await expect(store.getRawEntry('embed:catalog-explicit')).resolves.toMatchObject({
      app_id: 'events',
      skill_id: 'calendar',
    });
  });

  // contract-test: supporting surface=gui.web assertions=web-search.surface-parity,chats.persistence.client-encrypted
  it('keeps canonical catalog fields in an encrypted batch without decryption', async () => {
    const store = new EmbedStore();
    const getEmbedKey = vi.spyOn(store, 'getEmbedKey');
    await store.putEncryptedBatch([{
      contentRef: 'embed:catalog-batch',
      data: {
        embed_id: 'catalog-batch',
        encrypted_content: '<encrypted>',
        app_id: 'web',
        skill_id: 'search',
      },
      type: 'app_skill_use',
    }]);

    await expect(store.getRawEntry('embed:catalog-batch')).resolves.toMatchObject({
      app_id: 'web',
      skill_id: 'search',
    });
    expect(persisted.get('embed:catalog-batch')).toMatchObject({ app_id: 'web', skill_id: 'search' });
    expect(getEmbedKey).not.toHaveBeenCalled();
  });

  // contract-test: supporting surface=gui.web assertions=web-search.surface-parity,chats.persistence.client-encrypted
  it('reads catalog context from locally decrypted JSON and TOON content', async () => {
    const store = new EmbedStore();
    const get = vi.spyOn(store, 'get');
    get.mockResolvedValueOnce({ content: JSON.stringify({ app_id: 'web', skill_id: 'search' }) });
    await expect(store.getCatalogContext('embed:json')).resolves.toEqual({
      app_id: 'web', skill_id: 'search',
    });
    get.mockResolvedValueOnce({ content: encode({ app_id: 'web', skill_id: 'search' }) });
    await expect(store.getCatalogContext('embed:toon')).resolves.toEqual({
      app_id: 'web', skill_id: 'search',
    });
  });

  // contract-test: supporting surface=gui.web assertions=web-search.surface-parity,chats.persistence.client-encrypted
  it('distinguishes absent or unreadable content from decoded non-catalog content', async () => {
    const store = new EmbedStore();
    const get = vi.spyOn(store, 'get');
    get.mockResolvedValueOnce(undefined)
      .mockResolvedValueOnce({ _decryptionPending: true, content: '{"app_id":"web"}' })
      .mockResolvedValueOnce({ _decryptionFailed: true, content: '{"app_id":"web"}' })
      .mockResolvedValueOnce({ content: '<encrypted>' })
      .mockResolvedValueOnce({ content: JSON.stringify({ title: 'Unrelated' }) })
      .mockResolvedValueOnce({ content: JSON.stringify({ app_id: 'web' }) });

    await expect(store.getCatalogContext('embed:absent')).resolves.toBeUndefined();
    await expect(store.getCatalogContext('embed:pending')).resolves.toBeUndefined();
    await expect(store.getCatalogContext('embed:failed')).resolves.toBeUndefined();
    await expect(store.getCatalogContext('embed:invalid')).resolves.toBeUndefined();
    await expect(store.getCatalogContext('embed:noncatalog')).resolves.toEqual({});
    await expect(store.getCatalogContext('embed:partial')).resolves.toEqual({ app_id: 'web' });
  });
});
