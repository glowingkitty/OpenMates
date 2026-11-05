import { readFileSync } from "node:fs";
import YAML from "yaml";
import { describe, expect, it } from "vitest";
import { buildPrivacyPolicyContent } from "../../../../public-site/src/legal/buildLegalContent";
import { privacyPolicyChat } from "../../../../public-site/src/legal/documents/privacy-policy";

const translations = YAML.parse(readFileSync(new URL("../../i18n/sources/legal/privacy.yml", import.meta.url), "utf8"));
const canonical = YAML.parse(readFileSync(new URL("../../../../../../shared/docs/privacy_policy.yml", import.meta.url), "utf8"));

const render = (locale: "en" | "de") => buildPrivacyPolicyContent((key) => {
  const entry = translations[key.replace(/^legal\.privacy\./, "")];
  return entry?.[locale] ?? entry?.en ?? key;
}, { lastUpdated: privacyPolicyChat.metadata?.lastUpdated ?? "", locale });

describe("Redact licensing privacy disclosure", () => {
  // contract-test: supporting surface=gui.web assertions=pii.web.provider-disclosure
  it("records the controller and the content-free mandatory licensing boundary", () => {
    const group = canonical.provider_groups.local_privacy_protection;
    const provider = group.providers.desert_ant_labs;
    expect(group.description).toContain("enabled by default");
    expect(group.description).toContain("complete basic detector");
    expect(provider.role).toContain("controller");
    expect(provider.data_shared.join(" ")).toContain("Browser installation UUID");
    expect(provider.data_shared.join(" ")).toContain("signed license token");
    expect(provider.data_shared.join(" ")).toContain("Origin");
    expect(provider.data_not_shared.join(" ")).toContain("Text being scanned, detection results, placeholder mappings and OpenMates account ID");
    expect(provider.data_handling).toContain("do not promise a particular vendor retention period");
  });

  // contract-test: supporting surface=gui.web assertions=pii.web.provider-disclosure
  it.each(["en", "de"] as const)("publishes the complete %s disclosure and verified links", (locale) => {
    const body = render(locale);
    expect(body).toContain("Redact");
    expect(body).toContain("Desert Ant Labs");
    expect(body).toContain("https://desertant.com/privacy/");
    expect(body).toContain("https://license.desertant.com/1.0");
    expect(body).toContain(locale === "en" ? "enabled by default" : "standardmäßig aktiviert");
    expect(body).toContain(locale === "en" ? "complete basic text detector" : "vollständige grundlegende Textdetektor");
    expect(body).toContain(locale === "en" ? "directly from your browser" : "direkt von deinem Browser");
    expect(body).toContain(locale === "en" ? "independent controller" : "eigenständiger Verantwortlicher");
    expect(body).toContain(locale === "en" ? "not anonymous or wholly offline" : "weder anonym noch vollständig offline");
    expect(body).toContain(locale === "en" ? "does not promise a particular vendor retention period" : "verspricht keine bestimmte Aufbewahrungsfrist");
    expect(body).toContain(locale === "en" ? "Text being scanned, detection results, placeholder mappings and your OpenMates account ID are not included" : "Der untersuchte Text, Erkennungsergebnisse, Platzhalterzuordnungen und deine OpenMates-Konto-ID sind in diesen Anfragen nicht enthalten");
    expect(body).toContain(locale === "en" ? "web users do not need to download them from Hugging Face" : "im Web musst du sie nicht von Hugging Face herunterladen");
    expect(body).toContain(locale === "en" ? "raw transcripts, uploaded files" : "Rohtranskripte, hochgeladene Dateien");
    expect(body).not.toContain("legal.privacy.providers.local_privacy");
    expect(privacyPolicyChat.metadata?.lastUpdated).toBe("2026-10-28T00:00:00Z");
  });
});
