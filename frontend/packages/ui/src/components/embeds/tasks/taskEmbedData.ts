// frontend/packages/ui/src/components/embeds/tasks/taskEmbedData.ts
// Shared normalizers for task app-skill embeds.
// Parent previews use only snapshot fields from the skill result.
// Parent fullscreens hydrate children through SearchResultsTemplate.
// Child fullscreens can then attempt live workspace loads for editable detail.

import type { UserTaskAssigneeType, UserTaskStatus } from '../../../services/userTaskService';
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
  due_date?: string;
  project_name?: string;
  validation?: TaskEmbedValidation;
}

export interface TaskEmbedValidation {
  status: 'valid' | 'invalid';
  errors: string[];
  warnings: string[];
}

function messageList(value: unknown): string[] {
  if (!Array.isArray(value)) return [];
  return value
    .map((item) => {
      if (typeof item === 'string') return item;
      if (item && typeof item === 'object') return asString((item as Record<string, unknown>).message);
      return undefined;
    })
    .filter((item): item is string => !!item);
}

function normalizeValidation(value: unknown): TaskEmbedValidation | undefined {
  if (!value || typeof value !== 'object') return undefined;
  const record = value as Record<string, unknown>;
  const status = asString(record.status) === 'invalid' ? 'invalid' : 'valid';
  return { status, errors: messageList(record.errors), warnings: messageList(record.warnings) };
}

/** Short localized due date ("Nov 24") from an ISO date or timestamp; empty when absent or unparsable. */
export function formatTaskDueDate(value?: string, locale?: string): string {
  if (!value) return '';
  const parsed = /^\d{4}-\d{2}-\d{2}$/.test(value) ? new Date(`${value}T12:00:00`) : new Date(value);
  if (Number.isNaN(parsed.getTime())) return '';
  return new Intl.DateTimeFormat(locale, { month: 'short', day: 'numeric' }).format(parsed);
}

/** Text safe to show for a task: its short id (TASK-123) when present, never a UUID. */
export function taskVisibleId(shortId?: string): string {
  return shortId && !/^[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}$/i.test(shortId) ? shortId : '';
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
    due_date: asString(content.due_date),
    project_name: asString(content.project_name),
    validation: normalizeValidation(content.validation),
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
  if (value === 'openmates') return 'OpenMates';
  return value.replace(/_/g, ' ').replace(/\b\w/g, (match) => match.toUpperCase());
}

const TASK_STATUSES: ReadonlySet<string> = new Set(['backlog', 'todo', 'in_progress', 'blocked', 'done']);
const TASK_ASSIGNEES: ReadonlySet<string> = new Set(['user', 'openmates', 'external_ai', 'unassigned']);

/** Decode the saved task source for a card restore and its encrypted Task update. */
export function taskRestoreFromSource(source: string) {
  let parsed: unknown;
  try {
    parsed = JSON.parse(source);
  } catch {
    return null;
  }
  if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) return null;
  const record = parsed as Record<string, unknown>;
  const title = asString(record.title);
  const description = asString(record.description) ?? '';
  const status = asString(record.status) ?? 'todo';
  const assignee = asString(record.assignee)?.toLowerCase() ?? 'user';
  const assigneeType = assignee === 'me' ? 'user' : assignee;
  if (!title || !TASK_STATUSES.has(status) || !TASK_ASSIGNEES.has(assigneeType)) return null;
  const dueDate = asString(record.due_date) ?? '';
  const dateOnly = /^\d{4}-\d{2}-\d{2}$/.test(dueDate);
  const dueTime = dueDate ? Date.parse(dateOnly ? `${dueDate}T00:00:00Z` : dueDate) : null;
  if (dueTime !== null && Number.isNaN(dueTime)) return null;

  const patch = {
    title,
    description,
    status: status as UserTaskStatus,
    assigneeType: assigneeType as UserTaskAssigneeType,
    dueAt: dueTime === null ? null : Math.floor(dueTime / 1000),
  };
  return {
    patch,
    fields: { title, description, status, assignee_type: patch.assigneeType, due_date: dueDate },
  };
}
