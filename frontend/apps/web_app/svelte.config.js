import adapter from '@sveltejs/adapter-vercel';
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
		adapter: adapter({
			// see https://github.com/sveltejs/kit/tree/master/packages/adapter-vercel
			// for more information on Vercel specific options
		}),
		files: {
			assets: 'static'
		}
	}
};

export default config;
