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
			library: {
				id: '/sveltejs/svelte',
				title: 'Svelte',
				description: 'Cybernetically enhanced web apps'
			},
			documentation:
				'The `$state` rune declares reactive state. When you assign to a `$state` variable, ' +
				'Svelte automatically updates all DOM nodes that depend on it.\n\n' +
				'## Basic Usage\n\n' +
				'```svelte\n<script>\nlet count = $state(0);\n</script>\n<button onclick={() => count++}>{count}</button>\n```',
			word_count: 48,
			source: 'context7'
		}
	],
	isMobile: false,
	onFullscreen: () => {}
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

	/** FastAPI docs */
	fastapi: {
		id: 'preview-code-getdocs-fastapi',
		status: 'finished' as const,
		library: 'fastapi',
		question: 'How to define path parameters?',
		results: [
			{
				library: {
					id: '/tiangolo/fastapi',
					title: 'FastAPI'
				},
				documentation: 'Path parameters are defined using Python type hints in the function signature.',
				word_count: 62,
				source: 'context7'
			}
		],
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
	}
};
