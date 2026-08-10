// frontend/packages/ui/src/utils/__tests__/rememberMessage.test.ts
//
// Verifies visible quote-block formatting for forgotten-message recall.
// The formatter must preserve markdown/embed refs because the user edits and
// sends this plaintext draft explicitly instead of mutating hidden context.

import { describe, expect, it } from "vitest";
import { formatRememberMessageDraft } from "../rememberMessage";

describe("formatRememberMessageDraft", () => {
  it("formats multiline content as an editable markdown quote block", () => {
    expect(formatRememberMessageDraft("First line\nSecond [embed](embed:abc123)")).toBe(
      "Remember my earlier message:\n\n> First line\n> Second [embed](embed:abc123)",
    );
  });

  it("keeps empty remembered content visible without adding a blank quote", () => {
    expect(formatRememberMessageDraft("  \n\t")).toBe("Remember my earlier message:");
  });
});
