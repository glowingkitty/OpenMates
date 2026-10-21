import { afterEach, describe, expect, it, vi } from 'vitest';
vi.mock('../../config/api', () => ({ getApiEndpoint: (path: string) => `https://api.test${path}` }));
import { rankAppsWorkspaceImageResults } from '../appsWorkspaceImageRankingService';
const options = { prepareModelText: (value: string) => value, appId: 'shopping', text: 'match the reference photo', assets: { image: { type: 'image' as const, format: 'jpg' as const, data_base64: 'reference' } }, assertCurrent: () => {} };
afterEach(() => vi.unstubAllGlobals());
describe('image-aware result relevance', () => {
  // contract-test: direct surface=gui.web assertions=apps.requests.natural-language
  it('sends bounded actual candidate text and reorders only existing result objects', async () => {
    const original = { data: { results: [{ title: 'First', description: 'blue chair', secret: 'not sent' }, { title: 'Second', description: 'green chair' }] } };
    const fetchMock = vi.fn(async (_url: string, _options: RequestInit) => Response.json({ ranked_ids: ['result-1', 'invented', 'result-1', 'result-0'] })); vi.stubGlobal('fetch', fetchMock);
    const ranked = await rankAppsWorkspaceImageResults(original, options);
    expect(ranked).toEqual({ data: { results: [original.data.results[1], original.data.results[0]] } });
    const body = JSON.parse(fetchMock.mock.calls[0][1].body as string);
    expect(body.assets).toEqual(options.assets); expect(body.candidates).toHaveLength(2);
    expect(JSON.stringify(body.candidates)).not.toContain('not sent');
    expect(original.data.results[0].title).toBe('First');
  });
  // contract-test: direct surface=gui.web assertions=apps.requests.natural-language
  it('preserves the accepted result when scoring is unavailable', async () => {
    const original = { data: { results: [{ title: 'First' }, { title: 'Second' }] } };
    vi.stubGlobal('fetch', vi.fn(async () => Response.json({ detail: 'unavailable' }, { status: 503 })));
    expect(await rankAppsWorkspaceImageResults(original, options)).toBe(original);
  });
  // contract-test: direct surface=gui.web assertions=apps.requests.natural-language
  it('does not swallow account/Team context changes while ranking', async () => {
    let current = true;
    vi.stubGlobal('fetch', vi.fn(async () => { current = false; return Response.json({ ranked_ids: ['result-1'] }); }));
    await expect(rankAppsWorkspaceImageResults({ data: { results: [{ title: 'A' }, { title: 'B' }] } }, { ...options, assertCurrent: () => { if (!current) throw new Error('team_context_changed'); } })).rejects.toThrow('team_context_changed');
  });
});
