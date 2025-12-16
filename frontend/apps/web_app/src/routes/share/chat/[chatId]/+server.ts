// frontend/apps/web_app/src/routes/share/chat/[chatId]/+server.ts
//
// SvelteKit server route for serving OG tags for shared chats
// This route serves HTML with Open Graph meta tags for social media sharing

import type { RequestHandler } from '@sveltejs/kit';
import { env } from '$env/dynamic/private';

/**
 * Server route handler for /share/chat/[chatId]
 *
 * This route serves HTML with OG tags for social media crawlers.
 * The encryption key is in the URL fragment (#key=...), which is never sent to the server.
 * This ensures the server never sees the encryption key.
 *
 * Flow:
 * 1. Fetch OG metadata from backend API (/v1/share/chat/{chatId}/og-metadata)
 * 2. Generate HTML with proper OG tags using the fetched metadata
 * 3. Client-side JavaScript redirects to main app if key fragment is present
 */
export const GET: RequestHandler = async ({ params, url, fetch }) => {
    const chatId = params.chatId;

    if (!chatId) {
        return new Response('Invalid chat ID', { status: 400 });
    }

    // Fetch OG metadata from backend API
    const backendUrl = env.BACKEND_URL || 'https://app.dev.openmates.org';
    let ogTitle = 'Shared Chat - OpenMates';
    let ogDescription = 'View this shared conversation on OpenMates';
    let ogImage = '/og-images/default-chat.png';

    try {
        const response = await fetch(`${backendUrl}/v1/share/chat/${chatId}/og-metadata`);

        if (response.ok) {
            const data = await response.json();
            ogTitle = data.title || ogTitle;
            ogDescription = data.description || ogDescription;
            ogImage = data.image || ogImage;
        } else {
            console.warn(`Failed to fetch OG metadata for chat ${chatId}: ${response.status}`);
        }
    } catch (error) {
        console.error(`Error fetching OG metadata for chat ${chatId}:`, error);
        // Use fallback values
    }

    const siteUrl = url.origin;
    const shareUrl = `${siteUrl}/share/chat/${chatId}`;

    // Generate HTML with OG tags
    const html = `<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>${ogTitle}</title>
    <meta name="description" content="${ogDescription}">

    <!-- Open Graph / Facebook -->
    <meta property="og:type" content="website">
    <meta property="og:url" content="${shareUrl}">
    <meta property="og:title" content="${ogTitle}">
    <meta property="og:description" content="${ogDescription}">
    <meta property="og:image" content="${siteUrl}${ogImage}">

    <!-- Twitter -->
    <meta name="twitter:card" content="summary_large_image">
    <meta property="twitter:domain" content="${url.hostname}">
    <meta property="twitter:url" content="${shareUrl}">
    <meta name="twitter:title" content="${ogTitle}">
    <meta name="twitter:description" content="${ogDescription}">
    <meta name="twitter:image" content="${siteUrl}${ogImage}">

    <!-- Redirect to main app if JavaScript is enabled and key fragment exists -->
    <script>
        // If user has the full URL with key fragment, redirect to main app
        if (window.location.hash && window.location.hash.includes('key=')) {
            const fragment = window.location.hash.substring(1);
            window.location.href = '/#chat-id=${chatId}&' + fragment;
        }
    </script>
</head>
<body>
    <h1>${ogTitle}</h1>
    <p>${ogDescription}</p>
    <p><a href="/">Open in OpenMates</a></p>
</body>
</html>`;

    return new Response(html, {
        headers: {
            'Content-Type': 'text/html; charset=utf-8',
        },
    });
};

