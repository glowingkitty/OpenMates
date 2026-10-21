import { afterEach, describe, expect, it, vi } from 'vitest';
import { mount, unmount } from 'svelte';

const mocks = vi.hoisted(() => ({ getAppsResult: vi.fn(), resolveEmbed: vi.fn() }));
vi.mock('../../../services/appsWorkspaceResultsService', () => ({ getAppsResult: mocks.getAppsResult }));
vi.mock('../../../services/embedResolver', () => ({
  resolveEmbed: mocks.resolveEmbed,
  decodeToonContent: async (value: string) => JSON.parse(value),
}));
vi.mock('../AppsEmbedPreview.svelte', async () => ({ default: (await import('./AppsEmbedPreviewStub.svelte')).default }));
import AppsResultPreviewGroup from '../AppsResultPreviewGroup.svelte';

let mounted: ReturnType<typeof mount> | undefined;
afterEach(async () => { if (mounted) await unmount(mounted); mounted = undefined; document.body.innerHTML = ''; vi.clearAllMocks(); });

describe('Apps retained child cards', () => {
  // contract-test: supporting surface=gui.web assertions=apps.results.web-retained-graph,apps.presentation.shared-detail-and-recency
  it.each([{ embedIds: ['news-one', 'news-two'] }, { embedIds: '["news-one","news-two"]' }])('opens the selected child and retains its root context for graph %j', async ({ embedIds }) => {
    mocks.resolveEmbed.mockResolvedValue({ content: JSON.stringify({ embed_ids: embedIds, query: 'Public news' }) });
    const onOpen = vi.fn();
    const onLabel = vi.fn();
    mounted = mount(AppsResultPreviewGroup, { target: document.body, props: {
      result: { embedId: 'news-root', appId: 'news', skillId: 'search', createdAt: 1, status: 'finished' },
      appId: 'news', teamId: 'team-context', onOpen, onLabel,
    } });
    await vi.waitFor(() => expect(document.querySelector('[data-testid="news-two"]')).not.toBeNull());
    (document.querySelector('[data-testid="news-two"]') as HTMLButtonElement).click();
    expect(onOpen).toHaveBeenCalledExactlyOnceWith('news-two', 'news-root');
    expect(mocks.getAppsResult).toHaveBeenCalledWith('news-root', 'team-context');
    expect(onLabel).toHaveBeenCalledWith('news-root', 'Public news');
  });
});
