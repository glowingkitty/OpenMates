// frontend/packages/ui/src/components/embeds/tasks/taskEmbedData.ts
// Shared normalizers for task app-skill embeds.
// Parent previews use only snapshot fields from the skill result.
// Parent fullscreens hydrate children through SearchResultsTemplate.
// Child fullscreens can then attempt live workspace loads for editable detail.

import type { UserTaskStatus } from '../../../services/userTaskService';
import { asString } from '../embedDataUtils';

export type TaskEmbedStatus = UserTaskStatus | 'cancelled' | 'unknown';

export interface TaskEmbedResult {
  embed_id: string;
  task_id?: string;
  short_id?: string;
  title?: string;
  description?: string;
  status?: TaskEmbedStatus;
  assignee?: string;
  assignee_type?: string;
}

export function normalizeTaskResult(embedId: string, content: Record<string, unknown>): TaskEmbedResult {
  return {
    embed_id: embedId,
    task_id: asString(content.task_id) ?? asString(content.id),
    short_id: asString(content.short_id),
    title: asString(content.title),
    description: asString(content.description),
    status: asString(content.status) as TaskEmbedStatus | undefined,
    assignee: asString(content.assignee),
    assignee_type: asString(content.assignee_type),
  };
}

export function normalizeTaskLegacyResults(results: unknown[]): TaskEmbedResult[] {
  return results.map((result, index) => {
    const content = result && typeof result === 'object' ? result as Record<string, unknown> : {};
    return normalizeTaskResult(asString(content.embed_id) ?? `legacy-task-${index}`, content);
  });
}

export function taskStatusLabel(status?: string): string {
  if (!status) return 'Unknown';
  return status.replace(/_/g, ' ').replace(/\b\w/g, (match) => match.toUpperCase());
}

export function taskAssigneeLabel(value?: string): string {
  if (!value) return 'Unassigned';
  if (value === 'openmates' || value === 'ai') return 'OpenMates';
  return value.replace(/_/g, ' ').replace(/\b\w/g, (match) => match.toUpperCase());
}
