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
<li>Client-side encryption for user data</li>
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

const generatedDocxPageOneSvg = `<svg xmlns="http://www.w3.org/2000/svg" width="794" height="1123" viewBox="0 0 794 1123">
<rect width="794" height="1123" fill="#ffffff"/>
<rect x="76" y="72" width="642" height="979" rx="2" fill="#ffffff" stroke="#e5e7eb"/>
<text x="112" y="148" font-family="Inter, Arial, sans-serif" font-size="34" font-weight="700" fill="#111827">Project Architecture Overview</text>
<text x="112" y="206" font-family="Inter, Arial, sans-serif" font-size="16" fill="#374151">Generated as a real DOCX artifact, then converted server-side to preview pages.</text>
<rect x="112" y="252" width="570" height="1" fill="#d1d5db"/>
<text x="112" y="314" font-family="Inter, Arial, sans-serif" font-size="22" font-weight="700" fill="#111827">Frontend</text>
<text x="112" y="356" font-family="Inter, Arial, sans-serif" font-size="16" fill="#374151">SvelteKit and Svelte 5 render the encrypted document preview after decrypting</text>
<text x="112" y="382" font-family="Inter, Arial, sans-serif" font-size="16" fill="#374151">the generated screenshot artifact in the browser.</text>
<text x="112" y="456" font-family="Inter, Arial, sans-serif" font-size="22" font-weight="700" fill="#111827">Backend Pipeline</text>
<text x="112" y="498" font-family="Inter, Arial, sans-serif" font-size="16" fill="#374151">1. The model emits structured docx_model JSON.</text>
<text x="112" y="526" font-family="Inter, Arial, sans-serif" font-size="16" fill="#374151">2. The Docs worker creates a canonical .docx file.</text>
<text x="112" y="554" font-family="Inter, Arial, sans-serif" font-size="16" fill="#374151">3. LibreOffice converts it to PDF; PyMuPDF renders page screenshots.</text>
<text x="112" y="582" font-family="Inter, Arial, sans-serif" font-size="16" fill="#374151">4. DOCX and screenshots are AES-GCM encrypted before upload.</text>
<rect x="112" y="660" width="570" height="132" rx="14" fill="#eef2ff" stroke="#c7d2fe"/>
<text x="142" y="711" font-family="Inter, Arial, sans-serif" font-size="18" font-weight="700" fill="#3730a3">Download</text>
<text x="142" y="750" font-family="Inter, Arial, sans-serif" font-size="16" fill="#4338ca">The download button returns the real generated DOCX, not browser HTML.</text>
</svg>`;

const generatedDocxPageTwoSvg = `<svg xmlns="http://www.w3.org/2000/svg" width="794" height="1123" viewBox="0 0 794 1123">
<rect width="794" height="1123" fill="#ffffff"/>
<rect x="76" y="72" width="642" height="979" rx="2" fill="#ffffff" stroke="#e5e7eb"/>
<text x="112" y="148" font-family="Inter, Arial, sans-serif" font-size="30" font-weight="700" fill="#111827">Compatibility</text>
<text x="112" y="214" font-family="Inter, Arial, sans-serif" font-size="16" fill="#374151">Existing document_html embeds still render through the legacy HTML fallback.</text>
<text x="112" y="242" font-family="Inter, Arial, sans-serif" font-size="16" fill="#374151">New embeds use docx_model, encrypted artifacts, and generated preview pages.</text>
<rect x="112" y="318" width="250" height="130" rx="16" fill="#ecfdf5" stroke="#a7f3d0"/>
<text x="142" y="372" font-family="Inter, Arial, sans-serif" font-size="18" font-weight="700" fill="#065f46">Legacy HTML</text>
<text x="142" y="410" font-family="Inter, Arial, sans-serif" font-size="15" fill="#047857">Still viewable and downloadable.</text>
<rect x="432" y="318" width="250" height="130" rx="16" fill="#fef3c7" stroke="#fde68a"/>
<text x="462" y="372" font-family="Inter, Arial, sans-serif" font-size="18" font-weight="700" fill="#92400e">DOCX Artifact</text>
<text x="462" y="410" font-family="Inter, Arial, sans-serif" font-size="15" fill="#b45309">Canonical generated file.</text>
</svg>`;

const previewPageUrls = {
	'1': `data:image/svg+xml;charset=utf-8,${encodeURIComponent(generatedDocxPageOneSvg)}`,
	'2': `data:image/svg+xml;charset=utf-8,${encodeURIComponent(generatedDocxPageTwoSvg)}`
};

/** Default props — shows a fullscreen document view */
const defaultProps = {
	htmlContent: sampleHtml,
	title: 'Project Architecture Overview',
	filename: 'architecture.docx',
	wordCount: 156,
	preview_page_urls: previewPageUrls,
	page_count: 2,
	onClose: () => {},
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
		onNavigatePrevious: () => {},
		onNavigateNext: () => {}
	},

	/** Minimal — no title/filename */
	minimal: {
		htmlContent: '<p>A simple document with minimal metadata.</p>',
		onClose: () => {}
	},

	/** Generated DOCX artifact preview — renders the pre-generated page screenshots */
	generatedDocxArtifact: {
		...defaultProps,
		title: 'Generated DOCX Artifact',
		filename: 'generated-artifact.docx',
		wordCount: 91,
		preview_page_urls: previewPageUrls,
		page_count: 2
	}
};
