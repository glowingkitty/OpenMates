<!--
    SettingsShared Component
    
    This component displays:
    1. "Shared" section: Lists all chats/embeds owned by the user that are shared (is_private = false)
    2. "Shared with me" section: Lists all chats/embeds owned by others that the user has access to
    
    Users can unshare chats from the "Shared" section, which sets is_private = true on the server.
-->
<script lang="ts">
    import { text } from '@repo/ui';
    import { createEventDispatcher, onMount, onDestroy } from 'svelte';
    import SettingsItem from '../SettingsItem.svelte';
    import { chatDB } from '../../services/db';
    import { userDB } from '../../services/userDB';
    import { authStore } from '../../stores/authStore';
    import { activeChatStore } from '../../stores/activeChatStore';
    import { chatMetadataCache, type DecryptedChatMetadata } from '../../services/chatMetadataCache';
    import { chatSyncService } from '../../services/chatSyncService';
    import { get } from 'svelte/store';
    import type { Chat } from '../../types/chat';

    // Event dispatcher for navigation
    const dispatch = createEventDispatcher();
    
    // State
    let ownedSharedChats = $state<Chat[]>([]);
    let sharedWithMeChats = $state<Chat[]>([]);
    let isLoading = $state(true);
    let chatMetadataMap = $state<Record<string, DecryptedChatMetadata>>({});
    // Get current user ID from userDB (user_id is not in UserProfile interface but is in the DB)
    let currentUserId = $state<string | null>(null);
    
    let isAuthenticated = $derived(get(authStore).isAuthenticated);
    
    /**
     * Load current user ID from userDB
     * This is needed to filter chats by ownership
     */
    async function loadCurrentUserId() {
        if (!isAuthenticated) {
            currentUserId = null;
            return;
        }
        
        try {
            const profile = await userDB.getUserProfile();
            console.debug('[SettingsShared] Retrieved profile from userDB:', profile);
            currentUserId = profile?.user_id || null;
            console.debug('[SettingsShared] Loaded currentUserId:', currentUserId);
        } catch (error) {
            console.error('[SettingsShared] Error loading current user ID:', error);
            currentUserId = null;
        }
    }
    
    /**
     * Load all chats and filter by ownership and shared status
     * Note: Currently, we filter by user_id. In the future, we'll also check is_private from server.
     */
    async function loadSharedChats() {
        if (!isAuthenticated || !currentUserId) {
            isLoading = false;
            return;
        }
        
        try {
            isLoading = true;
            console.debug('[SettingsShared] Loading shared chats for user:', currentUserId);
            
            // Get all chats from IndexedDB
            const allChats = await chatDB.getAllChats();
            console.debug('[SettingsShared] Loaded', allChats.length, 'chats from IndexedDB');
            
            // Filter chats owned by current user that are shared
            // A chat is "shared" if: is_shared === true AND is_private is NOT true
            // This ensures we only show chats that are actively shared (not unshared)
            ownedSharedChats = allChats.filter(chat => 
                chat.user_id === currentUserId && 
                chat.is_shared === true && 
                chat.is_private !== true
            );
            
            // Filter chats owned by others (shared with me)
            // These are chats where the user is not the owner
            // These are chats that the user has opened from share links
            sharedWithMeChats = allChats.filter(chat => 
                chat.user_id && chat.user_id !== currentUserId &&
                chat.is_shared === true
            );
            
            console.debug('[SettingsShared] Found', ownedSharedChats.length, 'owned shared chats');
            console.debug('[SettingsShared] Found', sharedWithMeChats.length, 'shared with me chats');
            
            // Load metadata for all shared chats
            const allSharedChats = [...ownedSharedChats, ...sharedWithMeChats];
            const metadataPromises = allSharedChats.map(async (chat) => {
                try {
                    const metadata = await chatMetadataCache.getDecryptedMetadata(chat);
                    if (metadata) {
                        return { chatId: chat.chat_id, metadata };
                    }
                } catch (error) {
                    console.error(`[SettingsShared] Error loading metadata for chat ${chat.chat_id}:`, error);
                }
                return null;
            });
            
            const metadataResults = await Promise.all(metadataPromises);
            const newMetadataMap: Record<string, DecryptedChatMetadata> = {};
            metadataResults.forEach(result => {
                if (result) {
                    newMetadataMap[result.chatId] = result.metadata;
                }
            });
            chatMetadataMap = newMetadataMap;
            console.debug('[SettingsShared] Loaded metadata for', Object.keys(chatMetadataMap).length, 'chats');
        } catch (error) {
            console.error('[SettingsShared] Error loading shared chats:', error);
        } finally {
            isLoading = false;
        }
    }
    
    /**
     * Unshare a chat by setting is_private = true and is_shared = false
     * Updates both IndexedDB and server
     * @param chatId The ID of the chat to unshare
     */
    async function unshareChat(chatId: string) {
        if (!isAuthenticated) {
            console.warn('[SettingsShared] Cannot unshare chat: user not authenticated');
            return;
        }
        
        try {
            console.debug('[SettingsShared] Unsharing chat:', chatId);
            
            // Update IndexedDB: set is_private = true and is_shared = false
            const chat = await chatDB.getChat(chatId);
            if (chat) {
                // Update chat with new sharing status
                await chatDB.updateChat({
                    ...chat,
                    is_private: true,
                    is_shared: false
                });
                console.debug('[SettingsShared] Updated chat in IndexedDB:', chatId);
            }
            
            // Send request to server to set is_private = true and is_shared = false
            const { getApiEndpoint } = await import('../../config/api');
            const response = await fetch(getApiEndpoint('/v1/share/chat/unshare'), {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'Accept': 'application/json',
                    'Origin': window.location.origin
                },
                body: JSON.stringify({
                    chat_id: chatId
                }),
                credentials: 'include'
            });
            
            if (!response.ok) {
                const errorData = await response.json().catch(() => ({ detail: 'Unknown error' }));
                console.error('[SettingsShared] Failed to unshare chat on server:', errorData);
                // Still remove from list locally even if server request fails
            } else {
                const data = await response.json();
                if (data.success) {
                    console.debug('[SettingsShared] Successfully unshared chat on server:', chatId);
                }
            }
            
            // Invalidate metadata cache for this chat
            chatMetadataCache.invalidateChat(chatId);
            
            // Remove from owned shared chats list
            ownedSharedChats = ownedSharedChats.filter(chat => chat.chat_id !== chatId);
            
            // Remove from metadata map
            delete chatMetadataMap[chatId];
            chatMetadataMap = { ...chatMetadataMap }; // Trigger reactivity
            
            // Dispatch event to notify other components
            window.dispatchEvent(new CustomEvent('chatUnshared', { detail: { chat_id: chatId } }));
            
            console.debug('[SettingsShared] Chat unshared:', chatId);
        } catch (error) {
            console.error('[SettingsShared] Error unsharing chat:', error);
        }
    }
    
    /**
     * Navigate to share submenu for a specific chat
     * @param chatId The ID of the chat to share
     */
    function navigateToShare(chatId: string) {
        // Set the active chat in the store first
        // This ensures SettingsShare component can access the chat ID
        activeChatStore.setActiveChat(chatId);
        
        // Then navigate to the share submenu
        dispatch('openSettings', {
            settingsPath: 'shared/share',
            direction: 'forward',
            icon: 'share',
            title: $text('settings.share.share_chat.text')
        });
    }
    
    /**
     * Handle chatShared event - reload shared chats when a chat is shared
     */
    async function handleChatShared(event: Event) {
        const customEvent = event as CustomEvent;
        console.debug('[SettingsShared] Chat shared event received:', customEvent.detail);
        // Reload shared chats to include the newly shared chat
        await loadSharedChats();
    }
    
    /**
     * Handle chatUpdated/metadata_updated events to refresh metadata
     */
    async function handleChatUpdated(event: Event) {
        const customEvent = event as CustomEvent;
        const detail = customEvent.detail;
        
        if (detail && detail.chat_id) {
            const chat = [...ownedSharedChats, ...sharedWithMeChats].find(c => c.chat_id === detail.chat_id);
            if (chat) {
                console.debug('[SettingsShared] Chat updated, refreshing metadata:', detail.chat_id);
                // Invalidate cache first
                chatMetadataCache.invalidateChat(detail.chat_id);
                // Re-fetch chat from DB to get latest state
                const freshChat = await chatDB.getChat(detail.chat_id);
                if (freshChat) {
                    const metadata = await chatMetadataCache.getDecryptedMetadata(freshChat);
                    if (metadata) {
                        chatMetadataMap[detail.chat_id] = metadata;
                        // Trigger reactivity
                        chatMetadataMap = { ...chatMetadataMap };
                    }
                }
            }
        }
    }
    
    // Load current user ID and chats on mount
    onMount(async () => {
        await loadCurrentUserId();
        await loadSharedChats();
        
        // Listen for chatShared events to reload the list
        window.addEventListener('chatShared', handleChatShared);
        // Listen for chat updates
        chatSyncService.addEventListener('chatUpdated', handleChatUpdated);
    });
    
    // Clean up event listener on destroy
    onDestroy(() => {
        window.removeEventListener('chatShared', handleChatShared);
        chatSyncService.removeEventListener('chatUpdated', handleChatUpdated);
    });
    
    // Reload when authentication status changes
    $effect(() => {
        if (isAuthenticated) {
            loadCurrentUserId().then(() => {
                if (currentUserId) {
                    loadSharedChats();
                }
            });
        } else {
            currentUserId = null;
            ownedSharedChats = [];
            sharedWithMeChats = [];
        }
    });
</script>

<div class="settings-shared-container">
    {#if !isAuthenticated}
        <div class="not-authenticated-message">
            <p>{$text('settings.share.not_authenticated.text')}</p>
        </div>
    {:else if isLoading}
        <div class="loading-message">
            <p>{$text('settings.share.loading.text')}</p>
        </div>
    {:else}
        <!-- Shared Section: Chats owned by user -->
        <div class="shared-section">
            <SettingsItem
                type="heading"
                icon="share"
                title={$text('settings.share.shared_section.text')}
            />
            
            {#if ownedSharedChats.length === 0}
                <div class="empty-state">
                    <p>{$text('settings.share.no_shared_chats.text')}</p>
                </div>
            {:else}
                <div class="chat-list">
                    {#each ownedSharedChats as chat}
                        {@const metadata = chatMetadataMap[chat.chat_id]}
                        <div class="chat-item">
                            <SettingsItem
                                type="submenu"
                                icon="chat"
                                iconType={metadata?.category ? 'category' : 'default'}
                                category={metadata?.category}
                                categoryIcon={metadata?.icon}
                                title={metadata?.title || chat.title || $text('settings.share.untitled_chat.text')}
                                onClick={() => navigateToShare(chat.chat_id)}
                            />
                            <button
                                class="unshare-button"
                                onclick={() => unshareChat(chat.chat_id)}
                                title={$text('settings.share.unshare.text')}
                                aria-label={$text('settings.share.unshare.text')}
                            >
                                <div class="icon settings_size icon_close"></div>
                            </button>
                        </div>
                    {/each}
                </div>
            {/if}
        </div>
        
        <!-- Shared with me Section: Chats owned by others -->
        <div class="shared-with-me-section">
            <SettingsItem
                type="heading"
                icon="user"
                title={$text('settings.share.shared_with_me_section.text')}
            />
            
            {#if sharedWithMeChats.length === 0}
                <div class="empty-state">
                    <p>{$text('settings.share.no_shared_with_me_chats.text')}</p>
                </div>
            {:else}
                <div class="chat-list">
                    {#each sharedWithMeChats as chat}
                        {@const metadata = chatMetadataMap[chat.chat_id]}
                        <SettingsItem
                            type="submenu"
                            icon="chat"
                            iconType={metadata?.category ? 'category' : 'default'}
                            category={metadata?.category}
                            categoryIcon={metadata?.icon}
                            title={metadata?.title || chat.title || $text('settings.shared.untitled_chat.text')}
                            onClick={() => {
                                // Navigate to the chat
                                activeChatStore.setActiveChat(chat.chat_id);
                            }}
                        />
                    {/each}
                </div>
            {/if}
        </div>
    {/if}
</div>

<style>
    .settings-shared-container {
        padding: 0 10px;
        display: flex;
        flex-direction: column;
        gap: 24px;
    }
    
    .not-authenticated-message,
    .loading-message,
    .empty-state {
        padding: 20px;
        text-align: center;
        color: var(--color-grey-60);
        font-size: 14px;
    }
    
    .shared-section,
    .shared-with-me-section {
        display: flex;
        flex-direction: column;
        gap: 12px;
    }
    
    .chat-list {
        display: flex;
        flex-direction: column;
        gap: 8px;
    }
    
    .chat-item {
        display: flex;
        align-items: center;
        gap: 8px;
    }
    
    .unshare-button {
        background: none;
        border: none;
        cursor: pointer;
        padding: 8px;
        display: flex;
        align-items: center;
        justify-content: center;
        opacity: 0.6;
        transition: opacity 0.2s ease;
    }
    
    .unshare-button:hover {
        opacity: 1;
    }
    
    .unshare-button:active {
        opacity: 0.8;
    }
</style>
