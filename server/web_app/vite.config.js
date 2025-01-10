import { sveltekit } from '@sveltejs/kit/vite';
import { defineConfig } from 'vite';
import path from 'path';

// Get the absolute path to your other project's source directory
const websiteSourcePath = path.resolve(__dirname, '../website/src');
const websiteStaticPath = path.resolve(__dirname, '../website/static');

export default defineConfig({
	plugins: [sveltekit()],
	resolve: {
		alias: {
			// Component and library aliases
			'@website-components': path.resolve(websiteSourcePath, 'routes/components'),
			'@website-styles': path.resolve(websiteSourcePath, 'lib/styles'),
			'@website-stores': path.resolve(websiteSourcePath, 'lib/stores'),
			'@website-actions': path.resolve(websiteSourcePath, 'lib/actions'),
			'@website-i18n': path.resolve(websiteSourcePath, 'lib/i18n'),
			
			// Static file aliases
			'/icons': path.resolve(websiteStaticPath, 'icons'),
			'/images': path.resolve(websiteStaticPath, 'images')
		}
	},
	server: {
		fs: {
			// Allow serving files from one level up to include the website project
			allow: [
				// Defaults
				'.',
				'../website/static',
				websiteStaticPath
			]
		}
	}
});