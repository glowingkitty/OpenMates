import { readFileSync } from "node:fs";
import YAML from "yaml";
import { describe, expect, it } from "vitest";
import { buildPrivacyPolicyContent } from "../buildLegalContent";
import { privacyPolicyChat } from "../documents/privacy-policy";

const privacy = YAML.parse(readFileSync(new URL("../../i18n/sources/legal/privacy.yml", import.meta.url), "utf8"));
const canonical = YAML.parse(readFileSync(new URL("../../../../../../shared/docs/privacy_policy.yml", import.meta.url), "utf8"));

const render = (locale: "en" | "de" | "fr"): string => buildPrivacyPolicyContent((key) => {
  const [legal, document, ...parts] = key.split(".");
  if (legal !== "legal" || document !== "privacy") return key;
  const entry = privacy[parts.join(".")];
  return entry?.[locale] ?? entry?.en ?? key;
}, {
  lastUpdated: privacyPolicyChat.metadata?.lastUpdated ?? "",
  locale,
});

describe("published sealed recovery privacy copy", () => {
  // contract-test: supporting surface=gui.web assertions=storage.background.saved-output-retention,storage.privacy.ciphertext-boundary
  it("renders the English pending-copy rule without a seven-day expiry or plaintext promise", () => {
    const content = render("en");
    expect(content).toContain("remains available until an authorized client");
    expect(content).toContain("verifies and confirms its normal client-encrypted save");
    expect(content).toContain("or the related chat or account is deleted");
    expect(content).toContain("Expiry of a retry lease or the AI");
    expect(content).toContain("Large sealed responses may be stored in regional S3");
    expect(content).toContain("The server cannot rebuild missing readable AI context");
    expect(content).toContain("Deletion markers: To prevent delayed synchronization");
    expect(content).toContain("currently do not expire automatically");
    expect(content).toContain("contain no deleted content");
    expect(content).not.toContain("up to seven days");
    expect(content).not.toContain("pending copy can expire");
    expect(content).toContain("User data backups:** 60 days");
  });

  // contract-test: supporting surface=gui.web assertions=storage.privacy.ciphertext-boundary
  it("separates historical database snapshots from content-free deletion markers", () => {
    for (const locale of ["en", "de", "fr"] as const) {
      const content = render(locale);
      expect(content).toContain(locale === "de"
        ? "Historische Datenbank"
        : "Historical database");
      expect(content).not.toContain("Historical Directus");
      expect(content).not.toContain("generic Directus");
      expect(content).toContain(locale === "de"
        ? "keinen durchgesetzten automatischen Ablauf"
        : "no enforced automatic expiry");
      expect(content).toContain(locale === "de"
        ? "inhaltsfreien Löschmarkern"
        : "content-free deletion markers");
      expect(content).not.toContain("configured for up to two years");
      expect(content).not.toContain("für bis zu zwei Jahre konfiguriert");
    }
    const english = render("en");
    expect(english).toContain("earlier account-profile fields or encrypted chat and artifact snapshots");
    expect(english).toContain("Deleting the current records does not automatically purge");
    expect(english).toContain("Financial transaction records are configured for up to ten years");
    expect(english).not.toContain("unpaid-storage notices");
    expect(english).not.toContain("older chat and artifact ciphertext");
    expect(english).toContain("Uploaded files and recordings are kept separately");
  });

  // contract-test: supporting surface=gui.web assertions=storage.background.saved-output-retention,storage.privacy.ciphertext-boundary
  it("renders the German ACK and deletion rule", () => {
    const content = render("de");
    expect(content).toContain("bis ein berechtigter Client");
    expect(content).toContain("clientseitig verschlüsselte Speicherung überprüft und bestätigt");
    expect(content).toContain("oder der zugehörige Chat beziehungsweise das Konto gelöscht wird");
    expect(content).toContain("Der Ablauf einer Wiederholungsfrist");
    expect(content).toContain("Löschmarker: Um zu verhindern");
    expect(content).toContain("laufen derzeit nicht automatisch ab");
    expect(content).toContain("keine gelöschten Inhalte");
    expect(content).not.toContain("sieben Tage");
    expect(content).not.toContain("unbezahlten Speicher");
    expect(content).not.toContain("ältere Chat- und Artefakt-Geheimtexte");
  });

  // contract-test: supporting surface=gui.web assertions=storage.privacy.ciphertext-boundary
  it("uses the accurate English deletion-marker fallback for other locales", () => {
    const content = render("fr");
    expect(content).toContain("Deletion markers: To prevent delayed synchronization");
    expect(content).toContain("currently do not expire automatically");
  });

  // contract-test: supporting surface=gui.web assertions=storage.background.saved-output-retention,storage.privacy.ciphertext-boundary
  it("keeps the canonical privacy mirror aligned with selected paragraphs", () => {
    expect(canonical.quick_answers.storage_protection).toContain("remains available until an authorized client");
    expect(canonical.data_retention.content.period).toContain("normal client-encrypted save");
    expect(canonical.quick_answers.storage_protection).toContain("server-side Vault keys");
    expect(canonical.quick_answers.storage_protection).not.toContain("seven days");
    expect(canonical.data_retention.content.period).not.toContain("seven days");
    expect(canonical.data_retention.content.period).not.toContain("unpaid-storage");
    expect(canonical.quick_answers.storage_protection).not.toContain("older chat and artifact ciphertext");
    expect(canonical.quick_answers.deletion).toContain("separate from content-free deletion markers");
    expect(canonical.data_retention.deletion_markers.period).toContain("currently do not expire automatically");
    expect(canonical.data_retention.deletion_markers.period).toContain("no deleted content");
    expect(canonical.data_retention.historical_directus_records.period).toContain("no enforced automatic expiry");
    expect(canonical.limitations_of_erasure_items.historical_directus_records.scope).toContain("account-profile fields");
    expect(canonical.limitations_of_erasure_items.audit_logs.retention).not.toBe("2 years");
  });
});
