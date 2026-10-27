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

  // contract-test: supporting surface=gui.web assertions=storage.privacy.ciphertext-boundary
  it("discloses optional shopping image processing and excludes image fallback forwarding", () => {
    const provider = canonical.provider_groups.ai_models.providers.typesafe;
    expect(provider.used_for.join(" ")).toContain("shopping visual matching, only when reference images are provided");
    const shared = provider.data_shared.join(" ");
    expect(shared).toContain("up to three authorized user-uploaded or assistant-generated reference images");
    expect(shared).toContain("bounded public product photos");
    expect(shared).toContain("metadata-stripped JPEG images with a maximum dimension of 336 pixels");
    expect(shared).toContain("Visible image content can contain personal data");
    expect(shared).toContain("not forwarded to OpenRouter");
    const english = render("en");
    expect(english).toContain("only when reference images are provided");
    expect(english).toContain("up to three authorized user-uploaded or assistant-generated reference images");
    expect(english).toContain("bounded public product photos");
    expect(english).toContain("visible image content can still contain personal data");
    expect(english).toContain("Image requests use direct TypeSafe only");
    const german = render("de");
    expect(german).toContain("nur dann Bilder, wenn Referenzbilder angegeben werden");
    expect(german).toContain("bis zu drei autorisierte");
    expect(german).toContain("sichtbare Bildinhalte können weiterhin personenbezogene Daten enthalten");
    expect(german).toContain("Bildanfragen verwenden ausschließlich die direkte TypeSafe-Verbindung");
  });

  // contract-test: supporting surface=gui.web assertions=storage.privacy.ciphertext-boundary
  it("separates the no-training promise from retention and resolves the source links", () => {
    const handling = canonical.provider_groups.ai_models.providers.typesafe.data_shared.join(" ");
    expect(handling).toContain("does not train or fine-tune");
    expect(handling).toContain("without a fixed maximum retention period");
    expect(handling).toContain("does not guarantee zero data retention");
    expect(training.providers.typesafe.last_verified).toBe("2026-10-19T00:00:00Z");
    expect(training.providers.typesafe.notes).toContain("no-training commitment does not imply immediate deletion");

    const english = render("en");
    expect(english).toContain("does not train or fine-tune models on submitted input");
    expect(english).toContain("without a fixed maximum retention period");
    expect(english).toContain("does not guarantee zero data retention");
    const german = render("de");
    expect(german).toContain("ohne eine feste maximale Aufbewahrungsfrist");
    expect(german).toContain("Ein Ausschluss des Modelltrainings bedeutet nicht");
    for (const policy of [english, german]) {
      expect(policy).toContain("https://typesafe.ai/legal/data-processing");
      expect(policy).toContain("https://docs.typesafe.ai/legal");
      expect(policy).not.toContain("{data_processing_url}");
      expect(policy).not.toContain("{legal_url}");
    }
  });
});
