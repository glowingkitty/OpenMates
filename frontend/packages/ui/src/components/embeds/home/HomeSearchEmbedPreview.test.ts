// @vitest-environment jsdom
import { mount, tick, unmount } from 'svelte';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
const mocks = vi.hoisted(() => ({resolve: vi.fn(), decode: vi.fn(), request: vi.fn()}));
vi.mock('@repo/ui', async () => { const {readable} = await import('svelte/store'); return {text: readable((key: string) => key)}; });
vi.mock('../../../services/embedResolver', () => ({resolveEmbed: mocks.resolve, decodeToonContent: mocks.decode, requestEmbedFromServerOnce: mocks.request}));
vi.mock('../../../services/chatSyncService', () => ({chatSyncService: new EventTarget()}));
vi.mock('../BasicInfosBar.svelte', () => ({default: () => {}}));
vi.mock('../../Icon.svelte', () => ({default: () => {}}));
vi.mock('../../../stores/appSettingsMemoriesStore', () => ({appSettingsMemoriesStore: {subscribe: (run: (value: unknown) => void) => {run({entriesByApp: new Map()}); return () => {};}}}));
import HomeSearchEmbedPreview from './HomeSearchEmbedPreview.svelte';
const mounted: Array<{component: ReturnType<typeof mount>; target: HTMLElement}> = [];
beforeEach(() => {vi.clearAllMocks(); mocks.resolve.mockResolvedValue(null); mocks.decode.mockResolvedValue(null); mocks.request.mockResolvedValue(true);});
afterEach(async () => {for (const {component, target} of mounted) {await unmount(component);target.remove();} mounted.length = 0;});
async function preview(props: Record<string, unknown>) {
  const target = document.createElement('div');document.body.append(target);
  const component = mount(HomeSearchEmbedPreview, {target, props: {id: 'legacy-home-preview', status: 'finished', onFullscreen: () => {}, ...props}});
  mounted.push({component, target});await tick();return target;
}
// contract-test: direct surface=gui.web assertions=home-search.web.map-and-filter,home-search.output.safe-and-truthful
it('uses saved parent preview metadata and total count without fetching children', async () => {
  const target = await preview({previewData: {status: 'finished', result_count: 6, embed_ids: 'a|b|c|d|e|f', preview_results: [
    {title: 'Canal flat', image_url: '/store-examples/home-1.webp'}, {title: 'Loft', image_url: '/store-examples/home-2.webp'}, {title: 'Garden flat', image_url: '/store-examples/home-3.webp'}]}});
  expect(target.querySelector('[data-testid="home-search-result-count"]')?.getAttribute('data-count')).toBe('6');
  expect(target.querySelectorAll('.listing-thumbnail')).toHaveLength(3);
  expect(target.querySelector('[data-testid="search-no-results-message"]')).toBeNull();
  expect(mocks.resolve).not.toHaveBeenCalled();expect(mocks.request).not.toHaveBeenCalled();
});
// contract-test: direct surface=gui.web assertions=home-search.output.safe-and-truthful
it.each([{resultCount: 6}, {childEmbedIds: 'a|b|c|d|e|f'}])('retains positive metadata without falsely claiming empty results: %j', async props => {
  const target = await preview({results: [], ...props});
  expect(target.querySelector('[data-testid="home-search-result-count"]')?.getAttribute('data-count')).toBe('6');
  expect(target.querySelector('[data-testid="search-no-results-message"]')).toBeNull();
});
// contract-test: direct surface=gui.web assertions=home-search.output.safe-and-truthful
it('distinguishes explicitly zero results from missing metadata', async () => {
  const zero = await preview({resultCount: 0, results: []});
  expect(zero.querySelector('[data-testid="search-no-results-message"]')).not.toBeNull();
  const unknown = await preview({results: []});
  expect(unknown.querySelector('[data-testid="search-no-results-message"]')).toBeNull();
  expect(unknown.querySelector('[data-testid="search-preview-metadata-missing-message"]')).not.toBeNull();
});
// contract-test: direct surface=gui.web assertions=home-search.output.safe-and-truthful
it('hydrates preview_results from the finished parent callback without child fallback', async () => {
  mocks.resolve.mockResolvedValue({status: 'finished', content: 'saved-parent'});
  mocks.decode.mockResolvedValue({status: 'finished', result_count: 6, embed_ids: 'a|b|c|d|e|f', preview_results: [{title: 'Canal flat', image_url: '/store-examples/home-1.webp'}]});
  const target = await preview({id: 'saved-home-parent', status: 'processing'});
  await vi.waitFor(() => expect(target.querySelector('[data-testid="home-search-result-count"]')?.getAttribute('data-count')).toBe('6'));
  expect(target.querySelectorAll('.listing-thumbnail')).toHaveLength(1);
  expect(target.querySelector('[data-testid="search-no-results-message"]')).toBeNull();
  expect(mocks.resolve.mock.calls.every(call => call[0] === 'saved-home-parent')).toBe(true);
  expect(mocks.request).not.toHaveBeenCalled();
});
