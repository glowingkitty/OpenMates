<!--
    Settings Community Suggestions Component

    Shows pending community chat suggestions for admin approval.
    Allows admins to approve chats to become demo chats.
-->
<script lang="ts">
    import { createEventDispatcher, onMount, onDestroy } from 'svelte';
    import { getApiEndpoint } from '@repo/ui';
    import Chat from '../../chats/Chat.svelte';
    import type { Chat as ChatType } from '../../../types/chat';
    import { webSocketService } from '../../../services/websocketService';

    const dispatch = createEventDispatcher();

    interface Suggestion {
        demo_chat_id?: string;  // UUID of the pending demo_chat entry (optional for email deep links)
        chat_id: string;
        title: string;
        summary?: string;
        category?: string;
        icon?: string;
        follow_up_suggestions?: string[];
        shared_at: string;
        share_link: string;
        encryption_key?: string;  // No longer needed with zero-knowledge architecture, kept for backward compatibility
        status?: string;  // Status of the demo_chat entry (pending_approval, translating, published, translation_failed)
    }

    interface DemoChat {
        id: string;  // UUID of the demo_chat entry
        title?: string;
        summary?: string;
        category?: string;
        icon?: string;
        status?: string;
        demo_chat_category?: string;  // 'for_everyone' or 'for_developers'
        created_at: string;
    }

    interface DemoChatUpdatePayload {
        user_id?: string;
        demo_chat_id: string;
        status: string;
    }

    interface DemoChatProgressPayload {
        user_id?: string;
        demo_chat_id: string;
        stage: 'metadata' | 'translating' | 'storing';
        progress_percentage?: number;
        current_language?: string;
        message?: string;
    }

    interface TranslationProgress {
        stage: 'metadata' | 'translating' | 'storing';
        progress_percentage: number;
        current_language: string;
        message: string;
        last_update: number;
    }

    // State
    let isLoading = $state(true);
    let error = $state<string | null>(null);
    let suggestions = $state<Suggestion[]>([]);
    let currentDemoChats = $state<DemoChat[]>([]);
    let isSubmitting = $state(false);
    let pendingSuggestion = $state<Suggestion | null>(null);
    let selectedDemoChatCategory = $state<string>('for_everyone');  // Category to assign when approving

    // UI visibility limits (published demos can exceed these; older demos remain link-accessible)
    const UI_CATEGORY_LIMITS: Record<string, number> = { for_everyone: 10, for_developers: 4 };

    // Translation progress tracking
    let translationProgress = $state<Map<string, TranslationProgress>>(new Map());

    // URL parameters for email link
    let urlParams = $state<{ chat_id?: string; key?: string; title?: string; summary?: string; category?: string; icon?: string; follow_up_suggestions?: string }>({});

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
                summary: searchParams.get('summary') || undefined,
                category: searchParams.get('category') || undefined,
                icon: searchParams.get('icon') || undefined,
                follow_up_suggestions: searchParams.get('follow_up_suggestions') || undefined
            };

            // If we have URL params, create a pending suggestion
            if (urlParams.chat_id && urlParams.key) {
                let followUpSuggestions: string[] | undefined = undefined;
                if (urlParams.follow_up_suggestions) {
                    try {
                        followUpSuggestions = JSON.parse(decodeURIComponent(urlParams.follow_up_suggestions));
                    } catch (e) {
                        console.warn('Failed to parse follow-up suggestions from URL:', e);
                    }
                }

                pendingSuggestion = {
                    chat_id: urlParams.chat_id,
                    encryption_key: urlParams.key,
                    title: decodeURIComponent(urlParams.title || 'Community Shared Chat'),
                    summary: decodeURIComponent(urlParams.summary || ''),
                    category: urlParams.category || undefined,
                    icon: urlParams.icon || undefined,
                    follow_up_suggestions: followUpSuggestions,
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

            const { getApiEndpoint } = await import('@repo/ui');
    const lang = document.documentElement.lang || 'en';
    const response = await fetch(getApiEndpoint('/v1/admin/community-suggestions?lang=' + lang), {
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
            const lang = document.documentElement.lang || 'en';
    const response = await fetch(getApiEndpoint('/v1/admin/demo-chats?lang=' + lang), {
                credentials: 'include'
            });

            if (response.ok) {
                const data = await response.json();
                // Show published and translating demo chats in the "Active Demo Chats" section
                // pending_approval demos appear in "Other Pending Suggestions"
                currentDemoChats = (data.demo_chats || []).filter(demo => 
                    demo.status === 'published' || demo.status === 'translating'
                );
            }

        } catch (err) {
            console.error('Error loading demo chats:', err);
        }
    }

    // Preview modal state
    interface PreviewMessage {
        message_id: string;
        role: string;
        content: string;
        category?: string;
        model_name?: string;
        created_at?: string;
    }

    interface PreviewEmbed {
        embed_id: string;
        type: string;
        content: string;
        embed_ids?: string[];
        parent_embed_id?: string;
        created_at?: string;
    }

    interface PreviewData {
        title: string;
        summary?: string;
        messages: PreviewMessage[];
        embeds: PreviewEmbed[];
    }

    let previewOpen = $state(false);
    let previewLoading = $state(false);
    let previewError = $state<string | null>(null);
    let previewData = $state<PreviewData | null>(null);
    let previewSuggestion = $state<Suggestion | null>(null);

    /**
     * Approve a chat as demo chat
     * With zero-knowledge architecture, we don't need to send the encryption key
     * The server already has the decrypted content stored (Vault-encrypted)
     */
    async function approveDemoChat(suggestion: Suggestion) {
        try {
            isSubmitting = true;

            const response = await fetch(getApiEndpoint('/v1/admin/approve-demo-chat'), {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json'
                },
                credentials: 'include',
                body: JSON.stringify({
                    demo_chat_id: suggestion.demo_chat_id,  // UUID of the pending entry
                    chat_id: suggestion.chat_id,
                    demo_chat_category: selectedDemoChatCategory  // Target audience: for_everyone or for_developers
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

            // Optimistically add to currentDemoChats with full metadata from suggestion
            // This will be updated when the translation task completes
            currentDemoChats = [...currentDemoChats, {
                id: suggestion.demo_chat_id!,
                title: suggestion.title,
                summary: suggestion.summary,
                category: suggestion.category,
                icon: suggestion.icon,
                status: 'translating',
                demo_chat_category: selectedDemoChatCategory,
                created_at: new Date().toISOString()
            }];

            // Remove from suggestions list
            suggestions = suggestions.filter(s => s.demo_chat_id !== suggestion.demo_chat_id);

            // Show success message
            dispatch('showToast', {
                type: 'success',
                message: 'Demo chat approved! Translation in progress...'
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
     * Reject a community suggestion
     * Deactivates the pending demo_chat entry and removes from community suggestions
     */
    async function rejectSuggestion(demoChatId: string, chatId: string) {
        if (!confirm('Are you sure you want to reject this suggestion? It will be removed from the review queue.')) {
            return;
        }

        // Optimistically remove the suggestion from the UI
        const suggestionIndex = suggestions.findIndex(s => s.chat_id === chatId);
        const removedSuggestion = suggestionIndex !== -1 ? suggestions[suggestionIndex] : null;

        if (removedSuggestion) {
            suggestions.splice(suggestionIndex, 1);
            suggestions = [...suggestions]; // Trigger reactivity
        }

        try {
            isSubmitting = true;

            const response = await fetch(getApiEndpoint('/v1/admin/reject-suggestion'), {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json'
                },
                credentials: 'include',
                body: JSON.stringify({
                    demo_chat_id: demoChatId,  // UUID
                    chat_id: chatId
                })
            });

            if (!response.ok) {
                throw new Error('Failed to reject suggestion');
            }

            // If this was a pending suggestion from email, clear it
            if (pendingSuggestion && pendingSuggestion.chat_id === chatId) {
                pendingSuggestion = null;
                // Clear URL params using native History API (works in shared UI package)
                const url = new URL(window.location.href);
                url.search = '';
                window.history.replaceState({}, '', url.toString());
            }

            dispatch('showToast', {
                type: 'success',
                message: 'Suggestion rejected successfully'
            });

        } catch (err) {
            console.error('Error rejecting suggestion:', err);

            // Restore the suggestion if the API call failed
            if (removedSuggestion) {
                suggestions = [removedSuggestion, ...suggestions];
            }

            dispatch('showToast', {
                type: 'error',
                message: err instanceof Error ? err.message : 'Failed to reject suggestion'
            });
        } finally {
            isSubmitting = false;
        }
    }

    /**
     * Helper to reject a pending suggestion from email deep link
     * Looks up the demo_chat_id from loaded suggestions if not present in the pendingSuggestion
     */
    function rejectPendingSuggestion(suggestion: Suggestion) {
        // For email deep-link pending suggestions, look up demo_chat_id from loaded suggestions
        const matchingSuggestion = suggestions.find(s => s.chat_id === suggestion.chat_id);
        const demoChatId = suggestion.demo_chat_id || matchingSuggestion?.demo_chat_id || '';
        
        if (demoChatId) {
            rejectSuggestion(demoChatId, suggestion.chat_id);
        } else {
            console.error('Cannot reject: demo_chat_id not found for chat', suggestion.chat_id);
            dispatch('showToast', {
                type: 'error',
                message: 'Cannot reject: suggestion not found in pending list'
            });
        }
    }

    /**
     * Helper to approve a pending suggestion from email deep link
     * Merges demo_chat_id from loaded suggestions if not present in the pendingSuggestion
     */
    function approvePendingSuggestion(suggestion: Suggestion) {
        // For email deep-link pending suggestions, merge with matching loaded suggestion to get demo_chat_id
        const matchingSuggestion = suggestions.find(s => s.chat_id === suggestion.chat_id);
        const mergedSuggestion = matchingSuggestion 
            ? { ...suggestion, demo_chat_id: matchingSuggestion.demo_chat_id }
            : suggestion;
        
        if (mergedSuggestion.demo_chat_id) {
            approveDemoChat(mergedSuggestion);
        } else {
            console.error('Cannot approve: demo_chat_id not found for chat', suggestion.chat_id);
            dispatch('showToast', {
                type: 'error',
                message: 'Cannot approve: suggestion not found in pending list'
            });
        }
    }

    /**
     * Remove a demo chat
     */
    async function removeDemoChat(demoChatId: string) {
        if (!confirm('Are you sure you want to remove this demo chat? This action cannot be undone.')) {
            return;
        }

        // Optimistically remove the demo chat from the UI
        const demoChatIndex = currentDemoChats.findIndex(d => d.id === demoChatId);
        const removedDemoChat = demoChatIndex !== -1 ? currentDemoChats[demoChatIndex] : null;

        if (removedDemoChat) {
            currentDemoChats.splice(demoChatIndex, 1);
            currentDemoChats = [...currentDemoChats]; // Trigger reactivity
        }

        try {
            isSubmitting = true;

            const response = await fetch(getApiEndpoint(`/v1/admin/demo-chat/${demoChatId}`), {
                method: 'DELETE',
                credentials: 'include'
            });

            if (!response.ok) {
                throw new Error('Failed to remove demo chat');
            }

            dispatch('showToast', {
                type: 'success',
                message: 'Demo chat removed successfully!'
            });

        } catch (err) {
            console.error('Error removing demo chat:', err);

            // Restore the demo chat if the API call failed
            if (removedDemoChat) {
                currentDemoChats = [...currentDemoChats, removedDemoChat];
            }

            dispatch('showToast', {
                type: 'error',
                message: 'Failed to remove demo chat'
            });
        } finally {
            isSubmitting = false;
        }
    }

    /**
     * Update the category of an existing demo chat
     */
    async function updateDemoChatCategory(demoChatId: string, newCategory: string) {
        try {
            isSubmitting = true;

            const response = await fetch(getApiEndpoint(`/v1/admin/demo-chat/${demoChatId}/category`), {
                method: 'PATCH',
                headers: {
                    'Content-Type': 'application/json'
                },
                credentials: 'include',
                body: JSON.stringify({
                    demo_chat_category: newCategory
                })
            });

            if (!response.ok) {
                const data = await response.json().catch(() => ({ detail: 'Unknown error' }));
                throw new Error(data.detail || 'Failed to update category');
            }

            // Update locally
            const demoIndex = currentDemoChats.findIndex(d => d.id === demoChatId);
            if (demoIndex !== -1) {
                currentDemoChats[demoIndex] = {
                    ...currentDemoChats[demoIndex],
                    demo_chat_category: newCategory
                };
                currentDemoChats = [...currentDemoChats];
            }

            dispatch('showToast', {
                type: 'success',
                message: `Category updated to "${newCategory === 'for_developers' ? 'For developers' : 'For everyone'}"`
            });

        } catch (err) {
            console.error('Error updating demo chat category:', err);
            // Reload to revert optimistic update
            loadCurrentDemoChats();
            dispatch('showToast', {
                type: 'error',
                message: err instanceof Error ? err.message : 'Failed to update category'
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
     * Helper to create a virtual chat object for display in the Chat component
     */
    function createVirtualChat(item: Suggestion): ChatType {
        const now = Math.floor(Date.now() / 1000);
        return {
            chat_id: item.chat_id,
            title: item.title || undefined, // Use title from backend (already decrypted)
            // ARCHITECTURE: Use cleartext fields for demo/preview chats (already decrypted by server)
            category: item.category,
            icon: item.icon,
            follow_up_request_suggestions: item.follow_up_suggestions ? JSON.stringify(item.follow_up_suggestions) : undefined,
            waiting_for_metadata: false,
            messages_v: 1,
            title_v: 1,
            pinned: false,
            is_incognito: false,
            unread_count: 0,
            encrypted_title: '', // Empty for virtual chats - title is in cleartext `title` field
            last_edited_overall_timestamp: now,
            created_at: now,
            updated_at: now
        };
    }

    /**
     * Open a preview modal showing the full chat content from the admin preview endpoint.
     *
     * The demo_chat entry stores decrypted content (submitted by the user at share time),
     * so the admin can review messages and embeds without needing the encryption key.
     */
    async function openChatPreview(suggestion: Suggestion) {
        if (!suggestion.demo_chat_id) {
            dispatch('showToast', {
                type: 'error',
                message: 'Cannot preview: demo chat ID not found'
            });
            return;
        }

        previewSuggestion = suggestion;
        previewOpen = true;
        previewLoading = true;
        previewError = null;
        previewData = null;

        try {
            const response = await fetch(
                getApiEndpoint(`/v1/admin/demo-chat/${suggestion.demo_chat_id}/preview`),
                { credentials: 'include' }
            );

            if (!response.ok) {
                const errorText = await response.text();
                throw new Error(errorText || `Server returned ${response.status}`);
            }

            const data = await response.json();
            previewData = {
                title: data.title || suggestion.title || 'Untitled Chat',
                summary: data.summary || suggestion.summary,
                messages: data.messages || [],
                embeds: data.embeds || []
            };
        } catch (err) {
            console.error('[SettingsCommunitySuggestions] Error loading preview:', err);
            previewError = err instanceof Error ? err.message : 'Failed to load chat preview';
        } finally {
            previewLoading = false;
        }
    }

    /**
     * Close the preview modal
     */
    function closePreview() {
        previewOpen = false;
        previewData = null;
        previewSuggestion = null;
        previewError = null;
    }

    /**
     * Try to parse JSON content for display.
     * Embeds store their content as a JSON string.
     */
    function tryParseJson(content: string): unknown {
        try { return JSON.parse(content); } catch { return content; }
    }

    /**
     * Get a human-readable label for an embed type string
     */
    function embedTypeLabel(type: string): string {
        // Common patterns: "app_skill_use", "web-search", "images-search", etc.
        return type.replace(/[_-]/g, ' ').replace(/\b\w/g, c => c.toUpperCase());
    }

    // Load data on mount
    onMount(() => {
        extractUrlParams();
        Promise.all([loadSuggestions(), loadCurrentDemoChats()]).then(() => {
            // If we have a pending suggestion from email, open the preview automatically
            if (pendingSuggestion) {
                // Merge demo_chat_id from loaded suggestions if available
                const matchingSuggestion = suggestions.find(s => s.chat_id === pendingSuggestion!.chat_id);
                if (matchingSuggestion?.demo_chat_id) {
                    pendingSuggestion = { ...pendingSuggestion!, demo_chat_id: matchingSuggestion.demo_chat_id };
                }
                if (pendingSuggestion!.demo_chat_id) {
                    openChatPreview(pendingSuggestion!);
                }
            }
        });

        // Register WebSocket handlers
        webSocketService.on('demo_chat_updated', handleDemoChatUpdate);
        webSocketService.on('demo_chat_progress', handleDemoChatProgress);
    });

    onDestroy(() => {
        // Clean up WebSocket handlers
        webSocketService.off('demo_chat_updated', handleDemoChatUpdate);
        webSocketService.off('demo_chat_progress', handleDemoChatProgress);
    });

    /**
     * Handle WebSocket updates for demo chats
     * Updates the status and metadata when translation completes
     */
    function handleDemoChatUpdate(payload: DemoChatUpdatePayload) {
        console.warn('[SettingsCommunitySuggestions] Received demo_chat_updated event:', payload);
        
        const { demo_chat_id, status } = payload;
        
        // Find and update the demo chat in currentDemoChats
        const demoIndex = currentDemoChats.findIndex(d => d.id === demo_chat_id);
        if (demoIndex !== -1) {
            currentDemoChats[demoIndex] = {
                ...currentDemoChats[demoIndex],
                status
            };
            currentDemoChats = [...currentDemoChats]; // Trigger reactivity
            
            // If translation completed, reload to get full metadata
            if (status === 'published') {
                console.warn('[SettingsCommunitySuggestions] Demo chat published, reloading data...');
                loadCurrentDemoChats();
                
                dispatch('showToast', {
                    type: 'success',
                    message: 'Demo chat translation completed and published!'
                });
            } else if (status === 'translation_failed') {
                dispatch('showToast', {
                    type: 'error',
                    message: 'Demo chat translation failed. Please try again.'
                });
            }
        }
    }

    /**
     * Handle WebSocket progress updates for demo chat translation
     * 
     * The backend sends granular progress updates with:
     * - stage: 'metadata' | 'translating'
     * - completed_units: number of language units completed
     * - total_units: total language units (messages × languages)
     * - progress_percentage: 0-100
     * - current_batch_languages: array of language codes just completed
     * - message: human-readable status message
     */
    function handleDemoChatProgress(payload: DemoChatProgressPayload) {
        console.warn('[SettingsCommunitySuggestions] Received demo_chat_progress event:', payload);

        const { 
            demo_chat_id, 
            stage, 
            progress_percentage, 
            current_language,
            message 
        } = payload;

        // Ensure progress only moves forward (monotonically increasing)
        const existing = translationProgress.get(demo_chat_id);
        const newPercentage = progress_percentage || 0;
        const effectivePercentage = existing 
            ? Math.max(existing.progress_percentage, newPercentage) 
            : newPercentage;

        // Update progress state
        translationProgress.set(demo_chat_id, {
            stage,
            progress_percentage: effectivePercentage,
            current_language: current_language || '',
            message: message || 'Processing...',
            last_update: Date.now()
        });

        // Trigger reactivity
        translationProgress = new Map(translationProgress);

        // Update the demo chat in currentDemoChats if it exists
        const demoIndex = currentDemoChats.findIndex(d => d.id === demo_chat_id);
        if (demoIndex !== -1) {
            currentDemoChats[demoIndex] = {
                ...currentDemoChats[demoIndex],
                status: 'translating'
            };
            currentDemoChats = [...currentDemoChats]; // Trigger reactivity
        }
    }

    /**
     * Get progress information for a demo chat
     */
    function getProgressInfo(demoChatId: string) {
        return translationProgress.get(demoChatId);
    }

</script>

<div class="community-suggestions">
    <!-- Header -->
    <div class="header">
        <h2>Community Chat Suggestions</h2>
        <p>Manage demo chats from community-shared conversations</p>
    </div>

    <!-- Current Demo Chats Section -->
    <div class="section">
        <div class="section-header">
            <h3>Active Demo Chats ({currentDemoChats.length})</h3>
            <span class="limit-info">UI visible: latest {UI_CATEGORY_LIMITS.for_everyone} for everyone, latest {UI_CATEGORY_LIMITS.for_developers} for developers</span>
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
                            <h4>{demo.title || 'Demo Chat'}</h4>
                            <div class="header-tags">
                                {#if demo.status}
                                    <span class="status-tag status-{demo.status}">
                                        {#if demo.status === 'published'}
                                            ✅ Published
                                        {:else if demo.status === 'translation_failed'}
                                            ❌ Failed
                                        {:else if demo.status === 'translating'}
                                            ⏳ Translating...
                                        {:else}
                                            {demo.status}
                                        {/if}
                                    </span>
                                {/if}
                                <select
                                    class="category-inline-select category-select-{demo.demo_chat_category || 'for_everyone'}"
                                    value={demo.demo_chat_category || 'for_everyone'}
                                    onchange={(e) => updateDemoChatCategory(demo.id, e.currentTarget.value)}
                                    disabled={isSubmitting}
                                    title="Change demo chat category"
                                >
                                    <option value="for_everyone">Everyone</option>
                                    <option value="for_developers">Developers</option>
                                </select>
                                {#if demo.category}
                                    <span class="category-tag">{demo.category}</span>
                                {:else if demo.icon}
                                    <span class="icon-tag">{demo.icon}</span>
                                {/if}
                            </div>
                        </div>

                        <!-- Translation Progress Bar -->
                        {#if demo.status === 'translating'}
                            {@const progress = getProgressInfo(demo.id)}
                            <div class="translation-progress">
                                <div class="progress-bar-container">
                                    <div 
                                        class="progress-bar-fill" 
                                        style="width: {progress?.progress_percentage || 0}%"
                                    ></div>
                                </div>
                                <div class="progress-info">
                                    {#if progress}
                                        <span class="progress-text">
                                            {progress.message}
                                        </span>
                                        <span class="progress-percentage">
                                            {progress.progress_percentage}%
                                        </span>
                                    {:else}
                                        <span class="progress-text">Starting translation...</span>
                                        <span class="progress-percentage">0%</span>
                                    {/if}
                                </div>
                                {#if progress?.current_language}
                                    <div class="progress-languages">
                                        Currently translating: {progress.current_language.toUpperCase()}
                                    </div>
                                {/if}
                            </div>
                        {/if}

                        {#if demo.summary}
                            <p class="demo-summary">{demo.summary}</p>
                        {/if}

                        <div class="demo-footer">
                            <span class="demo-date">{formatDate(demo.created_at)}</span>
                            <button
                                onclick={() => removeDemoChat(demo.id)}
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
                <!-- svelte-ignore a11y_click_events_have_key_events -->
                <!-- svelte-ignore a11y_no_static_element_interactions -->
                <div 
                    class="suggestion-chat-preview clickable" 
                    onclick={() => openChatPreview(pendingSuggestion!)}
                    title="Click to preview chat content"
                >
                    <Chat 
                        chat={createVirtualChat(pendingSuggestion)}
                        activeChatId={undefined}
                        selectMode={false}
                    />
                </div>

                {#if pendingSuggestion.summary}
                    <p class="suggestion-summary">{pendingSuggestion.summary}</p>
                {/if}

                <div class="suggestion-actions">
                    <div class="category-selection">
                        <label for="category-select-email" class="replacement-label">Target audience:</label>
                        <select
                            id="category-select-email"
                            bind:value={selectedDemoChatCategory}
                            class="replacement-select"
                        >
                            <option value="for_everyone">For everyone</option>
                            <option value="for_developers">For developers</option>
                        </select>
                    </div>
                    <button
                        onclick={() => rejectPendingSuggestion(pendingSuggestion!)}
                        class="btn btn-danger btn-small"
                        disabled={isSubmitting}
                    >
                        Reject
                    </button>
                    <button
                        onclick={() => approvePendingSuggestion(pendingSuggestion!)}
                        class="btn btn-primary btn-small"
                        disabled={isSubmitting}
                    >
                        Approve as Demo
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
                        <!-- svelte-ignore a11y_click_events_have_key_events -->
                        <!-- svelte-ignore a11y_no_static_element_interactions -->
                        <div 
                            class="suggestion-chat-preview clickable"
                            onclick={() => openChatPreview(suggestion)}
                            title="Click to preview chat content"
                        >
                            <Chat 
                                chat={createVirtualChat(suggestion)}
                                activeChatId={undefined}
                                selectMode={false}
                            />
                        </div>

                        {#if suggestion.summary}
                            <p class="suggestion-summary">{suggestion.summary}</p>
                        {/if}

                        <div class="suggestion-actions">
                            <div class="category-selection">
                                <label for="category-select-{suggestion.chat_id}" class="replacement-label">Target audience:</label>
                                <select
                                    id="category-select-{suggestion.chat_id}"
                                    bind:value={selectedDemoChatCategory}
                                    class="replacement-select"
                                >
                                    <option value="for_everyone">For everyone</option>
                                    <option value="for_developers">For developers</option>
                                </select>
                            </div>
                            <button
                                onclick={() => rejectSuggestion(suggestion.demo_chat_id, suggestion.chat_id)}
                                class="btn btn-danger btn-small"
                                disabled={isSubmitting}
                            >
                                Reject
                            </button>
                            <button
                                onclick={() => approveDemoChat(suggestion)}
                                class="btn btn-primary btn-small"
                                disabled={isSubmitting}
                            >
                                Approve as Demo
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
                <li>No hard publish cap: older demo chats remain available until manually removed</li>
                <li>"For everyone" chats are shown in the main intro chat</li>
                <li>"For developers" chats are shown in the developers intro chat</li>
                <li>Only the latest 10 "For everyone" and latest 4 "For developers" are shown in UI lists</li>
                <li>Older demo chats remain accessible via direct /demo/chat/{'{slug}'} links</li>
                <li>Click a chat preview to view the full conversation with embeds</li>
            </ul>
        </div>
    </div>
</div>

<!-- Chat Preview Modal -->
{#if previewOpen}
    <!-- svelte-ignore a11y_click_events_have_key_events -->
    <!-- svelte-ignore a11y_no_static_element_interactions -->
    <div class="preview-overlay" onclick={closePreview}>
        <!-- svelte-ignore a11y_click_events_have_key_events -->
        <!-- svelte-ignore a11y_no_static_element_interactions -->
        <div class="preview-modal" onclick={(e) => e.stopPropagation()}>
            <div class="preview-header">
                <h3>{previewData?.title || previewSuggestion?.title || 'Chat Preview'}</h3>
                <button class="preview-close-btn" onclick={closePreview} aria-label="Close preview">
                    &times;
                </button>
            </div>

            {#if previewLoading}
                <div class="loading">
                    <div class="spinner"></div>
                    <p>Loading chat content...</p>
                </div>
            {:else if previewError}
                <div class="error">
                    <div class="error-icon">&#x26A0;&#xFE0F;</div>
                    <p>{previewError}</p>
                </div>
            {:else if previewData}
                {#if previewData.summary}
                    <div class="preview-summary">
                        <strong>Summary:</strong> {previewData.summary}
                    </div>
                {/if}

                <div class="preview-stats">
                    <span>{previewData.messages.length} messages</span>
                    {#if previewData.embeds.length > 0}
                        <span>&middot; {previewData.embeds.length} embeds</span>
                    {/if}
                </div>

                <div class="preview-messages">
                    {#each previewData.messages as msg}
                        <div class="preview-message preview-message-{msg.role}">
                            <div class="preview-message-header">
                                <span class="preview-role">{msg.role === 'user' ? 'User' : msg.role === 'assistant' ? 'Assistant' : 'System'}</span>
                                {#if msg.model_name}
                                    <span class="preview-model">{msg.model_name}</span>
                                {/if}
                            </div>
                            <div class="preview-message-content">
                                {#if msg.role === 'system'}
                                    {#if typeof tryParseJson(msg.content) === 'object'}
                                        <pre class="preview-json">{JSON.stringify(tryParseJson(msg.content), null, 2)}</pre>
                                    {:else}
                                        <p>{msg.content}</p>
                                    {/if}
                                {:else}
                                    <p>{msg.content}</p>
                                {/if}
                            </div>
                        </div>
                    {/each}
                </div>

                {#if previewData.embeds.length > 0}
                    <div class="preview-embeds-section">
                        <h4>Embeds ({previewData.embeds.length})</h4>
                        {#each previewData.embeds as embed}
                            <div class="preview-embed" class:is-child={!!embed.parent_embed_id}>
                                <div class="preview-embed-header">
                                    <span class="preview-embed-type">{embedTypeLabel(embed.type)}</span>
                                    <span class="preview-embed-id" title={embed.embed_id}>{embed.embed_id.slice(0, 8)}...</span>
                                    {#if embed.parent_embed_id}
                                        <span class="preview-embed-child-badge">child of {embed.parent_embed_id.slice(0, 8)}...</span>
                                    {/if}
                                    {#if embed.embed_ids && embed.embed_ids.length > 0}
                                        <span class="preview-embed-parent-badge">{embed.embed_ids.length} children</span>
                                    {/if}
                                </div>
                                {#if typeof tryParseJson(embed.content) === 'object'}
                                    <pre class="preview-json">{JSON.stringify(tryParseJson(embed.content), null, 2)}</pre>
                                {:else}
                                    <p class="preview-embed-content">{embed.content}</p>
                                {/if}
                            </div>
                        {/each}
                    </div>
                {/if}
            {/if}
        </div>
    </div>
{/if}

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
        display: flex;
        flex-direction: column;
        min-height: 0; /* Allow flex children to shrink */
        overflow: visible; /* Ensure buttons are not clipped */
    }

    .demo-card:hover,
    .suggestion-card:hover {
        transform: translateY(-2px);
        box-shadow: 0 4px 12px rgba(0, 0, 0, 0.1);
    }

    .suggestion-chat-preview {
        margin-bottom: 1rem;
        background: var(--color-background-tertiary);
        border-radius: 8px;
        overflow: hidden;
        border: 1px solid var(--color-border);
        transition: all 0.2s ease;
    }

    .suggestion-chat-preview.clickable {
        cursor: pointer;
    }

    .suggestion-chat-preview.clickable:hover {
        border-color: var(--color-primary);
        background: var(--color-background-secondary);
        transform: scale(1.02);
    }

    .demo-header {
        display: flex;
        justify-content: space-between;
        align-items: flex-start;
        margin-bottom: 0.75rem;
        gap: 1rem;
    }

    .demo-header h4 {
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

    .audience-tag {
        padding: 0.2rem 0.4rem;
        border-radius: 4px;
        font-size: 0.7rem;
        font-weight: 600;
        text-transform: uppercase;
        white-space: nowrap;
    }

    .audience-for_everyone {
        background: #DBEAFE;
        color: #1E40AF;
    }

    .audience-for_developers {
        background: #FEF3C7;
        color: #92400E;
    }

    .category-inline-select {
        padding: 0.15rem 0.3rem;
        border-radius: 4px;
        font-size: 0.7rem;
        font-weight: 600;
        text-transform: uppercase;
        white-space: nowrap;
        border: 1px solid transparent;
        cursor: pointer;
        appearance: auto;
        transition: border-color 0.2s ease;
    }

    .category-inline-select:hover:not(:disabled) {
        border-color: var(--color-border);
    }

    .category-inline-select:disabled {
        opacity: 0.6;
        cursor: not-allowed;
    }

    .category-select-for_everyone {
        background: #DBEAFE;
        color: #1E40AF;
    }

    .category-select-for_developers {
        background: #FEF3C7;
        color: #92400E;
    }

    .category-selection {
        width: 100%;
        margin-bottom: 0.75rem;
        padding: 0.75rem;
        background: var(--color-background-tertiary);
        border-radius: 6px;
        border: 1px solid var(--color-border);
    }

    .header-tags {
        display: flex;
        gap: 0.5rem;
        align-items: center;
    }

    .status-tag {
        padding: 0.2rem 0.4rem;
        border-radius: 4px;
        font-size: 0.75rem;
        font-weight: 600;
        text-transform: uppercase;
    }

    .status-translating {
        background: #FEF3C7;
        color: #92400E;
    }

    .status-published {
        background: #D1FAE5;
        color: #065F46;
    }

    .status-error,
    .status-translation_failed {
        background: #FEE2E2;
        color: #991B1B;
    }

    /* Translation Progress Bar Styles */
    .translation-progress {
        margin: 0.75rem 0;
        padding: 0.75rem;
        background: var(--color-background-tertiary);
        border-radius: 6px;
        border: 1px solid var(--color-border);
    }

    .progress-bar-container {
        width: 100%;
        height: 8px;
        background: var(--color-background-secondary);
        border-radius: 4px;
        overflow: hidden;
        margin-bottom: 0.5rem;
    }

    .progress-bar-fill {
        height: 100%;
        background: linear-gradient(90deg, var(--color-primary) 0%, var(--color-primary-light) 100%);
        border-radius: 4px;
        transition: width 0.3s ease-out;
        position: relative;
    }

    .progress-bar-fill::after {
        content: '';
        position: absolute;
        top: 0;
        left: 0;
        right: 0;
        bottom: 0;
        background: linear-gradient(
            90deg,
            transparent 0%,
            rgba(255, 255, 255, 0.2) 50%,
            transparent 100%
        );
        animation: shimmer 1.5s infinite;
    }

    @keyframes shimmer {
        0% { transform: translateX(-100%); }
        100% { transform: translateX(100%); }
    }

    .progress-info {
        display: flex;
        justify-content: space-between;
        align-items: center;
        font-size: 0.8rem;
    }

    .progress-text {
        color: var(--color-text-secondary);
        flex: 1;
        overflow: hidden;
        text-overflow: ellipsis;
        white-space: nowrap;
        margin-right: 0.5rem;
    }

    .progress-percentage {
        color: var(--color-primary);
        font-weight: 600;
        white-space: nowrap;
    }

    .progress-languages {
        font-size: 0.75rem;
        color: var(--color-text-tertiary);
        margin-top: 0.25rem;
        overflow: hidden;
        text-overflow: ellipsis;
        white-space: nowrap;
    }

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
        justify-content: flex-start;
        align-items: center;
        margin-top: auto;
        gap: 0.5rem;
        flex-wrap: wrap;
        width: 100%;
    }

    .replacement-selection {
        width: 100%;
        margin-bottom: 0.75rem;
        padding: 0.75rem;
        background: var(--color-background-tertiary);
        border-radius: 6px;
        border: 1px solid var(--color-border);
    }

    .replacement-label {
        display: block;
        font-size: 0.85rem;
        font-weight: 500;
        color: var(--color-text-primary);
        margin-bottom: 0.5rem;
    }

    .replacement-select {
        width: 100%;
        padding: 0.5rem;
        border: 1px solid var(--color-border);
        border-radius: 4px;
        background: var(--color-background-secondary);
        color: var(--color-text-primary);
        font-size: 0.9rem;
        cursor: pointer;
    }

    .replacement-select:focus {
        outline: none;
        border-color: var(--color-primary);
        box-shadow: 0 0 0 2px rgba(59, 130, 246, 0.1);
    }
    
    .suggestion-actions .btn {
        flex: 0 0 auto;
        min-width: fit-content;
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

    /* Preview Modal Styles */
    .preview-overlay {
        position: fixed;
        inset: 0;
        background: rgba(0, 0, 0, 0.6);
        z-index: 9999;
        display: flex;
        align-items: center;
        justify-content: center;
        padding: 1rem;
    }

    .preview-modal {
        background: var(--color-background-primary);
        border: 1px solid var(--color-border);
        border-radius: 12px;
        width: 100%;
        max-width: 700px;
        max-height: 85vh;
        display: flex;
        flex-direction: column;
        overflow: hidden;
        box-shadow: 0 20px 60px rgba(0, 0, 0, 0.3);
    }

    .preview-header {
        display: flex;
        justify-content: space-between;
        align-items: center;
        padding: 1rem 1.25rem;
        border-bottom: 1px solid var(--color-border);
        flex-shrink: 0;
    }

    .preview-header h3 {
        margin: 0;
        font-size: 1.1rem;
        color: var(--color-text-primary);
        overflow: hidden;
        text-overflow: ellipsis;
        white-space: nowrap;
        flex: 1;
        margin-right: 1rem;
    }

    .preview-close-btn {
        background: none;
        border: none;
        font-size: 1.5rem;
        cursor: pointer;
        color: var(--color-text-secondary);
        padding: 0 0.25rem;
        line-height: 1;
        flex-shrink: 0;
    }

    .preview-close-btn:hover {
        color: var(--color-text-primary);
    }

    .preview-summary {
        padding: 0.75rem 1.25rem;
        font-size: 0.9rem;
        color: var(--color-text-secondary);
        border-bottom: 1px solid var(--color-border);
        flex-shrink: 0;
    }

    .preview-stats {
        padding: 0.5rem 1.25rem;
        font-size: 0.8rem;
        color: var(--color-text-tertiary);
        border-bottom: 1px solid var(--color-border);
        flex-shrink: 0;
    }

    .preview-stats span + span {
        margin-left: 0.25rem;
    }

    .preview-messages {
        overflow-y: auto;
        padding: 1rem 1.25rem;
        flex: 1;
        min-height: 0;
    }

    .preview-message {
        margin-bottom: 1rem;
        padding: 0.75rem;
        border-radius: 8px;
        border: 1px solid var(--color-border);
    }

    .preview-message-user {
        background: var(--color-background-tertiary);
    }

    .preview-message-assistant {
        background: var(--color-background-secondary);
    }

    .preview-message-system {
        background: var(--color-background-tertiary);
        opacity: 0.7;
        font-size: 0.85rem;
    }

    .preview-message-header {
        display: flex;
        align-items: center;
        gap: 0.5rem;
        margin-bottom: 0.5rem;
    }

    .preview-role {
        font-weight: 600;
        font-size: 0.85rem;
        color: var(--color-text-primary);
        text-transform: capitalize;
    }

    .preview-model {
        font-size: 0.75rem;
        color: var(--color-text-tertiary);
        background: var(--color-background-tertiary);
        padding: 0.1rem 0.4rem;
        border-radius: 4px;
    }

    .preview-message-content p {
        margin: 0;
        white-space: pre-wrap;
        word-break: break-word;
        line-height: 1.5;
        color: var(--color-text-primary);
        font-size: 0.9rem;
    }

    .preview-json {
        margin: 0;
        font-size: 0.75rem;
        line-height: 1.4;
        background: var(--color-background-tertiary);
        border-radius: 4px;
        padding: 0.5rem;
        overflow-x: auto;
        max-height: 200px;
        color: var(--color-text-secondary);
    }

    .preview-embeds-section {
        border-top: 1px solid var(--color-border);
        padding: 1rem 1.25rem;
        overflow-y: auto;
        max-height: 300px;
        flex-shrink: 0;
    }

    .preview-embeds-section h4 {
        margin: 0 0 0.75rem 0;
        font-size: 0.95rem;
        color: var(--color-text-primary);
    }

    .preview-embed {
        border: 1px solid var(--color-border);
        border-radius: 6px;
        padding: 0.75rem;
        margin-bottom: 0.5rem;
        background: var(--color-background-secondary);
    }

    .preview-embed.is-child {
        margin-left: 1.5rem;
        border-left: 3px solid var(--color-primary-light);
    }

    .preview-embed-header {
        display: flex;
        align-items: center;
        gap: 0.5rem;
        margin-bottom: 0.5rem;
        flex-wrap: wrap;
    }

    .preview-embed-type {
        font-weight: 600;
        font-size: 0.8rem;
        color: var(--color-primary);
    }

    .preview-embed-id {
        font-size: 0.7rem;
        color: var(--color-text-tertiary);
        font-family: monospace;
    }

    .preview-embed-child-badge,
    .preview-embed-parent-badge {
        font-size: 0.7rem;
        padding: 0.1rem 0.4rem;
        border-radius: 4px;
        font-weight: 500;
    }

    .preview-embed-child-badge {
        background: #FEF3C7;
        color: #92400E;
    }

    .preview-embed-parent-badge {
        background: #DBEAFE;
        color: #1E40AF;
    }

    .preview-embed-content {
        margin: 0;
        font-size: 0.85rem;
        color: var(--color-text-secondary);
        white-space: pre-wrap;
        word-break: break-word;
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
            width: 100%;
        }

        .replacement-selection {
            padding: 0.5rem;
        }

        .replacement-label {
            font-size: 0.8rem;
        }

        .replacement-select {
            font-size: 0.85rem;
        }
        
        .suggestion-actions .btn {
            width: 100%;
        }

        .demo-header {
            flex-direction: column;
            gap: 0.5rem;
        }

        .preview-modal {
            max-height: 90vh;
        }

        .preview-embed.is-child {
            margin-left: 0.75rem;
        }
    }
</style>
