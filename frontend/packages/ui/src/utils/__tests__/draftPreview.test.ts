import { describe, expect, it } from "vitest";
import { formatDraftPreview } from "../draftPreview";

describe("formatDraftPreview", () => {
  // contract-test: supporting surface=gui.web assertions=drafts.draft-only.presentation,drafts.persistence.local-first-encrypted
  it("replaces saved embed references while preserving surrounding text and order", () => {
    const preview = 'Look at this ```json\n{"type":"image","embed_id":"image-1"}\n``` and ```json\n{"type":"audio-recording","embed_id":"audio-1"}\n```';
    expect(formatDraftPreview(preview)).toBe("Look at this [Image] and [Audio]");
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
});
