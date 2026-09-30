import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

vi.mock('../../stores/userProfile', async () => {
  const { writable } = await import('svelte/store');
  return { userProfile: writable({ user_id: 'test-account' }) };
});
vi.mock('../../config/api', () => ({ getApiEndpoint: (path: string) => `https://api.test${path}` }));

import { WorkspaceQueryCache, WorkspaceCacheDiscardedError } from '../workspaceQueryCache';
import { invalidateWorkspaceCaches } from '../workspaceCacheLifecycle';

function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((complete) => { resolve = complete; });
  return { promise, resolve };
}

describe('account-scoped workspace projections', () => {
  beforeEach(() => { vi.useFakeTimers(); vi.setSystemTime(1000); invalidateWorkspaceCaches(); });
  afterEach(() => { vi.useRealTimers(); });

  // contract-test: infrastructure
  it('deduplicates identical queries and treats an empty result as fresh data', async () => {
    const cache = new WorkspaceQueryCache<string[]>();
    const result = deferred<string[]>();
    const loader = vi.fn(() => result.promise);
    const first = cache.load('owner/list', loader);
    const second = cache.load('owner/list', loader);
    await Promise.resolve();
    expect(loader).toHaveBeenCalledTimes(1);
    result.resolve([]);
    expect(await first).toEqual([]);
    expect(await second).toEqual([]);
    expect(cache.peek('owner/list')).toEqual([]);
    expect(await cache.load('owner/list', loader)).toEqual([]);
    expect(loader).toHaveBeenCalledTimes(1);
  });

  // contract-test: infrastructure
  it('retains useful stale content while a refresh is held, then publishes the update', async () => {
    const cache = new WorkspaceQueryCache<string>({ ttlMs: 60_000 });
    cache.set('team-a/list', 'previous');
    vi.setSystemTime(61_001);
    const result = deferred<string>();
    const loader = vi.fn(() => result.promise);
    const listener = vi.fn();
    cache.subscribe(listener);
    expect(await cache.load('team-a/list', loader)).toBe('previous');
    expect(cache.peek('team-a/list')).toBe('previous');
    result.resolve('updated');
    await vi.waitFor(() => expect(cache.peek('team-a/list')).toBe('updated'));
    expect(listener).toHaveBeenCalledTimes(1);
  });

  // contract-test: infrastructure
  it('does not let a slow read overwrite a newer mutation or resurrect a deletion', async () => {
    const cache = new WorkspaceQueryCache<string>();
    const result = deferred<string>();
    const request = cache.load('task-a', () => result.promise);
    const assertion = expect(request).rejects.toBeInstanceOf(WorkspaceCacheDiscardedError);
    await Promise.resolve();
    cache.set('task-a', 'newer');
    result.resolve('old');
    await assertion;
    expect(cache.peek('task-a')).toBe('newer');
    const deleted = deferred<string>();
    const old = cache.load('task-a', () => deleted.promise, { force: true });
    const deletion = expect(old).rejects.toBeInstanceOf(WorkspaceCacheDiscardedError);
    await Promise.resolve();
    cache.invalidate('task-a');
    deleted.resolve('deleted record');
    await deletion;
    expect(cache.peek('task-a')).toBeUndefined();
  });

  // contract-test: infrastructure
  it('fences account changes and clears a different key epoch synchronously', async () => {
    let scope = 'account-a';
    const cache = new WorkspaceQueryCache<string>({ scope: () => scope });
    cache.set('list', 'private-a');
    const result = deferred<string>();
    const request = cache.load('list', () => result.promise, { force: true });
    const assertion = expect(request).rejects.toBeInstanceOf(WorkspaceCacheDiscardedError);
    await Promise.resolve();
    scope = 'account-b';
    expect(cache.peek('list')).toBeUndefined();
    result.resolve('private-a');
    await assertion;
    cache.set('list', 'private-b');
    invalidateWorkspaceCaches();
    expect(cache.peek('list')).toBeUndefined();
  });

  // contract-test: infrastructure
  it('bounds retained payloads and keeps different team/filter keys independent', async () => {
    const cache = new WorkspaceQueryCache<string>({ maxEntries: 2, maxBytes: 1024 });
    cache.set('team-a/filter-a', 'a');
    cache.set('team-b/filter-a', 'b');
    cache.set('team-a/filter-b', 'c');
    expect(cache.peek('team-a/filter-a')).toBeUndefined();
    expect(cache.peek('team-b/filter-a')).toBe('b');
    cache.set('oversized', 'x'.repeat(1024));
    expect(cache.peek('oversized')).toBeUndefined();
  });

  // contract-test: infrastructure
  it('allows a subscriber to read the cache during an account reset without recursion', () => {
    let scope = 'a';
    const cache = new WorkspaceQueryCache<string>({ scope: () => scope });
    cache.set('list', 'a');
    cache.subscribe(() => cache.peek('list'));
    scope = 'b';
    expect(cache.peek('list')).toBeUndefined();
  });

  // contract-test: infrastructure
  it('reports a failed background refresh while retaining the last valid content', async () => {
    const cache = new WorkspaceQueryCache<string>({ ttlMs: 10 });
    cache.set('list', 'valid');
    vi.setSystemTime(1011);
    const error = new Error('Offline');
    const log = vi.spyOn(console, 'error').mockImplementation(() => {});
    expect(await cache.load('list', async () => { throw error; })).toBe('valid');
    await vi.waitFor(() => expect(cache.getError('list')).toBe(error));
    expect(cache.peek('list')).toBe('valid');
    expect(await cache.load('list', async () => 'recovered', { force: true })).toBe('recovered');
    expect(cache.getError('list')).toBeUndefined();
    log.mockRestore();
  });
});
