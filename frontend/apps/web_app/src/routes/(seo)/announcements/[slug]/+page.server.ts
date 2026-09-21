import { redirect } from '@sveltejs/kit';
import type { PageServerLoad } from './$types';

const migratedReleaseSlugs = new Set([
	'introducing-openmates-v09',
	'introducing-openmates-v010',
	'introducing-openmates-v011'
]);

/** Preserve newsletter and shared legacy links while moving announcements to News. */
export const load: PageServerLoad = async ({ params }) => {
	const destination = migratedReleaseSlugs.has(params.slug)
		? `/news/${encodeURIComponent(params.slug)}`
		: '/news';
	redirect(308, destination);
};
