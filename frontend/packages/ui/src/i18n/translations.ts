import { _ } from 'svelte-i18n';
import { derived, type Readable } from 'svelte/store';
import { browser } from '$app/environment';

type TranslateFunction = (key: string, vars?: Record<string, any>) => string;

// Simple fallback that returns the key as-is
const passThroughTranslate: TranslateFunction = (key: string) => key;

// Create an SSR-safe text store
// During SSR: provides a simple passthrough function
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
              if (!$translate) return key;

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
                  // i18n not ready yet, return the key as fallback
                  console.debug('[i18n] Translation not ready for key:', key);
                  return key;
              }

              // If svelte-i18n returns the lookup key itself, it means the key was not found.
              // Return the original key (without .text) as fallback for better debugging.
              if (translated === lookupKey) {
                  return key;
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
              // SSR: immediately call with passthrough function
              fn(passThroughTranslate);
              return () => {}; // no-op unsubscribe
          }
      } as any;

export type TextStore = Readable<TranslateFunction>;
