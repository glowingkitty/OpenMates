import { notificationStore } from '../../stores/notificationStore';
import { emptyAppsLibrary, isAppsSearchSaved } from '../../services/appsWorkspaceLibraryService';
import type { AppsRequestContext } from '../../services/appsWorkspaceContext';
import type { SkillStoreExampleFullscreen } from '../../stores/skillStoreExampleFullscreenStore';

// This wrapper mounts an absolute fullscreen embed, just like embeds/*Fullscreen.
// Give it the definite host height supplied by the real Apps result layer.
export const layout = 'fill' as const;

const embedId = '00000000-0000-4000-8000-000000000001';
const exampleData: SkillStoreExampleFullscreen = {
  embedId, appId: 'web', skillId: 'search',
  decodedContent: { app_id: 'web', skill_id: 'search', query: 'Empty saved search', results: [], provider: 'Brave Search' },
};
const onClose = () => window.dispatchEvent(new Event('apps-result-preview-close'));

const savedLibrary = { ...emptyAppsLibrary('web'), saved_searches: [{ id: 'saved-cafes', skill_id: 'search', parameters: { requests: [{ query: 'Saved cafes' }] }, saved_at: 1 }] };
const sharedResults = { embedId, appId: 'web', onClose,
    onSubmit: async (text: string, attachments: File[], context: unknown) => { window.dispatchEvent(new CustomEvent('apps-result-preview-followup', { detail: { text, filenames: attachments.map(file => file.name), context } })); },
    onSaveSearch: async (context: AppsRequestContext) => { window.dispatchEvent(new CustomEvent('apps-result-preview-save', { detail: context })); },
    isSearchSaved: () => false, onCreateWorkflow: async () => {},
    exampleData: { ...exampleData, decodedContent: { app_id: 'web', skill_id: 'search', query: 'Saved cafes', input: { requests: [{ query: 'Saved cafes' }] }, provider: 'Brave Search', results: Array.from({ length: 12 }, (_, index) => ({ title: `Cafe ${index + 1}`, url: `https://example.com/cafe-${index + 1}`, description: index === 0 ? 'Quiet coffee and books' : 'Coffee near the station' })) } } };

export default { embedId, appId: 'web', exampleData, onClose };
export const variants = {
  transcription: { embedId, appId: 'audio', onClose, exampleData: { embedId, appId: 'audio', skillId: 'transcribe', decodedContent: { app_id: 'audio', skill_id: 'transcribe', input: { requests: [{ filename: 'Meeting.webm' }] }, results: [{ id: 'native-request', results: [{ transcript: 'The meeting starts at nine.', title: 'Meeting notes', duration_seconds: 12 }] }] } } },
  sharedResults,
  guestSaveDeclined: { ...sharedResults, onSaveSearch: async () => { window.dispatchEvent(new Event('apps-result-preview-signup')); return false; } },
  savedResults: { ...sharedResults, isSearchSaved: (context: AppsRequestContext) => isAppsSearchSaved(savedLibrary, context) },
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

// Synthetic component evidence records the actual notification store, including
// failures emitted before the preview's ready marker is visible.
export const ready = (() => {
  if (typeof window === 'undefined') return;
  const browser = window as Window & { appsResultPreviewNotifications?: Array<{ type: string; message: string }>; appsResultPreviewClosed?: number };
  browser.appsResultPreviewNotifications = [];
  browser.appsResultPreviewClosed = 0;
  window.addEventListener('apps-result-preview-close', () => { browser.appsResultPreviewClosed = (browser.appsResultPreviewClosed ?? 0) + 1; });
  const unsubscribe = notificationStore.subscribe(state => { browser.appsResultPreviewNotifications = state.notifications.map(({ type, message }) => ({ type, message })); });
  window.addEventListener('pagehide', unsubscribe, { once: true });
})();
