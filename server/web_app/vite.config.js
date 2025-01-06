import { sveltekit } from '@sveltejs/kit/vite';
import { defineConfig } from 'vite';
import path from 'path';

// Get the absolute path to your other project's source directory
const websiteSourcePath = path.resolve(__dirname, '../website/src');

export default defineConfig({
	plugins: [sveltekit()],
	resolve: {
		alias: {
			// Add aliases to the other project's directories
			'@website-styles': path.resolve(websiteSourcePath, 'lib/styles'),
			'@website-static': path.resolve(websiteSourcePath, 'static'),
			'@website-actions': path.resolve(websiteSourcePath, 'lib/actions'),
		}
	}
});