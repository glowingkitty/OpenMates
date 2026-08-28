// frontend/packages/ui/src/message_parsing/__tests__/parse_message_wikipedia_mentions.test.ts
// Verifies canonical Wikipedia mentions preserve edit-mode serialization while
// becoming interactive Wiki links in rendered user messages.
// Language and title metadata must survive the read-only conversion so the
// fullscreen viewer opens the article selected by the user.

import { describe, expect, it } from "vitest";
import { parse_message } from "../parse_message";

function firstInlineNode(document: any): any {
  return document.content[0].content[0];
}

describe("parse_message Wikipedia mentions", () => {
  // contract-test: supporting surface=gui.web assertions=wikipedia-mentions.surfaces.semantic-parity
  it("renders canonical user mentions as language-aware Wiki links", () => {
    const document = parse_message(
      "@wikipedia:de:Albert_Einstein",
      "read",
      { unifiedParsingEnabled: true, role: "user" },
    );

    expect(firstInlineNode(document)).toEqual({
      type: "wikiInline",
      attrs: {
        displayText: "Albert Einstein",
        wikiTitle: "Albert_Einstein",
        language: "de",
        wikidataId: null,
        thumbnailUrl: null,
        description: null,
      },
    });
  });

  // contract-test: supporting surface=gui.web assertions=wikipedia-mentions.syntax.explicit-trigger
  it("keeps canonical mentions editable in write mode", () => {
    const document = parse_message(
      "@wikipedia:de:Albert_Einstein",
      "write",
      { unifiedParsingEnabled: true, role: "user" },
    );

    expect(firstInlineNode(document).type).toBe("genericMention");
  });

  // contract-test: supporting surface=gui.web assertions=wikipedia-mentions.syntax.explicit-trigger
  it("keeps malformed percent encoding readable", () => {
    const document = parse_message(
      "@wikipedia:en:Broken%Title",
      "read",
      { unifiedParsingEnabled: true, role: "user" },
    );

    expect(firstInlineNode(document)).toMatchObject({
      type: "wikiInline",
      attrs: {
        displayText: "Broken%Title",
        wikiTitle: "Broken%Title",
        language: "en",
      },
    });
  });

  // contract-test: supporting surface=gui.web assertions=wikipedia-mentions.surfaces.semantic-parity
  it("keeps malformed assistant Wiki links readable", () => {
    const document = parse_message(
      "[Broken title](wiki:Broken%Title)",
      "read",
      { unifiedParsingEnabled: true, role: "assistant" },
    );

    expect(firstInlineNode(document)).toMatchObject({
      type: "wikiInline",
      attrs: {
        displayText: "Broken title",
        wikiTitle: "Broken%Title",
      },
    });
  });
});
