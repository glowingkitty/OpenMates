// frontend/packages/ui/src/message_parsing/__tests__/parse_message_large_promotion.test.ts
//
// Purpose: verify assistant read-mode promotion rules for large embed previews.
// Ensures non app-skill embeds are promoted to `embedPreviewLarge`, while code
// groups remain in horizontal regular-size grouped rendering.
//
// Architecture: docs/architecture/embeds.md
// Related parser: frontend/packages/ui/src/message_parsing/parse_message.ts

import { describe, expect, it } from "vitest";
import { parse_message } from "../parse_message";

function parseAssistant(markdown: string): any {
  return parse_message(markdown, "read", {
    unifiedParsingEnabled: true,
    role: "assistant",
  });
}

describe("parse_message assistant large promotion", () => {
  it("promotes a single sheet embed to embedPreviewLarge", () => {
    const doc = parseAssistant(
      '```json\n{"type":"sheet","embed_id":"sheet-1"}\n```',
    );

    expect(doc.content?.[0]?.type).toBe("embedPreviewLarge");
    expect(doc.content?.[0]?.attrs?.embedRef).toBe("sheet-1");
    expect(doc.content?.[0]?.attrs?.carouselTotal).toBe(1);
  });

  it("expands multiple non-code embeds into large slideshow nodes", () => {
    const markdown = [
      "```json",
      '{"type":"sheet","embed_id":"sheet-1"}',
      "```",
      "",
      "```json",
      '{"type":"sheet","embed_id":"sheet-2"}',
      "```",
    ].join("\n");

    const doc = parseAssistant(markdown);
    const largeNodes = (doc.content || []).filter(
      (node: any) => node.type === "embedPreviewLarge",
    );

    expect(largeNodes).toHaveLength(2);
    expect(largeNodes[0].attrs.embedRef).toBe("sheet-1");
    expect(largeNodes[1].attrs.embedRef).toBe("sheet-2");
    expect(largeNodes[0].attrs.carouselTotal).toBe(2);
    expect(largeNodes[1].attrs.carouselTotal).toBe(2);
  });

  it("groups [!](embed:ref) links separated by blank line into carousel", () => {
    // When the LLM writes two [!](embed:ref) on separate lines with a blank
    // line between them, the preprocessor inserts an <!-- EMPTY_PARAGRAPH -->
    // which becomes an empty paragraph.  Phase B must skip these so the
    // large-preview nodes form a single carousel run.
    const markdown = [
      "[!](embed:ref-alpha)",
      "",
      "[!](embed:ref-beta)",
      "",
      "[!](embed:ref-gamma)",
    ].join("\n");

    const doc = parseAssistant(markdown);
    const largeNodes = (doc.content || []).filter(
      (node: any) => node.type === "embedPreviewLarge",
    );

    expect(largeNodes).toHaveLength(3);
    expect(largeNodes[0].attrs.carouselTotal).toBe(3);
    expect(largeNodes[1].attrs.carouselTotal).toBe(3);
    expect(largeNodes[2].attrs.carouselTotal).toBe(3);
    expect(largeNodes[0].attrs.carouselIndex).toBe(0);
    expect(largeNodes[1].attrs.carouselIndex).toBe(1);
    expect(largeNodes[2].attrs.carouselIndex).toBe(2);
    expect(largeNodes[1].attrs.runRef).toBe("ref-alpha");
  });

  it("groups [!](embed:ref) links on consecutive lines (no blank) into carousel", () => {
    // Single newlines — markdown-it keeps them in one paragraph with breaks.
    // Phase A must filter out hardBreak/softBreak nodes to hoist properly.
    const markdown = [
      "[!](embed:ref-one)",
      "[!](embed:ref-two)",
    ].join("\n");

    const doc = parseAssistant(markdown);
    const largeNodes = (doc.content || []).filter(
      (node: any) => node.type === "embedPreviewLarge",
    );

    expect(largeNodes).toHaveLength(2);
    expect(largeNodes[0].attrs.carouselTotal).toBe(2);
    expect(largeNodes[1].attrs.carouselTotal).toBe(2);
  });

  it("hoists trailing [!](embed:ref) from list items with text and groups into carousel", () => {
    // Real-world pattern: LLM writes a bullet list where each item has text
    // followed by one or more [!](embed:ref) links on separate lines.
    // The embeds must be split out of the paragraph and grouped.
    const markdown = [
      "*   **Acquisition:** OpenAI has acquired TBPN.",
      "    [!](embed:cnbc.com-qDe)",
      "    [!](embed:nytimes.com-BVV)",
      "*   **Sora Shutdown:** OpenAI shut down Sora.",
    ].join("\n");

    const doc = parseAssistant(markdown);

    function findLarge(nodes: any[]): any[] {
      const out: any[] = [];
      for (const node of nodes || []) {
        if (node?.type === "embedPreviewLarge") out.push(node);
        if (Array.isArray(node?.content)) out.push(...findLarge(node.content));
      }
      return out;
    }

    const largeNodes = findLarge(doc.content || []);
    expect(largeNodes).toHaveLength(2);
    expect(largeNodes[0].attrs.embedRef).toBe("cnbc.com-qDe");
    expect(largeNodes[1].attrs.embedRef).toBe("nytimes.com-BVV");
    expect(largeNodes[0].attrs.carouselTotal).toBe(2);
    expect(largeNodes[1].attrs.carouselTotal).toBe(2);
  });

  it("keeps multi code blocks as horizontal grouped embeds", () => {
    const markdown = [
      "```ts",
      "const a = 1;",
      "```",
      "",
      "```js",
      "const b = 2;",
      "```",
    ].join("\n");

    const doc = parseAssistant(markdown);
    const firstNode = doc.content?.[0];

    expect(firstNode?.type).toBe("paragraph");
    expect(firstNode?.content?.[0]?.type).toBe("embed");
    expect(firstNode?.content?.[0]?.attrs?.type).toBe("code-code-group");
    expect(
      (doc.content || []).some(
        (node: any) => node.type === "embedPreviewLarge",
      ),
    ).toBe(false);
  });

  it("does not promote app-skill-use embeds", () => {
    const doc = parseAssistant(
      '```json\n{"type":"app_skill_use","embed_id":"skill-1","app_id":"web","skill_id":"search"}\n```',
    );

    const firstNode = doc.content?.[0];
    expect(firstNode?.type).toBe("paragraph");
    expect(firstNode?.content?.[0]?.type).toBe("embed");
    expect(firstNode?.content?.[0]?.attrs?.type).toBe("app-skill-use");
  });

  it("promotes a sheet embed surrounded by markdown headings", () => {
    const markdown = [
      "### Comparison Table",
      "",
      "```json",
      '{"type": "sheet", "embed_id": "b7654dc1-07e7-4703-bb58-a135e36bf3ec"}',
      "```",
      "",
      "Which should you choose?",
    ].join("\n");

    const doc = parseAssistant(markdown);
    const largeNodes = (doc.content || []).filter(
      (node: any) => node.type === "embedPreviewLarge",
    );
    expect(largeNodes).toHaveLength(1);
    expect(largeNodes[0].attrs.embedRef).toBe(
      "b7654dc1-07e7-4703-bb58-a135e36bf3ec",
    );
  });

  it("promotes a code embed inside numbered list context", () => {
    const markdown = [
      "3. **The AI Tool Definition (Claude):**",
      "   Give Claude a tool called `query_app_logs`.",
      "   ```json",
      '{"type": "code", "embed_id": "d1acb994-29fd-48d8-9920-c6a8e990d6d3"}',
      "   ```",
    ].join("\n");

    const doc = parseAssistant(markdown);

    function findLarge(nodes: any[]): any[] {
      const out: any[] = [];
      for (const node of nodes || []) {
        if (node?.type === "embedPreviewLarge") out.push(node);
        if (Array.isArray(node?.content)) out.push(...findLarge(node.content));
      }
      return out;
    }

    const largeNodes = findLarge(doc.content || []);
    expect(largeNodes).toHaveLength(1);
    expect(largeNodes[0].attrs.embedRef).toBe(
      "d1acb994-29fd-48d8-9920-c6a8e990d6d3",
    );
  });

  it("keeps legal markdown SVG images as inline image embeds", () => {
    const markdown = [
      "![Contact information 1](/images/legal/1.svg)",
      "",
      "![Contact information 2](/images/legal/2.svg)",
      "",
      "![Contact information 3](/images/legal/3.svg)",
      "",
      "![Contact information 4](/images/legal/4.svg)",
    ].join("\n");

    const doc = parseAssistant(markdown);

    const largeNodes = (doc.content || []).filter(
      (node: any) => node.type === "embedPreviewLarge",
    );
    expect(largeNodes).toHaveLength(0);

    const imageUrls = (doc.content || [])
      .map((node: any) => node?.content?.[0])
      .filter(
        (node: any) => node?.type === "embed" && node?.attrs?.type === "image",
      )
      .map((node: any) => node.attrs.url);

    expect(imageUrls).toEqual([
      "/images/legal/1.svg",
      "/images/legal/2.svg",
      "/images/legal/3.svg",
      "/images/legal/4.svg",
    ]);
  });
});
