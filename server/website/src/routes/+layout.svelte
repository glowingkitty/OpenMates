<script lang="ts">
    
    // Import all necessary styles
    import '$lib/styles/fonts.css';
    import '$lib/styles/icons.css';
    import '$lib/styles/buttons.css';
    import '$lib/styles/fields.css';
    import '$lib/styles/cards.css';
    import '$lib/styles/chat.css';
    import '$lib/styles/mates.css';
    import '$lib/styles/theme.css';
    import { replaceOpenMates } from '$lib/actions/replaceText';
    import Header from './components/Header.svelte';
    import Footer from './components/Footer.svelte';
    import MetaTags from './components/MetaTags.svelte';
    import { theme, toggleTheme, initializeTheme } from '$lib/stores/theme';
    import { onMount } from 'svelte';
    import { browser } from '$app/environment';
    import { SUPPORTED_LOCALES, isValidLocale } from '$lib/i18n/types';
    import { waitLocale, locale } from 'svelte-i18n';

    // Initialize translations
    let mounted = false;
    let appLoaded = false;

    // Combined initialization for theme and locale
    onMount(async () => {
        // Initialize theme
        initializeTheme();
        
        // Initialize locale from stored preference or browser language
        if (browser) {
            const savedLocale = localStorage.getItem('preferredLanguage');
            if (savedLocale && isValidLocale(savedLocale)) {
                // Only use saved locale if explicitly set by user
                locale.set(savedLocale);
            } else {
                // Use browser language
                const browserLang = navigator.language.split('-')[0];
                if (isValidLocale(browserLang)) {
                    locale.set(browserLang);
                } else {
                    locale.set('en');
                }
            }
        }
        
        // Wait for locale to be ready
        await waitLocale();
        appLoaded = true;
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
        <!-- Optional: Add loading indicator -->
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
    /* Global styles moved from global.css */
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
</style>