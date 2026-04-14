/**
 * Build legal document content from translation keys
 *
 * These functions construct markdown content from i18n translation keys
 * to ensure legal documents use the same translations as the Svelte components.
 *
 * Date handling: The lastUpdated date is stored in TypeScript metadata (ISO format)
 * and formatted at runtime using Intl.DateTimeFormat for the user's locale.
 * This provides a single source of truth for dates with automatic localization.
 */

import { privacyPolicyLinks } from "../config/links";
import { SURFACED_PRIVACY_PROMISES } from "./privacyPromises.generated";

/**
 * Type for translation function (compatible with svelte-i18n's _ store)
 */
export type TranslationFunction = (key: string) => string;

/**
 * Format a date string for display in the user's locale
 *
 * Uses Intl.DateTimeFormat for proper localization of date formats:
 * - English: "January 28, 2026"
 * - German: "28. Januar 2026"
 * - Chinese: "2026年1月28日"
 * - Japanese: "2026年1月28日"
 * etc.
 *
 * @param isoDate - ISO date string (e.g., "2026-01-28T00:00:00Z")
 * @param locale - The user's locale (e.g., "en", "de", "zh")
 * @returns Formatted date string for the locale
 */
export function formatDateForLocale(isoDate: string, locale: string): string {
  const date = new Date(isoDate);

  // Use Intl.DateTimeFormat for proper localization
  // Options: Show full month name, day, and year
  return new Intl.DateTimeFormat(locale, {
    year: "numeric",
    month: "long",
    day: "numeric",
  }).format(date);
}

/**
 * Options for building legal content with date formatting
 *
 * The lastUpdated date is stored in TypeScript metadata (single source of truth)
 * and formatted at runtime using Intl.DateTimeFormat for the user's locale.
 */
export interface LegalContentOptions {
  /** ISO date string for when the document was last updated (from metadata.lastUpdated) */
  lastUpdated: string;
  /** User's locale for date formatting (e.g., "en", "de", "zh") */
  locale: string;
}

/**
 * Build Privacy Policy content from translation keys.
 *
 * The structure mirrors shared/docs/privacy_policy.yml. Providers are grouped
 * by WHEN they are used (Group A-J), so a user can tell at a glance which
 * third parties they opt into by using a specific feature.
 *
 * Honest encryption posture: the server processes user content in memory
 * (for AI responses, invoices, reminders) but never writes plaintext to
 * disk. This is NOT end-to-end encryption. The i18n strings below use
 * "client-side encryption" and "in-memory-only processing" language
 * accordingly — do not reintroduce E2EE / zero-knowledge claims.
 *
 * When adding a new provider:
 *   1. Add it to shared/docs/privacy_policy.yml under the correct group
 *   2. Add its i18n keys to frontend/packages/ui/src/i18n/sources/legal/privacy.yml
 *   3. Add its URL to privacyPolicyLinks in config/links.ts
 *   4. Render it in the matching renderGroup* helper below
 *   5. Bump `lastUpdated` in legal/documents/privacy-policy.ts
 *
 * @param t - Translation function from svelte-i18n
 * @param options - Options including lastUpdated date and locale for formatting
 */
export function buildPrivacyPolicyContent(
  t: TranslationFunction,
  options: LegalContentOptions,
): string {
  const lines: string[] = [];

  // ──────────────────────────────────────────────────────────────
  // Helper: render a provider entry with a heading and privacy link
  // ──────────────────────────────────────────────────────────────
  const providerLinkLabel = t("legal.privacy.provider_link_label");
  const renderProvider = (keyBase: string, url: string) => {
    lines.push(`### ${t(`${keyBase}.heading`)}`);
    lines.push("");
    lines.push(t(`${keyBase}.description`));
    lines.push("");
    lines.push(`${providerLinkLabel}: ${url}`);
    lines.push("");
  };

  // ──────────────────────────────────────────────────────────────
  // Title + last updated
  // ──────────────────────────────────────────────────────────────
  lines.push(`# ${t("legal.privacy.title")}`);
  lines.push("");

  const formattedDate = formatDateForLocale(
    options.lastUpdated,
    options.locale,
  );
  lines.push(`*${t("legal.privacy.last_updated")}: ${formattedDate}*`);
  lines.push("");

  // ──────────────────────────────────────────────────────────────
  // Section 1 — Overview
  // ──────────────────────────────────────────────────────────────
  lines.push(`## ${t("legal.privacy.overview.heading")}`);
  lines.push("");
  lines.push(t("legal.privacy.overview.summary"));
  lines.push("");
  lines.push(t("legal.privacy.overview.website_vs_webapp"));
  lines.push("");

  // ──────────────────────────────────────────────────────────────
  // Section 2 — Privacy Promises (auto-generated from
  // shared/docs/privacy_promises.yml via SURFACED_PRIVACY_PROMISES).
  // Every promise is backed by code + tests; see
  // docs/architecture/compliance/ and the registry for the full chain of
  // enforcement.
  // ──────────────────────────────────────────────────────────────
  lines.push(`## ${t("legal.privacy.protection.heading")}`);
  lines.push("");
  lines.push(t("legal.privacy.promises.intro"));
  lines.push("");

  for (const promise of SURFACED_PRIVACY_PROMISES) {
    lines.push(`### ${t(`${promise.i18n_key}.heading`)}`);
    lines.push("");
    lines.push(t(`${promise.i18n_key}.description`));
    lines.push("");
  }

  // ──────────────────────────────────────────────────────────────
  // Section 3 — Data we collect
  // ──────────────────────────────────────────────────────────────
  lines.push(`## ${t("legal.privacy.data_categories.heading")}`);
  lines.push("");
  lines.push(t("legal.privacy.data_categories.intro"));
  lines.push("");
  lines.push(`- ${t("legal.privacy.data_categories.account")}`);
  lines.push(`- ${t("legal.privacy.data_categories.usage")}`);
  lines.push(`- ${t("legal.privacy.data_categories.content")}`);
  lines.push(`- ${t("legal.privacy.data_categories.payments")}`);
  lines.push(`- ${t("legal.privacy.data_categories.newsletter")}`);
  lines.push("");

  // ──────────────────────────────────────────────────────────────
  // Section 4 — When each provider is used (Group A-J)
  // ──────────────────────────────────────────────────────────────
  lines.push(`## ${t("legal.privacy.providers.heading")}`);
  lines.push("");
  lines.push(t("legal.privacy.providers.intro"));
  lines.push("");

  // Group A — Always active
  lines.push(`### ${t("legal.privacy.providers.always_active.heading")}`);
  lines.push("");
  lines.push(t("legal.privacy.providers.always_active.description"));
  lines.push("");
  renderProvider("legal.privacy.providers.always_active.vercel", privacyPolicyLinks.vercel);
  renderProvider("legal.privacy.providers.always_active.hetzner", privacyPolicyLinks.hetzner);
  renderProvider("legal.privacy.providers.always_active.brevo", privacyPolicyLinks.brevo);
  renderProvider("legal.privacy.providers.always_active.ip_api", privacyPolicyLinks.ipApi);
  renderProvider("legal.privacy.providers.always_active.sightengine", privacyPolicyLinks.sightengine);
  renderProvider("legal.privacy.providers.always_active.api_video", privacyPolicyLinks.apiVideo);

  // Group B — Payments
  lines.push(`### ${t("legal.privacy.providers.payments.heading")}`);
  lines.push("");
  lines.push(t("legal.privacy.providers.payments.description"));
  lines.push("");
  renderProvider("legal.privacy.providers.payments.stripe", privacyPolicyLinks.stripe);
  renderProvider("legal.privacy.providers.payments.polar", privacyPolicyLinks.polar);
  renderProvider("legal.privacy.providers.payments.revolut_business", privacyPolicyLinks.revolutBusiness);

  // Group C — AI models
  lines.push(`### ${t("legal.privacy.providers.ai_models.heading")}`);
  lines.push("");
  lines.push(t("legal.privacy.providers.ai_models.description"));
  lines.push("");
  renderProvider("legal.privacy.providers.ai_models.mistral", privacyPolicyLinks.mistral);
  renderProvider("legal.privacy.providers.ai_models.aws_bedrock", privacyPolicyLinks.aws);
  renderProvider("legal.privacy.providers.ai_models.anthropic", privacyPolicyLinks.anthropic);
  renderProvider("legal.privacy.providers.ai_models.openai", privacyPolicyLinks.openai);
  renderProvider("legal.privacy.providers.ai_models.openrouter", privacyPolicyLinks.openrouter);
  renderProvider("legal.privacy.providers.ai_models.cerebras", privacyPolicyLinks.cerebras);
  renderProvider("legal.privacy.providers.ai_models.google_gemini", privacyPolicyLinks.google);
  renderProvider("legal.privacy.providers.ai_models.google_vertex_maas", privacyPolicyLinks.googleVertexMaas);
  renderProvider("legal.privacy.providers.ai_models.together", privacyPolicyLinks.together);
  renderProvider("legal.privacy.providers.ai_models.groq", privacyPolicyLinks.groq);

  // Group D — Image generation
  lines.push(`### ${t("legal.privacy.providers.image_generation.heading")}`);
  lines.push("");
  lines.push(t("legal.privacy.providers.image_generation.description"));
  lines.push("");
  renderProvider("legal.privacy.providers.image_generation.fal", privacyPolicyLinks.fal);
  renderProvider("legal.privacy.providers.image_generation.recraft", privacyPolicyLinks.recraft);

  // Group E — Web, search, content
  lines.push(`### ${t("legal.privacy.providers.web_and_search.heading")}`);
  lines.push("");
  lines.push(t("legal.privacy.providers.web_and_search.description"));
  lines.push("");
  renderProvider("legal.privacy.providers.web_and_search.brave", privacyPolicyLinks.brave);
  renderProvider("legal.privacy.providers.web_and_search.firecrawl", privacyPolicyLinks.firecrawl);
  renderProvider("legal.privacy.providers.web_and_search.webshare", privacyPolicyLinks.webshare);
  renderProvider("legal.privacy.providers.web_and_search.google_maps", privacyPolicyLinks.googleMaps);

  // Group F — Travel
  lines.push(`### ${t("legal.privacy.providers.travel.heading")}`);
  lines.push("");
  lines.push(t("legal.privacy.providers.travel.description"));
  lines.push("");
  renderProvider("legal.privacy.providers.travel.serpapi", privacyPolicyLinks.serpapi);
  renderProvider("legal.privacy.providers.travel.flightradar24", privacyPolicyLinks.flightradar24);

  // Group G — Events
  lines.push(`### ${t("legal.privacy.providers.events.heading")}`);
  lines.push("");
  lines.push(t("legal.privacy.providers.events.description"));
  lines.push("");
  renderProvider("legal.privacy.providers.events.meetup", privacyPolicyLinks.meetup);
  renderProvider("legal.privacy.providers.events.luma", privacyPolicyLinks.luma);
  renderProvider("legal.privacy.providers.events.resident_advisor", privacyPolicyLinks.residentAdvisor);

  // Group H — Health
  lines.push(`### ${t("legal.privacy.providers.health.heading")}`);
  lines.push("");
  lines.push(t("legal.privacy.providers.health.description"));
  lines.push("");
  renderProvider("legal.privacy.providers.health.doctolib", privacyPolicyLinks.doctolib);
  renderProvider("legal.privacy.providers.health.jameda", privacyPolicyLinks.jameda);

  // Group I — Shopping
  lines.push(`### ${t("legal.privacy.providers.shopping.heading")}`);
  lines.push("");
  lines.push(t("legal.privacy.providers.shopping.description"));
  lines.push("");
  renderProvider("legal.privacy.providers.shopping.rewe", privacyPolicyLinks.rewe);
  renderProvider("legal.privacy.providers.shopping.amazon", privacyPolicyLinks.amazon);

  // Group J — Community
  lines.push(`### ${t("legal.privacy.providers.community.heading")}`);
  lines.push("");
  lines.push(t("legal.privacy.providers.community.description"));
  lines.push("");
  renderProvider("legal.privacy.providers.community.discord", privacyPolicyLinks.discord);
  lines.push(t("legal.privacy.providers.community.discord.admin_access"));
  lines.push("");

  // ──────────────────────────────────────────────────────────────
  // Section 5 — Device fingerprinting (security measure)
  // ──────────────────────────────────────────────────────────────
  lines.push(`## ${t("legal.privacy.security_measures.heading")}`);
  lines.push("");
  lines.push(t("legal.privacy.security_measures.intro"));
  lines.push("");
  lines.push(
    `### ${t("legal.privacy.security_measures.device_fingerprinting.subheading")}`,
  );
  lines.push("");
  lines.push(t("legal.privacy.security_measures.device_fingerprinting.purpose"));
  lines.push("");
  lines.push(t("legal.privacy.security_measures.device_fingerprinting.storage"));
  lines.push("");
  lines.push(t("legal.privacy.security_measures.device_fingerprinting.ip_logging"));
  lines.push("");

  // ──────────────────────────────────────────────────────────────
  // Section 6 — Data retention
  // ──────────────────────────────────────────────────────────────
  lines.push(`## ${t("legal.privacy.data_retention.heading")}`);
  lines.push("");
  lines.push(`- ${t("legal.privacy.data_retention.account")}`);
  lines.push(`- ${t("legal.privacy.data_retention.usage_and_logs")}`);
  lines.push(`- ${t("legal.privacy.data_retention.device_fingerprints")}`);
  lines.push(`- ${t("legal.privacy.data_retention.content")}`);
  lines.push(`- ${t("legal.privacy.data_retention.payments_and_invoices")}`);
  lines.push(`- ${t("legal.privacy.data_retention.compliance_logs")}`);
  lines.push(`- ${t("legal.privacy.data_retention.observability_traces")}`);
  lines.push(`- ${t("legal.privacy.data_retention.user_data_backups")}`);
  lines.push("");

  // ──────────────────────────────────────────────────────────────
  // Section 7 — Limitations of erasure
  // ──────────────────────────────────────────────────────────────
  lines.push(`## ${t("legal.privacy.limitations_of_erasure.heading")}`);
  lines.push("");
  lines.push(t("legal.privacy.limitations_of_erasure.intro"));
  lines.push("");
  const limitationItems = [
    "financial_records",
    "audit_logs",
    "third_party_ai_logs",
    "observability_traces",
    "user_data_backups",
  ];
  for (const item of limitationItems) {
    lines.push(`### ${t(`legal.privacy.limitations_of_erasure.${item}.heading`)}`);
    lines.push("");
    lines.push(t(`legal.privacy.limitations_of_erasure.${item}.description`));
    lines.push("");
  }

  // ──────────────────────────────────────────────────────────────
  // Section 8 — Legal basis
  // ──────────────────────────────────────────────────────────────
  lines.push(`## ${t("legal.privacy.legal_basis.heading")}`);
  lines.push("");
  lines.push(`- ${t("legal.privacy.legal_basis.contract")}`);
  lines.push(`- ${t("legal.privacy.legal_basis.consent")}`);
  lines.push(`- ${t("legal.privacy.legal_basis.legitimate_interests")}`);
  lines.push(`- ${t("legal.privacy.legal_basis.legal_obligation")}`);
  lines.push("");

  // ──────────────────────────────────────────────────────────────
  // Section 9 — Your rights
  // ──────────────────────────────────────────────────────────────
  lines.push(`## ${t("legal.privacy.legal_rights.heading")}`);
  lines.push("");
  lines.push(t("legal.privacy.legal_rights.intro"));
  lines.push("");

  lines.push(`### ${t("legal.privacy.legal_rights.gdpr.subheading")}`);
  lines.push("");
  lines.push(`- ${t("legal.privacy.legal_rights.gdpr.access")}`);
  lines.push(`- ${t("legal.privacy.legal_rights.gdpr.rectification")}`);
  lines.push(`- ${t("legal.privacy.legal_rights.gdpr.erasure")}`);
  lines.push(`- ${t("legal.privacy.legal_rights.gdpr.portability")}`);
  lines.push(`- ${t("legal.privacy.legal_rights.gdpr.withdraw_consent")}`);
  lines.push("");
  lines.push(t("legal.privacy.legal_rights.gdpr.manual_note"));
  lines.push("");
  lines.push(`- ${t("legal.privacy.legal_rights.gdpr.restriction")}`);
  lines.push(`- ${t("legal.privacy.legal_rights.gdpr.objection")}`);
  lines.push("");
  lines.push(t("legal.privacy.legal_rights.gdpr.exercise"));
  lines.push("");

  lines.push(`### ${t("legal.privacy.legal_rights.ccpa_cpra.subheading")}`);
  lines.push("");
  lines.push(`- ${t("legal.privacy.legal_rights.ccpa_cpra.right_to_know")}`);
  lines.push(`- ${t("legal.privacy.legal_rights.ccpa_cpra.right_to_delete")}`);
  lines.push(`- ${t("legal.privacy.legal_rights.ccpa_cpra.right_to_correct")}`);
  lines.push(
    `- ${t("legal.privacy.legal_rights.ccpa_cpra.right_to_opt_out_of_sale_or_sharing")}`,
  );
  lines.push(
    `- ${t("legal.privacy.legal_rights.ccpa_cpra.right_to_non_discrimination")}`,
  );
  lines.push("");
  lines.push(t("legal.privacy.legal_rights.ccpa_cpra.exercise"));
  lines.push("");

  // ──────────────────────────────────────────────────────────────
  // Section 10 — Contact
  // ──────────────────────────────────────────────────────────────
  lines.push(`## ${t("legal.privacy.contact.heading")}`);
  lines.push("");
  lines.push(t("legal.privacy.contact.questions"));
  lines.push("");
  lines.push(`${t("legal.privacy.contact.email")}: contact@openmates.org`);
  lines.push("");
  lines.push(t("legal.privacy.contact.postal"));
  lines.push("");
  lines.push(t("legal.privacy.contact.controller"));
  lines.push("");

  return lines.join("\n");
}

/**
 * Build Terms of Use content from translation keys
 *
 * @param t - Translation function from svelte-i18n
 * @param options - Options including lastUpdated date and locale for formatting
 */
export function buildTermsOfUseContent(
  t: TranslationFunction,
  options: LegalContentOptions,
): string {
  const lines: string[] = [];

  // Title
  lines.push(`# ${t("legal.terms.title")}`);
  lines.push("");

  // Last updated - format date using Intl.DateTimeFormat for the user's locale
  // The date comes from TypeScript metadata (single source of truth)
  const formattedDate = formatDateForLocale(
    options.lastUpdated,
    options.locale,
  );
  lines.push(`*${t("legal.terms.last_updated")}: ${formattedDate}*`);
  lines.push("");

  // Section 1: Agreement
  lines.push(`## 1. ${t("legal.terms.agreement.heading")}`);
  lines.push("");
  lines.push(t("legal.terms.agreement.description"));
  lines.push("");

  // Section 2: About
  lines.push(`## 2. ${t("legal.terms.about.heading")}`);
  lines.push("");
  lines.push(t("legal.terms.about.description"));
  lines.push("");

  // Section 3: Intellectual Property
  lines.push(`## 3. ${t("legal.terms.intellectual_property.heading")}`);
  lines.push("");
  lines.push(t("legal.terms.intellectual_property.description"));
  lines.push("");

  // Section 4: Use License
  lines.push(`## 4. ${t("legal.terms.use_license.heading")}`);
  lines.push("");
  lines.push(t("legal.terms.use_license.description"));
  lines.push("");

  // Prohibited Uses of OpenMates Service
  lines.push(
    `### ${t("legal.terms.use_license.restrictions.service_use.heading")}`,
  );
  lines.push("");
  lines.push(t("legal.terms.use_license.restrictions.service_use.description"));
  lines.push("");
  lines.push(
    "- " + t("legal.terms.use_license.restrictions.service_use.military"),
  );
  lines.push(
    "- " + t("legal.terms.use_license.restrictions.service_use.gambling"),
  );
  lines.push(
    "- " + t("legal.terms.use_license.restrictions.service_use.misinformation"),
  );
  lines.push(
    "- " + t("legal.terms.use_license.restrictions.service_use.scams"),
  );
  lines.push(
    "- " + t("legal.terms.use_license.restrictions.service_use.illegal"),
  );
  lines.push("");

  // Section 5: AI Accuracy and Data Sharing
  lines.push(`## 5. ${t("legal.terms.ai_accuracy.heading")}`);
  lines.push("");
  lines.push(t("legal.terms.ai_accuracy.description"));
  lines.push("");
  lines.push(`### ${t("legal.terms.ai_accuracy_data_sharing_heading")}`);
  lines.push("");
  lines.push(t("legal.terms.ai_accuracy_data_sharing_text"));
  lines.push("");

  // Section 6: Credits and Payments
  lines.push(`## 6. ${t("legal.terms.credits.heading")}`);
  lines.push("");
  lines.push(t("legal.terms.credits.description"));
  lines.push("");
  lines.push(t("legal.terms.credits.refund"));
  lines.push("");

  // Section 7: Disclaimer
  lines.push(`## 7. ${t("legal.terms.disclaimer.heading")}`);
  lines.push("");
  lines.push(t("legal.terms.disclaimer.description"));
  lines.push("");

  // Section 8: Limitations
  lines.push(`## 8. ${t("legal.terms.limitations.heading")}`);
  lines.push("");
  lines.push(t("legal.terms.limitations.description"));
  lines.push("");
  lines.push("- " + t("legal.terms.limitations.list.website_use"));
  lines.push("- " + t("legal.terms.limitations.list.ai_responses"));
  lines.push("- " + t("legal.terms.limitations.list.information"));
  lines.push("- " + t("legal.terms.limitations.list.technical"));
  lines.push("- " + t("legal.terms.limitations.list.data_loss"));
  lines.push("");

  // Section 9: Service Availability
  lines.push(`## 9. ${t("legal.terms.service_availability.heading")}`);
  lines.push("");
  lines.push(t("legal.terms.service_availability.description"));
  lines.push("");

  // Section 10: Encryption Keys and Account Recovery
  lines.push(`## 10. ${t("legal.terms.encryption_keys.heading")}`);
  lines.push("");
  lines.push(t("legal.terms.encryption_keys.description"));
  lines.push("");

  // Section 11: Governing Law
  lines.push(`## 11. ${t("legal.terms.governing_law.heading")}`);
  lines.push("");
  lines.push(t("legal.terms.governing_law.explanation"));
  lines.push("");

  // Section 12: Contact
  lines.push(`## 12. ${t("legal.terms.contact.heading")}`);
  lines.push("");
  lines.push(t("legal.terms.contact.intro"));
  lines.push("");
  lines.push(`${t("legal.terms.contact.email_label")}: contact@openmates.org`);
  lines.push("");

  return lines.join("\n");
}

/**
 * Build Imprint content from translation keys
 * Note: Imprint uses SVG images for contact info, which are displayed below
 * Imprint doesn't have a last updated date as it's primarily contact info
 */
export function buildImprintContent(t: TranslationFunction): string {
  const lines: string[] = [];

  // Title
  lines.push(`# ${t("legal.imprint.title")}`);
  lines.push("");

  // Section: Information according to TMG
  lines.push(`## ${t("legal.imprint.information_tmg")}`);
  lines.push("");
  // Display SVG images with contact information
  // Images are in static/images/legal/ folder (1.svg, 2.svg, 3.svg, 4.svg)
  lines.push("![Contact information 1](/images/legal/1.svg)");
  lines.push("");
  lines.push("![Contact information 2](/images/legal/2.svg)");
  lines.push("");
  lines.push("![Contact information 3](/images/legal/3.svg)");
  lines.push("");
  lines.push("![Contact information 4](/images/legal/4.svg)");
  lines.push("");

  // Section: Contact
  lines.push(`## ${t("legal.imprint.contact")}`);
  lines.push("");
  lines.push(`${t("legal.imprint.email")}: contact@openmates.org`);
  lines.push("");

  return lines.join("\n");
}
