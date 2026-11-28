/**
 * Thin IndexedDB effects for Rust-scoped opened-history completion receipts.
 * Sealing uses the existing private master CryptoKey. The readwrite CAS shares
 * the transaction with the chat header and the message mutation revision.
 */
import { get } from 'svelte/store';
import { authStore, getLoginSessionGeneration } from '../../stores/authStore';
import { isLoggingOut, forcedLogoutInProgress } from '../../stores/signupState';
import { getActiveTeamContextSnapshot } from '../../stores/teamStore';
import { userProfile } from '../../stores/userProfile';
import { getMasterKey } from '../cryptoKeyStorage';
import { chatDB } from '../db';
import {
  COVERED_CHAT_DATABASE_VERSION, LEGACY_COVERAGE_FIELD, LEGACY_COVERAGE_ROW_LIMIT, LEGACY_MESSAGE_STORE,
  OPENED_HISTORY_STORE, readOpenedHistoryMutation,
} from '../db/openedHistoryStorage';
import type { OpenedHistoryPageWitness } from '../db/openedHistoryStorage';
import { legacyCoverageRow } from './browserMessageCacheIO';
import { getWorkspaceCacheEpoch } from '../workspaceCacheLifecycle';
import { rustWebCrypto } from './crypto/webCryptoClient';
import { persistCall } from './persist/persistUnitClient';
import type { OpenedHistoryCompletion, OpenedHistoryStorageBinding } from './persist/persistProtocol';
import type { OpenedChatStartupScope } from './startupOpenedChats';

export interface OpenedHistoryStoredState {
  readonly revision: string | null;
  readonly completion?: OpenedHistoryCompletion;
  readonly encryptedChatKey?: string;
  readonly legacy?: boolean;
}

async function context(scope: OpenedChatStartupScope, signal: AbortSignal) {
  const owner = get(userProfile).user_id;
  const generation = getLoginSessionGeneration();
  const epoch = getWorkspaceCacheEpoch();
  const database = chatDB.db;
  const crypto = rustWebCrypto();
  if (!owner || !database || !crypto || scope.teamId !== null) return null;
  const legacy = database.version < COVERED_CHAT_DATABASE_VERSION;
  if (!legacy && !database.objectStoreNames.contains(OPENED_HISTORY_STORE)) return null;
  const current = () => {
    signal.throwIfAborted();
    const workspace = getActiveTeamContextSnapshot();
    if (!get(authStore).isAuthenticated || get(isLoggingOut) || get(forcedLogoutInProgress) ||
        get(userProfile).user_id !== owner || getLoginSessionGeneration() !== generation ||
        getWorkspaceCacheEpoch() !== epoch || workspace.teamId !== null || workspace.epoch !== scope.contextEpoch ||
        chatDB.db !== database) throw Error('cancelled');
  };
  current();
  const key = await getMasterKey();
  current();
  return key ? { owner, database, crypto, key, current, legacy } : null;
}

type Snapshot = {
  readonly binding: OpenedHistoryStorageBinding | null;
  readonly ciphertext: string | undefined;
  readonly revision: string | null;
};
type HeaderRow = {
  chat_id?: string; user_id?: string; team_id?: string | null; hashed_team_id?: string | null;
  encrypted_chat_key?: string; key_version?: number; is_anonymous?: boolean;
  chat_visibility?: string | null;
  is_hidden?: boolean; is_hidden_candidate?: boolean; parent_id?: string; is_sub_chat?: boolean;
  [LEGACY_COVERAGE_FIELD]?: string;
};
function bindingFromHeader(header: HeaderRow | undefined, owner: string, chatId: string,
  rowRevision: string | null): OpenedHistoryStorageBinding | null {
  if (!rowRevision || !header || header.chat_id !== chatId || header.user_id && header.user_id !== owner ||
      header.team_id || header.hashed_team_id || header.parent_id || header.is_sub_chat ||
      header.chat_visibility && header.chat_visibility !== 'personal' ||
      header.is_anonymous || header.is_hidden || header.is_hidden_candidate ||
      typeof header.encrypted_chat_key !== 'string' || !header.encrypted_chat_key) return null;
  return { owner, chatId, teamId: null, encryptedChatKey: header.encrypted_chat_key,
    keyVersion: header.key_version ?? null, rowRevision };
}

function afterTransaction(transaction: IDBTransaction, signal: AbortSignal): Promise<void> {
  return new Promise((resolve, reject) => {
    const abort = () => { try { transaction.abort(); } catch { /* Await its native terminal. */ } };
    const finish = () => signal.removeEventListener('abort', abort);
    transaction.addEventListener('abort', () => {
      finish();
      reject(transaction.error ?? Error('cancelled'));
    }, { once: true });
    transaction.addEventListener('complete', () => { finish(); resolve(); }, { once: true });
    signal.addEventListener('abort', abort, { once: true });
    if (signal.aborted) abort();
  });
}

async function snapshot(database: IDBDatabase, ids: readonly string[], owner: string, signal: AbortSignal): Promise<Snapshot[]> {
  const tx = database.transaction(['chats', OPENED_HISTORY_STORE], 'readonly');
  const terminal = afterTransaction(tx, signal);
  const rows = ids.map(id => ({ id, header: tx.objectStore('chats').get(id), mutation: readOpenedHistoryMutation(tx, id) }));
  await terminal;
  return rows.map(({ id, header, mutation }) => {
    const revision = typeof mutation.result?.revision === 'string' ? mutation.result.revision : null;
    const ciphertext = typeof mutation.result?.ciphertext === 'string' ? mutation.result.ciphertext : undefined;
    return { binding: bindingFromHeader(header.result, owner, id, revision), revision, ciphertext };
  });
}

async function legacyHeader(database: IDBDatabase, id: string, signal: AbortSignal): Promise<HeaderRow | undefined> {
  const tx = database.transaction('chats');
  const terminal = afterTransaction(tx, signal);
  const request = tx.objectStore('chats').get(id);
  await terminal;
  return request.result;
}

async function legacyRows(database: IDBDatabase, id: string, signal: AbortSignal): Promise<{
  rows: Record<string, unknown>[]; header: HeaderRow;
} | null> {
  const tx = database.transaction(['chats', LEGACY_MESSAGE_STORE]);
  const terminal = afterTransaction(tx, signal);
  const rows: Record<string, unknown>[] = [];
  let bytes = 0;
  let header: HeaderRow | undefined;
  let exceeded = false;
  const encoder = new TextEncoder();
  const metadataRequest = tx.objectStore('chats').get(id);
  metadataRequest.onsuccess = () => {
    const saved = metadataRequest.result as HeaderRow | undefined;
    const ciphertext = saved?.[LEGACY_COVERAGE_FIELD];
    if (!saved || typeof ciphertext !== 'string' || !ciphertext || ciphertext.length > 4096) return;
    header = saved;
    const request = tx.objectStore(LEGACY_MESSAGE_STORE).index('chat_id_created_at')
      .openCursor(IDBKeyRange.bound([id, -Infinity], [id, Infinity]), 'prev');
    request.onsuccess = () => {
      const cursor = request.result;
      if (!cursor) return;
      const projected = legacyCoverageRow(cursor.value);
      // Bound exact compatibility work per offered chat, without expanding history.
      bytes += encoder.encode(JSON.stringify(projected)).byteLength;
      if (rows.length >= LEGACY_COVERAGE_ROW_LIMIT || bytes > 2 * 1024 * 1024) {
        exceeded = true;
        return;
      }
      rows.push(projected);
      cursor.continue();
    };
  };
  await terminal;
  return !exceeded && header ? { rows, header } : null;
}

async function nextDigest(chatId: string, previous: string | null, rows: Record<string, unknown>[]): Promise<string | null> {
  const proof = await persistCall('startupOpened', { kind: 'coverageDigest', chatId, previous, rows });
  return 'digest' in proof ? proof.digest : null;
}

async function verifyLegacyStorage(ctx: NonNullable<Awaited<ReturnType<typeof context>>>,
  id: string, signal: AbortSignal): Promise<Snapshot> {
  const blank = { binding: null, revision: null, ciphertext: undefined };
  const snapshot = await legacyRows(ctx.database, id, signal);
  ctx.current();
  if (!snapshot) return blank;
  const { rows, header } = snapshot;
  const ciphertext = header[LEGACY_COVERAGE_FIELD];
  if (!bindingFromHeader(header, ctx.owner, id, 'snapshot')) return blank;
  let revision: string | null = null;
  for (let i = 0; i < Math.max(rows.length, 1); i += 20) {
    ctx.current();
    revision = await nextDigest(id, revision, rows.slice(i, i + 20));
    if (!revision) return blank;
  }
  ctx.current();
  return { binding: bindingFromHeader(header, ctx.owner, id, revision), revision, ciphertext };
}

export async function loadOpenedHistoryReceipts(ids: readonly string[], scope: OpenedChatStartupScope,
  signal: AbortSignal): Promise<Map<string, OpenedHistoryStoredState> | null> {
  if (ids.length > 11 || ids.some(id => typeof id !== 'string' || !/^[a-f0-9-]{36}$/.test(id))) return null;
  const ctx = await context(scope, signal);
  if (!ctx) return null;
  let records: Snapshot[];
  if (ctx.legacy) {
    records = [];
    // One bounded old-cache read at a time, only for the authorized cohort.
    for (const id of ids) {
      ctx.current();
      try { records.push(await verifyLegacyStorage(ctx, id, signal)); }
      catch (error) {
        ctx.current();
        if (!(error instanceof Error) && error !== 'protocol') throw error;
        records.push({ binding: null, revision: null, ciphertext: undefined });
      }
    }
  } else {
    records = await snapshot(ctx.database, ids, ctx.owner, signal);
  }
  ctx.current();
  const entries = await Promise.all(records.map(async ({ binding, revision, ciphertext }, index) => {
    const state: OpenedHistoryStoredState = {
      revision, legacy: ctx.legacy, encryptedChatKey: binding?.encryptedChatKey,
    };
    if (!binding || !ciphertext || ciphertext.length > 4096) return [ids[index], state] as const;
    let bytes: Uint8Array | undefined;
    try {
      bytes = await ctx.crypto.call<Uint8Array>('masterDecrypt', ctx.key, ciphertext);
      const receipt = await persistCall('startupOpened', {
        kind: 'coverageReceipt', binding, document: new TextDecoder().decode(bytes),
      });
      if ('messagesVersion' in receipt && 'retainedRows' in receipt) {
        return [ids[index], { ...state, completion: receipt, encryptedChatKey: binding.encryptedChatKey }] as const;
      }
      return [ids[index], state] as const;
    } catch (error) {
      ctx.current();
      if (!(error instanceof Error) && error !== 'protocol') throw error;
      return [ids[index], state] as const;
    } finally {
      bytes?.fill(0);
    }
  }));
  ctx.current();
  return new Map(entries);
}

export async function saveOpenedHistoryReceipt(chatId: string, scope: OpenedChatStartupScope, signal: AbortSignal,
  witness: OpenedHistoryPageWitness, complete: OpenedHistoryCompletion): Promise<void> {
  const ctx = await context(scope, signal);
  if (!ctx) return;
  const binding = ctx.legacy
    ? bindingFromHeader(await legacyHeader(ctx.database, chatId, signal), ctx.owner, chatId, witness.after)
    : (await snapshot(ctx.database, [chatId], ctx.owner, signal))[0].binding;
  ctx.current();
  if (!binding || binding.rowRevision !== witness.after || binding.encryptedChatKey !== witness.encryptedChatKey) return;
  const receipt = await persistCall('startupOpened', { kind: 'coverageReceipt', binding, ...complete });
  ctx.current();
  if (!('document' in receipt)) return;
  const bytes = new TextEncoder().encode(receipt.document);
  let ciphertext: string;
  try { ciphertext = await ctx.crypto.call<string>('masterEncrypt', ctx.key, bytes); }
  finally { bytes.fill(0); }
  ctx.current();
  if (ctx.legacy) {
    const transaction = ctx.database.transaction('chats', 'readwrite');
    const terminal = afterTransaction(transaction, signal);
    const store = transaction.objectStore('chats');
    const request = store.get(chatId);
    request.onsuccess = () => {
      try {
        ctx.current();
        const current = bindingFromHeader(request.result, ctx.owner, chatId, binding.rowRevision);
        if (current?.encryptedChatKey === binding.encryptedChatKey && current.keyVersion === binding.keyVersion) {
          store.put({ ...request.result, [LEGACY_COVERAGE_FIELD]: ciphertext });
        }
      } catch (error) {
        transaction.abort();
        if (!(error instanceof Error)) throw error;
      }
    };
    await terminal;
    ctx.current();
    return;
  }
  const transaction = ctx.database.transaction(['chats', OPENED_HISTORY_STORE], 'readwrite');
  const terminal = afterTransaction(transaction, signal);
  const header = transaction.objectStore('chats').get(chatId);
  const mutation = readOpenedHistoryMutation(transaction, chatId);
  let pending = 2;
  const compareAndWrite = () => {
    if (--pending) return;
    try {
      ctx.current();
      const current = bindingFromHeader(header.result, ctx.owner, chatId, mutation.result?.revision ?? null);
      if (!current || current.rowRevision !== binding.rowRevision ||
          current.encryptedChatKey !== binding.encryptedChatKey || current.keyVersion !== binding.keyVersion) return;
      transaction.objectStore(OPENED_HISTORY_STORE).put({ chatId, revision: current.rowRevision, ciphertext });
    } catch (error) {
      transaction.abort();
      if (!(error instanceof Error)) throw error;
    }
  };
  header.onsuccess = mutation.onsuccess = compareAndWrite;
  await terminal;
  ctx.current();
}
