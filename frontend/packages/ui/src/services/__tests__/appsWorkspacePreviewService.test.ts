import { describe, expect, it } from 'vitest';
import { recommendationPreviewItems } from '../appsWorkspacePreviewService';
const batch = { id: 'daily', skill_id: 'search_repos', created_at: 1, expires_at: 2, result: {} };
describe('temporary recommendation child previews', () => {
  // contract-test: direct surface=gui.web assertions=apps.recommendations.public-daily,apps.results.shared-fullscreen
  it('renders actual children inside native batched result envelopes without changing them', () => {
    const repos = [{ title: 'Useful project', url: 'https://example.com/repo' }];
    const result = { data: { results: [{ id: 'native-request', results: repos }] } };
    const snapshot = JSON.stringify(result);
    const previews = recommendationPreviewItems('code', { ...batch, result });
    expect(previews).toEqual([{ id: 'daily:0', type: 'code-repo', content: { ...repos[0], app_id: 'code', skill_id: 'search_repos' } }]);
    expect(JSON.stringify(result)).toBe(snapshot);
  });
  // contract-test: direct surface=gui.web assertions=apps.recommendations.public-daily,apps.results.shared-fullscreen
  it('preserves individual News article payloads and their creating app in recommendation envelopes', () => {
    const articles = [{ type: 'search_result', url: 'https://example.test/one', title: 'First article' },
      { url: 'https://example.test/two', title: 'Second article', thumbnail: { original: 'https://example.test/photo.png' } }];
    const previews = recommendationPreviewItems('news', { ...batch, skill_id: 'search', result: { data: { results: [{ results: articles }] } } });
    expect(previews.map(item => item.id)).toEqual(['daily:0', 'daily:1']);
    expect(previews[0].content).toEqual({ ...articles[0], app_id: 'news', skill_id: 'search' });
    expect(previews[1]).toMatchObject({ type: 'web-website', content: { ...articles[1], app_id: 'news', skill_id: 'search' } });
  });
  // contract-test: direct surface=gui.web assertions=apps.recommendations.public-daily,apps.results.shared-fullscreen
  it('bounds preview work while preserving source order', () => {
    const results = Array.from({ length: 100 }, (_, index) => ({ title: `Repo ${index}` }));
    const previews = recommendationPreviewItems('code', { ...batch, result: { results } });
    expect(previews).toHaveLength(40);
    expect(previews[0].content.title).toBe('Repo 0'); expect(previews[39].content.title).toBe('Repo 39');
  });
});
