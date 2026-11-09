/**
 * Turns a chat Recommendation into an unsaved draft: a Memory draft for Settings > Memories
 * (billed create-draft or update-preview request) or the authoring instruction for the
 * workflow side panel. Nothing here saves a Memory or a Workflow.
 * Plan: docs/plans/chat-recommendations/plan.yml (D-8, wire_contract.memory_create_draft_endpoint)
 * Spec: app-memories.suggestions.post-processor, app-memories.suggestions.billing.
 */
import { getApiEndpoint } from '../config/api';
import { chatDB } from './db';
import { listPersonalRuleDocuments, type EditableRuleDocument } from './ruleDocumentService';
import { parseRuleDocument } from '../utils/ruleDocuments';
import type { MemoryDraftPayload } from '../stores/memoryDraftSuggestionStore';
import type { ChatRecommendation } from '../types/recommendations';

export const RECOMMENDATION_DRAFT_WIRE = {
  createDraftPath: '/v1/memory-suggestions/create-draft',
  updatePreviewPath: '/v1/memory-suggestions/update-preview',
  insufficientCreditsStatus: 402,
} as const;

export type RecommendationDraftFailure = 'insufficient_credits' | 'memory_not_found' | 'request_failed';

export class RecommendationDraftError extends Error {
  constructor(readonly code: RecommendationDraftFailure) { super(code); }
}

/** Draft id used for a not-yet-existing memory; Settings routes it as memories/<id>. */
export const NEW_MEMORY_DRAFT_ID = 'suggested-new-memory';

/** Longest turn text sent to a draft request or the workflow instruction. */
const MAX_TURN_TEXT = 8_000;

export interface UpdatePreviewMessage { role: 'user' | 'assistant'; text: string }

export interface UpdatePreviewRequestBody {
  chat_id: string;
  memory_id: string;
  memory_markdown: string;
  messages: UpdatePreviewMessage[];
}

/** body is the full updated canonical Markdown document. */
export type UpdatePreviewResult = { status: 'updated'; body: string } | { status: 'unchanged' };

/** The previous user message and the last assistant response, decrypted on this device. */
export interface RecommendationTurn { userMessage: string; assistantResponse: string }

const nonEmpty = (value: unknown): value is string => typeof value === 'string' && value.trim().length > 0;

/** Embed reference blocks point at tool/external results; they are never draft input. */
const EMBED_REFERENCE_BLOCK = /```json\s*\{[^`]*"embed_id"[^`]*\}\s*```/g;

export function previewMessageText(content: string): string {
  return content.replace(EMBED_REFERENCE_BLOCK, '').trim();
}

/** Text of user/assistant turns only, oldest first. */
export function toPreviewMessages(
  messages: ReadonlyArray<{ role: string; content?: unknown; created_at?: number }>,
): UpdatePreviewMessage[] {
  return [...messages]
    .filter(message => message.role === 'user' || message.role === 'assistant')
    .sort((a, b) => (a.created_at ?? 0) - (b.created_at ?? 0))
    .flatMap(message => {
      const text = typeof message.content === 'string' ? previewMessageText(message.content) : '';
      return text ? [{ role: message.role as 'user' | 'assistant', text }] : [];
    });
}

/** Last assistant response and the user message right before it. */
export function latestTurn(messages: UpdatePreviewMessage[]): RecommendationTurn {
  const assistantIndex = messages.map(message => message.role).lastIndexOf('assistant');
  const assistantResponse = assistantIndex >= 0 ? messages[assistantIndex].text : '';
  const before = assistantIndex >= 0 ? messages.slice(0, assistantIndex) : messages;
  const userMessage = [...before].reverse().find(message => message.role === 'user')?.text ?? '';
  return {
    userMessage: userMessage.slice(0, MAX_TURN_TEXT),
    assistantResponse: assistantResponse.slice(0, MAX_TURN_TEXT),
  };
}

async function chatPreviewMessages(chatId: string): Promise<UpdatePreviewMessage[]> {
  // getMessagesForChat decrypts with the chat key on this device.
  return toPreviewMessages(await chatDB.getMessagesForChat(chatId));
}

export async function loadRecommendationTurn(chatId: string): Promise<RecommendationTurn> {
  return latestTurn(await chatPreviewMessages(chatId));
}

/** Instruction for the existing AI workflow authoring stream (side panel draft). */
export function buildWorkflowInstruction(
  recommendation: Pick<ChatRecommendation, 'action' | 'title' | 'summary'>,
  turn: RecommendationTurn,
): string {
  const lead = recommendation.action === 'update'
    ? `Update this workflow: ${recommendation.title}`
    : `Create a workflow: ${recommendation.title}`;
  return [
    lead,
    `Summary: ${recommendation.summary}`,
    'Base it on this chat turn.',
    `Previous user message:\n${turn.userMessage}`,
    `Last assistant response:\n${turn.assistantResponse}`,
  ].join('\n\n');
}

function draftFields(canonicalDocument: string): Omit<MemoryDraftPayload, 'id'> {
  // Server drafts carry a full canonical document; the editor wants its fields.
  const fields = parseRuleDocument(canonicalDocument);
  return {
    title: fields.title, memory: fields.body, when_to_use: fields.when_to_use,
    load_mode: fields.load_mode, valid_from: fields.valid_from, valid_until: fields.valid_until,
  };
}

/** body: canonical Markdown document returned by create-draft. */
export function newMemoryDraft(input: { body: string }): MemoryDraftPayload {
  return { id: NEW_MEMORY_DRAFT_ID, ...draftFields(input.body), is_new: true };
}

/** body: canonical Markdown document returned by the update preview. */
export function updateMemoryDraft(document: EditableRuleDocument, body: string): MemoryDraftPayload {
  return {
    id: document.id, ...draftFields(body),
    // Revision recorded at preview time: Save reports a conflict if the memory changed since.
    base_document: document.document,
  };
}

export async function loadPersonalMemory(memoryId: string): Promise<EditableRuleDocument> {
  const documents = await listPersonalRuleDocuments();
  const found = documents.find(item => item.id === memoryId || item.id === `personal:${memoryId}`);
  if (!found) throw new RecommendationDraftError('memory_not_found');
  return found;
}

async function postBilled(path: string, body: unknown): Promise<unknown> {
  const response = await fetch(getApiEndpoint(path), {
    method: 'POST', credentials: 'include', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
  if (response.status === RECOMMENDATION_DRAFT_WIRE.insufficientCreditsStatus) {
    throw new RecommendationDraftError('insufficient_credits');
  }
  if (!response.ok) throw new RecommendationDraftError('request_failed');
  try {
    return await response.json();
  } catch {
    throw new RecommendationDraftError('request_failed');
  }
}

/** Throws on a response that is neither a diff nor an explicit unchanged result. */
export function parseUpdatePreviewResponse(raw: unknown): UpdatePreviewResult {
  const item = raw && typeof raw === 'object' ? raw as Record<string, unknown> : {};
  if (item.status === 'updated' && nonEmpty(item.body)) return { status: 'updated', body: item.body };
  if (item.status === 'unchanged') return { status: 'unchanged' };
  throw new RecommendationDraftError('request_failed');
}

/** Throws unless the response carries a parseable canonical memory document. */
export function parseCreateDraftResponse(raw: unknown): { body: string } {
  const item = raw && typeof raw === 'object' ? raw as Record<string, unknown> : {};
  if (!nonEmpty(item.body)) throw new RecommendationDraftError('request_failed');
  try {
    parseRuleDocument(item.body);
  } catch {
    throw new RecommendationDraftError('request_failed');
  }
  return { body: item.body };
}

/**
 * Billed to the chat by the server. Sends the recommendation and the latest turn text
 * (decrypted locally); returns the unsaved new-memory draft.
 */
export async function requestCreateMemoryDraft(
  chatId: string,
  recommendation: Pick<ChatRecommendation, 'title' | 'summary'>,
): Promise<MemoryDraftPayload> {
  const turn = await loadRecommendationTurn(chatId);
  const raw = await postBilled(RECOMMENDATION_DRAFT_WIRE.createDraftPath, {
    chat_id: chatId,
    title: recommendation.title,
    summary: recommendation.summary,
    user_message: turn.userMessage,
    assistant_response: turn.assistantResponse,
  });
  return newMemoryDraft(parseCreateDraftResponse(raw));
}

/** Billed to the chat by the server; the request body is the only place text is sent. */
export async function requestUpdatePreview(chatId: string, memoryId: string): Promise<{
  document: EditableRuleDocument; result: UpdatePreviewResult;
}> {
  const document = await loadPersonalMemory(memoryId);
  const body: UpdatePreviewRequestBody = {
    chat_id: chatId, memory_id: document.id, memory_markdown: document.document,
    messages: await chatPreviewMessages(chatId),
  };
  const raw = await postBilled(RECOMMENDATION_DRAFT_WIRE.updatePreviewPath, body);
  return { document, result: parseUpdatePreviewResponse(raw) };
}
