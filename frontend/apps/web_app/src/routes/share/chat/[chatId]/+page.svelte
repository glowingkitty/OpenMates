<!--
    Share Chat Page
    
    This page handles shared chat links in the format:
    /share/chat/{chatId}#key={encrypted_blob}
    
    The chat ID is in the URL path (visible to server for OG tags).
    The encryption key is in the URL fragment (never sent to server).
    
    Flow:
    1. Extract chat ID from URL params
    2. Extract encryption key from URL fragment (#key=...)
    3. Decrypt the key blob to get the chat encryption key
    4. Request chat data from server (or load from local storage if available)
    5. Decrypt and display the chat
-->
<script lang="ts">
    import { onMount } from 'svelte';
    import { page } from '$app/stores';
    import { browser } from '$app/environment';
    import {
        chatDB,
        activeChatStore,
        decryptShareKeyBlob,
        type Chat,
        type Message
    } from '@repo/ui';
    import { goto } from '$app/navigation';
    import { getApiEndpoint } from '@repo/ui';
    import { deriveParentByChildEmbeds } from '../shareChatEmbedUtils';

    // Get chat ID from URL params
    let chatId = $derived($page.params.chatId);
    
    // State
    let isLoading = $state(true);
    let error = $state<string | null>(null);
    let requiresPassword = $state(false);
    let passwordInput = $state('');
    let passwordError = $state<string | null>(null);
    
    /**
     * Extract the encryption key from the URL fragment
     * Format: #key={encrypted_blob}
     */
    function extractKeyFromFragment(): string | null {
        if (!browser) return null;
        
        const hash = window.location.hash;
        if (hash.startsWith('#key=')) {
            return hash.substring(5); // Remove '#key=' prefix
        }
        return null;
    }
    
    /**
     * Get server time for expiration validation
     * Falls back to client time if server is unreachable
     */
    async function getServerTime(): Promise<number> {
        try {
            const response = await fetch(getApiEndpoint('/v1/share/time'));
            if (response.ok) {
                const data = await response.json();
                return data.timestamp || data.server_time || Math.floor(Date.now() / 1000);
            }
            throw new Error('Server time request failed');
        } catch (error) {
            console.warn('[ShareChat] Failed to get server time, using client time:', error);
            return Math.floor(Date.now() / 1000);
        }
    }
    
    /**
     * Fetch chat data from server
     * Returns chat, messages, embeds, and embed_keys for the wrapped key architecture
     */
    async function fetchChatFromServer(chatId: string): Promise<{ chat: Chat | null; messages: Message[]; embeds: any[]; embed_keys: any[] }> {
        try {
            const response = await fetch(getApiEndpoint(`/v1/share/chat/${chatId}`));
            if (!response.ok) {
                throw new Error(`Server returned ${response.status}`);
            }
            
            const data = await response.json();
            
            // Check if this is dummy data (non-existent chat)
            // The backend returns dummy data for non-existent chats to prevent enumeration
            // We can't distinguish real from dummy data, but if decryption fails later, we'll know
            console.debug('[ShareChat] Received chat data from server:', {
                chat_id: data.chat_id,
                has_title: !!data.encrypted_title,
                message_count: data.messages?.length || 0,
                embed_count: data.embeds?.length || 0,
                embed_keys_count: data.embed_keys?.length || 0
            });
            
            // Parse messages first (backend returns JSON strings when decrypt_content=False)
            const rawMessages = data.messages || [];
            const parsedMessages = rawMessages.map((msg: any) => {
                if (typeof msg === 'string') {
                    try {
                        return JSON.parse(msg);
                    } catch (e) {
                        console.warn('[ShareChat] Failed to parse message JSON:', e);
                        return null;
                    }
                }
                return msg;
            }).filter((msg: any) => msg !== null);
            
            // Calculate last_edited_overall_timestamp from parsed messages
            const messageTimestamps = parsedMessages
                .map((m: any) => m.created_at || 0)
                .filter((ts: number) => ts > 0);
            const lastMessageTimestamp = messageTimestamps.length > 0
                ? Math.max(...messageTimestamps)
                : Math.floor(Date.now() / 1000);
            
            // Convert parsed messages to Message format
            const messages: Message[] = parsedMessages.map((messageObj: any) => {
                // Backend uses 'id' as the Directus primary key, but 'client_message_id' is the actual message_id
                // For shared chats, we use 'id' as message_id since that's what we get from the server
                return {
                    message_id: messageObj.id || messageObj.message_id || messageObj.client_message_id,
                    chat_id: data.chat_id,
                    role: messageObj.role || 'user',
                    created_at: messageObj.created_at || Math.floor(Date.now() / 1000),
                    status: 'synced' as const,
                    encrypted_content: messageObj.encrypted_content || '',
                    encrypted_sender_name: messageObj.encrypted_sender_name,
                    encrypted_category: messageObj.encrypted_category,
                    encrypted_model_name: messageObj.encrypted_model_name, // Model name for assistant messages
                    user_message_id: messageObj.user_message_id,
                    client_message_id: messageObj.client_message_id
                };
            });
            
            // Get current user ID to check ownership
            // For authenticated users, we need to determine if they own this chat
            // If they don't own it, set user_id to a placeholder to mark it as read-only
            let chatUserId: string | undefined = undefined;
            const { authStore } = await import('@repo/ui');
            const { get } = await import('svelte/store');
            const { userDB } = await import('@repo/ui');
            const isAuthenticated = get(authStore).isAuthenticated;
            
            if (isAuthenticated) {
                try {
                    // Try to get current user ID
                    const profile = await userDB.getUserProfile();
                    const currentUserId = (profile as any)?.user_id;
                    
                    // For now, we'll check ownership on the backend when sending messages
                    // Here we set user_id to a placeholder if we can't verify ownership
                    // The actual ownership check happens in ActiveChat component
                    // If the chat doesn't have user_id set, it means it's a shared chat from another user
                    // We'll leave it undefined for now and let the ownership check in ActiveChat handle it
                    // TODO: In the future, we could fetch chat metadata from backend to get owner info
                } catch (error) {
                    console.warn('[ShareChat] Could not determine user ownership:', error);
                }
            }
            
            // Convert server response to Chat object
            // Note: user_id is intentionally not set here - it will be determined by ownership check
            // If the chat is owned by another user, the ownership check will detect it
            const chat: Chat = {
                chat_id: data.chat_id,
                encrypted_title: data.encrypted_title || null,
                messages_v: messages.length, // Set based on actual message count
                title_v: 0,
                last_edited_overall_timestamp: lastMessageTimestamp,
                unread_count: 0,
                created_at: Math.floor(Date.now() / 1000), // Use current time as fallback
                updated_at: Math.floor(Date.now() / 1000),
                encrypted_chat_summary: data.encrypted_chat_summary || null,
                encrypted_follow_up_request_suggestions: data.encrypted_follow_up_request_suggestions || null,
                encrypted_icon: data.encrypted_icon || null,  // Icon name encrypted with chat key
                encrypted_category: data.encrypted_category || null,  // Category name encrypted with chat key
                // user_id is intentionally not set - will be determined by ownership check in ActiveChat
                // If chat is from another user, ownership check will fail and chat will be read-only
            };
            
            return { 
                chat, 
                messages, 
                embeds: data.embeds || [],
                embed_keys: data.embed_keys || []
            };
        } catch (error) {
            console.error('[ShareChat] Error fetching chat from server:', error);
            return { chat: null, messages: [], embeds: [], embed_keys: [] };
        }
    }
    
    /**
     * Load and decrypt the shared chat
     */
    async function loadSharedChat(password?: string) {
        if (!chatId) {
            error = 'Invalid chat link: missing chat ID';
            isLoading = false;
            return;
        }
        
        try {
            isLoading = true;
            error = null;
            passwordError = null;
            
            // Extract encryption key from URL fragment
            const encryptedBlob = extractKeyFromFragment();
            if (!encryptedBlob) {
                error = 'Invalid share link: missing encryption key';
                isLoading = false;
                return;
            }
            
            // Get server time for expiration validation
            const serverTime = await getServerTime();
            
            // Decrypt the key blob
            const result = await decryptShareKeyBlob(chatId, encryptedBlob, serverTime, password);
            
            if (!result.success) {
                if (result.error === 'password_required') {
                    requiresPassword = true;
                    isLoading = false;
                    return;
                } else if (result.error === 'invalid_password') {
                    passwordError = 'Incorrect password. Please try again.';
                    isLoading = false;
                    return;
                } else if (result.error === 'expired') {
                    error = 'This chat link has expired.';
                    isLoading = false;
                    return;
                } else {
                    error = 'Failed to decrypt share link. The link may be invalid.';
                    isLoading = false;
                    return;
                }
            }
            
            if (!result.chatEncryptionKey) {
                error = 'Failed to extract chat encryption key.';
                isLoading = false;
                return;
            }
            
            // Fetch chat data from server
            // The server returns encrypted chat data for existing chats
            // or dummy encrypted data for non-existent chats (to prevent enumeration)
            console.debug('[ShareChat] Fetching chat data from server...');
            const { chat: fetchedChat, messages: fetchedMessages, embeds: fetchedEmbeds, embed_keys: fetchedEmbedKeys } = await fetchChatFromServer(chatId);
            
            if (!fetchedChat) {
                error = 'Chat not found. The chat may have been deleted or the link is invalid.';
                isLoading = false;
                return;
            }
            
            // Convert the chat encryption key from base64 string to Uint8Array
            // The key is stored as base64 in the blob, but chatDB expects Uint8Array
            const keyBytes = Uint8Array.from(atob(result.chatEncryptionKey), c => c.charCodeAt(0));
            
            // Set the chat encryption key in the database cache BEFORE storing chat
            // This allows the chat to be decrypted when stored
            chatDB.setChatKey(chatId, keyBytes);
            
            // CRITICAL: Persist the shared chat key to IndexedDB so it survives page reloads
            // This is essential for unauthenticated users who can't derive keys from a master key.
            // Without this, the key would be lost on reload since it's only in memory.
            const { saveSharedChatKey } = await import('@repo/ui');
            await saveSharedChatKey(chatId, keyBytes);
            console.debug('[ShareChat] Persisted shared chat key to IndexedDB for chat:', chatId);
            
            // Store chat and messages in IndexedDB
            console.debug('[ShareChat] Storing chat and messages in IndexedDB...');
            await chatDB.init();
            
            // Store chat metadata first (addChat creates its own transaction)
            await chatDB.addChat(fetchedChat);
            
            // Store messages if any (batchSaveMessages creates its own transaction)
            if (fetchedMessages.length > 0) {
                await chatDB.batchSaveMessages(fetchedMessages);
                console.debug(`[ShareChat] Stored ${fetchedMessages.length} messages`);
            }
            
            // Process embed_keys first - unwrap them with chat key and store
            // This is the wrapped key architecture: embed_keys contain AES(embed_key, chat_key)
            // We unwrap to get embed_key, which is used to decrypt embed content
            const { embedStore, unwrapEmbedKeyWithChatKey } = await import('@repo/ui');
            const { computeSHA256 } = await import('@repo/ui');
            
            // Compute hashed_chat_id for matching embed_keys
            const hashedChatId = await computeSHA256(chatId);
            
            if (fetchedEmbedKeys && fetchedEmbedKeys.length > 0) {
                // Store embed keys and unwrap them with chat key
                for (const keyEntry of fetchedEmbedKeys) {
                    try {
                        // Only process key entries for this chat (key_type='chat' with matching hashed_chat_id)
                        if (keyEntry.key_type === 'chat' && keyEntry.hashed_chat_id === hashedChatId) {
                            // Unwrap the embed key using the chat key
                            const embedKey = await unwrapEmbedKeyWithChatKey(keyEntry.encrypted_embed_key, keyBytes);
                            if (embedKey) {
                                // Find matching embed by computing hashed_embed_id from embed_id
                                // We need to match keyEntry.hashed_embed_id with computed hash of each embed's embed_id
                                for (const embed of fetchedEmbeds) {
                                    if (embed.embed_id) {
                                        const embedIdHash = await computeSHA256(embed.embed_id);
                                        if (embedIdHash === keyEntry.hashed_embed_id) {
                                            // Store the unwrapped embed key in cache for decryption
                                            embedStore.setEmbedKeyInCache(embed.embed_id, embedKey, hashedChatId);
                                            console.debug('[ShareChat] Unwrapped and cached embed key for:', embed.embed_id);
                                            break;
                                        }
                                    }
                                }
                            }
                        }
                    } catch (keyError) {
                        console.warn('[ShareChat] Error processing embed key:', keyError);
                    }
                }
                
                // Also store the raw embed_keys entries in IndexedDB for future use
                await embedStore.storeEmbedKeys(fetchedEmbedKeys);
                console.debug(`[ShareChat] Stored ${fetchedEmbedKeys.length} embed keys`);
            }
            
            // Store embeds if any
            if (fetchedEmbeds && fetchedEmbeds.length > 0) {
                // Ensure child embeds can resolve the parent key in shared-chat (non-auth) flows.
                // The EmbedStore can reuse a parent's embed key for a child embed if `parent_embed_id` is stored.
                // Some payloads include `parent_embed_id` directly; otherwise we can derive it from parent `embed_ids`.
                const derivedParentByChild = deriveParentByChildEmbeds(fetchedEmbeds);

                for (const embed of fetchedEmbeds) {
                    try {
                        const contentRef = `embed:${embed.embed_id}`;
                        // Store the embed with its already-encrypted content (no re-encryption)
                        // The embed_key is already in cache, so decryption will work
                        await embedStore.putEncrypted(contentRef, {
                            encrypted_content: embed.encrypted_content,
                            encrypted_type: embed.encrypted_type,
                            embed_id: embed.embed_id,
                            status: embed.status || 'finished',
                            hashed_chat_id: embed.hashed_chat_id,
                            hashed_user_id: embed.hashed_user_id,
                            embed_ids: Array.isArray(embed.embed_ids) ? embed.embed_ids : undefined,
                            parent_embed_id: embed.parent_embed_id || derivedParentByChild.get(embed.embed_id)
                        }, (embed.encrypted_type ? 'app-skill-use' : embed.embed_type || 'app-skill-use') as any);
                    } catch (embedError) {
                        console.warn(`[ShareChat] Error storing embed ${embed.embed_id}:`, embedError);
                    }
                }
                console.debug(`[ShareChat] Stored ${fetchedEmbeds.length} embeds`);
            }
            
            // NOTE: Shared chat keys are now persisted in IndexedDB via sharedChatKeyStorage
            // This allows unauthenticated users to reload the tab and still access the chat.
            // The sessionStorage tracking has been removed since keys persist until explicitly deleted.
            // For authenticated users, the chat will sync normally via the regular chat sync mechanism.
            
            console.debug('[ShareChat] Successfully stored chat in IndexedDB');
            
            // Set active chat in store
            activeChatStore.setActiveChat(chatId);
            
            // Navigate to main app with the chat loaded
            // This allows the user to see the chat in the normal interface
            // The chat key is already set in the cache, so the chat will be decrypted when loaded
            await goto(`/#chat_id=${chatId}`);
            
            isLoading = false;
        } catch (err) {
            console.error('[ShareChat] Error loading shared chat:', err);
            error = 'An error occurred while loading the shared chat.';
            isLoading = false;
        }
    }
    
    /**
     * Handle password submission
     */
    async function handlePasswordSubmit() {
        if (!passwordInput || passwordInput.length === 0) {
            passwordError = 'Password is required';
            return;
        }
        
        await loadSharedChat(passwordInput);
    }
    
    // Load chat on mount
    onMount(() => {
        if (chatId) {
            loadSharedChat();
        } else {
            error = 'Invalid share link: missing chat ID';
            isLoading = false;
        }
    });
</script>

<div class="share-chat-page">
    {#if isLoading}
        <div class="loading-container">
            <div class="loading-spinner"></div>
            <p>Loading shared chat...</p>
        </div>
    {:else if error}
        <div class="error-container">
            <div class="error-icon">⚠️</div>
            <h1>Unable to Load Chat</h1>
            <p>{error}</p>
            <button onclick={() => goto('/')}>Go to Home</button>
        </div>
    {:else if requiresPassword}
        <div class="password-container">
            <div class="password-icon">🔒</div>
            <h1>Password Required</h1>
            <p>This shared chat is protected with a password.</p>
            <form onsubmit={(e) => { e.preventDefault(); handlePasswordSubmit(); }}>
                <input
                    type="password"
                    bind:value={passwordInput}
                    placeholder="Enter password"
                    maxlength="10"
                    class:error={!!passwordError}
                />
                {#if passwordError}
                    <p class="password-error">{passwordError}</p>
                {/if}
                <button type="submit">Access Chat</button>
            </form>
        </div>
    {/if}
</div>

<style>
    .share-chat-page {
        min-height: 100vh;
        display: flex;
        flex-direction: column;
        align-items: center;
        justify-content: center;
        padding: 20px;
        background-color: var(--color-grey-5, #f5f5f5);
    }
    
    .loading-container,
    .error-container,
    .password-container {
        max-width: 500px;
        width: 100%;
        text-align: center;
        padding: 40px;
        background: white;
        border-radius: 12px;
        box-shadow: 0 2px 8px rgba(0, 0, 0, 0.1);
    }
    
    .loading-spinner {
        width: 48px;
        height: 48px;
        border: 4px solid var(--color-grey-20, #e0e0e0);
        border-top-color: var(--color-primary, #6b46c1);
        border-radius: 50%;
        animation: spin 1s linear infinite;
        margin: 0 auto 20px;
    }
    
    @keyframes spin {
        to { transform: rotate(360deg); }
    }
    
    .error-icon,
    .password-icon {
        font-size: 64px;
        margin-bottom: 20px;
    }
    
    h1 {
        font-size: 24px;
        margin: 0 0 12px;
        color: var(--color-grey-100, #1a1a1a);
    }
    
    p {
        font-size: 16px;
        color: var(--color-grey-70, #666);
        margin: 0 0 24px;
    }
    
    button {
        padding: 12px 24px;
        background-color: var(--color-primary, #6b46c1);
        color: white;
        border: none;
        border-radius: 8px;
        font-size: 16px;
        font-weight: 500;
        cursor: pointer;
        transition: background-color 0.2s ease;
    }
    
    button:hover {
        background-color: var(--color-primary-dark, #5a36b2);
    }
    
    form {
        display: flex;
        flex-direction: column;
        gap: 12px;
        margin-top: 24px;
    }
    
    input[type="password"] {
        padding: 12px;
        border: 2px solid var(--color-grey-30, #d0d0d0);
        border-radius: 8px;
        font-size: 16px;
    }
    
    input[type="password"].error {
        border-color: var(--color-error, #dc2626);
    }
    
    .password-error {
        color: var(--color-error, #dc2626);
        font-size: 14px;
        margin: -8px 0 0;
    }
</style>
