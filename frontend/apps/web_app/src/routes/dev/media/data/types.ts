/**
 * Type definitions for the media generation system.
 *
 * Templates load their configuration from YAML config files. Device screens
 * render the real app via iframes in media mode (?media=1), so chat content
 * comes from the live app rather than static YAML scenarios.
 *
 * Architecture: docs/media-generation.md
 */

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
		iframe_src?: string;
		screen_width?: number;
		screen_height?: number;
		scale?: number;
	};
	laptop?: {
		iframe_src?: string;
		screen_width?: number;
		screen_height?: number;
		scale?: number;
	};
	slides?: SlideConfig[];
}

/** A single carousel slide configuration */
export interface SlideConfig {
	type: 'hero' | 'chat' | 'feature' | 'cta';
	headline?: string;
	subtitle?: string;
	iframe_src?: string;
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
