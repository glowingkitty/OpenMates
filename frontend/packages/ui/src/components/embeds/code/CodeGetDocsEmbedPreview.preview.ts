/**
 * Preview mock data for CodeGetDocsEmbedPreview.
 *
 * This file provides sample props and named variants for the component preview system.
 * Access at: /dev/preview/embeds/code/CodeGetDocsEmbedPreview
 */

/** Default props — shows a finished code docs embed with results */
const defaultProps = {
	id: 'preview-code-getdocs-1',
	status: 'finished' as const,
	library: 'svelte',
	question: 'How to use $state rune in Svelte 5?',
	results: [
		{
			title: '$state — Svelte 5 Runes',
			content:
				'The $state rune declares reactive state. When you assign to a $state variable, ' +
				'Svelte automatically updates all DOM nodes that depend on it.\n\n' +
				'```svelte\n<script>\nlet count = $state(0);\n</script>\n<button onclick={() => count++}>{count}</button>\n```',
			url: 'https://svelte.dev/docs/svelte/$state',
			source: 'svelte.dev'
		}
	],
	isMobile: false,
	onFullscreen: () => console.log('[Preview] Fullscreen clicked')
};

export default defaultProps;

/** Named variants for different component states */
export const variants = {
	/** Processing state — shows loading while fetching docs */
	processing: {
		id: 'preview-code-getdocs-processing',
		status: 'processing' as const,
		library: 'react',
		question: 'How to use useEffect hook?',
		results: [],
		isMobile: false
	},

	/** Error state */
	error: {
		id: 'preview-code-getdocs-error',
		status: 'error' as const,
		library: 'unknown-lib',
		question: 'How to use unknown feature?',
		results: [],
		isMobile: false
	},

	/** Multiple results */
	multipleResults: {
		...defaultProps,
		id: 'preview-code-getdocs-multi',
		library: 'fastapi',
		question: 'How to define path parameters?',
		results: [
			{
				title: 'Path Parameters — FastAPI',
				content: 'Path parameters are defined using Python type hints in the function signature.',
				url: 'https://fastapi.tiangolo.com/tutorial/path-params/',
				source: 'fastapi.tiangolo.com'
			},
			{
				title: 'Path Parameters and Numeric Validations',
				content: 'Use Path() to add validation to path parameters.',
				url: 'https://fastapi.tiangolo.com/tutorial/path-params-numeric-validations/',
				source: 'fastapi.tiangolo.com'
			}
		]
	},

	/** Mobile view */
	mobile: {
		...defaultProps,
		id: 'preview-code-getdocs-mobile',
		isMobile: true
	}
};
