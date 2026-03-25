<!--
    Short URL Redirect Page (/s/)

    Lightweight client-only page that resolves ephemeral short URLs.

    Flow:
    1. Parse window.location.hash → extract token and shortKey
    2. Fetch encrypted blob from GET /v1/share/short-url/{token}
    3. Decrypt blob with shortKey via PBKDF2 + AES-GCM
    4. Redirect to the decrypted full share URL

    Zero-knowledge: the shortKey (decryption key) is in the URL fragment,
    never sent to the server. The server returns an opaque encrypted blob.
-->
<script lang="ts">
    import { onMount } from 'svelte';
    import { getApiEndpoint } from '@repo/ui';
    import {
        parseShortUrlFragment,
        decryptShareUrl,
    } from '@repo/ui/services/shortUrlEncryption';

    // State
    let status: 'loading' | 'redirecting' | 'error' = $state('loading');
    let errorMessage = $state('');
    let errorDetail = $state('');

    onMount(async () => {
        try {
            // Step 1: Parse the fragment
            const hash = window.location.hash;
            if (!hash || hash.length < 2) {
                status = 'error';
                errorMessage = 'Invalid short link';
                errorDetail = 'The link appears to be incomplete. Please ask the sender for a new link.';
                return;
            }

            const parsed = parseShortUrlFragment(hash);
            if (!parsed) {
                status = 'error';
                errorMessage = 'Invalid short link';
                errorDetail = 'The link format is not recognized. Please ask the sender for a new link.';
                return;
            }

            const { token, shortKey } = parsed;

            // Step 2: Fetch encrypted blob from API
            status = 'loading';
            const apiUrl = getApiEndpoint(`/v1/share/short-url/${encodeURIComponent(token)}`);
            const response = await fetch(apiUrl);

            if (response.status === 404) {
                status = 'error';
                errorMessage = 'Link expired or not found';
                errorDetail = 'This short link has expired or does not exist. Short links are temporary — please ask the sender for a new link.';
                return;
            }

            if (response.status === 429) {
                status = 'error';
                errorMessage = 'Link disabled';
                errorDetail = 'This short link has been used too many times and is now disabled for security. Please ask the sender for a new link.';
                return;
            }

            if (!response.ok) {
                status = 'error';
                errorMessage = 'Something went wrong';
                errorDetail = 'Could not resolve the short link. Please try again or ask the sender for a new link.';
                return;
            }

            const data = await response.json();
            if (!data.encrypted_url) {
                status = 'error';
                errorMessage = 'Invalid response';
                errorDetail = 'The server returned an unexpected response. Please try again.';
                return;
            }

            // Step 3: Decrypt the blob
            let decryptedUrl: string;
            try {
                decryptedUrl = await decryptShareUrl(data.encrypted_url, token, shortKey);
            } catch {
                status = 'error';
                errorMessage = 'Decryption failed';
                errorDetail = 'The link could not be decrypted. It may have been corrupted or the key is incorrect.';
                return;
            }

            // Step 4: Redirect
            status = 'redirecting';

            // Check if the decrypted URL is on the same origin — use SPA navigation if so
            try {
                const targetUrl = new URL(decryptedUrl, window.location.origin);
                if (targetUrl.origin === window.location.origin) {
                    // Same origin: use location.replace for clean history
                    // We include the hash (fragment) which contains the encryption key
                    window.location.replace(decryptedUrl);
                } else {
                    // Different origin: full redirect
                    window.location.replace(decryptedUrl);
                }
            } catch {
                // If URL parsing fails, try direct redirect
                window.location.replace(decryptedUrl);
            }
        } catch (error) {
            console.error('[ShortUrl] Unexpected error:', error);
            status = 'error';
            errorMessage = 'Something went wrong';
            errorDetail = 'An unexpected error occurred. Please try again or ask the sender for a new link.';
        }
    });
</script>

<div class="short-url-page">
    {#if status === 'loading'}
        <div class="status-container">
            <div class="spinner"></div>
            <p class="status-text">Resolving link...</p>
        </div>
    {:else if status === 'redirecting'}
        <div class="status-container">
            <div class="spinner"></div>
            <p class="status-text">Redirecting...</p>
        </div>
    {:else if status === 'error'}
        <div class="error-container">
            <div class="error-icon">!</div>
            <h1 class="error-title">{errorMessage}</h1>
            <p class="error-detail">{errorDetail}</p>
            <a href="/" class="home-link">Go to OpenMates</a>
        </div>
    {/if}
</div>

<style>
    .short-url-page {
        display: flex;
        align-items: center;
        justify-content: center;
        min-height: 100vh;
        padding: 20px;
        text-align: center;
    }

    .status-container {
        display: flex;
        flex-direction: column;
        align-items: center;
        gap: 16px;
    }

    .spinner {
        width: 40px;
        height: 40px;
        border: 3px solid var(--color-grey-20, #e5e7eb);
        border-top-color: var(--color-primary, #6366f1);
        border-radius: 50%;
        animation: spin 0.8s linear infinite;
    }

    @keyframes spin {
        to { transform: rotate(360deg); }
    }

    .status-text {
        font-size: 16px;
        color: var(--color-grey-70, #374151);
        margin: 0;
    }

    .error-container {
        display: flex;
        flex-direction: column;
        align-items: center;
        gap: 12px;
        max-width: 400px;
    }

    .error-icon {
        width: 48px;
        height: 48px;
        border-radius: 50%;
        background-color: var(--color-grey-10, #f3f4f6);
        color: var(--color-grey-60, #6b7280);
        display: flex;
        align-items: center;
        justify-content: center;
        font-size: 24px;
        font-weight: 700;
    }

    .error-title {
        font-size: 20px;
        font-weight: 600;
        color: var(--color-grey-100, #111827);
        margin: 0;
    }

    .error-detail {
        font-size: 14px;
        color: var(--color-grey-60, #6b7280);
        margin: 0;
        line-height: 1.5;
    }

    .home-link {
        display: inline-block;
        margin-top: 8px;
        padding: 10px 24px;
        background-color: var(--color-primary, #6366f1);
        color: white;
        text-decoration: none;
        border-radius: 8px;
        font-size: 14px;
        font-weight: 500;
        transition: opacity 0.2s;
    }

    .home-link:hover {
        opacity: 0.9;
    }
</style>
