import { sveltekit } from '@sveltejs/kit/vite';
import { defineConfig } from 'vite';
import path from 'path';

export default defineConfig({
	plugins: [sveltekit()],
	resolve: {
		alias: {
			// Add new alias for UI package
			'@openmates/ui': path.resolve(__dirname, '../../packages/ui'),
		}
	},
	server: {
		fs: {
			// Allow serving files from one level up to include the website and api projects
			allow: [
				// Defaults
				'.',
				'../shared',
				'../../../api',
				'../../packages/ui'
			]
		}
	}
});
