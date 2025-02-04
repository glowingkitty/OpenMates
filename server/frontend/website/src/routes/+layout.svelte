<script lang="ts">
    // Import styles directly
    import '@openmates/shared/src/styles/buttons.css';
    import '@openmates/shared/src/styles/fields.css';
    import '@openmates/shared/src/styles/cards.css';
    import '@openmates/shared/src/styles/chat.css';
    import '@openmates/shared/src/styles/mates.css';
    import '@openmates/shared/src/styles/theme.css';
    import '@openmates/shared/src/styles/fonts.css';
    import '@openmates/shared/src/styles/icons.css';
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
    } from '@openmates/shared';
    import { onMount } from 'svelte';
    import { browser } from '$app/environment';
    import { waitLocale, locale } from 'svelte-i18n';

    // Initialize translations
    let mounted = false;
    let appLoaded = false;

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
    $: if (browser) {
        document.documentElement.setAttribute('data-theme', $theme);
    }
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
            <slot />
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
        width: 100%;
        max-width: 100%;
        overflow-x: hidden;
    }

    :global(html) {
        overflow-x: hidden;
    }

    .app-loading {
        min-height: 100vh;
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
        color: var(--color-text);
    }
</style>