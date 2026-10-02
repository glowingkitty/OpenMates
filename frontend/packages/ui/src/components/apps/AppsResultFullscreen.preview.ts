import type { SkillStoreExampleFullscreen } from '../../stores/skillStoreExampleFullscreenStore';

const embedId = '00000000-0000-4000-8000-000000000001';
const exampleData: SkillStoreExampleFullscreen = {
  embedId, appId: 'web', skillId: 'search',
  decodedContent: { app_id: 'web', skill_id: 'search', query: 'Empty saved search', results: [], provider: 'Brave Search' },
};
const onClose = () => window.dispatchEvent(new Event('apps-result-preview-close'));

export default { embedId, appId: 'web', exampleData, onClose };
export const variants = {
  legacyRequest: { embedId, appId: 'web', onClose, exampleData: { ...exampleData, decodedContent: { app_id: 'web', skill_id: 'search', input: { requests: [{ query: 'Saved native request', count: 10 }] }, results: [], provider: 'Brave Search' } } },
  failedRequest: { embedId, appId: 'web', onClose, exampleData: { ...exampleData, decodedContent: { app_id: 'web', skill_id: 'search', status: 'error', results: [] } } },
  missingRegistry: { embedId, appId: 'web', onClose, exampleData: { ...exampleData, decodedContent: { app_id: 'web', results: [] } } },
};
