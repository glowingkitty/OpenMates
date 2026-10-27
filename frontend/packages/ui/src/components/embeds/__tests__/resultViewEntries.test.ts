import { describe, expect, it } from 'vitest';
import { deduplicateResultViewEntries } from '../resultViewEntries';

function event(embedId: string, overrides: Record<string, unknown> = {}) {
  return {
    ref: embedId,
    embedId,
    category: 'event',
    status: 'ready' as const,
    highlighted: false,
    decodedContent: {
      title: 'Community AI evening',
      url: 'https://events.example.org/ai-evening',
      date_start: '2026-10-22T17:00:00Z',
      ...overrides,
    },
  };
}

// contract-test: supporting surface=gui.web assertions=chats.rendering.inline-entity-interaction
describe('results-view entry identity', () => {
  // contract-test: supporting surface=gui.web assertions=chats.rendering.inline-entity-interaction
  it('merges short-reference and UUID aliases without mutating cached highlights', () => {
    const first = { ...event('canonical-id'), ref: 'ai-evening-Ab1' };
    const alias = { ...event('canonical-id'), highlighted: true };
    const result = deduplicateResultViewEntries([first, alias]);
    expect(result).toHaveLength(1);
    expect(result[0]).toMatchObject({ ref: first.ref, highlighted: true });
    expect(first.highlighted).toBe(false);
  });

  // contract-test: supporting surface=gui.web assertions=chats.rendering.inline-entity-interaction
  it('merges the same event from different searches and equivalent timezone representations', () => {
    const first = event('search-one-child');
    const duplicate = {
      ...event('search-two-child', {
        url: 'https://events.example.org/ai-evening',
        date_start: '2026-10-22T19:00:00+02:00',
      }),
      highlighted: true,
    };
    expect(deduplicateResultViewEntries([first, duplicate, event('search-two-child')]))
      .toEqual([{ ...first, highlighted: true }]);
  });

  // contract-test: supporting surface=gui.web assertions=chats.rendering.inline-entity-interaction
  it('preserves different occurrences and different source links with identical titles', () => {
    const events = [
      event('first'),
      event('next-day', { date_start: '2026-10-23T17:00:00Z' }),
      event('other-event', { url: 'https://events.example.org/another-event' }),
      event('other-session', { url: 'https://events.example.org/ai-evening?session=2' }),
    ];
    expect(deduplicateResultViewEntries(events)).toEqual(events);
  });

  // contract-test: supporting surface=gui.web assertions=chats.rendering.inline-entity-interaction
  it('keeps results without a trustworthy event identity and non-event results', () => {
    const events = [
      event('no-url-one', { url: undefined }), event('no-url-two', { url: undefined }),
      event('invalid-date-one', { date_start: 'unknown' }), event('invalid-date-two', { date_start: 'unknown' }),
      { ...event('route-one'), category: 'route' }, { ...event('route-two'), category: 'route' },
    ];
    expect(deduplicateResultViewEntries(events)).toEqual(events);
  });

  // contract-test: supporting surface=gui.web assertions=chats.rendering.inline-entity-interaction
  it('prefers available content if another alias was still loading', () => {
    const ready = event('canonical-id');
    const loading = { ...ready, status: 'loading' as const, highlighted: true, decodedContent: null };
    expect(deduplicateResultViewEntries([loading, ready])).toEqual([{ ...ready, highlighted: true }]);
  });

  // contract-test: supporting surface=gui.web assertions=chats.rendering.inline-entity-interaction
  it('merges recovered aliases before comparing event identity across searches', () => {
    const ready = event('canonical-id');
    const loading = { ...ready, status: 'loading' as const, decodedContent: null };
    expect(deduplicateResultViewEntries([loading, event('other-search'), ready]))
      .toEqual([ready]);
  });
});
