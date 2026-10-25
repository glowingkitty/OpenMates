// Exercise the real metadata cache around an overlapping decrypt and invalidation.
import { beforeEach, describe, expect, it, vi } from 'vitest';
import type { Chat } from '../../types/chat';
const decrypt = vi.hoisted(() => vi.fn());
vi.mock('../cryptoService', () => ({ decryptWithChatKey: decrypt, decryptWithMasterKey: vi.fn() }));
vi.mock('../db', () => ({ chatDB: { setChatKey: vi.fn() } }));
vi.mock('../encryption/ChatKeyManager', () => ({ chatKeyManager: { getKeySync: () => new Uint8Array(32), getKey: vi.fn(), onKeyReady: vi.fn() } }));
vi.mock('../../stores/userProfile', async () => {
  const { writable } = await import('svelte/store');
  return { userProfile: writable({ user_id: 'account-a' }) };
});
import { clearRecentChatWindows, putRecentChatWindow, getRecentChatSelection, getRecentChatRevision, invalidateRecentChatWindow } from '../recentChatWindowCache';
import { invalidateWorkspaceCaches } from '../workspaceCacheLifecycle';
import { userProfile } from '../../stores/userProfile';
import type { Message } from '../../types/chat';
import { chatMetadataCache } from '../chatMetadataCache';
const chat = (title: string, id = 'linked-chat') => ({ chat_id: id, encrypted_title: title } as Chat);

describe('chat metadata cache invalidation', () => {
  beforeEach(() => { vi.resetAllMocks(); chatMetadataCache.clearAll(); clearRecentChatWindows(); userProfile.set({ user_id: 'account-a' } as never); decrypt.mockImplementation(async title => title); });
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

// contract-test: supporting surface=gui.web assertions=chat-navigation.open.local-first-coherent
describe('draft projection refresh and settled replay', () => {
  const admit = () => {
    const selected = { ...chat('cipher'), user_id: 'account-a', encrypted_draft_md: 'private draft ciphertext', encrypted_draft_preview: 'private preview ciphertext' } as Chat;
    expect(putRecentChatWindow('linked-chat', {
      messages: [{ message_id: 'message', chat_id: 'linked-chat', role: 'user', created_at: 1, status: 'synced', content: 'settled history' } as Message],
      compressionCheckpoints: [], hasMoreBefore: false,
      header: { title: 'History title', category: null, icon: null, summary: null, encryptedTitle: 'cipher' },
    }, undefined, undefined, selected)).toBe(true);
  };
  beforeEach(() => { vi.resetAllMocks(); chatMetadataCache.clearAll(); clearRecentChatWindows(); userProfile.set({ user_id: 'account-a' } as never); decrypt.mockImplementation(async title => title); });
  // contract-test: supporting surface=gui.web assertions=chat-navigation.open.local-first-coherent
  it('retires obsolete preview decrypts without losing history or importing draft into selection', async () => {
    admit(); const revision = getRecentChatRevision('linked-chat');
    let release!: (title: string) => void;
    decrypt.mockReturnValueOnce(new Promise(resolve => { release = resolve; }));
    const old = chatMetadataCache.getDecryptedMetadata(chat('Earlier title'));
    await vi.waitFor(() => expect(decrypt).toHaveBeenCalledOnce());
    chatMetadataCache.invalidateDraftProjection('linked-chat');
    expect((await chatMetadataCache.getDecryptedMetadata(chat('Current title')))?.title).toBe('Current title');
    release('Earlier title'); expect(await old).toBeNull();
    expect((await chatMetadataCache.getDecryptedMetadata(chat('Current title')))?.title).toBe('Current title');
    const selected = getRecentChatSelection('linked-chat');
    expect(selected?.window.messages[0].content).toBe('settled history');
    expect(selected?.chat.encrypted_draft_md).toBeNull(); expect(selected?.chat.encrypted_draft_preview).toBeNull();
    expect(getRecentChatRevision('linked-chat')).toBe(revision);
  });
  // contract-test: supporting surface=gui.web assertions=chat-navigation.open.local-first-coherent
  it.each(['unknown', 'header', 'key', 'message', 'workspace', 'account'])('continues revoking cached plaintext for %s changes', kind => {
    admit();
    if (kind === 'workspace') invalidateWorkspaceCaches();
    else if (kind === 'account') userProfile.set({ user_id: 'account-b' } as never);
    else if (kind === 'key' || kind === 'message') invalidateRecentChatWindow('linked-chat', kind);
    else chatMetadataCache.invalidateChat('linked-chat');
    expect(getRecentChatSelection('linked-chat')).toBeNull();
  });
});
