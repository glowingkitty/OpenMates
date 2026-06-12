/**
 * Unit tests for CLI interactive question protocol helpers.
 *
 * These tests keep terminal rendering, automation JSON, and hidden protocol
 * response formatting aligned with the web/Apple product contract.
 */

import { describe, it } from "node:test";
import assert from "node:assert/strict";

import {
  formatInteractiveQuestionAnswer,
  parseInteractiveQuestionBlock,
  toWaitingForUserResult,
} from "../src/interactiveQuestions.ts";

describe("CLI interactive question helpers", () => {
  it("parses a valid interactive_question fenced block", () => {
    const parsed = parseInteractiveQuestionBlock(`Intro

\`\`\`interactive_question
{
  "type": "choice",
  "id": "python_slicing",
  "multiple": false,
  "question": "Which expression returns every second item?",
  "options": [
    { "id": "step_2", "text": "items[::2]" },
    { "id": "from_2", "text": "items[2:]" }
  ]
}
\`\`\`
`);

    assert.equal(parsed?.id, "python_slicing");
    assert.equal(parsed?.type, "choice");
  });

  it("parses valid input questions without a top-level question", () => {
    const parsed = parseInteractiveQuestionBlock(`\`\`\`interactive_question
{
  "type": "input",
  "id": "experience",
  "fields": [{ "id": "topic", "label": "Topic", "required": true }]
}
\`\`\`
`);

    assert.equal(parsed?.id, "experience");
    assert.equal(parsed?.type, "input");
  });

  it("formats choice answers as answer-only display text plus hidden protocol", () => {
    const result = formatInteractiveQuestionAnswer(
      {
        type: "choice",
        id: "python_slicing",
        multiple: false,
        question: "Which expression returns every second item?",
        options: [
          { id: "step_2", text: "items[::2]" },
          { id: "from_2", text: "items[2:]" },
        ],
      },
      { selection: ["step_2"] },
    );

    assert.equal(result.displayText, "items[::2]");
    assert.ok(!result.messageContent.startsWith("Selected:"));
    assert.ok(result.messageContent.startsWith("items[::2]"));
    assert.match(result.messageContent, /```interactive_response/);
    assert.match(result.messageContent, /"id": "python_slicing"/);
  });

  it("builds structured waiting_for_user JSON for automation", () => {
    const question = {
      type: "input" as const,
      id: "experience",
      question: "What do you want to practice?",
      fields: [{ id: "topic", label: "Topic", required: true }],
    };

    const result = toWaitingForUserResult({
      chatId: "parent-chat",
      messageId: "assistant-question",
      parentId: "parent-chat",
      question,
    });

    assert.equal(result.status, "waiting_for_user");
    assert.equal(result.chat_id, "parent-chat");
    assert.equal(result.message_id, "assistant-question");
    assert.deepEqual(result.question, question);
  });
});
