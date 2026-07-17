/**
 * frontend/packages/ui/src/services/__tests__/sendersChatMessagesProtocol.test.ts
 *
 * Regression tests for protocol fenced blocks in the client message sender.
 * Interactive question answers are chat protocol, not user-authored code embeds.
 */

import { describe, expect, it } from "vitest";
import {
  preflightExpectedMessagesVersion,
  shouldIncludePreflightChatMetadata,
  shouldSkipClientCodeBlockExtraction,
} from "../sendersChatMessages";

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

  it("uses the server version before the locally saved user message", () => {
    expect(preflightExpectedMessagesVersion(undefined)).toBe(0);
    expect(preflightExpectedMessagesVersion(1)).toBe(0);
    expect(preflightExpectedMessagesVersion(7)).toBe(6);
  });

  it("only includes encrypted chat metadata on the first local message", () => {
    expect(shouldIncludePreflightChatMetadata(undefined)).toBe(true);
    expect(shouldIncludePreflightChatMetadata(1)).toBe(true);
    expect(shouldIncludePreflightChatMetadata(2)).toBe(false);
    expect(shouldIncludePreflightChatMetadata(7)).toBe(false);
  });
});
