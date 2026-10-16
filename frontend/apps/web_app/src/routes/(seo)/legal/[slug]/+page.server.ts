import { error, redirect } from '@sveltejs/kit';
import { publicWebsiteOrigin } from '$lib/server/publicWebsite';
import type { PageServerLoad } from './$types';

/** Old app document URLs now open the real public website without a chat shell. */
export const load: PageServerLoad = ({ params, url }) => {
  if (!['privacy', 'terms', 'imprint'].includes(params.slug)) error(404, 'Legal document not found');
  redirect(302, `${publicWebsiteOrigin(url)}/legal/${params.slug}${url.search}`);
};
