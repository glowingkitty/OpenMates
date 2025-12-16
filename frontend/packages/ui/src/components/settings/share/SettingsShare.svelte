<!--
    SettingsShare Component
    
    This component provides the UI for sharing a chat publicly with options for:
    - Password protection (optional)
    - Time limit/expiration (optional)
    - Copy link button
    - QR code display
    
    The sharing is done entirely offline - no server request is needed to create
    a shareable link. The encryption key and expiration info are embedded in the URL.
-->
<script lang="ts">
    import { text } from '@repo/ui';
    import { createEventDispatcher, onMount } from 'svelte';
    import SettingsItem from '../../SettingsItem.svelte';
    import Toggle from '../../Toggle.svelte';
    import { fade, slide } from 'svelte/transition';
    import { cubicOut } from 'svelte/easing';
    import QRCodeSVG from 'qrcode-svg';
    import { activeChatStore } from '../../../stores/activeChatStore';
    import { authStore } from '../../../stores/authStore';
    import { generateShareKeyBlob, type ShareDuration } from '../../../services/shareEncryption';
    import { shareMetadataQueue } from '../../../services/shareMetadataQueue';
    import { isDemoChat, isPublicChat } from '../../../demo_chats/convertToChat';
    import { userDB } from '../../../services/userDB';
    
    // Event dispatcher for navigation and settings events
    const dispatch = createEventDispatcher();
    
    // Props - the chat ID of the currently active chat
    let { 
        activeSettingsView = 'share'
    }: {
        activeSettingsView?: string;
    } = $props();
    
    // ===============================
    // State Variables
    // ===============================
    
    // Password protection state
    let isPasswordProtected = $state(false);
    let password = $state('');
    
    // Time limit state - duration in seconds (0 = no expiration)
    let selectedDuration: ShareDuration = $state(0);
    
    // Generated share link state
    let generatedLink = $state('');
    let isLinkGenerated = $state(false);
    let isCopied = $state(false);
    
    // QR code SVG content
    let qrCodeSvg = $state('');
    
    // Get the current chat ID from the active chat store
    // The store directly contains the chat ID string (or null), not an object
    // Use $state to track the chat ID and update it reactively from the store
    let currentChatId = $state<string | null>(null);
    
    // Update currentChatId when activeChatStore changes
    $effect(() => {
        const storeValue = $activeChatStore;
        if (storeValue && storeValue.trim() !== '') {
            currentChatId = storeValue;
            console.debug('[SettingsShare] currentChatId updated from store:', currentChatId);
        } else {
            currentChatId = null;
        }
    });
    
    // Chat ownership and type detection
    let currentChat = $state<any>(null);
    let isDemoChatType = $derived(currentChatId ? isDemoChat(currentChatId) : false);
    let isPublicChatType = $derived(currentChatId ? isPublicChat(currentChatId) : false);
    let isOwnedByUser = $state(true); // Default to true, will be checked asynchronously
    let isSharedChatNotOwned = $derived(!isOwnedByUser && !isPublicChatType && $authStore.isAuthenticated);
    
    // ===============================
    // Duration Options
    // ===============================
    
    /**
     * Available duration options for link expiration
     * Value is in seconds (0 = no expiration)
     * Options: never, 1 min, 1 hour, 24 hours, 7 days, 14 days, 30 days, 90 days
     */
    const durationOptions: { value: ShareDuration; labelKey: string }[] = [
        { value: 0, labelKey: 'settings.share.no_expiration.text' },
        { value: 60, labelKey: 'settings.share.one_minute.text' },
        { value: 3600, labelKey: 'settings.share.one_hour.text' },
        { value: 86400, labelKey: 'settings.share.twenty_four_hours.text' },
        { value: 604800, labelKey: 'settings.share.seven_days.text' },
        { value: 1209600, labelKey: 'settings.share.fourteen_days.text' },
        { value: 2592000, labelKey: 'settings.share.thirty_days.text' },
        { value: 7776000, labelKey: 'settings.share.ninety_days.text' }
    ];
    
    // Two-step flow state: configure options first, then generate link
    // For non-authenticated users, demo chats, and shared chats user doesn't own,
    // skip configuration and go straight to link generation
    // CRITICAL: Check isPublicChat() directly to ensure demo chats are detected correctly
    let isConfigurationStep = $derived(
        currentChatId && $authStore.isAuthenticated && !isPublicChat(currentChatId) && isOwnedByUser ? true : false
    );
    
    // ===============================
    // Link Generation
    // ===============================
    
    /**
     * Generate the share link with encrypted key blob
     * This is done entirely offline - no server request needed
     * Moves from configuration step to link generation step
     * For public chats (demo and legal): generates simple link format {domain}/#chat-id={chat id}
     * For shared chats user doesn't own: reconstructs original share link
     * For owned chats: uses configured settings (password, expiration)
     */
    async function generateLink() {
        if (!currentChatId) {
            console.warn('[SettingsShare] No chat selected to share');
            return;
        }
        
        try {
            console.debug('[SettingsShare] Generating share link for chat:', currentChatId);
            
            // For public chats (demo and legal): generate simple link format
            // Check directly using isPublicChat() to include both demo and legal chats
            if (isPublicChat(currentChatId)) {
                const baseUrl = window.location.origin;
                generatedLink = `${baseUrl}/#chat-id=${currentChatId}`;
                isLinkGenerated = true;
                isConfigurationStep = false;
                generateQRCode(generatedLink);
                console.debug('[SettingsShare] Public chat (demo/legal) share link generated:', generatedLink);
                return;
            }
            
            // For shared chats user doesn't own: reconstruct original share link
            // Use default settings (no password, no expiration) since we don't have original settings
            // Check ownership directly (not using derived value since it might not be updated yet)
            if ($authStore.isAuthenticated && !isPublicChatType && !isOwnedByUser) {
                try {
                    // Get the chat encryption key from cache (it was stored when user accessed the shared chat)
                    const chatEncryptionKey = await getChatEncryptionKey();
                    
                    // Create encrypted blob with default settings (no password, no expiration)
                    // This reconstructs the share link, though it may differ from original if original had password/expiration
                    const encryptedBlob = await generateShareKeyBlob(
                        currentChatId,
                        chatEncryptionKey,
                        0, // No expiration
                        undefined // No password
                    );
                    
                    const baseUrl = window.location.origin;
                    generatedLink = `${baseUrl}/share/chat/${currentChatId}#key=${encryptedBlob}`;
                    isLinkGenerated = true;
                    isConfigurationStep = false;
                    generateQRCode(generatedLink);
                    console.debug('[SettingsShare] Shared chat (not owned) share link generated:', generatedLink);
                    return;
                } catch (error) {
                    console.error('[SettingsShare] Error generating share link for shared chat:', error);
                    // If we can't get the key, we can't generate the link
                    return;
                }
            }
            
            // For owned chats: use configured settings
            const usePassword = isPasswordProtected;
            const usePasswordValue = usePassword ? password : undefined;
            const useDuration = selectedDuration;
            
            // Validate password if protection is enabled
            if (usePassword && (!password || password.length === 0 || password.length > 10)) {
                console.warn('[SettingsShare] Invalid password for protected share');
                return;
            }
            
            // Get the actual chat encryption key from IndexedDB
            const chatEncryptionKey = await getChatEncryptionKey();
            
            // Create the encrypted blob using our encryption service
            const encryptedBlob = await generateShareKeyBlob(
                currentChatId,
                chatEncryptionKey,
                useDuration,
                usePasswordValue
            );
            
            // Construct the full URL
            // The chat ID is in the path (visible to server for OG tags)
            // The encrypted blob is in the fragment (never sent to server)
            const baseUrl = window.location.origin;
            generatedLink = `${baseUrl}/share/chat/${currentChatId}#key=${encryptedBlob}`;
            isLinkGenerated = true;
            
            // Move to link generation step (show link and QR code)
            isConfigurationStep = false;
            
            // Generate QR code
            generateQRCode(generatedLink);
            
            // Mark chat as shared in IndexedDB (only for owned chats)
            // Don't mark shared chats as shared since user doesn't own them
            if (isOwnedByUser && !isPublicChatType) {
                await markChatAsShared(currentChatId);
                
                // Queue OG metadata update to server (retry if offline)
                // Only update OG metadata for chats the user owns
                if ($authStore.isAuthenticated) {
                    await queueOGMetadataUpdate();
                }
            }
            
            console.debug('[SettingsShare] Share link generated successfully');
        } catch (error) {
            console.error('[SettingsShare] Error generating share link:', error);
        }
    }
    
    /**
     * Check chat ownership asynchronously
     * Compares chat's user_id with current user's user_id
     */
    async function checkChatOwnership() {
        // CRITICAL: Check if it's a public chat directly (not using derived value)
        // This ensures we don't try to load demo/legal chats from the database
        const isPublic = currentChatId ? isPublicChat(currentChatId) : false;
        
        if (!currentChatId || !$authStore.isAuthenticated || isPublic) {
            // For non-authenticated users or public chats, assume owned (or not applicable)
            isOwnedByUser = true;
            console.debug('[SettingsShare] Skipping ownership check for public chat or non-authenticated user:', {
                currentChatId,
                isAuthenticated: $authStore.isAuthenticated,
                isPublic
            });
            return;
        }
        
        try {
            // Get current chat from database
            const { chatDB } = await import('../../../services/db');
            const chat = await chatDB.getChat(currentChatId);
            
            if (!chat) {
                // Chat not found, assume owned (fail open for UX)
                isOwnedByUser = true;
                return;
            }
            
            currentChat = chat;
            
            // If chat has no user_id, assume it's owned (backwards compatibility)
            if (!chat.user_id) {
                isOwnedByUser = true;
                return;
            }
            
            // Get current user ID
            const profile = await userDB.getUserProfile();
            const currentUserId = (profile as any)?.user_id;
            
            if (!currentUserId) {
                // Can't determine ownership, default to owned (fail open for UX)
                isOwnedByUser = true;
                return;
            }
            
            // Compare chat's user_id with current user's user_id
            isOwnedByUser = chat.user_id === currentUserId;
            console.debug(`[SettingsShare] Chat ownership check: ${isOwnedByUser} for chat ${currentChatId} (chat.user_id: ${chat.user_id}, currentUserId: ${currentUserId})`);
        } catch (error) {
            console.error('[SettingsShare] Error checking chat ownership:', error);
            // On error, assume owned (fail open for UX)
            isOwnedByUser = true;
        }
    }
    
    /**
     * Auto-generate link on mount for:
     * - Non-authenticated users (public chats)
     * - Public chats (demo and legal, for authenticated users too)
     * - Shared chats user doesn't own
     * They skip the configuration step and go straight to link/QR code
     */
    // Function to check and generate link if needed
    async function checkAndGenerateLink() {
        const chatId = currentChatId;
        if (!chatId) {
            console.debug('[SettingsShare] checkAndGenerateLink: No chatId available');
            return;
        }
        
        if (isLinkGenerated) {
            console.debug('[SettingsShare] checkAndGenerateLink: Link already generated');
            return;
        }
        
        // Check if it's a demo chat or public chat directly (more reliable than derived value)
        const isDemo = isDemoChat(chatId);
        const isPublic = isPublicChat(chatId);
        const isAuth = $authStore.isAuthenticated;
        
        console.debug('[SettingsShare] checkAndGenerateLink - chatId:', chatId, 'isDemo:', isDemo, 'isPublic:', isPublic, 'isAuth:', isAuth, 'isLinkGenerated:', isLinkGenerated);
        
        // Auto-generate link for demo chats, public chats, or non-authenticated users
        if (isDemo || isPublic || !isAuth) {
            console.debug('[SettingsShare] Auto-generating link for demo/public/non-auth chat:', chatId);
            try {
                await generateLink();
            } catch (error) {
                console.error('[SettingsShare] Error auto-generating link:', error);
            }
        } else if (isAuth && !isPublic) {
            // For authenticated users with non-public chats, check ownership first
            try {
                await checkChatOwnership();
                if (!isOwnedByUser && !isLinkGenerated && chatId) {
                    console.debug('[SettingsShare] Auto-generating link for shared chat (not owned):', chatId);
                    await generateLink();
                }
            } catch (error) {
                console.error('[SettingsShare] Error checking ownership or generating link:', error);
            }
        }
    }
    
    // Effect to watch for chatId changes
    $effect(() => {
        // Track dependencies to ensure reactivity
        const chatId = currentChatId;
        const isAuth = $authStore.isAuthenticated;
        const storeValue = $activeChatStore;
        
        console.debug('[SettingsShare] Effect triggered - chatId:', chatId, 'storeValue:', storeValue, 'isAuth:', isAuth, 'isLinkGenerated:', isLinkGenerated);
        
        if (chatId && !isLinkGenerated) {
            // Use setTimeout to ensure the component is fully mounted and store is updated
            setTimeout(() => {
                checkAndGenerateLink();
            }, 150);
        }
    });
    
    // Also check on mount in case the chatId is already set
    onMount(() => {
        console.debug('[SettingsShare] onMount - currentChatId:', currentChatId, 'activeChatStore:', $activeChatStore);
        // Ensure currentChatId is synced from store on mount
        const storeValue = $activeChatStore;
        if (storeValue && storeValue.trim() !== '' && storeValue !== currentChatId) {
            currentChatId = storeValue;
            console.debug('[SettingsShare] Synced currentChatId from store on mount:', currentChatId);
        }
        
        if (currentChatId && !isLinkGenerated) {
            setTimeout(() => {
                checkAndGenerateLink();
            }, 250);
        }
    });
    
    /**
     * Mark chat as shared in IndexedDB
     * Sets is_shared = true locally, which will be synced to server
     */
    async function markChatAsShared(chatId: string) {
        if (!chatId) return;
        
        try {
            const { chatDB } = await import('../../../services/db');
            const chat = await chatDB.getChat(chatId);
            
            if (chat) {
                // Update chat with is_shared = true and is_private = false
                await chatDB.updateChat({
                    ...chat,
                    is_shared: true,
                    is_private: false
                });
                console.debug('[SettingsShare] Marked chat as shared in IndexedDB:', chatId);
                
                // Dispatch event to notify other components (e.g., SettingsShared)
                window.dispatchEvent(new CustomEvent('chatShared', { detail: { chat_id: chatId } }));
            } else {
                console.warn('[SettingsShare] Chat not found for marking as shared:', chatId);
            }
        } catch (error) {
            console.error('[SettingsShare] Error marking chat as shared:', error);
        }
    }
    
    /**
     * Queue OG metadata update to server
     * This updates the server with title and summary for social media previews
     * If offline, the request is queued and retried when connection is restored
     * 
     * According to share_chat.md:
     * 1. Client decrypts encrypted_title and encrypted_chat_summary using chat key
     * 2. Client sends plaintext title and summary to server
     * 3. Server encrypts with shared vault key and stores in shared_encrypted_title and shared_encrypted_summary
     * 4. Also sends is_shared = true to mark the chat as shared on the server
     */
    async function queueOGMetadataUpdate() {
        if (!currentChatId) return;
        
        try {
            console.debug('[SettingsShare] Starting OG metadata update for chat:', currentChatId);
            
            // Get the chat from IndexedDB to decrypt title and summary
            const { chatDB } = await import('../../../services/db');
            const chat = await chatDB.getChat(currentChatId);
            
            if (!chat) {
                console.warn('[SettingsShare] Chat not found for OG metadata update');
                return;
            }
            
            // Decrypt title and summary using chat key
            // The chat key should already be available in chatDB cache
            const chatKey = chatDB.getChatKey(currentChatId);
            if (!chatKey) {
                console.warn('[SettingsShare] Chat key not found, cannot decrypt metadata for OG update');
                return;
            }
            
            const { decryptWithChatKey } = await import('../../../services/cryptoService');
            const { getApiEndpoint } = await import('../../../config/api');
            
            // Decrypt title
            let title: string | null = null;
            if (chat.encrypted_title) {
                title = await decryptWithChatKey(chat.encrypted_title, chatKey);
                if (!title) {
                    console.warn('[SettingsShare] Failed to decrypt title for OG metadata update');
                }
            }
            
            // Decrypt summary
            let summary: string | null = null;
            if (chat.encrypted_chat_summary) {
                summary = await decryptWithChatKey(chat.encrypted_chat_summary, chatKey);
                if (!summary) {
                    console.warn('[SettingsShare] Failed to decrypt summary for OG metadata update');
                }
            }
            
            // Always send is_shared = true when sharing (even if no title/summary)
            // This ensures the server marks the chat as shared
            try {
                const response = await fetch(getApiEndpoint('/v1/share/chat/metadata'), {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json',
                        'Accept': 'application/json',
                        'Origin': window.location.origin
                    },
                    body: JSON.stringify({
                        chat_id: currentChatId,
                        title: title || null,
                        summary: summary || null,
                        is_shared: true  // Mark chat as shared on server
                    }),
                    credentials: 'include' // Include cookies for authentication
                });
                
                if (!response.ok) {
                    const errorData = await response.json().catch(() => ({ detail: 'Unknown error' }));
                    console.warn('[SettingsShare] Failed to update OG metadata, queueing for retry:', errorData);
                    
                    // Queue for retry if offline or server error
                    // Network errors will be caught in the catch block
                    await shareMetadataQueue.queueUpdate(currentChatId, title, summary);
                    return;
                }
                
                const data = await response.json();
                if (data.success) {
                    console.debug('[SettingsShare] Successfully updated OG metadata and sharing status for chat:', currentChatId);
                } else {
                    console.warn('[SettingsShare] OG metadata update returned success=false, queueing for retry:', data);
                    // Queue for retry even if server returned success=false
                    await shareMetadataQueue.queueUpdate(currentChatId, title, summary);
                }
            } catch (fetchError: any) {
                // Network error (offline, timeout, etc.) - queue for retry
                console.debug('[SettingsShare] Network error sending OG metadata update, queueing for retry:', fetchError);
                await shareMetadataQueue.queueUpdate(currentChatId, title, summary);
            }
        } catch (error) {
            console.error('[SettingsShare] Error queueing OG metadata update:', error);
            // Don't block link generation if OG update fails
        }
    }
    
    /**
     * Go back to configuration step
     * Allows user to change settings and regenerate link
     */
    function backToConfiguration() {
        isConfigurationStep = true;
        resetGeneratedState();
    }
    
    /**
     * Get the chat's encryption key from IndexedDB
     * The chat key is stored in the database service's cache or can be retrieved from the chat object
     */
    async function getChatEncryptionKey(): Promise<string> {
        if (!currentChatId) {
            throw new Error('No chat ID available');
        }
        
        try {
            // Import chatDB to access the chat key
            const { chatDB } = await import('../../../services/db');
            
            // Get or generate the chat key (this returns the plaintext key)
            const chatKey = chatDB.getOrGenerateChatKey(currentChatId);
            
            if (!chatKey) {
                throw new Error('Failed to retrieve chat encryption key');
            }
            
            // Convert the chat key (Uint8Array) to base64 for use in share encryption
            // The chat key is already a string in the format we need, but we should verify
            // If it's a Uint8Array, convert to base64
            if (chatKey instanceof Uint8Array) {
                return btoa(String.fromCharCode(...chatKey));
            } else if (typeof chatKey === 'string') {
                // If it's already a string, it might be base64 or hex
                // For share encryption, we need base64, so if it's hex, convert it
                // Otherwise, assume it's already base64
                return chatKey;
            } else {
                throw new Error('Unexpected chat key format');
            }
        } catch (error) {
            console.error('[SettingsShare] Error getting chat encryption key:', error);
            throw error;
        }
    }
    
    /**
     * Generate QR code SVG from the share link
     */
    function generateQRCode(link: string) {
        try {
            const qr = new QRCodeSVG({
                content: link,
                padding: 4,
                width: 180,
                height: 180,
                color: '#000000',
                background: '#ffffff',
                ecl: 'M' // Medium error correction level
            });
            qrCodeSvg = qr.svg();
        } catch (error) {
            console.error('[SettingsShare] Error generating QR code:', error);
            qrCodeSvg = '';
        }
    }
    
    // ===============================
    // Copy Link Handler
    // ===============================
    
    /**
     * Copy the generated link to clipboard
     */
    async function copyLinkToClipboard() {
        if (!generatedLink) return;
        
        try {
            await navigator.clipboard.writeText(generatedLink);
            isCopied = true;
            console.debug('[SettingsShare] Link copied to clipboard');
            
            // Reset the copied state after 2 seconds
            setTimeout(() => {
                isCopied = false;
            }, 2000);
        } catch (error) {
            console.error('[SettingsShare] Error copying link to clipboard:', error);
        }
    }
    
    // ===============================
    // Reset State
    // ===============================
    
    /**
     * Reset all state when options change
     */
    function resetGeneratedState() {
        isLinkGenerated = false;
        generatedLink = '';
        qrCodeSvg = '';
        isCopied = false;
    }
    
    // Reset generated link when configuration changes (but only if we're in configuration step)
    $effect(() => {
        if (isConfigurationStep) {
            // Tracking dependencies
            void isPasswordProtected;
            void selectedDuration;
            void password;
            resetGeneratedState();
        }
    });
    
    // ===============================
    // Password Validation
    // ===============================
    
    // Password must be max 10 characters
    let isPasswordValid = $derived(!isPasswordProtected || (password.length > 0 && password.length <= 10));
    let canGenerateLink = $derived(currentChatId && isPasswordValid);
</script>

<!-- No chat selected message -->
{#if !currentChatId}
    <div class="no-chat-message" transition:fade={{ duration: 200 }}>
        <div class="icon settings_size shared"></div>
        <p>{$text('settings.share.no_chat_selected.text')}</p>
    </div>
{:else}
    <!-- Share description -->
    <div class="share-description" transition:fade={{ duration: 200 }}>
        <p>{$text('settings.share.share_description.text')}</p>
    </div>
    
    <!-- Two-Step Flow: Configuration Step -->
    {#if isConfigurationStep}
        <!-- Share Options Section -->
        <div class="share-options-section">
            <h3 class="section-title">{$text('settings.share.share_options.text')}</h3>
            
            <!-- Password Protection Toggle -->
            <div class="option-row">
                <div class="option-label">
                    <div class="icon settings_size lock"></div>
                    <span>{$text('settings.share.password_protection.text')}</span>
                </div>
                <Toggle
                    bind:checked={isPasswordProtected}
                    name="password-protection"
                    ariaLabel="Toggle password protection"
                />
            </div>
            
            <!-- Password Input (shown when password protection is enabled) -->
            {#if isPasswordProtected}
                <div class="password-input-container" transition:slide={{ duration: 200, easing: cubicOut }}>
                    <input
                        type="password"
                        bind:value={password}
                        placeholder={$text('settings.share.password_placeholder.text')}
                        maxlength="10"
                        class="password-input"
                        class:invalid={password.length > 10}
                    />
                    <p class="password-info">{$text('settings.share.password_required_info.text')}</p>
                </div>
            {/if}
            
            <!-- Time Limit Selection -->
            <div class="option-row">
                <div class="option-label">
                    <div class="icon settings_size time"></div>
                    <span>{$text('settings.share.time_limit.text')}</span>
                </div>
            </div>
            
            <!-- Duration Options -->
            <div class="duration-options">
                {#each durationOptions as option}
                    <button
                        class="duration-option"
                        class:selected={selectedDuration === option.value}
                        onclick={() => selectedDuration = option.value}
                    >
                        {$text(option.labelKey)}
                    </button>
                {/each}
            </div>
            
            <!-- Expire Time Info -->
            <div class="expire-time-info">
                <div class="info-icon">⏱️</div>
                <p>{$text('settings.share.expire_time_info.text')}</p>
            </div>
            
            <!-- Encryption Info -->
            <div class="encryption-info">
                <div class="info-icon">🔒</div>
                <p>{$text('settings.share.encryption_info.text')}</p>
            </div>
        </div>
        
        <!-- Share Chat Button (triggers link generation) -->
        <button
            class="share-chat-button"
            onclick={generateLink}
            disabled={!canGenerateLink}
        >
            {$text('settings.share.share_chat.text')}
        </button>
    {:else}
    <!-- Two-Step Flow: Link Generation Step -->
    {#if isLinkGenerated}
        <div class="generated-link-section" transition:slide={{ duration: 300, easing: cubicOut }}>
            <!-- Copy Link Button -->
            <button
                class="copy-link-button"
                class:copied={isCopied}
                onclick={copyLinkToClipboard}
            >
                <div class="copy-icon" class:icon_check={isCopied} class:icon_copy={!isCopied}></div>
                <span>{isCopied ? $text('settings.share.link_copied.text') : $text('settings.share.click_to_copy.text')}</span>
            </button>
            
            <!-- Expiration Info (if time limit set) -->
            {#if selectedDuration > 0}
                <p class="expiration-info">
                    {$text('settings.share.link_will_expire_in.text')} {$text(durationOptions.find(d => d.value === selectedDuration)?.labelKey || '')}
                </p>
            {/if}
            
            <!-- QR Code Section -->
            <div class="qr-code-section">
                <h4 class="qr-code-title">{$text('settings.share.qr_code.text')}</h4>
                <div class="qr-code-container">
                    {#if qrCodeSvg}
                        {@html qrCodeSvg}
                    {/if}
                </div>
                <p class="qr-code-instruction">{$text('settings.share.scan_qr_code.text')}</p>
            </div>
            
            <!-- Back to Configuration Button (only shown for owned chats) -->
            {#if isOwnedByUser && !isPublicChatType}
                <button
                    class="back-to-config-button"
                    onclick={backToConfiguration}
                >
                    {$text('settings.share.change_settings.text')}
                </button>
            {/if}
        </div>
    {/if}
    {/if}
{/if}

<style>
    
    /* No chat selected state */
    .no-chat-message {
        display: flex;
        flex-direction: column;
        align-items: center;
        justify-content: center;
        padding: 40px 20px;
        text-align: center;
        color: var(--color-grey-60);
    }
    
    .no-chat-message .icon {
        width: 48px;
        height: 48px;
        margin-bottom: 16px;
        opacity: 0.5;
    }
    
    .no-chat-message p {
        font-size: 14px;
        margin: 0;
    }
    
    /* Share description */
    .share-description {
        padding: 12px 16px;
        background-color: var(--color-grey-10);
        border-radius: 8px;
    }
    
    .share-description p {
        font-size: 14px;
        color: var(--color-grey-80);
        margin: 0;
        line-height: 1.5;
    }
    
    /* Share options section */
    .share-options-section {
        display: flex;
        flex-direction: column;
        gap: 12px;
    }
    
    .section-title {
        font-size: 14px;
        font-weight: 600;
        color: var(--color-grey-100);
        margin: 0 0 8px 0;
    }
    
    /* Option row */
    .option-row {
        display: flex;
        align-items: center;
        justify-content: space-between;
        padding: 8px 12px;
        background-color: var(--color-grey-10);
        border-radius: 8px;
    }
    
    .option-label {
        display: flex;
        align-items: center;
        gap: 12px;
    }
    
    .option-label .icon {
        width: 24px;
        height: 24px;
    }
    
    .option-label span {
        font-size: 14px;
        color: var(--color-grey-100);
    }
    
    /* Password input */
    .password-input-container {
        padding: 0 12px;
    }
    
    .password-input {
        width: 100%;
        padding: 12px 16px;
        border: 1px solid var(--color-grey-30);
        border-radius: 8px;
        font-size: 14px;
        background-color: var(--color-grey-5);
        color: var(--color-grey-100);
        transition: border-color 0.2s ease;
    }
    
    .password-input:focus {
        outline: none;
        border-color: var(--color-primary);
    }
    
    .password-input.invalid {
        border-color: var(--color-error, #ef4444);
    }
    
    .password-info {
        font-size: 12px;
        color: var(--color-grey-60);
        margin: 8px 0 0 0;
    }
    
    /* Duration options */
    .duration-options {
        display: flex;
        flex-wrap: wrap;
        gap: 8px;
        padding: 0 12px;
    }
    
    .duration-option {
        padding: 8px 16px;
        border: 1px solid var(--color-grey-30);
        border-radius: 20px;
        background-color: var(--color-grey-5);
        color: var(--color-grey-80);
        font-size: 13px;
        cursor: pointer;
        transition: all 0.2s ease;
    }
    
    .duration-option:hover {
        background-color: var(--color-grey-10);
    }
    
    .duration-option.selected {
        background-color: var(--color-primary);
        border-color: var(--color-primary);
        color: white;
    }
    
    /* Encryption info */
    .encryption-info {
        display: flex;
        align-items: flex-start;
        gap: 10px;
        padding: 12px 16px;
        background-color: var(--color-grey-5);
        border-radius: 8px;
        border: 1px solid var(--color-grey-20);
    }
    
    .info-icon {
        font-size: 16px;
        line-height: 1;
    }
    
    .encryption-info p {
        font-size: 12px;
        color: var(--color-grey-70);
        margin: 0;
        line-height: 1.4;
    }
    
    /* Share chat button (configuration step) */
    .share-chat-button {
        width: 100%;
        padding: 14px 20px;
        background-color: var(--color-primary);
        color: white;
        border: none;
        border-radius: 10px;
        font-size: 15px;
        font-weight: 500;
        cursor: pointer;
        transition: all 0.2s ease;
    }
    
    .share-chat-button:hover:not(:disabled) {
        background-color: var(--color-primary-dark, #5a36b2);
        transform: translateY(-1px);
    }
    
    .share-chat-button:disabled {
        opacity: 0.5;
        cursor: not-allowed;
    }
    
    /* Expire time info */
    .expire-time-info {
        display: flex;
        align-items: flex-start;
        gap: 10px;
        padding: 12px 16px;
        background-color: var(--color-grey-5);
        border-radius: 8px;
        border: 1px solid var(--color-grey-20);
        margin-top: 8px;
    }
    
    .expire-time-info .info-icon {
        font-size: 16px;
        line-height: 1;
    }
    
    .expire-time-info p {
        font-size: 12px;
        color: var(--color-grey-70);
        margin: 0;
        line-height: 1.4;
    }
    
    /* Back to configuration button */
    .back-to-config-button {
        width: 100%;
        padding: 12px 20px;
        background-color: var(--color-grey-10);
        color: var(--color-grey-100);
        border: 1px solid var(--color-grey-30);
        border-radius: 10px;
        font-size: 14px;
        font-weight: 500;
        cursor: pointer;
        transition: all 0.2s ease;
        margin-top: 8px;
    }
    
    .back-to-config-button:hover {
        background-color: var(--color-grey-15, #e8e8e8);
        border-color: var(--color-grey-40);
    }
    
    /* Generated link section */
    .generated-link-section {
        display: flex;
        flex-direction: column;
        gap: 16px;
        padding-top: 8px;
    }
    
    /* Copy link button */
    .copy-link-button {
        display: flex;
        align-items: center;
        justify-content: center;
        gap: 10px;
        width: 100%;
        padding: 14px 20px;
        background-color: var(--color-grey-10);
        border: 2px dashed var(--color-grey-40);
        border-radius: 10px;
        font-size: 14px;
        color: var(--color-grey-100);
        cursor: pointer;
        transition: all 0.2s ease;
    }
    
    .copy-link-button:hover {
        background-color: var(--color-grey-15, #e8e8e8);
        border-color: var(--color-grey-50);
    }
    
    .copy-link-button.copied {
        background-color: var(--color-success-light, #dcfce7);
        border-color: var(--color-success, #22c55e);
        border-style: solid;
        color: var(--color-success, #22c55e);
    }
    
    .copy-icon {
        width: 18px;
        height: 18px;
        background-color: currentColor;
        -webkit-mask-size: contain;
        -webkit-mask-position: center;
        -webkit-mask-repeat: no-repeat;
        mask-size: contain;
        mask-position: center;
        mask-repeat: no-repeat;
    }
    
    .copy-icon.icon_copy {
        -webkit-mask-image: url('@openmates/ui/static/icons/copy.svg');
        mask-image: url('@openmates/ui/static/icons/copy.svg');
    }
    
    .copy-icon.icon_check {
        -webkit-mask-image: url('@openmates/ui/static/icons/check.svg');
        mask-image: url('@openmates/ui/static/icons/check.svg');
    }
    
    /* Expiration info */
    .expiration-info {
        font-size: 13px;
        color: var(--color-grey-60);
        text-align: center;
        margin: 0;
    }
    
    /* QR Code section */
    .qr-code-section {
        display: flex;
        flex-direction: column;
        align-items: center;
        padding: 20px;
        background-color: var(--color-grey-5);
        border-radius: 12px;
    }
    
    .qr-code-title {
        font-size: 14px;
        font-weight: 600;
        color: var(--color-grey-100);
        margin: 0 0 16px 0;
    }
    
    .qr-code-container {
        background-color: white;
        padding: 12px;
        border-radius: 8px;
        box-shadow: 0 2px 8px rgba(0, 0, 0, 0.1);
    }
    
    .qr-code-container :global(svg) {
        display: block;
    }
    
    .qr-code-instruction {
        font-size: 12px;
        color: var(--color-grey-60);
        margin: 16px 0 0 0;
        text-align: center;
    }
</style>



