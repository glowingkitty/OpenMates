/**
 * Loader for /newsletter/<slug> landing pages.
 *
 * Each newsletter email contains a clickable video thumbnail that deep-links
 * to this route. We never embed YouTube — the video lives on our own asset
 * host, so recipients are not tracked by a third party when they click
 * through from their inbox.
 */

import { error } from '@sveltejs/kit';
import type { PageLoad } from './$types';
import { findNewsletter } from '$lib/newsletters';

export const load: PageLoad = ({ params }) => {
    const entry = findNewsletter(params.slug);
    if (!entry) {
        throw error(404, `Newsletter '${params.slug}' not found`);
    }
    return { newsletter: entry };
};
