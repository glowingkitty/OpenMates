import { browser } from '$app/environment';
import { init, register } from 'svelte-i18n';

// Register translations
register('en', () => import('../../locales/en.json'));
register('de', () => import('../../locales/de.json'));

// Initialize i18n with a default locale
const initI18n = () => {
    init({
        fallbackLocale: 'en',
        initialLocale: browser ? navigator.language.split('-')[0] : 'en'
    });
};

export { initI18n }; 