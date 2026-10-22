import adapterVercel from '@sveltejs/adapter-vercel';
import { vitePreprocess } from '@sveltejs/vite-plugin-svelte';
import { getVersionName } from './scripts/build-version.mjs';

/** @type {import('@sveltejs/kit').Config} */
const config = {
	// Consult https://kit.svelte.dev/docs/integrations#preprocessors
	// for more information about preprocessors
	preprocess: vitePreprocess(),
	compilerOptions: {
		runes: true
	},
	kit: {
		adapter: adapterVercel({
			// Match our deployment target even when the build runs under Bun.
			runtime: 'nodejs24.x'
		}),
		paths: {
			// Use absolute asset paths (/_app/...) instead of relative (./_app/...).
			// Required because the Vercel rewrite for /dev/* serves the SPA shell HTML
			// at deep nested URLs (e.g. /dev/preview/embeds/web/Component).
			// With relative paths, the browser would resolve ./_app/... relative to
			// that deep URL, producing wrong paths like /dev/preview/embeds/web/_app/...
			// which return HTML instead of JS (MIME type error, blank page).
			relative: false
		},
		files: {
			assets: 'static'
		},
		/**
		 * Version configuration for detecting app updates.
		 * This prevents "chunk loading errors" after deployments by:
		 * 1. Using git commit hash as version identifier
		 * 2. Polling every 2 minutes to detect new deployments
		 * 3. Setting `updated.current` to true when a new version is detected
		 *
		 * The app can then show an update banner and/or auto-refresh on navigation.
		 * See: https://kit.svelte.dev/docs/configuration#version
		 */
		version: {
			// Share one stable identity across HTML, client and prerender workers.
			name: getVersionName(),
			// Poll for updates every 2 minutes (120000ms)
			// This checks if a new version has been deployed
			// Set to 0 to disable polling (not recommended)
			pollInterval: 120000
		},
		prerender: {
			// SEO pages (e.g. /intro/[slug]) link to the SPA root via
			// /#chat-id={slug} hash deep links. The prerenderer follows these href links and
			// complains that no element with id="chat-id=..." exists on the / page — which is
			// correct, because / is a JS SPA and the anchor is a client-side deep link, not
			// a real DOM id. Ignore these missing-id warnings so the build succeeds.
			handleMissingId: 'ignore'
		}
	}
};

export default config;
