import adapter from '@sveltejs/adapter-auto';
import { vitePreprocess } from '@sveltejs/vite-plugin-svelte';
import path from 'path';
import { fileURLToPath } from 'url';
import { dirname } from 'path';

// Create __dirname equivalent for ES modules
const __filename = fileURLToPath(import.meta.url);
const __dirname = dirname(__filename);

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
			'@openmates/shared': path.resolve(__dirname, '../shared'),
		},
		// Add prerender configuration
		prerender: {
			handleHttpError: ({ path, referrer, message }) => {
				// Ignore 404s for pages that are not meant to be in production
				if (message.includes('404') && (
					path.includes('/developers') ||
					path.includes('/docs') ||
					path.includes('/docs/api') ||
					path.includes('/docs/design_guidelines') ||
					path.includes('/docs/design_system') ||
					path.includes('/docs/roadmap')
				)) {
					return;
				}
				// Otherwise throw the error
				throw new Error(message);
			}
		}
	}
};

export default config;
