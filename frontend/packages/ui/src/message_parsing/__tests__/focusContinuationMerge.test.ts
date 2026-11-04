// @vitest-environment jsdom
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

const activation = '```json\n{"type":"focus_mode_activation","embed_id":"f1","focus_id":"events-plan_conference_talk","app_id":"events","focus_mode_name":"Plan a conference talk"}\n```';

describe("focus continuation merge", () => {
  // contract-test: infrastructure
  it("converges when a final activation message with a list is merged with a streaming continuation", () => {
    const activationWithList = activation + "\n\n- one\n- two\n\nTail paragraph.";
    const previous = createAssistantRenderPlan(activationWithList, { phase: "final" });
    const merged = activationWithList + "\n\nContinuation text.";
    const plan = createAssistantRenderPlan(merged, { phase: "streaming", previous });
    expect(plan.operations.some((op) => op.kind === "convergence-failure")).toBe(false);
    expect(plan.sourceMarkdown).toBe(merged);
  });
});
