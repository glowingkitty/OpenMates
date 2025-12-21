/**
 * Build legal document content from translation keys
 * 
 * These functions construct markdown content from i18n translation keys
 * to ensure legal documents use the same translations as the Svelte components.
 */

/**
 * Type for translation function (compatible with svelte-i18n's _ store)
 */
export type TranslationFunction = (key: string) => string;

/**
 * Build Privacy Policy content from translation keys
 */
export function buildPrivacyPolicyContent(t: TranslationFunction): string {
	const lines: string[] = [];

	// Title
	lines.push(`# ${t('legal.privacy.title.text')}`);
	lines.push('');
	
	// Last updated - use fixed date from translation keys
	lines.push(`*${t('legal.privacy.last_updated.text')}: ${t('legal.privacy.last_updated_date.text')}*`);
	lines.push('');

	// Section 1: Data Protection Overview
	lines.push(`## ${t('legal.privacy.data_protection.heading.text')}`);
	lines.push('');
	lines.push(t('legal.privacy.data_protection.overview.text'));
	lines.push('');
	lines.push(t('legal.privacy.data_protection.website_vs_webapp.text'));
	lines.push('');

	// Section 2: Vercel
	lines.push(`## ${t('legal.privacy.vercel.heading.text')}`);
	lines.push('');
	lines.push(t('legal.privacy.vercel.description.text'));
	lines.push('');

	// Section 3: Web Application Services
	lines.push(`## ${t('legal.privacy.webapp_services.heading.text')}`);
	lines.push('');
	lines.push(t('legal.privacy.webapp_services.intro.text'));
	lines.push('');

	// Section 3.1: Hetzner
	lines.push(`### ${t('legal.privacy.hetzner.heading.text')}`);
	lines.push('');
	lines.push(t('legal.privacy.hetzner.description.text'));
	lines.push('');

	// Section 3.2: IP-API
	lines.push(`### ${t('legal.privacy.ip_api.heading.text')}`);
	lines.push('');
	lines.push(t('legal.privacy.ip_api.description.text'));
	lines.push('');

	// Section 3.3: Mailjet
	lines.push(`### ${t('legal.privacy.mailjet.heading.text')}`);
	lines.push('');
	lines.push(t('legal.privacy.mailjet.description.text'));
	lines.push('');

	// Section 3.4: Sightengine
	lines.push(`### ${t('legal.privacy.sightengine.heading.text')}`);
	lines.push('');
	lines.push(t('legal.privacy.sightengine.description.text'));
	lines.push('');

	// Section 3.5: Stripe
	lines.push(`### ${t('legal.privacy.stripe.heading.text')}`);
	lines.push('');
	lines.push(t('legal.privacy.stripe.description.text'));
	lines.push('');

	// Section 3.6: Mistral
	lines.push(`### ${t('legal.privacy.mistral.heading.text')}`);
	lines.push('');
	lines.push(t('legal.privacy.mistral.description.text'));
	lines.push('');

	// Section 3.7: AWS
	lines.push(`### ${t('legal.privacy.aws.heading.text')}`);
	lines.push('');
	lines.push(t('legal.privacy.aws.description.text'));
	lines.push('');

	// Section 3.8: OpenRouter
	lines.push(`### ${t('legal.privacy.openrouter.heading.text')}`);
	lines.push('');
	lines.push(t('legal.privacy.openrouter.description.text'));
	lines.push('');

	// Section 3.9: Cerebras
	lines.push(`### ${t('legal.privacy.cerebras.heading.text')}`);
	lines.push('');
	lines.push(t('legal.privacy.cerebras.description.text'));
	lines.push('');

	// Section 3.10: Brave Search
	lines.push(`### ${t('legal.privacy.brave.heading.text')}`);
	lines.push('');
	lines.push(t('legal.privacy.brave.description.text'));
	lines.push('');

	// Section 3.11: Webshare
	lines.push(`### ${t('legal.privacy.webshare.heading.text')}`);
	lines.push('');
	lines.push(t('legal.privacy.webshare.description.text'));
	lines.push('');

	// Section 3.12: Google
	lines.push(`### ${t('legal.privacy.google.heading.text')}`);
	lines.push('');
	lines.push(t('legal.privacy.google.description.text'));
	lines.push('');

	// Section 3.13: Firecrawl
	lines.push(`### ${t('legal.privacy.firecrawl.heading.text')}`);
	lines.push('');
	lines.push(t('legal.privacy.firecrawl.description.text'));
	lines.push('');

	// Section 3.14: Groq
	lines.push(`### ${t('legal.privacy.groq.heading.text')}`);
	lines.push('');
	lines.push(t('legal.privacy.groq.description.text'));
	lines.push('');

	// Section 4: Security Measures
	lines.push(`## ${t('legal.privacy.security_measures.heading.text')}`);
	lines.push('');
	lines.push(t('legal.privacy.security_measures.intro.text'));
	lines.push('');
	
	lines.push(`### ${t('legal.privacy.security_measures.device_fingerprinting.subheading.text')}`);
	lines.push('');
	lines.push(t('legal.privacy.security_measures.device_fingerprinting.purpose.text'));
	lines.push('');
	lines.push(t('legal.privacy.security_measures.device_fingerprinting.storage.text'));
	lines.push('');
	lines.push(t('legal.privacy.security_measures.device_fingerprinting.ip_logging.text'));
	lines.push('');

	// Section 5: Data Categories
	lines.push(`## ${t('legal.privacy.data_categories.heading.text')}`);
	lines.push('');
	lines.push(t('legal.privacy.data_categories.intro.text'));
	lines.push('');
	lines.push(`- ${t('legal.privacy.data_categories.account.text')}`);
	lines.push(`- ${t('legal.privacy.data_categories.usage.text')}`);
	lines.push(`- ${t('legal.privacy.data_categories.content.text')}`);
	lines.push(`- ${t('legal.privacy.data_categories.payments.text')}`);
	lines.push(`- ${t('legal.privacy.data_categories.newsletter.text')}`);
	lines.push('');

	// Section 6: Data Retention
	lines.push(`## ${t('legal.privacy.data_retention.heading.text')}`);
	lines.push('');
	lines.push(`- ${t('legal.privacy.data_retention.account.text')}`);
	lines.push(`- ${t('legal.privacy.data_retention.usage_and_logs.text')}`);
	lines.push(`- ${t('legal.privacy.data_retention.device_fingerprints.text')}`);
	lines.push(`- ${t('legal.privacy.data_retention.content.text')}`);
	lines.push(`- ${t('legal.privacy.data_retention.payments_and_invoices.text')}`);
	lines.push('');

	// Section 7: Legal Basis
	lines.push(`## ${t('legal.privacy.legal_basis.heading.text')}`);
	lines.push('');
	lines.push(`- ${t('legal.privacy.legal_basis.contract.text')}`);
	lines.push(`- ${t('legal.privacy.legal_basis.consent.text')}`);
	lines.push(`- ${t('legal.privacy.legal_basis.legitimate_interests.text')}`);
	lines.push(`- ${t('legal.privacy.legal_basis.legal_obligation.text')}`);
	lines.push('');

	// Section 8: Legal Rights
	lines.push(`## ${t('legal.privacy.legal_rights.heading.text')}`);
	lines.push('');
	lines.push(t('legal.privacy.legal_rights.intro.text'));
	lines.push('');
	
	lines.push(`### ${t('legal.privacy.legal_rights.gdpr.subheading.text')}`);
	lines.push('');
	lines.push(`- ${t('legal.privacy.legal_rights.gdpr.access.text')}`);
	lines.push(`- ${t('legal.privacy.legal_rights.gdpr.rectification.text')}`);
	lines.push(`- ${t('legal.privacy.legal_rights.gdpr.erasure.text')}`);
	lines.push(`- ${t('legal.privacy.legal_rights.gdpr.restriction.text')}`);
	lines.push(`- ${t('legal.privacy.legal_rights.gdpr.portability.text')}`);
	lines.push(`- ${t('legal.privacy.legal_rights.gdpr.objection.text')}`);
	lines.push(`- ${t('legal.privacy.legal_rights.gdpr.withdraw_consent.text')}`);
	lines.push('');
	lines.push(t('legal.privacy.legal_rights.gdpr.exercise.text'));
	lines.push('');

	lines.push(`### ${t('legal.privacy.legal_rights.ccpa_cpra.subheading.text')}`);
	lines.push('');
	lines.push(`- ${t('legal.privacy.legal_rights.ccpa_cpra.right_to_know.text')}`);
	lines.push(`- ${t('legal.privacy.legal_rights.ccpa_cpra.right_to_delete.text')}`);
	lines.push(`- ${t('legal.privacy.legal_rights.ccpa_cpra.right_to_correct.text')}`);
	lines.push(`- ${t('legal.privacy.legal_rights.ccpa_cpra.right_to_opt_out_of_sale_or_sharing.text')}`);
	lines.push(`- ${t('legal.privacy.legal_rights.ccpa_cpra.right_to_non_discrimination.text')}`);
	lines.push('');
	lines.push(t('legal.privacy.legal_rights.ccpa_cpra.exercise.text'));
	lines.push('');

	// Section 9: Discord Integration
	lines.push(`## ${t('legal.privacy.discord_integration.heading.text')}`);
	lines.push('');
	lines.push(t('legal.privacy.discord_integration.description.text'));
	lines.push('');
	lines.push(t('legal.privacy.discord_integration.admin_access.text'));
	lines.push('');

	// Section 10: Contact
	lines.push(`## ${t('legal.privacy.contact.heading.text')}`);
	lines.push('');
	lines.push(t('legal.privacy.contact.questions.text'));
	lines.push('');
	// Email and postal info are handled separately in the Svelte component, but we include email here
	lines.push(`${t('legal.privacy.contact.email.text')}: contact@openmates.org`);
	lines.push('');
	lines.push(t('legal.privacy.contact.postal.text'));
	lines.push('');
	lines.push(t('legal.privacy.contact.controller.text'));
	lines.push('');

	return lines.join('\n');
}

/**
 * Build Terms of Use content from translation keys
 */
export function buildTermsOfUseContent(t: TranslationFunction): string {
	const lines: string[] = [];

	// Title
	lines.push(`# ${t('legal.terms.title.text')}`);
	lines.push('');

	// Last updated - use fixed date from translation keys
	lines.push(`*${t('legal.terms.last_updated.text')}: ${t('legal.terms.last_updated_date.text')}*`);
	lines.push('');

	// Section 1: Agreement
	lines.push(`## 1. ${t('legal.terms.agreement.heading.text')}`);
	lines.push('');
	lines.push(t('legal.terms.agreement.description.text'));
	lines.push('');

	// Section 2: About
	lines.push(`## 2. ${t('legal.terms.about.heading.text')}`);
	lines.push('');
	lines.push(t('legal.terms.about.description.text'));
	lines.push('');

	// Section 3: Intellectual Property
	lines.push(`## 3. ${t('legal.terms.intellectual_property.heading.text')}`);
	lines.push('');
	lines.push(t('legal.terms.intellectual_property.description.text'));
	lines.push('');

	// Section 4: Use License
	lines.push(`## 4. ${t('legal.terms.use_license.heading.text')}`);
	lines.push('');
	lines.push(t('legal.terms.use_license.description.text'));
	lines.push('');
	
	// Prohibited Uses of OpenMates Service
	lines.push(`### ${t('legal.terms.use_license.restrictions.service_use.heading.text')}`);
	lines.push('');
	lines.push(t('legal.terms.use_license.restrictions.service_use.description.text'));
	lines.push('');
	lines.push('- ' + t('legal.terms.use_license.restrictions.service_use.military.text'));
	lines.push('- ' + t('legal.terms.use_license.restrictions.service_use.gambling.text'));
	lines.push('- ' + t('legal.terms.use_license.restrictions.service_use.misinformation.text'));
	lines.push('- ' + t('legal.terms.use_license.restrictions.service_use.scams.text'));
	lines.push('- ' + t('legal.terms.use_license.restrictions.service_use.illegal.text'));
	lines.push('');

	// Section 5: AI Accuracy and Data Sharing
	lines.push(`## 5. ${t('legal.terms.ai_accuracy.heading.text')}`);
	lines.push('');
	lines.push(t('legal.terms.ai_accuracy.description.text'));
	lines.push('');
	lines.push(`### ${t('legal.terms.ai_accuracy.data_sharing.heading.text')}`);
	lines.push('');
	lines.push(t('legal.terms.ai_accuracy.data_sharing.text.text'));
	lines.push('');

	// Section 6: Credits and Payments
	lines.push(`## 6. ${t('legal.terms.credits.heading.text')}`);
	lines.push('');
	lines.push(t('legal.terms.credits.description.text'));
	lines.push('');
	lines.push(t('legal.terms.credits.refund.text'));
	lines.push('');

	// Section 7: Disclaimer
	lines.push(`## 7. ${t('legal.terms.disclaimer.heading.text')}`);
	lines.push('');
	lines.push(t('legal.terms.disclaimer.description.text'));
	lines.push('');

	// Section 8: Limitations
	lines.push(`## 8. ${t('legal.terms.limitations.heading.text')}`);
	lines.push('');
	lines.push(t('legal.terms.limitations.description.text'));
	lines.push('');
	lines.push('- ' + t('legal.terms.limitations.list.website_use.text'));
	lines.push('- ' + t('legal.terms.limitations.list.ai_responses.text'));
	lines.push('- ' + t('legal.terms.limitations.list.information.text'));
	lines.push('- ' + t('legal.terms.limitations.list.technical.text'));
	lines.push('- ' + t('legal.terms.limitations.list.data_loss.text'));
	lines.push('');

	// Section 9: Service Availability
	lines.push(`## 9. ${t('legal.terms.service_availability.heading.text')}`);
	lines.push('');
	lines.push(t('legal.terms.service_availability.description.text'));
	lines.push('');

	// Section 10: Encryption Keys and Account Recovery
	lines.push(`## 10. ${t('legal.terms.encryption_keys.heading.text')}`);
	lines.push('');
	lines.push(t('legal.terms.encryption_keys.description.text'));
	lines.push('');

	// Section 11: Governing Law
	lines.push(`## 11. ${t('legal.terms.governing_law.heading.text')}`);
	lines.push('');
	lines.push(t('legal.terms.governing_law.explanation.text'));
	lines.push('');

	// Section 12: Contact
	lines.push(`## 12. ${t('legal.terms.contact.heading.text')}`);
	lines.push('');
	lines.push(t('legal.terms.contact.intro.text'));
	lines.push('');
	lines.push(`${t('legal.terms.contact.email_label.text')}: contact@openmates.org`);
	lines.push('');

	return lines.join('\n');
}

/**
 * Build Imprint content from translation keys
 * Note: Imprint uses SVG images for contact info, which are displayed below
 */
export function buildImprintContent(t: TranslationFunction): string {
	const lines: string[] = [];

	// Title
	lines.push(`# ${t('legal.imprint.title.text')}`);
	lines.push('');

	// Section: Information according to TMG
	lines.push(`## ${t('legal.imprint.information_tmg.text')}`);
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
	lines.push(`## ${t('legal.imprint.contact.text')}`);
	lines.push('');
	lines.push(`${t('legal.imprint.email.text')}: contact@openmates.org`);
	lines.push('');

	return lines.join('\n');
}

