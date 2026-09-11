// @vitest-environment jsdom
import { beforeEach, expect, it, vi } from 'vitest';
const mocks = vi.hoisted(() => ({ get: vi.fn(), resolve: vi.fn(), mount: vi.fn(), cleanups: [] as (() => void)[], listeners: new Set<EventListener>() }));
vi.mock('../../../../../services/embedStore', () => ({ embedStore: { get: mocks.get } }));
vi.mock('../../../../../services/embedResolver', () => ({ resolveEmbed: mocks.resolve }));
vi.mock('../../../../../services/chatSyncService', () => ({ chatSyncService: {
  addEventListener: (_type: string, listener: EventListener) => mocks.listeners.add(listener),
  removeEventListener: (_type: string, listener: EventListener) => mocks.listeners.delete(listener),
} }));
vi.mock('../../../../../stores/authStore', () => ({ authStore: { subscribe: (run: (v: unknown) => void) => { run({ isAuthenticated: true }); return () => {}; } } }));
vi.mock('../mountedEmbedLifecycle', () => ({ mount: mocks.mount, unmount: vi.fn(), disposeEmbedTree: vi.fn(), isEmbedTargetDisposed: () => false, onEmbedCleanup: (_target: Node, callback: () => void) => mocks.cleanups.push(callback) }));
vi.mock('../../../../embeds/audio/RecordingEmbedPreview.svelte', () => ({ default: {} }));
import { RecordingRenderer } from '../RecordingRenderer';

beforeEach(() => { vi.clearAllMocks(); mocks.listeners.clear(); mocks.cleanups.length = 0; mocks.mount.mockReturnValue({}); });
// contract-test: supporting surface=gui.web assertions=chats.local-state.precedence
it('recovers transcript on late embed delivery and releases the listener on disposal', async () => {
  mocks.get.mockResolvedValue(null);
  mocks.resolve.mockResolvedValue(null);
  const content = document.createElement('div');
  const renderer = new RecordingRenderer();
  await renderer.render({ content, attrs: { id: 'recording', type: 'recording', contentRef: 'embed:recording', status: 'finished' } } as Parameters<RecordingRenderer['render']>[0]);
  expect(mocks.listeners.size).toBe(1);
  mocks.get.mockResolvedValue({ content: JSON.stringify({ transcript: 'Recovered recording transcript', duration: '00:05' }) });
  for (const listener of [...mocks.listeners]) listener(new CustomEvent('embedUpdated', { detail: { embed_id: 'recording' } }));
  await vi.waitFor(() => expect(mocks.mount.mock.calls.at(-1)?.[1].props.transcript).toBe('Recovered recording transcript'));
  expect(mocks.listeners.size).toBe(1);
  for (const cleanup of mocks.cleanups) cleanup();
  expect(mocks.listeners.size).toBe(0);
});
