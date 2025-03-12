import { register, init, getLocaleFromNavigator } from 'svelte-i18n';
import { browser } from '$app/environment';
import { SUPPORTED_LOCALES, isValidLocale } from './types';
import { waitForTranslations } from '../stores/i18n';

// Function to replace OpenMates with styled version in all translation strings
function processTranslations(translations: any): any {
    const result: any = {};
    for (const [key, value] of Object.entries(translations)) {
        if (typeof value === 'object' && value !== null) {
            result[key] = processTranslations(value);
        } else if (typeof value === 'string' && value.includes('OpenMates')) {
            result[key] = value.replace(/OpenMates/g, '<strong><mark>Open</mark><span style="color: var(--color-grey-100);">Mates</span></strong>');
        } else {
            result[key] = value;
        }
    }
    return result;
}

const loadLocaleData = async (locale: string) => {
    let module;
    try {
        module = await import(`./locales/${locale}.json`);
        // Process translations before returning
        return processTranslations(module.default);
    } catch (e) {
        console.error(`Could not load locale data for ${locale}`, e);
        return null;
    }
};

// Function to normalize locale code to match our supported locales
function normalizeLocale(locale: string): string {
    // First check if the locale is already supported as-is
    if (isValidLocale(locale)) {
        return locale;
    }
    
    // If not, try to match the language part (before the hyphen)
    const languagePart = locale.split('-')[0].toLowerCase();
    if (isValidLocale(languagePart)) {
        return languagePart;
    }
    
    return 'en'; // fallback to English if no match
}

// Function to get the current language - simplified to prioritize browser language
export function getCurrentLanguage(): string {
    if (browser) {
        // Only use preferredLanguage if explicitly set by user, otherwise use browser language
        const userPreference = localStorage.getItem('preferredLanguage');
        if (userPreference) {
            return userPreference;
        }
        const browserLang = normalizeLocale(getLocaleFromNavigator() || 'en');
        return browserLang;
    }
    return 'en'; // Fallback for server-side rendering
}

export async function setupI18n() {
    // Register all supported locales
    SUPPORTED_LOCALES.forEach(locale => {
        register(locale, () => loadLocaleData(locale));
    });

    // Initialize with fallback locale and load initial data
    init({
        fallbackLocale: 'en',
        initialLocale: browser 
            ? getCurrentLanguage() // Use getCurrentLanguage to determine initial locale
            : 'en',
        warnOnMissingMessages: true
    });

    // Wait for initial translations to load
    await waitForTranslations();
}