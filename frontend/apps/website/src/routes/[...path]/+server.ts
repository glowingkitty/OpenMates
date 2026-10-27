import { redirect } from '@sveltejs/kit';
import type { RequestHandler } from './$types';

// Give unmatched paths a server route so the hosting adapter cannot show its bare 404.
export const GET: RequestHandler = () => {
  redirect(302, '/');
};
