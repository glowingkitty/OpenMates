import { browser } from '$app/environment'; // SvelteKit helper to detect client environment

// Instead of importing the CSS statically (which breaks SSR), we load it dynamically on the browser.
// This prevents Node from trying to process the CSS file during SSR rendering.
if (browser) {
    // Dynamically import the font CSS only in the browser.
    import('@fontsource-variable/lexend-deca')
        .then(() => {
            console.log('Font lexend-deca loaded successfully on the client.');
        })
        .catch((err) => {
            console.error('Failed to load lexend-deca font:', err);
        });
}

import { setupI18n } from '@repo/ui';

export const prerender = true;
export const ssr = true;

// Load function that waits for translations to be loaded before rendering
export const load = async () => {
    // Await the i18n setup, ensuring translations are available.
    await setupI18n();
    return {};
}; 
