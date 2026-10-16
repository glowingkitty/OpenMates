// Exercise the real metadata cache around an overlapping decrypt and invalidation.
import { beforeEach, describe, expect, it, vi } from 'vitest';
import type { Chat } from '../../types/chat';
const decrypt = vi.hoisted(() => vi.fn());
vi.mock('../cryptoService', () => ({ decryptWithChatKey: decrypt, decryptWithMasterKey: vi.fn() }));
vi.mock('../db', () => ({ chatDB: { setChatKey: vi.fn() } }));
vi.mock('../encryption/ChatKeyManager', () => ({ chatKeyManager: { getKeySync: () => new Uint8Array(32), getKey: vi.fn(), onKeyReady: vi.fn() } }));
vi.mock('../recentChatWindowCache', () => ({ invalidateRecentChatWindow: vi.fn() }));
import { chatMetadataCache } from '../chatMetadataCache';
const chat = (title: string, id = 'linked-chat') => ({ chat_id: id, encrypted_title: title } as Chat);

describe('chat metadata cache invalidation', () => {
  beforeEach(() => { vi.resetAllMocks(); chatMetadataCache.clearAll(); decrypt.mockImplementation(async title => title); });
  // contract-test: supporting surface=gui.web assertions=projects.links.openmates-only-encrypted
  it.each(['update', 'account reset'])('prevents an old decrypt from returning or caching plaintext after %s', async operation => {
    let release!: (title: string) => void;
    decrypt.mockReturnValueOnce(new Promise(resolve => { release = resolve; }));
    const old = chatMetadataCache.getDecryptedMetadata(chat('Earlier title'));
    await vi.waitFor(() => expect(decrypt).toHaveBeenCalledOnce());
    if (operation === 'update') chatMetadataCache.invalidateChat('linked-chat');
    else chatMetadataCache.clearAll();
    expect((await chatMetadataCache.getDecryptedMetadata(chat('Current title')))?.title).toBe('Current title');
    release('Earlier title'); expect(await old).toBeNull();
    expect((await chatMetadataCache.getDecryptedMetadata(chat('Current title')))?.title).toBe('Current title');
    expect(decrypt).toHaveBeenCalledTimes(2);
  });
  // contract-test: supporting surface=gui.web assertions=projects.links.openmates-only-encrypted
  it('keeps an unrelated chat decrypt usable when one chat changes', async () => {
    let release!: (title: string) => void;
    decrypt.mockReturnValueOnce(new Promise(resolve => { release = resolve; }));
    const other = chatMetadataCache.getDecryptedMetadata(chat('Other chat', 'other'));
    await vi.waitFor(() => expect(decrypt).toHaveBeenCalledOnce());
    chatMetadataCache.invalidateChat('linked-chat'); release('Other chat');
    expect((await other)?.title).toBe('Other chat');
    expect((await chatMetadataCache.getDecryptedMetadata(chat('Other chat', 'other')))?.title).toBe('Other chat');
    expect(decrypt).toHaveBeenCalledOnce();
  });
});
