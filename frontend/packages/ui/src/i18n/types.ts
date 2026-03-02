// NOTE: The single source of truth for supported locales is languages.json.
// This re-export keeps backwards compatibility for any code that imports
// isValidLocale / SupportedLocale from here.
import { LANGUAGE_CODES, isLanguageSupported } from "./languages";

export const SUPPORTED_LOCALES = LANGUAGE_CODES as readonly string[];
export type SupportedLocale = string;

declare module "svelte-i18n" {
  export type Locale = SupportedLocale;
}

/** Returns true if the locale code exists in languages.json */
export function isValidLocale(locale: string): boolean {
  return isLanguageSupported(locale);
}
