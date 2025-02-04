import { sveltekit } from '@sveltejs/kit/vite';
import { defineConfig } from 'vite';
import path from 'path';

export default defineConfig({
	plugins: [sveltekit()],
	resolve: {
		alias: {
			// Alias for shared package
			'@openmates/shared': path.resolve(__dirname, '../shared'),

			// Static file aliases
			'/icons': path.resolve(__dirname, '../shared/static/icons'),
			'/images': path.resolve(__dirname, '../shared/static/images'),

			// Add mate-images alias pointing to the API images folder
			'@mate-images': path.resolve(__dirname, '../../api/images/mates/profile_images'),
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