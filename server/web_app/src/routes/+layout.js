import '@fontsource-variable/lexend-deca';
import { browser } from '$app/environment';
import { init, register } from 'svelte-i18n';

export const prerender = true;
export const ssr = true;

// Initialize translations before any components are loaded
const initializeTranslations = () => {
    register('en', () => import('@website-locales/en.json'));
    register('de', () => import('@website-locales/de.json'));

    init({
        fallbackLocale: 'en',
        initialLocale: browser ? window.navigator.language : 'en',
    });
};

// Wait for translations to be loaded before rendering
export const load = async () => {
    await initializeTranslations();
    return {};
}; 