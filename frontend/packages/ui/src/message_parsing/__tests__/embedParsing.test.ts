// Unit tests for JSON embed-reference parsing.
// Covers persistence-sensitive attributes that survive draft reloads.
// Reference-only embeds point at existing synced uploads and must remain
// non-destructive after markdown serialization and parsing.
// These tests intentionally exercise public parser behavior only.

import { describe, expect, it } from "vitest";
import { parseEmbedNodes } from "../embedParsing";

describe("parseEmbedNodes", () => {
  // contract-test: supporting surface=gui.web assertions=chats.surface.semantic-parity
  it("restores reference-only metadata from JSON embed references", () => {
    const markdown = `\`\`\`json
{
  "type": "pdf",
  "embed_id": "uploaded-file-1",
  "filename": "report.pdf",
  "reference_only": true
}
\`\`\``;

    const [embed] = parseEmbedNodes(markdown, "write");

    expect(embed).toMatchObject({
      id: "uploaded-file-1",
      type: "pdf",
      contentRef: "embed:uploaded-file-1",
      filename: "report.pdf",
      referenceOnly: true,
    });
  });

  // contract-test: supporting surface=gui.web assertions=chats.surface.semantic-parity
  it("keeps complete JSON embed references finished when no status is present", () => {
    const markdown = `\`\`\`json
{
  "type": "code",
  "embed_id": "finished-code-1"
}
\`\`\``;

    const [embed] = parseEmbedNodes(markdown, "write");

    expect(embed).toMatchObject({
      id: "finished-code-1",
      type: "code-code",
      contentRef: "embed:finished-code-1",
      status: "finished",
    });
  });

  // contract-test: supporting surface=gui.web assertions=chats.surface.semantic-parity
  it("preserves explicit processing status from JSON embed references", () => {
    const markdown = `\`\`\`json
{
  "type": "code",
  "embed_id": "processing-code-1",
  "status": "processing"
}
\`\`\``;

    const [embed] = parseEmbedNodes(markdown, "write");

    expect(embed).toMatchObject({
      id: "processing-code-1",
      type: "code-code",
      contentRef: "embed:processing-code-1",
      status: "processing",
    });
  });

  // contract-test: supporting surface=gui.web assertions=chats.surface.semantic-parity
  it("preserves interactive question payloads in read-mode code blocks", () => {
    const payload = {
      id: "question-1",
      type: "choice",
      question: "Pick one",
      options: [{ id: "a", text: "A" }],
    };
    const markdown = `\`\`\`interactive_question
${JSON.stringify(payload)}
\`\`\``;

    const [embed] = parseEmbedNodes(markdown, "read");

    expect(embed).toMatchObject({
      type: "code-code",
      language: "interactive_question",
      code: JSON.stringify(payload),
    });
  });
});
