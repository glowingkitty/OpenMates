<!--
    Minimal layout for the /status page.
    No navigation chrome, no auth — just the status dashboard.
    Imports base theme CSS and initializes dark mode detection.
-->
<script lang="ts">
    import '@repo/ui/src/styles/theme.css';
    import '@repo/ui/src/styles/fonts.css';
    import { onMount } from 'svelte';
    import { browser } from '$app/environment';
    import { initializeTheme, theme } from '@repo/ui';
    import type { Snippet } from 'svelte';

    let { children }: { children: Snippet } = $props();

    onMount(() => {
        if (browser) {
            initializeTheme();
            // Apply theme to documentElement so CSS variables from theme.css work
            // (theme.css uses [data-theme="dark"] on :root / html)
            const unsub = theme.subscribe((t) => {
                document.documentElement.setAttribute('data-theme', t);
            });
            return unsub;
        }
    });
</script>

<div class="status-layout">
    {@render children()}
</div>

<style>
    .status-layout {
        min-height: 100vh;
        background-color: var(--color-grey-5, #fafafa);
        font-family: var(--font-family, -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif);
        color: var(--color-font-primary, #222);
    }
</style>
