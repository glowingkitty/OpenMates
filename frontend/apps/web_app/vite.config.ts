import { sveltekit } from '@sveltejs/kit/vite';
import { defineConfig } from 'vite';
import { SvelteKitPWA } from '@vite-pwa/sveltekit';
import path from 'path';

export default defineConfig({
	plugins: [
		sveltekit(),
		SvelteKitPWA({
			srcDir: './src',
			mode: 'production',
			strategies: 'generateSW',
			scope: '/',
			base: '/',
			selfDestroying: false,
			manifest: {
				name: 'OpenMates - Your AI Team',
				short_name: 'OpenMates',
				description: 'Digital teammates with Apps for everyday tasks and learning',
				theme_color: '#1a1a1a',
				background_color: '#ffffff',
				display: 'standalone',
				scope: '/',
				start_url: '/',
				orientation: 'portrait-primary',
				icons: [
					{
						src: '/icons/icon-192x192.png',
						sizes: '192x192',
						type: 'image/png',
						purpose: 'any maskable'
					},
					{
						src: '/icons/icon-512x512.png',
						sizes: '512x512',
						type: 'image/png',
						purpose: 'any maskable'
					}
				]
			},
			workbox: {
				globPatterns: ['**/*.{js,css,html,ico,png,svg,webp,woff,woff2}'],
				// Increase limit to 8MB to accommodate large chunks for offline-first functionality
				// The largest chunk is ~7.2MB (translations, TipTap editor, ProseMirror, UI library)
				// This enables true offline capability at the cost of a larger initial download
				// See docs/architecture/bundle_optimization_strategy.md for long-term optimization plan
				maximumFileSizeToCacheInBytes: 8 * 1024 * 1024, // 8 MB
				// Add cleanup configuration to prevent quota exceeded errors
				cleanupOutdatedCaches: true,
				// Safari-specific: Force immediate service worker updates
				// skipWaiting makes the new service worker activate immediately
				// clientsClaim makes it take control of all pages immediately
				skipWaiting: true,
				clientsClaim: true,
				// Safari-specific: Ensure precached files use versioned URLs
				// This ensures Safari detects file changes and updates properly
				// Workbox automatically generates revision hashes for precached files
				// Add cache busting for HTML to prevent Safari from using stale HTML
				// Note: SvelteKit already handles versioning for JS/CSS assets via build hashes
				runtimeCaching: [
					{
						urlPattern: /^https:\/\/api\.openmates\.org\/.*/i,
						handler: 'NetworkFirst',
						options: {
							cacheName: 'api-cache',
							expiration: {
								maxEntries: 50, // Reduced from 100 to prevent quota issues
								maxAgeSeconds: 60 * 60 // 1 hour
							},
							networkTimeoutSeconds: 10
						}
					}
				],
				navigateFallback: null // Let SvelteKit handle routing
			},
			devOptions: {
				enabled: true,
				type: 'module',
				navigateFallback: '/'
			}
		})
	],
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
					if (id.includes('/chunks/de.js') || id.includes('/chunks/en.js') || 
					    id.includes('/chunks/es.js') || id.includes('/chunks/fr.js') || 
					    id.includes('/chunks/ja.js') || id.includes('/chunks/zh.js')) {
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
				if (warning.code === 'UNUSED_EXTERNAL_IMPORT' ||
				    (warning.message && warning.message.includes('dynamic import will not move module'))) {
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
		exclude: ['@fontsource-variable/lexend-deca']
	},
	define: {
		// Define global variables to help with Svelte 5 build issues
		'process.env.NODE_ENV': JSON.stringify(process.env.NODE_ENV || 'production')
	}
});
