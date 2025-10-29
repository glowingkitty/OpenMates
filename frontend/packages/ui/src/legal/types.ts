/**
 * Legal document types for Privacy Policy, Terms of Use, and Imprint
 * These are chat-based legal documents accessible via dedicated routes
 */

export interface LegalDocument {
	id: string; // e.g., 'privacy', 'terms', 'imprint'
	title: string; // e.g., 'Privacy Policy'
	version: string; // e.g., 'v1.0'
	effectiveDate: string; // ISO date string
	lastUpdated: string; // ISO date string
	route: string; // e.g., '/privacy'
	sections: LegalSection[];
	metadata: {
		description: string; // For SEO meta tags
		keywords: string[]; // For SEO
		language: 'en' | 'de'; // Support for multilingual
	};
}

export interface LegalSection {
	id: string; // Section identifier
	title: string; // Section heading
	content: string; // Markdown content
	subsections?: LegalSection[]; // Nested sections
}

/**
 * Legal consent record (for Terms of Use acceptance)
 */
export interface LegalConsent {
	user_id: string;
	document_id: string; // 'terms'
	version: string; // 'v1.0'
	accepted_at: string; // ISO timestamp
	ip_address?: string; // Optional: IP for audit trail
}

