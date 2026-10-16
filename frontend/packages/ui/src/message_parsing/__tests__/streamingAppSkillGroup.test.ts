// @vitest-environment jsdom
// Assistant skill calls render at canonical source placeholders.
// Only adjacent calls share a group; completion order cannot move a card.
// Live, final, and reopened documents keep the same order and identities.
// Spec: specifications/features/chats/specification.yml

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

import { createAssistantRenderPlan, normalizeAssistantRenderPlan } from "../streamingMessageBlocks";
import { splitAssistantActivityRuns } from "../assistantActivityRuns";
import { classifyAssistantSkillPhase } from "../assistantActivityStatus";

function findNodes(node: any, type: string): any[] {
  const matches = node?.type === type ? [node] : [];
  for (const child of node?.content || []) matches.push(...findNodes(child, type));
  return matches;
}

const execution = (id: string, app: string, status = "processing", skill = "search") => [
  "```json",
  JSON.stringify({ type: "app_skill_use", embed_id: id, app_id: app, skill_id: skill, status }),
  "```",
].join("\n");

const contentOrder = (plan: ReturnType<typeof createAssistantRenderPlan>) =>
  plan.document.content.flatMap((node: any) => {
    const embeds = findNodes(node, "embed");
    if (embeds.length) return embeds.flatMap((embed) =>
      embed.attrs?.type === "app-skill-use-group"
        ? embed.attrs.groupedItems.map((item: any) => item.id)
        : [embed.attrs?.id]);
    return findNodes(node, "text").map((text) => text.text);
  });

describe("assistant app-skill source runs", () => {
  // contract-test: direct surface=gui.web assertions=chat-processing-feedback.skill-activity-label,chats.rendering.assistant-document-convergence
  it("classifies source skill IDs deterministically, with action calls taking precedence", () => {
    const plan = createAssistantRenderPlan([
      execution("search-one", "web"), "", execution("create-one", "images", "processing", "generate"),
    ].join("\n"), { phase: "streaming" });
    const skills = splitAssistantActivityRuns(plan.document)?.find((run) => run.kind === "skills");
    expect(skills?.skillIds).toEqual(["search", "generate"]);
    expect(classifyAssistantSkillPhase(skills?.skillIds ?? [])).toBe("working");
    expect(classifyAssistantSkillPhase(["search", "get_docs", "list-reminders"])).toBe("researching");
    expect(classifyAssistantSkillPhase(["unknown_future_skill"])).toBe("researching");
    expect(classifyAssistantSkillPhase(["send-message", "search"])).toBe("working");
    expect(classifyAssistantSkillPhase(["schedule-once"])).toBe("working");
    expect(classifyAssistantSkillPhase(["schedule-recurring"])).toBe("working");
    expect(classifyAssistantSkillPhase(["keep-temporary"])).toBe("working");
  });
  // contract-test: direct surface=gui.web assertions=chats.rendering.assistant-document-convergence,chats.rendering.inline-entity-interaction
  it("keeps separated calls around prose and authored result references", () => {
    const markdown = [
      execution("skill-old", "web"), "", "First answer paragraph.", "",
      "[!](embed:authored-preview)", "", execution("skill-middle", "events"), "",
      "Compare with [this result](embed:authored-inline).", "", execution("skill-new", "images"),
    ].join("\n");
    const plan = createAssistantRenderPlan(markdown, { phase: "final" });
    const order = contentOrder(plan);
    expect(order.indexOf("skill-old")).toBeLessThan(order.indexOf("First answer paragraph."));
    expect(order.indexOf("skill-middle")).toBeGreaterThan(order.indexOf("First answer paragraph."));
    expect(order.indexOf("skill-middle")).toBeLessThan(order.indexOf("skill-new"));
    expect(JSON.stringify(plan.document)).toContain("authored-preview");
    expect(JSON.stringify(plan.document)).toContain("authored-inline");
  });

  // contract-test: direct surface=gui.web assertions=chats.rendering.assistant-document-convergence
  it("groups only adjacent calls with a stable first-item anchor", () => {
    const first = createAssistantRenderPlan(execution("skill-old", "web"), { phase: "streaming" });
    const later = createAssistantRenderPlan(
      `${execution("skill-old", "web")}\n\n${execution("skill-new", "events")}`,
      { phase: "streaming", previous: first },
    );
    const grouped = findNodes(later.document, "embed").find((node) => node.attrs?.type === "app-skill-use-group");
    expect(grouped?.attrs?.groupedItems.map((item: any) => item.id)).toEqual(["skill-old", "skill-new"]);
    expect(grouped?.attrs?.id).toContain("skill-old");
  });

  // contract-test: direct surface=gui.web assertions=chats.rendering.assistant-document-convergence
  it("keeps source order when a parallel call completes and on reload", () => {
    const initial = `${execution("skill-old", "events")}\n\n${execution("skill-new", "web")}\n\nHere are both results.`;
    const completed = `${execution("skill-old", "events", "finished")}\n\n${execution("skill-new", "web")}\n\nHere are both results.`;
    const streaming = createAssistantRenderPlan(initial, { phase: "streaming" });
    const liveFinal = createAssistantRenderPlan(completed, { phase: "final", previous: streaming });
    const reopened = createAssistantRenderPlan(completed, { phase: "final" });
    expect(normalizeAssistantRenderPlan(liveFinal).appSkillIds).toEqual(["skill-old", "skill-new"]);
    expect(normalizeAssistantRenderPlan(liveFinal)).toEqual(normalizeAssistantRenderPlan(reopened));
  });
});
