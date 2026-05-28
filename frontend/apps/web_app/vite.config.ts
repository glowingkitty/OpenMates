import { sveltekit } from '@sveltejs/kit/vite';
import { defineConfig } from 'vite';
import path from 'path';
import { docsPlugin } from './scripts/vite-plugin-docs.js';

export default defineConfig({
	plugins: [sveltekit(), docsPlugin()],
	resolve: {
		alias: {
			// Add new alias for UI package
			'@openmates/ui': path.resolve(__dirname, '../../packages/ui')
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
		// Target modern browsers for better optimization
		target: 'es2020',
		// Enable CSS code splitting for better caching
		cssCodeSplit: true,
		// Increase chunk size warning limit - we're actively managing chunks now
		chunkSizeWarningLimit: 1000,
		rollupOptions: {
			output: {
				// Manual chunk splitting strategy to improve caching and load performance
				// Split large dependencies into separate chunks that can be cached independently
				manualChunks(id) {
					// TipTap and ProseMirror (~2MB) - loaded only for message input
					if (id.includes('tiptap') || id.includes('prosemirror')) {
						return 'editor';
					}
					// Translation files (~1.5MB total) - loaded per-language as needed
					if (
						id.includes('/chunks/de.js') ||
						id.includes('/chunks/en.js') ||
						id.includes('/chunks/es.js') ||
						id.includes('/chunks/fr.js') ||
						id.includes('/chunks/ja.js') ||
						id.includes('/chunks/zh.js')
					) {
						return 'translations';
					}
					// IndexedDB and crypto libraries - core functionality
					if (id.includes('idb') || id.includes('dexie')) {
						return 'database';
					}
					// Large third-party UI/utility libraries
					if (id.includes('node_modules')) {
						// Svelte framework
						if (id.includes('svelte')) {
							return 'svelte-vendor';
						}
						// Internationalization
						if (id.includes('svelte-i18n') || id.includes('intl') || id.includes('formatjs')) {
							return 'i18n-vendor';
						}
						// QR code generation (includes problematic 'fs' reference)
						if (id.includes('qrcode')) {
							return 'qrcode-vendor';
						}
						// Other large vendors
						if (id.includes('yaml') || id.includes('marked') || id.includes('lodash')) {
							return 'utilities-vendor';
						}
					}
					// NOTE: Removed app-services chunking to prevent SSR initialization issues
					// Services will be bundled with components that use them
					// This prevents circular dependency issues during SSR build analysis
					// Temporarily disable component chunking to avoid circular dependency issues
					// TODO: Re-enable after fixing Svelte 5 runes circular dependency issues
					// if (id.includes('packages/ui/src/components/signup/')) {
					// 	return 'signup-components';
					// }
					// if (id.includes('packages/ui/src/components/settings/')) {
					// 	return 'settings-components';
					// }
					// if (id.includes('packages/ui/src/components/chats/')) {
					// 	return 'chat-components';
					// }
				}
			},
			// Suppress expected warnings about modules being both dynamically and statically imported
			// These are intentional for code that needs to work both ways
			onwarn(warning, warn) {
				// Suppress "dynamic import will not move module into another chunk" warnings
				// This is expected behavior for modules like cryptoService, db, websocketService, etc.
				// that are imported both dynamically and statically for offline-first functionality
				if (
					warning.code === 'UNUSED_EXTERNAL_IMPORT' ||
					(warning.message && warning.message.includes('dynamic import will not move module'))
				) {
					return;
				}
				// Suppress externalized module warnings for qrcode-svg (uses 'fs' which is browser-incompatible)
				if (warning.message && warning.message.includes('externalized for browser compatibility')) {
					return;
				}
				// Suppress circular dependency warnings that are expected in our architecture
				if (warning.code === 'CIRCULAR_DEPENDENCY') {
					return;
				}
				// Pass through all other warnings
				warn(warning);
			}
		}
	},
	optimizeDeps: {
		// Exclude problematic modules from pre-bundling
		exclude: [
			'@fontsource-variable/lexend-deca',
			'@fontsource-variable/figtree',
			'@fontsource-variable/rubik',
			'@fontsource-variable/inter',
			'@fontsource-variable/public-sans',
			'@fontsource/atkinson-hyperlegible',
			'@fontsource/ibm-plex-sans',
			'@fontsource-variable/source-serif-4',
			'@fontsource-variable/jetbrains-mono',
			'@fontsource/ibm-plex-mono',
			'jspdf'
		]
	},
	define: {
		// Define global variables to help with Svelte 5 build issues
		'process.env.NODE_ENV': JSON.stringify(process.env.NODE_ENV || 'production')
	}
});
