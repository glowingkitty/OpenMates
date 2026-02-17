/**
 * Preview mock data for DocsEmbedFullscreen.
 *
 * This file provides sample props and named variants for the component preview system.
 * Access at: /dev/preview/embeds/docs/DocsEmbedFullscreen
 */

const sampleHtml = `<h1>Project Architecture Overview</h1>
<p>This document outlines the architecture decisions for the OpenMates platform, covering frontend, backend, and infrastructure components.</p>
<h2>1. Frontend Architecture</h2>
<p>The frontend is built with <strong>SvelteKit</strong> and uses Svelte 5 runes for reactivity. Key design decisions include:</p>
<ul>
<li>Component-based architecture with shared UI package</li>
<li>CSS custom properties for theming</li>
<li>IndexedDB for local data persistence</li>
<li>End-to-end encryption for user data</li>
</ul>
<h2>2. Backend Architecture</h2>
<p>The backend uses <strong>FastAPI</strong> with Python, providing RESTful APIs for all services. Core components:</p>
<ul>
<li>WebSocket connections for real-time updates</li>
<li>Redis for caching and task queues</li>
<li>S3-compatible storage for encrypted files</li>
</ul>
<h2>3. Database Layer</h2>
<p>PostgreSQL serves as the primary data store, managed through <strong>Directus CMS</strong>. The schema is designed for:</p>
<ul>
<li>Multi-tenant isolation</li>
<li>Efficient query patterns for chat history</li>
<li>JSON columns for flexible metadata storage</li>
</ul>
<h2>4. Infrastructure</h2>
<p>The application is deployed using Docker containers orchestrated with Docker Compose. Each service runs in its own container for isolation and scalability.</p>`;

/** Default props — shows a fullscreen document view */
const defaultProps = {
	htmlContent: sampleHtml,
	title: 'Project Architecture Overview',
	filename: 'architecture.docx',
	wordCount: 156,
	onClose: () => console.log('[Preview] Close clicked'),
	hasPreviousEmbed: false,
	hasNextEmbed: false
};

export default defaultProps;

/** Named variants for different component states */
export const variants = {
	/** With navigation arrows */
	withNavigation: {
		...defaultProps,
		hasPreviousEmbed: true,
		hasNextEmbed: true,
		onNavigatePrevious: () => console.log('[Preview] Navigate previous'),
		onNavigateNext: () => console.log('[Preview] Navigate next')
	},

	/** Minimal — no title/filename */
	minimal: {
		htmlContent: '<p>A simple document with minimal metadata.</p>',
		onClose: () => console.log('[Preview] Close clicked')
	}
};
