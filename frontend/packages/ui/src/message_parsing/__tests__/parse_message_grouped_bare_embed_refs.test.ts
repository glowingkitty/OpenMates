// frontend/packages/ui/src/message_parsing/__tests__/parse_message_grouped_bare_embed_refs.test.ts
//
// Regression tests for persisted grouped bare embed references such as
// `[openai.com-msb, openai.com-Uoj]` on shared/read-only chat pages.
//
// Related parser: frontend/packages/ui/src/message_parsing/parse_message.ts
// Contract: feature.app-skill.web-search surface parity.

import { afterEach, describe, expect, it } from "vitest";
import { parse_message } from "../parse_message";
import { embedStore } from "../../services/embedStore";

function parseAssistant(markdown: string): any {
  return parse_message(markdown, "read", {
    unifiedParsingEnabled: true,
    role: "assistant",
  });
}

function findInlineEmbeds(nodes: any[]): any[] {
  const out: any[] = [];
  for (const node of nodes || []) {
    if (node?.type === "embedInline") out.push(node);
    if (Array.isArray(node?.content)) out.push(...findInlineEmbeds(node.content));
  }
  return out;
}

describe("parse_message grouped bare embed refs", () => {
  afterEach(() => {
    embedStore.clearEmbedRefIndex();
  });

  // contract-test: direct surface=gui.web assertions=web-search.surface-parity
  it("repairs persisted grouped bare embed refs into inline embed nodes", () => {
    const doc = parseAssistant(
      "Sources include [openai.com-msb, openai.com-Uoj] for the release details.",
    );
    const inlineEmbeds = findInlineEmbeds(doc.content || []);

    expect(inlineEmbeds).toHaveLength(2);
    expect(inlineEmbeds[0].attrs).toMatchObject({
      embedRef: "openai.com-msb",
      displayText: "openai.com",
    });
    expect(inlineEmbeds[1].attrs).toMatchObject({
      embedRef: "openai.com-Uoj",
      displayText: "openai.com",
    });
    expect(JSON.stringify(doc)).not.toContain("[openai.com-msb, openai.com-Uoj]");
  });
});
