import { _ } from 'svelte-i18n';
import { derived, type Readable } from 'svelte/store';
import DOMPurify from 'dompurify';

type TranslateFunction = (key: string, vars?: Record<string, any>) => string;

export const text = derived(_, ($translate): TranslateFunction => {
    return (key: string, vars = {}) => {
        if (!$translate) return key; // Fallback to key if translation function is not ready
        const translated = $translate(key, vars);
        return DOMPurify.sanitize(translated, {
            ALLOWED_TAGS: ['mark', 'span', 'bold'],
            ALLOWED_ATTR: ['class']
        });
    };
});

export type TextStore = Readable<TranslateFunction>;
