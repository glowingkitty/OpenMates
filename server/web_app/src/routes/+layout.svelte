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
    import { waitLocale } from 'svelte-i18n';
    import { SUPPORTED_LOCALES, isValidLocale } from '@website-lib/i18n/types';

    let loaded = false;

    onMount(async () => {
        await waitLocale();
        loaded = true;
        initializeTheme();

        if (browser) {
            const browserLang = navigator.language.split('-')[0].toLowerCase();
            if (isValidLocale(browserLang)) {
                locale.set(browserLang);
            } else {
                locale.set('en'); // fallback to English
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

    // Set initial language based on browser preference or stored setting
    $: if (browser) {
        const browserLang = navigator.language.split('-')[0].toLowerCase();
        if (isValidLocale(browserLang)) {
            $locale = browserLang;
        } else {
            $locale = 'en'; // fallback to English
        }
    }
</script>

{#if loaded}
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