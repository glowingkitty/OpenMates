// @vitest-environment jsdom
// Defines committed-block and mutable-tail behavior for streamed assistant Markdown.
// Safe completed blocks use final read semantics before the message completes.
// Later snapshots may update only the tail or append newly committed blocks.
// Spec: docs/specs/streaming-message-render-convergence/spec.yml

import { describe, expect, it, vi } from "vitest";

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

function findNodes(node: any, type: string): any[] {
  const matches = node?.type === type ? [node] : [];
  for (const child of node?.content || []) matches.push(...findNodes(child, type));
  return matches;
}

describe("createAssistantRenderPlan", () => {
  // contract-test: direct surface=gui.web assertions=chats.rendering.assistant-document-convergence,chats.rendering.inline-entity-interaction
  it("commits safe complete blocks with final embed semantics and keeps one mutable tail", () => {
    const markdown = [
      "Use [the event](embed:event-ref).",
      "",
      "[!](embed:preview-ref)",
      "",
      "Still writing the final paragraph",
    ].join("\n");

    const plan = createAssistantRenderPlan(markdown, { phase: "streaming" });

    expect(plan.committed).toHaveLength(2);
    expect(plan.tail?.markdown).toBe("Still writing the final paragraph");
    expect(findNodes(plan.committed[0].document, "embedInline")).toHaveLength(1);
    expect(findNodes(plan.committed[1].document, "embedPreviewLarge")).toHaveLength(1);
  });

  // contract-test: direct surface=gui.web assertions=chats.rendering.assistant-document-convergence
  it("does not target committed blocks when only the mutable tail grows", () => {
    const first = createAssistantRenderPlan("First paragraph.\n\nStill", { phase: "streaming" });
    const later = createAssistantRenderPlan("First paragraph.\n\nStill writing", {
      phase: "streaming",
      previous: first,
    });

    expect(later.committed.map((block) => block.id)).toEqual(
      first.committed.map((block) => block.id),
    );
    expect(later.operations).toEqual([
      expect.objectContaining({ kind: "replace-tail" }),
    ]);
  });

  // contract-test: direct surface=gui.web assertions=chats.rendering.assistant-document-convergence
  it.each([
    "An [unfinished link](embed:",
    "```json\n{\"type\":\"app_skill_use\"",
    "- first item\n- second item",
    "| A | B |\n|---|---|\n| 1 |",
    "> an unfinished source quote",
    "An [unfinished\n\nlink](embed:",
    "- first item\n\n  continued item text",
  ])("keeps unsafe suffix provisional: %s", (tail) => {
    const plan = createAssistantRenderPlan(tail, { phase: "streaming" });

    expect(plan.committed).toHaveLength(0);
    expect(plan.tail?.markdown).toBe(tail);
  });

  // contract-test: direct surface=gui.web assertions=chats.rendering.assistant-document-convergence
  it("retains heading-adjacent result views across cumulative snapshots", () => {
    const chunks = [
      "Here are the results.\n\n",
      "### Weekend 1\n```embeds_results_view\ntitle: First weekend\nembeds: event-one, event-two\n```\n\n",
      "### Weekend 2\n```embeds_results_view\ntitle: Second weekend\nembeds: event-three\n```\n\n",
      "More details follow.",
    ];
    let markdown = "";
    let plan: ReturnType<typeof createAssistantRenderPlan> | undefined;
    for (const chunk of chunks) {
      markdown += chunk;
      plan = createAssistantRenderPlan(markdown, {
        phase: "streaming",
        previous: plan,
      });
    }

    const resultViews = findNodes(plan?.document, "embed").filter(
      (node) => node.attrs?.type === "embeds-map-view",
    );
    expect(resultViews).toHaveLength(2);
    expect(plan?.operations).not.toContainEqual(
      expect.objectContaining({ kind: "convergence-failure" }),
    );
  });
});
