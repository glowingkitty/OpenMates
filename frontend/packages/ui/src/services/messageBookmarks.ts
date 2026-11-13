/** Private navigation metadata; never message bodies, annotations or AI context. */
import { get, writable } from 'svelte/store';
import { authStore } from '../stores/authState';
import { userProfile, updateProfile } from '../stores/userProfile';
import { getApiEndpoint } from '../config/api';
import { getWorkspaceCacheEpoch, registerWorkspaceCacheClear } from './workspaceCacheLifecycle';

// The shared Rust chatState unit decides identities, decoding, the alias-aware toggle and the
// limit, and does the master-key crypto; there is no TypeScript fallback.
export type BookmarkMode = 'account' | 'device' | 'transient';
type Bookmarks = Map<string, Set<string>>;
type AccountSnapshot = { owner: string; ciphertext: string | null; bookmarks: Bookmarks };
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
  if (!(await (await import('./rustCore/chatState/rustBookmarks')).rustBookmarkIdentity(chatId))) throw new Error('Bookmark identity unavailable');
  if (mode !== 'account') {
    const key = localKey(chatId, mode);
    if (local.has(key)) return;
    let ids: Set<string> = new Set();
    ids = mode === 'device'
      ? await (await import('./rustCore/chatState/rustBookmarks')).rustDecodeDeviceBookmarks(localStorage.getItem(DEVICE_PREFIX + chatId))
      : ids;
    // A toggle of this chat may have stored fresher ids while the decode was in flight.
    if (local.has(key)) return;
    local.set(key, ids); changed(); return;
  }
  const account = owner(), ciphertext = get(userProfile).encrypted_settings ?? null;
  if (!account) throw new Error('Bookmark account unavailable');
  const epoch = getWorkspaceCacheEpoch();
  const snapshot = get(messageBookmarksStore).account;
  if (snapshot?.owner === account && snapshot.ciphertext === ciphertext) return;
  if (pending?.owner === account && pending.ciphertext === ciphertext && pending.epoch === epoch) return pending.promise;
  const apply = (bookmarks: Bookmarks): void => {
    if (!scopeMatches(account, epoch) || (get(userProfile).encrypted_settings ?? null) !== ciphertext) throw new Error('Bookmark scope changed');
    messageBookmarksStore.update(state => ({ ...state, account: { owner: account, ciphertext, bookmarks } }));
  };
  const promise = import('./rustCore/chatState/rustBookmarks').then(rust => rust.rustReadAccountBookmarks(ciphertext)).then(apply);
  pending = { owner: account, ciphertext, epoch, promise };
  try { await promise; } finally { if (pending?.promise === promise) pending = null; }
}

export function toggleMessageBookmark(chatId: string, messageId: string, mode: BookmarkMode, legacyIds: readonly string[] = []): Promise<void> {
  const account = owner(), epoch = getWorkspaceCacheEpoch();
  const key = `${mode}:${account ?? 'guest'}:${epoch}`;
  const operation = (queues.get(key) ?? Promise.resolve()).then(async () => {
    if (getWorkspaceCacheEpoch() !== epoch || owner() !== account) throw new Error('Bookmark scope changed');
    await loadMessageBookmarks(chatId, mode);
    if (getWorkspaceCacheEpoch() !== epoch || owner() !== account) throw new Error('Bookmark scope changed');
    if (mode !== 'account') {
      const toggled = await (await import('./rustCore/chatState/rustBookmarks')).rustToggleLocalBookmark(getMessageBookmarkIds(chatId, mode), chatId, messageId, legacyIds);
      if (getWorkspaceCacheEpoch() !== epoch || owner() !== account) throw new Error('Bookmark scope changed');
      if (mode === 'device') localStorage.setItem(DEVICE_PREFIX + chatId, toggled.stored);
      local.set(localKey(chatId, mode), toggled.ids); changed(); return;
    }
    if (!account) throw new Error('Bookmark account unavailable');
    const ciphertext = get(userProfile).encrypted_settings ?? null;
    const { encrypted, bookmarks } = await (await import('./rustCore/chatState/rustBookmarks')).rustToggleAccountBookmark(ciphertext, chatId, messageId, legacyIds);
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
