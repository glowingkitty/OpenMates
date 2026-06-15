import { beforeEach, describe, expect, it, vi } from 'vitest';

vi.mock('../../config/api', () => ({
  getApiEndpoint: (path: string) => `https://api.test${path}`
}));

vi.mock('../db', () => ({
  chatDB: {
    init: vi.fn(),
    db: null
  }
}));

vi.mock('../encryption/MetadataEncryptor', () => ({
  decryptWithEmbedKey: vi.fn(async (value: string) => value.replace(/^enc:/, '')),
  encryptWithEmbedKey: vi.fn(async (value: string) => `enc:${value}`)
}));

vi.mock('../embedStore', () => ({
  embedStore: {
    getEmbedKey: vi.fn(async () => new Uint8Array([1, 2, 3, 4])),
    prepareVersionRestoreUpdate: vi.fn(async () => ({
      updated: true,
      storePayload: {
        embed_id: 'embed-1',
        encrypted_type: 'enc:code',
        encrypted_content: 'enc:restored-toon',
        status: 'finished',
        hashed_chat_id: 'hash-chat',
        hashed_message_id: 'hash-message',
        hashed_user_id: 'hash-user',
        version_number: 3,
        content_hash: 'hash-content',
        is_private: false,
        is_shared: false,
        created_at: 1760000000,
        updated_at: 1760000300
      }
    }))
  }
}));

const senderMocks = vi.hoisted(() => ({
  sendStoreEmbedImpl: vi.fn(),
  sendStoreEmbedDiffImpl: vi.fn()
}));

vi.mock('../chatSyncService', () => ({
  chatSyncService: { webSocketConnected_FOR_SENDERS_ONLY: true }
}));

vi.mock('../chatSyncServiceSenders', () => ({
  sendStoreEmbedImpl: senderMocks.sendStoreEmbedImpl,
  sendStoreEmbedDiffImpl: senderMocks.sendStoreEmbedDiffImpl
}));

import {
  fetchEmbedVersionContent,
  fetchEmbedVersions,
  restoreEmbedVersion
} from '../embedDiffStore';

describe('embedDiffStore REST version helpers', () => {
  beforeEach(() => {
    vi.restoreAllMocks();
    vi.clearAllMocks();
  });

  it('loads version metadata with credentials and encrypted row blobs', async () => {
    const fetchMock = vi.spyOn(globalThis, 'fetch').mockResolvedValue(
      new Response(JSON.stringify({
        embed_id: 'embed-1',
        current_version: 2,
        readonly: false,
        versions: [
          { version_number: 1, created_at: 1760000000, has_snapshot: true, has_patch: false, encrypted_snapshot: 'enc:first' },
          { version_number: 2, created_at: 1760000100, has_snapshot: false, has_patch: true, encrypted_patch: 'enc:@@ -1 +1 @@\n-first\n+second' }
        ]
      }), { status: 200, headers: { 'Content-Type': 'application/json' } })
    );

    const response = await fetchEmbedVersions('embed-1');

    expect(fetchMock).toHaveBeenCalledWith('https://api.test/v1/embeds/embed-1/versions', {
      credentials: 'include'
    });
    expect(response.versions).toHaveLength(2);
    expect(response.versions[0].encrypted_snapshot).toBe('enc:first');
  });

  it('decrypts encrypted rows and reconstructs historical content locally', async () => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(
      new Response(JSON.stringify({
        embed_id: 'embed-1',
        version_number: 2,
        current_version: 2,
        readonly: false,
        rows: [
          { version_number: 1, created_at: 1760000000, has_snapshot: true, has_patch: false, encrypted_snapshot: 'enc:first' },
          { version_number: 2, created_at: 1760000100, has_snapshot: false, has_patch: true, encrypted_patch: 'enc:@@ -1 +1 @@\n-first\n+second' }
        ]
      }), { status: 200, headers: { 'Content-Type': 'application/json' } })
    );

    await expect(fetchEmbedVersionContent('embed-1', 2)).resolves.toMatchObject({
      version_number: 2,
      content: 'second'
    });
  });

  it('rejects restore without client-side encrypted restore context', async () => {
    const fetchMock = vi.spyOn(globalThis, 'fetch');

    await expect(restoreEmbedVersion('embed-1', 1)).rejects.toThrow(
      'Embed version restore requires client-side encrypted restore options'
    );
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it('restores by encrypting the parent update and append-only diff row client-side', async () => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(
      new Response(JSON.stringify({
        embed_id: 'embed-1',
        version_number: 1,
        current_version: 2,
        readonly: false,
        rows: [
          { version_number: 1, created_at: 1760000000, has_snapshot: true, has_patch: false, encrypted_snapshot: 'enc:first' }
        ]
      }), { status: 200, headers: { 'Content-Type': 'application/json' } })
    );

    await expect(restoreEmbedVersion('embed-1', 1, {
      currentVersion: 2,
      currentContent: 'second',
      buildRestoredContent: (content, newVersion) => ({ type: 'code', code: content, version_number: newVersion })
    })).resolves.toMatchObject({
      embed_id: 'embed-1',
      restored_from_version: 1,
      version_number: 3,
      content: 'first'
    });

    expect(senderMocks.sendStoreEmbedImpl).toHaveBeenCalledTimes(1);
    expect(senderMocks.sendStoreEmbedDiffImpl).toHaveBeenCalledWith(
      expect.anything(),
      expect.objectContaining({
        embed_id: 'embed-1',
        version_number: 3,
        encrypted_snapshot: null,
        encrypted_patch: expect.stringContaining('enc:--- v2'),
        hashed_user_id: 'hash-user'
      })
    );
  });
});
