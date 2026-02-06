<script lang="ts">
	// Import UI styles
	import '@repo/ui/src/styles/buttons.css';
	import '@repo/ui/src/styles/fields.css';
	import '@repo/ui/src/styles/cards.css';
	import '@repo/ui/src/styles/chat.css';
	import '@repo/ui/src/styles/mates.css';
	import '@repo/ui/src/styles/theme.css';
	import '@repo/ui/src/styles/fonts.css';
	import '@repo/ui/src/styles/icons.css';
	import '@repo/ui/src/styles/auth.css';
	import '@repo/ui/src/styles/markdown.css';
	// KaTeX CSS is imported via markdown.css
	import {
		// components
		MetaTags,
		OfflineBanner,
		// Config
		loadMetaTags,
		// Stores
		theme,
		initializeTheme,
		initializeServerStatus,
		notificationStore
	} from '@repo/ui';
	import { onMount } from 'svelte';
	import { browser } from '$app/environment';
	import { waitLocale } from 'svelte-i18n';
	import { updated } from '$app/state';
	import { beforeNavigate } from '$app/navigation';

	let loaded = $state(false);
	let { children } = $props();

	/**
	 * Track if we've already shown the update notification.
	 * Prevents showing multiple notifications for the same update.
	 */
	let updateNotificationShown = $state(false);

	onMount(async () => {
		// Import font CSS only in the browser to avoid SSR issues
		// Node.js cannot process CSS files directly during SSR
		// This dynamic import only runs in the browser, not during SSR
		if (browser) {
			await import('@fontsource-variable/lexend-deca');
		}

		await waitLocale();
		loaded = true;

		// Load meta tags after translations are ready
		await loadMetaTags();

		initializeTheme();

		// Initialize server status early to prevent UI flashing
		// (e.g., legal chats briefly appearing on self-hosted instances)
		initializeServerStatus();

		// Load meta tags after translations are ready (i18n setup happens elsewhere)
		await loadMetaTags();
	});

	// Watch theme changes and update document attribute
	$effect(() => {
		if (browser) {
			document.documentElement.setAttribute('data-theme', $theme);
		}
	});

	/**
	 * Show notification when a new app version is detected.
	 * Uses SvelteKit's built-in version detection via $app/state.
	 */
	$effect(() => {
		if (browser && updated.current && !updateNotificationShown) {
			console.log('[Layout] New app version detected, showing notification');
			updateNotificationShown = true;

			// Show a persistent info notification (no auto-dismiss)
			// User can dismiss it, or page will auto-refresh on next navigation
			notificationStore.info(
				'A new version is available. The page will refresh on your next navigation, or refresh now.',
				0, // 0 = persistent, no auto-dismiss
				true // dismissible
			);
		}
	});

	/**
	 * Auto-refresh on navigation when an update is detected.
	 * This prevents chunk loading errors (404s for old JS chunks) during navigation.
	 *
	 * When user navigates and an update is available:
	 * - Instead of client-side navigation (which might fail due to missing chunks)
	 * - We do a full page reload to get the fresh version
	 *
	 * This is the recommended pattern from SvelteKit docs for handling version skew.
	 */
	beforeNavigate(({ willUnload, to }) => {
		if (updated.current && !willUnload && to?.url) {
			console.log('[Layout] New version detected, forcing full reload on navigation');
			location.href = to.url.href;
		}
	});
</script>

{#if loaded}
	<MetaTags />
	<OfflineBanner />
	<main>
		{@render children()}
	</main>
{/if}

<style>
	/* Apply background color to the body */
	:global(body) {
		background-color: var(--color-grey-0);
	}
</style>
