/**
 * Existence check and open action behind the context_entry chat history event
 * (ContextEntryEventNotice): a saved memory opens in Settings > Memories; a workflow
 * is checked with the workflow API (404 means it no longer exists).
 * Plan: docs/plans/chat-recommendations/plan.yml (wire_contract.system_event)
 */
import type { ContextEntryHistoryEvent } from '../types/recommendations';
import { listPersonalRuleDocuments } from './ruleDocumentService';
import { workflowApiRequest, WorkflowApiError } from '../stores/workflowWorkspaceStore';
import { settingsDeepLink } from '../stores/settingsDeepLinkStore';
import { panelState } from '../stores/panelStateStore';
import { memoryDraftSuggestion } from '../stores/memoryDraftSuggestionStore';
import { settingsMenuVisible } from '../components/Settings.svelte';

const memoryIdMatches = (id: string, entryId: string) => id === entryId || id === `personal:${entryId}`;

/** True while the saved entry exists; rejects when the answer is unknown (offline, 5xx). */
export async function contextEntryExists(event: ContextEntryHistoryEvent): Promise<boolean> {
  if (event.kind === 'memory') {
    return (await listPersonalRuleDocuments()).some((document) => memoryIdMatches(document.id, event.entry_id));
  }
  try {
    await workflowApiRequest(`/v1/workflows/${encodeURIComponent(event.entry_id)}`);
    return true;
  } catch (error) {
    if (error instanceof WorkflowApiError && error.status === 404) return false;
    throw error;
  }
}

/** Opens the saved memory itself (no draft) in Settings > Memories. */
export function openContextEntryMemory(event: ContextEntryHistoryEvent): void {
  memoryDraftSuggestion.set(null);
  settingsMenuVisible.set(true);
  panelState.openSettings();
  settingsDeepLink.set(`memories/${encodeURIComponent(event.entry_id)}`);
}
