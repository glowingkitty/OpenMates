import '@fontsource-variable/lexend-deca';
import { setupI18n } from '@openmates/shared';

export const prerender = true;
export const ssr = true;

// Wait for translations to be loaded before rendering
export const load = async () => {
    await setupI18n();
    return {};
}; 