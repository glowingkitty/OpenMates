import { sveltekit } from '@sveltejs/kit/vite';
import { defineConfig } from 'vite';
import path from 'path';

// Get the absolute path to your other project's source directory
const websiteSourcePath = path.resolve(__dirname, '../website/src');
const websiteStaticPath = path.resolve(__dirname, '../website/static');
const websiteApiPath = path.resolve(__dirname, '../api');

export default defineConfig({
	plugins: [sveltekit()],
	resolve: {
		alias: {
			// Component and library aliases
			'@website-components': path.resolve(websiteSourcePath, 'routes/components'),
			'@website-styles': path.resolve(websiteSourcePath, 'lib/styles'),
			'@website-stores': path.resolve(websiteSourcePath, 'lib/stores'),
			'@website-actions': path.resolve(websiteSourcePath, 'lib/actions'),
			'@website-locales': path.resolve(websiteSourcePath, 'locales'),
			
			// Static file aliases
			'/icons': path.resolve(websiteStaticPath, 'icons'),
			'/images': path.resolve(websiteStaticPath, 'images'),
			
			// Add mate-images alias pointing to the API images folder
			'@mate-images': path.resolve(websiteApiPath, 'images/mates/profile_images'),
			'@website': path.resolve('../website/src')
		}
	},
	server: {
		fs: {
			// Allow serving files from one level up to include the website and api projects
			allow: [
				// Defaults
				'.',
				'../website',
				'../api'
			]
		}
	}
});