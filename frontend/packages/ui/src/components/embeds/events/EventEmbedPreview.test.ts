import { mount, tick, unmount } from 'svelte';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { chatSyncService } from '../../../services/chatSyncService';
import EventEmbedPreview from './EventEmbedPreview.svelte';

const mocks = vi.hoisted(() => ({ resolve: vi.fn(), decode: vi.fn(), request: vi.fn() }));
vi.mock('@repo/ui', async () => {
  const { readable } = await import('svelte/store');
  return { text: readable((key: string) => key) };
});
vi.mock('../../../services/embedResolver', () => ({
  resolveEmbed: mocks.resolve, decodeToonContent: mocks.decode, requestEmbedFromServerOnce: mocks.request,
}));
vi.mock('../../../services/chatSyncService', () => ({ chatSyncService: new EventTarget() }));
vi.mock('../../../services/directChatService', () => ({ startDirectChatIdentityEnrollment: vi.fn() }));
vi.mock('../BasicInfosBar.svelte', () => ({ default: () => {} }));
vi.mock('../../Icon.svelte', () => ({ default: () => {} }));
vi.mock('../../../stores/appSettingsMemoriesStore', () => ({ appSettingsMemoriesStore: {
  subscribe: (run: (value: unknown) => void) => { run({ entriesByApp: new Map() }); return () => {}; },
} }));

const eventId = 'deferred-event-reference';
const event = { type: 'event_result', title: 'Community AI Hack', date_start: '2026-11-14T09:00:00Z',
  timezone: 'UTC', organizer_name: 'Community Builders', image_url: '/favicon.png', rsvp_count: '42' };
let component: ReturnType<typeof mount> | undefined;
let target: HTMLElement;
beforeEach(() => {
  vi.clearAllMocks();
  component = undefined;
  mocks.resolve.mockResolvedValue(null);
  mocks.decode.mockResolvedValue(event);
  target = document.createElement('div'); document.body.append(target);
});
afterEach(async () => { if (component) await unmount(component); target.remove(); vi.useRealTimers(); });
async function preview() {
  component = mount(EventEmbedPreview, { target,
    props: { id: eventId, event: { embed_id: eventId }, onFullscreen: () => {} } });
  await tick();
  await vi.waitFor(() => expect(mocks.resolve).toHaveBeenCalled());
}
function available() { mocks.resolve.mockResolvedValue({ status: 'finished', content: 'saved-event' }); }
function update(id = eventId) {
  chatSyncService.dispatchEvent(new CustomEvent('embedUpdated', { detail: { embed_id: id, status: 'finished' } }));
}
function expectHydrated() {
  expect(target.textContent).toContain(event.title);
  expect(target.textContent).toContain('Community Builders');
  expect(target.textContent).toContain('42');
  expect(target.querySelector('img')?.getAttribute('src')).toContain('/favicon.png');
}

// contract-test: supporting surface=gui.web assertions=events-search.surface-parity,chats.sync.key-gated-recovery
it('hydrates a reply card after an initial miss and ignores unrelated updates', async () => {
  await preview();
  expect(target.querySelector('[data-status="processing"]')).not.toBeNull();
  available(); update('unrelated-event'); await tick();
  expect(target.textContent).not.toContain(event.title);
  update();
  await vi.waitFor(expectHydrated);
  expect(target.querySelector('[data-status="finished"]')).not.toBeNull();
  await unmount(component!); component = undefined; mocks.resolve.mockClear(); update(); await tick();
  expect(mocks.resolve).not.toHaveBeenCalled();
});

// contract-test: supporting surface=gui.web assertions=events-search.surface-parity,chats.sync.key-gated-recovery
it('uses the bounded content retry when the key becomes readable without another event', async () => {
  vi.useFakeTimers();
  await preview(); available();
  await vi.advanceTimersByTimeAsync(2000); await tick();
  expectHydrated();
  const reads = mocks.resolve.mock.calls.length;
  await vi.advanceTimersByTimeAsync(20_000);
  expect(mocks.resolve).toHaveBeenCalledTimes(reads);
});
