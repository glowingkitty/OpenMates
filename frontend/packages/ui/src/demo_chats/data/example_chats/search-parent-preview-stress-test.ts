// frontend/packages/ui/src/demo_chats/data/example_chats/search-parent-preview-stress-test.ts
//
// Synthetic internal example chat for large parent/child embed graph testing.
// This fixture is generated deterministically so it exercises many messages,
// parent embeds, and child embeds without storing a huge hand-written array.
// It must stay free of provider calls and AI inference.
// Architecture: docs/specs/search-parent-preview-metadata-sync/spec.yml

import type { ExampleChat, ExampleChatEmbed, ExampleChatMessage } from "../../types";

const CHAT_ID = "example-search-parent-preview-stress-test";
const BASE_TIMESTAMP = 1_780_900_000;
const TURN_COUNT = 40;
const CHILDREN_PER_PARENT = 12;

function deterministicId(kind: string, index: number, childIndex = 0): string {
  const suffix = `${index.toString().padStart(6, "0")}${childIndex.toString().padStart(6, "0")}`;
  const kindCode = kind === "parent" ? "4000" : kind === "child" ? "4001" : "4002";
  return `00000000-0000-${kindCode}-8000-${suffix}`;
}

function jsonContent(value: Record<string, unknown>): string {
  return JSON.stringify(value);
}

function parentEmbed(appId: "web" | "images", turnIndex: number, childIds: string[]): ExampleChatEmbed {
  const previewResults = childIds.slice(0, 6).map((childId, childIndex) => {
    const title = `${appId === "web" ? "Article" : "Image"} ${turnIndex}-${childIndex}`;
    return appId === "web"
      ? {
          title,
          url: `https://example.com/stress/${turnIndex}/${childIndex}`,
          favicon_url: `https://example.com/favicon-${childIndex}.ico`,
          source: "example.com",
        }
      : {
          title,
          source_page_url: `https://images.example.com/stress/${turnIndex}/${childIndex}`,
          image_url: `https://images.example.com/full/${turnIndex}-${childIndex}.jpg`,
          thumbnail_url: `https://images.example.com/thumb/${turnIndex}-${childIndex}.jpg`,
          source: "images.example.com",
        };
  });

  const embedId = deterministicId("parent", turnIndex);
  return {
    embed_id: embedId,
    type: "app_skill_use",
    content: jsonContent({
      app_id: appId,
      skill_id: "search",
      status: "finished",
      embed_id: embedId,
      embed_ids: childIds,
      result_count: childIds.length,
      query: `${appId} stress query ${turnIndex}`,
      provider: "Synthetic Fixture",
      preview_results: previewResults,
      ...(appId === "images" ? { preview_results_json: JSON.stringify(previewResults) } : {}),
    }),
    parent_embed_id: null,
    embed_ids: childIds,
  };
}

function childEmbed(appId: "web" | "images", turnIndex: number, childIndex: number, parentId: string): ExampleChatEmbed {
  const embedId = deterministicId("child", turnIndex, childIndex);
  const title = `${appId === "web" ? "Article" : "Image"} ${turnIndex}-${childIndex}`;
  return {
    embed_id: embedId,
    type: appId === "web" ? "website" : "image_result",
    content: jsonContent(
      appId === "web"
        ? {
            title,
            url: `https://example.com/stress/${turnIndex}/${childIndex}`,
            description: `Full synthetic child result ${turnIndex}-${childIndex}`,
            favicon_url: `https://example.com/favicon-${childIndex}.ico`,
            app_id: appId,
            skill_id: "search",
            embed_ref: `stress-web-${turnIndex}-${childIndex}`,
          }
        : {
            title,
            source_page_url: `https://images.example.com/stress/${turnIndex}/${childIndex}`,
            image_url: `https://images.example.com/full/${turnIndex}-${childIndex}.jpg`,
            thumbnail_url: `https://images.example.com/thumb/${turnIndex}-${childIndex}.jpg`,
            app_id: appId,
            skill_id: "search",
            embed_ref: `stress-image-${turnIndex}-${childIndex}`,
          },
    ),
    parent_embed_id: parentId,
    embed_ids: null,
  };
}

function buildStressData(): { messages: ExampleChatMessage[]; embeds: ExampleChatEmbed[] } {
  const messages: ExampleChatMessage[] = [];
  const embeds: ExampleChatEmbed[] = [];

  for (let turnIndex = 0; turnIndex < TURN_COUNT; turnIndex++) {
    const appId = turnIndex % 2 === 0 ? "web" : "images";
    const childIds = Array.from({ length: CHILDREN_PER_PARENT }, (_, childIndex) =>
      deterministicId("child", turnIndex, childIndex),
    );
    const parent = parentEmbed(appId, turnIndex, childIds);
    embeds.push(parent);
    for (let childIndex = 0; childIndex < CHILDREN_PER_PARENT; childIndex++) {
      embeds.push(childEmbed(appId, turnIndex, childIndex, parent.embed_id));
    }

    messages.push({
      id: deterministicId("message", turnIndex * 2),
      role: "user",
      content: `Run synthetic ${appId} search stress turn ${turnIndex}.`,
      created_at: BASE_TIMESTAMP + turnIndex * 60,
    });
    messages.push({
      id: deterministicId("message", turnIndex * 2 + 1),
      role: "assistant",
      content: `Synthetic ${appId} search parent ${turnIndex}:\n\n\`\`\`json\n${JSON.stringify({
        type: "app_skill_use",
        embed_id: parent.embed_id,
        app_id: appId,
        skill_id: "search",
      })}\n\`\`\``,
      created_at: BASE_TIMESTAMP + turnIndex * 60 + 30,
      category: "general_knowledge",
      model_name: "Synthetic Fixture",
    });
  }

  return { messages, embeds };
}

const stressData = buildStressData();

export const searchParentPreviewStressTestChat: ExampleChat = {
  chat_id: CHAT_ID,
  slug: "search-parent-preview-stress-test",
  title: "Search Parent Preview Stress Test",
  summary: "Internal synthetic fixture with many messages, parent embeds, and child embeds for load testing.",
  icon: "search",
  category: "general_knowledge",
  keywords: ["internal", "stress", "embeds", "search", "performance"],
  follow_up_suggestions: [],
  messages: stressData.messages,
  embeds: stressData.embeds,
  metadata: {
    featured: false,
    order: 99_999,
  },
};
