const content = {
  status: 'finished', app_id: 'web', skill_id: 'browse',
  results: [{ status: 'needs_user', session_id: '11111111-1111-4111-8111-111111111111',
    title: 'Example Domain', url: 'https://example.com/', reason: 'Review the website before continuing.',
    data_json: '{"purpose":"Documentation examples","items":[],"missing":null}' }],
};
const defaults = { id: 'preview-browse', content, onFullscreen: () => { document.documentElement.dataset.browseOpened = 'true'; } };
export default defaults;
export const variants = {
  processing: { ...defaults, content: { status: 'processing', task: 'Find the documentation' } },
  processingReady: { ...defaults, content: { status: 'processing', task: 'Find the documentation', session_id: '11111111-1111-4111-8111-111111111111' } },
  completed: { ...defaults, content: { ...content, results: [{ ...content.results[0], status: 'completed' }] } },
  error: { ...defaults, content: { status: 'error', results: [{ status: 'failed', reason: 'Website unavailable' }] } },
  cancelled: { ...defaults, content: { status: 'cancelled', results: [{ status: 'cancelled' }] } },
  mobile: { ...defaults, isMobile: true },
};
