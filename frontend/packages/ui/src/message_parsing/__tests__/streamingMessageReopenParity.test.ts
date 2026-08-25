// @vitest-environment jsdom
// Ensures live finalization and fresh persisted-Markdown compilation converge.
// Equality covers top-group ordering and authored embed positions and variants.
// Ephemeral DOM, loading, and hydration state are intentionally excluded.
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

import {
  createAssistantRenderPlan,
  normalizeAssistantRenderPlan,
} from "../streamingMessageBlocks";

const skill = (id: string) => `\`\`\`json\n${JSON.stringify({
  type: "app_skill_use",
  embed_id: id,
  app_id: "events",
  skill_id: "search",
})}\n\`\`\``;

describe("assistant live/reopen parity", () => {
  // contract-test: direct surface=gui.web assertions=chats.rendering.assistant-document-convergence,chats.rendering.inline-entity-interaction
  it("reconstructs the same ordered semantic document from persisted Markdown", () => {
    const prefix = `${skill("skill-old")}\n\nMadrid is Spain's capital.\n\n`;
    const finalMarkdown = [
      skill("skill-old"),
      "",
      "Madrid is Spain's capital.",
      "",
      "[!](embed:madrid-preview)",
      "",
      skill("skill-new"),
      "",
      "Read [the source](embed:madrid-source).",
    ].join("\n");

    const streaming = createAssistantRenderPlan(prefix, { phase: "streaming" });
    const liveFinal = createAssistantRenderPlan(finalMarkdown, {
      phase: "final",
      previous: streaming,
    });
    const reopened = createAssistantRenderPlan(finalMarkdown, { phase: "final" });

    expect(normalizeAssistantRenderPlan(liveFinal)).toEqual(
      normalizeAssistantRenderPlan(reopened),
    );
    expect(normalizeAssistantRenderPlan(reopened).appSkillIds).toEqual([
      "skill-new",
      "skill-old",
    ]);
  });
});
