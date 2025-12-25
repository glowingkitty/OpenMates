<!--
    Settings Community Suggestions Component

    Shows pending community chat suggestions for admin approval.
    Allows admins to approve chats to become demo chats with a limit of 5.
-->
<script lang="ts">
    import { createEventDispatcher, onMount } from 'svelte';
    import { getApiEndpoint } from '@repo/ui';

    const dispatch = createEventDispatcher();

    // State
    let isLoading = $state(true);
    let error = $state<string | null>(null);
    let suggestions = $state<Array<{ chat_id: string; title?: string; summary?: string; category?: string; shared_at: string; share_link: string }>>([]);
    let currentDemoChats = $state<Array<{ demo_id: string; title: string; summary?: string; category?: string; created_at: string }>>([]);
    let isSubmitting = $state(false);
    let pendingSuggestion = $state<{ chat_id: string; encryption_key: string; title: string; summary: string; shared_at: string; share_link: string } | null>(null);

    // URL parameters for email link
    let urlParams = $state<{ chat_id?: string; key?: string; title?: string; summary?: string }>({});

    /**
     * Extract URL parameters for email deep link
     */
    function extractUrlParams() {
        if (typeof window !== 'undefined') {
            const searchParams = new URLSearchParams(window.location.search);
            urlParams = {
                chat_id: searchParams.get('chat_id') || undefined,
                key: searchParams.get('key') || undefined,
                title: searchParams.get('title') || undefined,
                summary: searchParams.get('summary') || undefined
            };

            // If we have URL params, create a pending suggestion
            if (urlParams.chat_id && urlParams.key) {
                pendingSuggestion = {
                    chat_id: urlParams.chat_id,
                    encryption_key: urlParams.key,
                    title: decodeURIComponent(urlParams.title || 'Community Shared Chat'),
                    summary: decodeURIComponent(urlParams.summary || ''),
                    shared_at: new Date().toISOString(),
                    share_link: `${window.location.origin}/share/chat/${urlParams.chat_id}#key=${urlParams.key}`
                };
            }
        }
    }

    /**
     * Load community suggestions from server
     */
    async function loadSuggestions() {
        try {
            isLoading = true;
            error = null;

            const response = await fetch(getApiEndpoint('/v1/admin/community-suggestions'), {
                credentials: 'include'
            });

            if (!response.ok) {
                if (response.status === 403) {
                    error = 'Admin privileges required to view community suggestions.';
                } else {
                    error = 'Failed to load community suggestions.';
                }
                return;
            }

            const data = await response.json();
            suggestions = data.suggestions || [];

        } catch (err) {
            console.error('Error loading suggestions:', err);
            error = 'Failed to connect to server.';
        } finally {
            isLoading = false;
        }
    }

    /**
     * Load current demo chats
     */
    async function loadCurrentDemoChats() {
        try {
            const response = await fetch(getApiEndpoint('/v1/admin/demo-chats'), {
                credentials: 'include'
            });

            if (response.ok) {
                const data = await response.json();
                currentDemoChats = data.demo_chats || [];
            }

        } catch (err) {
            console.error('Error loading demo chats:', err);
        }
    }

    /**
     * Approve a chat as demo chat
     */
    async function approveDemoChat(suggestion: { chat_id: string; encryption_key?: string; title?: string; summary?: string; category?: string }) {
        try {
            isSubmitting = true;

            // Get encryption key from suggestion (for email links) or extract from share_link
            let encryptionKey = suggestion.encryption_key;
            if (!encryptionKey && 'share_link' in suggestion) {
                // Extract key from share link if not provided directly
                const shareLink = (suggestion as any).share_link;
                if (shareLink && shareLink.includes('#key=')) {
                    encryptionKey = shareLink.split('#key=')[1];
                }
            }

            if (!encryptionKey) {
                throw new Error('Encryption key is required to approve demo chat');
            }

            const response = await fetch(getApiEndpoint('/v1/admin/approve-demo-chat'), {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json'
                },
                credentials: 'include',
                body: JSON.stringify({
                    chat_id: suggestion.chat_id,
                    encryption_key: encryptionKey,  // Pass encryption key to backend
                    title: suggestion.title || 'Demo Chat',
                    summary: suggestion.summary || '',
                    category: suggestion.category || 'General'
                })
            });

            if (!response.ok) {
                const errorText = await response.text();
                throw new Error(errorText || 'Failed to approve demo chat');
            }

            // If this was a pending suggestion from email, clear it
            if (suggestion === pendingSuggestion) {
                pendingSuggestion = null;
                // Clear URL params using native History API (works in shared UI package)
                const url = new URL(window.location.href);
                url.search = '';
                window.history.replaceState({}, '', url.toString());
            }

            // Reload data
            await Promise.all([loadSuggestions(), loadCurrentDemoChats()]);

            // Show success message
            dispatch('showToast', {
                type: 'success',
                message: 'Demo chat approved successfully!'
            });

        } catch (err) {
            console.error('Error approving demo chat:', err);
            dispatch('showToast', {
                type: 'error',
                message: `Failed to approve demo chat: ${err.message}`
            });
        } finally {
            isSubmitting = false;
        }
    }

    /**
     * Remove a demo chat
     */
    async function removeDemoChat(demoId: string) {
        if (!confirm('Are you sure you want to remove this demo chat? This action cannot be undone.')) {
            return;
        }

        try {
            isSubmitting = true;

            const response = await fetch(getApiEndpoint(`/v1/admin/demo-chat/${demoId}`), {
                method: 'DELETE',
                credentials: 'include'
            });

            if (!response.ok) {
                throw new Error('Failed to remove demo chat');
            }

            // Reload data
            await Promise.all([loadSuggestions(), loadCurrentDemoChats()]);

            dispatch('showToast', {
                type: 'success',
                message: 'Demo chat removed successfully!'
            });

        } catch (err) {
            console.error('Error removing demo chat:', err);
            dispatch('showToast', {
                type: 'error',
                message: 'Failed to remove demo chat'
            });
        } finally {
            isSubmitting = false;
        }
    }

    /**
     * Format date for display
     */
    function formatDate(dateString: string): string {
        try {
            const date = new Date(dateString);
            return date.toLocaleDateString('en-US', {
                year: 'numeric',
                month: 'short',
                day: 'numeric',
                hour: '2-digit',
                minute: '2-digit'
            });
        } catch {
            return 'Unknown date';
        }
    }

    /**
     * Handle back button
     */
    function handleBack() {
        dispatch('back');
    }

    /**
     * Open the chat in the main view when coming from email link
     */
    function openChatFromEmail() {
        if (pendingSuggestion && pendingSuggestion.share_link) {
            // Extract chat_id from share link (format: /share/chat/{chat_id}#key=...)
            const shareLink = pendingSuggestion.share_link;
            const match = shareLink.match(/\/share\/chat\/([^#]+)/);
            if (match && match[1]) {
                const chatId = match[1];
                // Navigate to main app with chat loaded
                // This will open the chat in the main view while keeping settings open
                window.location.hash = `chat_id=${chatId}`;
                // Also dispatch event to ensure chat loads
                const event = new CustomEvent('globalChatSelected', {
                    detail: { chat: { chat_id: chatId } },
                    bubbles: true,
                    composed: true
                });
                window.dispatchEvent(event);
            }
        }
    }

    // Load data on mount
    onMount(() => {
        extractUrlParams();
        Promise.all([loadSuggestions(), loadCurrentDemoChats()]);
        
        // If we have a pending suggestion from email, open the chat automatically
        // This allows admin to see the chat while reviewing it
        if (pendingSuggestion) {
            // Small delay to ensure settings are fully loaded
            setTimeout(() => {
                openChatFromEmail();
            }, 500);
        }
    });
</script>

<div class="community-suggestions">
    <!-- Header -->
    <div class="header">
        <button onclick={handleBack} class="back-button">
            ← Back
        </button>
        <h2>Community Chat Suggestions</h2>
        <p>Manage demo chats from community-shared conversations</p>
    </div>

    <!-- Current Demo Chats Section -->
    <div class="section">
        <div class="section-header">
            <h3>Active Demo Chats ({currentDemoChats.length}/5)</h3>
            <span class="limit-info">Maximum 5 demo chats allowed</span>
        </div>

        {#if currentDemoChats.length === 0}
            <div class="empty-state">
                <div class="empty-icon">🎭</div>
                <p>No active demo chats</p>
            </div>
        {:else}
            <div class="demo-grid">
                {#each currentDemoChats as demo}
                    <div class="demo-card">
                        <div class="demo-header">
                            <h4>{demo.title}</h4>
                            {#if demo.category}
                                <span class="category-tag">{demo.category}</span>
                            {/if}
                        </div>

                        {#if demo.summary}
                            <p class="demo-summary">{demo.summary}</p>
                        {/if}

                        <div class="demo-footer">
                            <span class="demo-date">{formatDate(demo.created_at)}</span>
                            <button
                                onclick={() => removeDemoChat(demo.demo_id)}
                                class="btn btn-danger btn-small"
                                disabled={isSubmitting}
                            >
                                Remove
                            </button>
                        </div>
                    </div>
                {/each}
            </div>
        {/if}
    </div>

    <!-- Email Link Suggestion (if present) -->
    {#if pendingSuggestion}
        <div class="section">
            <div class="section-header">
                <h3>New Community Suggestion</h3>
                <span class="email-badge">From Email Link</span>
            </div>

            <div class="email-suggestion-card">
                <div class="suggestion-header">
                    <h4>{pendingSuggestion.title}</h4>
                    <span class="suggestion-date">Just now</span>
                </div>

                {#if pendingSuggestion.summary}
                    <p class="suggestion-summary">{pendingSuggestion.summary}</p>
                {/if}

                <div class="suggestion-actions">
                    <button
                        onclick={() => window.open(pendingSuggestion.share_link, '_blank')}
                        class="btn btn-secondary btn-small"
                    >
                        Preview Chat
                    </button>
                    <button
                        onclick={() => approveDemoChat(pendingSuggestion)}
                        class="btn btn-primary btn-small"
                        disabled={isSubmitting || currentDemoChats.length >= 5}
                    >
                        {#if currentDemoChats.length >= 5}
                            Demo Limit Reached
                        {:else}
                            Approve as Demo
                        {/if}
                    </button>
                </div>
            </div>
        </div>
    {/if}

    <!-- Pending Suggestions Section -->
    <div class="section">
        <div class="section-header">
            <h3>Other Pending Suggestions</h3>
            <span class="count-info">{suggestions.length} suggestions waiting for review</span>
        </div>

        {#if isLoading}
            <div class="loading">
                <div class="spinner"></div>
                <p>Loading community suggestions...</p>
            </div>
        {:else if error}
            <div class="error">
                <div class="error-icon">⚠️</div>
                <p>{error}</p>
                <button onclick={loadSuggestions} class="btn btn-primary">Try Again</button>
            </div>
        {:else if suggestions.length === 0}
            <div class="empty-state">
                <div class="empty-icon">📝</div>
                <p>No pending community suggestions</p>
                <span class="empty-subtext">
                    When users share chats with the community, they will appear here for review.
                </span>
            </div>
        {:else}
            <div class="suggestions-grid">
                {#each suggestions as suggestion}
                    <div class="suggestion-card">
                        <div class="suggestion-header">
                            <h4>{suggestion.title || 'Untitled Chat'}</h4>
                            <span class="suggestion-date">{formatDate(suggestion.shared_at)}</span>
                        </div>

                        {#if suggestion.summary}
                            <p class="suggestion-summary">{suggestion.summary}</p>
                        {/if}

                        <div class="suggestion-actions">
                            <button
                                onclick={() => window.open(suggestion.share_link, '_blank')}
                                class="btn btn-secondary btn-small"
                            >
                                Preview
                            </button>
                            <button
                                onclick={() => approveDemoChat(suggestion)}
                                class="btn btn-primary btn-small"
                                disabled={isSubmitting || currentDemoChats.length >= 5}
                            >
                                {#if currentDemoChats.length >= 5}
                                    Demo Limit Reached
                                {:else}
                                    Approve as Demo
                                {/if}
                            </button>
                        </div>
                    </div>
                {/each}
            </div>
        {/if}
    </div>

    <!-- Info Section -->
    <div class="info-section">
        <div class="info-card">
            <h4>About Demo Chats</h4>
            <ul>
                <li>Demo chats are shown to non-authenticated users</li>
                <li>They showcase OpenMates capabilities to potential users</li>
                <li>Maximum of 5 demo chats to keep selection curated</li>
                <li>Oldest demos are automatically removed when approving new ones</li>
                <li>Demo chats can be previewed before approval</li>
            </ul>
        </div>
    </div>
</div>

<style>
    .community-suggestions {
        padding: 1.5rem;
        max-width: 1000px;
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

    .section {
        margin-bottom: 2rem;
    }

    .section-header {
        display: flex;
        justify-content: space-between;
        align-items: center;
        margin-bottom: 1rem;
    }

    .section-header h3 {
        margin: 0;
        color: var(--color-text-primary);
    }

    .limit-info,
    .count-info {
        font-size: 0.9rem;
        color: var(--color-text-secondary);
    }

    .email-badge {
        background: var(--color-primary);
        color: white;
        padding: 0.25rem 0.75rem;
        border-radius: 1rem;
        font-size: 0.8rem;
        font-weight: 500;
    }

    .email-suggestion-card {
        background: linear-gradient(135deg, var(--color-primary-light) 0%, var(--color-primary-lightest) 100%);
        border: 2px solid var(--color-primary);
        border-radius: 8px;
        padding: 1.5rem;
        margin-bottom: 1rem;
        position: relative;
        overflow: hidden;
    }

    .email-suggestion-card::before {
        content: '✉️';
        position: absolute;
        top: 1rem;
        right: 1rem;
        font-size: 1.5rem;
        opacity: 0.3;
    }

    .demo-grid,
    .suggestions-grid {
        display: grid;
        grid-template-columns: repeat(auto-fill, minmax(300px, 1fr));
        gap: 1rem;
    }

    .demo-card,
    .suggestion-card {
        background: var(--color-background-secondary);
        border: 1px solid var(--color-border);
        border-radius: 8px;
        padding: 1rem;
        transition: all 0.2s ease;
    }

    .demo-card:hover,
    .suggestion-card:hover {
        transform: translateY(-2px);
        box-shadow: 0 4px 12px rgba(0, 0, 0, 0.1);
    }

    .demo-header,
    .suggestion-header {
        display: flex;
        justify-content: space-between;
        align-items: flex-start;
        margin-bottom: 0.75rem;
        gap: 1rem;
    }

    .demo-header h4,
    .suggestion-header h4 {
        margin: 0;
        flex: 1;
        color: var(--color-text-primary);
        line-height: 1.3;
    }

    .category-tag {
        background: var(--color-primary-light);
        color: var(--color-primary);
        padding: 0.25rem 0.5rem;
        border-radius: 4px;
        font-size: 0.8rem;
        font-weight: 500;
        white-space: nowrap;
    }

    .suggestion-date,
    .demo-date {
        font-size: 0.85rem;
        color: var(--color-text-secondary);
        white-space: nowrap;
    }

    .demo-summary,
    .suggestion-summary {
        color: var(--color-text-secondary);
        line-height: 1.4;
        margin-bottom: 1rem;
        display: -webkit-box;
        -webkit-line-clamp: 2;
        line-clamp: 2;
        -webkit-box-orient: vertical;
        overflow: hidden;
    }

    .demo-footer,
    .suggestion-actions {
        display: flex;
        justify-content: space-between;
        align-items: center;
        margin-top: auto;
    }

    .btn {
        padding: 0.5rem 1rem;
        border-radius: 6px;
        font-weight: 500;
        cursor: pointer;
        transition: all 0.2s ease;
        border: none;
        font-size: 0.9rem;
    }

    .btn:disabled {
        opacity: 0.6;
        cursor: not-allowed;
    }

    .btn-small {
        padding: 0.4rem 0.8rem;
        font-size: 0.85rem;
    }

    .btn-primary {
        background: var(--color-primary);
        color: white;
    }

    .btn-primary:hover:not(:disabled) {
        background: var(--color-primary-dark);
    }

    .btn-secondary {
        background: var(--color-background-tertiary);
        color: var(--color-text-secondary);
        border: 1px solid var(--color-border);
    }

    .btn-secondary:hover:not(:disabled) {
        background: var(--color-background-secondary);
        color: var(--color-text-primary);
    }

    .btn-danger {
        background: var(--color-error);
        color: white;
    }

    .btn-danger:hover:not(:disabled) {
        background: var(--color-error-dark);
    }

    .loading,
    .error,
    .empty-state {
        text-align: center;
        padding: 2rem;
    }

    .spinner {
        width: 2rem;
        height: 2rem;
        border: 3px solid var(--color-border);
        border-top: 3px solid var(--color-primary);
        border-radius: 50%;
        animation: spin 1s linear infinite;
        margin: 0 auto 1rem;
    }

    @keyframes spin {
        0% { transform: rotate(0deg); }
        100% { transform: rotate(360deg); }
    }

    .error-icon,
    .empty-icon {
        font-size: 2rem;
        margin-bottom: 0.5rem;
    }

    .empty-subtext {
        display: block;
        margin-top: 0.5rem;
        font-size: 0.9rem;
        color: var(--color-text-tertiary);
    }

    .info-section {
        margin-top: 2rem;
        padding-top: 2rem;
        border-top: 1px solid var(--color-border);
    }

    .info-card {
        background: var(--color-background-secondary);
        border: 1px solid var(--color-border);
        border-radius: 8px;
        padding: 1.5rem;
    }

    .info-card h4 {
        margin: 0 0 1rem 0;
        color: var(--color-text-primary);
    }

    .info-card ul {
        margin: 0;
        padding-left: 1.5rem;
        color: var(--color-text-secondary);
        line-height: 1.6;
    }

    .info-card li {
        margin-bottom: 0.5rem;
    }

    @media (max-width: 768px) {
        .community-suggestions {
            padding: 1rem;
        }

        .demo-grid,
        .suggestions-grid {
            grid-template-columns: 1fr;
        }

        .section-header {
            flex-direction: column;
            align-items: flex-start;
            gap: 0.5rem;
        }

        .demo-footer,
        .suggestion-actions {
            flex-direction: column;
            gap: 0.5rem;
        }

        .demo-header,
        .suggestion-header {
            flex-direction: column;
            gap: 0.5rem;
        }
    }
</style>