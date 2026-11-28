/**
 * Fallback labels for inline embed links whose model-written text is technical.
 * Web fallbacks are the bare domain so no English connective leaks into
 * answers in other languages (prod 7ETA7: "laut according to mdr.de").
 */
import { describe, expect, it } from "vitest";
import { deriveEmbedDisplayTextFromRef, resolveEmbedDisplayText } from "../embedDisplayText";

describe("deriveEmbedDisplayTextFromRef", () => {
  // contract-test: supporting surface=gui.web assertions=chats.rendering.inline-entity-interaction
  it("uses the bare domain for web refs", () => {
    expect(deriveEmbedDisplayTextFromRef("mdr.de-k2P")).toBe("mdr.de");
  });

  // contract-test: supporting surface=gui.web assertions=chats.rendering.inline-entity-interaction
  it("replaces a technical label with the bare domain", () => {
    expect(resolveEmbedDisplayText("mdr.de-k2P", "mdr.de-k2P")).toBe("mdr.de");
  });

  // contract-test: supporting surface=gui.web assertions=chats.rendering.inline-entity-interaction
  it("keeps a meaningful model-written label", () => {
    expect(resolveEmbedDisplayText("laut MDR", "mdr.de-k2P")).toBe("laut MDR");
  });
});
