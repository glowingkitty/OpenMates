/**
 * frontend/packages/ui/src/services/__tests__/sendersChatMessagesProtocol.test.ts
 *
 * Regression tests for protocol fenced blocks in the client message sender.
 * Interactive question answers are chat protocol, not user-authored code embeds.
 */

import { describe, expect, it } from "vitest";
import { shouldSkipClientCodeBlockExtraction } from "../sendersChatMessages";

describe("sendersChatMessages protocol fences", () => {
  it("does not extract interactive question protocol blocks as code embeds", () => {
    expect(shouldSkipClientCodeBlockExtraction("interactive_question", "{}"))
      .toBe(true);
    expect(shouldSkipClientCodeBlockExtraction("interactive_response", "{}"))
      .toBe(true);
  });

  it("continues extracting regular code fences", () => {
    expect(shouldSkipClientCodeBlockExtraction("typescript", "const answer = 42;"))
      .toBe(false);
  });
});
