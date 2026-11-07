/** Default account/Project persistence adapter for the Memories editor (Settings > Memories and Project Memories tab). */
import {
  activeRuleChatId, deletePersonalRuleDocument, listPersonalRuleDocuments, listProjectRuleDocuments,
  savePersonalRuleDocument, saveProjectRuleDocument,
} from './ruleDocumentService';
import type { MemoryEditorService } from '../components/settings/MemoriesEditor.svelte';

export const defaultMemoryEditorService: MemoryEditorService = {
  list: async (source, selectedProjectId) => {
    if (source === 'personal') return listPersonalRuleDocuments();
    const chatId = activeRuleChatId();
    if (!chatId || !selectedProjectId) throw new Error('rule_project_activation_required');
    return listProjectRuleDocuments({ chatId, projectId: selectedProjectId });
  },
  save: async (source, selectedProjectId, document, existing) => {
    if (source === 'personal') { await savePersonalRuleDocument({ id: existing?.id, document }); return; }
    const chatId = activeRuleChatId();
    if (!chatId || !selectedProjectId) throw new Error('rule_project_activation_required');
    await saveProjectRuleDocument({ chatId, projectId: selectedProjectId, document, existing: existing ?? undefined });
  },
  remove: async (source, _projectId, existing) => {
    if (source !== 'personal') throw new Error('rule_delete_unsupported');
    await deletePersonalRuleDocument(existing.id);
  },
};
