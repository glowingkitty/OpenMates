// frontend/apps/web_app/src/routes/privacy/+server.ts
//
// Short legal URL redirect for users and external links that expect
// openmates.org/privacy to exist. The canonical crawler page remains
// /legal/privacy, while this human-friendly route opens the same public
// privacy policy chat inside the SPA.

import { redirect } from '@sveltejs/kit';
import type { RequestHandler } from './$types';

export const GET: RequestHandler = () => {
	redirect(302, '/#chat-id=legal-privacy');
};
