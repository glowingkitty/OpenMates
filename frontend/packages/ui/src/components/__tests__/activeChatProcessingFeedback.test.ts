/**
 * Processing-feedback terminal identity regression cases.
 * Local completion sources may carry a task ID, a user message ID, or both.
 * Every supplied identity must belong to the active feedback turn, and an
 * uncorrelated event must not clear another turn's indicator.
 */
import { describe, expect, it } from "vitest";
import { matchesProcessingFeedbackTerminal } from "../activeChatProcessingFeedback";

const feedbackTurn = { taskId: "task-b", userMessageId: "user-b" };

describe("processing feedback terminal identity", () => {
  // contract-test: supporting surface=gui.web assertions=chat-processing-feedback.turn-lifecycle
  it("accepts a matching available task or user identifier", () => {
    expect(matchesProcessingFeedbackTerminal(feedbackTurn, { taskId: "task-b" })).toBe(true);
    expect(matchesProcessingFeedbackTerminal(feedbackTurn, { userMessageId: "user-b" })).toBe(true);
  });

  // contract-test: supporting surface=gui.web assertions=chat-processing-feedback.turn-lifecycle
  it("requires every supplied identifier to match", () => {
    expect(matchesProcessingFeedbackTerminal(feedbackTurn, {
      taskId: "task-b",
      userMessageId: "user-a",
    })).toBe(false);
    expect(matchesProcessingFeedbackTerminal(feedbackTurn, {
      taskId: "task-a",
      userMessageId: "user-b",
    })).toBe(false);
  });

  // contract-test: supporting surface=gui.web assertions=chat-processing-feedback.turn-lifecycle
  it("rejects terminal events without an identity", () => {
    expect(matchesProcessingFeedbackTerminal(feedbackTurn, {})).toBe(false);
  });
});
