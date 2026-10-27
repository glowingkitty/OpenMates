// Unit tests for JSON embed-reference parsing.
// Covers persistence-sensitive attributes that survive draft reloads.
// Reference-only embeds point at existing synced uploads and must remain
// non-destructive after markdown serialization and parsing.
// These tests intentionally exercise public parser behavior only.

import { describe, expect, it, vi } from "vitest";
// Serialization does not use the inverse parser or its editor/service dependencies.
vi.mock('../../components/enter_message/utils/markdownParser', () => ({ parseMarkdownToTiptap: vi.fn() }));
import { parseEmbedNodes } from "../embedParsing";
import { enhanceDocumentWithEmbeds } from "../documentEnhancement";
import { tipTapToCanonicalMarkdown } from "../serializers";

describe("parseEmbedNodes", () => {
  // contract-test: supporting surface=gui.web assertions=chats.rendering.assistant-document-convergence
  it.each(['write', 'read'] as const)('converts SVG-only fences to images in %s mode without losing source', (mode) => {
    const source = '<svg viewBox="0 0 20 10"><rect width="20" height="10"/></svg>';
    for (const language of ['svg', 'xml', 'html', '']) {
      const markdown = `\`\`\`${language}\n${source}\n\`\`\``;
      const embeds = parseEmbedNodes(markdown, mode);
      expect(embeds).toHaveLength(1);
      expect(embeds[0]).toMatchObject({ type: 'image', code: source, filename: 'image.svg' });
      const doc = enhanceDocumentWithEmbeds({ type: 'doc', content: [{
        type: 'codeBlock', attrs: { language }, content: [{ type: 'text', text: source }],
      }] }, embeds, mode);
      expect(doc.content?.[0].content?.[0].attrs).toMatchObject({ type: 'image', code: source });
      const restored = parseEmbedNodes(tipTapToCanonicalMarkdown(doc), mode);
      expect(restored[0]).toMatchObject({ type: 'image', code: source });
    }
  });

  // contract-test: supporting surface=gui.web assertions=chats.rendering.assistant-document-convergence
  it('keeps an SVG within an HTML document as a code embed', () => {
    const [embed] = parseEmbedNodes('```html\n<html><body><svg/></body></html>\n```', 'read');
    expect(embed.type).toBe('code-code');
  });

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
