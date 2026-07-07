// __tests__/markdownParser.preprocess.test.ts
//
// Purpose: regression tests for OPE-380 — indented or blank-line-split JSON
// code fences caused the fence-depth toggle to desync, injecting
// <!-- EMPTY_PARAGRAPH --> inside the fence where markdown-it rendered it
// as literal text in the chat UI.
// Architecture: pins preprocessMarkdown's fence tracking against the two
// AI-response patterns that broke it. Change detection — if someone swaps
// the regex back to ^``` this test fires.

import { describe, it, expect, vi } from "vitest";

// markdownParser.ts pulls in Svelte store modules and metadata tables at
// module load. In the GH-Actions node environment these imports can hang
// or fail silently, which causes the whole test file to be skipped. Stub
// them so the import graph stays minimal and preprocessMarkdown can be
// exercised in isolation.
vi.mock("../../../../data/modelsMetadata", () => ({ modelsMetadata: [] }));
vi.mock("../../../../data/matesMetadata", () => ({ matesMetadata: {} }));
vi.mock("../../../../data/providersMetadata", () => ({ providersMetadata: {} }));
vi.mock("../../../../stores/appSettingsMemoriesStore", () => ({
  appSettingsMemoriesStore: { subscribe: () => () => {} },
}));
vi.mock("../../../../stores/appSkillsStore", () => ({
  appSkillsStore: {
    subscribe: () => () => {},
    getState: () => ({
      apps: {
        openmates: {
          id: "openmates",
          skills: [{ id: "share-usecase" }],
          focus_modes: [],
          settings_and_memories: [],
        },
        maps: {
          id: "maps",
          skills: [],
          focus_modes: [],
          settings_and_memories: [
            {
              id: "favorite_places",
              schema_definition: {
                properties: {
                  name: { type: "string" },
                },
              },
            },
          ],
        },
      },
    }),
  },
}));

import { parseMarkdownToTiptap, preprocessMarkdown } from "../markdownParser";

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

  it("rewrites hallucinated settings links to message-prefill links", () => {
    const doc = parseMarkdownToTiptap(
      "Open [billing settings](/#settings/apps/openmates/settings_memories/billing).",
    );

    const paragraph = doc.content[0];
    const billingText = paragraph.content.find(
      (node: { text?: string }) => node.text === "billing settings",
    );

    expect(billingText?.marks?.[0]?.attrs?.href).toBe("#message=billing%20settings");
  });

  it("normalizes valid raw settings memory links before markdown parsing", () => {
    const doc = parseMarkdownToTiptap(
      '[Save Kottbusser Tor](/#settings/apps/maps/settings_memories/favorite_places/create?prefill={"name":"Kottbusser Tor"})',
    );

    const linkText = doc.content[0].content.find(
      (node: { text?: string }) => node.text === "Save Kottbusser Tor",
    );

    expect(linkText?.marks?.[0]?.attrs?.href).toBe(
      "#settings/apps/maps/memories/favorite_places/create?prefill=%7B%22name%22%3A%22Kottbusser%20Tor%22%7D",
    );
  });

  it("falls back when raw settings memory links include unsupported prefill fields", () => {
    const doc = parseMarkdownToTiptap(
      '[Kottbusser Tor als Lieblingsort speichern](/#settings/apps/maps/settings_memories/favorite_places/create?prefill={“name”:“Kottbusser Tor”,“city”:“Berlin”})',
    );

    const linkText = doc.content[0].content.find(
      (node: { text?: string }) => node.text === "Kottbusser Tor als Lieblingsort speichern",
    );

    expect(linkText?.marks?.[0]?.attrs?.href).toBe(
      "#message=Kottbusser%20Tor%20als%20Lieblingsort%20speichern",
    );
  });

  it("turns invalid raw settings memory links into message-prefill links", () => {
    const doc = parseMarkdownToTiptap(
      '[Fitnessziel setzen](/#settings/apps/fitness/settings_memories/goals/create?prefill={“name”:“Neue USC-Standorte erkunden”})',
    );

    const linkText = doc.content[0].content.find(
      (node: { text?: string }) => node.text === "Fitnessziel setzen",
    );

    expect(linkText?.marks?.[0]?.attrs?.href).toBe(
      "#message=Fitnessziel%20setzen",
    );
  });

  it("separates adjacent invalid settings fallback links into separate paragraphs", () => {
    const doc = parseMarkdownToTiptap(
      '[Fitnessziel setzen](/#settings/apps/fitness/settings_memories/goals/create?prefill={“name”:“Neue USC-Standorte erkunden”})' +
        '[Kottbusser Tor als Lieblingsort speichern](/#settings/apps/maps/settings_memories/favorite_places/create?prefill={“name”:“Kottbusser Tor”,“city”:“Berlin”})',
    );

    const paragraphs = doc.content.filter((node: { type?: string }) => node.type === "paragraph");

    expect(paragraphs[0].content[0].text).toBe("Fitnessziel setzen");
    expect(paragraphs[0].content[0].marks?.[0]?.attrs?.href).toBe(
      "#message=Fitnessziel%20setzen",
    );
    expect(paragraphs[1].content[0].text).toBe("Kottbusser Tor als Lieblingsort speichern");
    expect(paragraphs[1].content[0].marks?.[0]?.attrs?.href).toBe(
      "#message=Kottbusser%20Tor%20als%20Lieblingsort%20speichern",
    );
  });
});
