<!--
    Settings Community Suggestions Component

    Shows pending community chat suggestions for admin approval.
    Allows admins to approve chats to become demo chats with a limit of 5.
-->
<script lang="ts">
    import { createEventDispatcher, onMount, onDestroy } from 'svelte';
    import { getApiEndpoint } from '@repo/ui';
    import Chat from '../../chats/Chat.svelte';
    import type { Chat as ChatType } from '../../../types/chat';
    import { decryptShareKeyBlob } from '../../../services/shareEncryption';
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
    let selectedReplacementChatId = $state<string>('');

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

    /**
     * Helper to get the actual chat encryption key from a suggestion
     * Handles both raw base64 keys and encrypted share blobs
     */
    async function getDecryptedChatKey(suggestion: Suggestion): Promise<string | null> {
        let keyOrBlob = suggestion.encryption_key;
        
        // Try to get key from local storage if not in suggestion
        if (!keyOrBlob) {
            const { getSharedChatKey } = await import('../../../services/sharedChatKeyStorage');
            const storedKey = await getSharedChatKey(suggestion.chat_id);
            if (storedKey) {
                // Convert Uint8Array to base64
                keyOrBlob = window.btoa(String.fromCharCode(...storedKey));
            }
        }

        if (!keyOrBlob && suggestion.share_link) {
            // Extract key from share link if not provided directly
            const shareLink = suggestion.share_link;
            if (shareLink && shareLink.includes('#key=')) {
                keyOrBlob = shareLink.split('#key=')[1];
            }
        }

        if (!keyOrBlob) return null;

        // If the key is short, it's likely already a raw base64 key
        if (keyOrBlob.length < 100) {
            return keyOrBlob;
        }

        // Otherwise, it's an encrypted share blob - decrypt it
        try {
            const serverTime = Math.floor(Date.now() / 1000);
            const result = await decryptShareKeyBlob(suggestion.chat_id, keyOrBlob, serverTime);
            
            if (result.success && result.chatEncryptionKey) {
                console.debug('[SettingsCommunitySuggestions] Decrypted share key blob successfully');
                return result.chatEncryptionKey;
            } else {
                console.warn('[SettingsCommunitySuggestions] Failed to decrypt share key blob:', result.error);
                return null;
            }
        } catch (e) {
            console.error('[SettingsCommunitySuggestions] Error decrypting share key blob:', e);
            return null;
        }
    }

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
                    replace_demo_chat_id: selectedReplacementChatId || null  // ID of demo chat to replace (null for auto-replacement)
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
                created_at: new Date().toISOString()
            }];

            // Remove from suggestions list
            suggestions = suggestions.filter(s => s.demo_chat_id !== suggestion.demo_chat_id);

            // Clear replacement selection
            selectedReplacementChatId = '';

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
     * Preview a shared chat in the main app view
     * 
     * The encryption key is provided by the server (decrypted from shared_encrypted_chat_key).
     * Stores the key in IndexedDB, closes settings panel, and navigates to the chat in the current tab.
     */
    async function openSharedChat(suggestion: Suggestion) {
        // Get the actual chat encryption key (decrypting if necessary)
        const encryptionKey = await getDecryptedChatKey(suggestion);

        // If no key is available, show error
        if (!encryptionKey) {
            dispatch('showToast', {
                type: 'error',
                message: 'Encryption key not available. This chat may have been shared before this feature was added.'
            });
            return;
        }

        // Store the key in sharedChatKeyStorage so it's available for decryption
        try {
            const { saveSharedChatKey } = await import('../../../services/sharedChatKeyStorage');
            // Convert base64 to Uint8Array
            const keyBytes = Uint8Array.from(atob(encryptionKey), c => c.charCodeAt(0));
            await saveSharedChatKey(suggestion.chat_id, keyBytes);
        } catch (e) {
            console.warn('Failed to save shared chat key to IndexedDB:', e);
        }

        // Close settings and navigate to the chat in the current tab
        // Use the hash format that the app expects for deep links
        window.location.hash = `chat_id=${suggestion.chat_id}`;
        
        // Dispatch event to ensure chat loads immediately
        const event = new CustomEvent('globalChatSelected', {
            detail: { 
                chat: { chat_id: suggestion.chat_id },
                is_shared: true
            },
            bubbles: true,
            composed: true
        });
        window.dispatchEvent(event);
        
        // Close the settings panel
        dispatch('close');
    }

    /**
     * Open the chat in the main view when coming from email link
     */
    function openChatFromEmail() {
        if (pendingSuggestion) {
            openSharedChat(pendingSuggestion);
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
        console.log('[SettingsCommunitySuggestions] Received demo_chat_updated event:', payload);
        
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
                console.log('[SettingsCommunitySuggestions] Demo chat published, reloading data...');
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
        console.log('[SettingsCommunitySuggestions] Received demo_chat_progress event:', payload);

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
                    onclick={() => openSharedChat(pendingSuggestion!)}
                    title="Click to open chat in new window"
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
                    {#if currentDemoChats.length >= 5}
                        <div class="replacement-selection">
                            <label for="replacement-select-email" class="replacement-label">Replace existing demo chat:</label>
                            <select
                                id="replacement-select-email"
                                bind:value={selectedReplacementChatId}
                                class="replacement-select"
                            >
                                <option value="">Select chat to replace...</option>
                                {#each currentDemoChats as demo}
                                    <option value={demo.id}>{demo.title || 'Demo Chat'}</option>
                                {/each}
                            </select>
                        </div>
                    {/if}
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
                        disabled={isSubmitting || (currentDemoChats.length >= 5 && !selectedReplacementChatId)}
                    >
                        {#if currentDemoChats.length >= 5}
                            {#if selectedReplacementChatId}
                                Approve & Replace
                            {:else}
                                Select Chat to Replace
                            {/if}
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
                        <!-- svelte-ignore a11y_click_events_have_key_events -->
                        <!-- svelte-ignore a11y_no_static_element_interactions -->
                        <div 
                            class="suggestion-chat-preview clickable"
                            onclick={() => openSharedChat(suggestion)}
                            title="Click to open chat in new window"
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
                            {#if currentDemoChats.length >= 5}
                                <div class="replacement-selection">
                                    <label for="replacement-select-{suggestion.chat_id}" class="replacement-label">Replace existing demo chat:</label>
                                    <select
                                        id="replacement-select-{suggestion.chat_id}"
                                        bind:value={selectedReplacementChatId}
                                        class="replacement-select"
                                    >
                                        <option value="">Select chat to replace...</option>
                                        {#each currentDemoChats as demo}
                                            <option value={demo.id}>{demo.title || 'Demo Chat'}</option>
                                        {/each}
                                    </select>
                                </div>
                            {/if}
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
                                disabled={isSubmitting || (currentDemoChats.length >= 5 && !selectedReplacementChatId)}
                            >
                                {#if currentDemoChats.length >= 5}
                                    {#if selectedReplacementChatId}
                                        Approve & Replace
                                    {:else}
                                        Select Chat to Replace
                                    {/if}
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
                <li>Click a chat preview to view the conversation in a new window</li>
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
    }
</style>
