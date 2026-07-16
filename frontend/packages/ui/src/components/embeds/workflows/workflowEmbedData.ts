// frontend/packages/ui/src/components/embeds/workflows/workflowEmbedData.ts
// Shared normalizers for workflow app-skill embeds.
// Search/create parent embeds render from snapshot metadata until fullscreen.
// Child fullscreens then attempt live workflow store loads for editable detail.
// The snapshot path keeps preview pages and public example chats deterministic.

import { asString, asNumber } from '../embedDataUtils';

export interface WorkflowEmbedResult {
  embed_id: string;
  workflow_id?: string;
  title?: string;
  description?: string;
  status?: string;
  enabled?: boolean;
  trigger_summary?: string;
  next_run_at?: number | null;
  created_at?: number | null;
}

export function normalizeWorkflowResult(embedId: string, content: Record<string, unknown>): WorkflowEmbedResult {
  const enabledValue = content.enabled;
  return {
    embed_id: embedId,
    workflow_id: asString(content.workflow_id) ?? asString(content.id),
    title: asString(content.title),
    description: asString(content.description),
    status: asString(content.status),
    enabled: typeof enabledValue === 'boolean' ? enabledValue : undefined,
    trigger_summary: asString(content.trigger_summary),
    next_run_at: asNumber(content.next_run_at) ?? null,
    created_at: asNumber(content.created_at) ?? null,
  };
}

export function normalizeWorkflowLegacyResults(results: unknown[]): WorkflowEmbedResult[] {
  return results.map((result, index) => {
    const content = result && typeof result === 'object' ? result as Record<string, unknown> : {};
    return normalizeWorkflowResult(asString(content.embed_id) ?? `legacy-workflow-${index}`, content);
  });
}

export function workflowStatusLabel(status?: string, enabled?: boolean): string {
  if (enabled === false) return 'Off';
  if (!status) return enabled ? 'On' : 'Manual';
  return status.replace(/_/g, ' ').replace(/\b\w/g, (match) => match.toUpperCase());
}
