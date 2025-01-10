import adapter from '@sveltejs/adapter-auto';
import { vitePreprocess } from '@sveltejs/vite-plugin-svelte';
import path from 'path';

/** @type {import('@sveltejs/kit').Config} */
const config = {
	// Consult https://svelte.dev/docs/kit/integrations
	// for more information about preprocessors
	preprocess: vitePreprocess(),

	kit: {
		// adapter-auto only supports some environments, see https://svelte.dev/docs/kit/adapter-auto for a list.
		// If your environment is not supported, or you settled on a specific environment, switch out the adapter.
		// See https://svelte.dev/docs/kit/adapters for more information about adapters.
		adapter: adapter(),
		alias: {
			'@website-components': path.resolve('../website/src/routes/components'),
			'@website-styles': path.resolve('../website/src/lib/styles'),
			'@website-stores': path.resolve('../website/src/lib/stores'),
			'@website-actions': path.resolve('../website/src/lib/actions'),
			// '@website-locales': path.resolve('../website/src/locales')
		}
	}
};

export default config;
