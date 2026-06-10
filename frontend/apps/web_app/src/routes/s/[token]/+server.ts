// frontend/apps/web_app/src/routes/s/[token]/+server.ts
//
// Durable short-link route with crawler-visible token and fragment-only secret.
// Social crawlers request /s/{token} without the #shortKey fragment and receive
// safe OG tags. Browsers with a fragment are redirected client-side to the
// legacy /s/#token-shortKey resolver so the shortKey is never sent to the server.

import type { RequestHandler } from '@sveltejs/kit';
import { getBackendUrl } from '$lib/backendUrl';

function escapeHtml(value: string): string {
	return value
		.replace(/&/g, '&amp;')
		.replace(/</g, '&lt;')
		.replace(/>/g, '&gt;')
		.replace(/"/g, '&quot;')
		.replace(/'/g, '&#39;');
}

export const GET: RequestHandler = async ({ params, url, fetch }) => {
	const token = params.token;
	if (!token || !/^[A-Za-z0-9]{6,12}$/.test(token)) {
		return new Response('Not found', { status: 404 });
	}

	const backendUrl = getBackendUrl(url);
	const siteUrl = url.origin;
	let title = 'Shared Chat - OpenMates';
	let description = 'View this shared conversation on OpenMates';
	let image = '/images/og-image.jpg';

	try {
		const response = await fetch(`${backendUrl}/v1/share/short-url/${token}/metadata`, {
			cache: 'no-store'
		});
		if (response.ok) {
			const metadata = await response.json();
			title = metadata.title || title;
			description = metadata.description || description;
			image = metadata.image || image;
		}
	} catch (error) {
		console.warn(`[ShortUrl] Failed to fetch metadata for ${token}:`, error);
	}

	const absoluteImage = image.startsWith('http') ? image : `${backendUrl}${image}`;
	const shareUrl = `${siteUrl}/s/${token}`;
	const safeTitle = escapeHtml(title);
	const safeDescription = escapeHtml(description);
	const safeImage = escapeHtml(absoluteImage);
	const safeShareUrl = escapeHtml(shareUrl);

	const html = `<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>${safeTitle}</title>
    <meta name="description" content="${safeDescription}">

    <meta property="og:type" content="website">
    <meta property="og:url" content="${safeShareUrl}">
    <meta property="og:title" content="${safeTitle}">
    <meta property="og:description" content="${safeDescription}">
    <meta property="og:image" content="${safeImage}">
    <meta property="og:image:width" content="1200">
    <meta property="og:image:height" content="630">

    <meta name="twitter:card" content="summary_large_image">
    <meta property="twitter:domain" content="${escapeHtml(url.hostname)}">
    <meta property="twitter:url" content="${safeShareUrl}">
    <meta name="twitter:title" content="${safeTitle}">
    <meta name="twitter:description" content="${safeDescription}">
    <meta name="twitter:image" content="${safeImage}">

    <script>
        if (window.location.hash && window.location.hash.length > 1) {
            window.location.replace('/s/#${token}-' + window.location.hash.substring(1));
        }
    </script>
</head>
<body>
    <h1>${safeTitle}</h1>
    <p>${safeDescription}</p>
    <p><a href="/">Open in OpenMates</a></p>
</body>
</html>`;

	return new Response(html, {
		headers: {
			'Content-Type': 'text/html; charset=utf-8',
			'Cache-Control': 'public, max-age=300'
		}
	});
};
