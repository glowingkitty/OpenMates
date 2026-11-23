import { describe, expect, it, vi } from "vitest";

vi.mock("../../data/modelsMetadata", () => ({
  modelsMetadata: [{ id: "claude-sonnet-5", name: "Claude Sonnet 5" }],
}));
vi.mock("../../data/matesMetadata", () => ({ matesMetadata: [] }));
vi.mock("../../stores/appSkillsStore", () => ({
  appSkillsStore: {
    apps: {
      code: {
        focus_modes: [{ id: "write_specification", name_translation_key: "app_focus_modes.code.write_specification" }],
        skills: [],
      },
    },
  },
}));
vi.mock("../../i18n/translations", async () => {
  const { readable } = await import("svelte/store");
  const titles: Record<string, string> = { "app_focus_modes.code.write_specification": "Write a specification" };
  return { text: readable((key: string) => titles[key] ?? `[T:${key}]`) };
});

import { formatDraftPreview } from "../draftPreview";

describe("formatDraftPreview", () => {
  // contract-test: supporting surface=gui.web assertions=drafts.draft-only.presentation
  it("shows an ai-model mention with provider suffix as its display name", () => {
    expect(formatDraftPreview("@ai-model:claude-sonnet-5:anthropic Is a hot dog a sandwich? One sentence.")).toBe(
      "@Claude-Sonnet-5 Is a hot dog a sandwich? One sentence.",
    );
  });

  // contract-test: supporting surface=gui.web assertions=drafts.draft-only.presentation
  it("falls back to a readable name when model metadata is missing", () => {
    expect(formatDraftPreview("@ai-model:unknown-model:acme hi @best-model:fast go")).toBe(
      "@Unknown-Model hi @Fast go",
    );
  });

  // contract-test: supporting surface=gui.web assertions=drafts.draft-only.presentation,drafts.persistence.local-first-encrypted
  it("replaces saved embed references while preserving surrounding text and order", () => {
    const preview = 'Look at this ```json\n{"type":"image","embed_id":"image-1"}\n``` and ```json\n{"type":"audio-recording","embed_id":"audio-1"}\n```';
    expect(formatDraftPreview(preview)).toBe("Look at this [Image] and [Audio]");
  });

  // contract-test: supporting surface=gui.web assertions=drafts.draft-only.presentation,message-input.drafts.preview-persistence
  it("labels app embed types with short readable names", () => {
    const preview = '```json\n{"type":"sheets-sheet","embed_id":"s-1"}\n``` ```json\n{"type":"images-image","embed_id":"i-1"}\n``` ```json\n{"type":"docs-doc","embed_id":"d-1"}\n```';
    expect(formatDraftPreview(preview)).toBe("[Sheet] [Image] [Document]");
  });

  // contract-test: supporting surface=gui.web assertions=drafts.draft-only.presentation
  it("recovers the label from a preview truncated inside an embed reference", () => {
    expect(formatDraftPreview('```json {"type": "image", "embed_id": "900f821a-b9f7-4a00-84...')).toBe("[Image]");
    expect(formatDraftPreview('Visit ```json_embed\n{"type":"website","embed_id":"web-1"}\n```')).toBe("Visit [Website]");
  });

  // contract-test: supporting surface=gui.web assertions=drafts.draft-only.presentation
  it("handles unfenced saved references and leaves ordinary draft text alone", () => {
    expect(formatDraftPreview('{"type":"pdf","embed_id":"pdf-1"}')).toBe("[PDF]");
    expect(formatDraftPreview('Write a short summary of this document')).toBe("Write a short summary of this document");
  });

  // contract-test: supporting surface=gui.web assertions=drafts.draft-only.presentation
  it("never leaks malformed serialized JSON into a preview", () => {
    expect(formatDraftPreview('```json {"embed_id":"broken"')).toBe("[Embed]");
  });

  // contract-test: direct surface=gui.web assertions=message-input.drafts.preview-persistence,chats.titles.first-message-fallback
  it("shows a Project mention in a draft card by the Project name, never its id", () => {
    const draft = "@project:6b0c2f4e-3a91-4d2b-9c57-1f8e2a7d4c10:read Plan the beds";
    expect(formatDraftPreview(draft, (id) => (id.startsWith("6b0c2f4e") ? "Garden planner" : undefined)))
      .toBe("@Garden planner Plan the beds");
    expect(formatDraftPreview(draft)).toBe("@Project Plan the beds");
  });

  // contract-test: direct surface=gui.web assertions=message-input.drafts.preview-persistence,chats.titles.first-message-fallback
  it("shows a Focus mention by its Focus title", () => {
    expect(formatDraftPreview("@focus:code:write_specification Garden planner"))
      .toBe("@Write a specification Garden planner");
  });

  // contract-test: direct surface=gui.web assertions=message-input.drafts.preview-persistence,chats.titles.first-message-fallback
  it("never leaves mention syntax or ids in a preview", () => {
    expect(formatDraftPreview("@mate:missing Hi 6b0c2f4e-3a91-4d2b-9c57-1f8e2a7d4c10 @unknown:x:y there"))
      .toBe("Hi there");
  });
});
