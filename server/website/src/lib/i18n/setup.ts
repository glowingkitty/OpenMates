import { browser } from '$app/environment';
import { init, register } from 'svelte-i18n';

// Register translations
register('en', () => import('../../locales/en.json'));
register('de', () => import('../../locales/de.json'));

// Initialize i18n with a default locale
const initI18n = () => {
    init({
        fallbackLocale: 'en',
        initialLocale: 'en'  // Always start with 'en' for SSR
    });
};

export { initI18n }; 