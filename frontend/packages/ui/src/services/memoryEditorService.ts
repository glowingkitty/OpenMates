/** Default account/Project persistence adapter for the Memories editor (Settings > Memories and Project Memories tab). */
import {
  activeRuleChatId, deletePersonalRuleDocument, listPersonalRuleDocuments, listProjectRuleDocuments,
  savePersonalRuleDocument, saveProjectRuleDocument,
} from './ruleDocumentService';
import type { MemoryEditorService } from '../components/settings/MemoriesEditor.svelte';
import type { MemoryDraftOrigin } from '../stores/memoryDraftSuggestionStore';
import { parseRuleDocument } from '../utils/ruleDocuments';

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

/**
 * Personal editor service for a draft opened from a chat Recommendation: after a
 * successful save it resolves the recommendation and adds the chat history event.
 * Plan: docs/plans/chat-recommendations/plan.yml (D-9)
 */
export function recommendationMemoryEditorService(origin: MemoryDraftOrigin): MemoryEditorService {
  return {
    ...defaultMemoryEditorService,
    save: async (source, selectedProjectId, document, existing) => {
      if (source !== 'personal') {
        await defaultMemoryEditorService.save(source, selectedProjectId, document, existing);
        return;
      }
      const saved = await savePersonalRuleDocument({ id: existing?.id, document });
      const { recordContextEntrySaved } = await import('./contextEntryEvents');
      // The memory is saved; a failed history event is reported, never undoes the save.
      void recordContextEntrySaved({
        chatId: origin.chatId, recommendationId: origin.recommendationId, kind: 'memory',
        action: existing ? 'updated' : 'created', entryId: saved.id,
        title: parseRuleDocument(document).title,
      }).catch((error) => console.error('[Recommendations] Could not record the saved memory in the chat', error));
    },
  };
}
