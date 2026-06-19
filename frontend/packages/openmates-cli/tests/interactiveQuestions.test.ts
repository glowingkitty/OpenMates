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

  it("parses rating questions that use the web max_stars schema", () => {
    const parsed = parseInteractiveQuestionBlock(`\`\`\`interactive_question
{
  "type": "rating",
  "id": "rate_experience",
  "question": "How useful was this?",
  "max_stars": 5
}
\`\`\`
`);

    assert.equal(parsed?.id, "rate_experience");
    assert.equal(parsed?.type, "rating");
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

  it("formats input answers from the web-compatible inputs object", () => {
    const result = formatInteractiveQuestionAnswer(
      {
        type: "input",
        id: "experience",
        question: "What do you want to practice?",
        fields: [{ id: "topic", label: "Topic", required: true }],
      },
      { inputs: { topic: "Backend tests" } },
    );

    assert.equal(result.displayText, "Backend tests");
    assert.match(result.messageContent, /"inputs"/);
    assert.match(result.messageContent, /```interactive_response/);
  });

  it("formats custom choice answers as typed answer text plus hidden protocol", () => {
    const result = formatInteractiveQuestionAnswer(
      {
        type: "choice",
        id: "project_direction",
        multiple: false,
        question: "What should we work on next?",
        custom_option_id: "own_answer",
        custom_placeholder: "Type your own answer",
        options: [
          { id: "ship_fix", text: "Ship the bug fix" },
          { id: "own_answer", text: "I give you my own answer" },
        ],
      },
      { selection: ["own_answer"], custom_answer: "Let users type a custom response" },
    );

    assert.equal(result.displayText, "Let users type a custom response");
    assert.ok(result.messageContent.startsWith("Let users type a custom response"));
    assert.match(result.messageContent, /"custom_answer": "Let users type a custom response"/);
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
