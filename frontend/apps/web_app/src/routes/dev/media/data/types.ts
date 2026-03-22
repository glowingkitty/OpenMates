/**
 * Type definitions for the media generation data system.
 *
 * All media templates load their content from YAML scenario files,
 * parsed at runtime into these types. This ensures deterministic,
 * reproducible media output.
 *
 * Architecture: docs/media-generation.md
 */

/** A single chat message in a media scenario */
export interface MediaMessage {
	role: 'user' | 'assistant';
	content: string;
	category?: string;
	mate_name?: string;
}

/** An embed card to display in a media scenario */
export interface MediaEmbed {
	type: string;
	title: string;
	description?: string;
	url?: string;
	image_url?: string;
}

/** A complete scenario loaded from YAML */
export interface MediaScenario {
	id: string;
	name: string;
	description?: string;
	messages: MediaMessage[];
	embeds?: MediaEmbed[];
	theme?: 'dark' | 'light';
}

/** Brand configuration for templates */
export interface BrandConfig {
	headline: string;
	subtitle: string;
	features: string[];
	logo_size?: number;
	headline_size?: string;
}

/** A complete template configuration loaded from YAML */
export interface MediaTemplateConfig {
	template: string;
	format: string;
	width: number;
	height: number;
	pages?: number;
	brand?: BrandConfig;
	phone?: {
		scenario?: string;
		screen?: 'new-chat' | 'chat';
		screen_width?: number;
		screen_height?: number;
		scale?: number;
		show_sidebar?: boolean;
		chat_title?: string;
		chat_category?: string;
	};
	laptop?: {
		scenario?: string;
		screen?: 'new-chat' | 'chat';
		screen_width?: number;
		screen_height?: number;
		scale?: number;
		show_sidebar?: boolean;
		chat_title?: string;
		chat_category?: string;
	};
	slides?: SlideConfig[];
}

/** A single carousel slide configuration */
export interface SlideConfig {
	type: 'hero' | 'chat' | 'feature' | 'cta';
	headline?: string;
	subtitle?: string;
	scenario?: string;
	device?: 'phone' | 'laptop';
	features?: string[];
	cta_text?: string;
	cta_url?: string;
}

/** Canonical format dimensions */
export const FORMAT_DIMENSIONS: Record<string, { width: number; height: number }> = {
	'og': { width: 1200, height: 630 },
	'instagram-square': { width: 1080, height: 1080 },
	'instagram-story': { width: 1080, height: 1920 },
	'twitter-header': { width: 1500, height: 500 },
	'github-social': { width: 1280, height: 640 },
	'linkedin-post': { width: 1200, height: 627 },
	'facebook-cover': { width: 820, height: 312 },
};
