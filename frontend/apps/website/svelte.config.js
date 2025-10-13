import adapter from '@sveltejs/adapter-vercel';
import { vitePreprocess } from '@sveltejs/vite-plugin-svelte';

/** @type {import('@sveltejs/kit').Config} */
const config = {
	// Consult https://kit.svelte.dev/docs/integrations#preprocessors
	// for more information about preprocessors
	preprocess: vitePreprocess(),
	kit: {
		// See https://kit.svelte.dev/docs/adapters for more information about adapters.
		adapter: adapter({
			// Vercel specific options can be added here if needed
			// See https://github.com/sveltejs/kit/tree/master/packages/adapter-vercel#options
		}),
		prerender: {
			handleUnseenRoutes: 'ignore'
		}
	},
};

export default config;
