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
				runtimeCaching: [
					{
						urlPattern: /^https:\/\/api\.openmates\.org\/.*/i,
						handler: 'NetworkFirst',
						options: {
							cacheName: 'api-cache',
							expiration: {
								maxEntries: 100,
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
