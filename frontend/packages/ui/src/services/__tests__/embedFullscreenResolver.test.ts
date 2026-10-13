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

import { loadFullscreenComponent, resolveRegistryKey } from '../embedFullscreenResolver';

// contract-test: supporting surface=gui.web assertions=chats.rendering.inline-entity-interaction
describe('fullscreen registry routing', () => {
  // contract-test: supporting surface=gui.web assertions=chats.rendering.inline-entity-interaction
  it('opens a generated invocation as a group and its historical asset on the leaf viewer', () => {
    expect(resolveRegistryKey('app_skill_use', {
      app_id: 'images', skill_id: 'generate', embed_ids: ['child-1', 'child-2'],
    })).toBe('app:images:generate');
    expect(resolveRegistryKey('app_skill_use', {
      app_id: 'images', skill_id: 'generate', files: { original: 'asset' },
    })).toBe('images-generated-image');
  });

  // contract-test: supporting surface=gui.web assertions=app-skills.media.parent-children-and-attribution
  it.each([
    ['images', 'generate_draft', 'images-generated-image'],
    ['images', 'vectorize', 'images-generated-image'],
    ['audio', 'generate', 'audio-generated-audio'],
    ['audio', 'speak', 'audio-generated-audio'],
    ['music', 'generate', 'music-generated-music'],
    ['videos', 'generate', 'videos-generated-video'],
    ['models3d', 'generate', 'models3d-generated-model'],
  ])('routes %s.%s parent and historical asset separately', (appId, skillId, childKey) => {
    expect(resolveRegistryKey('app_skill_use', {
      app_id: appId, skill_id: skillId, embed_ids: ['child-1'],
    })).toBe(`app:${appId}:${skillId}`);
    expect(resolveRegistryKey('app_skill_use', {
      app_id: appId, skill_id: skillId, files: { original: 'asset' },
    })).toBe(childKey);
  });

  // contract-test: supporting surface=gui.web assertions=app-skills.media.parent-children-and-attribution
  it('recognizes a historical snake-case preview URL and preserves Remotion editing', () => {
    expect(resolveRegistryKey('app_skill_use', {
      app_id: 'images', skill_id: 'generate', preview_image_url: '/asset.png',
    })).toBe('images-generated-image');
    expect(resolveRegistryKey('app_skill_use', {
      app_id: 'videos', skill_id: 'create', files: { original: 'rendered.mp4' },
    })).toBe('app:videos:create');
  });

  // contract-test: supporting surface=gui.web assertions=chats.rendering.inline-entity-interaction
  it.each(['generate', 'speak'])('routes generated audio payloads to the asset viewer for audio.%s', (skillId) => {
    expect(resolveRegistryKey('audio', {
      type: 'audio', app_id: 'audio', skill_id: skillId,
    })).toBe('audio-generated-audio');
  });

  // contract-test: supporting surface=gui.web assertions=chats.rendering.inline-entity-interaction
  it('uses app/skill metadata in stored TOON content for generic audio', () => {
    expect(resolveRegistryKey('audio', {
      content: 'app_id: audio\nskill_id: generate\ntype: audio',
    })).toBe('audio-generated-audio');
  });

  // contract-test: supporting surface=gui.web assertions=chats.rendering.inline-entity-interaction
  it('preserves registered direct fullscreen types ahead of the app fallback', () => {
    expect(resolveRegistryKey('audio-recording', {
      app_id: 'audio', skill_id: 'generate',
    })).toBe('recording');
  });

  // contract-test: supporting surface=gui.web assertions=chats.rendering.inline-entity-interaction
  it('preserves child fullscreen routing ahead of the parent app fallback', () => {
    expect(resolveRegistryKey('location', {
      app_id: 'fitness', skill_id: 'search_locations',
    })).toBe('fitness-location');
  });

  // contract-test: supporting surface=gui.web assertions=chats.rendering.inline-entity-interaction
  it('preserves explicit parent app-skill fullscreen routing', () => {
    expect(resolveRegistryKey('app_skill_use', {
      app_id: 'fitness', skill_id: 'search_locations',
    })).toBe('app:fitness:search_locations');
  });

  // contract-test: supporting surface=gui.web assertions=chats.rendering.inline-entity-interaction
  it('keeps unsupported types unresolved without a registered app/skill fallback', () => {
    expect(resolveRegistryKey('audio')).toBe('audio');
    expect(resolveRegistryKey('audio', { app_id: 'audio' })).toBe('audio');
    expect(resolveRegistryKey('audio', {
      app_id: 'audio', skill_id: 'unknown',
    })).toBe('audio');
  });
});

// contract-test: supporting surface=gui.web assertions=chats.rendering.inline-entity-interaction
describe('fullscreen lazy import recovery', () => {
  it('evicts failed imports, preserves the page, and caches successful retries', async () => {
    const component = () => {};
    mocks.component
      .mockImplementationOnce(() => { throw new Error('Importing a module script failed'); })
      .mockImplementationOnce(() => { throw new Error('Temporary load error'); })
      .mockReturnValue(component);
    await expect(loadFullscreenComponent('maps-place')).rejects.toThrow('Importing a module script failed');
    expect(mocks.reload).not.toHaveBeenCalled();
    expect(await loadFullscreenComponent('maps-place')).toBeNull();
    expect(await loadFullscreenComponent('maps-place')).toBe(component);
    expect(await loadFullscreenComponent('maps-place')).toBe(component);
    expect(mocks.component).toHaveBeenCalledTimes(3);
  });
});
