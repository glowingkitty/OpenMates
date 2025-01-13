<script lang="ts">
    import type { Locale } from 'svelte-i18n';
    import '$lib/i18n/types';  // Import the type declaration
    
    // Import all necessary styles
    import '$lib/styles/fonts.css';
    import '$lib/styles/icons.css';
    import '$lib/styles/buttons.css';
    import '$lib/styles/fields.css';
    import '$lib/styles/cards.css';
    import '$lib/styles/chat.css';
    import '$lib/styles/mates.css';
    import '$lib/styles/theme.css';
    import { locale } from '$lib/i18n';
    import { replaceOpenMates } from '$lib/actions/replaceText';
    import Header from './components/Header.svelte';
    import Footer from './components/Footer.svelte';
    import MetaTags from './components/MetaTags.svelte';
    import { theme, toggleTheme, initializeTheme } from '$lib/stores/theme';
    import { onMount } from 'svelte';
    import { browser } from '$app/environment';
    import { SUPPORTED_LOCALES, isValidLocale } from '$lib/i18n/types';
    import { waitLocale } from 'svelte-i18n';

    // Initialize translations
    let mounted = false;

    // Combined initialization for theme and locale
    onMount(async () => {
        // Initialize theme
        initializeTheme();
        
        // Wait for locale to be ready
        await waitLocale();
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

    // Set initial language based on browser preference or stored setting
    $: if (browser) {
        const browserLang = navigator.language.split('-')[0];
        if (browserLang === 'en' || browserLang === 'de') {
            $locale = browserLang as 'en' | 'de';
        }
    }

    // Handle locale changes
    $: if (mounted && browser) {
        const savedLocale = localStorage.getItem('preferredLanguage');
        if (savedLocale && isValidLocale(savedLocale)) {
            locale.set(savedLocale);
            // Force a wait for new translations to load
            waitLocale();
        }
    }
</script>

<div class="app">
    <MetaTags />
    <Header />
    <main use:replaceOpenMates>
        <slot />
    </main>
    <Footer />
</div>

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
</style>