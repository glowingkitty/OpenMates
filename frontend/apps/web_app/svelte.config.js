import adapter from '@sveltejs/adapter-vercel';
import { vitePreprocess } from '@sveltejs/vite-plugin-svelte';
import * as child_process from 'node:child_process';

/**
 * Get the current git commit hash for version tracking.
 * This enables SvelteKit's built-in version detection to work properly.
 * Falls back to timestamp if git is not available.
 */
function getVersionName() {
	try {
		return child_process.execSync('git rev-parse HEAD').toString().trim();
	} catch {
		// Fallback to timestamp if git is not available (e.g., in some CI environments)
		return `build-${Date.now()}`;
	}
}

/** @type {import('@sveltejs/kit').Config} */
const config = {
	// Consult https://kit.svelte.dev/docs/integrations#preprocessors
	// for more information about preprocessors
	preprocess: vitePreprocess(),
	compilerOptions: {
		runes: true
	},
	kit: {
		adapter: adapter({
			// see https://github.com/sveltejs/kit/tree/master/packages/adapter-vercel
			// for more information on Vercel specific options
		}),
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
			// Use git commit hash for deterministic version identification
			name: getVersionName(),
			// Poll for updates every 2 minutes (120000ms)
			// This checks if a new version has been deployed
			// Set to 0 to disable polling (not recommended)
			pollInterval: 120000
		}
	}
};

export default config;
