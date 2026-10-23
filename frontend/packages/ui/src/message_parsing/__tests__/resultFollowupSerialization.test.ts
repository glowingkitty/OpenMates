import { describe, it, expect, vi } from "vitest";
// These tests exercise canonical reference serialization without loading the chat runtime.
vi.mock("../groupHandlers", () => ({ groupHandlerRegistry: { groupToMarkdown: vi.fn() } }));
vi.mock("../../components/enter_message/utils/markdownParser", () => ({ parseMarkdownToTiptap: vi.fn() }));
import { tipTapToCanonicalMarkdown } from "../serializers";

describe("fullscreen follow-up serialization", () => {
  // contract-test: supporting surface=gui.web assertions=chats.rendering.inline-entity-interaction
  it("preserves reference-only result types through normal chat serialization", () => {
    for (const type of ["app-skill-use", "events-event", "images-image-result"]) {
      const result = tipTapToCanonicalMarkdown({ type: "doc", content: [
        { type: "paragraph", content: [{ type: "text", text: "Make the sky brighter" }] },
        { type: "paragraph", content: [{ type: "embed", attrs: {
          id: "selected-result", type, status: "finished", referenceOnly: true,
          contentRef: "embed:selected-result", app_id: "images", skill_id: "generate",
        } }] },
      ] });
      const reference = JSON.parse(result.split("```json\n")[1].split("\n```")[0]);
      expect(reference).toEqual({ type, embed_id: "selected-result", reference_only: true,
        app_id: "images", skill_id: "generate" });
      expect(result).toContain("Make the sky brighter");
    }
  });
});
