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
	},
	build: {
		// Increase chunk size warning limit to 8000 kB for web_app
		// The web app includes the full UI library with translations, editor, and chat functionality
		// This is necessary for the offline-first architecture
		chunkSizeWarningLimit: 8000,
		rollupOptions: {
			// Suppress expected warnings about modules being both dynamically and statically imported
			// These are intentional for code that needs to work both ways
			onwarn(warning, warn) {
				// Suppress "dynamic import will not move module into another chunk" warnings
				// This is expected behavior for modules like cryptoService, db, websocketService, etc.
				// that are imported both dynamically and statically for offline-first functionality
				if (warning.code === 'UNUSED_EXTERNAL_IMPORT' || 
				    (warning.message && warning.message.includes('dynamic import will not move module'))) {
					return;
				}
				// Suppress externalized module warnings for qrcode-svg (uses 'fs' which is browser-incompatible)
				if (warning.message && warning.message.includes('externalized for browser compatibility')) {
					return;
				}
				// Pass through all other warnings
				warn(warning);
			}
		}
	}
});
