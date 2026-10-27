// @vitest-environment jsdom
import { beforeEach, expect, it, vi } from 'vitest';

const mocks = vi.hoisted(() => ({ mount: vi.fn() }));
vi.mock('../mountedEmbedLifecycle', () => ({
  mount: mocks.mount,
  unmount: vi.fn(),
  disposeEmbedTree: vi.fn(),
  onEmbedCleanup: vi.fn(),
}));
vi.mock('../../../../embeds/images/ImageEmbedPreview.svelte', () => ({ default: {} }));
vi.mock('../../../../../stores/authStore', () => ({
  authStore: { subscribe: (run: (value: unknown) => void) => { run({ isAuthenticated: true }); return () => {}; } },
}));
vi.mock('../../../../../services/embedResolver', () => ({ resolveEmbed: vi.fn() }));
vi.mock('../../../../../services/chatSyncService', () => ({ chatSyncService: {} }));

import { ImageRenderer } from '../ImageRenderer';

beforeEach(() => {
  vi.clearAllMocks();
  mocks.mount.mockReturnValue({});
});

// contract-test: supporting surface=gui.web assertions=chats.rendering.assistant-document-convergence
it('renders SVG source as an image and opens the image fullscreen event', () => {
  const content = document.createElement('div');
  const listener = vi.fn();
  content.addEventListener('imagefullscreen', listener);
  new ImageRenderer().render({ content, container: content, attrs: {
    id: 'inline-svg', type: 'image', status: 'finished', contentRef: 'stream:inline-svg',
    filename: 'drawing.svg', code: '<svg viewBox="0 0 20 10"><rect width="20" height="10"/></svg>',
  } } as Parameters<ImageRenderer['render']>[0]);
  const props = mocks.mount.mock.calls[mocks.mount.mock.calls.length - 1]?.[1].props;
  expect(props).toMatchObject({ presentationOnly: true, filename: 'drawing.svg', fileType: 'image/svg+xml' });
  expect(props.src).toMatch(/^data:image\/svg\+xml/);
  props.onFullscreen();
  expect(listener.mock.calls[0][0].detail).toMatchObject({ src: props.src, filename: 'drawing.svg', fileType: 'image/svg+xml' });
});

// contract-test: supporting surface=gui.web assertions=teams.collaboration.realtime-team-sync
it('keeps an uploading editor image local, then resolves its server ID after upload', () => {
  const renderer = new ImageRenderer();
  const content = document.createElement('div');
  const render = (attrs: Record<string, unknown>) => renderer.render({ content, container: content, attrs } as unknown as Parameters<ImageRenderer['render']>[0]);

  render({ id: 'draft-node-id', type: 'image', status: 'uploading', src: 'blob:local-image' });
  expect(mocks.mount.mock.calls[mocks.mount.mock.calls.length - 1]?.[1].props).toMatchObject({
    id: 'draft-node-id', localOnly: true, status: 'uploading',
  });

  render({ id: 'draft-node-id', type: 'image', status: 'finished', src: 'blob:local-image', uploadEmbedId: 'server-embed-id' });
  expect(mocks.mount.mock.calls[mocks.mount.mock.calls.length - 1]?.[1].props).toMatchObject({
    id: 'server-embed-id', localOnly: true, status: 'finished',
  });

  render({ id: 'draft-node-id', type: 'image', status: 'finished', contentRef: 'embed:server-embed-id',
    s3Files: { preview: { s3_key: 'encrypted-image' } }, aesKey: 'key' });
  expect(mocks.mount.mock.calls[mocks.mount.mock.calls.length - 1]?.[1].props).toMatchObject({
    id: 'server-embed-id', localOnly: false, status: 'finished',
  });
});
