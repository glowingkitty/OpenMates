// frontend/packages/ui/src/message_parsing/__tests__/parse_message_grouped_bare_embed_refs.test.ts
//
// Regression tests for persisted bare embed references such as
// `[openai.com-msb, openai.com-Uoj]` or `[-Ur6]` on shared/read-only chat pages.
//
// Related parser: frontend/packages/ui/src/message_parsing/parse_message.ts
// Contract: feature.app-skill.web-search surface parity.

import { afterEach, describe, expect, it } from "vitest";
import { parse_message } from "../parse_message";
import { embedStore } from "../../services/embedStore";
import { registerEmbedRefIndex } from "../../services/embedRefIndex";

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
    registerEmbedRefIndex("openai.com-msb", {
      embedId: "embed-1",
      appId: "web-search",
      skillId: "search",
      type: "website",
    });
    registerEmbedRefIndex("openai.com-Uoj", {
      embedId: "embed-2",
      appId: "web-search",
      skillId: "search",
      type: "website",
    });

    const doc = parseAssistant(
      "Sources include [openai.com-msb, openai.com-Uoj] for the release details.",
    );
    const inlineEmbeds = findInlineEmbeds(doc.content || []);

    expect(inlineEmbeds).toHaveLength(2);
    expect(inlineEmbeds[0].attrs).toMatchObject({
      embedRef: "openai.com-msb",
      displayText: "Source: openai.com",
    });
    expect(inlineEmbeds[1].attrs).toMatchObject({
      embedRef: "openai.com-Uoj",
      displayText: "Source: openai.com",
    });
    expect(JSON.stringify(doc)).not.toContain("[openai.com-msb, openai.com-Uoj]");
  });

  // contract-test: supporting surface=gui.web assertions=web-search.surface-parity
  it("repairs grouped bare embed refs before the encrypted ref index is warm", () => {
    const doc = parseAssistant(
      "Sources include [openai.com-msb, openai.com-Uoj] for the release details.",
    );
    const inlineEmbeds = findInlineEmbeds(doc.content || []);

    expect(inlineEmbeds).toHaveLength(2);
    expect(inlineEmbeds[0].attrs).toMatchObject({
      embedRef: "openai.com-msb",
      embedId: null,
      displayText: "Source: openai.com",
    });
    expect(inlineEmbeds[1].attrs).toMatchObject({
      embedRef: "openai.com-Uoj",
      embedId: null,
      displayText: "Source: openai.com",
    });
    expect(JSON.stringify(doc)).not.toContain("[openai.com-msb, openai.com-Uoj]");
  });

  // contract-test: supporting surface=gui.web assertions=web-search.surface-parity
  it("repairs an unbracketed source domain ref before the encrypted ref index is warm", () => {
    const doc = parseAssistant("Source: techcrunch.com-70I explains the news.");
    const inlineEmbeds = findInlineEmbeds(doc.content || []);

    expect(inlineEmbeds).toHaveLength(1);
    expect(inlineEmbeds[0].attrs).toMatchObject({
      embedRef: "techcrunch.com-70I",
      embedId: null,
      displayText: "Source: techcrunch.com",
    });
    expect(JSON.stringify(doc)).not.toContain("techcrunch.com-70I explains");
  });

  // contract-test: supporting surface=gui.web assertions=web-search.surface-parity
  it("repairs inline domain refs in existing shared-chat prose", () => {
    const doc = parseAssistant(
      "OpenAI expects to become a public company by 2027 or sooner cnbc.com-37P. " +
        "The enterprise market share gap narrowed in Q3 techcrunch.com-70I.",
    );
    const inlineEmbeds = findInlineEmbeds(doc.content || []);
    const serialized = JSON.stringify(doc);

    expect(inlineEmbeds).toHaveLength(2);
    expect(inlineEmbeds[0].attrs).toMatchObject({
      embedRef: "cnbc.com-37P",
      embedId: null,
      displayText: "Source: cnbc.com",
    });
    expect(inlineEmbeds[1].attrs).toMatchObject({
      embedRef: "techcrunch.com-70I",
      embedId: null,
      displayText: "Source: techcrunch.com",
    });
    expect(serialized).not.toContain("sooner cnbc.com-37P");
    expect(serialized).not.toContain("Q3 techcrunch.com-70I");
  });

  // contract-test: supporting surface=gui.web assertions=web-search.surface-parity
  it("repairs persisted grouped suffix-only embed refs into canonical inline embed nodes", () => {
    registerEmbedRefIndex("mashable.com-7fJ", {
      embedId: "embed-1",
      appId: "web-search",
      skillId: "search",
      type: "website",
    });
    registerEmbedRefIndex("macrumors.com-TW4", {
      embedId: "embed-2",
      appId: "web-search",
      skillId: "search",
      type: "website",
    });

    const doc = parseAssistant("Sources include [-7fj, ‑tw4, -NOPE] for context.");
    const inlineEmbeds = findInlineEmbeds(doc.content || []);
    const serialized = JSON.stringify(doc);

    expect(inlineEmbeds).toHaveLength(2);
    expect(inlineEmbeds[0].attrs).toMatchObject({
      embedRef: "mashable.com-7fJ",
      embedId: "embed-1",
      displayText: "Source: mashable.com",
    });
    expect(inlineEmbeds[1].attrs).toMatchObject({
      embedRef: "macrumors.com-TW4",
      embedId: "embed-2",
      displayText: "Source: macrumors.com",
    });
    expect(serialized).not.toContain("-7fj");
    expect(serialized).not.toContain("‑tw4");
    expect(serialized).not.toContain("-NOPE");
  });

  // contract-test: supporting surface=gui.web assertions=web-search.surface-parity
  it("repairs persisted single suffix-only embed refs into canonical inline embed nodes", () => {
    registerEmbedRefIndex("macrumors.com-Ur6", {
      embedId: "embed-1",
      appId: "web-search",
      skillId: "search",
      type: "website",
    });

    const doc = parseAssistant("Another source is [-Ur6] for context.");
    const inlineEmbeds = findInlineEmbeds(doc.content || []);
    const serialized = JSON.stringify(doc);

    expect(inlineEmbeds).toHaveLength(1);
    expect(inlineEmbeds[0].attrs).toMatchObject({
      embedRef: "macrumors.com-Ur6",
      embedId: "embed-1",
      displayText: "Source: macrumors.com",
    });
    expect(serialized).not.toContain("[-Ur6]");
  });

  // contract-test: supporting surface=gui.web assertions=events-search.surface-parity
  it("repairs bracketed embed-prefixed refs without leaking protocol text", () => {
    registerEmbedRefIndex("else-x-home-dsBI", {
      embedId: "embed-1",
      appId: "events",
      skillId: "search",
      type: "app-skill-use",
    });

    const doc = parseAssistant("Event Options Comparison [embed:else-x-home-dsBI]");
    const inlineEmbeds = findInlineEmbeds(doc.content || []);
    const serialized = JSON.stringify(doc);

    expect(inlineEmbeds).toHaveLength(1);
    expect(inlineEmbeds[0].attrs).toMatchObject({
      embedRef: "else-x-home-dsBI",
      embedId: "embed-1",
      appId: "events",
    });
    expect(serialized).not.toContain("[embed:else-x-home-dsBI]");
  });
});
