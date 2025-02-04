import { sveltekit } from '@sveltejs/kit/vite';
import { defineConfig } from 'vite';
import path from 'path';

export default defineConfig({
	plugins: [sveltekit()],
	resolve: {
		alias: {
			// Alias for shared package
			'@openmates/shared': path.resolve(__dirname, '../shared'),
			// Alias for mate images pointing to the API images folder
			'@mate-images': path.resolve(__dirname, '../api/images/mates/profile_images')
		}
	},
	server: {
		fs: {
			// Allow serving files from one level up to include the api folder
			allow: [
				// Defaults
				'src',
				'.svelte-kit',
				// Add api directory to allow list
				path.resolve(__dirname, '../api')
			]
		}
	}
});
