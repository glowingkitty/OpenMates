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
});
