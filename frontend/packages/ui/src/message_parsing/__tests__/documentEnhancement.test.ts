// Unit tests for document-level embed enhancement.
// Covers read-mode safety guards that keep internal protocol blocks
// out of visible assistant messages when an embed reference cannot be
// matched to a renderable embed node.
// These tests intentionally avoid renderer internals and assert the
// TipTap document that reaches the read-only message UI.

import { describe, expect, it } from "vitest";
import { enhanceDocumentWithEmbeds } from "../documentEnhancement";

describe("enhanceDocumentWithEmbeds", () => {
  // contract-test: supporting surface=gui.web assertions=chats.surface.semantic-parity
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

  // contract-test: supporting surface=gui.web assertions=chats.surface.semantic-parity
  it("preserves read-mode interactive question payloads on matched code embeds", () => {
    const payload = {
      type: "choice",
      id: "iphone_interest_2026",
      multiple: false,
      question: "Which iPhone topic should we explore next?",
      options: [{ id: "camera", text: "Camera rumors" }],
    };
    const codeText = JSON.stringify(payload, null, 2);
    const doc = {
      type: "doc",
      content: [
        {
          type: "codeBlock",
          attrs: { language: "interactive_question" },
          content: [{ type: "text", text: codeText }],
        },
      ],
    };

    const enhanced = enhanceDocumentWithEmbeds(doc, [
      {
        id: "historical-question-embed",
        type: "code-code",
        status: "finished",
        contentRef: null,
        language: "interactive_question",
        filename: "Code snippet",
      },
    ], "read");

    expect(enhanced.content?.[0]?.content?.[0]?.attrs).toMatchObject({
      id: "historical-question-embed",
      type: "code-code",
      language: "interactive_question",
      code: codeText,
    });
  });
});
