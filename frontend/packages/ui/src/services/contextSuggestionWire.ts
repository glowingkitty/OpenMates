/**
 * Wire adapter for post-processor context suggestions (memory create/update, workflow create).
 *
 * ALL server wire names live in this module so the backend contract can change in one place.
 * Spec: app-memories.suggestions.post-processor, app-memories.suggestions.billing.
 */

/** Names assumed for the server contract; adjust here only. */
export const CONTEXT_SUGGESTION_WIRE = {
  /** Field on the post_processing_completed payload carrying one suggestion (or null/absent). */
  postProcessingField: 'context_suggestion',
  /** POST endpoint for a billed memory update preview. */
  updatePreviewPath: '/v1/memory-suggestions/update-preview',
  kinds: { update: 'memory_update', create: 'memory_create', workflow: 'workflow_create' },
  statuses: { updated: 'updated', unchanged: 'unchanged' },
  insufficientCreditsStatus: 402,
} as const;

export type ContextSuggestion =
  | { kind: 'memory_update'; memoryId: string; title: string }
  /** body is the full canonical Markdown document (frontmatter + body). */
  | { kind: 'memory_create'; title: string; body: string }
  | { kind: 'workflow_create'; title: string; summary: string };

export interface UpdatePreviewMessage { role: 'user' | 'assistant'; text: string }

export interface UpdatePreviewRequestBody {
  chat_id: string;
  memory_id: string;
  memory_markdown: string;
  messages: UpdatePreviewMessage[];
}

/** body is the full updated canonical Markdown document. */
export type UpdatePreviewResult = { status: 'updated'; body: string } | { status: 'unchanged' };

const MAX_TITLE = 200;
const nonEmpty = (value: unknown): value is string => typeof value === 'string' && value.trim().length > 0;

/** Reads the suggestion from a post-processing payload; unknown or malformed shapes yield null. */
export function parseContextSuggestion(payload: unknown): ContextSuggestion | null {
  if (!payload || typeof payload !== 'object') return null;
  const raw = (payload as Record<string, unknown>)[CONTEXT_SUGGESTION_WIRE.postProcessingField];
  if (!raw || typeof raw !== 'object') return null;
  const item = raw as Record<string, unknown>;
  const { kinds } = CONTEXT_SUGGESTION_WIRE;
  if (!nonEmpty(item.title)) return null;
  const title = item.title.trim().slice(0, MAX_TITLE);
  if (item.kind === kinds.update && nonEmpty(item.memory_id)) {
    return { kind: 'memory_update', memoryId: item.memory_id, title };
  }
  if (item.kind === kinds.create && nonEmpty(item.body)) {
    return { kind: 'memory_create', title, body: item.body };
  }
  if (item.kind === kinds.workflow && nonEmpty(item.summary)) {
    return { kind: 'workflow_create', title, summary: item.summary.trim() };
  }
  return null;
}

/** Stable per-suggestion key used for local dismissal. */
export function contextSuggestionKey(suggestion: ContextSuggestion): string {
  const target = suggestion.kind === 'memory_update' ? suggestion.memoryId : '';
  return `${suggestion.kind}:${target}:${suggestion.title}`;
}

export function buildUpdatePreviewRequest(input: {
  chatId: string; memoryId: string; memoryMarkdown: string; messages: UpdatePreviewMessage[];
}): UpdatePreviewRequestBody {
  return {
    chat_id: input.chatId,
    memory_id: input.memoryId,
    memory_markdown: input.memoryMarkdown,
    messages: input.messages,
  };
}

/** Throws on a response that is neither a diff nor an explicit unchanged result. */
export function parseUpdatePreviewResponse(raw: unknown): UpdatePreviewResult {
  const item = raw && typeof raw === 'object' ? raw as Record<string, unknown> : {};
  if (item.status === CONTEXT_SUGGESTION_WIRE.statuses.updated && nonEmpty(item.body)) {
    return { status: 'updated', body: item.body };
  }
  if (item.status === CONTEXT_SUGGESTION_WIRE.statuses.unchanged) return { status: 'unchanged' };
  throw new Error('context_suggestion_invalid_response');
}
