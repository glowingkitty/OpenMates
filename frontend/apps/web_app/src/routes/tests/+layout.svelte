<!--
  Dev-only gate for the Playwright recording browser.
  These pages are available on local dev and app.dev.openmates.org only.
  Production renders a static not-available message and does not fetch data.
-->
<script lang="ts">
	import { browser } from '$app/environment';

	let { children } = $props();

	let isDevEnvironment = $derived.by(() => {
		if (!browser) return false;
		const hostname = window.location.hostname;
		return (
			hostname === 'localhost' ||
			hostname === '127.0.0.1' ||
			hostname.includes('.dev.') ||
			hostname.includes('-dev.') ||
			hostname.endsWith('.vercel.app')
		);
	});
</script>

{#if isDevEnvironment}
	{@render children()}
{:else}
	<div class="not-available">
		<h1>Not Available</h1>
		<p>Test recordings are only available in development environments.</p>
	</div>
{/if}

<style>
	.not-available {
		display: flex;
		flex-direction: column;
		align-items: center;
		justify-content: center;
		min-height: 100vh;
		gap: 8px;
		color: var(--color-font-primary);
		font-family: var(--font-primary, 'Lexend Deca Variable'), sans-serif;
		background: var(--color-grey-0);
	}

	.not-available h1 {
		margin: 0;
		font-size: 24px;
		font-weight: 600;
	}

	.not-available p {
		margin: 0;
		font-size: 14px;
		color: var(--color-font-tertiary);
	}
</style>
