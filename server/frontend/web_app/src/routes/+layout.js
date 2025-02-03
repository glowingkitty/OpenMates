import '@fontsource-variable/lexend-deca';
import { setupI18n } from '@website-lib/i18n/setup';

export const prerender = true;
export const ssr = true;

// Wait for translations to be loaded before rendering
export const load = async () => {
    await setupI18n();
    return {};
}; 