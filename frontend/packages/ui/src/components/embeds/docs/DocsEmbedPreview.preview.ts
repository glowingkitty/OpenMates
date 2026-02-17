/**
 * Preview mock data for DocsEmbedPreview.
 *
 * This file provides sample props and named variants for the component preview system.
 * Access at: /dev/preview/embeds/docs/DocsEmbedPreview
 */

const sampleHtml = `<h1>Project Architecture Overview</h1>
<p>This document outlines the architecture decisions for the OpenMates platform.</p>
<h2>Frontend</h2>
<p>The frontend is built with <strong>SvelteKit</strong> and uses Svelte 5 runes for reactivity.</p>
<h2>Backend</h2>
<p>The backend uses <strong>FastAPI</strong> with Python, providing RESTful APIs for all services.</p>
<h2>Database</h2>
<p>PostgreSQL serves as the primary data store, managed through Directus CMS.</p>`;

/** Default props — shows a finished document embed card */
const defaultProps = {
	id: 'preview-docs-1',
	title: 'Project Architecture Overview',
	filename: 'architecture.docx',
	wordCount: 156,
	status: 'finished' as const,
	htmlContent: sampleHtml,
	isMobile: false,
	onFullscreen: () => console.log('[Preview] Fullscreen clicked')
};

export default defaultProps;

/** Named variants for different component states */
export const variants = {
	/** Processing state — shows loading animation */
	processing: {
		id: 'preview-docs-processing',
		status: 'processing' as const,
		isMobile: false
	},

	/** Error state */
	error: {
		id: 'preview-docs-error',
		status: 'error' as const,
		isMobile: false
	},

	/** Long document */
	longDocument: {
		id: 'preview-docs-long',
		title: 'Complete API Reference Manual',
		filename: 'api-reference.docx',
		wordCount: 12450,
		status: 'finished' as const,
		htmlContent: sampleHtml,
		isMobile: false
	},

	/** Mobile view */
	mobile: {
		...defaultProps,
		id: 'preview-docs-mobile',
		isMobile: true
	}
};
