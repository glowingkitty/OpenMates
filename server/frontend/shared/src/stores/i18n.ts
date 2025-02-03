import { writable } from 'svelte/store';
import { waitLocale } from 'svelte-i18n';

export const i18nLoaded = writable(false);

// Helper function to wait for translations
export async function waitForTranslations() {
    await waitLocale();
    i18nLoaded.set(true);
}

// Helper function to reset loading state
export function resetI18nLoading() {
    i18nLoaded.set(false);
} 