// contract-test-file: infrastructure
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
  isCustomChoiceOption,
  isInteractiveQuestionPayload,
  parseInteractiveQuestionBlock,
  toWaitingForUserResult,
  validateInteractiveQuestionAnswer,
} from "../src/interactiveQuestions.ts";

describe("CLI interactive question helpers", () => {
  // contract-test: supporting surface=cli assertions=cli.surface.semantic-parity
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

  // contract-test: supporting surface=cli assertions=cli.surface.semantic-parity
  it("parses choice option embed references", () => {
    const parsed = parseInteractiveQuestionBlock(`\`\`\`interactive_question
{
  "type": "choice",
  "id": "choose_snippet",
  "multiple": false,
  "question": "Which implementation should we use?",
  "options": [
    { "id": "minimal", "text": "Minimal implementation", "embed_ids": ["embed-code-a"] }
  ]
}
\`\`\`
`);

    assert.equal(parsed?.id, "choose_snippet");
    assert.deepEqual(parsed?.options?.[0]?.embed_ids, ["embed-code-a"]);
  });

  // contract-test: supporting surface=cli assertions=cli.surface.semantic-parity
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

  // contract-test: supporting surface=cli assertions=cli.surface.semantic-parity
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

  // contract-test: supporting surface=cli assertions=cli.surface.semantic-parity
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

  // contract-test: supporting surface=cli assertions=cli.surface.semantic-parity
  it("formats choice answers with selected embed IDs without duplicating embed content", () => {
    const result = formatInteractiveQuestionAnswer(
      {
        type: "choice",
        id: "choose_snippet",
        multiple: false,
        question: "Which implementation should we use?",
        options: [
          { id: "minimal", text: "Minimal implementation", embed_ids: ["embed-code-a"] },
          { id: "robust", text: "More robust implementation", embed_ids: ["embed-code-b"] },
        ],
      },
      { selection: ["robust"] },
    );

    assert.equal(result.displayText, "More robust implementation");
    assert.deepEqual(result.responsePayload.embed_ids, ["embed-code-b"]);
    assert.match(result.messageContent, /"embed_ids": \[/);
    assert.doesNotMatch(result.messageContent, /function robustImplementation/);
  });

  // contract-test: supporting surface=cli assertions=cli.surface.semantic-parity
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

  // contract-test: supporting surface=cli assertions=cli.surface.semantic-parity
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

  // contract-test: supporting surface=cli assertions=cli.surface.semantic-parity
  it("validates choice selection and custom text while preserving option order and answer immutability", () => {
    const question = {type: "choice" as const, id: "direction", question: "Choose", multiple: true,
      options: [{id: "first", text: "First", embed_ids: ["a"]}, {id: "own", text: "Other"},
        {id: "last", text: "Last", embed_ids: ["b"]}]};
    assert.equal(isCustomChoiceOption(question, "own"), true);
    assert.equal(validateInteractiveQuestionAnswer(question, {selection: ["last", "own"]}), "Enter a custom answer.");
    assert.equal(validateInteractiveQuestionAnswer(question, {selection: ["missing"]}), "Select a valid option.");
    const answer = {selection: ["last", "own", "first"], custom_answer: "My plan"};
    const result = formatInteractiveQuestionAnswer(question, answer);
    assert.equal(result.displayText, "First\nMy plan\nLast");
    assert.deepEqual(result.responsePayload.embed_ids, ["a", "b"]);
    assert.deepEqual(answer, {selection: ["last", "own", "first"], custom_answer: "My plan"});
  });

  // contract-test: supporting surface=cli assertions=cli.surface.semantic-parity
  it("formats input fields in question order and checks required text", () => {
    const question = {type: "input" as const, id: "form", fields: [
      {id: "first", label: "First", required: true}, {id: "optional", label: "Optional"},
      {id: "last", label: "Last", required: true}]};
    assert.equal(validateInteractiveQuestionAnswer(question, {inputs: {first: " ", last: "Done"}}), "Fill in every required field.");
    const result = formatInteractiveQuestionAnswer(question, {inputs: {last: "Done", first: "Start"}});
    assert.equal(result.displayText, "Start\nDone");
    assert.deepEqual(result.responsePayload.inputs, {first: "Start", optional: "", last: "Done"});
  });

  // contract-test: supporting surface=cli assertions=cli.surface.semantic-parity
  it("uses slider defaults and labels in the web schema while checking bounds and steps", () => {
    const question = {type: "slider" as const, id: "scale", question: "How much?", min: 0, max: 10,
      step: 0.5, default: 5, labels: {5: "middle"}};
    assert.equal(isInteractiveQuestionPayload(question), true);
    assert.equal(validateInteractiveQuestionAnswer(question, {value: 5.2}), "Choose a value on the slider step.");
    assert.equal(validateInteractiveQuestionAnswer(question, {value: 11}), "Choose a value within the slider range.");
    assert.equal(formatInteractiveQuestionAnswer(question, {value: 5}).displayText, "5 (middle)");
    assert.equal(isInteractiveQuestionPayload({...question, step: 0}), false);
  });

  // contract-test: supporting surface=cli assertions=cli.surface.semantic-parity
  it("requires a decision for every swipe card and formats all decisions", () => {
    const question = {type: "swipe" as const, id: "cards", cards: [
      {id: "a", text: "Alpha", embed_ids: ["embed-a"]},
      {id: "b", text: "Beta", embed_ids: ["embed-b"]}]};
    assert.equal(isInteractiveQuestionPayload(question), true);
    assert.equal(validateInteractiveQuestionAnswer(question, {swipes: {a: "like"}}), "Review every card.");
    const result = formatInteractiveQuestionAnswer(question, {swipes: {a: "like", b: "dislike"}});
    assert.equal(result.displayText, "Alpha: like\nBeta: dislike");
    assert.deepEqual(result.responsePayload.embed_ids, ["embed-a", "embed-b"]);
    assert.deepEqual(result.responsePayload.swipes, {a: "like", b: "dislike"});
  });

  // contract-test: supporting surface=cli assertions=cli.surface.semantic-parity
  it("defaults rating to five stars and enforces a required comment", () => {
    const question = {type: "rating" as const, id: "stars", question: "Rate this", require_comment: true};
    assert.equal(isInteractiveQuestionPayload(question), true);
    assert.equal(validateInteractiveQuestionAnswer(question, {rating: 0, comment: "Helpful"}), "Choose a rating from 1 to 5.");
    assert.equal(validateInteractiveQuestionAnswer(question, {rating: 4, comment: "  "}), "Enter a comment.");
    const result = formatInteractiveQuestionAnswer(question, {rating: 4, comment: " Helpful "});
    assert.equal(result.displayText, "4/5\nHelpful");
    assert.deepEqual(result.responsePayload, {id: "stars", rating: 4, comment: "Helpful"});
  });

  // contract-test: supporting surface=cli assertions=cli.surface.semantic-parity
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
