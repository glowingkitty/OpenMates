import { describe, expect, it, vi } from 'vitest';
import type { ChatStateBinding, HiddenChatVaultBinding } from '../chatState/chatStateBinding';
import { RustHiddenChatAdapter, hiddenKeyUpdateFrame, readHiddenChatSalt } from '../chatState/hiddenChatAdapter';
import { createChatStateAdapter, forkSourceFromMessage } from '../chatState/chatStateAdapter';

function storage(initial: Record<string, string> = {}) {
  const values = new Map(Object.entries(initial));
  return { getItem: (key: string) => values.get(key) ?? null, setItem: (key: string, value: string) => void values.set(key, value), values };
}

function vault(overrides: Partial<HiddenChatVaultBinding> = {}): HiddenChatVaultBinding {
  return {
    is_unlocked: () => false,
    remaining_lockout_seconds: () => 0,
    unlock: async () => 1,
    wrap_with_code: async () => 'wrapped',
    wrap: () => 'wrapped',
    unwrap: () => undefined,
    classify: async () => ({ class: 'locked_candidate', chatKey: null }),
    plan_hide: async () => ({ plan: 'needs_unlock' }),
    unhide: async () => ({ encryptedChatKey: 'master-wrapped' }),
    lock: () => undefined,
    free: () => undefined,
    ...overrides,
  };
}

const io = (keys: string[] = []) => ({ now: () => 1_000, salt: () => new Uint8Array(16), storedEncryptedChatKeys: async () => keys, clearAllChatKeys: vi.fn() });

describe('rust core hidden chat adapter', () => {
  // contract-test: supporting surface=gui.web assertions=chats.persistence.client-encrypted
  it('reads the hidden-chat salt exactly like getOrCreateSalt', () => {
    const emailSalt = btoa(String.fromCharCode(...Array.from({ length: 24 }, (_, i) => i)));
    const session = storage(), local = storage({ openmates_email_salt: emailSalt });
    const salt = readHiddenChatSalt(session, local);
    expect(Array.from(salt ?? [])).toEqual(Array.from({ length: 16 }, (_, i) => i));
    expect(session.values.get('hidden_chat_salt')).toBe(btoa(String.fromCharCode(...Array.from({ length: 16 }, (_, i) => i))));
    // The session cache wins afterwards, even if the email salt changes.
    local.setItem('openmates_email_salt', btoa('other-salt-value-xx'));
    expect(Array.from(readHiddenChatSalt(session, local) ?? [])).toEqual(Array.from(salt ?? []));
    expect(readHiddenChatSalt(storage(), storage())).toBeUndefined();
  });

  // contract-test: supporting surface=gui.web assertions=chats.persistence.client-encrypted
  it('maps unlock outcomes to the web service results and only throws for lockout', async () => {
    const unlock = vi.fn(async () => 2);
    const adapter = new RustHiddenChatAdapter(vault({ unlock }), io(['a', 'b']));
    await expect(adapter.unlockHiddenChats('4821', 'fresh')).resolves.toEqual({ success: true, decryptedCount: 2 });
    expect(unlock).toHaveBeenCalledWith('4821', new Uint8Array(16), ['a', 'b'], 'fresh', 1_000);
    const failing = new RustHiddenChatAdapter(vault({ unlock: async () => Promise.reject('Hidden chat code must be 4 to 30 characters.') }), io());
    await expect(failing.unlockHiddenChats('ab')).resolves.toEqual({ success: false, decryptedCount: 0 });
    const locked = new RustHiddenChatAdapter(vault({ unlock: async () => Promise.reject('locked'), wrap_with_code: async () => Promise.reject('locked') }), io());
    await expect(locked.unlockHiddenChats('4821')).rejects.toThrow('Too many failed attempts. Please wait before trying again.');
    await expect(locked.encryptChatKeyWithCode(new Uint8Array(32), '4821')).rejects.toThrow('Too many failed attempts');
    const derivation = new RustHiddenChatAdapter(vault({ wrap_with_code: async () => Promise.reject('crypto') }), io());
    await expect(derivation.encryptChatKeyWithCode(new Uint8Array(32), '4821')).resolves.toBeNull();
  });

  // contract-test: supporting surface=gui.web assertions=sync.client.shared-rust-policy,chats.persistence.client-encrypted
  it('classifies, plans hides, unhides and locks like hiddenChatService', async () => {
    const key = new Uint8Array(32).fill(7);
    const keyIo = io();
    let classified: 'normal' | 'hidden' | 'locked_candidate' = 'normal';
    const adapter = new RustHiddenChatAdapter(vault({
      is_unlocked: () => true,
      classify: async () => ({ class: classified, chatKey: classified === 'locked_candidate' ? null : key }),
      plan_hide: async () => ({ plan: 'hide', encryptedChatKey: 'hidden-wrapped', decryptedChatKey: key }),
    }), keyIo);
    await expect(adapter.tryDecryptChatKey('w')).resolves.toEqual({ chatKey: key, isHidden: false, isHiddenCandidate: false });
    classified = 'hidden';
    await expect(adapter.tryDecryptChatKey('w')).resolves.toEqual({ chatKey: key, isHidden: true, isHiddenCandidate: true });
    classified = 'locked_candidate';
    await expect(adapter.tryDecryptChatKey('w')).resolves.toEqual({ chatKey: null, isHidden: false, isHiddenCandidate: true });
    await expect(adapter.planHide(null, 'w')).resolves.toEqual({ kind: 'hide', encryptedChatKey: 'hidden-wrapped', decryptedChatKey: key });
    await expect(adapter.unhide('hidden-wrapped')).resolves.toBe('master-wrapped');
    adapter.lockHiddenChats();
    expect(keyIo.clearAllChatKeys).toHaveBeenCalledOnce();
    const lockedVault = new RustHiddenChatAdapter(vault(), io());
    expect(lockedVault.encryptChatKeyWithCombinedSecret(key)).toBeNull();
    await expect(lockedVault.unhide('x')).resolves.toBeNull();
  });

  // contract-test: supporting surface=gui.web assertions=sync.client.shared-rust-policy,chats.persistence.client-encrypted
  it('builds the hidden key-rotation frame from falsy-defaulted versions', () => {
    const build = vi.fn(() => '{"chat_id":"c"}');
    expect(hiddenKeyUpdateFrame(build, 'c', 'k', { messages_v: 0, title_v: 3 }, 9)).toEqual({ type: 'encrypted_chat_metadata', payload: { chat_id: 'c' } });
    expect(build).toHaveBeenCalledWith('c', 'k', undefined, 3, undefined, 9);
  });
});

describe('rust core chat state adapter', () => {
  // contract-test: supporting surface=gui.web assertions=sync.client.shared-rust-policy,chats.persistence.client-encrypted
  it('parses binding JSON and turns rejection codes into Errors', async () => {
    const binding = {
      chat_state_pin_frame: () => '{"type":"update_chat","payload":{"chat_id":"c","pinned":true}}',
      chat_state_bookmarks_toggle_device: () => { throw 'Bookmark limit reached'; },
      chat_state_bookmarks_toggle_account: async () => '{"encryptedSettings":"enc","index":{"c":["m"]}}',
      chat_state_fork_select: () => { throw 'Fork point message not found'; },
      chat_state_deletion_decision: () => undefined,
      chat_state_pending_deletions_edit: () => '{"changed":true,"write":null}',
    } as unknown as ChatStateBinding;
    const adapter = createChatStateAdapter(binding);
    expect(adapter.pinFrame('c', true)).toEqual({ type: 'update_chat', payload: { chat_id: 'c', pinned: true } });
    expect(() => adapter.toggleDeviceBookmark(null, 'c', 'm')).toThrow(new Error('Bookmark limit reached'));
    await expect(adapter.toggleAccountBookmark({} as CryptoKey, undefined, 'c', 'm')).resolves.toEqual({ encryptedSettings: 'enc', index: { c: ['m'] } });
    expect(() => adapter.forkSelect([], 'm')).toThrow('Fork point message not found');
    expect(adapter.deletionDecision({})).toBeNull();
    expect(adapter.pendingDeletionEdit(null, 'c', false)).toEqual({ changed: true, write: null });
  });

  // contract-test: supporting surface=gui.web assertions=sync.client.shared-rust-policy,chats.persistence.client-encrypted
  it('stringifies non-string fork content like reencryptMessage', () => {
    expect(forkSourceFromMessage({ message_id: 'm', content: { type: 'doc' } }).content).toBe('{"type":"doc"}');
    expect(forkSourceFromMessage({ message_id: 'm', content: '' }).content).toBeUndefined();
    expect(forkSourceFromMessage({ message_id: 'm', content: 'hi' }).content).toBe('hi');
  });
});
