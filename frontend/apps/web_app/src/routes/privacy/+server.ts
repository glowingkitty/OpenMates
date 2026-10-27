import { redirect } from '@sveltejs/kit';
import { publicWebsiteOrigin } from '$lib/server/publicWebsite';
import type { RequestHandler } from './$types';

export const GET: RequestHandler = ({ url }) => {
  redirect(302, `${publicWebsiteOrigin(url)}/legal/privacy${url.search}`);
};
