<!--
    Minimal layout for the /s/ short URL redirect page.
    No navigation chrome — just the redirect content.
    Imports only the base theme CSS needed for styling.
-->
<script lang="ts">
    import '@repo/ui/src/styles/theme.css';
    import '@repo/ui/src/styles/fonts.css';
    import type { Snippet } from 'svelte';

    let { children }: { children: Snippet } = $props();
</script>

<div class="short-url-layout">
    {@render children()}
</div>

<style>
    .short-url-layout {
        min-height: 100vh;
        display: flex;
        align-items: center;
        justify-content: center;
        background-color: var(--color-grey-5, #fafafa);
        font-family: var(--font-family, -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif);
    }
</style>
