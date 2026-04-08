// __tests__/markdownParser.preprocess.test.ts
//
// Purpose: regression tests for OPE-380 — indented or blank-line-split JSON
// code fences caused the fence-depth toggle to desync, injecting
// <!-- EMPTY_PARAGRAPH --> inside the fence where markdown-it rendered it
// as literal text in the chat UI.
// Architecture: pins preprocessMarkdown's fence tracking against the two
// AI-response patterns that broke it. Change detection — if someone swaps
// the regex back to ^``` this test fires.

import { describe, it, expect } from "vitest";
import { preprocessMarkdown } from "../markdownParser";

describe("preprocessMarkdown — fence tracking (OPE-380)", () => {
  it("does not inject EMPTY_PARAGRAPH inside a JSON fence containing blank lines", () => {
    const input = [
      "Here is an example:",
      "",
      "```json",
      "{",
      '  "foo": 1,',
      "",
      '  "bar": 2',
      "}",
      "```",
      "",
      "That's all.",
    ].join("\n");

    const out = preprocessMarkdown(input);

    // The marker must only appear OUTSIDE the fence (between paragraphs and
    // the fence, and between the fence and the trailing paragraph) — never
    // inside, which would surface as literal text in the rendered message.
    const inFenceRegion = out.match(/```json[\s\S]*?```/);
    expect(inFenceRegion).not.toBeNull();
    expect(inFenceRegion![0]).not.toContain("EMPTY_PARAGRAPH");
  });

  it("tracks indented ```json fences inside list items", () => {
    const input = [
      "- Item one:",
      "",
      "    ```json",
      "    {",
      '      "key": "value"',
      "    }",
      "    ```",
      "",
      "- Item two",
    ].join("\n");

    const out = preprocessMarkdown(input);

    // Closing fence must bring the state back to "outside" — otherwise
    // markdown-it emits the literal '<!-- EMPTY_PARAGRAPH -->' comment as
    // text inside the code block.
    const fenceBody = out.match(/```json[\s\S]*?```/);
    expect(fenceBody).not.toBeNull();
    expect(fenceBody![0]).not.toContain("EMPTY_PARAGRAPH");
  });

  it("still inserts EMPTY_PARAGRAPH between normal paragraphs", () => {
    const input = "First paragraph.\n\nSecond paragraph.";
    const out = preprocessMarkdown(input);
    expect(out).toContain("EMPTY_PARAGRAPH");
  });
});
