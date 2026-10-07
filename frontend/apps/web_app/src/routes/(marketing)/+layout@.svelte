<script lang="ts">
  import '@repo/ui/src/styles/icon-urls.generated.css';
	import '@repo/ui/src/styles/theme.css';
	import '@repo/ui/src/styles/fonts.css';
	import '@repo/ui/src/styles/icons.css';
	import '@repo/ui/src/styles/buttons.css';
	import '@fontsource-variable/lexend-deca';
	import type { Snippet } from 'svelte';

	let { children }: { children: Snippet } = $props();
</script>

<div class="marketing-viewport">{@render children()}</div>

<style>
	.marketing-viewport { height: 100dvh; }
	:global(body) {
		margin: 0;
		opacity: 1;
		animation: none;
		background: var(--color-grey-0);
		color: var(--color-font-primary);
		font-family: var(--font-primary);
	}
</style>
