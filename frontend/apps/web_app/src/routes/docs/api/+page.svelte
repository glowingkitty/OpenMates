<script lang="ts">
    /**
     * API Documentation Page
     * 
     * Displays interactive OpenAPI documentation using Swagger UI.
     * Features:
     * - Auto-fetches OpenAPI spec from API server
     * - Auto-injects user's API key when logged in
     * - Full interactive "Try it out" functionality
     * 
     * This page replaces the need for api.openmates.org/docs
     */
    import { onMount } from 'svelte';
    import { browser } from '$app/environment';
    import { authStore, getApiEndpoint } from '@repo/ui';
    
    // State
    let swaggerContainer: HTMLDivElement | null = $state(null);
    let isLoading = $state(true);
    let error = $state<string | null>(null);
    let apiKey = $state<string | null>(null);
    
    // Get API base URL
    const apiBaseUrl = getApiEndpoint();
    
    // Watch for auth changes to update API key
    $effect(() => {
        if (browser && $authStore.isAuthenticated) {
            // Try to get API key from user's stored keys
            loadApiKey();
        }
    });
    
    /**
     * Load user's API key from storage
     */
    async function loadApiKey() {
        try {
            // Import dynamically to avoid SSR issues
            const { getKeyFromStorage } = await import('@repo/ui');
            const storedKey = await getKeyFromStorage('api_key');
            if (storedKey) {
                apiKey = storedKey;
                // Re-initialize Swagger UI with the API key
                if (swaggerContainer) {
                    initSwaggerUI();
                }
            }
        } catch (err) {
            console.debug('[API Docs] Could not load API key:', err);
        }
    }
    
    /**
     * Initialize Swagger UI
     */
    async function initSwaggerUI() {
        if (!browser || !swaggerContainer) return;
        
        isLoading = true;
        error = null;
        
        // Set a timeout to prevent infinite loading
        const loadTimeout = setTimeout(() => {
            if (isLoading) {
                console.warn('[API Docs] Swagger UI load timeout - showing error');
                error = 'API documentation is taking too long to load. The API server may be unavailable.';
                isLoading = false;
            }
        }, 15000); // 15 second timeout
        
        try {
            // First, verify the OpenAPI spec is accessible
            console.log('[API Docs] Fetching OpenAPI spec from:', `${apiBaseUrl}/openapi.json`);
            const specResponse = await fetch(`${apiBaseUrl}/openapi.json`, {
                method: 'GET',
                headers: { 'Accept': 'application/json' }
            }).catch(err => {
                console.error('[API Docs] Failed to fetch OpenAPI spec:', err);
                return null;
            });
            
            if (!specResponse || !specResponse.ok) {
                clearTimeout(loadTimeout);
                error = `Cannot connect to API server at ${apiBaseUrl}. Make sure the backend is running.`;
                isLoading = false;
                return;
            }
            
            // Dynamically load Swagger UI from CDN
            const SwaggerUIBundle = await loadSwaggerUIBundle();
            
            // Clear previous instance
            swaggerContainer.innerHTML = '';
            
            // Initialize Swagger UI
            SwaggerUIBundle({
                url: `${apiBaseUrl}/openapi.json`,
                dom_id: '#swagger-container',
                deepLinking: true,
                presets: [
                    SwaggerUIBundle.presets.apis,
                    SwaggerUIBundle.SwaggerUIStandalonePreset
                ],
                plugins: [
                    SwaggerUIBundle.plugins.DownloadUrl
                ],
                layout: 'BaseLayout',
                // Auto-authorize with API key if available
                onComplete: () => {
                    clearTimeout(loadTimeout);
                    console.log('[API Docs] Swagger UI loaded successfully');
                    if (apiKey) {
                        // Programmatically authorize with the user's API key
                        const ui = (window as WindowWithUI).ui;
                        if (ui?.preauthorizeApiKey) {
                            ui.preauthorizeApiKey('BearerAuth', apiKey);
                        }
                    }
                    isLoading = false;
                },
                requestInterceptor: (req: RequestWithHeaders) => {
                    // Auto-inject API key for all requests if available
                    if (apiKey && !req.headers['Authorization']) {
                        req.headers['Authorization'] = `Bearer ${apiKey}`;
                    }
                    return req;
                }
            });
        } catch (err) {
            clearTimeout(loadTimeout);
            console.error('[API Docs] Failed to load Swagger UI:', err);
            error = 'Failed to load API documentation. Please try again.';
            isLoading = false;
        }
    }
    
    /**
     * Load Swagger UI Bundle from CDN
     */
    async function loadSwaggerUIBundle(): Promise<SwaggerUIBundleType> {
        // Check if already loaded
        if ((window as WindowWithSwagger).SwaggerUIBundle) {
            return (window as WindowWithSwagger).SwaggerUIBundle!;
        }
        
        // Load CSS
        const cssLink = document.createElement('link');
        cssLink.rel = 'stylesheet';
        cssLink.href = 'https://unpkg.com/swagger-ui-dist@5/swagger-ui.css';
        document.head.appendChild(cssLink);
        
        // Load JS
        return new Promise((resolve, reject) => {
            const script = document.createElement('script');
            script.src = 'https://unpkg.com/swagger-ui-dist@5/swagger-ui-bundle.js';
            script.onload = () => {
                const bundle = (window as WindowWithSwagger).SwaggerUIBundle;
                if (bundle) {
                    resolve(bundle);
                } else {
                    reject(new Error('SwaggerUIBundle not found after loading script'));
                }
            };
            script.onerror = () => reject(new Error('Failed to load Swagger UI script'));
            document.head.appendChild(script);
        });
    }
    
    // Initialize on mount
    onMount(() => {
        initSwaggerUI();
    });
    
    // Type definitions
    interface SwaggerUIBundleType {
        (config: Record<string, unknown>): void;
        presets: {
            apis: unknown;
        };
        SwaggerUIStandalonePreset: unknown;
        plugins: {
            DownloadUrl: unknown;
        };
    }
    
    interface WindowWithSwagger extends Window {
        SwaggerUIBundle?: SwaggerUIBundleType;
    }
    
    interface WindowWithUI extends Window {
        ui?: {
            preauthorizeApiKey: (name: string, key: string) => void;
        };
    }
    
    interface RequestWithHeaders {
        headers: Record<string, string>;
    }
</script>

<svelte:head>
    <title>API Reference | OpenMates Docs</title>
    <meta name="description" content="OpenMates REST API documentation - interactive endpoint reference with try-it-out functionality" />
</svelte:head>

<div class="api-docs">
    <header class="api-header">
        <h1>API Reference</h1>
        <p class="api-description">
            Interactive documentation for the OpenMates REST API.
            {#if $authStore.isAuthenticated}
                <span class="auth-status authenticated">
                    Authenticated - API requests will use your credentials
                </span>
            {:else}
                <span class="auth-status">
                    <a href="/">Log in</a> to use "Try it out" with your API key
                </span>
            {/if}
        </p>
    </header>
    
    {#if error}
        <div class="error-message">
            <p>{error}</p>
            <button onclick={() => initSwaggerUI()}>Retry</button>
        </div>
    {/if}
    
    {#if isLoading}
        <div class="loading">
            <div class="spinner"></div>
            <p>Loading API documentation...</p>
        </div>
    {/if}
    
    <div 
        id="swagger-container" 
        class="swagger-container"
        bind:this={swaggerContainer}
        class:hidden={isLoading || !!error}
    ></div>
</div>

<style>
    .api-docs {
        max-width: 100%;
        min-height: calc(100vh - 200px);
    }
    
    .api-header {
        padding: 1.5rem 0;
        margin-bottom: 1rem;
        border-bottom: 1px solid var(--color-grey-200, #e5e5e5);
    }
    
    .api-header h1 {
        font-size: 2rem;
        font-weight: 700;
        color: var(--color-grey-900, #111827);
        margin-bottom: 0.5rem;
    }
    
    .api-description {
        color: var(--color-grey-600, #4b5563);
        font-size: 1rem;
    }
    
    .auth-status {
        display: inline-block;
        margin-top: 0.5rem;
        padding: 0.25rem 0.75rem;
        background-color: var(--color-grey-100, #f3f4f6);
        border-radius: 9999px;
        font-size: 0.875rem;
    }
    
    .auth-status.authenticated {
        background-color: var(--color-success-50, #ecfdf5);
        color: var(--color-success-700, #047857);
    }
    
    .auth-status a {
        color: var(--color-primary, #3b82f6);
        text-decoration: none;
    }
    
    .auth-status a:hover {
        text-decoration: underline;
    }
    
    .loading {
        display: flex;
        flex-direction: column;
        align-items: center;
        justify-content: center;
        padding: 4rem 2rem;
        color: var(--color-grey-500, #6b7280);
    }
    
    .spinner {
        width: 40px;
        height: 40px;
        border: 3px solid var(--color-grey-200, #e5e5e5);
        border-top-color: var(--color-primary, #3b82f6);
        border-radius: 50%;
        animation: spin 1s linear infinite;
        margin-bottom: 1rem;
    }
    
    @keyframes spin {
        to { transform: rotate(360deg); }
    }
    
    .error-message {
        text-align: center;
        padding: 2rem;
        background-color: var(--color-error-50, #fef2f2);
        border-radius: 0.5rem;
        margin-bottom: 1rem;
    }
    
    .error-message p {
        color: var(--color-error-700, #b91c1c);
        margin-bottom: 1rem;
    }
    
    .error-message button {
        padding: 0.5rem 1rem;
        background-color: var(--color-primary, #3b82f6);
        color: white;
        border: none;
        border-radius: 0.375rem;
        cursor: pointer;
    }
    
    .error-message button:hover {
        background-color: var(--color-primary-dark, #2563eb);
    }
    
    .swagger-container {
        /* Override Swagger UI default styles to match our theme */
    }
    
    .swagger-container.hidden {
        display: none;
    }
    
    /* Swagger UI theme overrides */
    :global(.swagger-ui) {
        font-family: inherit;
    }
    
    :global(.swagger-ui .topbar) {
        display: none;
    }
    
    :global(.swagger-ui .info) {
        margin-bottom: 2rem;
    }
    
    :global(.swagger-ui .info .title) {
        font-size: 1.5rem;
        color: var(--color-grey-900, #111827);
    }
    
    :global(.swagger-ui .opblock-tag) {
        font-size: 1.25rem;
        border-bottom: 1px solid var(--color-grey-200, #e5e5e5);
    }
    
    :global(.swagger-ui .opblock) {
        border-radius: 0.5rem;
        margin-bottom: 0.5rem;
    }
    
    :global(.swagger-ui .opblock .opblock-summary) {
        border-radius: 0.5rem;
    }
    
    :global(.swagger-ui .btn) {
        border-radius: 0.375rem;
    }
    
    :global(.swagger-ui .btn.execute) {
        background-color: var(--color-primary, #3b82f6);
        border-color: var(--color-primary, #3b82f6);
    }
    
    :global(.swagger-ui .btn.execute:hover) {
        background-color: var(--color-primary-dark, #2563eb);
    }
</style>
