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

const generatedDocxPageSvg = `<svg xmlns="http://www.w3.org/2000/svg" width="794" height="1123" viewBox="0 0 794 1123">
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

const generatedDocxPreviewPageUrl = `data:image/svg+xml;charset=utf-8,${encodeURIComponent(generatedDocxPageSvg)}`;

/** Default props — shows a finished document embed card */
const defaultProps = {
	id: 'preview-docs-1',
	title: 'Project Architecture Overview',
	filename: 'architecture.docx',
	wordCount: 156,
	status: 'finished' as const,
	htmlContent: sampleHtml,
	previewPageUrls: { '1': generatedDocxPreviewPageUrl },
	isMobile: false,
	onFullscreen: () => {}
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
		previewPageUrls: { '1': generatedDocxPreviewPageUrl },
		isMobile: false
	},

	/** Generated DOCX artifact preview — uses the same screenshot rendering path as production */
	generatedDocxArtifact: {
		...defaultProps,
		id: 'preview-docs-generated-artifact',
		title: 'Generated DOCX Artifact',
		filename: 'generated-artifact.docx',
		wordCount: 91,
		previewPageUrls: { '1': generatedDocxPreviewPageUrl }
	},

	/** Mobile view */
	mobile: {
		...defaultProps,
		id: 'preview-docs-mobile',
		isMobile: true
	}
};
