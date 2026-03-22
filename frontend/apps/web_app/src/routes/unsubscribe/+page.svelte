<script lang="ts">
    import { onMount } from 'svelte';
    import { browser } from '$app/environment';
    import { text, Header, Footer } from '@repo/ui';
    import { getApiEndpoint, apiEndpoints } from '@repo/ui';

    // State
    let email = $state<string | null>(null);
    let isLoading = $state(false);
    let isSuccess = $state(false);
    let errorMessage = $state<string | null>(null);
    let successMessage = $state<string | null>(null);

    /**
     * Extract token from URL path parameter
     * Format: /unsubscribe/{token}
     */
    function extractTokenFromPath(): string | null {
        if (!browser) return null;
        
        const path = window.location.pathname;
        // Path should be /unsubscribe/{token}
        const match = path.match(/^\/unsubscribe\/(.+)$/);
        return match ? match[1] : null;
    }

    /**
     * Unsubscribe from newsletter using token
     */
    async function unsubscribeEmail() {
        if (!email) {
            errorMessage = 'No unsubscribe token provided in the URL.';
            return;
        }

        isLoading = true;
        errorMessage = null;
        successMessage = null;

        try {
            // Use GET request with token in path
            const response = await fetch(getApiEndpoint(`${apiEndpoints.newsletter.unsubscribe}/${email}`), {
                method: 'GET',
                headers: {
                    'Origin': window.location.origin
                },
                credentials: 'include'
            });

            const result = await response.json();

            if (response.ok && result.success) {
                isSuccess = true;
                successMessage = result.message || 'You have been unsubscribed from our newsletter.';
            } else {
                errorMessage = result.message || 'An error occurred while unsubscribing.';
            }
        } catch (error) {
            console.error('Error unsubscribing:', error);
            errorMessage = 'An error occurred while processing your request. Please try again later.';
        } finally {
            isLoading = false;
        }
    }

    onMount(() => {
        // Extract token from path on mount
        const extractedToken = extractTokenFromPath();
        if (extractedToken) {
            email = extractedToken; // Reuse email variable to store token
            // Automatically unsubscribe using the token
            unsubscribeEmail();
        } else {
            errorMessage = 'No unsubscribe token found in the URL. Please use the link from the email.';
        }
    });
</script>

<svelte:head>
    <title>{$text('email.unsubscribe.title')}</title>
</svelte:head>

<div class="page-container">
    <Header context="website" />
    
    <main class="main-content">
        <div class="content-wrapper">
            {#if isLoading}
                <div class="status-message loading">
                    <p>{$text('email.unsubscribe.processing')}</p>
                </div>
            {:else if isSuccess}
                <div class="status-message success">
                    <h1>{$text('email.unsubscribe.success.title')}</h1>
                    <p>{successMessage || $text('email.unsubscribe.success.message')}</p>
                </div>
            {:else if errorMessage}
                <div class="status-message error">
                    <h1>{$text('email.unsubscribe.error.title')}</h1>
                    <p>{errorMessage}</p>
                </div>
            {:else}
                <div class="status-message">
                    <p>{$text('email.unsubscribe.loading')}</p>
                </div>
            {/if}
        </div>
    </main>
    
    <Footer />
</div>

<style>
    .page-container {
        min-height: 100vh;
        display: flex;
        flex-direction: column;
    }

    .main-content {
        flex: 1;
        display: flex;
        align-items: center;
        justify-content: center;
        padding: 2rem 1rem;
    }

    .content-wrapper {
        max-width: 600px;
        width: 100%;
    }

    .status-message {
        text-align: center;
        padding: 2rem;
        border-radius: 8px;
        background-color: var(--color-background, #ffffff);
    }

    .status-message.loading {
        color: var(--color-text, #000000);
    }

    .status-message.success {
        background-color: var(--color-success-bg, #d4edda);
        color: var(--color-success-text, #155724);
        border: 1px solid var(--color-success-border, #c3e6cb);
    }

    .status-message.error {
        background-color: var(--color-error-bg, #f8d7da);
        color: var(--color-error-text, #721c24);
        border: 1px solid var(--color-error-border, #f5c6cb);
    }

    .status-message h1 {
        margin: 0 0 1rem 0;
        font-size: 1.5rem;
    }

    .status-message p {
        margin: 0;
        line-height: 1.6;
    }
</style>
