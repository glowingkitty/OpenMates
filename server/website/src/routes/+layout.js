import '@fontsource-variable/lexend-deca';
import { browser } from '$app/environment';
import { init, register } from 'svelte-i18n';

export const prerender = true;
export const ssr = true;



register('en', () => import('../locales/en.json'));
register('de', () => import('../locales/de.json'));

init({
    fallbackLocale: 'en',
    initialLocale: browser ? window.navigator.language : 'en',
}); 