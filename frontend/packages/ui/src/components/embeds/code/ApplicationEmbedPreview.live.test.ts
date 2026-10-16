import { mount, tick, unmount } from 'svelte';
import { describe, expect, it, vi } from 'vitest';
const mocks = vi.hoisted(() => ({ autoStart: vi.fn(), decrypt: vi.fn(), cached: vi.fn() }));
vi.mock('../UnifiedEmbedPreview.svelte', async () => ({ default: (await import('../health/__tests__/HealthAppointmentShell.svelte')).default }));
vi.mock('@repo/ui', async () => ({ text: (await import('svelte/store')).readable((key: string) => key) }));
vi.mock('../../../stores/authStore', async () => ({ authStore: (await import('svelte/store')).readable({ isAuthenticated: true }) }));
vi.mock('../../../demo_chats', () => ({ isPublicChat: () => false }));
vi.mock('../../../services/applicationPreviewService', () => ({ autoStartVisibleOwnerApplicationPreviewForEmbed: mocks.autoStart,
  getApplicationPreviewStatus: vi.fn() }));
vi.mock('../images/imageEmbedCrypto', () => ({ fetchAndDecryptImage: mocks.decrypt, getCachedImageUrl: mocks.cached,
  createImageUrlOwner: () => ({ retain: vi.fn(), release: vi.fn(), destroy: vi.fn() }) }));
import ApplicationEmbedPreview from './ApplicationEmbedPreview.svelte';

describe('persisted encrypted application thumbnail', () => {
  // contract-test: supporting surface=gui.web assertions=app-skills.media.application-screenshot
  it('waits for the saved screenshot to decrypt without starting another sandbox', async () => {
    let complete!: () => void;
    mocks.cached.mockReturnValue(undefined);
    mocks.autoStart.mockReset();
    mocks.decrypt.mockImplementation(() => new Promise<void>(resolve => { complete = () => {
      mocks.cached.mockReturnValue('blob:fixture-image'); resolve();
    }; }));
    const target = document.createElement('div'); document.body.append(target);
    const component = mount(ApplicationEmbedPreview, { target, props: { id: 'application-fixture', chatId: 'chat-fixture', status: 'finished',
      latest_screenshot: { files: { preview: { s3_key: 'fixture-image', encryption: 'fixture' } }, aes_key: 'fixture-key', aes_nonce: 'fixture-nonce' },
      onFullscreen: () => {} } });
    try {
      await tick();
      expect(mocks.decrypt).toHaveBeenCalled(); expect(mocks.autoStart).not.toHaveBeenCalled();
      complete(); await tick(); await tick();
      expect(target.querySelector('img')?.getAttribute('src')).toBe('blob:fixture-image');
      expect(mocks.autoStart).not.toHaveBeenCalled();
    } finally { await unmount(component); target.remove(); }
  });
});
