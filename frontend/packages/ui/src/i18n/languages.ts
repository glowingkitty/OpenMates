/**
 * Single source of truth for supported languages in OpenMates
 * 
 * This file reads from languages.json which is the actual source of truth.
 * Both frontend (TypeScript/JavaScript) and backend (Python) read from the same JSON file.
 * 
 * Languages are ordered by:
 * 1. English (en) - always first
 * 2. German (de) - always second
 * 3. Rest by global speaker count (most to least)
 */

import languagesData from './languages.json';

export type Language = {
    code: string;
    name: string;
    shortCode: string;
    nativeName?: string;
};

/**
 * Supported languages - loaded from languages.json (single source of truth)
 */
export const SUPPORTED_LANGUAGES: Language[] = languagesData.languages;

/**
 * Get language codes in order (for scripts and backend)
 */
export const LANGUAGE_CODES = SUPPORTED_LANGUAGES.map(lang => lang.code);

/**
 * Get supported locale codes (for svelte-i18n compatibility)
 */
export const SUPPORTED_LOCALES = LANGUAGE_CODES as readonly string[];

/**
 * Get language by code
 */
export function getLanguageByCode(code: string): Language | undefined {
    return SUPPORTED_LANGUAGES.find(lang => lang.code === code);
}

/**
 * Check if a language code is supported
 */
export function isLanguageSupported(code: string): boolean {
    return SUPPORTED_LANGUAGES.some(lang => lang.code === code);
}

