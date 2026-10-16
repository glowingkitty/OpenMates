/** Owner-scoped Project routing metadata; private files stay behind shared consent. */
import { getWorkspaceCacheIdentity } from './workspaceQueryCache';
import { getWebSocketUrl } from '../config/api';
import type { ProjectFocusRoutingCandidate } from './agenticProjectContextService';

export async function loadVoiceProjectContext(chatId?: string): Promise<{
  project_focus_candidates: ProjectFocusRoutingCandidate[];
  client_capabilities: string[];
  app_settings_memories_metadata: string[];
  project_focus_documents?: Array<{ item_id: string; revision: string; document: string }>;
}> {
  const identity = getWorkspaceCacheIdentity();
  const client_capabilities = new URL(getWebSocketUrl()).searchParams.get('client_capabilities')?.split(',') ?? [];
  if (!identity) return { project_focus_candidates: [], client_capabilities, app_settings_memories_metadata: [] };
  const [{ listProjects, getActiveProjectFocus }, { collectProjectFocusRoutingCandidates, loadSelectedProjectFocusDocuments }] = await Promise.all([
    import('./projectService'), import('./agenticProjectContextService'),
  ]);
  let project_focus_candidates: ProjectFocusRoutingCandidate[] = [];
  try { project_focus_candidates = await collectProjectFocusRoutingCandidates(await listProjects({ teamId: null }), null); }
  catch { /* Discovery failure grants no additional Project authority. */ }
  let project_focus_documents: Array<{ item_id: string; revision: string; document: string }> = [];
  if (chatId) {
    const focus = await getActiveProjectFocus(chatId);
    const prefix = focus ? `project-focus:${focus.project_id}:` : '';
    if (focus?.specialist_focus_id?.startsWith(prefix)) {
      const itemId = focus.specialist_focus_id.slice(prefix.length);
      const selected = await loadSelectedProjectFocusDocuments(chatId, focus.project_id, [itemId]);
      project_focus_documents = selected.map(({ id, revision, markdown }) => ({ item_id: id, revision, document: markdown }));
    }
  }
  const { personalDocumentMemoryEntries } = await import('./ruleDocumentService');
  const app_settings_memories_metadata = (await personalDocumentMemoryEntries()).length ? ['openmates-memories'] : [];
  if (getWorkspaceCacheIdentity() !== identity) throw new Error('Voice Project context owner changed');
  return { project_focus_candidates, client_capabilities, app_settings_memories_metadata,
    ...(project_focus_documents.length ? { project_focus_documents } : {}) };
}
