<script lang="ts">
    import '@repo/ui/src/styles/buttons.css';
    import '@repo/ui/src/styles/fields.css';
    import '@repo/ui/src/styles/cards.css';
    import '@repo/ui/src/styles/chat.css';
    import '@repo/ui/src/styles/mates.css';
    import '@repo/ui/src/styles/theme.css';
    import '@repo/ui/src/styles/fonts.css';
    import '@repo/ui/src/styles/icons.css';
    import '@repo/ui/src/styles/auth.css';
    import {
        // components
        MetaTags,
        // Actions
        replaceOpenMates,
        // Config
        loadMetaTags,
        // Stores
        theme,
        initializeTheme,
        // i18n
        isValidLocale
    } from '@repo/ui';
    import { onMount } from 'svelte';
    import { browser } from '$app/environment';
    import { waitLocale, locale } from 'svelte-i18n';

    let loaded = false;

    onMount(async () => {
        await waitLocale();
        loaded = true;

        // Load meta tags after translations are ready
        await loadMetaTags();

        initializeTheme();

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
    $: if (browser) {
        document.documentElement.setAttribute('data-theme', $theme);
    }

    // Removed reactive block setting $locale
</script>

{#if loaded}
    <MetaTags />
    <main use:replaceOpenMates>
        <slot />
    </main>
{/if}

<style>
    /* Apply background color to the body */
    :global(body) {
        background-color: var(--color-grey-0);
    }
</style> 