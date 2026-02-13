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

import { privacyPolicyLinks } from '../config/links';

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
		year: 'numeric',
		month: 'long',
		day: 'numeric'
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
 * Build Privacy Policy content from translation keys
 * 
 * @param t - Translation function from svelte-i18n
 * @param options - Options including lastUpdated date and locale for formatting
 */
export function buildPrivacyPolicyContent(t: TranslationFunction, options: LegalContentOptions): string {
	const lines: string[] = [];

	// Title
	lines.push(`# ${t('legal.privacy.title')}`);
	lines.push('');
	
	// Last updated - format date using Intl.DateTimeFormat for the user's locale
	// The date comes from TypeScript metadata (single source of truth)
	const formattedDate = formatDateForLocale(options.lastUpdated, options.locale);
	lines.push(`*${t('legal.privacy.last_updated')}: ${formattedDate}*`);
	lines.push('');

	// Section 1: Data Protection Overview
	lines.push(`## ${t('legal.privacy.data_protection.heading')}`);
	lines.push('');
	lines.push(t('legal.privacy.data_protection.overview'));
	lines.push('');
	lines.push(t('legal.privacy.data_protection.website_vs_webapp'));
	lines.push('');

	// Section 2: Vercel
	lines.push(`## ${t('legal.privacy.vercel.heading')}`);
	lines.push('');
	lines.push(t('legal.privacy.vercel.description'));
	lines.push('');
	lines.push(`${t('legal.privacy.vercel.privacy_policy_link')}: ${privacyPolicyLinks.vercel}`);
	lines.push('');

	// Section 3: Web Application Services
	lines.push(`## ${t('legal.privacy.webapp_services.heading')}`);
	lines.push('');
	lines.push(t('legal.privacy.webapp_services.intro'));
	lines.push('');

	// Section 3.1: Hetzner
	lines.push(`### ${t('legal.privacy.hetzner.heading')}`);
	lines.push('');
	lines.push(t('legal.privacy.hetzner.description'));
	lines.push('');
	lines.push(`${t('legal.privacy.hetzner.privacy_policy_link')}: ${privacyPolicyLinks.hetzner}`);
	lines.push('');

	// Section 3.2: IP-API
	lines.push(`### ${t('legal.privacy.ip_api.heading')}`);
	lines.push('');
	lines.push(t('legal.privacy.ip_api.description'));
	lines.push('');
	lines.push(`${t('legal.privacy.ip_api.privacy_policy_link')}: ${privacyPolicyLinks.ipApi}`);
	lines.push('');

	// Section 3.3: Brevo
	lines.push(`### ${t('legal.privacy.brevo.heading')}`);
	lines.push('');
	lines.push(t('legal.privacy.brevo.description'));
	lines.push('');
	lines.push(`${t('legal.privacy.brevo.privacy_policy_link')}: ${privacyPolicyLinks.brevo}`);
	lines.push('');

	// Section 3.4: Sightengine
	lines.push(`### ${t('legal.privacy.sightengine.heading')}`);
	lines.push('');
	lines.push(t('legal.privacy.sightengine.description'));
	lines.push('');
	lines.push(`${t('legal.privacy.sightengine.privacy_policy_link')}: ${privacyPolicyLinks.sightengine}`);
	lines.push('');

	// Section 3.5: Stripe
	lines.push(`### ${t('legal.privacy.stripe.heading')}`);
	lines.push('');
	lines.push(t('legal.privacy.stripe.description'));
	lines.push('');
	lines.push(`${t('legal.privacy.stripe.privacy_policy_link')}: ${privacyPolicyLinks.stripe}`);
	lines.push('');

	// Section 3.6: Mistral
	lines.push(`### ${t('legal.privacy.mistral.heading')}`);
	lines.push('');
	lines.push(t('legal.privacy.mistral.description'));
	lines.push('');
	lines.push(`${t('legal.privacy.mistral.privacy_policy_link')}: ${privacyPolicyLinks.mistral}`);
	lines.push('');

	// Section 3.7: AWS
	lines.push(`### ${t('legal.privacy.aws.heading')}`);
	lines.push('');
	lines.push(t('legal.privacy.aws.description'));
	lines.push('');
	lines.push(`${t('legal.privacy.aws.privacy_policy_link')}: ${privacyPolicyLinks.aws}`);
	lines.push('');

	// Section 3.8: OpenRouter
	lines.push(`### ${t('legal.privacy.openrouter.heading')}`);
	lines.push('');
	lines.push(t('legal.privacy.openrouter.description'));
	lines.push('');
	lines.push(`${t('legal.privacy.openrouter.privacy_policy_link')}: ${privacyPolicyLinks.openrouter}`);
	lines.push('');

	// Section 3.9: Cerebras
	lines.push(`### ${t('legal.privacy.cerebras.heading')}`);
	lines.push('');
	lines.push(t('legal.privacy.cerebras.description'));
	lines.push('');
	lines.push(`${t('legal.privacy.cerebras.privacy_policy_link')}: ${privacyPolicyLinks.cerebras}`);
	lines.push('');

	// Section 3.10: Brave Search
	lines.push(`### ${t('legal.privacy.brave.heading')}`);
	lines.push('');
	lines.push(t('legal.privacy.brave.description'));
	lines.push('');
	lines.push(`${t('legal.privacy.brave.privacy_policy_link')}: ${privacyPolicyLinks.brave}`);
	lines.push('');

	// Section 3.11: Webshare
	lines.push(`### ${t('legal.privacy.webshare.heading')}`);
	lines.push('');
	lines.push(t('legal.privacy.webshare.description'));
	lines.push('');
	lines.push(`${t('legal.privacy.webshare.privacy_policy_link')}: ${privacyPolicyLinks.webshare}`);
	lines.push('');

	// Section 3.12: Google
	lines.push(`### ${t('legal.privacy.google.heading')}`);
	lines.push('');
	lines.push(t('legal.privacy.google.description'));
	lines.push('');
	lines.push(`${t('legal.privacy.google.privacy_policy_link')}: ${privacyPolicyLinks.google}`);
	lines.push('');

	// Section 3.13: Firecrawl
	lines.push(`### ${t('legal.privacy.firecrawl.heading')}`);
	lines.push('');
	lines.push(t('legal.privacy.firecrawl.description'));
	lines.push('');
	lines.push(`${t('legal.privacy.firecrawl.privacy_policy_link')}: ${privacyPolicyLinks.firecrawl}`);
	lines.push('');

	// Section 3.14: Groq
	lines.push(`### ${t('legal.privacy.groq.heading')}`);
	lines.push('');
	lines.push(t('legal.privacy.groq.description'));
	lines.push('');
	lines.push(`${t('legal.privacy.groq.privacy_policy_link')}: ${privacyPolicyLinks.groq}`);
	lines.push('');

	// Section 4: Security Measures
	lines.push(`## ${t('legal.privacy.security_measures.heading')}`);
	lines.push('');
	lines.push(t('legal.privacy.security_measures.intro'));
	lines.push('');
	
	lines.push(`### ${t('legal.privacy.security_measures.device_fingerprinting.subheading')}`);
	lines.push('');
	lines.push(t('legal.privacy.security_measures.device_fingerprinting.purpose'));
	lines.push('');
	lines.push(t('legal.privacy.security_measures.device_fingerprinting.storage'));
	lines.push('');
	lines.push(t('legal.privacy.security_measures.device_fingerprinting.ip_logging'));
	lines.push('');

	// Section 5: Data Categories
	lines.push(`## ${t('legal.privacy.data_categories.heading')}`);
	lines.push('');
	lines.push(t('legal.privacy.data_categories.intro'));
	lines.push('');
	lines.push(`- ${t('legal.privacy.data_categories.account')}`);
	lines.push(`- ${t('legal.privacy.data_categories.usage')}`);
	lines.push(`- ${t('legal.privacy.data_categories.content')}`);
	lines.push(`- ${t('legal.privacy.data_categories.payments')}`);
	lines.push(`- ${t('legal.privacy.data_categories.newsletter')}`);
	lines.push('');

	// Section 6: Data Retention
	lines.push(`## ${t('legal.privacy.data_retention.heading')}`);
	lines.push('');
	lines.push(`- ${t('legal.privacy.data_retention.account')}`);
	lines.push(`- ${t('legal.privacy.data_retention.usage_and_logs')}`);
	lines.push(`- ${t('legal.privacy.data_retention.device_fingerprints')}`);
	lines.push(`- ${t('legal.privacy.data_retention.content')}`);
	lines.push(`- ${t('legal.privacy.data_retention.payments_and_invoices')}`);
	lines.push('');

	// Section 7: Legal Basis
	lines.push(`## ${t('legal.privacy.legal_basis.heading')}`);
	lines.push('');
	lines.push(`- ${t('legal.privacy.legal_basis.contract')}`);
	lines.push(`- ${t('legal.privacy.legal_basis.consent')}`);
	lines.push(`- ${t('legal.privacy.legal_basis.legitimate_interests')}`);
	lines.push(`- ${t('legal.privacy.legal_basis.legal_obligation')}`);
	lines.push('');

	// Section 8: Legal Rights
	lines.push(`## ${t('legal.privacy.legal_rights.heading')}`);
	lines.push('');
	lines.push(t('legal.privacy.legal_rights.intro'));
	lines.push('');
	
	lines.push(`### ${t('legal.privacy.legal_rights.gdpr.subheading')}`);
	lines.push('');
	lines.push(`- ${t('legal.privacy.legal_rights.gdpr.access')}`);
	lines.push(`- ${t('legal.privacy.legal_rights.gdpr.rectification')}`);
	lines.push(`- ${t('legal.privacy.legal_rights.gdpr.erasure')}`);
	lines.push(`- ${t('legal.privacy.legal_rights.gdpr.restriction')}`);
	lines.push(`- ${t('legal.privacy.legal_rights.gdpr.portability')}`);
	lines.push(`- ${t('legal.privacy.legal_rights.gdpr.objection')}`);
	lines.push(`- ${t('legal.privacy.legal_rights.gdpr.withdraw_consent')}`);
	lines.push('');
	lines.push(t('legal.privacy.legal_rights.gdpr.exercise'));
	lines.push('');

	lines.push(`### ${t('legal.privacy.legal_rights.ccpa_cpra.subheading')}`);
	lines.push('');
	lines.push(`- ${t('legal.privacy.legal_rights.ccpa_cpra.right_to_know')}`);
	lines.push(`- ${t('legal.privacy.legal_rights.ccpa_cpra.right_to_delete')}`);
	lines.push(`- ${t('legal.privacy.legal_rights.ccpa_cpra.right_to_correct')}`);
	lines.push(`- ${t('legal.privacy.legal_rights.ccpa_cpra.right_to_opt_out_of_sale_or_sharing')}`);
	lines.push(`- ${t('legal.privacy.legal_rights.ccpa_cpra.right_to_non_discrimination')}`);
	lines.push('');
	lines.push(t('legal.privacy.legal_rights.ccpa_cpra.exercise'));
	lines.push('');

	// Section 9: Discord Integration
	lines.push(`## ${t('legal.privacy.discord_integration.heading')}`);
	lines.push('');
	lines.push(t('legal.privacy.discord_integration.description'));
	lines.push('');
	lines.push(t('legal.privacy.discord_integration.admin_access'));
	lines.push('');
	lines.push(`${t('legal.privacy.discord_integration.privacy_policy_link')}: ${privacyPolicyLinks.discord}`);
	lines.push('');

	// Section 10: Contact
	lines.push(`## ${t('legal.privacy.contact.heading')}`);
	lines.push('');
	lines.push(t('legal.privacy.contact.questions'));
	lines.push('');
	// Email and postal info are handled separately in the Svelte component, but we include email here
	lines.push(`${t('legal.privacy.contact.email')}: contact@openmates.org`);
	lines.push('');
	lines.push(t('legal.privacy.contact.postal'));
	lines.push('');
	lines.push(t('legal.privacy.contact.controller'));
	lines.push('');

	return lines.join('\n');
}

/**
 * Build Terms of Use content from translation keys
 * 
 * @param t - Translation function from svelte-i18n
 * @param options - Options including lastUpdated date and locale for formatting
 */
export function buildTermsOfUseContent(t: TranslationFunction, options: LegalContentOptions): string {
	const lines: string[] = [];

	// Title
	lines.push(`# ${t('legal.terms.title')}`);
	lines.push('');

	// Last updated - format date using Intl.DateTimeFormat for the user's locale
	// The date comes from TypeScript metadata (single source of truth)
	const formattedDate = formatDateForLocale(options.lastUpdated, options.locale);
	lines.push(`*${t('legal.terms.last_updated')}: ${formattedDate}*`);
	lines.push('');

	// Section 1: Agreement
	lines.push(`## 1. ${t('legal.terms.agreement.heading')}`);
	lines.push('');
	lines.push(t('legal.terms.agreement.description'));
	lines.push('');

	// Section 2: About
	lines.push(`## 2. ${t('legal.terms.about.heading')}`);
	lines.push('');
	lines.push(t('legal.terms.about.description'));
	lines.push('');

	// Section 3: Intellectual Property
	lines.push(`## 3. ${t('legal.terms.intellectual_property.heading')}`);
	lines.push('');
	lines.push(t('legal.terms.intellectual_property.description'));
	lines.push('');

	// Section 4: Use License
	lines.push(`## 4. ${t('legal.terms.use_license.heading')}`);
	lines.push('');
	lines.push(t('legal.terms.use_license.description'));
	lines.push('');
	
	// Prohibited Uses of OpenMates Service
	lines.push(`### ${t('legal.terms.use_license.restrictions.service_use.heading')}`);
	lines.push('');
	lines.push(t('legal.terms.use_license.restrictions.service_use.description'));
	lines.push('');
	lines.push('- ' + t('legal.terms.use_license.restrictions.service_use.military'));
	lines.push('- ' + t('legal.terms.use_license.restrictions.service_use.gambling'));
	lines.push('- ' + t('legal.terms.use_license.restrictions.service_use.misinformation'));
	lines.push('- ' + t('legal.terms.use_license.restrictions.service_use.scams'));
	lines.push('- ' + t('legal.terms.use_license.restrictions.service_use.illegal'));
	lines.push('');

	// Section 5: AI Accuracy and Data Sharing
	lines.push(`## 5. ${t('legal.terms.ai_accuracy.heading')}`);
	lines.push('');
	lines.push(t('legal.terms.ai_accuracy.description'));
	lines.push('');
	lines.push(`### ${t('legal.terms.ai_accuracy_data_sharing_heading')}`);
	lines.push('');
	lines.push(t('legal.terms.ai_accuracy_data_sharing_text'));
	lines.push('');

	// Section 6: Credits and Payments
	lines.push(`## 6. ${t('legal.terms.credits.heading')}`);
	lines.push('');
	lines.push(t('legal.terms.credits.description'));
	lines.push('');
	lines.push(t('legal.terms.credits.refund'));
	lines.push('');

	// Section 7: Disclaimer
	lines.push(`## 7. ${t('legal.terms.disclaimer.heading')}`);
	lines.push('');
	lines.push(t('legal.terms.disclaimer.description'));
	lines.push('');

	// Section 8: Limitations
	lines.push(`## 8. ${t('legal.terms.limitations.heading')}`);
	lines.push('');
	lines.push(t('legal.terms.limitations.description'));
	lines.push('');
	lines.push('- ' + t('legal.terms.limitations.list.website_use'));
	lines.push('- ' + t('legal.terms.limitations.list.ai_responses'));
	lines.push('- ' + t('legal.terms.limitations.list.information'));
	lines.push('- ' + t('legal.terms.limitations.list.technical'));
	lines.push('- ' + t('legal.terms.limitations.list.data_loss'));
	lines.push('');

	// Section 9: Service Availability
	lines.push(`## 9. ${t('legal.terms.service_availability.heading')}`);
	lines.push('');
	lines.push(t('legal.terms.service_availability.description'));
	lines.push('');

	// Section 10: Encryption Keys and Account Recovery
	lines.push(`## 10. ${t('legal.terms.encryption_keys.heading')}`);
	lines.push('');
	lines.push(t('legal.terms.encryption_keys.description'));
	lines.push('');

	// Section 11: Governing Law
	lines.push(`## 11. ${t('legal.terms.governing_law.heading')}`);
	lines.push('');
	lines.push(t('legal.terms.governing_law.explanation'));
	lines.push('');

	// Section 12: Contact
	lines.push(`## 12. ${t('legal.terms.contact.heading')}`);
	lines.push('');
	lines.push(t('legal.terms.contact.intro'));
	lines.push('');
	lines.push(`${t('legal.terms.contact.email_label')}: contact@openmates.org`);
	lines.push('');

	return lines.join('\n');
}

/**
 * Build Imprint content from translation keys
 * Note: Imprint uses SVG images for contact info, which are displayed below
 * Imprint doesn't have a last updated date as it's primarily contact info
 */
export function buildImprintContent(t: TranslationFunction): string {
	const lines: string[] = [];

	// Title
	lines.push(`# ${t('legal.imprint.title')}`);
	lines.push('');

	// Section: Information according to TMG
	lines.push(`## ${t('legal.imprint.information_tmg')}`);
	lines.push('');
	// Display SVG images with contact information
	// Images are in static/images/legal/ folder (1.svg, 2.svg, 3.svg, 4.svg)
	lines.push('![Contact information 1](/images/legal/1.svg)');
	lines.push('');
	lines.push('![Contact information 2](/images/legal/2.svg)');
	lines.push('');
	lines.push('![Contact information 3](/images/legal/3.svg)');
	lines.push('');
	lines.push('![Contact information 4](/images/legal/4.svg)');
	lines.push('');

	// Section: Contact
	lines.push(`## ${t('legal.imprint.contact')}`);
	lines.push('');
	lines.push(`${t('legal.imprint.email')}: contact@openmates.org`);
	lines.push('');

	return lines.join('\n');
}
