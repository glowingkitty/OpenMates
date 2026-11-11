// frontend/packages/ui/src/stores/workflowSidePanelStore.ts
//
// Opens the workflow editor next to the active chat (chat left, editor right;
// fullscreen below 1024px) with an AI-authored draft built from a chat
// Recommendation. Nothing is saved until the user saves in the editor.
// Plan: docs/plans/chat-recommendations/plan.yml (D-8, D-10)

import { writable } from 'svelte/store';

/** Request to open the side panel with an unsaved, AI-generated workflow draft. */
export interface WorkflowSidePanelRequest {
  /** Chat the panel belongs to; the panel closes when another chat opens. */
  chatId: string;
  /** Recommendation that opened the panel (removed from the chat only on save). */
  recommendationId: string;
  mode: 'create' | 'update';
  /** Existing workflow id when mode is 'update'. */
  workflowId: string | null;
  /** Authoring instruction for the existing AI authoring stream. */
  instruction: string;
  /** User message id of the chat turn the recommendation belongs to, when known (usage attribution). */
  sourceMessageId?: string;
}

/** Emitted once when the user saves the workflow opened from a recommendation. */
export interface WorkflowSidePanelSaved {
  chatId: string;
  recommendationId: string;
  workflowId: string;
  title: string;
  action: 'created' | 'updated';
}

/** Currently open request, or null when the panel is closed. */
export const workflowSidePanel = writable<WorkflowSidePanelRequest | null>(null);

/** Last save event; subscribers act once per distinct object. */
export const workflowSidePanelSaved = writable<WorkflowSidePanelSaved | null>(null);

export function openWorkflowSidePanel(request: WorkflowSidePanelRequest): void {
  workflowSidePanel.set(request);
}

export function closeWorkflowSidePanel(): void {
  workflowSidePanel.set(null);
}

export function reportWorkflowSidePanelSaved(event: WorkflowSidePanelSaved): void {
  workflowSidePanelSaved.set(event);
}
