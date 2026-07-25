// frontend/packages/ui/src/utils/sharedInteractiveQuestionOrdering.ts
// Repairs display order for historical interactive questions.
// Some legacy rows have user answer timestamps before the assistant question.
// This utility uses decrypted protocol blocks to infer the visible order without
// mutating persisted messages or server data. It is a no-op for chronological
// chats and for messages without matched interactive question/response pairs.

import type { Message } from '../types/chat';

const INTERACTIVE_QUESTION_BLOCK_RE = /```interactive_question\s*([\s\S]*?)\s*```/g;
const INTERACTIVE_RESPONSE_BLOCK_RE = /```interactive_response\s*([\s\S]*?)\s*```/;
const QUESTION_BEFORE_RESPONSE_OFFSET = 0.5;

type IndexedMessage<T extends Message> = {
  message: T;
  index: number;
  questionIds: string[];
  responseId: string | null;
  sortKey: number;
};

function extractQuestionIds(content: unknown): string[] {
  if (typeof content !== 'string') return [];
  const ids: string[] = [];
  INTERACTIVE_QUESTION_BLOCK_RE.lastIndex = 0;

  let match = INTERACTIVE_QUESTION_BLOCK_RE.exec(content);
  while (match) {
    try {
      const parsed = JSON.parse(match[1]) as { id?: unknown };
      if (typeof parsed.id === 'string' && parsed.id.trim()) ids.push(parsed.id);
    } catch {
      // Malformed historic blocks should not affect message ordering.
    }
    match = INTERACTIVE_QUESTION_BLOCK_RE.exec(content);
  }

  return ids;
}

function extractResponseId(content: unknown): string | null {
  if (typeof content !== 'string') return null;
  const match = content.match(INTERACTIVE_RESPONSE_BLOCK_RE);
  if (!match) return null;

  try {
    const parsed = JSON.parse(match[1]) as { id?: unknown };
    return typeof parsed.id === 'string' && parsed.id.trim() ? parsed.id : null;
  } catch {
    return null;
  }
}

function nearestQuestionIndex(questionIndexes: number[], responseIndex: number): number | null {
  const priorQuestionIndexes = questionIndexes.filter((index) => index < responseIndex);
  if (priorQuestionIndexes.length > 0) return priorQuestionIndexes[priorQuestionIndexes.length - 1];
  return questionIndexes.length > 0 ? questionIndexes[questionIndexes.length - 1] : null;
}

export function orderSharedInteractiveQuestionMessages<T extends Message>(messages: T[]): T[] {
  if (messages.length < 2) return messages;

  const indexedMessages: IndexedMessage<T>[] = messages.map((message, index) => ({
    message,
    index,
    questionIds: message.role === 'assistant' ? extractQuestionIds(message.content) : [],
    responseId: message.role === 'user' ? extractResponseId(message.content) : null,
    sortKey: Number.isFinite(message.created_at) ? message.created_at : index,
  }));

  const questionIndexesById = new Map<string, number[]>();
  for (const indexed of indexedMessages) {
    for (const questionId of indexed.questionIds) {
      const indexes = questionIndexesById.get(questionId) ?? [];
      indexes.push(indexed.index);
      questionIndexesById.set(questionId, indexes);
    }
  }

  let changed = false;
  for (const indexed of indexedMessages) {
    if (!indexed.responseId) continue;
    const questionIndexes = questionIndexesById.get(indexed.responseId);
    if (!questionIndexes || questionIndexes.length === 0) continue;

    const questionIndex = nearestQuestionIndex(questionIndexes, indexed.index);
    if (questionIndex === null || indexed.index > questionIndex) continue;

    const question = indexedMessages[questionIndex];
    const repairedQuestionSortKey = indexed.sortKey - QUESTION_BEFORE_RESPONSE_OFFSET;
    if (question.sortKey > repairedQuestionSortKey) {
      question.sortKey = repairedQuestionSortKey;
      changed = true;
    }
  }

  if (!changed) return messages;

  return [...indexedMessages]
    .sort((a, b) => a.sortKey - b.sortKey || a.index - b.index)
    .map((indexed) => indexed.message);
}
