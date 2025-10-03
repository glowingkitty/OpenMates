/**
 * Documentation Index Page Loader
 * 
 * Loads the root documentation structure for the index page.
 * This provides the main entry point to the documentation system.
 */

import type { PageLoad } from './$types';
import docsData from '$lib/generated/docs-data.json';

export const prerender = true; // Enable static generation

export const load: PageLoad = () => {
    return {
        type: 'index',
        structure: docsData.structure
    };
};
