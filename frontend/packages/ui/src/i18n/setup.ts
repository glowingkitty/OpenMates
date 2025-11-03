import { register, init, getLocaleFromNavigator } from 'svelte-i18n';
import { browser } from '$app/environment';
import { SUPPORTED_LOCALES, isValidLocale } from './types';
import { waitForTranslations } from '../stores/i18n';

const loadLocaleData = async (locale: string) => {
    let module;
    try {
        module = await import(`./locales/${locale}.json`);
        return module.default;
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

// Register all supported locales immediately when module loads
// This ensures the i18n system is set up before any components try to use it
SUPPORTED_LOCALES.forEach(locale => {
    register(locale, () => loadLocaleData(locale));
});

// Initialize i18n immediately when module loads (synchronous)
// This MUST happen before any component tries to use $_ or other i18n functions
// The init() call sets up the locale store and makes waitLocale() work properly
init({
    fallbackLocale: 'en',
    initialLocale: browser 
        ? getCurrentLanguage() // Use getCurrentLanguage to determine initial locale
        : 'en',
    warnOnMissingMessages: true
});

// Async function for explicit initialization if needed
// This is mainly for backwards compatibility - the init() above already ran
export async function setupI18n() {
    // Wait for initial translations to load
    await waitForTranslations();
}