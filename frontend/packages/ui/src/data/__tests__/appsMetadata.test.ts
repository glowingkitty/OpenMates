// frontend/packages/ui/src/data/__tests__/appsMetadata.test.ts
//
// Regression coverage for Settings > Apps app metadata.
// Apps that expose direct content embeds, but no callable skills or memories,
// must still appear in the generated app catalog so their content pages and
// public example chats are discoverable from settings.

import { describe, expect, it } from "vitest";

import { emailVerificationSequenceDiagramChat } from "../../demo_chats/data/example_chats/email-verification-sequence-diagram";
import { appsMetadata } from "../appsMetadata";
import { CONTENT_EMBED_CATALOG } from "../embedRegistry.generated";

describe("appsMetadata generated catalog", () => {
  it("includes the Diagrams app with its Mermaid content embed example", () => {
    expect(appsMetadata.diagrams).toMatchObject({
      id: "diagrams",
      name_translation_key: "apps.diagrams",
      description_translation_key: "apps.diagrams.description",
      icon_image: "diagram.svg",
    });

    expect(
      CONTENT_EMBED_CATALOG.find((item) => item.id === "diagrams.mermaid"),
    ).toMatchObject({
      appId: "diagrams",
      contentTypeId: "mermaid",
      frontendType: "diagrams-mermaid",
      backendType: "mermaid",
      exampleKey: "diagrams.mermaid",
    });

    expect(
      emailVerificationSequenceDiagramChat.metadata.content_embed_examples,
    ).toContain("diagrams.mermaid");
    expect(emailVerificationSequenceDiagramChat.embeds).toEqual(
      expect.arrayContaining([
        expect.objectContaining({
          type: "mermaid",
        }),
      ]),
    );
  });
});
