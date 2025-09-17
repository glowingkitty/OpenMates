<script lang="ts">
    import '@repo/ui/src/styles/buttons.css';
    import '@repo/ui/src/styles/fields.css';
    import '@repo/ui/src/styles/cards.css';
    import '@repo/ui/src/styles/chat.css';
    import '@repo/ui/src/styles/mates.css';
    import '@repo/ui/src/styles/theme.css';
    import '@repo/ui/src/styles/fonts.css';
    import '@repo/ui/src/styles/icons.css';
    import {
        // components
        Header,
        Footer,
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

    // Initialize translations
    let mounted = false;
    let appLoaded = $state(false);
    let { children } = $props();

    // Combined initialization
    async function initializeApp() {
        try {
            // Initialize theme
            initializeTheme();

            // Initialize i18n
            if (browser) {
                const savedLocale = localStorage.getItem('preferredLanguage');
                if (savedLocale && isValidLocale(savedLocale)) {
                    locale.set(savedLocale);
                } else {
                    const browserLang = navigator.language.split('-')[0];
                    locale.set(isValidLocale(browserLang) ? browserLang : 'en');
                }
            }

            // Wait for translations to be ready
            await waitLocale();

            // Load meta tags after translations are ready
            await loadMetaTags();

            appLoaded = true;
        } catch (error) {
            console.error('Failed to initialize app:', error);
            // Consider showing an error state to the user
        }
    }

    onMount(() => {
        initializeApp();
        mounted = true;
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
</script>

{#if !appLoaded}
    <div class="app-loading">
        <!-- Add a loading spinner or placeholder -->
        <div class="loading-spinner">Loading...</div>
    </div>
{:else}
    <div class="app">
        <MetaTags />
        <Header />
        <main use:replaceOpenMates>
            {@render children()}
        </main>
        <Footer />
    </div>
{/if}

<style>
    :global(body) {
        margin: 0;
        overflow-x: hidden;
        position: relative;
        max-width: 100vw;
    }

    :global(section) {
        overflow: hidden;
    }

    :global(.centered) {
        display: flex;
        align-items: center;
        justify-content: center;
        flex-direction: column;
    }

    :global(.content) {
        max-width: 1000px;
        margin: 0 auto;
    }

    /* Main content styling */
    main {
        min-height: calc(100vh - var(--header-height) - var(--footer-height));
        min-height: calc(100dvh - var(--header-height) - var(--footer-height));
        width: 100%;
        max-width: 100%;
        overflow-x: hidden;
    }

    :global(html) {
        overflow-x: hidden;
    }

    .app-loading {
        min-height: 100vh;
        min-height: 100dvh;
        display: flex;
        align-items: center;
        justify-content: center;
        /* Optional: Add loading animation styles */
    }

    .loading-spinner {
        display: flex;
        align-items: center;
        justify-content: center;
        min-height: 100vh;
        min-height: 100dvh;
        color: var(--color-text);
    }
</style>
