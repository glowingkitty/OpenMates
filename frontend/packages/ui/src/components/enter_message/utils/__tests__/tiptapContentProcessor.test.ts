// frontend/packages/ui/src/components/enter_message/utils/__tests__/tiptapContentProcessor.test.ts
// Regression coverage for the legacy TipTap preprocessing pass.
// Some shared-chat markdown reaches this pass as raw fenced text nodes after
// decryption/reload. The preprocessor must preserve code bodies when it upgrades
// those fences into embed nodes, or renderers cannot recover semantic payloads.
// This is intentionally scoped to the public exported preprocessor.

import { describe, expect, it } from "vitest";
import { preprocessTiptapJsonForEmbeds } from "../tiptapContentProcessor";

describe("preprocessTiptapJsonForEmbeds", () => {
  // contract-test: supporting surface=gui.web assertions=chats.surface.semantic-parity
  it("preserves raw interactive question fence payloads when creating code embeds", () => {
    const payload = JSON.stringify({
      id: "iphone_interest_2026",
      type: "choice",
      question: "Which iPhone topic should we explore next?",
      options: [{ id: "camera", text: "Camera rumors" }],
    });
    const doc = {
      type: "doc" as const,
      content: [
        {
          type: "paragraph",
          content: [
            {
              type: "text",
              text: `\`\`\`interactive_question\n${payload}\n\`\`\``,
            },
          ],
        },
      ],
    };

    const processed = preprocessTiptapJsonForEmbeds(doc);
    const attrs = processed?.content[0]?.content?.[0]?.attrs;

    expect(attrs).toMatchObject({
      type: "code-code",
      contentRef: null,
      language: "interactive_question",
      filename: "Code snippet",
      lineCount: 1,
      code: payload,
    });
  });
});
