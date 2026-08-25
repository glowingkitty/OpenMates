// @vitest-environment jsdom
// Protects the permanent app-skill execution group at the top of assistant messages.
// Executions are newest-first regardless of when prose is produced.
// Authored result references remain at their original Markdown positions.
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

const execution = (id: string, app: string) => [
  "```json",
  JSON.stringify({ type: "app_skill_use", embed_id: id, app_id: app, skill_id: "search" }),
  "```",
].join("\n");

describe("assistant app-skill top group", () => {
  // contract-test: direct surface=gui.web assertions=chats.rendering.assistant-document-convergence,chats.rendering.inline-entity-interaction
  it("extracts scattered executions to the top in newest-first order", () => {
    const markdown = [
      execution("skill-old", "web"),
      "",
      "First answer paragraph.",
      "",
      "[!](embed:authored-preview)",
      "",
      execution("skill-middle", "events"),
      "",
      "Compare with [this result](embed:authored-inline).",
      "",
      execution("skill-new", "images"),
    ].join("\n");

    const plan = createAssistantRenderPlan(markdown, { phase: "final" });

    expect(plan.appSkillGroup?.executions.map((item) => item.embedId)).toEqual([
      "skill-new",
      "skill-middle",
      "skill-old",
    ]);
    expect(findNodes(plan.document, "embed")[0]?.attrs?.type).toBe("app-skill-use-group");
    expect(JSON.stringify(plan.authoredDocument)).toContain("authored-preview");
    expect(JSON.stringify(plan.authoredDocument)).toContain("authored-inline");
  });

  // contract-test: direct surface=gui.web assertions=chats.rendering.assistant-document-convergence
  it("keeps group and item identity when a newer execution is added", () => {
    const first = createAssistantRenderPlan(execution("skill-old", "web"), { phase: "streaming" });
    const later = createAssistantRenderPlan(
      `${execution("skill-old", "web")}\n\n${execution("skill-new", "events")}`,
      { phase: "streaming", previous: first },
    );

    expect(later.appSkillGroup?.id).toBe(first.appSkillGroup?.id);
    expect(later.appSkillGroup?.executions.map((item) => item.embedId)).toEqual([
      "skill-new",
      "skill-old",
    ]);
    expect(later.operations).toContainEqual(
      expect.objectContaining({ kind: "update-app-skill-group" }),
    );
  });

  // contract-test: direct surface=gui.web assertions=chats.rendering.assistant-document-convergence
  it("keeps the streamed execution group when canonical content completes", () => {
    const markdown = [
      execution("skill-old", "events"),
      "",
      execution("skill-new", "events"),
      "",
      "Here are both weekends.",
    ].join("\n");
    const streaming = createAssistantRenderPlan(markdown, { phase: "streaming" });
    const completed = createAssistantRenderPlan(markdown, {
      phase: "final",
      previous: streaming,
    });

    expect(completed.appSkillGroup).toBe(streaming.appSkillGroup);
    expect(completed.appSkillGroup?.executions.map((item) => item.embedId)).toEqual([
      "skill-new",
      "skill-old",
    ]);
    expect(JSON.stringify(completed.document)).not.toContain("embedPreviewLarge");
  });
});
