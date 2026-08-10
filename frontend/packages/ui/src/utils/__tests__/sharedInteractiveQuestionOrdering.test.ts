// frontend/packages/ui/src/utils/__tests__/sharedInteractiveQuestionOrdering.test.ts
// Regression coverage for interactive question display ordering.
// Legacy rows may have user answer timestamps before their assistant question
// rows. The UI must repair only matched interactive pairs after decryption.

import { describe, expect, it } from 'vitest';
import type { Message } from '../../types/chat';
import { orderSharedInteractiveQuestionMessages } from '../sharedInteractiveQuestionOrdering';

function message(partial: Partial<Message> & Pick<Message, 'message_id' | 'role' | 'created_at' | 'content'>): Message {
  return {
    chat_id: 'shared-chat',
    status: 'synced',
    ...partial,
  } as Message;
}

function questionContent(id: string, label: string): string {
  return `${label}\n\n\`\`\`interactive_question\n${JSON.stringify({
    id,
    type: 'choice',
    question: label,
    options: [{ id: 'a', text: 'A' }],
  })}\n\`\`\``;
}

function responseContent(id: string, label: string): string {
  return `${label}\n\n\`\`\`interactive_response\n${JSON.stringify({
    id,
    type: 'choice',
    selection: ['a'],
  })}\n\`\`\``;
}

describe('orderSharedInteractiveQuestionMessages', () => {
  it('moves assistant questions before matched answers when shared timestamps are inverted', () => {
    const ordered = orderSharedInteractiveQuestionMessages([
      message({ message_id: 'prompt', role: 'user', created_at: 100, content: 'Explain machine learning' }),
      message({ message_id: 'answer-1', role: 'user', created_at: 110, content: responseContent('q1', 'Fundamentals') }),
      message({ message_id: 'answer-2', role: 'user', created_at: 120, content: responseContent('q2', 'Code example') }),
      message({ message_id: 'assistant-2', role: 'assistant', created_at: 200, content: questionContent('q2', 'Second question') }),
      message({ message_id: 'assistant-1', role: 'assistant', created_at: 200, content: questionContent('q1', 'First question') }),
      message({ message_id: 'assistant-3', role: 'assistant', created_at: 220, content: questionContent('q3', 'Unanswered question') }),
    ]);

    expect(ordered.map((item) => item.message_id)).toEqual([
      'prompt',
      'assistant-1',
      'answer-1',
      'assistant-2',
      'answer-2',
      'assistant-3',
    ]);
  });

  it('leaves already chronological interactive pairs unchanged', () => {
    const messages = [
      message({ message_id: 'prompt', role: 'user', created_at: 100, content: 'Explain machine learning' }),
      message({ message_id: 'assistant-1', role: 'assistant', created_at: 110, content: questionContent('q1', 'First question') }),
      message({ message_id: 'answer-1', role: 'user', created_at: 120, content: responseContent('q1', 'Fundamentals') }),
    ];

    expect(orderSharedInteractiveQuestionMessages(messages)).toBe(messages);
  });
});
