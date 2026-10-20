// @vitest-environment jsdom
import { mount, tick, unmount } from 'svelte';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';

const mocks = vi.hoisted(() => ({
  get: vi.fn(),
  resolve: vi.fn(),
  request: vi.fn(),
  decode: vi.fn(),
}));
vi.mock('../../../services/embedStore', () => ({ embedStore: { get: mocks.get } }));
vi.mock('../../../services/embedResolver', () => ({
  resolveEmbed: mocks.resolve,
  requestEmbedFromServerOnce: mocks.request,
  decodeToonContent: mocks.decode,
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
import { chatSyncService } from '../../../services/chatSyncService';

const mounted: Array<{ component: ReturnType<typeof mount>; target: HTMLElement }> = [];
beforeEach(() => {
  vi.clearAllMocks();
  mocks.get.mockResolvedValue(undefined);
  mocks.resolve.mockResolvedValue(null);
  mocks.request.mockResolvedValue(true);
  mocks.decode.mockResolvedValue(null);
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
  const onEmbedDataUpdated = vi.fn();
  const component = mount(UnifiedEmbedPreview, { target, props: {
    id, localOnly, appId: 'images', skillId: 'view', skillIconName: 'image',
    status: 'processing', skillName: 'Image', onFullscreen: () => {},
    onEmbedDataUpdated,
  } });
  mounted.push({ component, target });
  return onEmbedDataUpdated;
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
  expect(mocks.resolve).toHaveBeenCalledWith('persisted-id', { chatId: null });
  await vi.advanceTimersByTimeAsync(5_000);
  expect(mocks.request).toHaveBeenCalledWith('persisted-id', 'preview-stale-recovery');
});

// contract-test: supporting surface=gui.web assertions=teams.collaboration.realtime-team-sync
it('recovers missing content from an existing persisted head', async () => {
  mocks.resolve.mockResolvedValue({ status: 'finished', content: '' });
  mountPreview('finished-id', false);
  await vi.waitFor(() => expect(mocks.request).toHaveBeenCalledWith('finished-id', 'preview-content-recovery'));
});

// contract-test: supporting surface=gui.web assertions=app-skills.execution.registered-validated,chats.rendering.assistant-document-convergence
it.each([['finished', 'error'], ['error', 'finished']] as const)(
  'uses decrypted %s envelope terminal status %s for child details', async (outerStatus, contentStatus) => {
    mocks.resolve.mockResolvedValue({ status: outerStatus, content: 'terminal-content' });
    const decodedContent = { app_id: 'fitness', skill_id: 'search_classes', status: contentStatus,
      error: contentStatus === 'error' ? 'The request timed out' : null, embed_ids: [] };
    mocks.decode.mockResolvedValue(decodedContent);
    const updated = mountPreview('terminal-execution', false);
    await vi.waitFor(() => expect(updated).toHaveBeenCalledWith({ status: contentStatus, decodedContent }));
    expect(mocks.request).not.toHaveBeenCalled();
  },
);

// contract-test: supporting surface=gui.web assertions=app-skills.execution.registered-validated,chats.rendering.assistant-document-convergence
it('settles mounted processing details when an encrypted failed execution arrives', async () => {
  mocks.resolve.mockResolvedValue({ status: 'processing', content: 'processing-content' });
  mocks.decode.mockResolvedValue({ status: 'processing' });
  const updated = mountPreview('live-terminal-execution', false);
  await vi.waitFor(() => expect(updated).toHaveBeenCalledWith({ status: 'processing', decodedContent: { status: 'processing' } }));
  const target = mounted.at(-1)!.target;
  expect(target.querySelector('[data-embed-status]')?.getAttribute('data-embed-status')).toBe('processing');
  updated.mockClear();
  const failed = { app_id: 'fitness', skill_id: 'search_classes', status: 'error', error: 'The request timed out', embed_ids: [] };
  mocks.resolve.mockResolvedValue({ status: 'error', content: 'encrypted-error-content' });
  mocks.decode.mockResolvedValue(failed);
  chatSyncService.dispatchEvent(new CustomEvent('embedUpdated', { detail: { embed_id: 'live-terminal-execution', status: 'error' } }));
  await vi.waitFor(() => expect(updated).toHaveBeenCalledWith({ status: 'error', decodedContent: failed }));
  await tick();
  const card = target.querySelector('[data-embed-status]');
  expect(card?.getAttribute('data-embed-status')).toBe('error');
  expect(card?.classList.contains('processing')).toBe(false);
  expect(mocks.request).not.toHaveBeenCalled();
});
