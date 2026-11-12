import { describe, expect, it } from 'vitest';
import { formatEmbedProgress, nextEmbedProgress, parseEmbedProgress } from './embedProgress';

const t = (key: string, options?: { values: Record<string, string | number> }) =>
  `${key}${options ? JSON.stringify(options.values) : ''}`;

describe('embed progress', () => {
  // contract-test: supporting surface=gui.web assertions=app-skills.progress.live-status
  it('parses valid frames and rejects malformed ones', () => {
    expect(parseEmbedProgress({ sources_total: 4, sources_done: 2, result_count: 17, seq: 3 }))
      .toEqual({ sources_total: 4, sources_done: 2, result_count: 17, seq: 3 });
    expect(parseEmbedProgress(undefined)).toBeNull();
    expect(parseEmbedProgress({ sources_total: 0, sources_done: 0, result_count: 0, seq: 1 })).toBeNull();
    expect(parseEmbedProgress({ sources_total: '4', sources_done: 2, result_count: 1, seq: 1 })).toBeNull();
  });

  // contract-test: supporting surface=gui.web assertions=app-skills.progress.live-status
  it('lets a higher seq win and ignores a lower or equal one', () => {
    const a = { sources_total: 4, sources_done: 1, result_count: 3, seq: 2 };
    const b = { ...a, sources_done: 2, seq: 3 };
    expect(nextEmbedProgress(a, b)).toBe(b);
    expect(nextEmbedProgress(b, a)).toBe(b);
    expect(nextEmbedProgress(b, { ...a, seq: 3 })).toBe(b);
    expect(nextEmbedProgress(b, null)).toBe(b);
  });

  // contract-test: supporting surface=gui.web assertions=app-skills.progress.live-status
  it('formats multi source, single source and zero result lines', () => {
    expect(formatEmbedProgress({ sources_total: 4, sources_done: 2, result_count: 17, seq: 1 }, t))
      .toBe('2/4 · embeds.progress_results{"count":17}');
    expect(formatEmbedProgress({ sources_total: 4, sources_done: 0, result_count: 0, seq: 1 }, t))
      .toBe('embeds.progress_searching_sources{"total":4,"done":0}');
    expect(formatEmbedProgress({ sources_total: 1, sources_done: 0, result_count: 17, seq: 1 }, t))
      .toBe('embeds.progress_results{"count":17}');
    expect(formatEmbedProgress({ sources_total: 1, sources_done: 0, result_count: 1, seq: 1 }, t))
      .toBe('embeds.progress_result_one');
    expect(formatEmbedProgress({ sources_total: 1, sources_done: 0, result_count: 0, seq: 1 }, t))
      .toBe('embeds.progress_searching');
  });
});
