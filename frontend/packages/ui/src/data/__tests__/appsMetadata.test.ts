// frontend/packages/ui/src/data/__tests__/appsMetadata.test.ts
//
// Regression coverage for Settings > Apps app metadata.
// Deactivated app definitions must stay out of generated catalogs even when
// dormant implementation files remain in the repository.

import { describe, expect, it } from "vitest";

import { appsMetadata } from "../appsMetadata";
import { CONTENT_EMBED_CATALOG } from "../embedRegistry.generated";

describe("appsMetadata generated catalog", () => {
  it("omits the deactivated Diagrams app and Mermaid content type", () => {
    expect(appsMetadata.diagrams).toBeUndefined();
    expect(
      CONTENT_EMBED_CATALOG.find((item) => item.id === "diagrams.mermaid"),
    ).toBeUndefined();
  });

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
