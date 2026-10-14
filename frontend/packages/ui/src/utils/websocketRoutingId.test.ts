import { beforeEach, describe, expect, it, vi } from 'vitest';

let nextId = 0;
vi.mock('uuid', () => ({ v4: () => `document-${++nextId}` }));

describe('WebSocket routing identity', () => {
  beforeEach(() => {
    nextId = 0;
    vi.resetModules();
  });

  // contract-test: supporting surface=gui.web assertions=auth.session.lifecycle
  it('keeps one ID across reconnects, then gives a new document its own ID', async () => {
    const first = await import('./websocketRoutingId');
    expect(first.getWebSocketRoutingId()).toBe('document-1');
    expect(first.getWebSocketRoutingId()).toBe('document-1');

    vi.resetModules();
    const second = await import('./websocketRoutingId');
    expect(second.getWebSocketRoutingId()).toBe('document-2');
  });
});
