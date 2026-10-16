import type { SkillStoreExampleFullscreen } from '../../stores/skillStoreExampleFullscreenStore';

const embedId = '00000000-0000-4000-8000-000000000001';
const exampleData: SkillStoreExampleFullscreen = {
  embedId, appId: 'web', skillId: 'search',
  decodedContent: { app_id: 'web', skill_id: 'search', query: 'Empty saved search', results: [], provider: 'Brave Search' },
};
const onClose = () => window.dispatchEvent(new Event('apps-result-preview-close'));

export default { embedId, appId: 'web', exampleData, onClose };
export const variants = {
  trademarkGap: { embedId, appId: 'business', onClose, exampleData: {
    embedId, appId: 'business', skillId: 'search_trademarks', decodedContent: {
      app_id: 'business', skill_id: 'search_trademarks', query: 'Proposed name', status: 'error',
      error: 'No requested region could be searched.', result_count: 0, matches: [],
      coverage: [{ query: 'Proposed name', region: 'DE', status: 'unsupported',
        source_url: 'https://register.dpma.de/DPMAregister/marke/uebersicht' }],
    },
  } },
  legacyRequest: { embedId, appId: 'web', onClose, exampleData: { ...exampleData, decodedContent: { app_id: 'web', skill_id: 'search', input: { requests: [{ query: 'Saved native request', count: 10 }] }, results: [], provider: 'Brave Search' } } },
  failedRequest: { embedId, appId: 'web', onClose, exampleData: { ...exampleData, decodedContent: { app_id: 'web', skill_id: 'search', status: 'error', results: [] } } },
  missingRegistry: { embedId, appId: 'web', onClose, exampleData: { ...exampleData, decodedContent: { app_id: 'web', results: [] } } },
};
