// Shared, bounded projections for recently visited web workspaces.
// Memory only: domain services own decryption, permissions and query membership.
// Exact keys identify filters; account/team/key epochs isolate tab sessions.
// Fresh data avoids duplicate reads; stale data remains usable during refresh.
// Pending request identity prevents old responses from undoing local mutations.
import { get } from 'svelte/store';
import { userProfile } from '../stores/userProfile';
import { getActiveTeamContextSnapshot } from '../stores/teamStore';
import { getApiEndpoint } from '../config/api';
import { BoundedCache } from '../utils/boundedCache';
import { getWorkspaceCacheEpoch, registerWorkspaceCacheClear } from './workspaceCacheLifecycle';

interface Entry<T> { value: T; fetchedAt: number }
interface Options {
  ttlMs?: number;
  maxEntries?: number;
  maxBytes?: number;
  /** Injection for focused tests; production identity is never caller-supplied. */
  scope?: () => string | null;
}

export function getWorkspaceCacheIdentity(): string | null {
  const id = get(userProfile).user_id;
  const team = getActiveTeamContextSnapshot();
  return id ? `${getApiEndpoint('/v1')}|${id}|${team.teamId ?? ''}|${team.epoch}|${getWorkspaceCacheEpoch()}` : null;
}

export class WorkspaceCacheDiscardedError extends Error {
  constructor() { super('Workspace request superseded by an identity or data change'); }
}

/** Recoverable decrypted projections, confined to this tab and account/key epoch.
 * Exact query keys must include team and every server filter. No disk writes.
 */
export class WorkspaceQueryCache<T> {
  private readonly data: BoundedCache<string, Entry<T>>;
  private readonly pending = new Map<string, Promise<T>>();
  private readonly errors = new BoundedCache<string, unknown>(64 * 1024, 64);
  private readonly listeners = new Set<() => void>();
  private scope: string | null = null;
  private generation = 0;
  private readonly scopeForRead: () => string | null;
  private readonly ttlMs: number;

  constructor(options: Options = {}) {
    this.data = new BoundedCache(options.maxBytes ?? 8 * 1024 * 1024, options.maxEntries ?? 64);
    this.ttlMs = options.ttlMs ?? 60_000;
    this.scopeForRead = options.scope ?? getWorkspaceCacheIdentity;
    registerWorkspaceCacheClear(() => this.clear());
  }

  private checkScope(): string | null {
    const current = this.scopeForRead();
    if (current !== this.scope) { this.scope = current; this.clear(); }
    return current;
  }

  peek(key: string): T | undefined {
    if (!this.checkScope()) return undefined;
    return this.data.get(key)?.value;
  }

  isFresh(key: string): boolean {
    if (!this.checkScope()) return false;
    const entry = this.data.get(key);
    return entry !== undefined && Date.now() - entry.fetchedAt < this.ttlMs;
  }

  getError(key: string): unknown {
    if (!this.checkScope()) return undefined;
    return this.errors.get(key);
  }

  set(key: string, value: T): void {
    if (!this.checkScope()) return;
    // A successful local write supersedes the older read of this key, without
    // discarding unrelated concurrent entity requests.
    this.pending.delete(key);
    this.errors.delete(key);
    this.data.set(key, { value, fetchedAt: Date.now() });
    this.notify();
  }

  /** Mutation invalidation removes entries, so deleted rows cannot be reused. */
  invalidate(key?: string): void {
    if (key === undefined) {
      this.generation += 1;
      this.pending.clear();
      this.data.clear();
      this.errors.clear();
    } else {
      this.pending.delete(key);
      this.data.delete(key);
      this.errors.delete(key);
    }
    this.notify();
  }

  clear(): void { this.invalidate(); }

  subscribe(listener: () => void): () => void {
    this.listeners.add(listener);
    return () => this.listeners.delete(listener);
  }

  private notify(): void { for (const listener of this.listeners) listener(); }

  async load(key: string, loader: () => Promise<T>, options: { force?: boolean } = {}): Promise<T> {
    const scope = this.checkScope();
    const cached = scope ? this.data.get(key) : undefined;
    if (cached && !options.force) {
      if (Date.now() - cached.fetchedAt >= this.ttlMs) {
        void this.fetch(key, loader, scope).catch((error) => {
          if (!(error instanceof WorkspaceCacheDiscardedError)) console.error('[WorkspaceCache] Refresh failed:', error);
        });
      }
      return cached.value;
    }
    return this.fetch(key, loader, scope);
  }

  private fetch(key: string, loader: () => Promise<T>, scope: string | null): Promise<T> {
    const existing = this.pending.get(key);
    if (existing) return existing;
    const generation = this.generation;
    const epoch = getWorkspaceCacheEpoch();
    const promise = Promise.resolve().then(() => {
      if (this.pending.get(key) !== promise || generation !== this.generation || epoch !== getWorkspaceCacheEpoch() || scope !== this.scopeForRead()) {
        throw new WorkspaceCacheDiscardedError();
      }
      return loader();
    }).then((value) => {
      if (this.pending.get(key) !== promise || generation !== this.generation || epoch !== getWorkspaceCacheEpoch() || scope !== this.scopeForRead()) {
        throw new WorkspaceCacheDiscardedError();
      }
      if (scope) this.data.set(key, { value, fetchedAt: Date.now() });
      this.errors.delete(key);
      this.notify();
      return value;
    }).catch((error) => {
      if (!(error instanceof WorkspaceCacheDiscardedError) && this.pending.get(key) === promise && scope === this.scopeForRead()) {
        this.errors.set(key, error);
        this.notify();
      }
      throw error;
    }).finally(() => {
      if (this.pending.get(key) === promise) this.pending.delete(key);
    });
    this.pending.set(key, promise);
    return promise;
  }
}
