/** Chatless Apps result graphs using the normal encrypted embed store. */
import { getApiEndpoint } from "../config/api";
import { EMBED_CHILD_TYPE_MAP } from "../data/embedRegistry.generated";
import { get } from "svelte/store";
import { userProfile } from "../stores/userProfile";
import { authStore } from "../stores/authStore";
import type { EmbedType } from "../message_parsing/types";
import { computeSHA256 } from "../message_parsing/utils";
import { embedStore } from "./embedStore";
import { clearEmbedError } from "./embedResolver";
import {
  decryptWithEmbedKey,
  encryptWithEmbedKey,
  generateEmbedKey,
  unwrapEmbedKeyWithChatKey,
  unwrapEmbedKeyWithMasterKey,
  wrapEmbedKeyWithChatKey,
  wrapEmbedKeyWithMasterKey,
} from "./cryptoService";
import { getTeamKey } from "./teamService";
import { unwrapAnonymousChatKey, wrapAnonymousChatKey } from "./anonymousChatKeyWrapping";
import { pollAppsSkillTask } from "./appsWorkspaceService";
import { chatDB } from "./db";
import { activeTeamId } from "../stores/teamStore";
import type { EmbedStoreEntry } from "../message_parsing/types";
import type { Chat, ChatContentBatchResponsePayload } from "../types/chat";
import type { EmbedKeyEntry } from "./embedStore";
import { decryptChatKeyWithMasterKey } from "./cryptoService";
import { unwrapTeamChatKey } from "./teamService";

export type AppsResultStatus = "processing" | "finished" | "error" | "cancelled";
export interface AppsResultItem {
  embedId: string;
  appId: string;
  skillId: string;
  createdAt: number;
  status: AppsResultStatus;
}
export interface AppsResultsPage {
  items: AppsResultItem[];
  hasMore: boolean;
  offset: number;
  limit: number;
}
export interface RetainAppsResultInput {
  appId: string;
  skillId: string;
  input: unknown;
  response: unknown;
  teamId?: string | null;
  guest?: boolean;
  requestId?: string;
  rootEmbedId?: string;
}
type CipherRow = {
  embed_id: string;
  encrypted_type: string;
  encrypted_content: string;
  encrypted_text_preview?: string;
  status: AppsResultStatus;
  embed_ids?: string[];
  parent_embed_id?: string;
};
type StoredGraph = {
  app_id: string;
  skill_id: string;
  root_embed_id: string;
  team_id?: string;
  embeds: CipherRow[];
  linked_embed_ids?: string[];
  encrypted_embed_key: string;
  created_at: number;
};
type ServerDetail = {
  root: CipherRow & { app_id: string; skill_id: string; created_at: number; updated_at: number; hashed_chat_id?: string };
  children: CipherRow[];
  linked?: CipherRow[];
  key: { hashed_embed_id: string; hashed_user_id: string; encrypted_embed_key: string; created_at: number; key_type: "master" | "team" } | null;
};

const GUEST_DB = "openmates_apps_guest_results";
const GUEST_STORE = "results";
const activeKeys = new Map<string, Uint8Array>();
const activeContexts = new Map<string, { teamId: string | null; guest: boolean; userId: string | null; wrapper?: string }>();
const resumptions = new Map<string, Promise<boolean>>();
const historicalIndexes = new Map<string, Promise<void>>();
const historicalIndexed = new Set<string>();
const historicalEpochs = new Map<string, number>();
const historicalScopes = new Map<string, { userId: string; appId: string; teamId: string | null }>();
const historicalCatchupTimers = new Map<string, ReturnType<typeof setTimeout>>();
const accountDiscoveries = new Map<string, { controller: AbortController; users: number }>();
let legacyPostQueue: Promise<void> = Promise.resolve();
let nextLegacyPostAt = 0;
type LegacyIndexItem = { embed_id: string; chat_id: string; app_id: string; skill_id: string };
const catalogId = /^[a-z][a-z0-9_]{0,63}$/;
const uuid = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

function requestJson<T>(path: string, init?: RequestInit): Promise<T> {
  return fetch(getApiEndpoint(path), {
    credentials: "include",
    headers: { "Content-Type": "application/json" },
    ...init,
  }).then(async (response) => {
    if (!response.ok) throw new Error(`Apps result request failed (${response.status})`);
    return response.json() as Promise<T>;
  });
}

function openGuestDb(): Promise<IDBDatabase> {
  return new Promise((resolve, reject) => {
    const request = indexedDB.open(GUEST_DB, 2);
    request.onupgradeneeded = () => {
      const store = request.transaction!.objectStoreNames.contains(GUEST_STORE)
        ? request.transaction!.objectStore(GUEST_STORE)
        : request.result.createObjectStore(GUEST_STORE, { keyPath: "root_embed_id" });
      if (!store.indexNames.contains("app_created")) store.createIndex("app_created", ["app_id", "created_at", "root_embed_id"]);
    };
    request.onsuccess = () => resolve(request.result);
    request.onerror = () => reject(request.error);
  });
}

async function guestPage(appId: string, offset: number, limit: number): Promise<AppsResultsPage> {
  const db = await openGuestDb();
  try {
    const rows = await new Promise<StoredGraph[]>((resolve, reject) => {
      const result: StoredGraph[] = [];
      let skipped = 0;
      const range = IDBKeyRange.bound([appId, 0, ""], [appId, Number.MAX_SAFE_INTEGER, "\uffff"]);
      const request = db.transaction(GUEST_STORE, "readonly").objectStore(GUEST_STORE).index("app_created").openCursor(range, "prev");
      request.onsuccess = () => {
        const cursor = request.result;
        if (!cursor || result.length >= limit + 1) return resolve(result);
        if (skipped++ >= offset) result.push(cursor.value as StoredGraph);
        cursor.continue();
      };
      request.onerror = () => reject(request.error);
    });
    return { items: rows.slice(0, limit).map((row) => ({ embedId: row.root_embed_id, appId: row.app_id, skillId: row.skill_id, createdAt: row.created_at, status: row.embeds[0].status })), hasMore: rows.length > limit, offset, limit };
  } finally { db.close(); }
}

async function guestRecords(): Promise<StoredGraph[]> {
  const db = await openGuestDb();
  try {
    return await new Promise((resolve, reject) => {
      const request = db.transaction(GUEST_STORE, "readonly").objectStore(GUEST_STORE).getAll();
      request.onsuccess = () => resolve(request.result as StoredGraph[]);
      request.onerror = () => reject(request.error);
    });
  } finally { db.close(); }
}

async function writeGuest(record: StoredGraph): Promise<void> {
  const db = await openGuestDb();
  try {
    await new Promise<void>((resolve, reject) => {
      const tx = db.transaction(GUEST_STORE, "readwrite");
      tx.objectStore(GUEST_STORE).put(record);
      tx.oncomplete = () => resolve();
      tx.onerror = () => reject(tx.error);
      tx.onabort = () => reject(tx.error);
    });
  } finally { db.close(); }
}

async function deleteGuest(rootId: string): Promise<void> {
  const db = await openGuestDb();
  try {
    await new Promise<void>((resolve, reject) => {
      const tx = db.transaction(GUEST_STORE, "readwrite");
      tx.objectStore(GUEST_STORE).delete(rootId);
      tx.oncomplete = () => resolve();
      tx.onerror = () => reject(tx.error);
      tx.onabort = () => reject(tx.error);
    });
  } finally { db.close(); }
}

function normalizedStatus(response: unknown): AppsResultStatus {
  const data = response && typeof response === "object" ? response as Record<string, unknown> : {};
  const nested = data.data && typeof data.data === "object" ? data.data as Record<string, unknown> : {};
  const raw = nested.status ?? data.status;
  return raw === "processing" || raw === "error" || raw === "cancelled" ? raw : "finished";
}

function extractResults(response: unknown): unknown[] {
  if (!response || typeof response !== "object") return [];
  const outer = response as Record<string, unknown>;
  const data = outer.data && typeof outer.data === "object" ? outer.data as Record<string, unknown> | unknown[] : outer;
  if (Array.isArray(data)) return data.flatMap((item) => {
    const nested = extractResults(item);
    return nested.length ? nested : [item];
  });
  if (!Array.isArray(data.results)) {
    return typeof data.embed_id === "string" && /^[0-9a-f-]{36}$/i.test(data.embed_id) ? [data] : [];
  }
  const groups = data.results as unknown[];
  if (groups.some((group) => group && typeof group === "object" && Array.isArray((group as Record<string, unknown>).results))) {
    return groups.flatMap((group) => group && typeof group === "object" && Array.isArray((group as Record<string, unknown>).results) ? (group as { results: unknown[] }).results : [group]);
  }
  return groups;
}

function existingResultIds(response: unknown): string[] {
  if (!response || typeof response !== "object") return [];
  const outer = response as Record<string, unknown>;
  const data = outer.data && typeof outer.data === "object" ? outer.data as Record<string, unknown> : outer;
  const ids = data.child_embed_ids ?? data.embed_ids;
  return Array.isArray(ids) ? ids.filter((id): id is string => typeof id === "string" && /^[0-9a-f-]{36}$/i.test(id)) : [];
}

async function stableChildId(rootId: string, index: number): Promise<string> {
  const bytes = new Uint8Array(await crypto.subtle.digest("SHA-256", new TextEncoder().encode(`${rootId}:child:${index}`))).slice(0, 16);
  bytes[6] = (bytes[6] & 0x0f) | 0x40;
  bytes[8] = (bytes[8] & 0x3f) | 0x80;
  const hex = Array.from(bytes, (byte) => byte.toString(16).padStart(2, "0")).join("");
  return `${hex.slice(0, 8)}-${hex.slice(8, 12)}-${hex.slice(12, 16)}-${hex.slice(16, 20)}-${hex.slice(20)}`;
}

function uploadGraph(graph: StoredGraph, expectedUserId: string): Promise<{ root_embed_id: string; linked_embed_ids: string[] }> {
  const { created_at: _createdAt, ...body } = graph;
  return requestJson("/v1/apps/workspace/results", { method: "POST", body: JSON.stringify({ ...body, expected_user_id: expectedUserId }) });
}

function assertSameAuthenticatedUser(userId: string): void {
  if (!get(authStore).isAuthenticated || get(userProfile).user_id !== userId) {
    throw new Error("Apps result account changed before encrypted upload completed");
  }
}

function assertHistoricalContext(userId: string, teamId: string | null): void {
  assertSameAuthenticatedUser(userId);
  if ((get(activeTeamId) || null) !== teamId) throw new Error("Apps result account changed during historical indexing");
}

async function localCatalogMetadata(row: EmbedStoreEntry): Promise<{ appId: string; skillId: string } | null> {
  let appId = row.app_id;
  let skillId = row.skill_id;
  if ((!appId || !skillId) && row.embed_id) {
    try {
      const stored = await embedStore.get(`embed:${row.embed_id}`);
      if (stored && typeof stored === "object" && typeof stored.content === "string") {
        const content = stored.content.trimStart();
        const decoded = content.startsWith("{") ? JSON.parse(content) as Record<string, unknown>
          : (await import("@toon-format/toon")).decode(content, { strict: false }) as Record<string, unknown>;
        appId ||= typeof decoded.app_id === "string" ? decoded.app_id : undefined;
        skillId ||= typeof decoded.skill_id === "string" ? decoded.skill_id : undefined;
      }
    } catch { /* Undecodable historical rows cannot be safely classified. */ }
  }
  return appId && skillId && catalogId.test(appId) && catalogId.test(skillId) ? { appId, skillId } : null;
}

async function postLegacyIndexBatch(items: LegacyIndexItem[], userId: string, teamId: string | null, signal?: AbortSignal): Promise<{ indexed: number; received: number }> {
  if (!items.length) return { indexed: 0, received: 0 };
  const previous = legacyPostQueue;
  let release!: () => void;
  legacyPostQueue = new Promise<void>((resolve) => { release = resolve; });
  await previous;
  try {
    const delay = Math.max(0, nextLegacyPostAt - Date.now());
    if (delay) await new Promise((resolve) => setTimeout(resolve, delay));
    if (signal?.aborted) throw new Error("Apps historical discovery stopped");
    assertHistoricalContext(userId, teamId);
    const result = await requestJson<{ indexed: number; received: number }>("/v1/apps/workspace/results/index/batch", {
      method: "POST", body: JSON.stringify({ expected_user_id: userId, team_id: teamId, items }),
    });
    nextLegacyPostAt = Date.now() + 5100; // Under the server's 12/minute bound.
    assertHistoricalContext(userId, teamId);
    if (result.indexed > 0 && typeof window !== "undefined") window.dispatchEvent(new CustomEvent("appsResultUpdated", { detail: { teamId } }));
    return result;
  } finally { release(); }
}

/** Index locally available legacy chat roots in bounded pages for one app. */
export function indexHistoricalAppsResults(appId: string, teamId?: string | null): Promise<void> {
  const userId = get(userProfile).user_id;
  const scopedTeamId = teamId || null;
  if (!userId || !get(authStore).isAuthenticated || !catalogId.test(appId)) return Promise.resolve();
  const scope = `${userId}:${scopedTeamId || "personal"}:${appId}`;
  historicalScopes.set(scope, { userId, appId, teamId: scopedTeamId });
  if (historicalIndexed.has(scope)) return Promise.resolve();
  const active = historicalIndexes.get(scope);
  if (active) return active;
  const startEpoch = historicalEpochs.get(scope) || 0;
  const operation = (async () => {
    let afterChat: string | null = null;
    let batch: LegacyIndexItem[] = [];
    do {
      assertHistoricalContext(userId, scopedTeamId);
      const chatPage = await chatDB.getChatsPage(afterChat, 50);
      for (const chat of chatPage.items) {
        if ((chat.team_id || null) !== scopedTeamId || !uuid.test(chat.chat_id)) continue;
        let posting = false;
        try {
          const hashedChatId = await computeSHA256(chat.chat_id);
          let afterEmbed: string | null = null;
          do {
            assertHistoricalContext(userId, scopedTeamId);
            const page = await embedStore.getEmbedsByHashedChatIdPage(hashedChatId, afterEmbed, 50);
            for (const row of page.items) {
              if (!row.embed_id || !uuid.test(row.embed_id) || row.parent_embed_id || !row.encrypted_content) continue;
              const metadata = await localCatalogMetadata(row);
              if (metadata?.appId === appId) batch.push({ embed_id: row.embed_id, chat_id: chat.chat_id, app_id: appId, skill_id: metadata.skillId });
              if (batch.length === 50) {
                posting = true;
                await postLegacyIndexBatch(batch, userId, scopedTeamId);
                posting = false;
                batch = [];
              }
            }
            afterEmbed = page.nextAfter;
          } while (afterEmbed);
        } catch (error) {
          // A stale/deleted local chat should not hide other valid chat roots.
          if (posting || !get(authStore).isAuthenticated || get(userProfile).user_id !== userId || (get(activeTeamId) || null) !== scopedTeamId) throw error;
        }
      }
      afterChat = chatPage.nextAfter;
    } while (afterChat);
    await postLegacyIndexBatch(batch, userId, scopedTeamId);
    // Bulk sync may have committed another encrypted batch while this scan ran.
    // A completed scan only covers the IndexedDB snapshot it actually observed.
    if ((historicalEpochs.get(scope) || 0) === startEpoch) historicalIndexed.add(scope);
  })().finally(() => historicalIndexes.delete(scope));
  historicalIndexes.set(scope, operation);
  return operation;
}

/** Revisit an already opened library after encrypted chat embeds arrive via bulk sync. */
export function notifyAppsHistoricalEmbedsSynced(expectedUserId: string | null): void {
  if (!expectedUserId || !get(authStore).isAuthenticated || get(userProfile).user_id !== expectedUserId) return;
  const teamId = get(activeTeamId) || null;
  for (const [scope, context] of Array.from(historicalScopes)) {
    if (context.userId !== expectedUserId || context.teamId !== teamId) continue;
    historicalEpochs.set(scope, (historicalEpochs.get(scope) || 0) + 1);
    historicalIndexed.delete(scope);
    const pending = historicalCatchupTimers.get(scope);
    if (pending) clearTimeout(pending);
    // Coalesce consecutive Phase 3 batches. The existing cursor scan and server
    // POST queue still bound local work and request rate.
    historicalCatchupTimers.set(scope, setTimeout(() => {
      historicalCatchupTimers.delete(scope);
      if (!get(authStore).isAuthenticated || get(userProfile).user_id !== context.userId ||
          (get(activeTeamId) || null) !== context.teamId) return;
      void (async () => {
        await historicalIndexes.get(scope)?.catch(() => {});
        if (!historicalIndexed.has(scope)) await indexHistoricalAppsResults(context.appId, context.teamId);
      })().catch(() => {});
    }, 350));
  }
}

type LegacyChatPage = { chats: Chat[]; has_more: boolean; offset: number; team_id: string | null; error?: string };
type LegacyRootPage = ChatContentBatchResponsePayload & { chat_id: string; embed_offset: number; next_embed_offset: number | null };

function assertDiscoveryContext(userId: string, teamId: string | null, signal: AbortSignal): void {
  if (signal.aborted) throw new Error("Apps historical discovery stopped");
  assertHistoricalContext(userId, teamId);
}

async function awaitSyncEvent<T>(
  type: string, send: () => Promise<void>, matches: (value: T) => boolean, signal: AbortSignal,
): Promise<T> {
  const { chatSyncService } = await import("./chatSyncService");
  if (signal.aborted) throw new Error("Apps historical discovery stopped");
  return new Promise<T>((resolve, reject) => {
    const clean = () => {
      clearTimeout(timeout);
      chatSyncService.removeEventListener(type, onEvent);
      signal.removeEventListener("abort", onAbort);
    };
    const onAbort = () => { clean(); reject(new Error("Apps historical discovery stopped")); };
    const onEvent = (event: Event) => {
      const value = (event as CustomEvent<T>).detail;
      if (!matches(value)) return;
      clean(); resolve(value);
    };
    const timeout = setTimeout(() => { clean(); reject(new Error("Apps historical sync timed out")); }, 20_000);
    chatSyncService.addEventListener(type, onEvent);
    signal.addEventListener("abort", onAbort, { once: true });
    void send().catch((error) => { clean(); reject(error); });
  });
}

async function loadLegacyChats(offset: number, teamId: string | null, signal: AbortSignal): Promise<LegacyChatPage> {
  const { chatSyncService } = await import("./chatSyncService");
  const page = await awaitSyncEvent<LegacyChatPage>("load_more_chats_ready",
    () => chatSyncService.sendLoadMoreChats(offset, 20),
    (value) => value.offset === offset && (value.team_id || null) === teamId, signal);
  if (page.error) throw new Error("Apps historical chat listing unavailable");
  return page;
}

async function loadLegacyRoots(chatId: string, offset: number, teamId: string | null, signal: AbortSignal): Promise<LegacyRootPage> {
  const requestId = crypto.randomUUID();
  const { webSocketService } = await import("./websocketService");
  const { activeTeamContext } = await import("../stores/teamStore");
  const context = get(activeTeamContext);
  if (context.teamId !== teamId) throw new Error("Apps historical Team context changed");
  const page = await awaitSyncEvent<LegacyRootPage>("apps_legacy_embed_page_ready",
    () => webSocketService.sendMessage("request_chat_content_batch", {
      chat_ids: [chatId], apps_legacy_embeds_only: true, embed_offset: offset,
      request_id: requestId, team_id: teamId, context_epoch: context.epoch,
    }),
    (value) => value.request_id === requestId && value.chat_id === chatId && (value.team_id || null) === teamId,
    signal);
  if (page.error) throw new Error("Apps historical embed page unavailable");
  return page;
}

async function classifyLegacyRoot(
  row: NonNullable<ChatContentBatchResponsePayload["embeds"]>[number],
  wrappers: EmbedKeyEntry[], chatKey: Uint8Array,
): Promise<{ metadata: { appId: string; skillId: string }; key: Uint8Array; wrappers: EmbedKeyEntry[] } | null> {
  if (!row.embed_id || !uuid.test(row.embed_id) || row.parent_embed_id ||
      (row.root_embed_id && row.root_embed_id !== row.embed_id) || !row.encrypted_content) return null;
  const embedHash = await computeSHA256(row.embed_id);
  const keys = wrappers.filter((entry) => entry.hashed_embed_id === embedHash);
  for (const wrapper of keys) {
    const key = wrapper.key_type === "master"
      ? await unwrapEmbedKeyWithMasterKey(wrapper.encrypted_embed_key, row.embed_id)
      : await unwrapEmbedKeyWithChatKey(wrapper.encrypted_embed_key, chatKey, { embedId: row.embed_id });
    if (!key) continue;
    try {
      const content = await decryptWithEmbedKey(row.encrypted_content, key);
      const decoded = content.trimStart().startsWith("{") ? JSON.parse(content) as Record<string, unknown>
        : (await import("@toon-format/toon")).decode(content, { strict: false }) as Record<string, unknown>;
      const appId = decoded.app_id;
      const skillId = decoded.skill_id;
      if (typeof appId === "string" && typeof skillId === "string" && catalogId.test(appId) && catalogId.test(skillId)) {
        return { metadata: { appId, skillId }, key, wrappers: keys };
      }
    } catch { /* A row without a usable original key cannot be classified. */ }
  }
  return null;
}

function discoveryCursorKey(userId: string, teamId: string | null): string {
  return `apps-legacy-discovery:${userId}:${teamId || "personal"}`;
}

function legacyChatKey(userId: string, teamId: string | null, embedId: string): string {
  return `apps-legacy-chat:${userId}:${teamId || "personal"}:${embedId}`;
}

async function discoverAccountLegacyRoots(userId: string, teamId: string | null, signal: AbortSignal): Promise<void> {
  const cursorKey = discoveryCursorKey(userId, teamId);
  let offset = 100; // Startup sync and the local cursor scan cover the first 100 chats.
  try {
    const saved = localStorage.getItem(cursorKey);
    if (saved === "done") return;
    if (saved && /^\d+$/.test(saved)) offset = Math.max(100, Number(saved));
  } catch { /* Discovery still works without resumable browser storage. */ }
  while (true) {
    assertDiscoveryContext(userId, teamId, signal);
    const page = await loadLegacyChats(offset, teamId, signal);
    assertDiscoveryContext(userId, teamId, signal);
    let pendingItems: LegacyIndexItem[] = [];
    for (const chat of page.chats) {
      if (!uuid.test(chat.chat_id) || !chat.encrypted_chat_key || (chat.team_id || null) !== teamId) continue;
      const chatKey = teamId
        ? await unwrapTeamChatKey(teamId, chat.encrypted_chat_key)
        : await decryptChatKeyWithMasterKey(chat.encrypted_chat_key);
      if (!chatKey) continue;
      let embedOffset = 0;
      let savedChat = false;
      do {
        assertDiscoveryContext(userId, teamId, signal);
        const roots = await loadLegacyRoots(chat.chat_id, embedOffset, teamId, signal);
        assertDiscoveryContext(userId, teamId, signal);
        for (const root of roots.embeds || []) {
          assertDiscoveryContext(userId, teamId, signal);
          const found = await classifyLegacyRoot(root, roots.embed_keys || [], chatKey);
          if (!found) continue;
          // Persist only chats that contain a discoverable root. Both stores
          // check identity at their IndexedDB put boundary after async setup.
          const guard = () => assertDiscoveryContext(userId, teamId, signal);
          if (!savedChat) {
            await chatDB.addChat(chat, undefined, { isFromSync: true, writeGuard: guard });
            savedChat = true;
          }
          await embedStore.storeEmbedKeys(found.wrappers, guard);
          guard();
          embedStore.setEmbedKeyInCache(root.embed_id, found.key, root.hashed_chat_id);
          try { localStorage.setItem(legacyChatKey(userId, teamId, root.embed_id), chat.chat_id); } catch { /* Key cache still works for this session. */ }
          pendingItems.push({ embed_id: root.embed_id, chat_id: chat.chat_id,
            app_id: found.metadata.appId, skill_id: found.metadata.skillId });
          if (pendingItems.length === 50) {
            await postLegacyIndexBatch(pendingItems, userId, teamId, signal);
            pendingItems = [];
          }
        }
        embedOffset = roots.next_embed_offset ?? -1;
      } while (embedOffset >= 0);
    }
    if (pendingItems.length) await postLegacyIndexBatch(pendingItems, userId, teamId, signal);
    offset += 20;
    assertDiscoveryContext(userId, teamId, signal);
    try { localStorage.setItem(cursorKey, page.has_more ? String(offset) : "done"); } catch { /* Resume is optional. */ }
    if (!page.has_more) return;
  }
}

/** Start a cancellable, resumable ciphertext-only account scan for an open Apps library. */
export function startAppsHistoricalDiscovery(appId: string, teamId?: string | null): () => void {
  const userId = get(userProfile).user_id;
  const scopedTeamId = teamId || null;
  if (!userId || !get(authStore).isAuthenticated || !catalogId.test(appId)) return () => {};
  const scope = `${userId}:${scopedTeamId || "personal"}`;
  let running = accountDiscoveries.get(scope);
  if (!running || running.controller.signal.aborted) {
    running = { controller: new AbortController(), users: 0 };
    accountDiscoveries.set(scope, running);
    const controller = running.controller;
    void discoverAccountLegacyRoots(userId, scopedTeamId, controller.signal)
      .catch(() => {})
      .finally(() => { if (accountDiscoveries.get(scope)?.controller === controller) accountDiscoveries.delete(scope); });
  }
  running.users++;
  return () => {
    const current = accountDiscoveries.get(scope);
    if (current !== running) return;
    if (--current.users <= 0) { current.controller.abort(); accountDiscoveries.delete(scope); }
  };
}

/** A newly re-synced legacy root can be projected without waiting for a library scan. */
export async function indexSyncedAppsEmbed(
  embedId: string, chatId: string, appId: string, skillId: string, teamId?: string | null,
): Promise<void> {
  const userId = get(userProfile).user_id;
  const scopedTeamId = teamId || null;
  if (!userId || !get(authStore).isAuthenticated || !uuid.test(embedId) || !uuid.test(chatId)
    || !catalogId.test(appId) || !catalogId.test(skillId)) return;
  const item = { embed_id: embedId, chat_id: chatId, app_id: appId, skill_id: skillId };
  for (const delay of [300, 900, 1800]) {
    await new Promise((resolve) => setTimeout(resolve, delay));
    const result = await postLegacyIndexBatch([item], userId, scopedTeamId);
    if (result.indexed > 0) return;
  }
}

async function hydrateRows(rows: CipherRow[], appId: string, skillId: string, key: Uint8Array, createdAt: number, expectedUserId?: string): Promise<void> {
  for (const row of rows) {
    const type = await decryptWithEmbedKey(row.encrypted_type, key);
    if (!type) throw new Error("Saved Apps result type could not be decrypted");
    if (expectedUserId) assertSameAuthenticatedUser(expectedUserId);
    await embedStore.putEncrypted(`embed:${row.embed_id}`, {
      ...row, createdAt: createdAt * 1000, updatedAt: Date.now(), is_private: true,
    }, type as EmbedType, undefined, { app_id: appId, skill_id: skillId },
    expectedUserId ? { writeGuard: () => assertSameAuthenticatedUser(expectedUserId) } : undefined);
    if (expectedUserId) assertSameAuthenticatedUser(expectedUserId);
    embedStore.setEmbedKeyInCache(row.embed_id, key);
    // A library preview may have tried this locally cached ciphertext before
    // its wrapper was restored. The resolver remembers that failed decrypt;
    // clear it only after the row and its key are available again.
    clearEmbedError(row.embed_id);
  }
}

/** Refresh short-lived generated-media URLs in local encrypted embed content. */
export async function refreshAppsGeneratedAssetUrls(embedIds: string[], teamId?: string | null, expectedUserId?: string | null): Promise<void> {
  const ownerId = expectedUserId === undefined ? (get(authStore).isAuthenticated ? get(userProfile).user_id : null) : expectedUserId;
  for (const embedId of embedIds) {
    if (ownerId) assertSameAuthenticatedUser(ownerId);
    const stored = await embedStore.get(`embed:${embedId}`);
    if (!stored || typeof stored !== "object" || stored.status !== "finished" || typeof stored.content !== "string") continue;
    let content: Record<string, unknown>;
    try { content = JSON.parse(stored.content) as Record<string, unknown>; } catch { continue; }
    if (!["images", "audio", "music", "videos"].includes(String(content.app_id || ""))) continue;
    if (!content.files || typeof content.files !== "object" || Array.isArray(content.files)) continue;
    const files = content.files as Record<string, unknown>;
    let updated = false;
    const nextFiles: Record<string, unknown> = { ...files };
    for (const [variant, raw] of Object.entries(files)) {
      if (!raw || typeof raw !== "object" || Array.isArray(raw) || !/^[a-z][a-z0-9_-]{0,40}$/.test(variant)) continue;
      const file = raw as Record<string, unknown>;
      // Normal chat media uses encrypted S3 keys and has no expiring REST URL.
      if (typeof file.s3_key === "string" && typeof content.aes_key === "string") continue;
      const expiresAt = typeof file.download_expires_at === "number" ? file.download_expires_at : 0;
      if (!teamId && typeof file.download_url === "string" && expiresAt > Math.floor(Date.now() / 1000) + 60) continue;
      const url = `/v1/generated-assets/${encodeURIComponent(embedId)}/files/${encodeURIComponent(variant)}/download-url${teamId ? `?team_id=${encodeURIComponent(teamId)}` : ""}`;
      const refreshed = await requestJson<{ download_url: string; download_expires_at: number }>(url);
      nextFiles[variant] = { ...file, download_url: refreshed.download_url, download_expires_at: refreshed.download_expires_at };
      updated = true;
    }
    if (!updated) continue;
    content = { ...content, files: nextFiles };
    const original = nextFiles.original as Record<string, unknown> | undefined;
    const preview = nextFiles.preview as Record<string, unknown> | undefined;
    const originalUrl = typeof original?.download_url === "string" ? original.download_url : "";
    const previewUrl = typeof preview?.download_url === "string" ? preview.download_url : originalUrl;
    const appId = typeof content.app_id === "string" ? content.app_id : "";
    if (appId === "images") content.previewImageUrl = previewUrl;
    if (appId === "audio") { content.previewAudioUrl = originalUrl; content.audio_url = originalUrl; }
    if (appId === "music") content.previewAudioUrl = originalUrl;
    if (appId === "videos") { content.previewVideoUrl = originalUrl; content.video_url = originalUrl; }
    const key = await embedStore.getEmbedKey(embedId);
    if (!key) throw new Error("Generated asset embed key is unavailable");
    const type = typeof stored.type === "string" ? stored.type : "app_skill_use";
    if (ownerId) assertSameAuthenticatedUser(ownerId);
    await embedStore.putEncrypted(`embed:${embedId}`, {
      embed_id: embedId,
      encrypted_type: await encryptWithEmbedKey(type, key),
      encrypted_content: await encryptWithEmbedKey(JSON.stringify(content), key),
      status: "finished",
      parent_embed_id: stored.parent_embed_id,
      embed_ids: stored.embed_ids,
      createdAt: typeof stored.createdAt === "number" ? stored.createdAt : Date.now(),
      updatedAt: Date.now(),
    }, type as EmbedType, undefined, { app_id: appId, skill_id: typeof content.skill_id === "string" ? content.skill_id : undefined },
    ownerId ? { writeGuard: () => assertSameAuthenticatedUser(ownerId) } : undefined);
  }
}

/** Persist one request graph, including a processing parent before provider dispatch. */
export async function retainAppsResult(args: RetainAppsResultInput): Promise<string> {
  const rootId = args.rootEmbedId || args.requestId || crypto.randomUUID();
  const guest = Boolean(args.guest);
  if (!guest && !get(userProfile).user_id) throw new Error("Apps result owner is unavailable");
  const submittedContext = { teamId: args.teamId ?? null, guest, userId: guest ? null : get(userProfile).user_id };
  const previousContext = activeContexts.get(rootId);
  if (previousContext && (previousContext.teamId !== submittedContext.teamId || previousContext.guest !== guest || previousContext.userId !== submittedContext.userId)) {
    throw new Error("Apps result account changed while request was processing");
  }
  if (!previousContext) activeContexts.set(rootId, submittedContext);
  const existingGuest = guest ? (await guestRecords()).find((row) => row.root_embed_id === rootId) : undefined;
  let key = activeKeys.get(rootId) ?? await embedStore.getEmbedKey(rootId);
  if (!key && existingGuest) key = await unwrapAnonymousChatKey(existingGuest.encrypted_embed_key);
  if (!key && !guest) {
    try { await getAppsResult(rootId, args.teamId); key = activeKeys.get(rootId) ?? await embedStore.getEmbedKey(rootId); } catch { /* New result. */ }
  }
  key ||= generateEmbedKey();
  activeKeys.set(rootId, key);
  const status = normalizedStatus(args.response);
  const results = status === "processing" ? [] : extractResults(args.response);
  const resultIds = new Set(results.flatMap((result) => result && typeof result === "object"
      && typeof (result as Record<string, unknown>).embed_id === "string"
      && /^[0-9a-f-]{36}$/i.test((result as { embed_id: string }).embed_id)
      ? [(result as { embed_id: string }).embed_id] : []));
  const persistedIds = Array.from(new Set(existingResultIds(args.response).filter((id) => !resultIds.has(id))));
  const childType = EMBED_CHILD_TYPE_MAP[`${args.appId}:${args.skillId}`];
  const children: CipherRow[] = [];
  if (results.length > 500) throw new Error("Apps result exceeds the supported graph size");
  for (let index = 0; index < results.length; index++) {
    const result = results[index];
    const resultObject = result && typeof result === "object" ? result as Record<string, unknown> : {};
    const assetId = typeof resultObject.embed_id === "string" && /^[0-9a-f-]{36}$/i.test(resultObject.embed_id) ? resultObject.embed_id : null;
    if (!childType && !assetId) continue;
    const childId = assetId || await stableChildId(rootId, index);
    const resultType = typeof resultObject.type === "string" ? resultObject.type
      : typeof resultObject.embed_type === "string" ? resultObject.embed_type
      : childType || ({ images: "image", audio: "audio", videos: "video", music: "music" } as Record<string, string>)[args.appId] || "app_skill_use";
    children.push({
      embed_id: childId,
      encrypted_type: await encryptWithEmbedKey(resultType, key),
      encrypted_content: await encryptWithEmbedKey(JSON.stringify({ app_id: args.appId, skill_id: args.skillId, ...resultObject, result }), key),
      status: "finished",
      parent_embed_id: rootId,
    });
  }
  const childIds = children.map((child) => child.embed_id);
  const responseData = args.response && typeof args.response === "object" && "data" in args.response
    && (args.response as { data?: unknown }).data && typeof (args.response as { data?: unknown }).data === "object"
    ? (args.response as { data: Record<string, unknown> }).data : args.response;
  const metadata = responseData && typeof responseData === "object" ? responseData as Record<string, unknown> : {};
  const { results: _nestedResults, ...responseMetadata } = metadata;
  let acceptedTaskIds: string[] = [];
  if (status === "processing") {
    const previous = await embedStore.get(`embed:${rootId}`);
    if (previous && typeof previous === "object" && typeof previous.content === "string") {
      try {
        const content = JSON.parse(previous.content) as { task_id?: unknown; task_ids?: unknown };
        if (typeof content.task_id === "string") acceptedTaskIds.push(content.task_id);
        if (Array.isArray(content.task_ids)) acceptedTaskIds.push(...content.task_ids.filter((id): id is string => typeof id === "string"));
      } catch { /* A new processing row has no prior task IDs. */ }
    }
    if (typeof metadata.task_id === "string") acceptedTaskIds.push(metadata.task_id);
    if (Array.isArray(metadata.task_ids)) acceptedTaskIds.push(...metadata.task_ids.filter((id): id is string => typeof id === "string"));
    acceptedTaskIds = Array.from(new Set(acceptedTaskIds));
  }
  const rootContent = {
    ...responseMetadata,
    app_id: args.appId, skill_id: args.skillId, input: args.input,
    ...(acceptedTaskIds.length ? { task_ids: acceptedTaskIds } : {}),
    ...(childType ? {} : { results }), result_count: results.length,
    embed_ids: [...childIds, ...persistedIds], status,
  };
  const root: CipherRow = {
    embed_id: rootId,
    encrypted_type: await encryptWithEmbedKey("app_skill_use", key),
    encrypted_content: await encryptWithEmbedKey(JSON.stringify(rootContent), key),
    status,
    embed_ids: [...childIds, ...persistedIds],
  };
  const createdAt = existingGuest?.created_at ?? Math.floor(Date.now() / 1000);
  const wrapper = previousContext?.wrapper || existingGuest?.encrypted_embed_key || (guest ? await wrapAnonymousChatKey(key)
    : args.teamId ? await wrapEmbedKeyWithChatKey(key, await getTeamKey(args.teamId))
    : await wrapEmbedKeyWithMasterKey(key));
  if (!wrapper) throw new Error("Apps result key could not be wrapped");
  activeContexts.set(rootId, { ...submittedContext, wrapper });
  const graph: StoredGraph = { app_id: args.appId, skill_id: args.skillId, root_embed_id: rootId,
    ...(args.teamId ? { team_id: args.teamId } : {}), embeds: [root, ...children], linked_embed_ids: persistedIds,
    encrypted_embed_key: wrapper, created_at: createdAt };
  if (guest) {
    await hydrateRows([root, ...children], args.appId, args.skillId, key, createdAt);
    await writeGuest(graph);
  } else {
    assertSameAuthenticatedUser(submittedContext.userId!);
    const saved = await uploadGraph(graph, submittedContext.userId!);
    assertSameAuthenticatedUser(submittedContext.userId!);
    const linked = new Set(saved.linked_embed_ids);
    await hydrateRows([root, ...children.filter((row) => !linked.has(row.embed_id))], args.appId, args.skillId, key, createdAt, submittedContext.userId!);
  }
  if (status === "finished") {
    // The encrypted graph is already durable; a transient URL refresh must not
    // report the provider result as unsaved.
    try { await refreshAppsGeneratedAssetUrls(children.map((row) => row.embed_id), args.teamId, submittedContext.userId); }
    catch { /* Reopening the result retries the refresh. */ }
  }
  return rootId;
}

export async function listAppsResults(appId: string, teamId?: string | null, offset = 0, limit = 20): Promise<AppsResultsPage> {
  if (!get(authStore).isAuthenticated) {
    return guestPage(appId, offset, limit);
  }
  void indexHistoricalAppsResults(appId, teamId).catch(() => {});
  const params = new URLSearchParams({ app_id: appId, offset: String(offset), limit: String(limit) });
  if (teamId) params.set("team_id", teamId);
  const page = await requestJson<{ items: Array<{ embed_id: string; app_id: string; skill_id: string; created_at: number; status: AppsResultStatus }>; has_more: boolean; offset: number; limit: number }>(`/v1/apps/workspace/results?${params}`);
  for (const row of page.items) {
    if (row.status === "processing") void resumeAppsResult(row.embed_id, teamId).catch(() => {});
  }
  return { items: page.items.map((row) => ({ embedId: row.embed_id, appId: row.app_id, skillId: row.skill_id, createdAt: row.created_at, status: row.status })), hasMore: page.has_more, offset: page.offset, limit: page.limit };
}

/** Continue an accepted background task using its encrypted saved task ID. */
export function resumeAppsResult(embedId: string, teamId?: string | null): Promise<boolean> {
  const key = `${teamId || "personal"}:${embedId}`;
  const running = resumptions.get(key);
  if (running) return running;
  const resume = (async () => {
    const ownerId = get(userProfile).user_id;
    if (!ownerId || !get(authStore).isAuthenticated) return false;
    await getAppsResult(embedId, teamId);
    assertSameAuthenticatedUser(ownerId);
    const stored = await embedStore.get(`embed:${embedId}`);
    if (!stored || typeof stored !== "object" || stored.status !== "processing" || typeof stored.content !== "string") return false;
    let content: Record<string, unknown>;
    try { content = JSON.parse(stored.content) as Record<string, unknown>; } catch { return false; }
    const taskIds = Array.isArray(content.task_ids) ? content.task_ids.filter((id): id is string => typeof id === "string")
      : typeof content.task_id === "string" ? [content.task_id]
      : content.response && typeof content.response === "object" && typeof (content.response as Record<string, unknown>).task_id === "string"
        ? [(content.response as { task_id: string }).task_id] : [];
    if (!taskIds.length) return false;
    try {
      const completed = await Promise.all(taskIds.map((taskId) => pollAppsSkillTask(taskId, { expectedUserId: ownerId })));
      assertSameAuthenticatedUser(ownerId);
      await retainAppsResult({ appId: String(content.app_id), skillId: String(content.skill_id),
        input: content.input, response: { success: true, data: completed.length === 1 ? completed[0] : completed },
        teamId, requestId: embedId });
      if (typeof window !== "undefined") window.dispatchEvent(new CustomEvent("appsResultUpdated", { detail: { embedId, teamId: teamId ?? null } }));
      return true;
    } catch {
      // Distinguish a terminal provider failure from network loss, account
      // changes, or owner-only authorization before changing saved status.
      try {
        for (const taskId of taskIds) {
          const response = await fetch(getApiEndpoint(`/v1/tasks/${encodeURIComponent(taskId)}`), { credentials: "include" });
          if (!response.ok) continue;
          const body = await response.json() as { status?: string; error?: string };
          if (body.status !== "failed") continue;
          await retainAppsResult({ appId: String(content.app_id), skillId: String(content.skill_id), input: content.input,
            response: { status: "error", error: body.error || "task_failed", task_ids: taskIds }, teamId, requestId: embedId });
          if (typeof window !== "undefined") window.dispatchEvent(new CustomEvent("appsResultUpdated", { detail: { embedId, teamId: teamId ?? null } }));
          return true;
        }
      } catch { /* Retain processing for another retry. */ }
      return false;
    }
  })().finally(() => resumptions.delete(key));
  resumptions.set(key, resume);
  return resume;
}

/** Fetch and ingest a saved root and all children into the standard embed store. */
export async function getAppsResult(embedId: string, teamId?: string | null): Promise<void> {
  const requestedUserId = get(authStore).isAuthenticated ? get(userProfile).user_id : null;
  const guest = !get(authStore).isAuthenticated ? (await guestRecords()).find((row) => row.root_embed_id === embedId) : undefined;
  if (guest) {
    const key = await unwrapAnonymousChatKey(guest.encrypted_embed_key);
    if (!key) throw new Error("Guest Apps result key is unavailable");
    activeKeys.set(embedId, key);
    activeContexts.set(embedId, { teamId: null, guest: true, userId: null, wrapper: guest.encrypted_embed_key });
    await hydrateRows(guest.embeds, guest.app_id, guest.skill_id, key, guest.created_at);
    await refreshAppsGeneratedAssetUrls(guest.embeds.slice(1).map((row) => row.embed_id), null, null);
    return;
  }
  if (!requestedUserId) throw new Error("Guest Apps result is unavailable");
  const suffix = teamId ? `?team_id=${encodeURIComponent(teamId)}` : "";
  const detail = await requestJson<ServerDetail>(`/v1/apps/workspace/results/${encodeURIComponent(embedId)}${suffix}`);
  assertSameAuthenticatedUser(requestedUserId);
  if (!detail.key) {
    // An older chat embed uses its existing chat-key wrapper. Resolve that key
    // through the normal embed store and hydrate the original ciphertext graph.
    let chatKey: Uint8Array | null = null;
    let mappedChatId: string | null = null;
    try { mappedChatId = localStorage.getItem(legacyChatKey(requestedUserId, teamId || null, embedId)); } catch { /* Optional local mapping. */ }
    if (mappedChatId && uuid.test(mappedChatId)) {
      const chat = await chatDB.getChat(mappedChatId);
      assertSameAuthenticatedUser(requestedUserId);
      if (chat?.encrypted_chat_key && (chat.team_id || null) === (teamId || null) &&
          await computeSHA256(mappedChatId) === detail.root.hashed_chat_id) {
        const originalChatKey = teamId
          ? await unwrapTeamChatKey(teamId, chat.encrypted_chat_key)
          : await decryptChatKeyWithMasterKey(chat.encrypted_chat_key);
        if (originalChatKey) {
          const wrappers = await embedStore.getEmbedKeyEntries(await computeSHA256(embedId));
          for (const wrapper of wrappers) {
            if (wrapper.hashed_chat_id !== detail.root.hashed_chat_id || wrapper.key_type !== "chat") continue;
            chatKey = await unwrapEmbedKeyWithChatKey(wrapper.encrypted_embed_key, originalChatKey, { embedId, chatId: mappedChatId });
            if (chatKey) break;
          }
        }
      }
    }
    chatKey ||= await embedStore.getEmbedKey(embedId, detail.root.hashed_chat_id);
    if (chatKey) {
      assertSameAuthenticatedUser(requestedUserId);
      await hydrateRows([detail.root, ...detail.children], detail.root.app_id, detail.root.skill_id, chatKey, detail.root.created_at, requestedUserId);
      assertSameAuthenticatedUser(requestedUserId);
      activeKeys.set(embedId, chatKey);
      activeContexts.set(embedId, { teamId: teamId ?? null, guest: false, userId: requestedUserId });
      await refreshAppsGeneratedAssetUrls([...detail.children, ...(detail.linked || [])].map((row) => row.embed_id), teamId, requestedUserId);
      return;
    }
    const local = await embedStore.get(`embed:${embedId}`);
    if (local) return;
    throw new Error("Chat result is waiting for its original key sync");
  }
  const key = teamId
    ? await unwrapEmbedKeyWithChatKey(detail.key.encrypted_embed_key, await getTeamKey(teamId), { embedId })
    : await unwrapEmbedKeyWithMasterKey(detail.key.encrypted_embed_key, embedId);
  if (!key) throw new Error("Apps result key could not be unwrapped");
  assertSameAuthenticatedUser(requestedUserId);
  if (!teamId) {
    await embedStore.storeEmbedKeys([{ hashed_embed_id: await computeSHA256(embedId), key_type: "master", hashed_chat_id: null, encrypted_embed_key: detail.key.encrypted_embed_key, hashed_user_id: detail.key.hashed_user_id, created_at: detail.key.created_at }], () => assertSameAuthenticatedUser(requestedUserId));
  }
  await hydrateRows([detail.root, ...detail.children], detail.root.app_id, detail.root.skill_id, key, detail.root.created_at, requestedUserId);
  assertSameAuthenticatedUser(requestedUserId);
  activeKeys.set(embedId, key);
  activeContexts.set(embedId, { teamId: teamId ?? null, guest: false, userId: requestedUserId, wrapper: detail.key.encrypted_embed_key });
  await refreshAppsGeneratedAssetUrls([...detail.children, ...(detail.linked || [])].map((row) => row.embed_id), teamId, requestedUserId);
}

/** Rewrap guest keys for Personal and retry exact same IDs until upload succeeds. */
export async function promoteGuestAppsResults(): Promise<number> {
  const userId = get(userProfile).user_id;
  if (!userId) throw new Error("Personal account is unavailable for guest Apps promotion");
  assertSameAuthenticatedUser(userId);
  let promoted = 0;
  for (const record of await guestRecords()) {
    assertSameAuthenticatedUser(userId);
    const key = await unwrapAnonymousChatKey(record.encrypted_embed_key);
    if (!key) continue;
    const wrapped = await wrapEmbedKeyWithMasterKey(key);
    if (!wrapped) throw new Error("Personal key is unavailable for guest Apps results");
    assertSameAuthenticatedUser(userId);
    await uploadGraph({ ...record, encrypted_embed_key: wrapped, team_id: undefined }, userId);
    assertSameAuthenticatedUser(userId);
    await deleteGuest(record.root_embed_id);
    promoted++;
  }
  return promoted;
}
