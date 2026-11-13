// frontend/packages/ui/src/message_parsing/__tests__/bodyEmbedPolicy.test.ts
//
// Purpose: an assistant answer body shows only result embeds; app skill
// invocations (including generated-media parents) show only in the "Used the
// X app" container (app-skills.answer.only-result-embeds-in-body).
//
// Related: ../bodyEmbedPolicy.ts, ../parse_message.ts, ../assistantActivityRuns.ts

import { afterEach, describe, expect, it } from "vitest";
import { parse_message } from "../parse_message";
import { embedStore } from "../../services/embedStore";
import { bodyMayShowEmbed, enforceBodyEmbedPolicy, pendingBodySkillParents } from "../bodyEmbedPolicy";
import { assistantActivityItems, splitAssistantActivityRuns } from "../assistantActivityRuns";
import { resolveEmbedRefIndexEntry } from "../../services/embedRefIndex";

const PARENT_ID = "0e29d61f-c88d-4a11-9c61-111111111111";
const PARENT_REF = "generated-media-images-0e29d61fc88d";
const CHILD_ID = "ff26d807-eb07-592a-907f-3db004423cd5";
const CHILD_REF = "generated-images-ff26d807eb07";
const EXAMPLE_CHAT = "example-community-garden-sunflower-illustration";
const EXAMPLE_PARENT_REF = "generated-media-images-83e98b9b8bcb";

function parseAssistant(markdown: string, chatId?: string): any {
  return parse_message(markdown, "read", { unifiedParsingEnabled: true, role: "assistant", chatId });
}

function find(nodes: any[], type: string): any[] {
  const out: any[] = [];
  for (const node of nodes || []) {
    if (node?.type === type) out.push(node);
    if (Array.isArray(node?.content)) out.push(...find(node.content, type));
  }
  return out;
}

function visibleLarge(doc: any): any[] {
  return find(doc.content, "embedPreviewLarge").filter((node) => !node.attrs?.bodyHidden);
}

function registerImageGraph(): void {
  embedStore.registerEmbedRef(PARENT_REF, PARENT_ID, "images", "app_skill_use", "generate");
  embedStore.registerEmbedRef(CHILD_REF, CHILD_ID, "images", "generated_image", "generate");
}

const lateContext = (children: Record<string, string[]>) => ({
  resolve: (ref: string) => resolveEmbedRefIndexEntry(ref),
  childIds: (id: string) => children[id] ?? null,
});

describe("answer body shows only result embeds", () => {
  afterEach(() => {
    embedStore.clearEmbedRefIndex();
  });

  // contract-test: direct surface=gui.web assertions=app-skills.answer.only-result-embeds-in-body

  it("renders only the child when a parent [!] ref follows its child", () => {
    registerImageGraph();
    const doc = parseAssistant([
      "Here is your image:",
      `[!](embed:${CHILD_REF})`,
      `[!](embed:${PARENT_REF})`,
    ].join("\n"));

    const visible = visibleLarge(doc);
    expect(visible).toHaveLength(1);
    expect(visible[0].attrs).toMatchObject({ embedRef: CHILD_REF, embedId: CHILD_ID, carouselIndex: 0, carouselTotal: 1 });

    // Once the parent's children are known, the placeholder disappears and
    // the already shown child is not repeated.
    const resolved = enforceBodyEmbedPolicy(doc, lateContext({ [PARENT_ID]: [CHILD_ID] }));
    expect(find(resolved.content, "embedPreviewLarge")).toHaveLength(1);
    expect(find(resolved.content, "embedPreviewLarge")[0].attrs).toMatchObject({ embedId: CHILD_ID, carouselTotal: 1 });

    // Without a JSON block the parent ref is the only marker of the
    // invocation: it goes to the "Used the app" run, never the body run.
    const runs = splitAssistantActivityRuns(resolved) ?? [];
    expect(runs.map((run) => run.kind)).toEqual(["content", "skills"]);
    expect(assistantActivityItems(runs[1].document)).toEqual([
      expect.objectContaining({ id: PARENT_ID, type: "app-skill-use", app_id: "images", skill_id: "generate" }),
    ]);
    expect(assistantActivityItems(runs[0].document)).toHaveLength(0);
  });

  // contract-test: direct surface=gui.web assertions=app-skills.answer.only-result-embeds-in-body

  it("hides an unresolved generated-media parent ref while streaming", () => {
    const doc = parseAssistant(`Working on it.\n\n[!](embed:${PARENT_REF})`);
    expect(visibleLarge(doc)).toHaveLength(0);
    expect(bodyMayShowEmbed(PARENT_REF, null)).toBe(false);
    expect(bodyMayShowEmbed(CHILD_REF, null)).toBe(true);
  });

  // contract-test: direct surface=gui.web assertions=app-skills.answer.only-result-embeds-in-body

  it("replaces a parent-only ref by its result children", () => {
    // Public example chats know the graph synchronously.
    const example = parseAssistant(`Here it is:\n\n[!](embed:${EXAMPLE_PARENT_REF})`, EXAMPLE_CHAT);
    expect(visibleLarge(example).map((node) => node.attrs.embedId)).toEqual([CHILD_ID]);

    // Synced chats read the parent later; the late pass inserts the children
    // at the parent's spot with correct carousel counts.
    registerImageGraph();
    const secondChild = "aa26d807-eb07-592a-907f-3db004423cd6";
    const doc = parseAssistant(`Intro.\n\n[!](embed:${PARENT_REF})\n\nOutro.`);
    const context = lateContext({});
    expect(pendingBodySkillParents(doc, context)).toEqual([PARENT_ID]);
    const resolved = enforceBodyEmbedPolicy(doc, lateContext({ [PARENT_ID]: [CHILD_ID, secondChild] }));
    const blocks = resolved.content.filter((node: any) => node.type !== "paragraph" || node.content?.length);
    expect(blocks.map((node: any) => node.content?.[0]?.type ?? node.type)).toEqual([
      "text", "embed", "embedPreviewLarge", "embedPreviewLarge", "text",
    ]);
    expect(find(resolved.content, "embedPreviewLarge").map((node) => node.attrs)).toEqual([
      expect.objectContaining({ embedId: CHILD_ID, carouselIndex: 0, carouselTotal: 2, runRef: CHILD_ID }),
      expect.objectContaining({ embedId: secondChild, carouselIndex: 1, carouselTotal: 2, runRef: CHILD_ID }),
    ]);
  });

  // contract-test: direct surface=gui.web assertions=app-skills.answer.only-result-embeds-in-body

  it("keeps the text of an inline link to a skill embed as plain text", () => {
    registerImageGraph();
    const doc = parseAssistant(`See [the generation](embed:${PARENT_REF}) above.`);
    expect(find(doc.content, "embedInline")).toHaveLength(0);
    const texts = find(doc.content, "text").map((node) => node.text).join("");
    expect(texts).toBe("See the generation above.");
    expect(find(doc.content, "text").every((node) => !node.marks?.some((mark: any) => mark.type === "link"))).toBe(true);

    // A link that resolves to a skill only after parsing becomes text too.
    embedStore.clearEmbedRefIndex();
    const early = parseAssistant("See [the search](embed:web-search-parent-k8D).");
    expect(find(early.content, "embedInline")).toHaveLength(1);
    embedStore.registerEmbedRef("web-search-parent-k8D", "web-search-1", "web", "app_skill_use", "search");
    const late = enforceBodyEmbedPolicy(early, lateContext({}));
    expect(find(late.content, "embedInline")).toHaveLength(0);
    expect(find(late.content, "text").map((node) => node.text).join("")).toBe("See the search.");
  });

  // contract-test: direct surface=gui.web assertions=app-skills.answer.only-result-embeds-in-body

  it("still places the skill embed in the Used the app container", () => {
    registerImageGraph();
    const doc = parseAssistant([
      `\`\`\`json\n{"type":"app_skill_use","embed_id":"${PARENT_ID}","app_id":"images","skill_id":"generate"}\n\`\`\``,
      "",
      "Here is your image:",
      "",
      `[!](embed:${CHILD_REF})`,
      `[!](embed:${PARENT_REF})`,
    ].join("\n"));
    const runs = splitAssistantActivityRuns(doc) ?? [];
    expect(runs.map((run) => run.kind)).toEqual(["skills", "content"]);
    expect(assistantActivityItems(runs[0].document)).toEqual([
      expect.objectContaining({ id: PARENT_ID, type: "app-skill-use", app_id: "images", skill_id: "generate" }),
    ]);
    expect(visibleLarge(runs[1].document).map((node) => node.attrs.embedId)).toEqual([CHILD_ID]);
    expect(assistantActivityItems(runs[1].document)).toHaveLength(0);
  });

  // contract-test: direct surface=gui.web assertions=app-skills.answer.only-result-embeds-in-body

  it("leaves result embeds untouched", () => {
    registerImageGraph();
    const doc = parseAssistant(`[!](embed:${CHILD_REF})\n\nSee [the image](embed:${CHILD_REF}).`);
    expect(visibleLarge(doc)[0].attrs).toMatchObject({ embedRef: CHILD_REF, embedId: CHILD_ID, carouselTotal: 1 });
    expect(find(doc.content, "embedInline")[0].attrs).toMatchObject({ embedRef: CHILD_REF, embedId: CHILD_ID });
    expect(enforceBodyEmbedPolicy(doc, lateContext({}))).toBe(doc);
  });
});
