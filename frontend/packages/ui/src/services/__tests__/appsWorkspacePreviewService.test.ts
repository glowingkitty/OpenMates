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
  it('bounds preview work while preserving source order', () => {
    const results = Array.from({ length: 100 }, (_, index) => ({ title: `Repo ${index}` }));
    const previews = recommendationPreviewItems('code', { ...batch, result: { results } });
    expect(previews).toHaveLength(40);
    expect(previews[0].content.title).toBe('Repo 0'); expect(previews[39].content.title).toBe('Repo 39');
  });
});
