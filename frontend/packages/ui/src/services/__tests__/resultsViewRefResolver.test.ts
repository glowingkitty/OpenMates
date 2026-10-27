import { describe, expect, it, vi } from 'vitest';
import { resolveResultsViewRefToId } from '../resultsViewRefResolver';

describe('results-view reference validation', () => {
  // contract-test: supporting surface=gui.web assertions=public-example-chats.transcript.safe-rendering,public-example-chats.surface.semantic-parity
  it('rejects the copied WR7TN example and accepts the actual registered short parent', async () => {
    const parentId = '11111111-1111-4111-8111-111111111111';
    const parentRef = 'events-search-111111';
    const store = {
      resolveByRefDeep: vi.fn(async (ref: string) => ref === parentRef ? parentId : null),
      get: vi.fn(async () => undefined),
    };
    expect(await resolveResultsViewRefToId('events-search-12ab34', store)).toBeNull();
    expect(await resolveResultsViewRefToId(parentRef, store)).toBe(parentId);
  });

  // contract-test: supporting surface=gui.web assertions=public-example-chats.transcript.safe-rendering,public-example-chats.surface.semantic-parity
  it('accepts a late short reference once its real parent becomes available', async () => {
    const store = {
      resolveByRefDeep: vi.fn<(...args: string[]) => Promise<string | null>>().mockResolvedValue(null),
      get: vi.fn(async () => undefined),
    };
    expect(await resolveResultsViewRefToId('events-search-Ab1', store)).toBeNull();
    store.resolveByRefDeep.mockResolvedValue('11111111-1111-4111-8111-111111111111');
    expect(await resolveResultsViewRefToId('events-search-Ab1', store))
      .toBe('11111111-1111-4111-8111-111111111111');
  });

  // contract-test: supporting surface=gui.web assertions=public-example-chats.surface.semantic-parity
  it('preserves canonical UUID recovery and locally registered static IDs', async () => {
    const store = {
      resolveByRefDeep: vi.fn(async () => null),
      get: vi.fn(async (ref: string) => ref === 'embed:static-event' ? { title: 'Local event' } : undefined),
    };
    expect(await resolveResultsViewRefToId('11111111-1111-4111-8111-111111111111', store))
      .toBe('11111111-1111-4111-8111-111111111111');
    expect(await resolveResultsViewRefToId('static-event', store)).toBe('static-event');
  });
});
