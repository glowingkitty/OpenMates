<script lang="ts">
    import '@website-styles/buttons.css';
    import '@website-styles/fonts.css';
    import '@website-styles/icons.css';
    import '@website-styles/buttons.css';
    import '@website-styles/fields.css';
    import '@website-styles/cards.css';
    import '@website-styles/chat.css';
    import '@website-styles/mates.css';
    import '@website-styles/theme.css';
    import { locale } from 'svelte-i18n';
    import { theme, toggleTheme, initializeTheme } from '@website-stores/theme';
    import { replaceOpenMates } from '@website-actions/replaceText';
    import { onMount } from 'svelte';
    import { browser } from '$app/environment';

    // Initialize theme on mount
    onMount(async () => {
        initializeTheme();
        
        // Set initial language based on browser preference
        if (browser) {
            const browserLang = navigator.language.split('-')[0];
            if (browserLang === 'en' || browserLang === 'de') {
                locale.set(browserLang);
            }
        }
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

<main use:replaceOpenMates>
    <slot />
</main>

<style>
    /* Apply background color to the body */
    :global(body) {
        background-color: var(--color-grey-0);
    }
</style> 