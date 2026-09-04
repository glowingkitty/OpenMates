// @vitest-environment jsdom
// frontend/packages/ui/src/message_parsing/__tests__/streamingMessageCompiler.test.ts
// Verifies one canonical assistant display compiler for streaming and final text.
// Complete Markdown prefixes must keep final embed semantics and stable identities.
// Only an incomplete trailing construct may remain provisional during streaming.
// Spec: docs/specs/streaming-message-render-convergence/spec.yml

import { describe, expect, it, vi } from "vitest";

// Keep this parser contract independent from generated metadata and browser stores.
vi.mock("../../data/modelsMetadata", () => ({ modelsMetadata: [] }));
vi.mock("../../data/matesMetadata", () => ({ matesMetadata: [] }));
vi.mock("../../data/providersMetadata", () => ({ providersMetadata: {} }));
vi.mock("../../stores/appSettingsMemoriesStore", () => ({
  appSettingsMemoriesStore: { subscribe: () => () => undefined },
}));
vi.mock("../../stores/appSkillsStore", () => ({
  appSkillsStore: { apps: {}, subscribe: () => () => undefined },
}));

import { compileAssistantDisplayMessage } from "../streamingMessageCompiler";

function findNodes(node: any, type: string): any[] {
  const matches = node?.type === type ? [node] : [];
  for (const child of node?.content || []) matches.push(...findNodes(child, type));
  return matches;
}

describe("compileAssistantDisplayMessage", () => {
  // contract-test: direct surface=gui.web assertions=chats.rendering.assistant-document-convergence,chats.rendering.inline-entity-interaction
  it("uses identical display semantics for a complete streaming snapshot and final message", () => {
    const markdown = [
      "Use [the selected event](embed:event-one-ref) and this result:",
      "",
      "[!](embed:event-one-ref)",
      "",
      "> [A verified source quote](embed:event-one-ref)",
      "",
      "```json",
      '{"type":"app_skill_use","embed_id":"search-parent","app_id":"events","skill_id":"search"}',
      "```",
    ].join("\n");

    const streaming = compileAssistantDisplayMessage(markdown, {
      phase: "streaming",
      role: "assistant",
      chatId: "chat-1",
    });
    const completed = compileAssistantDisplayMessage(markdown, {
      phase: "final",
      role: "assistant",
      chatId: "chat-1",
    });

    expect(streaming).toEqual(completed);
    expect(findNodes(streaming, "embedInline")).toHaveLength(1);
    expect(findNodes(streaming, "embedPreviewLarge")).toHaveLength(1);
    expect(findNodes(streaming, "sourceQuote")).toHaveLength(1);
    expect(findNodes(streaming, "embed")[0]?.attrs).toMatchObject({
      id: "search-parent",
      type: "app-skill-use",
      app_id: "events",
      skill_id: "search",
    });
  });

  // contract-test: direct surface=gui.web assertions=chats.rendering.assistant-document-convergence
  it("preserves completed-prefix identities while an incomplete suffix grows", () => {
    const completePrefix = [
      "First result:",
      "",
      "[!](embed:event-one-ref)",
    ].join("\n");
    const first = compileAssistantDisplayMessage(`${completePrefix}\n\n\`\`\`json\n{`, {
      phase: "streaming",
      role: "assistant",
    });
    const later = compileAssistantDisplayMessage(
      `${completePrefix}\n\n\`\`\`json\n{"type":"event"`,
      { phase: "streaming", role: "assistant" },
    );

    expect(findNodes(first, "embedPreviewLarge")[0]?.attrs.embedRef).toBe("event-one-ref");
    expect(findNodes(later, "embedPreviewLarge")[0]?.attrs.embedRef).toBe("event-one-ref");
  });

  // contract-test: direct surface=gui.web assertions=chats.rendering.assistant-document-convergence
  it("emits a closed result-view descriptor before surrounding prose completes", () => {
    const markdown = [
      "Here is the comparison:",
      "",
      "```embeds_results_view",
      "title: Berlin events",
      "embeds: event-one-ref, event-two-ref",
      "```",
      "",
      "I am still writing the rest of the answer",
    ].join("\n");

    const doc = compileAssistantDisplayMessage(markdown, {
      phase: "streaming",
      role: "assistant",
    });
    const resultView = findNodes(doc, "embed").find(
      (node) => node.attrs?.type === "embeds-map-view",
    );

    expect(resultView?.attrs.mapEmbedRefs).toEqual(["event-one-ref", "event-two-ref"]);
  });
});
