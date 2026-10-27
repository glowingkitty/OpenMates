import { redirect } from '@sveltejs/kit';
import type { RequestHandler } from './$types';
import { appOrigin } from '$lib/server/origins';

export const trailingSlash = 'ignore';

// Old public links must reach the app's example index or transcript, including query parameters.
export const GET: RequestHandler = ({ url }) => {
  redirect(302, `${appOrigin(url)}${url.pathname}${url.search}`);
};
