<script lang="ts">
	import '@repo/ui/src/styles/buttons.css';
	import '@repo/ui/src/styles/theme.css';
	import '@repo/ui/src/styles/fonts.css';
	import '@repo/ui/src/styles/icons.css';
	import '@repo/ui/src/styles/icon-urls.generated.css';

	let { children } = $props();
</script>

<svelte:head>
	<meta name="theme-color" content="#ffffff" />
</svelte:head>

{@render children()}
