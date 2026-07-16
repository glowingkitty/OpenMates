// frontend/apps/web_app/src/routes/privacy/pii/+server.ts
//
// Human-friendly PII settings shortcut. Redirecting from a server endpoint keeps
// the selected settings page in the URL fragment so it is never sent as a query
// parameter or persisted in server-side request logs.

import { redirect } from '@sveltejs/kit';
import type { RequestHandler } from './$types';

export const GET: RequestHandler = () => {
	redirect(302, '/#settings/privacy/pii');
};
