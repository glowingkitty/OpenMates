import { readFileSync } from "node:fs";
import YAML from "yaml";
import { describe, expect, it } from "vitest";
import { buildPrivacyPolicyContent } from "../buildLegalContent";
import { privacyPolicyChat } from "../documents/privacy-policy";

const translations = YAML.parse(readFileSync(new URL("../../i18n/sources/legal/privacy.yml", import.meta.url), "utf8"));
const canonical = YAML.parse(readFileSync(new URL("../../../../../../shared/docs/privacy_policy.yml", import.meta.url), "utf8"));

const render = (locale: "en" | "de" | "fr"): string => buildPrivacyPolicyContent((key) => {
  const [legal, document, ...parts] = key.split(".");
  if (legal !== "legal" || document !== "privacy") return key;
  const entry = translations[parts.join(".")];
  return entry?.[locale] ?? entry?.en ?? key;
}, {
  lastUpdated: privacyPolicyChat.metadata?.lastUpdated ?? "",
  locale,
});

describe("public historical Directus retention disclosure", () => {
  // contract-test: supporting surface=gui.web assertions=storage.privacy.ciphertext-boundary
  it("renders history separately from active-record deletion in English and German", () => {
    for (const locale of ["en", "de"] as const) {
      const content = render(locale);
      expect(content).toContain(locale === "de" ? "Historische Datenbank" : "Historical database");
      expect(content).toContain(locale === "de"
        ? "Kontoprofilfelder oder verschlüsselte Momentaufnahmen"
        : "account-profile fields or encrypted chat and artifact snapshots");
      expect(content).toContain(locale === "de"
        ? "keinen durchgesetzten automatischen Ablauf"
        : "no enforced automatic expiry");
      expect(content).toContain(locale === "de"
        ? "60-Tage-Lebenszyklus verschlüsselter Backups"
        : "60-day encrypted-backup lifecycle");
      expect(content).not.toContain("BSI §34 BDSG");
      expect(content).not.toContain("retained for 2 years");
    }
  });

  // contract-test: supporting surface=gui.web assertions=storage.privacy.ciphertext-boundary
  it("uses the accurate English fallback in an untranslated locale", () => {
    const content = render("fr");
    expect(content).toContain("Deleting the current records does not automatically purge");
    expect(content).toContain("no enforced automatic expiry");
    expect(content).not.toContain("BSI §34 BDSG");
  });

  // contract-test: supporting surface=gui.web assertions=storage.privacy.ciphertext-boundary
  it("keeps the canonical public policy and existing backup boundary aligned", () => {
    expect(canonical.quick_answers.deletion).toContain("Earlier database revision and activity records");
    expect(canonical.data_retention.historical_directus_history.period).toContain("No enforced automatic expiry");
    expect(canonical.limitations_of_erasure_items.historical_directus_history.scope).toContain("account-profile fields");
    expect(canonical.limitations_of_erasure_items.audit_logs.retention).not.toBe("2 years");
    expect(canonical.data_retention.user_data_backups.period).toContain("60 days");
    expect(render("en")).toContain("60 days via S3 lifecycle");
  });
});
