import { _ } from 'svelte-i18n';
import { derived, type Readable } from 'svelte/store';
import DOMPurify from 'dompurify';

type TranslateFunction = (key: string, vars?: Record<string, any>) => string;

export const text = derived(_, ($translate): TranslateFunction => {
    return (key: string, vars = {}) => 
        DOMPurify.sanitize($translate(key, vars), {
            ALLOWED_TAGS: ['mark', 'span', 'bold'],
            ALLOWED_ATTR: ['class']
        });
});

export type TextStore = Readable<TranslateFunction>;
