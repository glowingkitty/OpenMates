/**
 * Rust-core adapter for `hiddenChatService` (flag-on only). Same public
 * results as the TypeScript service: the combined secret never leaves the
 * WASM vault, wrappers stay byte-compatible (PBKDF2-SHA256 over
 * base64(master || code), email salt[0..16], 100k; IV || AES-GCM), and the
 * 3-failure / 30 s lockout counts attempts exactly like the web service.
 * IO (IndexedDB chat list, key cache, socket sync, events) is injected.
 */
import { bindingCode, type ChatStateFrame, type HiddenChatVaultBinding } from './chatStateBinding';

const HIDDEN_CHAT_SALT_KEY = 'hidden_chat_salt';
const EMAIL_SALT_KEY = 'openmates_email_salt';
const LOCKOUT_MESSAGE = 'Too many failed attempts. Please wait before trying again.';

interface StorageLike { getItem(key: string): string | null; setItem(key: string, value: string): void }

function base64ToBytes(value: string): Uint8Array {
  const binary = atob(value);
  const bytes = new Uint8Array(binary.length);
  for (let index = 0; index < binary.length; index++) bytes[index] = binary.charCodeAt(index);
  return bytes;
}

function bytesToBase64(bytes: Uint8Array): string {
  let binary = '';
  for (const byte of bytes) binary += String.fromCharCode(byte);
  return btoa(binary);
}

/**
 * `getOrCreateSalt`: the cached hidden-chat salt, else the first 16 bytes of
 * the account email salt (cached for the session). `undefined` when no salt
 * exists, which the vault counts as a derivation failure like the web code.
 */
export function readHiddenChatSalt(session: StorageLike, local: StorageLike): Uint8Array | undefined {
  const cached = session.getItem(HIDDEN_CHAT_SALT_KEY);
  if (cached) {
    try {
      return base64ToBytes(cached);
    } catch (error) {
      // Same as the web service: an unparseable cache falls through to the email salt.
      console.error('[HiddenChatAdapter] Error parsing stored salt:', error);
    }
  }
  const emailSalt = session.getItem(EMAIL_SALT_KEY) || local.getItem(EMAIL_SALT_KEY);
  if (!emailSalt) return undefined;
  const salt = base64ToBytes(emailSalt).slice(0, 16);
  session.setItem(HIDDEN_CHAT_SALT_KEY, bytesToBase64(salt));
  return salt;
}

export interface HiddenChatIO {
  now(): number;
  salt(): Uint8Array | undefined;
  /** Every stored `encrypted_chat_key` (chatDB.getAllChats). */
  storedEncryptedChatKeys(): Promise<string[]>;
  /** chatDB.clearAllChatKeys on lock. */
  clearAllChatKeys(): void;
}

export interface TryDecryptResult { chatKey: Uint8Array | null; isHidden: boolean; isHiddenCandidate: boolean }

export type HideOutcome =
  | { kind: 'needs_unlock' }
  | { kind: 'already_hidden'; decryptedChatKey: Uint8Array | null }
  | { kind: 'missing_key' }
  | { kind: 'hide'; encryptedChatKey: string; decryptedChatKey: Uint8Array | null };

export class RustHiddenChatAdapter {
  constructor(private readonly vault: HiddenChatVaultBinding, private readonly io: HiddenChatIO) {}

  isUnlocked(): boolean {
    return this.vault.is_unlocked();
  }

  getRemainingLockoutTime(): number {
    return this.vault.remaining_lockout_seconds(this.io.now());
  }

  /** `unlockHiddenChats`: throws only for the lockout, like the web service. */
  async unlockHiddenChats(code: string, verifiedEncryptedChatKey?: string): Promise<{ success: boolean; decryptedCount: number }> {
    const keys = await this.io.storedEncryptedChatKeys();
    try {
      const decryptedCount = await this.vault.unlock(code, this.io.salt(), keys, verifiedEncryptedChatKey, this.io.now());
      return { success: true, decryptedCount };
    } catch (reason) {
      if (bindingCode(reason) === 'locked') throw new Error(LOCKOUT_MESSAGE);
      return { success: false, decryptedCount: 0 };
    }
  }

  /** `encryptChatKeyWithCode`: `null` on failure, throws during lockout. */
  async encryptChatKeyWithCode(chatKey: Uint8Array, code: string): Promise<string | null> {
    try {
      return await this.vault.wrap_with_code(chatKey, code, this.io.salt(), this.io.now());
    } catch (reason) {
      if (bindingCode(reason) === 'locked') throw new Error(LOCKOUT_MESSAGE);
      return null;
    }
  }

  /** `encryptChatKeyWithCombinedSecret`: `null` while locked. */
  encryptChatKeyWithCombinedSecret(chatKey: Uint8Array): string | null {
    if (!this.vault.is_unlocked()) return null;
    return this.vault.wrap(chatKey);
  }

  decryptChatKeyWithCombinedSecret(encryptedChatKey: string): Uint8Array | null {
    return this.vault.unwrap(encryptedChatKey) ?? null;
  }

  async tryDecryptChatKey(encryptedChatKey: string): Promise<TryDecryptResult> {
    const result = await this.vault.classify(encryptedChatKey);
    if (result.class === 'normal') return { chatKey: result.chatKey, isHidden: false, isHiddenCandidate: false };
    if (result.class === 'hidden') return { chatKey: result.chatKey, isHidden: true, isHiddenCandidate: true };
    return { chatKey: null, isHidden: false, isHiddenCandidate: true };
  }

  /**
   * `hideChat` decision. The caller persists `encryptedChatKey`, sends
   * `keyUpdateFrame`, caches `decryptedChatKey` and shows the same notices.
   */
  async planHide(cachedChatKey: Uint8Array | null, encryptedChatKey: string | undefined): Promise<HideOutcome> {
    const plan = await this.vault.plan_hide(cachedChatKey ?? undefined, encryptedChatKey);
    if (plan.plan === 'hide') return { kind: 'hide', encryptedChatKey: plan.encryptedChatKey, decryptedChatKey: plan.decryptedChatKey };
    if (plan.plan === 'already_hidden') return { kind: 'already_hidden', decryptedChatKey: null };
    return { kind: plan.plan };
  }

  /** `unhideChat` re-wrap with the master key; `null` when it cannot open. */
  async unhide(encryptedChatKey: string): Promise<string | null> {
    if (!this.vault.is_unlocked()) return null;
    try {
      return (await this.vault.unhide(encryptedChatKey)).encryptedChatKey;
    } catch (reason) {
      console.error('[HiddenChatAdapter] Error unhiding chat:', bindingCode(reason));
      return null;
    }
  }

  lockHiddenChats(): void {
    this.vault.lock();
    this.io.clearAllChatKeys();
  }
}

export interface ChatVersions { messages_v?: number; title_v?: number; last_edited_overall_timestamp?: number }

/** `sendUpdateChatKeyImpl` frame (`encrypted_chat_metadata`). */
export function hiddenKeyUpdateFrame(
  build: (chatId: string, key: string, messagesV: number | undefined, titleV: number | undefined, edited: number | undefined, nowSeconds: number) => string,
  chatId: string,
  encryptedChatKey: string,
  chat: ChatVersions,
  nowSeconds: number,
): ChatStateFrame {
  const payload = JSON.parse(build(chatId, encryptedChatKey, chat.messages_v || undefined, chat.title_v || undefined, chat.last_edited_overall_timestamp || undefined, nowSeconds));
  return { type: 'encrypted_chat_metadata', payload };
}
