<!--
    Minimal layout for the /status page.
    No navigation chrome, no auth — just the status dashboard.
    Dark mode is handled by the anti-flicker script in app.html which sets
    data-theme on <html> before first paint. CSS variables from theme.css
    resolve automatically.
-->
<script lang="ts">
    import '@repo/ui/src/styles/theme.css';
    import '@repo/ui/src/styles/fonts.css';
    import type { Snippet } from 'svelte';

    let { children }: { children: Snippet } = $props();
</script>

<div class="status-layout">
    {@render children()}
</div>

<style>
    .status-layout {
        min-height: 100vh;
        background-color: var(--color-grey-5);
        font-family: var(--font-family, -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif);
        color: var(--color-font-primary);
    }
</style>
