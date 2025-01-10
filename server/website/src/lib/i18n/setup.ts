import { browser } from '$app/environment';
import { init, register, waitLocale } from 'svelte-i18n';

// Initialize translations
export const setupI18n = async () => {
    // Register available translations
    register('en', () => import('../../locales/en.json'));
    register('de', () => import('../../locales/de.json'));

    // Get initial locale from browser or fallback to 'en'
    const initialLocale = browser 
        ? window.navigator.language.split('-')[0] 
        : 'en';

    // Initialize i18n with configuration
    init({
        fallbackLocale: 'en',
        initialLocale: initialLocale,
    });

    // Wait for the initial locale to be loaded
    return await waitLocale();
}; 