import { register, init, getLocaleFromNavigator } from 'svelte-i18n';
import { browser } from '$app/environment';
import { SUPPORTED_LOCALES, isValidLocale } from './types';

const loadLocaleData = async (locale: string) => {
    let module;
    try {
        module = await import(`../../locales/${locale}.json`);
        return module.default;
    } catch (e) {
        console.error(`Could not load locale data for ${locale}`, e);
        return null;
    }
};

export function setupI18n() {
    // Register all supported locales
    SUPPORTED_LOCALES.forEach(locale => {
        register(locale, () => loadLocaleData(locale));
    });

    // Initialize with fallback locale and load initial data
    init({
        fallbackLocale: 'en',
        initialLocale: browser 
            ? localStorage.getItem('preferredLanguage') || getLocaleFromNavigator() 
            : 'en'
    });
} 