import { derived, writable } from 'svelte/store';
import en from '../locales/en.json';
import de from '../locales/de.json';

type Locale = 'en' | 'de';
type Translations = Record<Locale, typeof en>;

export const locale = writable<Locale>('en');

const translations: Translations = {
    en,
    de
};

export const t = derived(
    locale,
    ($locale) => (key: string) => {
        const parts = key.split('.');
        let translation: any = translations[$locale];

        for (const part of parts) {
            translation = translation?.[part];
            if (!translation) {
                console.warn(`Missing translation: ${key} for locale: ${$locale}`);
                return key;
            }
        }

        return typeof translation === 'object' ? translation.text : translation;
    }
); 