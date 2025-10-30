import adapter from '@sveltejs/adapter-static';
import { vitePreprocess } from '@sveltejs/vite-plugin-svelte';

/** @type {import('@sveltejs/kit').Config} */
const config = {
	// Consult https://kit.svelte.dev/docs/integrations#preprocessors
	// for more information about preprocessors
	preprocess: vitePreprocess(),
	compilerOptions: {
		runes: true
	},
	kit: {
		// adapter-static for true static PWA build
		adapter: adapter({
			// Output to build/ directory
			pages: 'build',
			assets: 'build',
			fallback: 'index.html', // SPA fallback for client-side routing
			precompress: false,
			strict: false // Disable strict mode to avoid SSR bundle analysis
		}),
		// Explicitly configure prerendering for SPA mode
		prerender: {
			entries: [], // Don't prerender any pages - pure SPA mode
			handleMissingId: 'ignore',
			handleHttpError: 'warn'
		}
	}
};

export default config;
