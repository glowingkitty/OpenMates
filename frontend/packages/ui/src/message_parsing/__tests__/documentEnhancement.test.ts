// Unit tests for document-level embed enhancement.
// Covers read-mode safety guards that keep internal protocol blocks
// out of visible assistant messages when an embed reference cannot be
// matched to a renderable embed node.
// These tests intentionally avoid renderer internals and assert the
// TipTap document that reaches the read-only message UI.

import { describe, expect, it } from "vitest";
import { enhanceDocumentWithEmbeds } from "../documentEnhancement";

describe("enhanceDocumentWithEmbeds", () => {
  it("does not render unmatched app_skill_use protocol JSON as a code block", () => {
    const doc = {
      type: "doc",
      content: [
        {
          type: "codeBlock",
          attrs: { language: "json" },
          content: [
            {
              type: "text",
              text: JSON.stringify({
                type: "app_skill_use",
                embed_id: "embed-with-missing-match",
                app_id: "images",
                skill_id: "view",
              }),
            },
          ],
        },
        {
          type: "paragraph",
          content: [{ type: "text", text: "Visible answer text" }],
        },
      ],
    };

    const enhanced = enhanceDocumentWithEmbeds(doc, [], "read");

    expect(JSON.stringify(enhanced)).not.toContain("app_skill_use");
    expect(JSON.stringify(enhanced)).not.toContain("embed-with-missing-match");
    expect(enhanced.content).toEqual([
      {
        type: "paragraph",
        content: [{ type: "text", text: "Visible answer text" }],
      },
    ]);
  });
});
