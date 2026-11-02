/**
 * Chat menu usage ranking.
 *
 * Remembers which chat menu actions (right-click menu and fullscreen More menu)
 * a user picks so the most used ones are shown first. Authenticated usage is
 * merged into the client-encrypted `encrypted_settings` account blob (master
 * key encryption; the server only stores ciphertext). Guests keep usage in
 * memory for the current tab only.
 */
import { get, writable } from 'svelte/store';

import { getApiEndpoint } from '../config/api';
import { decryptWithMasterKey, encryptWithMasterKey } from './encryption/MetadataEncryptor';
import { authStore } from '../stores/authStore';
import { updateProfile, userProfile } from '../stores/userProfile';

const SETTINGS_KEY = 'chat_menu_usage';
const ENCRYPTED_ACCOUNT_ENDPOINT = '/v1/settings/encrypted-account';
const SAVE_DEBOUNCE_MS = 4000;
const HALF_LIFE_DAYS = 14;
const MAX_COUNT = 1000;
const MAX_ENTRIES = 50;
const ACTION_ID = /^[a-zA-Z][a-zA-Z0-9_]{0,40}$/;

export interface ChatMenuUsageEntry {
  count: number;
  lastUsedAt: number;
}
export type ChatMenuUsage = Record<string, ChatMenuUsageEntry>;

interface UsageState {
  usage: ChatMenuUsage;
  /** Ciphertext the usage was hydrated from; null = not hydrated from account. */
  hydratedFrom: string | null | undefined;
}

const state = writable<UsageState>({ usage: {}, hydratedFrom: undefined });
let hydrating: Promise<void> | null = null;
let saveTimer: ReturnType<typeof setTimeout> | null = null;
let authWatchStarted = false;

/**
 * Drop usage on sign-out. Registered lazily (not at module scope) so importing
 * this module never touches stores that may still be initialising in an
 * import cycle.
 */
function watchAuth(): void {
  if (authWatchStarted) return;
  authWatchStarted = true;
  authStore.subscribe(auth => {
    if (auth.isAuthenticated) return;
    if (saveTimer) clearTimeout(saveTimer);
    saveTimer = null;
    state.set({ usage: {}, hydratedFrom: undefined });
  });
}

/** Readable usage map for ranking. */
export const chatMenuUsageStore = { subscribe: (run: (value: ChatMenuUsage) => void) => state.subscribe(s => run(s.usage)) };

function normalize(value: unknown): ChatMenuUsage {
  if (!value || typeof value !== 'object' || Array.isArray(value)) return {};
  const record = value as { version?: unknown; actions?: unknown };
  if (record.version !== 1 || !record.actions || typeof record.actions !== 'object') return {};
  const usage: ChatMenuUsage = {};
  for (const [id, entry] of Object.entries(record.actions as Record<string, unknown>).slice(0, MAX_ENTRIES)) {
    if (!ACTION_ID.test(id) || !entry || typeof entry !== 'object') continue;
    const { count, lastUsedAt } = entry as Partial<ChatMenuUsageEntry>;
    if (typeof count !== 'number' || typeof lastUsedAt !== 'number' || count <= 0) continue;
    usage[id] = { count: Math.min(Math.floor(count), MAX_COUNT), lastUsedAt };
  }
  return usage;
}

async function readSettings(ciphertext: string | null): Promise<Record<string, unknown>> {
  if (!ciphertext) return {};
  const plaintext = await decryptWithMasterKey(ciphertext);
  if (!plaintext) throw new Error('Encrypted account settings could not be decrypted');
  const parsed = JSON.parse(plaintext) as unknown;
  return parsed && typeof parsed === 'object' && !Array.isArray(parsed) ? (parsed as Record<string, unknown>) : {};
}

function mergeUsage(base: ChatMenuUsage, local: ChatMenuUsage): ChatMenuUsage {
  const merged: ChatMenuUsage = { ...base };
  for (const [id, entry] of Object.entries(local)) {
    const existing = merged[id];
    merged[id] = existing
      ? { count: Math.max(existing.count, entry.count), lastUsedAt: Math.max(existing.lastUsedAt, entry.lastUsedAt) }
      : entry;
  }
  return merged;
}

/** Load usage from the encrypted account settings once per settings revision. */
export function hydrateChatMenuUsage(): Promise<void> {
  watchAuth();
  if (!get(authStore).isAuthenticated) return Promise.resolve();
  const ciphertext = get(userProfile).encrypted_settings ?? null;
  if (get(state).hydratedFrom === ciphertext) return Promise.resolve();
  if (hydrating) return hydrating;
  hydrating = readSettings(ciphertext)
    .then(settings => {
      const stored = normalize(settings[SETTINGS_KEY]);
      state.update(s => ({ usage: mergeUsage(stored, s.usage), hydratedFrom: ciphertext }));
    })
    .catch(error => {
      console.warn('[ChatMenuUsage] Could not load menu usage from account settings', error);
      state.update(s => ({ ...s, hydratedFrom: ciphertext }));
    })
    .finally(() => { hydrating = null; });
  return hydrating;
}

async function persist(): Promise<void> {
  if (!get(authStore).isAuthenticated) return;
  await hydrateChatMenuUsage();
  const ciphertext = get(userProfile).encrypted_settings ?? null;
  const settings = await readSettings(ciphertext);
  const usage = mergeUsage(normalize(settings[SETTINGS_KEY]), get(state).usage);
  settings[SETTINGS_KEY] = { version: 1, actions: usage };
  const encrypted = await encryptWithMasterKey(JSON.stringify(settings));
  if (!encrypted) throw new Error('Unable to encrypt chat menu usage');
  // Another writer changed the blob while we were encrypting: retry on the next use.
  if ((get(userProfile).encrypted_settings ?? null) !== ciphertext) return;
  const response = await fetch(getApiEndpoint(ENCRYPTED_ACCOUNT_ENDPOINT), {
    method: 'POST',
    credentials: 'include',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ encrypted_settings: encrypted }),
  });
  if (!response.ok) throw new Error(`Chat menu usage save failed with ${response.status}`);
  updateProfile({ encrypted_settings: encrypted });
  state.set({ usage, hydratedFrom: encrypted });
}

/** Record that an action was picked; persists (debounced) for signed-in users. */
export function recordChatMenuUsage(actionId: string, now = Date.now()): void {
  if (!ACTION_ID.test(actionId)) return;
  watchAuth();
  state.update(s => {
    const entry = s.usage[actionId];
    return {
      ...s,
      usage: { ...s.usage, [actionId]: { count: Math.min((entry?.count ?? 0) + 1, MAX_COUNT), lastUsedAt: now } },
    };
  });
  if (!get(authStore).isAuthenticated) return;
  if (saveTimer) clearTimeout(saveTimer);
  saveTimer = setTimeout(() => {
    saveTimer = null;
    persist().catch(error => console.warn('[ChatMenuUsage] Could not save menu usage', error));
  }, SAVE_DEBOUNCE_MS);
}

/** Frecency score: use count decayed by a 14-day half-life since last use. */
export function chatMenuUsageScore(entry: ChatMenuUsageEntry | undefined, now = Date.now()): number {
  if (!entry) return 0;
  const ageDays = Math.max(0, now - entry.lastUsedAt) / 86_400_000;
  return entry.count * Math.pow(0.5, ageDays / HALF_LIFE_DAYS);
}

/**
 * Order items so the most used come first. Items with `pinned: 'end'` (delete,
 * debug) never move up; unused items keep their default relative order.
 */
export function rankChatMenuItems<T extends { usageId: string; pinned?: 'end' }>(
  items: readonly T[],
  usage: ChatMenuUsage,
  now = Date.now(),
): T[] {
  const movable = items.filter(item => item.pinned !== 'end');
  const fixed = items.filter(item => item.pinned === 'end');
  const ranked = movable
    .map((item, index) => ({ item, index, score: chatMenuUsageScore(usage[item.usageId], now) }))
    .sort((a, b) => b.score - a.score || a.index - b.index)
    .map(entry => entry.item);
  return [...ranked, ...fixed];
}
