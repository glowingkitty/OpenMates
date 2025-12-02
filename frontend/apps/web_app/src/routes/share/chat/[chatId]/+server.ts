// backend/apps/web_app/src/routes/share/chat/[chatId]/+server.ts
// 
// SvelteKit server route for serving OG tags for shared chats
// This route serves HTML with Open Graph meta tags for social media sharing

import type { RequestHandler } from '@sveltejs/kit';
import { redirect } from '@sveltejs/kit';

/**
 * Server route handler for /share/chat/[chatId]
 * 
 * This route serves two purposes:
 * 1. When accessed without a key fragment: Serve HTML with OG tags for social media crawlers
 * 2. When accessed with a key fragment: Redirect to main app with chat_id in hash
 * 
 * The encryption key is in the URL fragment (#key=...), which is never sent to the server.
 * This ensures the server never sees the encryption key.
 */
export const GET: RequestHandler = async ({ params, url }) => {
    const chatId = params.chatId;
    
    if (!chatId) {
        return new Response('Invalid chat ID', { status: 400 });
    }
    
    // Check if URL has a key fragment (client-side only, not sent to server)
    // If the URL has a fragment, redirect to main app
    // Note: URL fragments are not available server-side, so we check the full URL
    const fullUrl = url.toString();
    if (fullUrl.includes('#key=')) {
        // Client will handle the redirect, but we can also redirect here
        // Extract the fragment and redirect to main app
        const fragment = fullUrl.split('#')[1];
        return redirect(302, `/#chat_id=${chatId}&${fragment}`);
    }
    
    // No key fragment - serve OG tags for social media crawlers
    // TODO: Fetch chat metadata from backend API
    // For now, return basic OG tags
    // In production, this should:
    // 1. Call backend API: GET /api/v1/share/chat/{chatId}
    // 2. Decrypt shared_encrypted_title and shared_encrypted_summary using shared vault key
    // 3. Select appropriate OG image based on chat category
    // 4. Generate HTML with OG tags
    
    // Default OG tags (will be replaced with real data from backend)
    const ogTitle = 'Shared Chat - OpenMates';
    const ogDescription = 'View this shared conversation on OpenMates';
    const ogImage = '/og-images/default-chat.png'; // Default OG image
    const siteUrl = url.origin;
    const shareUrl = `${siteUrl}/share/chat/${chatId}`;
    
    // TODO: Fetch real metadata from backend
    // const response = await fetch(`${process.env.BACKEND_URL}/api/v1/share/chat/${chatId}`);
    // const data = await response.json();
    // if (data.shared_encrypted_title) {
    //     // Decrypt using shared vault key
    //     ogTitle = decrypt(data.shared_encrypted_title, 'shared-content-metadata');
    // }
    
    // Generate HTML with OG tags
    const html = `<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>${ogTitle}</title>
    
    <!-- Open Graph / Facebook -->
    <meta property="og:type" content="website">
    <meta property="og:url" content="${shareUrl}">
    <meta property="og:title" content="${ogTitle}">
    <meta property="og:description" content="${ogDescription}">
    <meta property="og:image" content="${siteUrl}${ogImage}">
    
    <!-- Twitter -->
    <meta name="twitter:card" content="summary_large_image">
    <meta name="twitter:url" content="${shareUrl}">
    <meta name="twitter:title" content="${ogTitle}">
    <meta name="twitter:description" content="${ogDescription}">
    <meta name="twitter:image" content="${siteUrl}${ogImage}">
    
    <!-- Redirect to main app if JavaScript is enabled -->
    <script>
        // If user has the full URL with key fragment, redirect to main app
        if (window.location.hash && window.location.hash.includes('key=')) {
            const fragment = window.location.hash.substring(1);
            window.location.href = '/#chat_id=${chatId}&' + fragment;
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

