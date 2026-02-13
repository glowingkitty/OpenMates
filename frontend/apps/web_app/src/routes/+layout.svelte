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
		notificationStore,
		// Utils
		performCleanUpdate
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

		// iOS Safari zoom fix: When the virtual keyboard closes, Safari can leave the page
		// in a zoomed-in state. Use the visualViewport API to detect when the viewport height
		// returns to the window height (keyboard closed) and reset any residual zoom by
		// scrolling to top-left. This complements the maximum-scale=1 viewport meta tag.
		if (window.visualViewport) {
			let lastViewportHeight = window.visualViewport.height;
			const handleViewportResize = () => {
				const vv = window.visualViewport;
				if (!vv) return;
				const currentHeight = vv.height;
				// Keyboard closed: viewport height increased back (keyboard was taking space)
				// AND there's residual zoom offset that needs resetting
				if (currentHeight > lastViewportHeight && (vv.offsetTop > 0 || vv.offsetLeft > 0)) {
					// Reset any zoom/scroll offset left by iOS Safari keyboard dismiss
					window.scrollTo(0, 0);
				}
				lastViewportHeight = currentHeight;
			};
			window.visualViewport.addEventListener('resize', handleViewportResize);
		}
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
	 *
	 * Displays a persistent software_update notification with a "Refresh now" button.
	 * Clicking the button triggers performCleanUpdate() which:
	 * 1. Clears all Service Worker caches
	 * 2. Activates any waiting Service Worker (SKIP_WAITING)
	 * 3. Reloads the page for a clean fresh start
	 *
	 * If the user doesn't click the button, the beforeNavigate hook below
	 * will trigger the same clean update flow on their next navigation.
	 */
	$effect(() => {
		if (browser && updated.current && !updateNotificationShown) {
			console.log('[Layout] New app version detected, showing notification');
			updateNotificationShown = true;

			notificationStore.softwareUpdate(
				'A new version is available. It will load on your next navigation.',
				{
					actionLabel: 'Refresh now',
					onAction: () => {
						console.log('[Layout] User triggered clean update via notification button');
						performCleanUpdate();
					},
					dismissible: true
				}
			);
		}
	});

	/**
	 * Auto-refresh on navigation when an update is detected.
	 * This prevents chunk loading errors (404s for old JS chunks) during navigation.
	 *
	 * When user navigates and an update is available:
	 * - Instead of client-side navigation (which might fail due to missing chunks)
	 * - We clear all caches, activate any waiting SW, and do a full page reload
	 *
	 * Uses performCleanUpdate() to ensure a completely fresh app state.
	 */
	beforeNavigate(({ willUnload, to }) => {
		if (updated.current && !willUnload && to?.url) {
			console.log('[Layout] New version detected, performing clean update on navigation');
			performCleanUpdate(to.url.href);
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
