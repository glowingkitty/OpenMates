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

              // Try to translate, catch if i18n not initialized yet
              let translated: string;
              try {
                  translated = $translate(key, vars);
              } catch (err) {
                  // i18n not ready yet, return the key as fallback
                  console.debug('[i18n] Translation not ready for key:', key);
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
