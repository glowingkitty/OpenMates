// The helpline card is created on the server just before the answer streams, so its
// payload can reach the client after the node rendered (assertion wellbeing-support.helpline-card).
import { beforeEach, expect, it, vi } from 'vitest';
const mocks = vi.hoisted(() => ({ resolve: vi.fn(), decode: vi.fn(), mount: vi.fn(), cleanups: [] as (() => void)[], listeners: new Set<EventListener>() }));
vi.mock('../../../../../services/embedResolver', () => ({ resolveEmbed: mocks.resolve, decodeToonContent: mocks.decode }));
vi.mock('../../../../../services/chatSyncService', () => ({ chatSyncService: {
  addEventListener: (_type: string, listener: EventListener) => mocks.listeners.add(listener),
  removeEventListener: (_type: string, listener: EventListener) => mocks.listeners.delete(listener),
} }));
vi.mock('../mountedEmbedLifecycle', () => ({ mount: mocks.mount, unmount: vi.fn(), disposeEmbedTree: vi.fn(), onEmbedCleanup: (_target: Node, callback: () => void) => mocks.cleanups.push(callback) }));
vi.mock('../../../../embeds/wellbeing/HelplineCard.svelte', () => ({ default: {} }));
import { HelplinesRenderer } from '../HelplinesRenderer';

const PAYLOAD = { emergency_number: '112', directory_url: 'https://example.org/helplines', country: 'DE', language: 'en', lines: [], source: 'emergency_only' };
const context = (content: HTMLElement) => ({ content, attrs: { id: 'card', type: 'helplines', contentRef: 'embed:card', status: 'finished' } }) as unknown as Parameters<HelplinesRenderer['render']>[0];
const fire = (embedId: string) => { for (const listener of [...mocks.listeners]) listener(new CustomEvent('embedUpdated', { detail: { embed_id: embedId } })); };

beforeEach(() => { vi.clearAllMocks(); mocks.listeners.clear(); mocks.cleanups.length = 0; mocks.mount.mockReturnValue({}); });

// contract-test: supporting surface=gui.web assertions=wellbeing-support.helpline-card
it('renders the card once its payload arrives after the node rendered', async () => {
  mocks.resolve.mockResolvedValue(null);
  const content = document.createElement('div');
  await new HelplinesRenderer().render(context(content));
  expect(mocks.mount).not.toHaveBeenCalled();
  expect(mocks.listeners.size).toBe(1);

  fire('other-embed');
  expect(mocks.listeners.size).toBe(1);

  mocks.resolve.mockResolvedValue({ content: 'toon' });
  mocks.decode.mockResolvedValue(PAYLOAD);
  fire('card');
  await vi.waitFor(() => expect(mocks.mount).toHaveBeenCalledTimes(1));
  expect(mocks.mount.mock.calls[0][1].props.emergency_number).toBe('112');
  expect(mocks.listeners.size).toBe(0);
});

// contract-test: supporting surface=gui.web assertions=wellbeing-support.helpline-card
it('stops waiting after a bounded number of attempts and releases the listener on disposal', async () => {
  mocks.resolve.mockResolvedValue(null);
  const content = document.createElement('div');
  await new HelplinesRenderer().render(context(content));
  for (let attempt = 0; attempt < 5; attempt += 1) {
    fire('card');
    await new Promise((resolve) => setTimeout(resolve, 0));
  }
  expect(mocks.mount).not.toHaveBeenCalled();
  expect(mocks.listeners.size).toBe(0);
  expect(mocks.resolve).toHaveBeenCalledTimes(4);

  const other = document.createElement('div');
  await new HelplinesRenderer().render(context(other));
  expect(mocks.listeners.size).toBe(1);
  for (const cleanup of mocks.cleanups) cleanup();
  expect(mocks.listeners.size).toBe(0);
});
