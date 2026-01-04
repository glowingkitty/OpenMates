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
        // Config
        loadMetaTags,
        // Stores
        theme,
        initializeTheme,
        initializeServerStatus,
        // i18n
        isValidLocale
    } from '@repo/ui';
    import { onMount } from 'svelte';
    import { browser } from '$app/environment';
    import { waitLocale, locale } from 'svelte-i18n';

    let loaded = $state(false);
    let { children } = $props();

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

    // Reset to system preference
    function resetToSystemPreference() {
        if (browser) {
            localStorage.removeItem('theme_preference');
            localStorage.removeItem('theme');
            initializeTheme();
        }
    }

    // Helper function to safely check localStorage
    function getThemePreference() {
        if (browser) {
            return localStorage?.getItem('theme_preference');
        }
        return null;
    }

    // Watch theme changes and update document attribute
    $effect(() => {
        if (browser) {
            document.documentElement.setAttribute('data-theme', $theme);
        }
    });

    // Removed reactive block setting $locale
</script>

{#if loaded}
    <MetaTags />
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