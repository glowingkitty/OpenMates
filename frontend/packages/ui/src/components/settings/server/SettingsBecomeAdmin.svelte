<!--
    Settings Become Admin Component

    Handles the process of becoming a server admin using a secure token.
    This component is accessed via deep link from the docker exec command.
-->
<script lang="ts">
    import { createEventDispatcher, onMount } from 'svelte';
    import { getApiEndpoint } from '@repo/ui';
    // Use standard browser check for library compatibility (not SvelteKit-specific)
    const browser = typeof window !== 'undefined';

    const dispatch = createEventDispatcher();

    // State
    let isLoading = $state(false);
    let error = $state<string | null>(null);
    let success = $state(false);
    let token = $state<string | null>(null);

    /**
     * Extract token from URL parameters
     */
    function extractToken() {
        if (!browser) return;

        const urlParams = new URLSearchParams(window.location.search);
        const tokenParam = urlParams.get('token');

        if (tokenParam) {
            token = tokenParam;
        } else {
            error = 'No admin token found in URL. Please use the complete link provided by the server administrator.';
        }
    }

    /**
     * Process the admin token and grant admin privileges
     */
    async function becomeAdmin() {
        if (!token) {
            error = 'No admin token available';
            return;
        }

        try {
            isLoading = true;
            error = null;

            const response = await fetch(getApiEndpoint('/v1/admin/become-admin'), {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json'
                },
                credentials: 'include',
                body: JSON.stringify({
                    token: token
                })
            });

            if (!response.ok) {
                const errorData = await response.text();
                if (response.status === 401) {
                    error = 'Please log in to your account before using the admin token.';
                } else if (response.status === 400) {
                    error = 'Invalid or expired admin token. Please request a new token from the server administrator.';
                } else {
                    error = errorData || 'Failed to grant admin privileges';
                }
                return;
            }

            success = true;

            // Show success and redirect after a delay
            setTimeout(() => {
                // Redirect to server settings
                dispatch('navigateToSettings', { path: 'server' });
            }, 3000);

        } catch (err) {
            console.error('Error becoming admin:', err);
            error = 'Failed to connect to server. Please try again.';
        } finally {
            isLoading = false;
        }
    }

    /**
     * Handle back button
     */
    function handleBack() {
        dispatch('back');
    }

    /**
     * Go to login page
     */
    function goToLogin() {
        window.location.href = '/auth/login';
    }

    // Extract token and auto-process on mount
    onMount(() => {
        extractToken();

        // If we have a token, automatically try to become admin
        if (token) {
            becomeAdmin();
        }
    });
</script>

<div class="become-admin">
    <!-- Header -->
    <div class="header">
        <button onclick={handleBack} class="back-button">
            ← Back
        </button>
        <h2>Become Server Administrator</h2>
        <p>Processing admin privileges request</p>
    </div>

    <!-- Content -->
    <div class="content">
        {#if isLoading}
            <!-- Loading State -->
            <div class="status loading-status">
                <div class="status-icon">
                    <div class="spinner"></div>
                </div>
                <h3>Processing Admin Token</h3>
                <p>Granting admin privileges to your account...</p>
            </div>
        {:else if success}
            <!-- Success State -->
            <div class="status success-status">
                <div class="status-icon">
                    <div class="success-icon">✅</div>
                </div>
                <h3>Admin Privileges Granted!</h3>
                <p>
                    Congratulations! Your account now has server administrator privileges.
                    You can now manage server settings and demo chats.
                </p>
                <p class="redirect-info">
                    Redirecting to server settings in a few seconds...
                </p>
            </div>
        {:else if error}
            <!-- Error State -->
            <div class="status error-status">
                <div class="status-icon">
                    <div class="error-icon">⚠️</div>
                </div>
                <h3>Failed to Grant Admin Privileges</h3>
                <p>{error}</p>

                <div class="error-actions">
                    {#if error.includes('log in')}
                        <button onclick={goToLogin} class="btn btn-primary">
                            Go to Login
                        </button>
                    {:else if error.includes('expired')}
                        <div class="help-text">
                            <p><strong>To get a new admin token:</strong></p>
                            <ol>
                                <li>Ask the server administrator to run the command again</li>
                                <li>Use the new URL within 30 seconds</li>
                                <li>Ensure you're logged into your account</li>
                            </ol>
                        </div>
                    {:else}
                        <button onclick={becomeAdmin} class="btn btn-primary">
                            Try Again
                        </button>
                    {/if}
                </div>
            </div>
        {:else}
            <!-- Initial State (no token) -->
            <div class="status info-status">
                <div class="status-icon">
                    <div class="info-icon">ℹ️</div>
                </div>
                <h3>Admin Token Required</h3>
                <p>
                    To become a server administrator, you need a valid admin token
                    generated by the server administrator.
                </p>

                <div class="instructions">
                    <h4>How to get admin privileges:</h4>
                    <ol>
                        <li>The server administrator runs this command:
                            <code>docker exec openmates-api python /app/backend/scripts/create_admin_token.py</code>
                        </li>
                        <li>They share the generated URL with you</li>
                        <li>You click the URL while logged into your account</li>
                        <li>You receive admin privileges (the token expires in 30 seconds)</li>
                    </ol>
                </div>
            </div>
        {/if}
    </div>

    <!-- Security Info -->
    <div class="security-info">
        <div class="security-card">
            <h4>Security Information</h4>
            <ul>
                <li><strong>Token Expiration:</strong> Admin tokens are valid for only 30 seconds</li>
                <li><strong>Single Use:</strong> Each token can only be used once</li>
                <li><strong>Account Required:</strong> You must be logged in to use a token</li>
                <li><strong>Server Access:</strong> Only server administrators can generate tokens</li>
                <li><strong>Permanent:</strong> Admin privileges cannot be revoked through the UI</li>
            </ul>
        </div>
    </div>
</div>

<style>
    .become-admin {
        padding: 1.5rem;
        max-width: 800px;
        margin: 0 auto;
    }

    .header {
        margin-bottom: 2rem;
        padding-bottom: 1rem;
        border-bottom: 1px solid var(--color-border);
    }

    .back-button {
        background: none;
        border: none;
        color: var(--color-text-secondary);
        cursor: pointer;
        margin-bottom: 1rem;
        font-size: 0.9rem;
    }

    .back-button:hover {
        color: var(--color-primary);
    }

    .header h2 {
        margin: 0 0 0.5rem 0;
        color: var(--color-text-primary);
    }

    .header p {
        margin: 0;
        color: var(--color-text-secondary);
    }

    .content {
        margin-bottom: 2rem;
    }

    .status {
        text-align: center;
        padding: 2rem;
        border-radius: 12px;
        border: 2px solid;
    }

    .loading-status {
        border-color: var(--color-primary);
        background: var(--color-primary-light);
    }

    .success-status {
        border-color: var(--color-success);
        background: var(--color-success-light);
    }

    .error-status {
        border-color: var(--color-error);
        background: var(--color-error-light);
    }

    .info-status {
        border-color: var(--color-info);
        background: var(--color-info-light);
    }

    .status-icon {
        margin-bottom: 1rem;
    }

    .spinner {
        width: 3rem;
        height: 3rem;
        border: 4px solid var(--color-primary-light);
        border-top: 4px solid var(--color-primary);
        border-radius: 50%;
        animation: spin 1s linear infinite;
        margin: 0 auto;
    }

    @keyframes spin {
        0% { transform: rotate(0deg); }
        100% { transform: rotate(360deg); }
    }

    .success-icon,
    .error-icon,
    .info-icon {
        font-size: 3rem;
    }

    .status h3 {
        margin: 0 0 1rem 0;
        color: var(--color-text-primary);
    }

    .status p {
        margin: 0 0 1rem 0;
        color: var(--color-text-secondary);
        line-height: 1.5;
    }

    .redirect-info {
        font-style: italic;
        color: var(--color-text-tertiary);
    }

    .error-actions {
        margin-top: 1.5rem;
    }

    .btn {
        padding: 0.75rem 1.5rem;
        border-radius: 6px;
        font-weight: 500;
        cursor: pointer;
        transition: all 0.2s ease;
        border: none;
        font-size: 1rem;
    }

    .btn-primary {
        background: var(--color-primary);
        color: white;
    }

    .btn-primary:hover {
        background: var(--color-primary-dark);
    }

    .instructions,
    .help-text {
        text-align: left;
        margin-top: 1.5rem;
        padding: 1rem;
        background: var(--color-background-secondary);
        border-radius: 8px;
        border: 1px solid var(--color-border);
    }

    .instructions h4,
    .help-text p strong {
        margin: 0 0 1rem 0;
        color: var(--color-text-primary);
    }

    .instructions ol {
        margin: 0;
        padding-left: 1.5rem;
        color: var(--color-text-secondary);
        line-height: 1.6;
    }

    .instructions li {
        margin-bottom: 0.75rem;
    }

    code {
        background: var(--color-background-tertiary);
        padding: 0.25rem 0.5rem;
        border-radius: 4px;
        font-family: 'Monaco', 'Menlo', monospace;
        font-size: 0.9rem;
        word-break: break-all;
        display: block;
        margin-top: 0.5rem;
        padding: 0.5rem;
    }

    .security-info {
        margin-top: 2rem;
        padding-top: 2rem;
        border-top: 1px solid var(--color-border);
    }

    .security-card {
        background: var(--color-background-secondary);
        border: 1px solid var(--color-border);
        border-radius: 8px;
        padding: 1.5rem;
    }

    .security-card h4 {
        margin: 0 0 1rem 0;
        color: var(--color-text-primary);
    }

    .security-card ul {
        margin: 0;
        padding-left: 1.5rem;
        color: var(--color-text-secondary);
        line-height: 1.6;
    }

    .security-card li {
        margin-bottom: 0.5rem;
    }

    @media (max-width: 768px) {
        .become-admin {
            padding: 1rem;
        }

        .status {
            padding: 1.5rem 1rem;
        }

        code {
            font-size: 0.8rem;
            padding: 0.4rem;
            word-break: break-all;
        }
    }
</style>