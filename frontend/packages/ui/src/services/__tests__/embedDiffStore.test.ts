import { beforeEach, describe, expect, it, vi } from 'vitest';

vi.mock('../../config/api', () => ({
  storageArchiveFetch: (input: RequestInfo | URL, init?: RequestInit) => globalThis.fetch(input, init), getApiEndpoint: (path: string) => `https://api.test${path}`
}));

vi.mock('../db', () => ({
  chatDB: {
    init: vi.fn(),
    getChat: vi.fn(async () => ({ team_id: 'team-1' })),
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

import { chatDB } from '../db';

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

  // contract-test: direct surface=gui.web assertions=storage.cold.shared-team-authorized,storage.versions.metadata-and-payload
  it('uses the captured Project scope for metadata pagination without looking up a chat', async () => {
    const fetchMock = vi.spyOn(globalThis, 'fetch').mockResolvedValue(Response.json({
      embed_id: 'embed-1', current_version: 80, readonly: true, versions: [], next_cursor: null
    }));
    for (const cursor of [undefined, 49]) {
      await fetchEmbedVersions('embed-1', { projectId: 'project-1', teamId: 'team-7', cursor });
    }
    for (const [url] of fetchMock.mock.calls) {
      const params = new URL(String(url)).searchParams;
      expect(params.get('project_id')).toBe('project-1');
      expect(params.get('team_id')).toBe('team-7');
      expect(params.has('chat_id')).toBe(false);
    }
    expect(chatDB.getChat).not.toHaveBeenCalled();
  });

  // contract-test: direct surface=gui.web assertions=storage.cold.shared-team-authorized,storage.versions.bounded-reconstruction
  it('retains Project scope for bounded and legacy exact reads', async () => {
    const fetchMock = vi.spyOn(globalThis, 'fetch')
      .mockResolvedValueOnce(Response.json({ detail: 'checkpoint needed' }, { status: 409 }))
      .mockResolvedValueOnce(Response.json({ embed_id: 'embed-1', version_number: 1, current_version: 2, content: 'old', readonly: true }));
    const result = await fetchEmbedVersionContent('embed-1', 1, { projectId: 'project-1', teamId: 'team-7' });
    expect(result.content).toBe('old');
    expect(fetchMock).toHaveBeenCalledTimes(2);
    for (const [url] of fetchMock.mock.calls) {
      const params = new URL(String(url)).searchParams;
      expect(params.get('project_id')).toBe('project-1');
      expect(params.get('team_id')).toBe('team-7');
      expect(params.has('chat_id')).toBe(false);
    }
    expect(chatDB.getChat).not.toHaveBeenCalled();
  });

  // contract-test: direct surface=gui.web assertions=storage.cold.shared-team-authorized,storage.versions.bounded-reconstruction
  it('publishes a reconstructed checkpoint under the same Project authorization', async () => {
    const rows = Array.from({ length: 33 }, (_, index) => ({
      version_number: index + 1, created_at: index, has_snapshot: true, has_patch: false, encrypted_snapshot: 'enc:content'
    }));
    const fetchMock = vi.spyOn(globalThis, 'fetch').mockImplementation(async (_url, init) =>
      init?.method === 'POST' ? Response.json({}) : Response.json({
        embed_id: 'embed-1', version_number: 33, current_version: 34, rows, readonly: false
      }));
    await fetchEmbedVersionContent('embed-1', 33, { projectId: 'project-1', teamId: 'team-7' });
    await vi.waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(2));
    const body = JSON.parse(String(fetchMock.mock.calls[1][1]?.body));
    expect(body).toEqual({ encrypted_snapshot: 'enc:content', expected_revision: 34,
      operation_id: 'snapshot.v33', project_id: 'project-1', team_id: 'team-7' });
  });

  // contract-test: direct surface=gui.web assertions=storage.cold.shared-team-authorized
  it('rejects ambiguous or unbound Team scopes before requesting history', async () => {
    const fetchMock = vi.spyOn(globalThis, 'fetch');
    await expect(fetchEmbedVersions('embed-1', { projectId: 'project-1', chatId: 'chat-1' })).rejects.toThrow('either Project or chat');
    await expect(fetchEmbedVersionContent('embed-1', 1, { teamId: 'team-1' })).rejects.toThrow('requires a Project or chat');
    expect(fetchMock).not.toHaveBeenCalled();
  });

  // contract-test: direct surface=gui.web assertions=storage.cold.shared-team-authorized
  it('sends the selected Team chat context for each version metadata page', async () => {
    const fetchMock = vi.spyOn(globalThis, 'fetch').mockResolvedValue(
      new Response(JSON.stringify({ embed_id: 'embed-1', current_version: 2, readonly: false, versions: [], next_cursor: null }),
        { status: 200, headers: { 'Content-Type': 'application/json' } })
    );
    await fetchEmbedVersions('embed-1', { order: 'desc', limit: 32, chatId: 'chat-1' });
    expect(fetchMock.mock.calls[0][0]).toContain('chat_id=chat-1');
    expect(fetchMock.mock.calls[0][0]).toContain('team_id=team-1');
  });

  // contract-test: direct surface=gui.web assertions=storage.versions.metadata-and-payload
  it('loads complete metadata pages with credentials and no row ciphertext', async () => {
    const fetchMock = vi.spyOn(globalThis, 'fetch').mockResolvedValue(
      new Response(JSON.stringify({
        embed_id: 'embed-1',
        current_version: 2,
        readonly: false,
        versions: [
          { version_number: 1, created_at: 1760000000, has_snapshot: true, has_patch: false },
          { version_number: 2, created_at: 1760000100, has_snapshot: false, has_patch: true }
        ]
      }), { status: 200, headers: { 'Content-Type': 'application/json' } })
    );

    const response = await fetchEmbedVersions('embed-1');

    expect(fetchMock).toHaveBeenCalledWith('https://api.test/v1/embeds/embed-1/versions', {
      credentials: 'include'
    });
    expect(response.versions).toHaveLength(2);
    expect(response.versions[0].encrypted_snapshot).toBeUndefined();
  });

  // contract-test: direct surface=gui.web assertions=storage.versions.metadata-and-payload
  it('follows the server cursor past version 100 without loading ciphertext', async () => {
    const fetchMock = vi.spyOn(globalThis, 'fetch').mockImplementation(async (url) => {
      const cursor = new URL(String(url)).searchParams.get('cursor');
      const first = cursor === null;
      return new Response(JSON.stringify({
        embed_id: 'embed-1', current_version: 101, readonly: false,
        next_cursor: first ? 100 : null,
        versions: first
          ? Array.from({ length: 100 }, (_, index) => ({ version_number: index + 1, created_at: index, has_snapshot: index === 0, has_patch: index > 0 }))
          : [{ version_number: 101, created_at: 101, has_snapshot: false, has_patch: true }]
      }), { status: 200, headers: { 'Content-Type': 'application/json' } });
    });
    const result = await fetchEmbedVersions('embed-1');
    expect(result.versions).toHaveLength(101);
    expect(result.versions[100].version_number).toBe(101);
    expect(fetchMock).toHaveBeenCalledTimes(2);
    expect(String(fetchMock.mock.calls[1][0])).toContain('cursor=100');
  });

  // contract-test: direct surface=gui.web assertions=storage.versions.metadata-and-payload
  it('requests just one newest-first UI page until Show more is selected', async () => {
    const fetchMock = vi.spyOn(globalThis, 'fetch').mockResolvedValue(new Response(JSON.stringify({
      embed_id: 'embed-1', current_version: 1000, readonly: false,
      next_cursor: 969,
      versions: Array.from({ length: 32 }, (_, index) => ({
        version_number: 1000 - index, created_at: index, has_snapshot: index === 8, has_patch: true
      }))
    }), { status: 200, headers: { 'Content-Type': 'application/json' } }));
    const page = await fetchEmbedVersions('embed-1', { order: 'desc', limit: 32 });
    expect(page.versions).toHaveLength(32);
    expect(page.next_cursor).toBe(969);
    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(String(fetchMock.mock.calls[0][0])).toContain('order=desc&limit=32');
  });

  // contract-test: direct surface=gui.web assertions=storage.versions.bounded-reconstruction
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

  // contract-test: direct surface=gui.web assertions=storage.versions.bounded-reconstruction
  it('keeps a long legacy chain readable and proposes a client-encrypted checkpoint', async () => {
    const fetchMock = vi.spyOn(globalThis, 'fetch').mockImplementation(async (url) => {
      const target = String(url);
      if (target.includes('capability=bounded-v1')) return new Response(JSON.stringify({ detail: 'snapshot_required' }), { status: 409 });
      if (target.endsWith('/snapshot')) return new Response(JSON.stringify({ status: 'committed' }), { status: 200 });
      return new Response(JSON.stringify({
        embed_id: 'embed-1', version_number: 33, current_version: 33, readonly: false,
        rows: Array.from({ length: 33 }, (_, index) => ({
          version_number: index + 1,
          encrypted_snapshot: index === 0 ? 'enc:first' : null,
          encrypted_patch: index === 0 ? null : 'enc:@@ -1 +1 @@\n first'
        }))
      }), { status: 200, headers: { 'Content-Type': 'application/json' } });
    });
    await expect(fetchEmbedVersionContent('embed-1', 33)).resolves.toMatchObject({ content: 'first' });
    await vi.waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(3));
    const snapshotCall = fetchMock.mock.calls[2];
    expect(String(snapshotCall[0])).toContain('/snapshot');
    expect(String(snapshotCall[1]?.body)).toContain('"encrypted_snapshot":"enc:first"');
  });

  // contract-test: supporting surface=gui.web assertions=storage.versions.bounded-reconstruction
  it('rejects restore without client-side encrypted restore context', async () => {
    const fetchMock = vi.spyOn(globalThis, 'fetch');

    await expect(restoreEmbedVersion('embed-1', 1)).rejects.toThrow(
      'Embed version restore requires client-side encrypted restore options'
    );
    expect(fetchMock).not.toHaveBeenCalled();
  });

  // contract-test: supporting surface=gui.web assertions=storage.versions.bounded-reconstruction
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
