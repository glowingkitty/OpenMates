// frontend/packages/ui/src/data/__tests__/appsMetadata.test.ts
//
// Regression coverage for Settings > Apps app metadata.
// Active app definitions and their durable content types must appear in the
// generated catalogs, while retired content types stay out.

import { describe, expect, it } from "vitest";

import { appsMetadata } from "../appsMetadata";
import { CONTENT_EMBED_CATALOG } from "../embedRegistry.generated";

describe("appsMetadata generated catalog", () => {
  // contract-test: supporting surface=gui.web assertions=apps.discovery.public-catalog
  it("includes Diagram Design with HTML diagrams but no Mermaid content type", () => {
    expect(appsMetadata.diagrams).toMatchObject({
      id: "diagrams",
      name_translation_key: "apps.diagrams",
      description_translation_key: "apps.diagrams.description",
      icon_image: "diagram.svg",
    });
    expect(
      CONTENT_EMBED_CATALOG.find((item) => item.id === "diagrams.diagram_html"),
    ).toMatchObject({
      appId: "diagrams",
      contentTypeId: "diagram_html",
      registryKey: "diagrams-html",
      backendType: "diagram_html",
    });
    expect(
      CONTENT_EMBED_CATALOG.find((item) => item.id === "diagrams.mermaid"),
    ).toBeUndefined();
  });

  // contract-test: supporting surface=gui.web assertions=apps.discovery.public-catalog
  it("keeps screenshot-to-HTML settings metadata user-facing", () => {
    const skill = appsMetadata.code.skills.find((item) => item.id === "image_to_html");

    expect(skill?.name_translation_key).toBe("app_skills.code.image_to_html");
    expect(skill?.description_translation_key).toBe("app_skills.code.image_to_html.description");
    expect(skill?.providers).toEqual(["Google", "E2B"]);
    expect(skill?.pricing).toEqual({
      tokens: {
        input: { per_credit_unit: 200 },
        output: { per_credit_unit: 45 },
      },
      per_minute: 5,
    });
  });
});
