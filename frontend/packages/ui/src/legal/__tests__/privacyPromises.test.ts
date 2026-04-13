// frontend/packages/ui/src/legal/__tests__/privacyPromises.test.ts
// Vitest meta-test for the generated Privacy Promises module and its
// integration with buildPrivacyPolicyContent(). Complements
// backend/tests/test_privacy_promises.py on the frontend side.
//
// Verifies:
//   1. generate-privacy-promises.js produced a non-empty registry.
//   2. Every surfaced promise appears as a heading in the rendered policy.
//   3. Every surfaced promise has live i18n keys (heading + description).
//   4. The "privacy-promises" intro line renders once.
//
// Source of truth: /shared/docs/privacy_promises.yml
// Generator:       frontend/packages/ui/scripts/generate-privacy-promises.js

import { describe, expect, it } from "vitest";
import {
  PRIVACY_PROMISES,
  SURFACED_PRIVACY_PROMISES,
} from "../privacyPromises.generated";
import { buildPrivacyPolicyContent } from "../buildLegalContent";

// Test translator: returns a marker string containing the key so we can
// assert which keys were consulted without needing a real i18n store.
const echoTranslator = (key: string): string => `{{${key}}}`;

describe("Privacy Promises — generated registry", () => {
  it("contains at least one promise", () => {
    expect(PRIVACY_PROMISES.length).toBeGreaterThan(0);
  });

  it("surfaces every promise marked surfaced_in_policy", () => {
    const surfaced = PRIVACY_PROMISES.filter((p) => p.surfaced_in_policy);
    expect(SURFACED_PRIVACY_PROMISES.length).toBe(surfaced.length);
    expect(SURFACED_PRIVACY_PROMISES.length).toBeGreaterThanOrEqual(12);
  });

  it("has unique ids and canonical i18n_key prefixes", () => {
    const ids = new Set<string>();
    for (const p of PRIVACY_PROMISES) {
      expect(ids.has(p.id)).toBe(false);
      ids.add(p.id);
      expect(p.i18n_key.startsWith("legal.privacy.promises.")).toBe(true);
    }
  });
});

describe("buildPrivacyPolicyContent — Privacy Promises section", () => {
  const rendered = buildPrivacyPolicyContent(
    echoTranslator,
    "2026-04-13T00:00:00Z",
    "en",
  );

  it("renders the promises intro once", () => {
    const matches =
      rendered.match(/\{\{legal\.privacy\.promises\.intro\}\}/g) ?? [];
    expect(matches.length).toBe(1);
  });

  it("renders every surfaced promise as a level-3 heading with a description", () => {
    for (const promise of SURFACED_PRIVACY_PROMISES) {
      const headingKey = `${promise.i18n_key}.heading`;
      const descriptionKey = `${promise.i18n_key}.description`;
      expect(rendered).toContain(`### {{${headingKey}}}`);
      expect(rendered).toContain(`{{${descriptionKey}}}`);
    }
  });

  it("does not reference the legacy protection.*.description keys", () => {
    // The old hard-coded 6-item list has been replaced by the registry.
    const legacy = [
      "legal.privacy.protection.client_side_encryption.description",
      "legal.privacy.protection.pii_placeholder_substitution.description",
      "legal.privacy.protection.encrypted_at_rest.description",
      "legal.privacy.protection.hashed_identifiers.description",
      "legal.privacy.protection.cryptographic_erasure.description",
      "legal.privacy.protection.observability_without_tracking.description",
    ];
    for (const key of legacy) {
      expect(rendered).not.toContain(`{{${key}}}`);
    }
  });
});
