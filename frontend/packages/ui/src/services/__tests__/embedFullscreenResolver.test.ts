import { describe, expect, it, vi } from 'vitest';

const mocks = vi.hoisted(() => ({ component: vi.fn(), reload: vi.fn() }));
vi.mock('../../components/embeds/business/BusinessCompanyFinancialsEmbedFullscreen.svelte', () => ({ default: () => {} }));
vi.mock('../../components/embeds/models3d/Model3DResultEmbedFullscreen.svelte', () => ({ default: () => {} }));
vi.mock('../../components/embeds/maps/MapLocationEmbedFullscreen.svelte', () => ({
  get default() { return mocks.component(); },
}));
vi.mock('../../utils/chunkErrorHandler', () => ({
  isChunkLoadError: (error: Error) => error.message.includes('module'),
  logChunkLoadError: vi.fn(),
  forcePageReload: mocks.reload,
}));

import { loadFullscreenComponent } from '../embedFullscreenResolver';

// contract-test: supporting surface=gui.web assertions=chats.rendering.inline-entity-interaction
describe('fullscreen lazy import recovery', () => {
  it('evicts failed imports, preserves the page, and caches successful retries', async () => {
    const component = () => {};
    mocks.component
      .mockImplementationOnce(() => { throw new Error('Importing a module script failed'); })
      .mockImplementationOnce(() => { throw new Error('Temporary load error'); })
      .mockReturnValue(component);
    expect(await loadFullscreenComponent('maps-place')).toBeNull();
    expect(mocks.reload).not.toHaveBeenCalled();
    expect(await loadFullscreenComponent('maps-place')).toBeNull();
    expect(await loadFullscreenComponent('maps-place')).toBe(component);
    expect(await loadFullscreenComponent('maps-place')).toBe(component);
    expect(mocks.component).toHaveBeenCalledTimes(3);
  });
});
