// @vitest-environment jsdom
import { mount, tick, unmount } from 'svelte';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';

const mocks = vi.hoisted(() => ({
  get: vi.fn(),
  resolve: vi.fn(),
  request: vi.fn(),
}));
vi.mock('../../../services/embedStore', () => ({ embedStore: { get: mocks.get } }));
vi.mock('../../../services/embedResolver', () => ({
  resolveEmbed: mocks.resolve,
  requestEmbedFromServerOnce: mocks.request,
  decodeToonContent: vi.fn(),
}));
vi.mock('../../../services/chatSyncService', () => ({ chatSyncService: new EventTarget() }));
vi.mock('../BasicInfosBar.svelte', () => ({ default: () => {} }));
vi.mock('../../Icon.svelte', () => ({ default: () => {} }));
vi.mock('../../../stores/appSettingsMemoriesStore', () => ({
  appSettingsMemoriesStore: {
    subscribe: (run: (value: unknown) => void) => { run({ entriesByApp: new Map() }); return () => {}; },
  },
}));

import UnifiedEmbedPreview from '../UnifiedEmbedPreview.svelte';

const mounted: Array<{ component: ReturnType<typeof mount>; target: HTMLElement }> = [];
beforeEach(() => {
  vi.clearAllMocks();
  mocks.get.mockResolvedValue(undefined);
  mocks.resolve.mockResolvedValue(null);
  mocks.request.mockResolvedValue(true);
});
afterEach(async () => {
  for (const { component, target } of mounted) {
    await unmount(component);
    target.remove();
  }
  mounted.length = 0;
  vi.useRealTimers();
});

function mountPreview(id: string, localOnly: boolean) {
  const target = document.createElement('div');
  document.body.appendChild(target);
  const component = mount(UnifiedEmbedPreview, { target, props: {
    id, localOnly, appId: 'images', skillId: 'view', skillIconName: 'image',
    status: 'processing', skillName: 'Image', onFullscreen: () => {},
    onEmbedDataUpdated: vi.fn(),
  } });
  mounted.push({ component, target });
}

// contract-test: supporting surface=gui.web assertions=teams.collaboration.realtime-team-sync
it('reads a draft preview locally without requesting a server embed', async () => {
  vi.useFakeTimers();
  mountPreview('draft-only-id', true);
  await vi.advanceTimersByTimeAsync(0);
  await tick();
  expect(mocks.get).toHaveBeenCalledWith('embed:draft-only-id');
  await vi.advanceTimersByTimeAsync(15_000);
  expect(mocks.resolve).not.toHaveBeenCalled();
  expect(mocks.request).not.toHaveBeenCalled();
});

// contract-test: supporting surface=gui.web assertions=teams.collaboration.realtime-team-sync
it('retains stale server recovery for a persisted embed', async () => {
  vi.useFakeTimers();
  mountPreview('persisted-id', false);
  await vi.advanceTimersByTimeAsync(0);
  await tick();
  expect(mocks.resolve).toHaveBeenCalledWith('persisted-id');
  await vi.advanceTimersByTimeAsync(5_000);
  expect(mocks.request).toHaveBeenCalledWith('persisted-id', 'preview-stale-recovery');
});

// contract-test: supporting surface=gui.web assertions=teams.collaboration.realtime-team-sync
it('recovers missing content from an existing persisted head', async () => {
  mocks.resolve.mockResolvedValue({ status: 'finished', content: '' });
  mountPreview('finished-id', false);
  await vi.waitFor(() => expect(mocks.request).toHaveBeenCalledWith('finished-id', 'preview-content-recovery'));
});
