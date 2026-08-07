// @vitest-environment jsdom
// Defines targeted correction behavior for server-verified final Markdown.
// One changed block may be replaced without touching unrelated committed blocks.
// Broad non-local divergence must never request whole-message replacement.
// Spec: docs/specs/streaming-message-render-convergence/spec.yml

import { describe, expect, it, vi } from "vitest";
import { Editor, Node } from "@tiptap/core";
import StarterKit from "@tiptap/starter-kit";

vi.mock("../../data/modelsMetadata", () => ({ modelsMetadata: [] }));
vi.mock("../../data/matesMetadata", () => ({ matesMetadata: [] }));
vi.mock("../../data/providersMetadata", () => ({ providersMetadata: {} }));
vi.mock("../../stores/appSettingsMemoriesStore", () => ({
  appSettingsMemoriesStore: { subscribe: () => () => undefined },
}));
vi.mock("../../stores/appSkillsStore", () => ({
  appSkillsStore: { apps: {}, subscribe: () => () => undefined },
}));

import { createAssistantRenderPlan } from "../streamingMessageBlocks";
import { applyIncrementalUpdate } from "../streamingDocDiff";

const BlockAtom = Node.create({
  name: "blockAtom",
  group: "block",
  atom: true,
  parseHTML: () => [{ tag: "div[data-block-atom]" }],
  renderHTML: () => ["div", { "data-block-atom": "" }],
});

describe("assistant block corrections", () => {
  it("commits only the previous mutable tail on normal completion", () => {
    const streaming = createAssistantRenderPlan("One.\n\nTwo.", { phase: "streaming" });
    const completed = createAssistantRenderPlan("One.\n\nTwo.", {
      phase: "final",
      previous: streaming,
    });

    expect(completed.operations).toEqual([
      expect.objectContaining({ kind: "commit-tail" }),
    ]);
  });

  it("replaces only one locally corrected committed block", () => {
    const previous = createAssistantRenderPlan("One.\n\nBad quote.\n\nThree.", { phase: "final" });
    const corrected = createAssistantRenderPlan("One.\n\nVerified quote.\n\nThree.", {
      phase: "final",
      previous,
    });

    expect(corrected.operations).toEqual([
      expect.objectContaining({ kind: "replace-block", index: 1 }),
    ]);
    expect(corrected.committed[0].id).toBe(previous.committed[0].id);
    expect(corrected.committed[2].id).toBe(previous.committed[2].id);
  });

  it("targets each changed block without a full replacement operation", () => {
    const previous = createAssistantRenderPlan("One.\n\nTwo.\n\nThree.", { phase: "final" });
    const divergent = createAssistantRenderPlan("Changed one.\n\nTwo.\n\nChanged three.", {
      phase: "final",
      previous,
    });

    expect(divergent.operations).toEqual([
      expect.objectContaining({ kind: "replace-block", index: 0 }),
      expect.objectContaining({ kind: "replace-block", index: 2 }),
    ]);
    expect(divergent.operations.map((operation) => operation.kind) as string[]).not.toContain(
      "replace-document",
    );
  });

  it("retries a rejected inline-to-block diff as one targeted block replacement", () => {
    const editor = new Editor({
      element: document.createElement("div"),
      extensions: [StarterKit, BlockAtom],
      content: {
        type: "doc",
        content: [
          { type: "paragraph", content: [{ type: "text", text: "Stable leading paragraph with enough content." }] },
          { type: "paragraph", content: [{ type: "text", text: "provisional" }] },
        ],
      },
    });

    const result = applyIncrementalUpdate(editor, {
      type: "doc",
      content: [
        { type: "paragraph", content: [{ type: "text", text: "Stable leading paragraph with enough content." }] },
        { type: "blockAtom" },
      ],
    });

    expect(result).toEqual({ applied: true, fallback: true, stepsApplied: 1 });
    expect(editor.getJSON().content).toEqual([
      { type: "paragraph", content: [{ type: "text", text: "Stable leading paragraph with enough content." }] },
      { type: "blockAtom" },
    ]);
    editor.destroy();
  });
});
