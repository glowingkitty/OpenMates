/** Private navigation metadata; never message bodies, annotations or AI context. */
import { get, writable } from 'svelte/store';
import { authStore } from '../stores/authState';
import { userProfile, updateProfile } from '../stores/userProfile';
import { getApiEndpoint } from '../config/api';
import { decryptWithMasterKey, encryptWithMasterKey } from './encryption/MetadataEncryptor';
import { getWorkspaceCacheEpoch, registerWorkspaceCacheClear } from './workspaceCacheLifecycle';

export type BookmarkMode = 'account' | 'device' | 'transient';
type Bookmarks = Map<string, Set<string>>;
type AccountSnapshot = { owner: string; ciphertext: string | null; bookmarks: Bookmarks };
const SETTINGS_KEY = 'message_bookmarks';
const DEVICE_PREFIX = 'openmates:message-bookmarks:v1:';
export const messageBookmarksStore = writable<{ account: AccountSnapshot | null; localRevision: number }>({ account: null, localRevision: 0 });
const local = new Map<string, Set<string>>();
const queues = new Map<string, Promise<void>>();
let pending: { owner: string; ciphertext: string | null; epoch: number; promise: Promise<void> } | null = null;

function owner(): string | null {
  return get(authStore).isAuthenticated ? get(userProfile).user_id : null;
}
function scopeMatches(account: string, epoch: number): boolean {
  return owner() === account && getWorkspaceCacheEpoch() === epoch;
}
function identity(value: unknown): value is string {
  return typeof value === 'string' && value.length > 0 && value.length <= 256 && [...value].every(char => char.charCodeAt(0) >= 32);
}
function parseSettings(plaintext: string): Record<string, unknown> {
  let value: unknown;
  try { value = JSON.parse(plaintext); } catch { throw new Error('Bookmark settings unavailable'); }
  if (!value || typeof value !== 'object' || Array.isArray(value)) throw new Error('Bookmark settings unavailable');
  return value as Record<string, unknown>;
}
function decode(value: unknown): Bookmarks {
  if (value === undefined) return new Map();
  if (!value || typeof value !== 'object' || Array.isArray(value)) throw new Error('Bookmark settings unavailable');
  const record = value as { version?: unknown; chats?: unknown };
  if (record.version !== 1 || !record.chats || typeof record.chats !== 'object' || Array.isArray(record.chats)) throw new Error('Bookmark settings unavailable');
  const bookmarks: Bookmarks = new Map();
  let count = 0;
  for (const [chat, ids] of Object.entries(record.chats)) {
    if (!identity(chat) || !Array.isArray(ids) || !ids.every(identity)) throw new Error('Bookmark settings unavailable');
    count += ids.length;
    if (count > 10000) throw new Error('Bookmark settings unavailable');
    bookmarks.set(chat, new Set(ids));
  }
  return bookmarks;
}
async function settings(ciphertext: string | null): Promise<Record<string, unknown>> {
  if (!ciphertext) return {};
  const plaintext = await decryptWithMasterKey(ciphertext);
  if (!plaintext) throw new Error('Bookmark settings unavailable');
  return parseSettings(plaintext);
}
function localKey(chatId: string, mode: BookmarkMode): string {
  return `${mode}:${mode === 'transient' ? owner() ?? 'guest' : 'guest'}:${chatId}`;
}
function changed(): void {
  messageBookmarksStore.update(state => ({ ...state, localRevision: state.localRevision + 1 }));
}

export function getMessageBookmarkIds(chatId: string, mode: BookmarkMode): Set<string> {
  if (mode !== 'account') return new Set(local.get(localKey(chatId, mode)) ?? []);
  const snapshot = get(messageBookmarksStore).account;
  return snapshot?.owner === owner() && snapshot.ciphertext === (get(userProfile).encrypted_settings ?? null)
    ? new Set(snapshot.bookmarks.get(chatId) ?? []) : new Set();
}

export async function loadMessageBookmarks(chatId: string, mode: BookmarkMode): Promise<void> {
  if (!identity(chatId)) throw new Error('Bookmark identity unavailable');
  if (mode !== 'account') {
    const key = localKey(chatId, mode);
    if (local.has(key)) return;
    let ids: Set<string> = new Set();
    if (mode === 'device') {
      const raw = localStorage.getItem(DEVICE_PREFIX + chatId);
      if (raw) {
        let value: unknown;
        try { value = JSON.parse(raw); } catch { throw new Error('Bookmark settings unavailable'); }
        if (!Array.isArray(value) || value.length > 10000 || !value.every(identity)) throw new Error('Bookmark settings unavailable');
        ids = new Set(value);
      }
    }
    local.set(key, ids); changed(); return;
  }
  const account = owner(), ciphertext = get(userProfile).encrypted_settings ?? null;
  if (!account) throw new Error('Bookmark account unavailable');
  const epoch = getWorkspaceCacheEpoch();
  const snapshot = get(messageBookmarksStore).account;
  if (snapshot?.owner === account && snapshot.ciphertext === ciphertext) return;
  if (pending?.owner === account && pending.ciphertext === ciphertext && pending.epoch === epoch) return pending.promise;
  const promise = settings(ciphertext).then(value => {
    const bookmarks = decode(value[SETTINGS_KEY]);
    if (!scopeMatches(account, epoch) || (get(userProfile).encrypted_settings ?? null) !== ciphertext) throw new Error('Bookmark scope changed');
    messageBookmarksStore.update(state => ({ ...state, account: { owner: account, ciphertext, bookmarks } }));
  });
  pending = { owner: account, ciphertext, epoch, promise };
  try { await promise; } finally { if (pending?.promise === promise) pending = null; }
}

export function toggleMessageBookmark(chatId: string, messageId: string, mode: BookmarkMode): Promise<void> {
  if (!identity(chatId) || !identity(messageId)) return Promise.reject(new Error('Bookmark identity unavailable'));
  const account = owner(), epoch = getWorkspaceCacheEpoch();
  const key = `${mode}:${account ?? 'guest'}:${epoch}`;
  const operation = (queues.get(key) ?? Promise.resolve()).then(async () => {
    if (getWorkspaceCacheEpoch() !== epoch || owner() !== account) throw new Error('Bookmark scope changed');
    await loadMessageBookmarks(chatId, mode);
    if (getWorkspaceCacheEpoch() !== epoch || owner() !== account) throw new Error('Bookmark scope changed');
    if (mode !== 'account') {
      const ids = getMessageBookmarkIds(chatId, mode);
      if (ids.has(messageId)) ids.delete(messageId); else ids.add(messageId);
      if (ids.size > 10000) throw new Error('Bookmark limit reached');
      if (mode === 'device') localStorage.setItem(DEVICE_PREFIX + chatId, JSON.stringify([...ids]));
      local.set(localKey(chatId, mode), ids); changed(); return;
    }
    if (!account) throw new Error('Bookmark account unavailable');
    const ciphertext = get(userProfile).encrypted_settings ?? null;
    const value = await settings(ciphertext);
    const bookmarks = decode(value[SETTINGS_KEY]);
    const ids = new Set(bookmarks.get(chatId) ?? []);
    if (ids.has(messageId)) ids.delete(messageId); else ids.add(messageId);
    if (ids.size) bookmarks.set(chatId, ids); else bookmarks.delete(chatId);
    if ([...bookmarks.values()].reduce((total, saved) => total + saved.size, 0) > 10000) throw new Error('Bookmark limit reached');
    value[SETTINGS_KEY] = { version: 1, chats: Object.fromEntries([...bookmarks].map(([chat, saved]) => [chat, [...saved]])) };
    const encrypted = await encryptWithMasterKey(JSON.stringify(value));
    if (!encrypted || !scopeMatches(account, epoch) || (get(userProfile).encrypted_settings ?? null) !== ciphertext) throw new Error('Bookmark scope changed');
    const response = await fetch(getApiEndpoint('/v1/settings/encrypted-account'), {
      method: 'POST', credentials: 'include', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ encrypted_settings: encrypted }),
    });
    if (!response.ok) throw new Error('Bookmark save unavailable');
    if (!scopeMatches(account, epoch) || (get(userProfile).encrypted_settings ?? null) !== ciphertext) throw new Error('Bookmark scope changed');
    updateProfile({ encrypted_settings: encrypted });
    messageBookmarksStore.update(state => ({ ...state, account: { owner: account, ciphertext: encrypted, bookmarks } }));
  });
  const settled = operation.catch(() => {});
  queues.set(key, settled);
  void settled.then(() => { if (queues.get(key) === settled) queues.delete(key); });
  return operation;
}

export function clearTransientMessageBookmarks(chatId: string): void {
  if (local.delete(localKey(chatId, 'transient'))) changed();
}

function invalidate(): void {
  const snapshot = get(messageBookmarksStore).account;
  if (snapshot && (snapshot.owner !== owner() || snapshot.ciphertext !== (get(userProfile).encrypted_settings ?? null))) {
    messageBookmarksStore.update(state => ({ ...state, account: null }));
  }
}
userProfile.subscribe(invalidate);
authStore.subscribe(invalidate);
registerWorkspaceCacheClear(() => {
  local.clear(); queues.clear(); pending = null;
  messageBookmarksStore.update(state => ({ account: null, localRevision: state.localRevision + 1 }));
});
