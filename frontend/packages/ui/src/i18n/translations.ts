import { _ } from 'svelte-i18n';
import { derived, type Readable } from 'svelte/store';
import { browser } from '$app/environment';

type TranslateFunction = (key: string, vars?: Record<string, any>) => string;

/**
 * Missing-translation placeholder prefix.
 * When a key has no translation, $text returns "[T:<key>]" so that:
 *   1. It's immediately visible in the UI during development
 *   2. Playwright tests can assert `not.toContainText('[T:')` to catch gaps
 */
const MISSING_PREFIX = '[T:';
const MISSING_SUFFIX = ']';
const missingPlaceholder = (key: string) => `${MISSING_PREFIX}${key}${MISSING_SUFFIX}`;

/**
 * Dev-mode missing translation tracker.
 * Logs a console.error the FIRST time each missing key is encountered on the client,
 * so developers immediately see which translations are missing without console spam.
 * Only active in dev mode (import.meta.env.DEV) and only on the client (not during SSR,
 * where all keys intentionally return [T:] placeholders).
 */
const reportedMissingKeys = new Set<string>();
function reportMissingTranslation(key: string, reason: string): void {
    if (!import.meta.env.DEV) return;
    if (reportedMissingKeys.has(key)) return;
    reportedMissingKeys.add(key);
    console.error(
        `[i18n] MISSING TRANSLATION: "${key}" (${reason}) — visible as [T:${key}] in the UI. ` +
        `Add this key to the YAML source files in i18n/sources/.`
    );
}

// Simple fallback that returns a visible placeholder during SSR
const passThroughTranslate: TranslateFunction = (key: string) => missingPlaceholder(key);

// Create an SSR-safe text store
// During SSR: provides a placeholder function so missing keys are visible
// On client: uses svelte-i18n with DOM Purify sanitization  
let DOMPurify: any = null;
if (browser && typeof window !== 'undefined') {
    // Only import DOMPurify on the client side
    import('dompurify').then(module => {
        DOMPurify = module.default;
    });
}

export const text: Readable<TranslateFunction> = browser
    ? derived(_, ($translate): TranslateFunction => {
          return (key: string, vars = {}) => {
              if (!$translate) {
                  reportMissingTranslation(key, 'translate function not ready');
                  return missingPlaceholder(key);
              }

              // Strip the svelte-i18n "default" option so that missing keys are
              // never silently hidden by a hardcoded fallback string.
              // Callers should NOT pass { default: '...' } — all translations
              // must exist in the locale files.
              if (vars && 'default' in vars) {
                  const cleanVars = { ...vars };
                  delete cleanVars.default;
                  vars = cleanVars;
              }

              // Internally append ".text" to the key before looking it up.
              // The JSON locale files store values as { text: "..." } objects to prevent
              // key collisions (e.g., "settings.privacy" can have both a direct value
              // and child keys like "settings.privacy.description"). Callers of $text()
              // never need to know about this — they just use $text('settings.privacy').
              const lookupKey = key + '.text';

              // Try to translate, catch if i18n not initialized yet
              let translated: string;
              try {
                  translated = $translate(lookupKey, vars);
              } catch (err) {
                  // i18n not ready yet — show visible placeholder
                  reportMissingTranslation(key, 'i18n not initialized');
                  return missingPlaceholder(key);
              }

              // If svelte-i18n returns the lookup key itself, it means the key was not found.
              // Return a clearly visible placeholder so missing translations are never hidden.
              if (translated === lookupKey) {
                  reportMissingTranslation(key, 'key not found in locale');
                  return missingPlaceholder(key);
              }

              // Guard against non-string values from svelte-i18n.
              // If a key points to an intermediate node (object) instead of a leaf string,
              // $translate() may return that object. Without this check, it would render
              // as "[object Object]" in the UI. Log the offending key for debugging.
              if (typeof translated !== 'string') {
                  reportMissingTranslation(key, `returned ${typeof translated} instead of string`);
                  return missingPlaceholder(key);
              }

              // Only sanitize if DOMPurify is loaded
              if (DOMPurify) {
                  return DOMPurify.sanitize(translated, {
                      ALLOWED_TAGS: [
                          'mark', 'span', 'bold',
                          'ul', 'li', 'p',
                          'h1', 'h2', 'h3', 'h4', 'h5', 'h6',
                          'br', 'strong', 'em', 'i', 'b',
                          'small', 'sub', 'sup'
                      ],
                      ALLOWED_ATTR: ['class']
                  });
              }

              return translated;
          };
      })
    : {
          subscribe: (fn: (value: TranslateFunction) => void) => {
              // SSR: immediately call with placeholder function
              fn(passThroughTranslate);
              return () => {}; // no-op unsubscribe
          }
      } as any;

export type TextStore = Readable<TranslateFunction>;
