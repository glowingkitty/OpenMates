import { describe, expect, it, vi } from 'vitest';
import { loadChildrenWithRetry } from '../../childEmbedRetry';

describe('Hosting checked child hydration', () => {
  // contract-test: direct surface=gui.web assertions=hosting-domains.embeds.parent-child
  it('retains loaded siblings while a late child arrives, in parent reference order', async () => {
    const attempts = new Map<string, number>();
    const progress = vi.fn();
    const wait = vi.fn(async () => {});
    const children = await loadChildrenWithRetry({
      ids: ['late', 'early'],
      concurrency: 2,
      retryLimit: 8,
      load: async (id) => {
        attempts.set(id, (attempts.get(id) ?? 0) + 1);
        return id === 'late' && attempts.get(id)! < 3 ? null : { id };
      },
      isCurrent: () => true,
      wait,
      onProgress: progress,
    });

    expect(children).toEqual([{ id: 'late' }, { id: 'early' }]);
    expect(attempts.get('early')).toBe(1);
    expect(attempts.get('late')).toBe(3);
    expect(wait).toHaveBeenCalledTimes(2);
    expect(progress.mock.calls[0][0]).toEqual([{ id: 'early' }]);
  });

  // contract-test: supporting surface=gui.web assertions=hosting-domains.embeds.parent-child
  it('stops at the retry limit and stops a stale load after cancellation', async () => {
    const load = vi.fn(async () => null);
    const wait = vi.fn(async () => {});
    expect(await loadChildrenWithRetry({
      ids: ['missing'], concurrency: 2, retryLimit: 8, load, isCurrent: () => true,
      wait, onProgress: () => {},
    })).toEqual([]);
    expect(load).toHaveBeenCalledTimes(9);
    expect(wait).toHaveBeenCalledTimes(8);

    let current = true;
    const cancelledLoad = vi.fn(async () => null);
    expect(await loadChildrenWithRetry({
      ids: ['missing'], concurrency: 2, retryLimit: 8, load: cancelledLoad,
      isCurrent: () => current,
      wait: async () => { current = false; },
      onProgress: () => {},
    })).toBeNull();
    expect(cancelledLoad).toHaveBeenCalledTimes(1);
  });
});
