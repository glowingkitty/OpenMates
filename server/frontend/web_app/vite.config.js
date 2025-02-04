import { sveltekit } from '@sveltejs/kit/vite';
import { defineConfig } from 'vite';
import path from 'path';

export default defineConfig({
	plugins: [sveltekit()],
	resolve: {
		alias: {
			// Alias for shared package
			'@openmates/shared': path.resolve(__dirname, '../shared'),

			// Add mate-images alias pointing to the API images folder
			'@openmates/mate-images': path.resolve(__dirname, '../../api/images/mates/profile_images'),
		}
	},
	server: {
		fs: {
			// Allow serving files from one level up to include the website and api projects
			allow: [
				// Defaults
				'.',
				'../shared',
				'../../api'
			]
		}
	}
});