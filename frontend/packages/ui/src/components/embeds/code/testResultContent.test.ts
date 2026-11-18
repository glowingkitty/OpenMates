// Evidence lookup of the test_result embed: the stored asset id plus file
// variant mint a fresh link through the generated-assets route.
import { afterEach, describe, expect, it, vi } from 'vitest';
import { findEvidence, parseTestResult, resolveArtifactEvidenceUrl, testResultTitle } from './testResultContent';

const content = {
  kind: 'browser', target: 'e2b', run_status: 'passed', steps: [], tests: [],
  evidence: [{ kind: 'video', path: 'outputs/test-run/video.webm', mime_type: 'video/webm', asset_id: 'embed-1', variant: 'video-abc' }],
};

afterEach(() => { vi.unstubAllGlobals(); });

describe('test result evidence', () => {
  // contract-test: supporting surface=gui.web assertions=code-run.tests.recorded-evidence
  it('requests a fresh download link for the stored asset and variant', async () => {
    const fetchMock = vi.fn(async () => new Response(JSON.stringify({ download_url: 'https://dl.example.org/v' }), { status: 200 }));
    vi.stubGlobal('fetch', fetchMock);
    const video = findEvidence(parseTestResult(content), 'video');
    expect(video?.variant).toBe('video-abc');
    await expect(resolveArtifactEvidenceUrl(video!)).resolves.toBe('https://dl.example.org/v');
    expect(String((fetchMock.mock.calls[0] as unknown[])[0])).toContain('/v1/generated-assets/embed-1/files/video-abc/download-url');
  });

  // contract-test: supporting surface=gui.web assertions=code-run.tests.recorded-evidence
  it('has no link for evidence without a stored variant', async () => {
    const fetchMock = vi.fn();
    vi.stubGlobal('fetch', fetchMock);
    await expect(resolveArtifactEvidenceUrl({ kind: 'video', path: 'v.webm', assetId: 'embed-1' })).resolves.toBeNull();
    expect(fetchMock).not.toHaveBeenCalled();
  });

  // contract-test: supporting surface=gui.web assertions=code-run.tests.recorded-evidence
  it('reports a refused lookup instead of hiding it', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => new Response('{}', { status: 404 })));
    await expect(resolveArtifactEvidenceUrl({ kind: 'video', path: 'v.webm', assetId: 'a', variant: 'b' })).rejects.toThrow('404');
  });
});

describe('test result title', () => {
  // contract-test: supporting surface=gui.web assertions=code-run.tests.recorded-evidence
  it('names the single test that ran, never the execution target', () => {
    const view = parseTestResult({ ...content, tests: [{ name: 'Adding a recipe shows it in the list', status: 'passed' }] });
    expect(testResultTitle(view, 'Test result')).toBe('Adding a recipe shows it in the list');
  });

  // contract-test: supporting surface=gui.web assertions=code-run.tests.recorded-evidence
  it('falls back to the generic title for several tests or none', () => {
    expect(testResultTitle(parseTestResult(content), 'Test result')).toBe('Test result');
    const several = parseTestResult({ ...content, tests: [{ name: 'a', status: 'passed' }, { name: 'b', status: 'passed' }] });
    expect(testResultTitle(several, 'Test result')).toBe('Test result');
  });
});
