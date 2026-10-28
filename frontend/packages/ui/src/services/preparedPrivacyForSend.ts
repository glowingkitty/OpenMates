/** Client-decrypted Personal context, retained only in this document's RAM. */
import { get } from 'svelte/store';
import { authStore } from '../stores/authState';
import { userProfile } from '../stores/userProfile';
import { personalDataStore } from '../stores/personalDataStore';
import { getWorkspaceCacheIdentity } from './workspaceQueryCache';
import { registerWorkspaceCacheClear } from './workspaceCacheLifecycle';
import { getSessionId } from '../utils/sessionId';
import { getWebSocketRoutingId } from '../utils/websocketRoutingId';
import { webSocketService } from './websocketService';
import { decryptWithMasterKey } from './cryptoService';
import { getApiEndpoint, apiEndpoints } from '../config/api';
import { detectPII, replacePIIWithPlaceholders, createPIIMappingsForStorage,
  type PIIDetectionOptions } from '../components/enter_message/services/piiDetectionService';

interface MemorySnapshot {
  encrypted_settings: string | null;
  memories: Array<{ id: string; app_id: string; item_type: string; encrypted_item_json: string | null }>;
}
export interface PreparedPrivacy {
  enabled: boolean;
  enhancedEnabled: boolean;
  options: PIIDetectionOptions;
  settings: Record<string, unknown>;
  memories: Array<{ id: string; app_id: string; item_type: string; data: Record<string, unknown> }>;
}
interface Bundle { scope: string; generation: string; touchedAt: number; privacy: PreparedPrivacy }
export interface PrivacySendReceipt {
  turnId: string; generation: string | null; receiptId: string | null;
  privacy: PreparedPrivacy; scope: string; checkedAt: number; mutation: number; authEpoch: number; connection: object | null;
}
const exclusions = new WeakMap<object, Set<string>>();
export function registerPersonalPrivacyExclusions(message: object, originals: Set<string>): void { exclusions.set(message, originals); }

let bundle: Bundle | null = null;
let expiryTimer: ReturnType<typeof setTimeout> | null = null;
let requestSequence = 0;
let capabilities = new Set<string>();
let socketEpoch = 0;
let mutationEpoch = 0;
let authRejectionEpoch = 0;
let prepareStarted = false;
let warmRequested = false;
let preparing: Promise<void> | null = null;
const IDLE_MS = 2 * 60 * 60 * 1000;

export function invalidatePreparedPrivacy(): void {
  if (expiryTimer !== null) clearTimeout(expiryTimer);
  expiryTimer = null; bundle = null; mutationEpoch += 1;
}
function retainBundle(entry: Bundle | null): void {
  if (expiryTimer !== null) clearTimeout(expiryTimer);
  expiryTimer = null; bundle = entry;
  if (entry) expiryTimer = setTimeout(() => {
    if (bundle === entry) invalidatePreparedPrivacy();
  }, IDLE_MS);
}
registerWorkspaceCacheClear(invalidatePreparedPrivacy);
let installed = false;
function installMutationObservers(): void {
  if (installed) return;
  installed = true;
  // Lazy installation avoids the aggregate store / chat sender import cycle.
  authStore.subscribe(state => { if (!state.isAuthenticated) invalidatePreparedPrivacy(); });
  // Storage reloads publish new arrays/objects even when policy is unchanged.
  // Compare detection inputs, retaining entry order because overlapping matches
  // may depend on it. Labels and storage timestamps do not affect detection.
  let entriesRevision: string | undefined;
  personalDataStore.subscribe(entries => {
    const revision = JSON.stringify(entries.map(entry => [entry.id, entry.enabled,
      entry.textToHide, entry.replaceWith, Object.values(entry.addressLines ?? {})]));
    if (entriesRevision !== revision) { entriesRevision = revision; invalidatePreparedPrivacy(); }
  });
  let settingsRevision: string | undefined;
  personalDataStore.settings.subscribe(settings => {
    const revision = JSON.stringify([settings.masterEnabled, settings.enhancedEnabled,
      Object.entries(settings.categories).sort(([a], [b]) => a.localeCompare(b))]);
    if (settingsRevision !== revision) { settingsRevision = revision; invalidatePreparedPrivacy(); }
  });
  let profileRevision: string | undefined;
  userProfile.subscribe(profile => {
    const revision = JSON.stringify([profile.user_id, profile.encrypted_settings]);
    if (profileRevision !== revision) { profileRevision = revision; invalidatePreparedPrivacy(); }
  });
}
webSocketService.addEventListener('close', () => {
  socketEpoch += 1; capabilities.clear(); prepareStarted = false; invalidatePreparedPrivacy();
});
webSocketService.addEventListener('open', () => {
  socketEpoch += 1; capabilities.clear(); prepareStarted = false; invalidatePreparedPrivacy();
});
webSocketService.on('server_capabilities', (payload: { capabilities?: string[] }) => {
  capabilities = new Set(payload?.capabilities ?? []);
  if (warmRequested) warmPersonalPrivacyForSend();
});
if (typeof window !== 'undefined') {
  window.addEventListener('appSettingsMemoriesSyncReady', event => {
    if ((event as CustomEvent<{ privacy_snapshot_unchanged?: boolean }>).detail?.privacy_snapshot_unchanged !== true) {
      invalidatePreparedPrivacy();
    }
  });
}

function scope(): string | null {
  const workspace = getWorkspaceCacheIdentity();
  return get(authStore).isAuthenticated && workspace
    ? JSON.stringify([workspace, getSessionId(), getWebSocketRoutingId(), socketEpoch]) : null;
}

/** Decrypt the actual snapshot, including legacy account Memory documents. */
export async function compilePersonalPrivacy(snapshot: MemorySnapshot): Promise<PreparedPrivacy> {
  if (!snapshot || !Array.isArray(snapshot.memories) ||
    (snapshot.encrypted_settings !== null && typeof snapshot.encrypted_settings !== 'string')) {
    throw new Error('Personal privacy snapshot is invalid');
  }
  const parse = async (ciphertext: string): Promise<Record<string, unknown>> => {
    const plaintext = await decryptWithMasterKey(ciphertext);
    if (!plaintext) throw new Error('Personal privacy decryption failed');
    const data: unknown = JSON.parse(plaintext);
    if (!data || typeof data !== 'object' || Array.isArray(data)) throw new Error('Personal privacy entry is invalid');
    return data as Record<string, unknown>;
  };
  const [settings, memories] = await Promise.all([
    snapshot.encrypted_settings ? parse(snapshot.encrypted_settings) : Promise.resolve({}),
    Promise.all(snapshot.memories.map(async row => {
      if (!row.encrypted_item_json) throw new Error('Personal privacy snapshot is missing encrypted row content');
      return { id: row.id, app_id: row.app_id, item_type: row.item_type, data: await parse(row.encrypted_item_json) };
    })),
  ]);
  const preferences = memories.find(row => row.app_id === 'privacy' && row.item_type === 'pii_detection_settings')?.data;
  const categories = preferences?.categories as Record<string, boolean> | undefined;
  return {
    enabled: preferences?.masterEnabled !== false,
    enhancedEnabled: preferences?.enhancedEnabled !== false,
    options: {
      disabledCategories: new Set(Object.entries(categories ?? {}).filter(([, enabled]) => enabled === false).map(([key]) => key)),
      personalDataEntries: memories.filter(row => row.app_id === 'privacy' && row.item_type === 'personal_data_entry').flatMap(row => {
        const data = row.data;
        if (data.enabled === false || typeof data.textToHide !== 'string' || typeof data.replaceWith !== 'string') return [];
        return [{ id: row.id, textToHide: data.textToHide, replaceWith: data.replaceWith,
          additionalTexts: Object.values((data.addressLines ?? {}) as Record<string, unknown>).filter((value): value is string => typeof value === 'string') }];
      }),
    }, settings, memories,
  };
}

async function requestSnapshot(purpose: 'prepare' | 'send', turnId: string | null, knownGeneration?: string): Promise<Record<string, unknown>> {
  const requestId = crypto.randomUUID();
  return new Promise((resolve, reject) => {
    const finish = (error?: Error, payload?: Record<string, unknown>) => {
      clearTimeout(timer);
      webSocketService.off('personal_send_context_snapshot_result', handler);
      webSocketService.removeEventListener('close', closed);
      if (error) reject(error); else resolve(payload!);
    };
    const handler = (payload: Record<string, unknown>) => {
      if (payload?.request_id !== requestId) return;
      if (payload.success !== true) return finish(new Error('Personal privacy freshness check failed'));
      finish(undefined, payload);
    };
    const closed = () => finish(new Error('Personal privacy connection changed'));
    const timer = setTimeout(() => finish(new Error('Personal privacy freshness check timed out')), 10_000);
    webSocketService.on('personal_send_context_snapshot_result', handler);
    webSocketService.addEventListener('close', closed);
    void webSocketService.sendMessage('personal_send_context_snapshot', {
      request_id: requestId, purpose, turn_id: turnId,
      ...(knownGeneration ? { known_generation: knownGeneration } : {}),
    }).catch(() => finish(new Error('Personal privacy freshness request could not be sent')));
  });
}

/** First-party session fallback always fetches the full encrypted snapshot. */
async function fullSnapshot(): Promise<MemorySnapshot> {
  const owner = scope();
  // Import only at the request boundary; aggregate auth actions also import chat
  // senders, so a static import here would create a startup store cycle.
  const { serializeAuthSessionRead, checkAuth } = await import('../stores/authStore');
  const signal = AbortSignal.timeout(10_000);
  const response = await serializeAuthSessionRead(() => {
    if (!owner || scope() !== owner) throw new Error('Personal privacy full snapshot owner changed');
    return fetch(getApiEndpoint(apiEndpoints.auth.session), {
      method: 'POST', credentials: 'include', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ session_id: getSessionId(), include_personal_memories: true }), signal,
    });
  }, signal);
  if (response.status === 401) {
    if (scope() === owner) {
      // Fence already prepared receipts before awaiting the coalesced recovery.
      authRejectionEpoch += 1;
      invalidatePreparedPrivacy();
      try { await checkAuth(undefined, true); }
      catch (error) { console.warn('[PreparedPrivacy] Session recovery unavailable', error); }
    }
    // Recovery never resumes or retransmits the rejected user turn.
    throw new Error('Personal privacy session expired before send');
  }
  if (!response.ok) throw new Error('Personal privacy full snapshot unavailable');
  const result = await response.json();
  if (result.success !== true || !result.personal_memories || result.user?.id !== get(userProfile).user_id) {
    throw new Error('Personal privacy full snapshot owner unavailable');
  }
  return result.personal_memories;
}

export function warmPersonalPrivacyForSend(): void {
  warmRequested = true;
  installMutationObservers();
  if (bundle?.scope === scope() && Date.now() - bundle.touchedAt < IDLE_MS) retainBundle({ ...bundle, touchedAt: Date.now() });
  if (!scope() || preparing || prepareStarted || !capabilities.has('personal_send_context_snapshot_v2')) return;
  prepareStarted = true;
  const owner = scope(), mutation = mutationEpoch, sequence = ++requestSequence;
  preparing = (async () => {
    const result = await requestSnapshot('prepare', null);
    const privacy = await compilePersonalPrivacy(result.personal_memories as MemorySnapshot);
    if (sequence === requestSequence && scope() === owner && mutation === mutationEpoch && typeof result.privacy_generation === 'string') {
      retainBundle({ scope: owner!, generation: result.privacy_generation, touchedAt: Date.now(), privacy });
    }
  })().catch(() => { if (sequence === requestSequence) invalidatePreparedPrivacy(); }).finally(() => { preparing = null; });
}

/** Every Send checks fresh server authority before any filtered text leaves. */
export async function freshPersonalPrivacyForSend(turnId: string): Promise<PrivacySendReceipt> {
  installMutationObservers();
  const owner = scope();
  if (!owner) throw new Error('Personal privacy owner unavailable');
  const writesSucceeded = await personalDataStore.waitForPrivacyMutations();
  if (scope() !== owner) throw new Error('Personal privacy owner changed while saving preferences');
  const mutation = mutationEpoch;
  // A still-pending focus warmup is optional; Send can request a full snapshot.
  const cached = writesSucceeded && bundle?.scope === owner && Date.now() - bundle.touchedAt < IDLE_MS ? bundle : null;
  const sequence = ++requestSequence;
  if (cached) retainBundle({ ...cached, touchedAt: Date.now() });
  const result = capabilities.has('personal_send_context_snapshot_v2')
    ? await requestSnapshot('send', turnId, cached?.generation) : null;
  const generation = typeof result?.privacy_generation === 'string' ? result.privacy_generation : null;
  if (result && (result.turn_id !== turnId || typeof result.receipt_id !== 'string')) throw new Error('Personal privacy receipt does not match this turn');
  if (result?.unchanged === true && (!cached || !generation || generation !== cached.generation || result.personal_memories !== undefined)) {
    throw new Error('Personal privacy unchanged response has no matching prepared snapshot');
  }
  const privacy = result?.unchanged === true ? cached!.privacy
    : await compilePersonalPrivacy(result ? result.personal_memories as MemorySnapshot : await fullSnapshot());
  // An interrupted write is reconciled against the fresh encrypted authority.
  // Never silently replace a displayed local policy with the old server policy.
  if (!writesSucceeded) {
    const local = get(personalDataStore.settings);
    const disabled = Object.entries(local.categories).filter(([, enabled]) => !enabled).map(([key]) => key).sort();
    const entries = get(personalDataStore.enabledEntries).map(entry => ({
      id: entry.id, textToHide: entry.textToHide, replaceWith: entry.replaceWith,
      additionalTexts: Object.values(entry.addressLines ?? {}).filter(Boolean).sort(),
    })).sort((a, b) => a.id.localeCompare(b.id));
    const verifiedEntries = (privacy.options.personalDataEntries ?? []).map(entry => ({
      id: entry.id, textToHide: entry.textToHide, replaceWith: entry.replaceWith,
      additionalTexts: [...(entry.additionalTexts ?? [])].filter(Boolean).sort(),
    })).sort((a, b) => a.id.localeCompare(b.id));
    if (local.masterEnabled !== privacy.enabled || local.enhancedEnabled !== privacy.enhancedEnabled || JSON.stringify(disabled) !== JSON.stringify([...(privacy.options.disabledCategories ?? [])].sort())
      || JSON.stringify(entries) !== JSON.stringify(verifiedEntries)) {
      throw new Error('Personal privacy changes are not yet confirmed by the server; retry after saving them');
    }
    personalDataStore.acknowledgePrivacyPersistence();
  }
  if (scope() !== owner || mutation !== mutationEpoch || personalDataStore.hasPendingPrivacyMutations()) throw new Error('Personal privacy scope changed during freshness check');
  if (sequence === requestSequence) retainBundle(generation ? { scope: owner, generation, privacy, touchedAt: Date.now() } : null);
  return { scope: owner, turnId, generation, privacy, receiptId: (result?.receipt_id as string | undefined) ?? null, checkedAt: Date.now(), mutation, authEpoch: authRejectionEpoch, connection: webSocketService.getConnectionForSend() };
}

export function filterWithFreshPersonalPrivacy(text: string, receipt: PrivacySendReceipt, message?: object) {
  if (receipt.authEpoch !== authRejectionEpoch || scope() !== receipt.scope || receipt.mutation !== mutationEpoch || personalDataStore.hasPendingPrivacyMutations()) throw new Error('Personal privacy owner or preferences changed before filtering');
  // Embed references are protocol identifiers, not user text. Their UUIDs can
  // otherwise match phone patterns and corrupt a valid upload reference.
  const references: Array<{ token: string; value: string }> = [];
  const uuid = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
  const protect = (value: string): string => {
    let token = `__OMREFERENCE_${references.length}__`;
    while (text.includes(token)) token += '_X';
    references.push({ token, value });
    return token;
  };
  const safe = text.replace(/```json\n([\s\S]*?)\n```/g, (block, json: string) => {
    let reference: Record<string, unknown>;
    try { reference = JSON.parse(json); } catch { return block; }
    // Camera provenance has a closed protocol shape. Preserve only validated
    // identifiers and its numeric timestamp; adjacent prose and JSON notes
    // still pass through the user's fresh privacy preferences below.
    if (reference && reference.type === 'image' &&
      Object.keys(reference).length === 6 &&
      typeof reference.embed_id === 'string' && uuid.test(reference.embed_id) &&
      typeof reference.source_frame_id === 'string' && uuid.test(reference.source_frame_id) &&
      typeof reference.source_call_id === 'string' && /^[A-Za-z0-9_-]{1,128}$/.test(reference.source_call_id) &&
      (reference.source === 'camera' || reference.source === 'screen') &&
      typeof reference.captured_at === 'number' && Number.isFinite(reference.captured_at) && reference.captured_at > 0) {
      return protect(block);
    }
    // Validate the JSON but protect only valid reference values. A reference
    // key must never exempt user notes or other JSON strings from privacy.
    const masked = json.replace(/("(?:embed_id|embed_ids)"\s*:\s*)("(?:\\.|[^"\\])*"|\[[\s\S]*?\])/g,
      (field, prefix: string, raw: string) => {
        let value: unknown;
        try { value = JSON.parse(raw); } catch { return field; }
        if (typeof value === 'string' && uuid.test(value)) return prefix + JSON.stringify(protect(value));
        if (Array.isArray(value) && value.every(item => typeof item === 'string')) {
          return prefix + raw.replace(/"(?:\\.|[^"\\])*"/g, literal => {
            const item: unknown = JSON.parse(literal);
            return typeof item === 'string' && uuid.test(item) ? JSON.stringify(protect(item)) : literal;
          });
        }
        return field;
      });
    return block.replace(json, masked);
  });
  const protectedRanges = references.map(({ token }) => ({ start: safe.indexOf(token), end: safe.indexOf(token) + token.length }));
  const excluded = message ? exclusions.get(message) : undefined;
  const matches = receipt.privacy.enabled ? detectPII(safe, receipt.privacy.options).filter(match => !excluded?.has(match.match)
    && !protectedRanges.some(range => match.startIndex < range.end && match.endIndex > range.start)) : [];
  const existing = (message as { pii_mappings?: Array<{ placeholder: string; original: string }> } | undefined)?.pii_mappings ?? [];
  const occupied = new Map(existing.map(mapping => [mapping.placeholder, mapping.original]));
  for (const match of matches) {
    const originalPlaceholder = match.placeholder;
    let index = 2;
    while (occupied.has(match.placeholder) && occupied.get(match.placeholder) !== match.match) {
      match.placeholder = /_\d+(?=[_\]])/.test(originalPlaceholder)
        ? originalPlaceholder.replace(/_\d+(?=[_\]])/, `_${index++}`)
        : originalPlaceholder.replace(/\]$/, `_${index++}]`);
      if (match.placeholder === originalPlaceholder) throw new Error('Personal privacy placeholder collision');
    }
    occupied.set(match.placeholder, match.match);
  }
  let content = matches.length ? replacePIIWithPlaceholders(safe, matches) : safe;
  references.forEach(({ token, value }) => { content = content.replace(token, value); });
  return { content, mappings: createPIIMappingsForStorage(matches) };
}

/** Receipts are transport proofs, never retained in the durable retry journal. */
export async function attachFreshPrivacyReceipt(frame: Record<string, unknown>, receipt: PrivacySendReceipt, message?: object): Promise<{ expectedConnection: object | null } | undefined> {
  if (receipt.authEpoch !== authRejectionEpoch) throw new Error('Personal privacy session expired before transmission');
  const turnId = frame.turn_id as string;
  let fresh = receipt;
  if (turnId !== receipt.turnId || Date.now() - receipt.checkedAt >= 25_000 || receipt.mutation !== mutationEpoch) {
    fresh = await freshPersonalPrivacyForSend(turnId);
    const inference = frame.inference_request as { message?: { content?: string } };
    const content = inference?.message?.content;
    if (typeof content === 'string' && filterWithFreshPersonalPrivacy(content, fresh, message).content !== content) {
      throw new Error('Personal privacy changed after the encrypted turn was prepared; retry this message');
    }
  }
  if (scope() !== fresh.scope) throw new Error('Personal privacy owner changed before transmission');
  if (fresh.receiptId) {
    frame.privacy_receipt_id = fresh.receiptId;
    frame.privacy_generation = fresh.generation;
    return { expectedConnection: fresh.connection };
  }
}

/** The fresh encrypted directory contributes keys only; Memory bodies remain
 * behind the normal client permission and detail-request flow. */
export function personalPrivacyMetadataKeys(receipt: PrivacySendReceipt): string[] {
  const keys = new Set(receipt.privacy.memories.map(memory => `${memory.app_id}-${memory.item_type}`));
  if (['memory_documents', 'rule_documents'].some(key => Array.isArray(receipt.privacy.settings[key])
    && (receipt.privacy.settings[key] as unknown[]).length > 0)) keys.add('openmates-memories');
  return [...keys];
}
