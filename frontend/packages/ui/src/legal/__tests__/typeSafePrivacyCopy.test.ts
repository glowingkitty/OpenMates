import { readFileSync } from "node:fs";
import YAML from "yaml";
import { describe, expect, it } from "vitest";
import { buildPrivacyPolicyContent } from "../../../../public-site/src/legal/buildLegalContent";
import { privacyPolicyChat } from "../../../../public-site/src/legal/documents/privacy-policy";

const translations = YAML.parse(readFileSync(new URL("../../i18n/sources/legal/privacy.yml", import.meta.url), "utf8"));
const canonical = YAML.parse(readFileSync(new URL("../../../../../../shared/docs/privacy_policy.yml", import.meta.url), "utf8"));
const training = YAML.parse(readFileSync(new URL("../../../../../../shared/docs/provider_training_policies.yml", import.meta.url), "utf8"));

const render = (locale: "en" | "de") => buildPrivacyPolicyContent((key) => {
  const [legal, document, ...parts] = key.split(".");
  if (legal !== "legal" || document !== "privacy") return key;
  const entry = translations[parts.join(".")];
  return entry?.[locale] ?? entry?.en ?? key;
}, { lastUpdated: privacyPolicyChat.metadata?.lastUpdated ?? "", locale });

describe("TypeSafe Jev privacy disclosure", () => {
  // contract-test: supporting surface=gui.web assertions=storage.privacy.ciphertext-boundary
  it("discloses the direct US route and conditional OpenRouter fallback", () => {
    const providers = canonical.provider_groups.ai_models.providers;
    expect(providers.typesafe.location).toBe("US");
    expect(providers.typesafe.privacy_policy).toBe("https://typesafe.ai/legal/privacy-policy");
    expect(providers.typesafe.used_for.join(" ")).toContain("direct");
    expect(providers.openrouter.used_for.join(" ")).toContain("fallback routing to TypeSafe Jev");
    expect(providers.openrouter.data_shared.join(" ")).toContain("same minimized");

    for (const locale of ["en", "de"] as const) {
      const policy = render(locale);
      expect(policy).toContain(locale === "en" ? "TypeSafe Jev (US)" : "TypeSafe Jev (USA)");
      expect(policy).toContain(locale === "en" ? "primarily sends bounded decision requests directly to TypeSafe Jev" : "überwiegend direkt an TypeSafe Jev");
      expect(policy).toContain(locale === "en" ? "Image requests use direct TypeSafe only" : "Bildanfragen verwenden ausschließlich die direkte TypeSafe-Verbindung");
      expect(policy).toContain(locale === "en" ? "does not guarantee zero retention by TypeSafe" : "garantiert jedoch keine speicherfreie Verarbeitung bei TypeSafe");
      expect(policy).toContain(locale === "en" ? "Raw API inputs and image bytes" : "Rohe API-Eingaben und Bildbytes");
      expect(policy).toContain("https://typesafe.ai/legal/privacy-policy");
      expect(policy).not.toContain("TypeSafe Jev (via OpenRouter)");
    }
    expect(training.providers.typesafe.status).toBe("no_training");
    expect(training.providers.typesafe.quote).toContain("will not train or fine tune");
    expect(training.providers.typesafe.notes).toContain("standard route does not imply it");
    expect(privacyPolicyChat.metadata?.lastUpdated).toBe("2026-10-19T00:00:00Z");
  });
});
