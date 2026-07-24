/**
 * frontend/packages/ui/src/components/interactive_questions/utils/questionState.test.ts
 *
 * Regression coverage for interactive-question history reconciliation.
 * Answered cards must lock from a matching later response, while orphan
 * responses from a truncated/shared window must not falsely select a card.
 */

import { describe, expect, it } from "vitest";
import type { Message } from "../../../types/chat";
import { findSubsequentResponse } from "./questionState";

const QUESTION_ID = "question-1";

function message(partial: Partial<Message> & Pick<Message, "message_id" | "role" | "content">): Message {
  return {
    chat_id: "chat-1",
    created_at: 1,
    status: "synced",
    ...partial,
  } as Message;
}

function interactiveQuestionContent(id = QUESTION_ID): string {
  return `Pick one\n\n\`\`\`interactive_question\n${JSON.stringify({
    id,
    type: "choice",
    question: "Pick one",
    options: [{ id: "a", text: "A" }],
  })}\n\`\`\``;
}

function interactiveResponseContent(id = QUESTION_ID): string {
  return `A\n\n\`\`\`interactive_response\n${JSON.stringify({
    id,
    type: "choice",
    selection: ["a"],
  })}\n\`\`\``;
}

describe("findSubsequentResponse", () => {
  it("returns the matching response after the latest matching question", () => {
    const response = findSubsequentResponse([
      message({ message_id: "assistant-1", role: "assistant", content: interactiveQuestionContent() }),
      message({ message_id: "user-1", role: "user", content: interactiveResponseContent() }),
    ], QUESTION_ID);

    expect(response).toMatchObject({
      id: QUESTION_ID,
      type: "choice",
      selection: ["a"],
    });
  });

  it("ignores orphan responses when the question is not present earlier in history", () => {
    const response = findSubsequentResponse([
      message({ message_id: "user-1", role: "user", content: interactiveResponseContent() }),
      message({ message_id: "assistant-1", role: "assistant", content: interactiveQuestionContent() }),
    ], QUESTION_ID);

    expect(response).toBeNull();
  });
});
