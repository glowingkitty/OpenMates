/** Cache-first TUI workspace loading with fenced background refresh. */
import { createHash } from "node:crypto";

import { createTuiWorkspaceCache, type TuiWorkspaceCache } from "./tuiWorkspaceCache.js";
import type { OpenMatesSession } from "./storage.js";

export interface TuiCacheClient {
  apiUrl?: string;
  hasSession?: () => boolean;
  getSession?: () => OpenMatesSession;
}

export type TuiWorkspaceSource = "cache" | "sync";
type Publish<T> = (value: T, source: TuiWorkspaceSource) => void | Promise<void>;
type OnError = (error: unknown, hasCached: boolean) => void;

interface PendingFetch {
  key: string;
  context: string;
  generation: number;
  globalGeneration: number;
  promise: Promise<unknown>;
}
interface ClientState {
  pending: Map<string, PendingFetch>;
  generations: Map<string, number>;
  globalGeneration: number;
  cacheOperations: Promise<void>;
}

const states = new WeakMap<object, ClientState>();

function stateFor(client: object): ClientState {
  let state = states.get(client);
  if (!state) {
    state = { pending: new Map(), generations: new Map(), globalGeneration: 0, cacheOperations: Promise.resolve() };
    states.set(client, state);
  }
  return state;
}

function queueCacheOperation<T>(state: ClientState, operation: () => Promise<T>): Promise<T> {
  const result = state.cacheOperations.then(operation);
  state.cacheOperations = result.then(() => {}, () => {});
  return result;
}

function reportError(onError: OnError | undefined, error: unknown, hasCached: boolean): void {
  try { onError?.(error, hasCached); } catch { /* UI error reporting cannot reject a background task. */ }
}

function rawSessionFrom(client: TuiCacheClient): OpenMatesSession | null {
  if (typeof client.hasSession !== "function" || typeof client.getSession !== "function") return null;
  try {
    if (!client.hasSession()) return null;
    return client.getSession();
  } catch {
    return null;
  }
}

function sessionFrom(client: TuiCacheClient): OpenMatesSession | null {
  const session = rawSessionFrom(client);
  if (!session || typeof client.apiUrl !== "string" ||
      client.apiUrl.replace(/\/$/, "") !== session.apiUrl.replace(/\/$/, "")) return null;
  return session;
}

/** Client identity excludes rotating auth credentials but includes login lifetime. */
function identity(session: OpenMatesSession): string {
  return createHash("sha256").update(JSON.stringify([
    session.apiUrl, session.hashedEmail, session.activeTeamId ?? null,
    session.createdAt, session.masterKeyExportedB64,
  ])).digest("hex");
}

interface Context {
  token: string;
  cache: TuiWorkspaceCache | null;
  isCurrent: () => boolean;
}

function contextFor(client: TuiCacheClient): Context {
  const session = sessionFrom(client);
  if (!session) {
    const raw = rawSessionFrom(client);
    if (raw) {
      const token = `${identity(raw)}:${client.apiUrl ?? ""}`;
      return {
        token, cache: null,
        isCurrent: () => {
          const current = rawSessionFrom(client);
          return !!current && `${identity(current)}:${client.apiUrl ?? ""}` === token;
        },
      };
    }
    const hasSessionApi = typeof client.hasSession === "function" && typeof client.getSession === "function";
    return { token: "uncached", cache: null, isCurrent: () => !hasSessionApi };
  }
  const token = identity(session);
  const isCurrent = () => {
    const current = sessionFrom(client);
    return !!current && identity(current) === token;
  };
  try {
    const cache = createTuiWorkspaceCache(session, () => sessionFrom(client));
    return { token, cache: cache.isCurrent() ? cache : null, isCurrent };
  } catch {
    return { token, cache: null, isCurrent };
  }
}

function pendingFor<T>(
  client: TuiCacheClient,
  key: string,
  context: Context,
  fetch: () => Promise<T>,
): { promise: Promise<T>; isCurrent: () => boolean } {
  const state = stateFor(client);
  const generation = state.generations.get(key) ?? 0;
  const globalGeneration = state.globalGeneration;
  const token = `${context.token}\0${key}`;
  const isCurrent = () => context.isCurrent() &&
    (state.generations.get(key) ?? 0) === generation &&
    state.globalGeneration === globalGeneration;
  const existing = state.pending.get(token);
  if (existing && existing.generation === generation &&
      existing.globalGeneration === globalGeneration && isCurrent()) {
    return { promise: existing.promise as Promise<T>, isCurrent };
  }

  const promise = Promise.resolve().then(fetch).then(async value => {
    if (isCurrent() && context.cache) {
      try {
        await queueCacheOperation(state, () => isCurrent()
          ? context.cache!.set(key, value)
          : Promise.resolve(false));
      } catch { /* Network data still renders. */ }
    }
    return value;
  });
  const pending: PendingFetch = { key, context: context.token, generation, globalGeneration, promise };
  state.pending.set(token, pending);
  void promise.then(
    () => { if (state.pending.get(token) === pending) state.pending.delete(token); },
    () => { if (state.pending.get(token) === pending) state.pending.delete(token); },
  );
  return { promise, isCurrent };
}

/**
 * Publish a saved snapshot first, then refresh it. With a cold cache this waits
 * for fetch. With a warm cache it returns the snapshot while refresh continues.
 * A failed cold fetch reports the error and returns null.
 */
export async function loadCachedTuiWorkspace<T>(
  client: TuiCacheClient,
  key: string,
  fetch: () => Promise<T>,
  publish: Publish<T>,
  onError?: OnError,
): Promise<T | null> {
  const context = contextFor(client);
  let cached: T | null = null;
  if (context.cache) {
    try { cached = await context.cache.get<T>(key); }
    catch { /* A broken cache is a cold fetch. */ }
  }
  if (!context.isCurrent()) return null;
  if (cached !== null) {
    try { await publish(cached, "cache"); }
    catch (error) { reportError(onError, error, true); }
  }

  const { promise, isCurrent } = pendingFor(client, key, context, fetch);
  const deliver = async (): Promise<T | null> => {
    try {
      const value = await promise;
      if (!isCurrent()) return null;
      await publish(value, "sync");
      return value;
    } catch (error) {
      reportError(onError, error, cached !== null);
      return null;
    }
  };
  if (cached !== null) {
    void deliver();
    return cached;
  }
  return deliver();
}

/** Invalidation also rejects responses from already-running refreshes. */
export function captureTuiWorkspaceOwner(client:TuiCacheClient):()=>boolean {return contextFor(client).isCurrent;}

/** Read a saved list for mutation fan-out without triggering another fetch. */
export async function readCachedTuiWorkspace<T>(client:TuiCacheClient,key:string,ownerCurrent:()=>boolean=()=>true):Promise<T|null> {
  if(!ownerCurrent())return null;
  const context=contextFor(client);
  if(!context.cache)return null;
  try {const value=await context.cache.get<T>(key);return ownerCurrent()&&context.isCurrent()?value:null;}catch{return null;}
}

export async function invalidateCachedTuiWorkspace(client: TuiCacheClient, key?: string,ownerCurrent:()=>boolean=()=>true): Promise<boolean> {
  if(!ownerCurrent())return false;
  const state = stateFor(client);
  if (key === undefined) state.globalGeneration++;
  else state.generations.set(key, (state.generations.get(key) ?? 0) + 1);
  const context = contextFor(client);
  if (!context.cache) return false;
  try { return await queueCacheOperation(state, () => ownerCurrent()&&context.isCurrent()?context.cache!.invalidate(key):Promise.resolve(false)); }
  catch { return false; }
}

/** Persist an authoritative post-mutation list and fence older refreshes. */
export async function writeCachedTuiWorkspace<T>(client: TuiCacheClient, key: string, value: T,ownerCurrent:()=>boolean=()=>true): Promise<boolean> {
  if(!ownerCurrent())return false;
  const state = stateFor(client);
  state.generations.set(key, (state.generations.get(key) ?? 0) + 1);
  const context = contextFor(client);
  if (!context.cache) return false;
  try { return await queueCacheOperation(state, () => ownerCurrent()&&context.isCurrent()?context.cache!.set(key, value):Promise.resolve(false)); }
  catch { return false; }
}
