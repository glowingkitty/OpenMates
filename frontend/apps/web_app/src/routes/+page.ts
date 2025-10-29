import type { PageLoad } from './$types';

/**
 * Client-side page load config
 * Ensures SSR is enabled for SEO
 */
export const prerender = false; // Disable prerendering for dynamic auth state
export const ssr = true; // Enable SSR for SEO crawlers

export const load: PageLoad = async ({ data }) => {
	// Pass through server data to the page (including SEO metadata)
	return {
		welcomeChat: data.welcomeChat,
		seo: data.seo
	};
};

