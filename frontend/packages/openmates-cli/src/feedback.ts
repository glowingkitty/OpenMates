/*
 * Assistant response feedback contract helpers.
 *
 * Purpose: keep CLI feedback decisions aligned with the web chat footer.
 * Architecture: pure helpers, no network writes, so tests can verify parity cheaply.
 * Web source: frontend/packages/ui/src/components/ChatHistory.svelte
 * Tests: frontend/packages/openmates-cli/tests/cli.test.ts
 */

export const ASSISTANT_FEEDBACK_THANKS = "Thanks for the feedback!";
export const ASSISTANT_FEEDBACK_REPORT_TITLE = "Assistant response quality bad:";

export type AssistantFeedbackDecision = {
  rating: number;
  action: "thanks" | "report_issue";
  message: string;
  reportTitle?: string;
};

export function buildAssistantFeedbackDecision(rating: number): AssistantFeedbackDecision {
  if (!Number.isInteger(rating) || rating < 1 || rating > 5) {
    throw new Error("Rating must be an integer from 1 to 5.");
  }

  if (rating <= 3) {
    return {
      rating,
      action: "report_issue",
      message: ASSISTANT_FEEDBACK_THANKS,
      reportTitle: ASSISTANT_FEEDBACK_REPORT_TITLE,
    };
  }

  return {
    rating,
    action: "thanks",
    message: ASSISTANT_FEEDBACK_THANKS,
  };
}
