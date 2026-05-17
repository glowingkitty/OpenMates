/**
 * frontend/packages/ui/src/utils/__tests__/embedSourceDomain.test.ts
 *
 * Regression coverage for image result embed preview source labels.
 * The visible preview pill should show the provider/source domain instead of
 * falling back to the generic "Image" label whenever source metadata exists.
 */

import { describe, expect, it } from "vitest";
import { resolveImageSourceDomain } from "../embedSourceDomain";

describe("resolveImageSourceDomain", () => {
  it("prefers the provider source field", () => {
    expect(resolveImageSourceDomain({ source: "cotoacademy.com" })).toBe("cotoacademy.com");
  });

  it("falls back to source_domain", () => {
    expect(resolveImageSourceDomain({ source_domain: "unsplash.com" })).toBe("unsplash.com");
  });

  it("derives a domain from the source page URL", () => {
    expect(resolveImageSourceDomain({ source_page_url: "https://www.example.com/images/honorifics" })).toBe("example.com");
  });
});
