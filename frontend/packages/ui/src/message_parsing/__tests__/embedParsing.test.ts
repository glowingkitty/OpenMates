// Unit tests for JSON embed-reference parsing.
// Covers persistence-sensitive attributes that survive draft reloads.
// Reference-only embeds point at existing synced uploads and must remain
// non-destructive after markdown serialization and parsing.
// These tests intentionally exercise public parser behavior only.

import { describe, expect, it } from "vitest";
import { parseEmbedNodes } from "../embedParsing";

describe("parseEmbedNodes", () => {
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
});
