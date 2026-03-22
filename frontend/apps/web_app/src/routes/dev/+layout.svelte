<!--
  Dev-only layout gate.
  All routes under /dev/ are only accessible on:
  - Local dev server (localhost)
  - Dev deployment (app.dev.openmates.org)
  In production (app.openmates.org), this shows a "not available" message.
-->
<script lang="ts">
	import { browser } from '$app/environment';

	let { children } = $props();

	/**
	 * Check if the current hostname is a dev environment.
	 * Allows access on:
	 * - localhost / 127.0.0.1 (local dev server via pnpm dev)
	 * - app.dev.openmates.org (Vercel auto-deployed dev branch)
	 * Blocks access on production (app.openmates.org, openmates.org).
	 */
	let isDevEnvironment = $derived.by(() => {
		if (!browser) return false;
		const hostname = window.location.hostname;
		return (
			hostname === 'localhost' ||
			hostname === '127.0.0.1' ||
			hostname.includes('.dev.') ||
			hostname.includes('-dev.')
		);
	});
</script>

{#if isDevEnvironment}
	{@render children()}
{:else}
	<div class="not-available">
		<h1>Not Available</h1>
		<p>Dev tools are only available in development environments.</p>
	</div>
{/if}

<style>
	.not-available {
		display: flex;
		flex-direction: column;
		align-items: center;
		justify-content: center;
		height: 100vh;
		color: var(--color-font-primary);
		font-family: var(--font-primary, 'Lexend Deca Variable'), sans-serif;
		gap: 8px;
	}

	.not-available h1 {
		font-size: 24px;
		font-weight: 600;
	}

	.not-available p {
		font-size: 14px;
		color: var(--color-font-tertiary);
	}
</style>
