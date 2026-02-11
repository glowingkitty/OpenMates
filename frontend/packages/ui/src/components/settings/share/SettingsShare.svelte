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
    import { onMount, type Component } from 'svelte';
    import Toggle from '../../Toggle.svelte';
    import { fade, slide } from 'svelte/transition';
    import { cubicOut } from 'svelte/easing';
    import QRCodeSVG from 'qrcode-svg';
    import ChatComponent from '../../chats/Chat.svelte';
    import { activeChatStore } from '../../../stores/activeChatStore';
    import { authStore } from '../../../stores/authStore';
    import type { Chat as ChatInterface, SyncEmbed } from '../../../types/chat';
    import { settingsDeepLink } from '../../../stores/settingsDeepLinkStore';
    import { generateShareKeyBlob, type ShareDuration } from '../../../services/shareEncryption';
    import { shareMetadataQueue } from '../../../services/shareMetadataQueue';
    import { isDemoChat, isPublicChat } from '../../../demo_chats/convertToChat';
    import { userDB } from '../../../services/userDB';
    import { embedStore } from '../../../services/embedStore';
    import { decodeToonContent } from '../../../services/embedResolver';
    // PII detection service is dynamically imported where needed (restorePIIInText in community share)
    
    // Define interface for embed context to avoid 'any'
    interface EmbedContext {
        embed_id: string;
        type?: string;
        title?: string;
        url?: string;
        language?: string;
        filename?: string;
        lineCount?: number;
    }

    // Define custom window type for embed sharing context
    interface EmbedWindow extends Window {
        __embedShareContext?: EmbedContext | null;
    }
    
    // Import embed preview components
    import WebSearchEmbedPreview from '../../embeds/web/WebSearchEmbedPreview.svelte';
    import NewsSearchEmbedPreview from '../../embeds/news/NewsSearchEmbedPreview.svelte';
    import VideosSearchEmbedPreview from '../../embeds/videos/VideosSearchEmbedPreview.svelte';
    import MapsSearchEmbedPreview from '../../embeds/maps/MapsSearchEmbedPreview.svelte';
    import VideoTranscriptEmbedPreview from '../../embeds/videos/VideoTranscriptEmbedPreview.svelte';
    import WebsiteEmbedPreview from '../../embeds/web/WebsiteEmbedPreview.svelte';
    import VideoEmbedPreview from '../../embeds/videos/VideoEmbedPreview.svelte';
    import CodeEmbedPreview from '../../embeds/code/CodeEmbedPreview.svelte';
    import ReminderEmbedPreview from '../../embeds/reminder/ReminderEmbedPreview.svelte';
    import TravelSearchEmbedPreview from '../../embeds/travel/TravelSearchEmbedPreview.svelte';
    import TravelPriceCalendarEmbedPreview from '../../embeds/travel/TravelPriceCalendarEmbedPreview.svelte';
    import ImageGenerateEmbedPreview from '../../embeds/images/ImageGenerateEmbedPreview.svelte';
    import SheetEmbedPreview from '../../embeds/sheets/SheetEmbedPreview.svelte';
    
    /**
     * Portal action to render element at body level
     * This ensures the overlay escapes parent container constraints
     */
    function portal(node: HTMLElement) {
        // Append to body
        document.body.appendChild(node);
        
        // Return cleanup function
        return {
            destroy() {
                if (node.parentNode) {
                    node.parentNode.removeChild(node);
                }
            }
        };
    }
    
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

    // Share with Community state - only for chats, not embeds
    let shareWithCommunity = $state(false);

    // Include sensitive data state - when false (default), PII is stripped from shared content.
    // Users must explicitly opt-in to include their personal information in shared chats.
    let includeSensitiveData = $state(false);

    // Whether the current chat has any PII mappings (used to conditionally show the sensitive data toggle)
    let chatHasPII = $state(false);

    // Generated share link state
    let generatedLink = $state('');
    let isLinkGenerated = $state(false);
    let isCopied = $state(false);

    // QR code SVG content
    let qrCodeSvg = $state('');
    
    // QR code size state - calculated based on viewport
    // Normal size: fits container, max 300px
    let qrCodeSize = $state(180);
    // Fullscreen size: large and easy to scan
    let qrCodeFullscreenSize = $state(600);

    // QR code fullscreen overlay state
    let showQRFullscreen = $state(false);
    
    // Viewport dimensions for responsive QR code sizing
    let viewportWidth = $state(0);
    let viewportHeight = $state(0);
    // Embed sharing context detection
    // Check if we're sharing an embed instead of a chat
    let embedContext = $state<EmbedContext | null>(null);
    let isEmbedSharing = $derived(embedContext !== null);
    
    /**
     * Load and render embed preview component
     * Returns a promise that resolves to component and props, or null if not available
     * This matches the pattern used in AppEmbedsPanel.svelte
     */
    async function loadEmbedPreview(): Promise<{ component: Component; props: Record<string, unknown> } | null> {
        if (!embedContext || !embedContext.embed_id) {
            return null;
        }
        
        try {
            const embedId = embedContext.embed_id;
            console.debug('[SettingsShare] Loading embed preview for:', embedId);
            
            // Load embed from store
            const contentRef = `embed:${embedId}`;
            const embedData = await embedStore.get(contentRef);
            
            if (!embedData || !embedData.content) {
                console.warn('[SettingsShare] No embed content available for preview');
                return;
            }
            
            // Decode the content
            const decodedContent = await decodeToonContent(embedData.content);
            if (!decodedContent) {
                console.warn('[SettingsShare] Failed to decode embed content');
                return;
            }
            
            // Get app_id and skill_id from embed data or decoded content
            const embedAppId = embedData.app_id || decodedContent.app_id || '';
            const skillId = embedData.skill_id || decodedContent.skill_id || '';
            const status =
                embedData.status === 'processing' || embedData.status === 'finished' || embedData.status === 'error'
                    ? embedData.status
                    : 'finished';
            
            console.debug('[SettingsShare] Rendering embed preview:', { embedId, appId: embedAppId, skillId, status });
            
            // Determine which component to use based on app_id and skill_id
            // This matches the logic from AppEmbedsPanel and AppSkillUseRenderer
            if (embedAppId === 'web' && skillId === 'search') {
                return {
                    component: WebSearchEmbedPreview,
                    props: {
                        id: embedId,
                        query: decodedContent.query || '',
                        provider: decodedContent.provider || 'Brave Search',
                        status: status,
                        results: decodedContent.results || [],
                        isMobile: false,
                        onFullscreen: () => {} // No-op for share preview
                    }
                };
            } else if (embedAppId === 'news' && skillId === 'search') {
                return {
                    component: NewsSearchEmbedPreview,
                    props: {
                        id: embedId,
                        query: decodedContent.query || '',
                        provider: decodedContent.provider || 'Brave Search',
                        status: status,
                        results: decodedContent.results || [],
                        isMobile: false,
                        onFullscreen: () => {}
                    }
                };
            } else if (embedAppId === 'videos' && skillId === 'search') {
                return {
                    component: VideosSearchEmbedPreview,
                    props: {
                        id: embedId,
                        query: decodedContent.query || '',
                        provider: decodedContent.provider || 'Brave Search',
                        status: status,
                        results: decodedContent.results || [],
                        isMobile: false,
                        onFullscreen: () => {}
                    }
                };
            } else if (embedAppId === 'maps' && skillId === 'search') {
                return {
                    component: MapsSearchEmbedPreview,
                    props: {
                        id: embedId,
                        query: decodedContent.query || '',
                        provider: decodedContent.provider || 'Brave Search',
                        status: status,
                        results: decodedContent.results || [],
                        isMobile: false,
                        onFullscreen: () => {}
                    }
                };
            } else if (embedAppId === 'videos' && (skillId === 'get_transcript' || skillId === 'get-transcript')) {
                return {
                    component: VideoTranscriptEmbedPreview,
                    props: {
                        id: embedId,
                        results: decodedContent.results || [],
                        status: status,
                        isMobile: false,
                        onFullscreen: () => {}
                    }
                };
            } else if (embedData.type === 'website' || embedContext.type === 'website') {
                // Website embed - use WebsiteEmbedPreview
                return {
                    component: WebsiteEmbedPreview,
                    props: {
                        id: embedId,
                        url: decodedContent.url || embedContext.url || '',
                        title: decodedContent.title || embedContext.title || '',
                        description: decodedContent.description || '',
                        image: decodedContent.image || '',
                        isMobile: false,
                        onFullscreen: () => {}
                    }
                };
            } else if (embedData.type === 'video' || embedContext.type === 'video') {
                // Video embed - pass all metadata from decodedContent
                return {
                    component: VideoEmbedPreview,
                    props: {
                        id: embedId,
                        url: decodedContent.url || embedContext.url || '',
                        title: decodedContent.title || embedContext.title || '',
                        status: status,
                        isMobile: false,
                        onFullscreen: () => {},
                        // Metadata from decodedContent (loaded from IndexedDB)
                        channelName: decodedContent.channel_name,
                        channelId: decodedContent.channel_id,
                        channelThumbnail: decodedContent.channel_thumbnail,
                        thumbnail: decodedContent.thumbnail,
                        durationSeconds: decodedContent.duration_seconds,
                        durationFormatted: decodedContent.duration_formatted,
                        viewCount: decodedContent.view_count,
                        likeCount: decodedContent.like_count,
                        publishedAt: decodedContent.published_at,
                        videoId: decodedContent.video_id
                    }
                };
            } else if (embedData.type === 'code' || embedData.type === 'code-block' || embedData.type === 'code-code') {
                // Code embed
                return {
                    component: CodeEmbedPreview,
                    props: {
                        id: embedId,
                        codeContent: decodedContent.code || decodedContent.content || '',
                        language: decodedContent.language || embedContext?.language || 'text',
                        filename: decodedContent.filename || embedContext?.filename,
                        lineCount: decodedContent.lineCount || embedContext?.lineCount || 0,
                        status,
                        isMobile: false,
                        onFullscreen: () => {}
                    }
                };
            } else if (embedAppId === 'travel' && (skillId === 'search_connections' || skillId === 'search-connections')) {
                // Travel search connections embed
                return {
                    component: TravelSearchEmbedPreview,
                    props: {
                        id: embedId,
                        query: decodedContent.query || '',
                        provider: decodedContent.provider || 'Google',
                        status: status,
                        results: decodedContent.results || [],
                        isMobile: false,
                        onFullscreen: () => {}
                    }
                };
            } else if (embedAppId === 'travel' && (skillId === 'price_calendar' || skillId === 'price-calendar')) {
                // Travel price calendar embed
                return {
                    component: TravelPriceCalendarEmbedPreview,
                    props: {
                        id: embedId,
                        query: decodedContent.query || '',
                        status: status,
                        results: decodedContent.results || [],
                        isMobile: false,
                        onFullscreen: () => {}
                    }
                };
            } else if (embedAppId === 'images' && (skillId === 'generate' || skillId === 'generate_draft')) {
                // Image generate embed
                return {
                    component: ImageGenerateEmbedPreview,
                    props: {
                        id: embedId,
                        skillId: skillId as 'generate' | 'generate_draft',
                        prompt: decodedContent.prompt || '',
                        s3BaseUrl: decodedContent.s3_base_url || '',
                        files: decodedContent.files || undefined,
                        aesKey: decodedContent.aes_key || '',
                        aesNonce: decodedContent.aes_nonce || '',
                        status: status,
                        error: decodedContent.error as string | undefined,
                        isMobile: false,
                        onFullscreen: () => {}
                    }
                };
            } else if (embedAppId === 'sheets' && skillId === 'sheet') {
                // Sheet/table embed
                return {
                    component: SheetEmbedPreview,
                    props: {
                        id: embedId,
                        title: decodedContent.title || '',
                        rowCount: decodedContent.row_count || 0,
                        colCount: decodedContent.col_count || 0,
                        tableContent: decodedContent.table_content || decodedContent.content || '',
                        status: status,
                        isMobile: false,
                        onFullscreen: () => {}
                    }
                };
            } else if (embedAppId === 'reminder' && (skillId === 'set_reminder' || skillId === 'set-reminder')) {
                // Reminder embed
                return {
                    component: ReminderEmbedPreview,
                    props: {
                        id: embedId,
                        reminderId: decodedContent.reminder_id,
                        triggerAtFormatted: decodedContent.trigger_at_formatted,
                        triggerAt: decodedContent.trigger_at,
                        targetType: decodedContent.target_type,
                        isRepeating: decodedContent.is_repeating || false,
                        message: decodedContent.message,
                        emailNotificationWarning: decodedContent.email_notification_warning,
                        status: status,
                        error: decodedContent.error,
                        isMobile: false,
                        onFullscreen: () => {}
                    }
                };
            } else {
                console.warn('[SettingsShare] No preview component for embed type:', { appId: embedAppId, skillId, type: embedData.type });
                // Return null if no component available
                return null;
            }
        } catch (error) {
            console.error('[SettingsShare] Error loading embed preview:', error);
            return null;
        }
    }
    
    // Create a derived promise that loads the embed preview when embed context changes
    // This avoids infinite loops by using a promise-based approach like AppEmbedsPanel
    let embedPreviewData = $derived.by(() => {
        if (isEmbedSharing && embedContext?.embed_id) {
            // Return a promise that loads the embed preview
            // The promise will be cached by Svelte's reactivity system
            return loadEmbedPreview();
        }
        return null;
    });

    // Check for embed context on mount, when (window as EmbedWindow).__embedShareContext changes, 
    // when settingsDeepLink is set to 'shared/share' (Share button clicked),
    // and when component becomes active (activeSettingsView is 'share')
    $effect(() => {
        const windowEmbedContext = (window as EmbedWindow).__embedShareContext;
        const deepLink = $settingsDeepLink;
        const isActive = activeSettingsView === 'share';
        
        // Check for embed context when:
        // 1. (window as EmbedWindow).__embedShareContext exists (embed share button clicked)
        // 2. settingsDeepLink is set to 'shared/share' (share settings opened)
        // 3. Component becomes active (activeSettingsView is 'share')
        if (windowEmbedContext) {
            // If we already have an embed context and it's different, reset share state
            if (embedContext && embedContext.embed_id !== windowEmbedContext.embed_id) {
                console.debug('[SettingsShare] New embed context detected, resetting share state. Old:', embedContext.embed_id, 'New:', windowEmbedContext.embed_id);
                resetGeneratedState();
            }
            embedContext = windowEmbedContext;
            console.debug('[SettingsShare] Embed sharing context detected:', embedContext);
            // Clear the global context to prevent reuse
            (window as EmbedWindow).__embedShareContext = null;
        } else if (deepLink === 'shared/share' || isActive) {
            // When share settings are opened or component becomes active, check again for embed context
            // This handles timing issues where context might be set before component mounts
            const contextCheck = (window as EmbedWindow).__embedShareContext;
            if (contextCheck) {
                // If we already have an embed context and it's different, reset share state
                if (embedContext && embedContext.embed_id !== contextCheck.embed_id) {
                    console.debug('[SettingsShare] New embed context detected via deep link, resetting share state. Old:', embedContext.embed_id, 'New:', contextCheck.embed_id);
                    resetGeneratedState();
                }
                embedContext = contextCheck;
                console.debug('[SettingsShare] Embed sharing context detected via deep link or active view:', embedContext);
                // Clear the global context to prevent reuse
                (window as EmbedWindow).__embedShareContext = null;
            }
        }
    });

    // Get the current chat ID from the active chat store
    // The store directly contains the chat ID string (or null), not an object
    // Use $state to track the chat ID and update it reactively from the store
    let currentChatId = $state<string | null>(null);
    
    // Shared chat ID - the chat that is currently being shared
    // This remains stable even when user switches to other chats
    // Only updates when a new share link is generated
    let sharedChatId = $state<string | null>(null);

    // ONLY update currentChatId when Share button is explicitly clicked
    // Watch settingsDeepLink for 'shared/share' - this is set when Share button is clicked
    // This ensures the share view remains stable when user switches chats normally
    $effect(() => {
        if (!isEmbedSharing) {
            const deepLink = $settingsDeepLink;
            
            // Only react when settingsDeepLink is set to 'shared/share' (Share button clicked)
            if (deepLink === 'shared/share') {
                const storeValue = $activeChatStore;
                const newChatId = storeValue && storeValue.trim() !== '' ? storeValue : null;
                
                // If we have a generated link for a different chat, reset everything
                // This happens when user clicks Share on a different chat
                if (isLinkGenerated && sharedChatId && newChatId && newChatId !== sharedChatId) {
                    console.debug('[SettingsShare] Share button clicked for different chat, resetting share state. Old:', sharedChatId, 'New:', newChatId);
                    // Reset the share state (this sets isLinkGenerated to false)
                    resetGeneratedState();
                    // Update currentChatId to the new chat
                    currentChatId = newChatId;
                } else if (!isLinkGenerated || !sharedChatId) {
                    // Update currentChatId if no link is generated, or if we're starting fresh
                    if (newChatId !== currentChatId) {
                        currentChatId = newChatId;
                        console.debug('[SettingsShare] Share button clicked, currentChatId updated:', currentChatId);
                    }
                }
            }
            // Do NOT react to activeChatStore changes unless Share button was clicked
            // This keeps the share view stable when user switches chats
        }
    });
    
    // Chat ownership and type detection
    let currentChat = $state<ChatInterface | null>(null);
    
    /**
     * Load currentChat for display
     * Uses sharedChatId if link is generated (to keep it stable), otherwise uses currentChatId
     * This ensures the displayed chat remains unchanged when user switches chats
     */
    $effect(() => {
        // Use sharedChatId if link is generated, otherwise use currentChatId
        const chatId = isLinkGenerated ? sharedChatId : currentChatId;
        if (!chatId || isEmbedSharing) {
            currentChat = null;
            return;
        }
        
        // Load chat asynchronously
        (async () => {
            try {
                const { chatDB } = await import('../../../services/db');
                const chat = await chatDB.getChat(chatId);
                currentChat = chat || null;
                console.debug('[SettingsShare] Loaded currentChat:', chatId, chat ? 'found' : 'not found', 'isLinkGenerated:', isLinkGenerated);
            } catch (error) {
                console.error('[SettingsShare] Error loading currentChat:', error);
                currentChat = null;
            }
        })();
    });
    let isPublicChatType = $derived(currentChatId ? isPublicChat(currentChatId) : false);
    let isOwnedByUser = $state(true); // Default to true, will be checked asynchronously
    
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
    // For embeds: allow configuration for password/expiration settings
    // For non-authenticated users, demo chats, and shared chats user doesn't own,
    // skip configuration and go straight to link generation
    // CRITICAL: Check isPublicChat() directly to ensure demo chats are detected correctly
    let isConfigurationStep = $derived(
        isEmbedSharing ? true : // Allow configuration for embeds (password/expiration)
        (currentChatId && $authStore.isAuthenticated && !isPublicChat(currentChatId) && isOwnedByUser ? true : false)
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
        // Handle embed sharing
        if (isEmbedSharing) {
            if (!embedContext || !embedContext.embed_id) {
                console.warn('[SettingsShare] No embed context or embed_id available for sharing');
                return;
            }

            try {
                console.debug('[SettingsShare] Generating encrypted share link for embed:', embedContext.embed_id);

                // Import embed share encryption service
                const { generateEmbedShareKeyBlob } = await import('../../../services/embedShareEncryption');

                // Use configured settings for embed sharing
                const usePassword = isPasswordProtected;
                const usePasswordValue = usePassword ? password : undefined;
                const useDuration = selectedDuration;

                // Validate password if protection is enabled
                if (usePassword && (!password || password.length === 0 || password.length > 10)) {
                    console.warn('[SettingsShare] Invalid password for protected embed share');
                    return;
                }

                // Generate encrypted blob with embed's encryption key
                const encryptedBlob = await generateEmbedShareKeyBlob(
                    embedContext.embed_id,
                    useDuration,
                    usePasswordValue
                );

                // Construct encrypted embed share URL similar to chat sharing
                const baseUrl = window.location.origin;
                generatedLink = `${baseUrl}/share/embed/${embedContext.embed_id}#key=${encryptedBlob}`;
                isLinkGenerated = true;
                isConfigurationStep = false;
                // Note: sharedChatId not set for embeds (embedContext is used instead)
                // Keep embedContext so it persists when showing the link/QR code
                console.debug('[SettingsShare] Embed share link generated, isLinkGenerated:', isLinkGenerated, 'embedContext:', embedContext?.embed_id);

                // Generate QR code
                generateQRCode(generatedLink);

                // Mark embed as shared in IndexedDB and on server
                // Only if user is authenticated (embeds must be owned by user to share)
                if ($authStore.isAuthenticated) {
                    await markEmbedAsShared(embedContext.embed_id);
                    
                    // Queue server update to mark embed as shared (set is_private=false, is_shared=true)
                    // Uses retry queue for reliability - if the request fails, it will be retried
                    await shareMetadataQueue.queueEmbedShareUpdate(embedContext.embed_id, true);
                }
                
                console.debug('[SettingsShare] Encrypted embed share link generated:', generatedLink);
                return;
            } catch (error) {
                console.error('[SettingsShare] Error generating encrypted embed share link:', error);
                return;
            }
        }

        // Handle chat sharing (existing logic)
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
                // Store the shared chat ID to keep it stable when user switches chats
                sharedChatId = currentChatId;
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
                    // Store the shared chat ID to keep it stable when user switches chats
                    sharedChatId = currentChatId;
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
            
            // Store the shared chat ID to keep it stable when user switches chats
            // This ensures the QR code and share link remain unchanged
            sharedChatId = currentChatId;
            
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
            const currentUserId = profile?.user_id;
            
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
    // Only triggers if link is not generated - once link is generated, we keep it stable
    $effect(() => {
        // Track dependencies to ensure reactivity
        const chatId = currentChatId;
        const isAuth = $authStore.isAuthenticated;
        const storeValue = $activeChatStore;
        
        console.debug('[SettingsShare] Effect triggered - chatId:', chatId, 'storeValue:', storeValue, 'isAuth:', isAuth, 'isLinkGenerated:', isLinkGenerated);
        
        // Only auto-generate link if no link is already generated
        // This prevents the share view from updating when user switches chats
        if (chatId && !isLinkGenerated) {
            // Use setTimeout to ensure the component is fully mounted and store is updated
            setTimeout(() => {
                checkAndGenerateLink();
            }, 150);
        }
    });

    // Check whether the current chat contains PII mappings
    // This determines if we show the "Include sensitive data" toggle
    $effect(() => {
        const chatId = currentChatId;
        if (!chatId || isEmbedSharing) {
            chatHasPII = false;
            return;
        }
        // Async check - load messages and see if any have pii_mappings
        (async () => {
            try {
                const { chatDB } = await import('../../../services/db');
                const { getMessagesForChat } = await import('../../../services/db/messageOperations');
                const messages = await getMessagesForChat(chatDB as any, chatId);
                if (messages && messages.length > 0) {
                    chatHasPII = messages.some(m => m.pii_mappings && m.pii_mappings.length > 0);
                } else {
                    chatHasPII = false;
                }
            } catch (error) {
                console.error('[SettingsShare] Error checking chat PII:', error);
                chatHasPII = false;
            }
        })();
    });
    
    // Also check on mount in case the chatId is already set
    // Only initialize if we don't already have a shared chat (to maintain stability)
    onMount(() => {
        console.debug('[SettingsShare] onMount - currentChatId:', currentChatId, 'sharedChatId:', sharedChatId, 'activeChatStore:', $activeChatStore, 'embedContext:', embedContext);
        
        // Check for embed context on mount (with a small delay to ensure it's set)
        // This handles cases where embed context is set just before component mounts
        setTimeout(() => {
            const windowEmbedContext = (window as EmbedWindow).__embedShareContext;
            if (windowEmbedContext && !embedContext) {
                embedContext = windowEmbedContext;
                console.debug('[SettingsShare] Embed sharing context detected on mount:', embedContext);
                // Clear the global context to prevent reuse
                (window as EmbedWindow).__embedShareContext = null;
            }
        }, 100);
        
        // Only sync from store on mount if we don't have a shared chat already
        // This maintains stability - if we already have a shared chat, don't change it
        if (!sharedChatId && !isLinkGenerated && !embedContext) {
            const storeValue = $activeChatStore;
            if (storeValue && storeValue.trim() !== '' && storeValue !== currentChatId) {
                currentChatId = storeValue;
                console.debug('[SettingsShare] Synced currentChatId from store on mount:', currentChatId);
            }
        }
        
        if (currentChatId && !isLinkGenerated && !embedContext) {
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
                // Get current user ID to ensure ownership is recorded
                const profile = await userDB.getUserProfile();
                const currentUserId = profile?.user_id;

                // Update chat with is_shared = true and is_private = false
                await chatDB.updateChat({
                    ...chat,
                    is_shared: true,
                    is_private: false,
                    user_id: chat.user_id || currentUserId || undefined
                });
                console.debug('[SettingsShare] Marked chat as shared in IndexedDB:', chatId, 'user_id:', chat.user_id || currentUserId);
                
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
     * Mark embed as shared in IndexedDB
     * Updates is_shared = true and is_private = false
     */
    async function markEmbedAsShared(embedId: string) {
        if (!embedId) return;
        
        try {
            const { embedStore } = await import('../../../services/embedStore');
            const embed = await embedStore.get(`embed:${embedId}`);
            
            if (embed) {
                // Update embed with is_shared = true and is_private = false
                // We need to update the embed in IndexedDB via putEncrypted
                // But we need to get the current encrypted data first
                const contentRef = `embed:${embedId}`;
                
                // Get the raw entry to preserve encrypted fields
                const { chatDB } = await import('../../../services/db');
                const EMBEDS_STORE_NAME = 'embeds';
                const transaction = await chatDB.getTransaction([EMBEDS_STORE_NAME], 'readonly');
                const store = transaction.objectStore(EMBEDS_STORE_NAME);
                
                const entry = await new Promise<SyncEmbed | null>((resolve, reject) => {
                    const request = store.get(contentRef);
                    request.onsuccess = () => resolve(request.result);
                    request.onerror = () => reject(request.error);
                });
                
                if (entry) {
                    // Update the entry with new sharing status
                    entry.is_private = false;
                    entry.is_shared = true;
                    
                    // Store updated entry back
                    const writeTransaction = await chatDB.getTransaction([EMBEDS_STORE_NAME], 'readwrite');
                    const writeStore = writeTransaction.objectStore(EMBEDS_STORE_NAME);
                    await new Promise<void>((resolve, reject) => {
                        const request = writeStore.put(entry);
                        request.onsuccess = () => resolve();
                        request.onerror = () => reject(request.error);
                    });
                    
                    console.debug('[SettingsShare] Marked embed as shared in IndexedDB:', embedId);
                    
                    // Dispatch event to notify other components (e.g., SettingsShared)
                    window.dispatchEvent(new CustomEvent('embedShared', { detail: { embed_id: embedId } }));
                } else {
                    console.warn('[SettingsShare] Embed not found in IndexedDB for marking as shared:', embedId);
                }
            } else {
                console.warn('[SettingsShare] Embed not found for marking as shared:', embedId);
            }
        } catch (error) {
            console.error('[SettingsShare] Error marking embed as shared:', error);
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
            
            // Decrypt category
            let category: string | null = null;
            if (chat.encrypted_category) {
                category = await decryptWithChatKey(chat.encrypted_category, chatKey);
                if (!category) {
                    console.warn('[SettingsShare] Failed to decrypt category for metadata update');
                }
            }

            // Decrypt icon
            let icon: string | null = null;
            if (chat.encrypted_icon) {
                icon = await decryptWithChatKey(chat.encrypted_icon, chatKey);
                if (!icon) {
                    console.warn('[SettingsShare] Failed to decrypt icon for metadata update');
                }
            }

            // Decrypt follow-up suggestions
            let followUpSuggestions: string[] | null = null;
            if (chat.encrypted_follow_up_request_suggestions) {
                const decryptedFollowUps = await decryptWithChatKey(chat.encrypted_follow_up_request_suggestions, chatKey);
                if (decryptedFollowUps) {
                    try {
                        followUpSuggestions = JSON.parse(decryptedFollowUps);
                    } catch (e) {
                        console.warn('[SettingsShare] Failed to parse follow-up suggestions:', e);
                    }
                }
            }
            
            // If sharing with community, decrypt all messages and embeds locally
            // and send plaintext to server (zero-knowledge architecture)
            let decryptedMessages: Array<{role: string; content: string; category?: string; model_name?: string; created_at: number}> | null = null;
            let decryptedEmbeds: Array<{embed_id: string; type: string; content: string; created_at: number}> | null = null;
            
            if (shareWithCommunity && !isEmbedSharing) {
                try {
                    console.debug('[SettingsShare] Decrypting messages and embeds for community sharing...');
                    
                    // Import database services
                    const { getMessagesForChat } = await import('../../../services/db/messageOperations');
                    const { embedStore } = await import('../../../services/embedStore');
                    const { computeSHA256 } = await import('../../../message_parsing/utils');
                    
                    // Get all messages for this chat (already decrypted by getMessagesForChat)
                    // NOTE: message.content from DB has PLACEHOLDERS (e.g., "[EMAIL_1]")
                    const messages = await getMessagesForChat(chatDB as any, currentChatId);
                    if (messages && messages.length > 0) {
                        // Build cumulative PII mappings from user messages for restoration
                        const allPIIMappings: import('../../../types/chat').PIIMapping[] = [];
                        for (const msg of messages) {
                            if (msg.role === 'user' && msg.pii_mappings && msg.pii_mappings.length > 0) {
                                allPIIMappings.push(...msg.pii_mappings);
                            }
                        }

                        // Import restorePIIInText for when user opts to include sensitive data
                        const { restorePIIInText } = await import('../../../components/enter_message/services/piiDetectionService');

                        decryptedMessages = messages.map(msg => {
                            let content = msg.content || '';
                            // Content from DB has PLACEHOLDERS. When includeSensitiveData is ON,
                            // restore originals so the shared content shows actual personal data.
                            // When OFF (default), content keeps placeholders — no action needed.
                            if (includeSensitiveData && allPIIMappings.length > 0 && typeof content === 'string') {
                                content = restorePIIInText(content, allPIIMappings);
                            }
                            return {
                                role: msg.role,
                                content, // Content with placeholders (default) or originals (if includeSensitiveData)
                                category: msg.category,
                                model_name: msg.model_name,
                                created_at: msg.created_at
                            };
                        });
                        console.debug(`[SettingsShare] Decrypted ${decryptedMessages.length} messages for community sharing (includeSensitiveData: ${includeSensitiveData})`);
                    }
                    
                    // Get all embeds for this chat
                    const hashedChatId = await computeSHA256(currentChatId);
                    const embedEntries = await embedStore.getEmbedsByHashedChatId(hashedChatId);
                    
                    // VALIDATION: Extract embed references from message content and check for missing embeds
                    // CRITICAL: This prevents sharing chats with orphan embed references that would break demo chats
                    if (decryptedMessages && decryptedMessages.length > 0) {
                        const { extractEmbedReferences } = await import('../../../services/embedResolver');
                        const embedIdsInStore = new Set((embedEntries || []).map(e => e.embed_id));
                        const referencedEmbedIds = new Set<string>();

                        for (const msg of decryptedMessages) {
                            if (msg.content) {
                                const refs = extractEmbedReferences(msg.content);
                                for (const ref of refs) {
                                    referencedEmbedIds.add(ref.embed_id);
                                }
                            }
                        }

                        // Find embed references that are not in the store
                        const missingEmbedIds = [...referencedEmbedIds].filter(id => !embedIdsInStore.has(id));
                        if (missingEmbedIds.length > 0) {
                            // CRITICAL ERROR: Cannot share chat with orphan embed references
                            const errorMessage = `Sorry, we can't share this chat right now. Something went wrong while processing the embeds in your messages. Please use the "Report Issue" button to let us know about this problem so we can help fix it.`;
                            console.error('[SettingsShare] ❌ BLOCKED sharing due to missing embeds:', missingEmbedIds);

                            // Show user-facing error and block sharing
                            throw new Error(errorMessage);
                        }
                    }
                    
                    if (embedEntries && embedEntries.length > 0) {
                        decryptedEmbeds = [];
                        console.debug(`[SettingsShare] Found ${embedEntries.length} embeds for community sharing`);
                        
                        // Pre-load all embed keys into cache to avoid transaction issues during decryption
                        console.debug('[SettingsShare] Pre-loading embed keys into cache...');
                        for (const embedEntry of embedEntries) {
                            try {
                                const embedId = embedEntry.embed_id;
                                if (!embedId) continue;
                                
                                // Pre-cache the embed key - this will load it from IndexedDB once
                                await embedStore.getEmbedKey(embedId, embedEntry.hashed_chat_id);
                            } catch (keyError) {
                                console.warn(`[SettingsShare] Failed to pre-load key for embed ${embedEntry.embed_id}:`, keyError);
                            }
                        }
                        console.debug('[SettingsShare] Embed keys pre-loaded, now decrypting content...');
                        
                        // Now decrypt embed content (keys should be in cache now, avoiding repeated transactions)
                        for (let i = 0; i < embedEntries.length; i++) {
                            const embedEntry = embedEntries[i];
                            try {
                                const contentRef = `embed:${embedEntry.embed_id}`;
                                console.debug(`[SettingsShare] Decrypting embed ${i + 1}/${embedEntries.length}: ${embedEntry.embed_id}`);
                                const embedData = await embedStore.get(contentRef);
                                
                                if (embedData && embedData.content) {
                                    decryptedEmbeds.push({
                                        embed_id: embedEntry.embed_id || '',
                                        type: embedEntry.type || 'unknown',
                                        content: embedData.content || '',
                                        created_at: embedEntry.createdAt || Date.now()
                                    });
                                    console.debug(`[SettingsShare] ✅ Successfully decrypted embed: ${embedEntry.embed_id}`);
                                } else {
                                    console.warn(`[SettingsShare] ⚠️ Embed ${embedEntry.embed_id} has no content or failed to decrypt`);
                                }
                            } catch (embedError) {
                                console.error(`[SettingsShare] ❌ Failed to decrypt embed ${embedEntry.embed_id}:`, embedError);
                                // Continue with other embeds - don't fail the entire process
                            }
                        }
                        console.debug(`[SettingsShare] Successfully decrypted ${decryptedEmbeds.length}/${embedEntries.length} embeds for community sharing`);
                    }
                } catch (error) {
                    console.error('[SettingsShare] Error decrypting messages/embeds for community sharing:', error);
                    // Continue anyway - backend will handle missing data
                }
            }
            
            // Always send is_shared = true when sharing (even if no title/summary)
            // This ensures the server marks the chat as shared
            // Also send share_with_community flag and decrypted content if community sharing is enabled
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
                        category: category || null,
                        icon: icon || null,
                        follow_up_suggestions: followUpSuggestions || null,
                        is_shared: true,  // Mark chat as shared on server
                        share_with_community: shareWithCommunity && !isEmbedSharing ? true : undefined,  // Only for chats, not embeds
                        decrypted_messages: decryptedMessages || undefined,  // Plaintext messages for community sharing
                        decrypted_embeds: decryptedEmbeds || undefined  // Plaintext embeds for community sharing
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
            } catch (fetchError) {
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
     * Calculate QR code size based on viewport
     * Normal size: fits container, responsive but capped at reasonable max
     * Fullscreen size: large and easy to scan, uses most of viewport
     */
    function calculateQRSizes() {
        // Normal QR code size: responsive to viewport but capped
        // Use container width or viewport, whichever is smaller, with max 300px
        const containerMax = 300;
        const viewportBased = Math.min(viewportWidth * 0.4, viewportHeight * 0.3);
        qrCodeSize = Math.max(180, Math.min(containerMax, Math.floor(viewportBased)));
        
        // Fullscreen QR code size: very large and easy to scan
        // Use 90% of smaller viewport dimension, with higher cap for large screens
        const fullscreenMax = 1200; // Increased max for very large screens
        const fullscreenMin = 400;
        const viewportBasedFullscreen = Math.min(viewportWidth, viewportHeight) * 0.9;
        qrCodeFullscreenSize = Math.max(fullscreenMin, Math.min(fullscreenMax, Math.floor(viewportBasedFullscreen)));
        
        console.debug('[SettingsShare] Calculated QR sizes - normal:', qrCodeSize, 'fullscreen:', qrCodeFullscreenSize);
    }
    
    /**
     * Generate QR code SVG from the share link with specified size
     * Creates a QR code with black squares on white background
     * Uses fixed pixel dimensions for reliable rendering
     */
    function generateQRCode(link: string, size: number = qrCodeSize) {
        try {
            console.debug('[SettingsShare] Generating QR code for link:', link, 'size:', size);
            const qr = new QRCodeSVG({
                content: link,
                padding: 4,
                width: size,
                height: size,
                color: '#000000',
                background: '#ffffff',
                ecl: 'M' // Medium error correction level
            });
            // Keep width and height attributes - QR codes need fixed pixel values to render correctly
            const svgString = qr.svg();
            qrCodeSvg = svgString;
            console.debug('[SettingsShare] QR code generated successfully, SVG length:', svgString.length);
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

    /**
     * Update viewport dimensions and recalculate QR code sizes
     */
    function updateViewportDimensions() {
        viewportWidth = window.innerWidth;
        viewportHeight = window.innerHeight;
        calculateQRSizes();
    }
    
    /**
     * Show QR code in fullscreen overlay
     * Regenerates QR code at fullscreen size for better scanning
     */
    function showQRCodeFullscreen() {
        updateViewportDimensions();
        // Regenerate QR code at fullscreen size
        if (generatedLink) {
            generateQRCode(generatedLink, qrCodeFullscreenSize);
        }
        showQRFullscreen = true;
    }
    
    /**
     * Close QR code fullscreen overlay
     * Regenerates QR code at normal size
     */
    function closeQRCodeFullscreen() {
        showQRFullscreen = false;
        // Regenerate QR code at normal size when closing fullscreen
        if (generatedLink) {
            generateQRCode(generatedLink, qrCodeSize);
        }
    }
    
    /**
     * Track viewport dimensions and recalculate QR sizes on resize
     */
    $effect(() => {
        // Initialize viewport dimensions on mount
        updateViewportDimensions();
        
        // Listen for window resize
        const handleResize = () => {
            const oldSize = qrCodeSize;
            const oldFullscreenSize = qrCodeFullscreenSize;
            updateViewportDimensions();
            // Only regenerate if size actually changed
            if (generatedLink && !showQRFullscreen && qrCodeSize !== oldSize) {
                generateQRCode(generatedLink, qrCodeSize);
            } else if (generatedLink && showQRFullscreen && qrCodeFullscreenSize !== oldFullscreenSize) {
                generateQRCode(generatedLink, qrCodeFullscreenSize);
            }
        };
        
        window.addEventListener('resize', handleResize);
        
        return () => {
            window.removeEventListener('resize', handleResize);
        };
    });
    
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
        sharedChatId = null; // Clear shared chat ID when resetting
    }
    
    // Reset generated link when configuration changes (but only if we're in configuration step)
    $effect(() => {
        if (isConfigurationStep) {
            // Tracking dependencies
            void isPasswordProtected;
            void selectedDuration;
            void password;
            void shareWithCommunity;
            resetGeneratedState();
        }
    });
    
    // When Share with Community is enabled, disable password and time limit
    $effect(() => {
        if (shareWithCommunity && !isEmbedSharing) {
            // Disable password protection and time limit when sharing with community
            isPasswordProtected = false;
            password = '';
            selectedDuration = 0;
        }
    });
    
    // ===============================
    // Password Validation
    // ===============================
    
    // Password must be max 10 characters
    let isPasswordValid = $derived(!isPasswordProtected || (password.length > 0 && password.length <= 10));
    
    // When Share with Community is enabled, password and time limit are disabled
    let isPasswordDisabled = $derived(shareWithCommunity && !isEmbedSharing);
    let isTimeLimitDisabled = $derived(shareWithCommunity && !isEmbedSharing);
    
    // Can generate link if we have either a chat ID or an embed context
    let canGenerateLink = $derived((currentChatId || (isEmbedSharing && embedContext)) && isPasswordValid);
    
    // Display chat ID: use sharedChatId if link is generated (to keep it stable), otherwise use currentChatId
    // This ensures the displayed chat and QR code remain unchanged when user switches chats
    let displayChatId = $derived(isLinkGenerated ? sharedChatId : currentChatId);
    
    // Check if we have something to share (chat or embed)
    // Show content if:
    // 1. We have a chat ID (for chat sharing)
    // 2. We have embed context and are sharing an embed (for embed sharing)
    // 3. A link has already been generated (for both chats and embeds)
    let hasShareableContent = $derived.by(() => {
        const result = isLinkGenerated || // Link already generated - always show
            displayChatId || // Chat ID available
            (isEmbedSharing && embedContext && embedContext.embed_id); // Embed context available
        
        // Debug logging for embed sharing
        if (isEmbedSharing) {
            console.debug('[SettingsShare] hasShareableContent check:', {
                isLinkGenerated,
                displayChatId,
                isEmbedSharing,
                hasEmbedContext: !!embedContext,
                embedId: embedContext?.embed_id,
                result
            });
        }
        
        return result;
    });
</script>

<!-- No chat/embed selected message -->
{#if !hasShareableContent}
    <div class="no-chat-message" transition:fade={{ duration: 200 }}>
        <div class="icon settings_size shared"></div>
        <p>{$text('settings.share.no_chat_selected.text')}</p>
    </div>
{:else}
    <!-- Two-Step Flow: Configuration Step -->
    {#if isConfigurationStep}
        <!-- Info Display - Show what is being shared (chat or embed) -->
        <div class="chat-info-display" transition:fade={{ duration: 200 }}>
            {#if isEmbedSharing && embedContext}
                <!-- Embed Preview Display -->
                <div class="embed-preview">
                    <div class="embed-preview-header">
                        <span class="embed-preview-label">{$text('settings.share.sharing_embed.text', { default: 'Sharing:' })}</span>
                    </div>
                    <div class="embed-preview-content">
                        {#await embedPreviewData then previewResult}
                            {#if previewResult}
                                {@const Component = previewResult.component}
                                <Component {...previewResult.props} />
                            {:else}
                                <!-- Fallback to text if component not loaded -->
                                <div class="embed-info">
                                    <div class="embed-title">{embedContext.title || 'Embed'}</div>
                                    <div class="embed-type">{embedContext.type === 'video' ? 'Video' : embedContext.type === 'video-transcript' ? 'Video Transcript' : embedContext.type === 'website' ? 'Website' : embedContext.type || 'Embed'}</div>
                                    {#if embedContext.url}
                                        <div class="embed-url">{embedContext.url}</div>
                                    {/if}
                                </div>
                            {/if}
                        {:catch}
                            <!-- Error state -->
                            <div class="embed-info">
                                <div class="embed-title">{embedContext.title || 'Embed'}</div>
                                <div class="embed-type">{embedContext.type || 'Embed'}</div>
                            </div>
                        {/await}
                    </div>
                </div>
            {:else if currentChat && displayChatId}
                <!-- Chat Info Display -->
                <div class="chat-preview">
                    <div class="chat-preview-header">
                        <span class="chat-preview-label">{$text('settings.share.sharing_chat.text', { default: 'Sharing:' })}</span>
                    </div>
                    <ChatComponent
                        chat={currentChat}
                        activeChatId={displayChatId}
                        selectMode={false}
                        selectedChatIds={new Set()}
                    />
                </div>
            {/if}
        </div>

        <!-- Share description -->
        <div class="share-description" transition:fade={{ duration: 200 }}>
            <p>
                {#if isEmbedSharing}
                    {$text('settings.share.share_embed_description.text')}
                {:else}
                    {$text('settings.share.share_description.text')}
                {/if}
            </p>
        </div>
        <!-- Share Button (shown FIRST - triggers link generation) -->
        <button
            class="share-chat-button primary-action"
            onclick={generateLink}
            disabled={!canGenerateLink}
        >
            {#if isEmbedSharing}
                {$text('settings.share.share_embed.text')}
            {:else}
                {$text('settings.share.share_chat.text')}
            {/if}
        </button>

        <!-- Optional Share Settings Section -->
        <div class="share-options-section">
            <h3 class="section-title">{$text('settings.share.optional_settings.text', { default: 'Optional Settings' })}</h3>

            <!-- Share with Community Toggle (only for chats, not embeds) -->
            {#if !isEmbedSharing}
                <div class="option-row">
                    <div class="option-label">
                        <div class="icon settings_size shared"></div>
                        <span>{$text('settings.share.share_with_community.text', { default: 'Share with Community' })}</span>
                    </div>
                    <Toggle
                        bind:checked={shareWithCommunity}
                        name="share-with-community"
                        ariaLabel="Toggle share with community"
                    />
                </div>

                <!-- Share with Community Explainer -->
                {#if shareWithCommunity}
                    <div class="community-info" transition:slide={{ duration: 200, easing: cubicOut }}>
                        <div class="info-icon">ℹ️</div>
                        <p>
                            {$text('settings.share.share_with_community_info.text', { 
                                default: 'If you select "Share with Community", your chat might also be selected to be shown to other users on the platform, as well as on social media and at events.' 
                            })}
                        </p>
                    </div>
                {/if}
            {/if}

            <!-- Include Sensitive Data Toggle (only shown when chat has PII) -->
            {#if chatHasPII && !isEmbedSharing}
                <div class="option-row">
                    <div class="option-label">
                        <div class="icon settings_size {includeSensitiveData ? 'icon_visible' : 'icon_hidden'}"></div>
                        <span>{$text('settings.share.include_sensitive_data.text', { default: 'Include sensitive data' })}</span>
                    </div>
                    <Toggle
                        bind:checked={includeSensitiveData}
                        name="include-sensitive-data"
                        ariaLabel="Toggle include sensitive data"
                    />
                </div>

                <!-- Sensitive Data Warning (shown when toggle is ON) -->
                {#if includeSensitiveData}
                    <div class="community-info warning" transition:slide={{ duration: 200, easing: cubicOut }}>
                        <div class="info-icon">&#9888;&#65039;</div>
                        <p>
                            {$text('settings.share.include_sensitive_data_warning.text', { 
                                default: 'Your personal information (emails, phone numbers, etc.) will be included in the shared content. Only enable this if you trust all recipients.' 
                            })}
                        </p>
                    </div>
                {/if}
            {/if}

            <!-- Password Protection Toggle -->
            <div class="option-row" class:disabled={isPasswordDisabled}>
                <div class="option-label">
                    <div class="icon settings_size lock"></div>
                    <span>{$text('settings.share.password_protection.text')}</span>
                </div>
                <Toggle
                    bind:checked={isPasswordProtected}
                    name="password-protection"
                    ariaLabel="Toggle password protection"
                    disabled={isPasswordDisabled}
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
                    <p class="password-info">
                        {#if isEmbedSharing}
                            {$text('settings.share.password_required_info_embed.text')}
                        {:else}
                            {$text('settings.share.password_required_info.text')}
                        {/if}
                    </p>
                </div>
            {/if}

            <!-- Time Limit Selection -->
            <div class="option-row" class:disabled={isTimeLimitDisabled}>
                <div class="option-label">
                    <div class="icon settings_size time"></div>
                    <span>{$text('settings.share.time_limit.text')}</span>
                </div>
            </div>

            <!-- Duration Options -->
            <div class="duration-options" class:disabled={isTimeLimitDisabled}>
                {#each durationOptions as option}
                    <button
                        class="duration-option"
                        class:selected={selectedDuration === option.value}
                        class:disabled={isTimeLimitDisabled}
                        onclick={() => {
                            if (!isTimeLimitDisabled) {
                                selectedDuration = option.value;
                            }
                        }}
                        disabled={isTimeLimitDisabled}
                    >
                        {$text(option.labelKey)}
                    </button>
                {/each}
            </div>

            <!-- Expire Time Info -->
            <div class="expire-time-info">
                <div class="info-icon">⏱️</div>
                <p>
                    {#if isEmbedSharing}
                        {$text('settings.share.expire_time_info_embed.text')}
                    {:else}
                        {$text('settings.share.expire_time_info.text')}
                    {/if}
                </p>
            </div>

            <!-- Encryption Info -->
            <div class="encryption-info">
                <div class="info-icon">🔒</div>
                <p>
                    {#if isEmbedSharing}
                        {$text('settings.share.encryption_info_embed.text')}
                    {:else}
                        {$text('settings.share.encryption_info.text')}
                    {/if}
                </p>
            </div>
        </div>
    {:else}
    <!-- Two-Step Flow: Link Generation Step -->
    {#if isLinkGenerated}
        <!-- Info Display - Show what the link is for (chat or embed) -->
        <div class="chat-info-display link-step" transition:fade={{ duration: 200 }}>
            {#if isEmbedSharing && embedContext}
                <!-- Embed Preview Display -->
                <div class="embed-preview">
                    <div class="embed-preview-header">
                        <span class="embed-preview-label">{$text('settings.share.link_for_embed.text', { default: 'Link for:' })}</span>
                    </div>
                    <div class="embed-preview-content">
                        {#await embedPreviewData then previewResult}
                            {#if previewResult}
                                {@const Component = previewResult.component}
                                <Component {...previewResult.props} />
                            {:else}
                                <!-- Fallback to text if component not loaded -->
                                <div class="embed-info">
                                    <div class="embed-title">{embedContext.title || 'Embed'}</div>
                                    <div class="embed-type">{embedContext.type === 'video' ? 'Video' : embedContext.type === 'video-transcript' ? 'Video Transcript' : embedContext.type === 'website' ? 'Website' : embedContext.type || 'Embed'}</div>
                                    {#if embedContext.url}
                                        <div class="embed-url">{embedContext.url}</div>
                                    {/if}
                                </div>
                            {/if}
                        {:catch}
                            <!-- Error state -->
                            <div class="embed-info">
                                <div class="embed-title">{embedContext.title || 'Embed'}</div>
                                <div class="embed-type">{embedContext.type || 'Embed'}</div>
                            </div>
                        {/await}
                    </div>
                </div>
            {:else if currentChat && displayChatId}
                <!-- Chat Info Display -->
                <div class="chat-preview">
                    <div class="chat-preview-header">
                        <span class="chat-preview-label">{$text('settings.share.link_for_chat.text', { default: 'Link for:' })}</span>
                    </div>
                    <ChatComponent
                        chat={currentChat}
                        activeChatId={displayChatId}
                        selectMode={false}
                        selectedChatIds={new Set()}
                    />
                </div>
            {/if}
        </div>

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
                <button
                    class="qr-code-container clickable"
                    onclick={showQRCodeFullscreen}
                    aria-label="Show QR code fullscreen"
                    title="Click to enlarge QR code"
                >
                    {#if qrCodeSvg}
                        {@html qrCodeSvg}
                    {:else}
                        <div class="qr-code-placeholder">Generating QR code...</div>
                    {/if}
                </button>
                <p class="qr-code-instruction">{$text('settings.share.click_to_enlarge_qr.text', { default: 'Click QR code to enlarge' })}</p>
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

<!-- QR Code Fullscreen Overlay - Simple white fullscreen with centered QR code -->
{#if showQRFullscreen && qrCodeSvg}
    <div
        class="qr-fullscreen-overlay"
        use:portal
        role="dialog"
        aria-modal="true"
        aria-label="QR Code Fullscreen"
        onclick={closeQRCodeFullscreen}
        onkeydown={(e) => {
            if (e.key === 'Escape') {
                closeQRCodeFullscreen();
            }
        }}
        tabindex="-1"
        transition:fade={{ duration: 200 }}
    >
        <!-- Centered QR Code - Uses full viewport with 20px padding, maintaining aspect ratio -->
        <div class="qr-large-container">
            {#if qrCodeSvg}
                {@html qrCodeSvg}
            {/if}
        </div>
    </div>
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
    
    .option-row.disabled {
        opacity: 0.5;
        pointer-events: none;
    }
    
    .duration-options.disabled {
        opacity: 0.5;
        pointer-events: none;
    }
    
    .duration-option.disabled {
        cursor: not-allowed;
        opacity: 0.5;
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
    
    /* Chat info display */
    .chat-info-display {
        margin-bottom: 16px;
        padding: 16px;
        background-color: var(--color-grey-5);
        border-radius: 8px;
        border: 1px solid var(--color-grey-20);
    }

    .chat-info-display.link-step {
        margin-bottom: 8px;
    }

    .chat-preview {
        width: 100%;
    }

    .chat-preview-header {
        margin-bottom: 8px;
    }

    .chat-preview-label {
        font-size: 12px;
        color: var(--color-grey-60);
        font-weight: 500;
        text-transform: uppercase;
        letter-spacing: 0.5px;
    }

    /* Share chat button (configuration step) */
    .share-chat-button {
        width: calc(100% - 40px);
        margin: 20px 20px;
        margin-bottom: 20px;
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
    
    /* Community share info */
    .community-info {
        display: flex;
        align-items: flex-start;
        gap: 10px;
        padding: 12px 16px;
        background-color: var(--color-grey-5);
        border-radius: 8px;
        border: 1px solid var(--color-grey-20);
        margin-top: 8px;
    }
    
    .community-info .info-icon {
        font-size: 16px;
        line-height: 1;
    }
    
    .community-info p {
        font-size: 12px;
        color: var(--color-grey-70);
        margin: 0;
        line-height: 1.4;
    }

    .community-info.warning {
        background-color: rgba(250, 204, 21, 0.1);
        border-color: rgba(250, 204, 21, 0.3);
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
        border: none;
        cursor: default;
        width: auto;
        display: inline-block;
        height: auto;
    }

    .qr-code-container.clickable {
        cursor: pointer;
        transition: transform 0.2s ease, box-shadow 0.2s ease;
    }

    .qr-code-container.clickable:hover {
        transform: scale(1.02);
        box-shadow: 0 4px 12px rgba(0, 0, 0, 0.15);
    }

    /* QR code SVG - uses fixed pixel dimensions from SVG attributes */
    .qr-code-container :global(svg) {
        display: block;
        /* SVG has width/height attributes set during generation - don't override */
        visibility: visible;
        opacity: 1;
    }

    .qr-code-placeholder {
        width: 180px;
        height: 180px;
        display: flex;
        align-items: center;
        justify-content: center;
        color: var(--color-grey-60);
        font-size: 12px;
    }
    
    .qr-code-instruction {
        font-size: 12px;
        color: var(--color-grey-60);
        margin: 16px 0 0 0;
        text-align: center;
    }

    /* QR Code Fullscreen Overlay - Simple white fullscreen */
    /* Use very high z-index to ensure it appears above settings panel and all other UI elements */
    .qr-fullscreen-overlay {
        position: fixed;
        top: 0;
        left: 0;
        right: 0;
        bottom: 0;
        background-color: white;
        z-index: 9999;
        display: flex;
        align-items: center;
        justify-content: center;
        padding: 20px;
        box-sizing: border-box;
        cursor: pointer;
    }

    /* QR code container - centered, uses full available space with 20px padding, maintains aspect ratio */
    .qr-large-container {
        display: flex;
        align-items: center;
        justify-content: center;
        width: 100%;
        height: 100%;
        max-width: 100%;
        max-height: 100%;
        box-sizing: border-box;
    }

    /* Fullscreen QR code - uses fixed pixel dimensions from SVG (calculated based on viewport) */
    .qr-large-container :global(svg) {
        display: block;
        /* SVG has width/height attributes set during generation at fullscreen size - don't override */
        visibility: visible;
        opacity: 1;
    }

    /* Embed Preview Styles */
    .embed-preview {
        padding: 12px;
        background-color: var(--color-grey-10);
        border-radius: 8px;
        border: 1px solid var(--color-grey-20);
    }

    .embed-preview-header {
        margin-bottom: 8px;
    }

    .embed-preview-label {
        font-size: 12px;
        font-weight: 500;
        color: var(--color-grey-80);
        text-transform: uppercase;
        letter-spacing: 0.5px;
    }

    .embed-info {
        display: flex;
        flex-direction: column;
        gap: 4px;
    }

    .embed-title {
        font-size: 14px;
        font-weight: 600;
        color: var(--color-grey-100);
        line-height: 1.3;
    }

    .embed-type {
        font-size: 12px;
        font-weight: 500;
        color: var(--color-button-primary);
        text-transform: uppercase;
        letter-spacing: 0.5px;
    }

    .embed-url {
        font-size: 12px;
        color: var(--color-grey-70);
        font-family: monospace;
        word-break: break-all;
        line-height: 1.3;
    }
</style>