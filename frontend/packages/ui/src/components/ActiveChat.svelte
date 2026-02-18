<script lang="ts">
    import MessageInput from './enter_message/MessageInput.svelte';
    import CodeFullscreen from './fullscreen_previews/CodeFullscreen.svelte';
    import ChatHistory from './ChatHistory.svelte';
    import NewChatSuggestions from './NewChatSuggestions.svelte';
    import FollowUpSuggestions from './FollowUpSuggestions.svelte';
    // AppSettingsMemoriesPermissionDialog is now rendered inside ChatHistory.svelte
    // so it scrolls with the messages instead of being fixed at the bottom
    import { isMobileView, loginInterfaceOpen } from '../stores/uiStateStore';
    import Login from './Login.svelte';
    import { text } from '@repo/ui';
    import { fade, fly } from 'svelte/transition';
    import { createEventDispatcher, tick, onMount, onDestroy } from 'svelte'; // Added onDestroy
    import { authStore, logout } from '../stores/authStore'; // Import logout action
    import { panelState } from '../stores/panelStateStore'; // Added import
    import type { Chat, Message as ChatMessageModel, TiptapJSON, MessageStatus, AITaskInitiatedPayload, ProcessingPhase, PreprocessorStepResult } from '../types/chat'; // Added Message, TiptapJSON, MessageStatus, AITaskInitiatedPayload, ProcessingPhase, PreprocessorStepResult
    import { tooltip } from '../actions/tooltip';
    import { chatDB } from '../services/db';
    import { chatSyncService } from '../services/chatSyncService'; // Import chatSyncService
    import { skillPreviewService } from '../services/skillPreviewService'; // Import skillPreviewService
    import KeyboardShortcuts from './KeyboardShortcuts.svelte';
    import WebSearchEmbedPreview from './embeds/web/WebSearchEmbedPreview.svelte';
    import WebSearchEmbedFullscreen from './embeds/web/WebSearchEmbedFullscreen.svelte';
    import NewsSearchEmbedFullscreen from './embeds/news/NewsSearchEmbedFullscreen.svelte';
    import VideosSearchEmbedFullscreen from './embeds/videos/VideosSearchEmbedFullscreen.svelte';
    import MapsSearchEmbedFullscreen from './embeds/maps/MapsSearchEmbedFullscreen.svelte';
    import CodeEmbedFullscreen from './embeds/code/CodeEmbedFullscreen.svelte';
    import DocsEmbedFullscreen from './embeds/docs/DocsEmbedFullscreen.svelte';
    import SheetEmbedFullscreen from './embeds/sheets/SheetEmbedFullscreen.svelte';
    import VideoTranscriptEmbedPreview from './embeds/videos/VideoTranscriptEmbedPreview.svelte';
    import VideoTranscriptEmbedFullscreen from './embeds/videos/VideoTranscriptEmbedFullscreen.svelte';
    import WebReadEmbedFullscreen from './embeds/web/WebReadEmbedFullscreen.svelte';
    import WebsiteEmbedFullscreen from './embeds/web/WebsiteEmbedFullscreen.svelte';
    import ReminderEmbedFullscreen from './embeds/reminder/ReminderEmbedFullscreen.svelte';
    import TravelSearchEmbedFullscreen from './embeds/travel/TravelSearchEmbedFullscreen.svelte';
    import TravelPriceCalendarEmbedFullscreen from './embeds/travel/TravelPriceCalendarEmbedFullscreen.svelte';
    import TravelStaysEmbedFullscreen from './embeds/travel/TravelStaysEmbedFullscreen.svelte';
    import ImageGenerateEmbedFullscreen from './embeds/images/ImageGenerateEmbedFullscreen.svelte';
    import UploadedImageFullscreen from './embeds/images/UploadedImageFullscreen.svelte';
    import FocusModeContextMenu from './embeds/FocusModeContextMenu.svelte';
    import { userProfile } from '../stores/userProfile';
    import { 
        isInSignupProcess, 
        currentSignupStep, 
        getStepFromPath, 
        isLoggingOut, 
        isSignupPath,
        STEP_ALPHA_DISCLAIMER,
        STEP_BASICS,
        STEP_CONFIRM_EMAIL,
        STEP_SECURE_ACCOUNT,
        STEP_PASSWORD,
        STEP_ONE_TIME_CODES,
        STEP_BACKUP_CODES,
        STEP_RECOVERY_KEY,
        STEP_TFA_APP_REMINDER,
        STEP_CREDITS,
        STEP_PAYMENT,
        STEP_AUTO_TOP_UP
        // Note: STEP_COMPLETION is not imported as it's not a visible step - users go directly to the app after auto top-up
    } from '../stores/signupState';
    import { signupStore } from '../stores/signupStore';
    import SignupStatusbar from './signup/SignupStatusbar.svelte';
    import { userDB } from '../services/userDB';
    import { initializeApp } from '../app';
    import { aiTypingStore, type AITypingStatus } from '../stores/aiTypingStore'; // Import the new store
    import { decryptWithMasterKey } from '../services/cryptoService'; // Import decryption function
    import { getModelDisplayName } from '../utils/modelDisplayName'; // For clean model name display
    import { parse_message } from '../message_parsing/parse_message'; // Import markdown parser
    import { loadSessionStorageDraft, getSessionStorageDraftMarkdown, migrateSessionStorageDraftsToIndexedDB, getAllDraftChatIdsWithDrafts } from '../services/drafts/sessionStorageDraftService'; // Import sessionStorage draft service
    import { draftEditorUIState } from '../services/drafts/draftState'; // Import draft state
    import { phasedSyncState, NEW_CHAT_SENTINEL } from '../stores/phasedSyncStateStore'; // Import phased sync state store and sentinel value
    import { websocketStatus } from '../stores/websocketStatusStore'; // Import WebSocket status for connection checks
    import { activeChatStore, deepLinkProcessing } from '../stores/activeChatStore'; // For clearing persistent active chat selection
    import { activeEmbedStore } from '../stores/activeEmbedStore'; // For managing embed URL hash
    import { settingsDeepLink } from '../stores/settingsDeepLinkStore'; // For opening settings to specific page (share)
    import { settingsMenuVisible } from '../components/Settings.svelte'; // Import settingsMenuVisible store to control Settings visibility
    import { videoIframeStore } from '../stores/videoIframeStore'; // For standalone VideoIframe component with CSS-based PiP
    import { DEMO_CHATS, LEGAL_CHATS, getDemoMessages, isPublicChat, translateDemoChat } from '../demo_chats'; // Import demo chat utilities
    import { convertDemoChatToChat } from '../demo_chats/convertToChat'; // Import conversion function
    import { incognitoChatService } from '../services/incognitoChatService'; // Import incognito chat service
    import { incognitoMode } from '../stores/incognitoModeStore'; // Import incognito mode store
    import { piiVisibilityStore } from '../stores/piiVisibilityStore'; // Import PII visibility store for hide/unhide toggle
    import { setEmbedPIIState, resetEmbedPIIState } from '../stores/embedPIIStore'; // Update embed PII state for preview/fullscreen components
    import type { PIIMapping } from '../types/chat'; // PII mapping type
    import { isDesktop } from '../utils/platform'; // Import desktop detection for conditional auto-focus
    import { getCategoryGradientColors, getValidIconName, getLucideIcon } from '../utils/categoryUtils'; // For resume card category gradient circle
    import { waitLocale } from 'svelte-i18n'; // Import waitLocale for waiting for translations to load
    import { get } from 'svelte/store'; // Import get to read store values
    import { extractEmbedReferences } from '../services/embedResolver'; // Import for embed navigation
    import { tipTapToCanonicalMarkdown } from '../message_parsing/serializers'; // Import for embed navigation
    import PushNotificationBanner from './PushNotificationBanner.svelte'; // Import push notification banner component
    import { shouldShowPushBanner } from '../stores/pushNotificationStore'; // Import push notification store for banner visibility
    import { chatListCache } from '../services/chatListCache'; // For invalidating stale 'sending' status in sidebar cache
    import type { 
        WebSearchSkillPreviewData,
        VideoTranscriptSkillPreviewData,
        VideoTranscriptResult,
        CodeGetDocsSkillPreviewData,
        CodeGetDocsResult
    } from '../types/appSkills';
    import type { EmbedStoreEntry } from '../message_parsing/types';
    
    // Lightweight type aliases to keep complex event payloads and component refs explicit.
    type EventListenerCallback = (event: Event) => void;
    type UserProfileRecord = { user_id?: string | null };
    type HiddenChatFlag = { is_hidden?: boolean | null };

    type ChatHistoryRef = {
        updateMessages: (messages: ChatMessageModel[]) => void;
        scrollToTop: () => void;
        scrollToBottom: (smooth?: boolean) => void;
        restoreScrollPosition: (messageId: string) => void;
    };

    type MessageInputFieldRef = {
        setDraftContent: (chatId: string | undefined, content: TiptapJSON | string | null, version: number, isRemote: boolean) => void;
        setSuggestionText: (text: string) => void;
        setOriginalMarkdown?: (markdown: string) => void;
        focus: () => void;
        getTextContent: () => string;
        clearMessageField: (shouldSaveDraft: boolean, preserveContext?: boolean) => Promise<void>;
    };

    type EmbedResolverData = {
        embed_id: string;
        type: string;
        status: 'processing' | 'finished' | 'error' | 'cancelled';
        content: string;
        text_preview?: string;
        embed_ids?: string[];
        file_path?: string;
        createdAt: number;
        updatedAt: number;
    };

    type EmbedDataRecord = EmbedStoreEntry | EmbedResolverData | Partial<EmbedResolverData>;

    type EmbedDecodedContent = Record<string, unknown> & {
        app_id?: string;
        skill_id?: string;
        query?: string;
        provider?: string;
        url?: string;
        title?: string;
        description?: string;
        meta_url_favicon?: string;
        favicon?: string;
        thumbnail_original?: string;
        image?: string;
        extra_snippets?: string | string[];
        page_age?: string;
        code?: string;
        language?: string;
        filename?: string;
        lineCount?: number;
        video_id?: string;
        videoId?: string;
        channel_name?: string;
        channel_id?: string;
        thumbnail?: string;
        duration_seconds?: number;
        duration_formatted?: string;
        view_count?: number;
        like_count?: number;
        published_at?: string;
        embed_ids?: string[] | string;
        results?: unknown[];
        original_metadata?: { url?: string };
        video_count?: number;
        success_count?: number;
        failed_count?: number;
        library?: string;
    };

    type EmbedFullscreenState = {
        embedId?: string | null;
        embedData?: EmbedDataRecord | null;
        decodedContent?: EmbedDecodedContent | null;
        embedType?: string | null;
        attrs?: Record<string, unknown> & {
            url?: string;
            title?: string;
            description?: string;
            favicon?: string;
            image?: string;
            code?: string;
            language?: string;
            filename?: string;
            lineCount?: number;
            videoId?: string;
        };
        restoreFromPip?: boolean;
    } | null;

    type EmbedFullscreenEventDetail = {
        embedId?: string | null;
        embedData?: EmbedDataRecord | null;
        decodedContent?: EmbedDecodedContent | null;
        embedType?: string | null;
        attrs?: Record<string, unknown> & {
            url?: string;
            title?: string;
            description?: string;
            favicon?: string;
            image?: string;
        };
    };

    type AiMessageChunkPayload = {
        sequence: number;
        chat_id: string;
        message_id: string;
        user_message_id?: string | null;
        full_content_so_far?: string | null;
        is_final_chunk?: boolean;
        category?: string;
        model_name?: string;
        rejection_reason?: string | null; // e.g., "insufficient_credits" - indicates system message, not AI response
    };

    type ChatUpdatedDetail = {
        chat_id?: string;
        chat?: Chat;
        messages?: ChatMessageModel[];
        newMessage?: ChatMessageModel;
        type?: string;
        messagesUpdated?: boolean;
    };

    type SkillPreviewData = WebSearchSkillPreviewData | VideoTranscriptSkillPreviewData;

    type SkillPreviewDetail = {
        task_id: string;
        previewData: SkillPreviewData;
        chat_id: string;
        message_id: string;
    };

    // Minimal result shapes for fullscreen embed components (mirrors local interfaces there).
    type WebSearchResult = {
        embed_id: string;
        url: string;
        title?: string;
        favicon_url?: string;
        preview_image_url?: string;
        snippet?: string;
        description?: string;
        extra_snippets?: string | string[];
        page_age?: string;
    };

    type NewsSearchResult = {
        embed_id: string;
        url: string;
        title?: string;
        favicon_url?: string;
        thumbnail?: string;
        description?: string;
    };

    type VideoSearchResult = {
        embed_id: string;
        url: string;
        title?: string;
        description?: string;
        channel_title?: string;
        channel_id?: string;
        thumbnail_url?: string;
        view_count?: number;
        duration?: string;
    };

    type PlaceSearchResult = {
        embed_id: string;
        displayName?: string;
        formattedAddress?: string;
        location?: { latitude?: number; longitude?: number };
        rating?: number;
        userRatingCount?: number;
        websiteUri?: string;
        placeId?: string;
    };

    type WebReadResult = {
        type: string;
        url: string;
        title?: string;
        markdown?: string;
        language?: string;
        favicon?: string;
        og_image?: string;
        og_sitename?: string;
        hash?: string;
    };

    type WebReadPreviewData = {
        app_id: 'web';
        skill_id: 'read';
        status: WebSearchSkillPreviewData['status'];
        results: WebReadResult[];
        url?: string;
    };

    type TravelConnectionResult = {
        embed_id: string;
        type?: string;
        transport_method?: string;
        trip_type?: string;
        total_price?: string;
        currency?: string;
        bookable_seats?: number;
        last_ticketing_date?: string;
        origin?: string;
        destination?: string;
        departure?: string;
        arrival?: string;
        duration?: string;
        stops?: number;
        carriers?: string[];
        hash?: string;
    };

    type AppCardEntry = {
        component: typeof WebSearchEmbedPreview | typeof VideoTranscriptEmbedPreview;
        props: {
            id: string;
            previewData: SkillPreviewData;
            isMobile: boolean;
            onFullscreen: () => void;
        };
    };

    type MessageWithAppCards = ChatMessageModel & { appCards?: AppCardEntry[] };
    /** Extended message type with transient embed metadata (not persisted, used for UI state) */
    type MessageWithEmbedMeta = ChatMessageModel & { _embedErrors?: Set<string> };

    const dispatch = createEventDispatcher();
    
    // Step sequences for signup status bar (must match Signup.svelte)
    // Note: STEP_COMPLETION is not included as it's not a visible step - users go directly to the app after auto top-up
    const fullStepSequence = [
        STEP_ALPHA_DISCLAIMER, STEP_BASICS, STEP_CONFIRM_EMAIL, STEP_SECURE_ACCOUNT, STEP_PASSWORD,
        STEP_ONE_TIME_CODES, STEP_TFA_APP_REMINDER, STEP_BACKUP_CODES, STEP_RECOVERY_KEY,
        STEP_CREDITS, STEP_PAYMENT, STEP_AUTO_TOP_UP
    ];

    const passkeyStepSequence = [
        STEP_ALPHA_DISCLAIMER, STEP_BASICS, STEP_CONFIRM_EMAIL, STEP_SECURE_ACCOUNT, STEP_RECOVERY_KEY,
        STEP_CREDITS, STEP_PAYMENT, STEP_AUTO_TOP_UP
    ];

    // State for payment enabled status (fetched from server)
    let paymentEnabled = $state(true); // Default to enabled for backward compatibility
    let isSelfHosted = $state(false); // Self-hosted status from request-based validation

    // Derive step sequence based on login method and payment status (same logic as Signup.svelte)
    // Default to passkey sequence (assume passkey by default)
    // Only use full sequence when user explicitly selects password + 2FA OTP
    let stepSequence = $derived.by(() => {
        const baseSequence = $signupStore.loginMethod === 'password' ? fullStepSequence : passkeyStepSequence;
        // Filter out email confirmation and payment steps if self-hosted (use isSelfHosted from request-based validation)
        if (isSelfHosted) {
            return baseSequence.filter(step => ![STEP_CONFIRM_EMAIL, STEP_CREDITS, STEP_PAYMENT, STEP_AUTO_TOP_UP].includes(step));
        }
        return baseSequence;
    });

    // Fade transition parameters for status bar
    const fadeParams = {
        duration: 600
    };
    
    // Get username from the store using Svelte 5 $derived
    // Use empty string for non-authenticated users - translation will handle "Hey there!" vs "Hey {username}!"
    let username = $derived($userProfile.username || '');

    // Split translation strings that include <br> into safe text parts for rendering.
    function splitHtmlLineBreaks(text: string): string[] {
        return text.split(/<br\s*\/?>/gi);
    }

    // Pre-split welcome copy to avoid {@html} and keep translations XSS-safe.
    let welcomeHeadingParts = $derived.by(() => {
        const rawHeading = username
            ? $text('chat.welcome.hey_user').replace('{username}', username)
            : $text('chat.welcome.hey_guest');
        return splitHtmlLineBreaks(rawHeading);
    });

    let welcomePromptParts = $derived.by(() => {
        return splitHtmlLineBreaks($text('chat.welcome.what_do_you_need_help_with'));
    });
    
    // State for current user ID (cached to avoid repeated DB lookups)
    let currentUserId = $state<string | null>(null);
    
    // State for chat ownership check
    let chatOwnershipResolved = $state<boolean>(true); // Default to true (allow editing)
    
    /**
     * Check if the current user owns the chat.
     * For shared chats, if user_id is set and doesn't match current user, it's read-only.
     * If user_id is not set, assume the user owns it (backwards compatibility).
     */
    async function checkChatOwnership() {
        if (!currentChat || !$authStore.isAuthenticated) {
            // Non-authenticated users can always edit (demo chats)
            // No chat loaded means welcome screen
            chatOwnershipResolved = true;
            return;
        }
        
        // If chat has no user_id, assume it's owned (backwards compatibility)
        if (!currentChat.user_id) {
            chatOwnershipResolved = true;
            return;
        }
        
        // Get current user ID (cache it to avoid repeated DB lookups)
        if (!currentUserId) {
            try {
                const profile = await userDB.getUserProfile();
                currentUserId = (profile as UserProfileRecord | null)?.user_id || null;
            } catch (error) {
                console.warn('[ActiveChat] Error getting user_id from profile:', error);
                // Fail open for UX - allow editing if we can't determine ownership
                chatOwnershipResolved = true;
                return;
            }
        }
        
        if (!currentUserId) {
            // Can't determine ownership, default to allowing (fail open for UX)
            chatOwnershipResolved = true;
            return;
        }
        
        // Compare chat's user_id with current user's user_id
        const isOwned = currentChat.user_id === currentUserId;
        chatOwnershipResolved = isOwned;
        console.debug(`[ActiveChat] Chat ownership check: ${isOwned} for chat ${currentChat.chat_id} (chat.user_id: ${currentChat.user_id}, currentUserId: ${currentUserId})`);
    }
    
    // Check ownership whenever chat or auth state changes
    $effect(() => {
        // Track dependencies
        void currentChat?.chat_id;
        void currentChat?.user_id;
        void $authStore.isAuthenticated;
        
        // Check ownership asynchronously
        checkChatOwnership();
    });

    // Add state for code fullscreen using $state
    let showCodeFullscreen = $state(false);
    let fullscreenCodeData = $state({
        code: '',
        filename: '',
        language: '',
        lineCount: 0
    });

    // Uploaded image fullscreen — triggered by clicking an in-editor upload embed
    let showUploadedImageFullscreen = $state(false);
    let uploadedImageFullscreenData = $state<{
        src?: string;
        filename?: string;
        s3Files?: Record<string, { s3_key: string; width: number; height: number; size_bytes: number; format: string }>;
        s3BaseUrl?: string;
        aesKey?: string;
        aesNonce?: string;
        isAuthenticated?: boolean;
        fileSize?: number;
        fileType?: string;
    }>({});

    // Note: isLoggingOutFromSignup state removed as it was set but never read

    async function handleLoginSuccess(event) {
        const { user, inSignupFlow } = event.detail;
        console.debug("Login success, in signup flow:", inSignupFlow);
        
        // CRITICAL: Set signup state BEFORE updating auth state
        // This ensures signup state is preserved and login interface stays open
        if (inSignupFlow && user?.last_opened) {
            const { currentSignupStep, isInSignupProcess, getStepFromPath } = await import('../stores/signupState');
            const step = getStepFromPath(user.last_opened);
            currentSignupStep.set(step);
            isInSignupProcess.set(true);
            // Ensure login interface is open to show signup flow
            const { loginInterfaceOpen } = await import('../stores/uiStateStore');
            loginInterfaceOpen.set(true);
            console.debug('[ActiveChat] Set signup state after login:', step);
        }
        
        // Update the authentication state after successful login
        const { setAuthenticatedState } = await import('../stores/authSessionActions');
        setAuthenticatedState();
        console.debug("Authentication state updated after login success");
        
        // CRITICAL: Migrate sessionStorage drafts to IndexedDB after successful login/signup
        // This ensures drafts created while not authenticated are properly encrypted and stored
        try {
            const { encryptWithMasterKey } = await import('../services/cryptoService');
            await migrateSessionStorageDraftsToIndexedDB(chatDB, encryptWithMasterKey);
            console.debug('[ActiveChat] SessionStorage drafts migrated to IndexedDB after login');
        } catch (error) {
            console.error('[ActiveChat] Error migrating sessionStorage drafts to IndexedDB:', error);
            // Don't block login if migration fails - drafts will be lost but user can continue
        }
        
        // CRITICAL: Check for pending deep link after successful login
        // This handles cases where user opened a deep link (e.g., settings) while not authenticated
        // The deep link was stored in sessionStorage and should be processed now
        try {
            const pendingDeepLink = sessionStorage.getItem('pendingDeepLink');
            if (pendingDeepLink) {
                console.debug(`[ActiveChat] Found pending deep link after login: ${pendingDeepLink}`);
                // Remove the pending deep link from sessionStorage
                sessionStorage.removeItem('pendingDeepLink');
                
                // Process the deep link by dispatching a custom event that +page.svelte can listen to
                // This ensures the deep link is processed after auth state is fully updated
                // Use a small delay to ensure auth state propagation is complete
                setTimeout(() => {
                    console.debug(`[ActiveChat] Processing pending deep link: ${pendingDeepLink}`);
                    window.dispatchEvent(new CustomEvent('processPendingDeepLink', {
                        detail: { hash: pendingDeepLink }
                    }));
                }, 100);
            }
        } catch (error) {
            console.warn('[ActiveChat] Error checking for pending deep link:', error);
            // Don't block login if deep link processing fails
        }
    }

    // Modify handleLogout to track signup state and reset signup step
    async function handleLogout() {
        isLoggingOut.set(true);
        
        // Reset signup step to 1
        currentSignupStep.set("basics");
        
        try {
            await logout(); // Call the imported logout action directly
        } catch (error) {
            console.error('Error during logout:', error);
            logout(); // Call the imported logout action directly
        }
        
        // After logout, load default welcome chat (even if user previously deleted/hid it)
        // This ensures users see the welcome chat after logging out
        setTimeout(() => {
            console.debug("[ActiveChat] After logout - loading default welcome chat");
            const welcomeDemo = DEMO_CHATS.find(chat => chat.chat_id === 'demo-for-everyone');
            if (welcomeDemo) {
                // Translate the demo chat to the user's locale
                const translatedWelcomeDemo = translateDemoChat(welcomeDemo);
                const welcomeChat = convertDemoChatToChat(translatedWelcomeDemo);
                
                // Check if deep link processing is happening
                if (get(deepLinkProcessing)) {
                    console.debug("[ActiveChat] Skipping welcome chat after logout - deep link processing in progress");
                    return;
                }

                // Clear current chat and load welcome chat
                currentChat = null;
                currentMessages = [];
                activeChatStore.setActiveChat('demo-for-everyone');
                loadChat(welcomeChat);
                console.debug("[ActiveChat] ✅ Default welcome chat loaded after logout");
            }
        }, 100);
        
        // Keep the flags active for a moment to prevent UI flash
        setTimeout(() => {
            isLoggingOut.set(false);
        }, 500);
    }

    // Fix the reactive statement to properly handle logout during signup using Svelte 5 $derived
    // CHANGED: Always show chat interface - non-authenticated users see demo chats, authenticated users see real chats
    // The login/signup flow is now in the Settings panel instead of replacing the entire chat interface
    // Also handle manual login interface toggle from header button
    // Use the global store to track login interface visibility (shared with Header.svelte)
    let showChat = $derived(!$isInSignupProcess && !$loginInterfaceOpen);

    // Reset the flags when auth state changes using Svelte 5 $effect
    $effect(() => {
        if (!$authStore.isAuthenticated) {
            // Clear video iframe state on logout
            videoIframeStore.clear();
            
            // CRITICAL: Backup handler for logout - ensures demo chat loads even if userLoggingOut event wasn't caught
            // This is especially important on mobile where event timing might be off
            // Only trigger if we have a current chat that's not a demo chat (user was logged in)
            // CRITICAL: Don't clear shared chats - they're valid for non-auth users
            // CRITICAL: Skip this entirely during initial deep link processing - the user is loading
            // a draft or specific chat from the URL, not logging out. This effect was incorrectly
            // firing when currentChat changed from null to the draft chat, causing demo-for-everyone
            // to overwrite the draft immediately after it loaded.
            if (get(deepLinkProcessing)) {
                console.debug('[ActiveChat] Skipping auth state effect - deep link processing in progress');
                return;
            }
            
            if (currentChat && !isPublicChat(currentChat.chat_id)) {
                // Check if this is a shared chat (has chat key in cache or is in sessionStorage shared_chats)
                // chatDB.getChatKey is synchronous, so we can check immediately
                const chatKey = chatDB.getChatKey(currentChat.chat_id);
                const sharedChatIds = typeof sessionStorage !== 'undefined' 
                    ? JSON.parse(sessionStorage.getItem('shared_chats') || '[]')
                    : [];
                const isSharedChat = chatKey !== null || sharedChatIds.includes(currentChat.chat_id);
                
                // CRITICAL: Also check if this is a sessionStorage draft chat (non-auth user's unsaved work)
                // Draft chats are valid for non-authenticated users and should NOT be overwritten with demo-for-everyone
                const isSessionStorageDraft = loadSessionStorageDraft(currentChat.chat_id) !== null;
                
                if (isSessionStorageDraft && !$isLoggingOut) {
                    // This is a sessionStorage draft - don't clear it, it's the user's unsaved work
                    console.debug('[ActiveChat] Auth state effect - keeping sessionStorage draft chat:', currentChat.chat_id);
                    return; // Keep the draft chat loaded
                }
                
                if (isSharedChat && !$isLoggingOut) {
                    // This is a shared chat - don't clear it, it's valid for non-auth users
                    // EXCEPTION: If we're explicitly logging out, always switch to demo-for-everyone
                    console.debug('[ActiveChat] Auth state changed to unauthenticated - keeping shared chat:', currentChat.chat_id);
                    return; // Keep the shared chat loaded
                }

                if (isSharedChat && $isLoggingOut) {
                    console.debug('[ActiveChat] Auth state changed during logout - clearing shared chat and loading demo-for-everyone:', currentChat.chat_id);
                    // Continue with clearing logic below
                }
                
                // Not a shared chat - proceed with clearing
                console.debug('[ActiveChat] Auth state changed to unauthenticated - clearing user chat and loading demo chat (backup handler)');
                
                // Clear current chat state
                currentChat = null;
                currentMessages = [];
                followUpSuggestions = [];
                settingsMemoriesSuggestions = [];
                rejectedSuggestionHashes = null;
                showWelcome = true;
                isAtBottom = false;
                
                // Clear the persistent store
                activeChatStore.clearActiveChat();
                
                // Load demo welcome chat (async operation)
                (async () => {
                    try {
                        // Check if deep link processing is happening
                        if (get(deepLinkProcessing)) {
                            console.debug('[ActiveChat] Skipping welcome chat backup - deep link processing in progress');
                            return;
                        }

                        const welcomeDemo = DEMO_CHATS.find(chat => chat.chat_id === 'demo-for-everyone');
                        if (welcomeDemo) {
                            const translatedWelcomeDemo = translateDemoChat(welcomeDemo);
                            const welcomeChat = convertDemoChatToChat(translatedWelcomeDemo);
                            activeChatStore.setActiveChat('demo-for-everyone');
                            await tick();
                            await loadChat(welcomeChat);
                            console.debug('[ActiveChat] ✅ Demo welcome chat loaded after auth state change (backup)');
                        }
                    } catch (error) {
                        console.error('[ActiveChat] Error loading demo chat in backup handler:', error);
                    }
                })();
            }
        } else {
            // Close login interface when user successfully logs in
            // CRITICAL: Do NOT close if user is in signup process - they need to complete signup
            if ($loginInterfaceOpen && !$isInSignupProcess) {
                loginInterfaceOpen.set(false);
                // Only open chats panel on desktop (not mobile) when closing login interface after successful login
                // On mobile, let the user manually open the panel if they want to see the chat list
                if (!$panelState.isActivityHistoryOpen && !$isMobileView) {
                    panelState.toggleChats();
                }
            } else if ($isInSignupProcess) {
                // User is in signup process - ensure login interface stays open
                console.debug('[ActiveChat] User is in signup process - keeping login interface open');
                if (!$loginInterfaceOpen) {
                    loginInterfaceOpen.set(true);
                }
            }
            
            // Restore draft from sessionStorage after successful authentication
            // This handles drafts saved before signup/login
            // Wrap async code in an async function since $effect can't be async directly
            (async () => {
                try {
                    const pendingDraftJson = sessionStorage.getItem('pendingDraftAfterSignup');
                    if (pendingDraftJson && messageInputFieldRef) {
                        const draftData = JSON.parse(pendingDraftJson);
                        console.debug('[ActiveChat] Found pending draft after signup:', {
                            chatId: draftData.chatId,
                            markdownLength: draftData.markdown?.length || 0,
                            timestamp: draftData.timestamp
                        });
                        
                        // Parse the markdown to TipTap JSON format
                        const { parse_message } = await import('../message_parsing/parse_message');
                        const draftContentJSON = parse_message(draftData.markdown, 'write', { unifiedParsingEnabled: true });
                        
                        // If the draft was for a specific chat, load that chat first
                        if (draftData.chatId && draftData.chatId !== 'new-chat') {
                            // Check if it's a demo chat
                            const isDemoChat = draftData.chatId.startsWith('demo-');
                            if (isDemoChat) {
                                // Load demo chat
                                const demoChat = DEMO_CHATS.find(chat => chat.chat_id === draftData.chatId);
                                if (demoChat) {
                                    const translatedDemo = translateDemoChat(demoChat);
                                    const convertedChat = convertDemoChatToChat(translatedDemo);
                                    loadChat(convertedChat);
                                }
                            } else {
                                // Try to load real chat from database
                                const chatFromDB = await chatDB.getChat(draftData.chatId);
                                if (chatFromDB) {
                                    loadChat(chatFromDB);
                                }
                            }
                        }
                        
                        // Wait a moment for chat to load, then restore draft
                        setTimeout(() => {
                            if (messageInputFieldRef) {
                                const chatIdToUse = draftData.chatId === 'new-chat' ? undefined : draftData.chatId;
                                messageInputFieldRef.setDraftContent(chatIdToUse, draftContentJSON, 0, false);
                                console.debug('[ActiveChat] ✅ Draft restored after signup');
                            }
                            // Remove from sessionStorage after successful restoration
                            sessionStorage.removeItem('pendingDraftAfterSignup');
                        }, 500);
                    }
                } catch (error) {
                    console.error('[ActiveChat] Error restoring draft from sessionStorage:', error);
                    // Clean up on error
                    try {
                        sessionStorage.removeItem('pendingDraftAfterSignup');
                    } catch {
                        // Ignore cleanup errors
                    }
                }
            })();
        }
    });

    // Add handler for code fullscreen
    function handleCodeFullscreen(event: CustomEvent) {
        console.debug('Received code fullscreen event:', event.detail);
        fullscreenCodeData = {
            code: event.detail.code,
            filename: event.detail.filename,
            language: event.detail.language,
            lineCount: event.detail.lineCount // Make sure we're capturing the line count
        };
        console.debug('Set fullscreen data:', fullscreenCodeData);
        showCodeFullscreen = true;
    }

    function handleImageFullscreen(event: CustomEvent) {
        console.debug('[ActiveChat] Received imagefullscreen event:', event.detail);
        uploadedImageFullscreenData = {
            src: event.detail.src,
            filename: event.detail.filename,
            s3Files: event.detail.s3Files,
            s3BaseUrl: event.detail.s3BaseUrl,
            aesKey: event.detail.aesKey,
            aesNonce: event.detail.aesNonce,
            isAuthenticated: event.detail.isAuthenticated,
            fileSize: event.detail.fileSize,
            fileType: event.detail.fileType,
        };
        showUploadedImageFullscreen = true;
    }

    function handleCloseUploadedImageFullscreen() {
        showUploadedImageFullscreen = false;
        uploadedImageFullscreenData = {};
    }

    // Normalize embed result arrays for fullscreen components with strict prop types.
    function getWebSearchResults(results?: unknown[]): WebSearchResult[] {
        return Array.isArray(results) ? (results as WebSearchResult[]) : [];
    }

    function getNewsSearchResults(results?: unknown[]): NewsSearchResult[] {
        return Array.isArray(results) ? (results as NewsSearchResult[]) : [];
    }

    function getVideoSearchResults(results?: unknown[]): VideoSearchResult[] {
        return Array.isArray(results) ? (results as VideoSearchResult[]) : [];
    }

    function getPlaceSearchResults(results?: unknown[]): PlaceSearchResult[] {
        return Array.isArray(results) ? (results as PlaceSearchResult[]) : [];
    }

    function getVideoTranscriptResults(results?: unknown[]): VideoTranscriptResult[] {
        return Array.isArray(results) ? (results as VideoTranscriptResult[]) : [];
    }

    function getWebReadResults(results?: unknown[]): WebReadResult[] {
        return Array.isArray(results) ? (results as WebReadResult[]) : [];
    }

    function getCodeDocsResults(results?: unknown[]): CodeGetDocsResult[] {
        return Array.isArray(results) ? (results as CodeGetDocsResult[]) : [];
    }

    function getTravelConnectionResults(results?: unknown[]): TravelConnectionResult[] {
        return Array.isArray(results) ? (results as TravelConnectionResult[]) : [];
    }

    // Coerce skill preview status to embed status.
    // Both embed and skill preview now support 'cancelled' status natively.
    function toEmbedStatus(status: SkillPreviewData['status']): EmbedResolverData['status'] {
        return status;
    }

    /**
     * Normalize unknown status values into a supported embed status.
     * This guards against loosely typed decodedContent fields.
     */
    function normalizeEmbedStatus(value: unknown): 'processing' | 'finished' | 'error' | 'cancelled' {
        if (value === 'processing' || value === 'finished' || value === 'error' || value === 'cancelled') {
            return value;
        }
        return 'finished';
    }

    // Normalize unknown values from embed payloads into the primitive types UI components expect.
    function coerceString(value: unknown, fallback: string = ''): string {
        return typeof value === 'string' ? value : fallback;
    }

    function coerceNumber(value: unknown, fallback: number = 0): number {
        return typeof value === 'number' ? value : fallback;
    }
    
    // Add state for embed fullscreen
    let showEmbedFullscreen = $state(false);
    let embedFullscreenData = $state<EmbedFullscreenState>(null);
    
    // Debug: Track state changes
    $effect(() => {
        console.debug('[ActiveChat] showEmbedFullscreen changed:', showEmbedFullscreen, 'embedFullscreenData:', !!embedFullscreenData);
    });
    
    // --- Focus mode context menu state ---
    let showFocusModeContextMenu = $state(false);
    let focusModeContextMenuX = $state(0);
    let focusModeContextMenuY = $state(0);
    let focusModeContextMenuIsActivated = $state(false);
    let focusModeContextMenuFocusId = $state('');
    let focusModeContextMenuAppId = $state('');
    let focusModeContextMenuFocusModeName = $state('');
    
    // --- Focus mode event handlers ---
    
    /**
     * Deactivate a focus mode: clear local state and tell the backend to
     * remove the encrypted_active_focus_id from cache and Directus.
     * The next user message will be sent without active_focus_id so the
     * AI reverts to normal behaviour.
     */
    async function handleFocusModeDeactivation(focusId: string) {
        if (!focusId) return;
        const chatId = currentChat?.chat_id;
        if (!chatId) return;
        console.debug('[ActiveChat] Deactivating focus mode:', focusId);
        
        // Send deactivation to the backend via WebSocket
        // The backend handler clears cache + dispatches Celery task for Directus
        try {
            const { webSocketService } = await import('../services/websocketService');
            webSocketService.sendMessage('chat_focus_mode_deactivate', {
                chat_id: chatId,
                focus_id: focusId,
            });
            console.debug('[ActiveChat] Sent focus mode deactivation to backend');
        } catch (e) {
            console.error('[ActiveChat] Error sending focus mode deactivation:', e);
        }
        
        // Clear the local encrypted_active_focus_id and invalidate the metadata cache
        // so the ChatContextMenu immediately reflects the deactivation without waiting
        // for a server round-trip or cache expiry.
        try {
            const chat = await chatDB.getChat(chatId);
            if (chat) {
                chat.encrypted_active_focus_id = null;
                await chatDB.updateChat(chat);
            }
            const { chatMetadataCache } = await import('../services/chatMetadataCache');
            chatMetadataCache.invalidateChat(chatId);
            console.debug('[ActiveChat] Cleared local focus mode state and invalidated cache');
        } catch (e) {
            console.error('[ActiveChat] Error clearing local focus mode state:', e);
        }
    }
    
    /**
     * Add a persisted system message to the chat indicating a focus mode state change.
     * Encrypts with the chat key and sends via `chat_system_message_added` WebSocket
     * so it's stored server-side and synced across devices.
     * 
     * @param focusId - The focus mode ID
     * @param focusModeName - Display name for the focus mode
     * @param action - 'rejected' or 'stopped'
     */
    async function handleFocusModeSystemMessage(focusId: string, focusModeName: string, action: 'rejected' | 'stopped' = 'rejected') {
        const chatId = currentChat?.chat_id;
        if (!focusId || !chatId) return;
        const displayName = focusModeName || focusId;
        const verb = action === 'stopped' ? 'Stopped' : 'Rejected';
        const messageText = `${verb} ${displayName} focus mode.`;
        
        console.debug('[ActiveChat] Adding focus mode system message:', messageText);
        
        try {
            const { encryptWithChatKey } = await import('../services/cryptoService');
            const { webSocketService } = await import('../services/websocketService');
            const importedChatSyncService = (await import('../services/chatSyncService')).default;
            
            // Generate message ID (format: last 10 chars of chat_id + uuid)
            const chatIdSuffix = chatId.slice(-10);
            const messageId = `${chatIdSuffix}-${crypto.randomUUID()}`;
            const now = Math.floor(Date.now() / 1000);
            
            // Encrypt content with chat key (zero-knowledge architecture)
            const chatKey = chatDB.getChatKey(chatId);
            let encryptedContent: string | null = null;
            
            if (chatKey) {
                encryptedContent = await encryptWithChatKey(messageText, chatKey);
            }
            
            if (!chatKey || !encryptedContent) {
                // Fallback: create local-only message if encryption fails (e.g., chat key not loaded)
                console.warn('[ActiveChat] Cannot encrypt focus mode system message, creating local-only');
                const localMessage = {
                    message_id: messageId,
                    chat_id: chatId,
                    role: 'system' as const,
                    content: messageText,
                    created_at: now,
                    status: 'sent' as const,
                };
                importedChatSyncService.dispatchEvent(
                    new CustomEvent('chatUpdated', {
                        detail: { chat_id: chatId, type: 'system_message_added', newMessage: localMessage },
                    }),
                );
                return;
            }
            
            // Create system message with encrypted content
            const systemMessage = {
                message_id: messageId,
                chat_id: chatId,
                role: 'system' as const,
                content: messageText,
                created_at: now,
                status: 'sending' as const,
                encrypted_content: encryptedContent,
            };
            
            // Save to IndexedDB first
            await chatDB.saveMessage(systemMessage);
            
            // Send encrypted content to server for persistence and cross-device sync
            const payload = {
                chat_id: chatId,
                message: {
                    message_id: messageId,
                    role: 'system',
                    encrypted_content: encryptedContent,
                    created_at: now,
                },
            };
            
            await webSocketService.sendMessage('chat_system_message_added', payload);
            
            // Update status to synced
            const syncedMessage = { ...systemMessage, status: 'synced' as const };
            await chatDB.saveMessage(syncedMessage);
            
            // Dispatch UI update event
            importedChatSyncService.dispatchEvent(
                new CustomEvent('chatUpdated', {
                    detail: { chat_id: chatId, type: 'system_message_added', newMessage: syncedMessage },
                }),
            );
            
            console.debug('[ActiveChat] Persisted focus mode system message:', messageId);
        } catch (e) {
            console.error('[ActiveChat] Error creating focus mode system message:', e);
        }
    }
    
    /**
     * Navigate to the focus mode details page in the settings / app store.
     * Deep link format: app_store/{appId}/focus/{focusModeId}
     */
    async function handleFocusModeDetailsNavigation(focusId: string, appId: string) {
        if (!focusId || !appId) return;
        
        // Extract the focus mode ID within the app (remove app prefix)
        const focusModeId = focusId.includes('-') ? focusId.split('-').slice(1).join('-') : focusId;
        
        try {
            const { navigateToSettings } = await import('../stores/settingsNavigationStore');
            const { settingsDeepLink } = await import('../stores/settingsDeepLinkStore');
            const { panelState } = await import('../stores/panelStateStore');
            
            const deepLink = `app_store/${appId}/focus/${focusModeId}`;
            navigateToSettings(deepLink, 'Focus Mode Details', 'focus_mode', '');
            settingsDeepLink.set(deepLink);
            panelState.openSettings();
        } catch (e) {
            console.error('[ActiveChat] Error navigating to focus mode details:', e);
        }
    }
    
    // Handler for embed fullscreen events (from embed renderers)
    async function handleEmbedFullscreen(event: CustomEvent) {
        console.debug('[ActiveChat] Received embedfullscreen event:', event.detail);
        const detail = event.detail as EmbedFullscreenEventDetail;
        const { embedId, embedData, decodedContent, embedType, attrs } = detail;
        
        // ALWAYS reload from EmbedStore when embedId is provided to ensure we get the latest data
        // The embed might have been updated since the preview was rendered (e.g., processing -> finished)
        // The event's embedData/decodedContent might be stale (captured at render time before skill results arrived)
        let finalEmbedData = embedData;
        let finalDecodedContent = decodedContent;
        
        // Skip EmbedStore lookup for preview/stream embeds — these are ephemeral and their
        // content is passed inline via the event's decodedContent. They have no backing
        // entry in the EmbedStore. (Legacy path — new embeds use embed: refs.)
        const isEphemeralEmbed = embedId && (embedId.startsWith('stream:') || embedId.startsWith('preview:'));
        
        if (embedId && !isEphemeralEmbed) {
            try {
                const { resolveEmbed, decodeToonContent } = await import('../services/embedResolver');
                const freshEmbedData = await resolveEmbed(embedId) as EmbedResolverData | null;
                
                if (freshEmbedData) {
                    // Use fresh data from EmbedStore
                    finalEmbedData = freshEmbedData;
                    
                    if (freshEmbedData.content) {
                        finalDecodedContent = await decodeToonContent(freshEmbedData.content);
                    }
                    
                    console.debug('[ActiveChat] 🔍 Loaded fresh embed data from EmbedStore:', {
                        embedId,
                        status: freshEmbedData.status,
                        type: freshEmbedData.type,
                        // Check content structure
                        hasContent: !!freshEmbedData.content,
                        contentType: typeof freshEmbedData.content,
                        contentPreview: typeof freshEmbedData.content === 'string' 
                            ? freshEmbedData.content.substring(0, 200) 
                            : JSON.stringify(freshEmbedData.content).substring(0, 200),
                        // Check results  
                        hasResults: !!finalDecodedContent?.results,
                        resultsCount: finalDecodedContent?.results?.length || 0,
                        // Check embed_ids from both sources
                        embedDataHasEmbedIds: !!freshEmbedData.embed_ids,
                        embedDataEmbedIds: freshEmbedData.embed_ids,
                        embedIdsCount: freshEmbedData.embed_ids?.length || 0,
                        decodedContentHasEmbedIds: !!finalDecodedContent?.embed_ids,
                        decodedContentEmbedIds: finalDecodedContent?.embed_ids,
                        decodedEmbedIdsCount: finalDecodedContent?.embed_ids?.length || 0,
                        // Check decoded content keys
                        decodedContentKeys: finalDecodedContent ? Object.keys(finalDecodedContent) : []
                    });
                } else if (!finalEmbedData && !finalDecodedContent) {
                    // Only error if we have no data at all (neither from EmbedStore nor from event)
                    console.error('[ActiveChat] Embed not found in EmbedStore and no fallback data:', embedId);
                    return;
                }
            } catch (error) {
                console.error('[ActiveChat] Error loading embed for fullscreen:', error);
                // Fall back to event data if available
                if (!finalEmbedData && !finalDecodedContent) {
                    return;
                }
            }
        }
        
        // Normalize embed types from different sources:
        // - Renderers use UI types (e.g. "code-code", "app-skill-use")
        // - Some synced/stored embeds can expose server types (e.g. "code", "app_skill_use")
        // - Deep links dispatch a placeholder type, but we can infer from stored embed when needed
        const normalizeEmbedType = (t: string | null | undefined): string | null => {
            if (!t) return null;
            switch (t) {
                case 'app_skill_use':
                case 'app-skill-use':
                    return 'app-skill-use';
                case 'web-website':
                case 'website':
                    return 'website';
                case 'code':
                case 'code-code':
                    return 'code-code';
                case 'document':
                case 'docs-doc':
                    return 'docs-doc';
                case 'video':
                case 'videos-video':
                    return 'videos-video';
                case 'sheet':
                case 'sheets-sheet':
                    return 'sheets-sheet';
                default:
                    return t;
            }
        };
        
        let resolvedEmbedType = normalizeEmbedType(embedType) || embedType;
        const inferredType = normalizeEmbedType(finalEmbedData?.type) || finalEmbedData?.type;
        
        // Use inferred type from embed data when:
        // 1. No type was provided in the event (null/undefined) - e.g., navigation between embeds
        // 2. Type is a placeholder (app-skill-use) and we can infer more specific type from stored data
        if (inferredType && (!resolvedEmbedType || resolvedEmbedType === 'app-skill-use' || resolvedEmbedType === 'app_skill_use')) {
            resolvedEmbedType = inferredType;
        }
        
        // If we already have this embed open, ignore duplicate events (e.g. hashchange deep-link echoes).
        if (showEmbedFullscreen && embedFullscreenData?.embedId === embedId && embedFullscreenData?.embedType === resolvedEmbedType) {
            console.debug('[ActiveChat] Ignoring duplicate embedfullscreen event for already-open embed:', {
                embedId,
                resolvedEmbedType
            });
            return;
        }
        
        // For web search embeds, load child website embeds and transform to results array
        // This is needed because parent embed only contains embed_ids, not the actual website data
        if (resolvedEmbedType === 'app-skill-use' && finalDecodedContent) {
            const appId = finalDecodedContent.app_id || '';
            const skillId = finalDecodedContent.skill_id || '';
            
            // embed_ids can be in decoded content OR in the embed data itself
            // embed_ids may be a pipe-separated string OR an array - normalize to array
            const rawEmbedIds = finalDecodedContent.embed_ids || finalEmbedData?.embed_ids || [];
            const childEmbedIds: string[] = typeof rawEmbedIds === 'string' 
                ? rawEmbedIds.split('|').filter((id: string) => id.length > 0)
                : Array.isArray(rawEmbedIds) ? rawEmbedIds : [];
            
            // DEBUG: Log embed_ids discovery for composite embeds
            console.debug('[ActiveChat] Checking embed_ids for composite embed:', {
                appId,
                skillId,
                decodedContentEmbedIds: finalDecodedContent.embed_ids,
                embedDataEmbedIds: finalEmbedData?.embed_ids,
                rawEmbedIds,
                childEmbedIds,
                childEmbedIdsCount: childEmbedIds.length
            });
            
            if (appId === 'web' && skillId === 'search' && childEmbedIds.length > 0) {
console.debug('[ActiveChat] Loading child website embeds for web search fullscreen:', childEmbedIds);
                try {
                    // Use loadEmbedsWithRetry to handle race condition where child embeds
                    // might not be persisted yet (they arrive via websocket after parent)
                    const { loadEmbedsWithRetry, decodeToonContent: decodeToon } = await import('../services/embedResolver');
                    const childEmbeds = await loadEmbedsWithRetry(childEmbedIds, 8, 400);
                    
                    // Transform child embeds to WebSearchResult format
                    const results = await Promise.all(childEmbeds.map(async (embed) => {
                        const websiteContent = embed.content ? await decodeToon(embed.content) : null;
                        if (!websiteContent) return null;
                        
                        // Extract favicon URL from multiple possible field formats:
                        // 1. meta_url_favicon: TOON-flattened format (meta_url.favicon becomes meta_url_favicon)
                        // 2. meta_url.favicon: Nested format (raw API or non-TOON encoded)
                        // 3. favicon: Direct field (processed backend format)
                        const faviconUrl = 
                            websiteContent.meta_url_favicon ||  // TOON flattened format (most common)
                            (websiteContent.meta_url as { favicon?: string } | undefined)?.favicon || 
                            websiteContent.favicon || 
                            '';
                        
                        // Extract preview image from multiple possible field formats:
                        // 1. thumbnail_original: TOON-flattened format
                        // 2. thumbnail.original: Nested format
                        // 3. image: Direct field
                        const previewImageUrl = 
                            websiteContent.thumbnail_original ||  // TOON flattened format
                            (websiteContent.thumbnail as { original?: string } | undefined)?.original ||
                            websiteContent.image || 
                            '';
                        
                        return {
                            type: 'search_result' as const,
                            title: websiteContent.title || '',
                            url: websiteContent.url || '',
                            snippet: websiteContent.description || websiteContent.extra_snippets || '',
                            hash: embed.embed_id || '',
                            // Include 'favicon' field for WebSearchEmbedPreview's getFaviconUrl()
                            favicon: faviconUrl,
                            favicon_url: faviconUrl,
                            preview_image_url: previewImageUrl
                        };
                    }));
                    
                    // Filter out nulls and add to decoded content
                    finalDecodedContent.results = results.filter(r => r !== null);
                    const websiteResults = getWebSearchResults(finalDecodedContent.results);
                    console.info('[ActiveChat] Loaded', websiteResults.length, 'website results for web search fullscreen:', 
                        websiteResults.map(r => ({ title: r?.title?.substring(0, 30), url: r?.url })));
                } catch (error) {
                    console.error('[ActiveChat] Error loading child embeds for web search:', error);
                    // Continue without results - fullscreen will show "No results" message
                }
            } else if (appId === 'maps' && skillId === 'search' && childEmbedIds.length > 0) {
                console.debug('[ActiveChat] Loading child place embeds for maps search fullscreen:', childEmbedIds);
                try {
                    // Use loadEmbedsWithRetry to handle race condition where child embeds
                    // might not be persisted yet (they arrive via websocket after parent)
                    const { loadEmbedsWithRetry, decodeToonContent: decodeToon } = await import('../services/embedResolver');
                    const childEmbeds = await loadEmbedsWithRetry(childEmbedIds, 8, 400);
                    
                    // Transform child embeds to PlaceSearchResult format
                    const results = await Promise.all(childEmbeds.map(async (embed) => {
                        const placeContent = embed.content ? await decodeToon(embed.content) : null;
                        if (!placeContent) return null;
                        
                        // Handle location - can be nested object or flattened fields
                        let location = undefined;
                        if (placeContent.location) {
                            // Nested location object
                            if (typeof placeContent.location === 'object' && 'latitude' in placeContent.location) {
                                location = {
                                    latitude: placeContent.location.latitude,
                                    longitude: placeContent.location.longitude
                                };
                            }
                        } else if (placeContent.location_latitude !== undefined || placeContent.location_longitude !== undefined) {
                            // Flattened location fields (from TOON encoding)
                            location = {
                                latitude: placeContent.location_latitude,
                                longitude: placeContent.location_longitude
                            };
                        }
                        
                        return {
                            displayName: placeContent.name || placeContent.displayName || '',
                            formattedAddress: placeContent.formatted_address || placeContent.formattedAddress || '',
                            location: location,
                            rating: placeContent.rating,
                            userRatingCount: placeContent.user_rating_count || placeContent.userRatingCount,
                            websiteUri: placeContent.website_uri || placeContent.websiteUri,
                            placeId: placeContent.place_id || placeContent.placeId
                        };
                    }));
                    
                    // Filter out nulls and add to decoded content
                    finalDecodedContent.results = results.filter(r => r !== null);
                    const placeResults = getPlaceSearchResults(finalDecodedContent.results);
                    console.info('[ActiveChat] Loaded', placeResults.length, 'place results for maps search fullscreen:', 
                        placeResults.map(r => ({ name: r?.displayName?.substring(0, 30), address: r?.formattedAddress })));
                } catch (error) {
                    console.error('[ActiveChat] Error loading child embeds for maps search:', error);
                    // Continue without results - fullscreen will show "No results" message
                }
            } else if (appId === 'web' && skillId === 'search') {
                console.warn('[ActiveChat] Web search fullscreen opened but no embed_ids found:', {
                    decodedContentEmbedIds: finalDecodedContent.embed_ids,
                    embedDataEmbedIds: finalEmbedData?.embed_ids
                });
            }
        }
        
        // Store fullscreen data (moved below after all async operations)
        console.debug('[ActiveChat] Setting showEmbedFullscreen to true, embedFullscreenData:', {
            embedType: resolvedEmbedType,
            embedId,
            hasEmbedData: !!finalEmbedData,
            hasDecodedContent: !!finalDecodedContent,
            appId: finalDecodedContent?.app_id,
            skillId: finalDecodedContent?.skill_id
        });
        
        // CRITICAL: Set embedFullscreenData first, then showEmbedFullscreen
        // This ensures both state variables are set before the template evaluates
        embedFullscreenData = {
            embedId,
            embedData: finalEmbedData,
            decodedContent: finalDecodedContent,
            embedType: resolvedEmbedType,
            attrs
        };
        
        // Use a microtask to ensure state is fully updated before setting showEmbedFullscreen
        // This helps with Svelte 5 reactivity
        await Promise.resolve();
        
        showEmbedFullscreen = true;
        
        // Update URL hash with embed ID for sharing/bookmarking
        if (embedId) {
            activeEmbedStore.setActiveEmbed(embedId);
            console.debug('[ActiveChat] Updated URL hash with embed ID:', embedId);
        }
        
        console.debug('[ActiveChat] Opening embed fullscreen:', resolvedEmbedType, embedId, 'showEmbedFullscreen:', showEmbedFullscreen, 'embedFullscreenData:', !!embedFullscreenData);
    }
    
    // Handler for closing embed fullscreen
    // This is called when any embed fullscreen is closed (via minimize button or other means)
    // For video embeds, VideoEmbedFullscreen's handleClose handles video cleanup,
    // but this is a fallback in case it's called directly
    function handleCloseEmbedFullscreen() {
        // Check if this was a video embed and clean up if needed
        // Note: VideoEmbedFullscreen's handleClose should handle this, but this is a safety net
        const wasVideoEmbed = embedFullscreenData?.embedType === 'videos-video';
        if (wasVideoEmbed) {
            const videoState = get(videoIframeStore);
            // Only close video if NOT in PiP mode (PiP should persist)
            if (videoState.isActive && !videoState.isPipMode) {
                console.debug('[ActiveChat] Closing video player via handleCloseEmbedFullscreen (not in PiP mode)');
                videoIframeStore.closeWithFadeOut(300);
            } else if (videoState.isPipMode) {
                console.debug('[ActiveChat] Video in PiP mode - keeping video playing');
            }
        }
        
        showEmbedFullscreen = false;
        embedFullscreenData = null;
        
        // Reset forceOverlayMode when embed is closed
        // This ensures the next time an embed is opened, it uses the default layout based on screen size
        forceOverlayMode = false;
        
        // Clear embed URL hash when embed is closed
        activeEmbedStore.clearActiveEmbed();
        console.debug('[ActiveChat] Cleared embed from URL hash');
        
        // If there's an active chat, restore the chat URL hash
        // This ensures that when closing an embed while viewing a chat, the chat URL is restored
        if (currentChat && currentChat.chat_id) {
            activeChatStore.setActiveChat(currentChat.chat_id);
            console.debug('[ActiveChat] Restored chat URL hash after closing embed:', currentChat.chat_id);
        }
    }
    
    // ===========================================
    // Embed Navigation Logic
    // ===========================================
    // Extracts embed IDs from chat messages and provides navigation between them
    
    /**
     * Extract all embed IDs from messages in order of appearance
     * This creates a flat list of all embeds that can be displayed in fullscreen
     * @param messages - Array of chat messages
     * @returns Array of embed IDs in order of appearance
     */
    function extractEmbedIdsFromMessages(messages: ChatMessageModel[]): string[] {
        const embedIds: string[] = [];
        
        // Collect all embed IDs that are known to have errored.
        // _embedErrors is populated by the embedUpdated event handler when
        // an embed's status transitions to 'error' (see ~line 4998).
        const errorEmbedIds = new Set<string>();
        for (const msg of messages) {
            const errors = (msg as MessageWithEmbedMeta)._embedErrors;
            if (errors) {
                for (const id of errors) {
                    errorEmbedIds.add(id);
                }
            }
        }
        
        for (const message of messages) {
            // Get message content as markdown string
            let markdownContent = '';
            if (typeof message.content === 'string') {
                markdownContent = message.content;
            } else if (message.content && typeof message.content === 'object') {
                // Convert TipTap JSON to markdown to extract embed references
                markdownContent = tipTapToCanonicalMarkdown(message.content);
            }
            
            // Extract embed references from markdown content
            const refs = extractEmbedReferences(markdownContent);
            for (const ref of refs) {
                // Skip error embeds — they are hidden from the UI and should
                // not appear in fullscreen prev/next navigation.
                if (errorEmbedIds.has(ref.embed_id)) {
                    continue;
                }
                // Avoid duplicates
                if (!embedIds.includes(ref.embed_id)) {
                    embedIds.push(ref.embed_id);
                }
            }
        }
        
        return embedIds;
    }
    
    /**
     * Navigate to the previous embed in the chat
     * Dispatches an embedfullscreen event with the previous embed's ID
     */
    async function handleNavigatePreviousEmbed() {
        if (!hasPreviousEmbed) {
            console.debug('[ActiveChat] No previous embed to navigate to');
            return;
        }
        
        const previousEmbedId = chatEmbedIds[currentEmbedIndex - 1];
        console.debug('[ActiveChat] Navigating to previous embed:', previousEmbedId, 'from index', currentEmbedIndex, 'to', currentEmbedIndex - 1);
        
        // Create a synthetic embedfullscreen event to open the previous embed
        // This reuses the existing handleEmbedFullscreen logic
        const event = new CustomEvent('embedfullscreen', {
            detail: {
                embedId: previousEmbedId,
                embedData: null, // Will be loaded from embedStore
                decodedContent: null, // Will be loaded from embedStore
                embedType: null, // Will be resolved from embed data
                attrs: {}
            }
        });
        
        await handleEmbedFullscreen(event);
    }
    
    /**
     * Navigate to the next embed in the chat
     * Dispatches an embedfullscreen event with the next embed's ID
     */
    async function handleNavigateNextEmbed() {
        if (!hasNextEmbed) {
            console.debug('[ActiveChat] No next embed to navigate to');
            return;
        }
        
        const nextEmbedId = chatEmbedIds[currentEmbedIndex + 1];
        console.debug('[ActiveChat] Navigating to next embed:', nextEmbedId, 'from index', currentEmbedIndex, 'to', currentEmbedIndex + 1);
        
        // Create a synthetic embedfullscreen event to open the next embed
        // This reuses the existing handleEmbedFullscreen logic
        const event = new CustomEvent('embedfullscreen', {
            detail: {
                embedId: nextEmbedId,
                embedData: null, // Will be loaded from embedStore
                decodedContent: null, // Will be loaded from embedStore
                embedType: null, // Will be resolved from embed data
                attrs: {}
            }
        });
        
        await handleEmbedFullscreen(event);
    }
    
    // Reference to PiP container for moving iframe
    // ===========================================
    // Video Iframe State (CSS-based PiP)
    // ===========================================
    // 
    // The VideoIframe component is always rendered in the same DOM position.
    // PiP mode is achieved purely through CSS class changes (no DOM movement).
    // This prevents iframe reloads and ensures smooth iOS-like transitions.
    
    // Derive video iframe state for template use - use reactive subscription
    // $derived(get(store)) doesn't create a subscription, so we need to use $state with subscription
    let videoIframeState = $state(get(videoIframeStore));
    
    // Subscribe to videoIframeStore to keep state reactive
    $effect(() => {
        const unsubscribe = videoIframeStore.subscribe((state) => {
            videoIframeState = state;
        });
        return unsubscribe;
    });
    
    // Debug: Log videoIframeState changes to help diagnose rendering issues
    $effect(() => {
        const state = videoIframeState;
        const conditionMet = state.isActive && state.videoId && state.embedUrl;
        console.debug('[ActiveChat] VideoIframeState check:', {
            isActive: state.isActive,
            isPipMode: state.isPipMode,
            videoId: state.videoId,
            embedUrl: state.embedUrl,
            conditionMet,
            willRender: conditionMet,
            fullState: state
        });
    });
    
    // Cleanup video iframe state on component destroy or logout
    onDestroy(() => {
        // Clear video state when component is destroyed (e.g., on logout)
        videoIframeStore.clear();
    });
    
    // Handler for clicking PiP overlay to restore fullscreen view
    // This is called when user clicks the overlay on the VideoIframe in PiP mode
    // It exits PiP mode (via CSS) and opens VideoEmbedFullscreen with restoreFromPip flag
    async function handlePipOverlayClick() {
        console.debug('[ActiveChat] PiP overlay clicked, restoring fullscreen');
        
        // Get current state from videoIframeStore
        const currentState = get(videoIframeStore);
        
        if (!currentState.isActive || !currentState.isPipMode) {
            console.warn('[ActiveChat] Cannot restore fullscreen - video not in PiP mode', {
                isActive: currentState.isActive,
                isPipMode: currentState.isPipMode
            });
            return;
        }
        
        // Get video data for fullscreen view
        const pipUrl = currentState.url;
        const pipTitle = currentState.title;
        const pipVideoId = currentState.videoId;
        const pipEmbedUrl = currentState.embedUrl || (pipVideoId ? `https://www.youtube-nocookie.com/embed/${pipVideoId}?modestbranding=1&rel=0&iv_load_policy=3&fs=1&autoplay=1&enablejsapi=0` : '');
        
        // Proxied thumbnail URL through preview server for privacy
        // If thumbnailUrl is already set and proxied, use it; otherwise construct and proxy
        const PREVIEW_SERVER = 'https://preview.openmates.org';
        const FULLSCREEN_IMAGE_MAX_WIDTH = 1560; // 2x for retina on 780px container
        let pipThumbnailUrl = currentState.thumbnailUrl;
        if (!pipThumbnailUrl && pipVideoId) {
            // Construct raw URL and proxy it
            const rawThumbnailUrl = `https://img.youtube.com/vi/${pipVideoId}/maxresdefault.jpg`;
            pipThumbnailUrl = `${PREVIEW_SERVER}/api/v1/image?url=${encodeURIComponent(rawThumbnailUrl)}&max_width=${FULLSCREEN_IMAGE_MAX_WIDTH}`;
        } else if (pipThumbnailUrl && (pipThumbnailUrl.includes('img.youtube.com') || pipThumbnailUrl.includes('i.ytimg.com'))) {
            // If it's a direct YouTube URL, proxy it
            pipThumbnailUrl = `${PREVIEW_SERVER}/api/v1/image?url=${encodeURIComponent(pipThumbnailUrl)}&max_width=${FULLSCREEN_IMAGE_MAX_WIDTH}`;
        }
        
        // Exit PiP mode - this will trigger CSS transition back to fullscreen position
        // The VideoIframe component will smoothly animate back to center
        videoIframeStore.exitPipMode();
        
        // Open VideoEmbedFullscreen with the video data
        // restoreFromPip flag tells it that video is already playing
        embedFullscreenData = {
            embedType: 'videos-video',
            decodedContent: {
                url: pipUrl,
                title: pipTitle,
                videoId: pipVideoId,
                embedUrl: pipEmbedUrl,
                thumbnailUrl: pipThumbnailUrl
            },
            attrs: {
                url: pipUrl,
                title: pipTitle,
                videoId: pipVideoId
            },
            // Flag to indicate this is a restore from PiP (video already playing)
            restoreFromPip: true
        };
        
        console.debug('[ActiveChat] Setting embedFullscreenData for PiP restore', {
            embedFullscreenData,
            videoId: pipVideoId
        });
        
        // Wait for state to be set
        await tick();
        
        showEmbedFullscreen = true;
        
        console.debug('[ActiveChat] Fullscreen opened from PiP restore');
    }

    // Handler for suggestion click - copies suggestion to message input
    function handleSuggestionClick(suggestion: string) {
        console.debug('[ActiveChat] Suggestion clicked:', suggestion);
        if (messageInputFieldRef) {
            // Set the suggestion text in the message input
            messageInputFieldRef.setSuggestionText(suggestion);
            // Focus the input
            messageInputFieldRef.focus();
        }
    }

    // Handler for the dislike/report-bad-answer retry prompt.
    // When the user clicks the thumbs-down button on an assistant message,
    // ChatMessage dispatches a 'setRetryMessage' event with a translated
    // prompt asking the assistant to try again with web search / app skills.
    function handleSetRetryMessage(event: Event) {
        const detail = (event as CustomEvent<{ text: string }>).detail;
        if (detail?.text && messageInputFieldRef) {
            console.debug('[ActiveChat] Setting retry message from dislike button:', detail.text);
            messageInputFieldRef.setSuggestionText(detail.text);
            messageInputFieldRef.focus();
        }
    }

    // Handler for when user adds a settings/memories suggestion
    // Removes the suggestion from the list so it no longer displays
    function handleSettingsMemorySuggestionAdded(suggestion: import('../types/apps').SuggestedSettingsMemoryEntry) {
        console.info('[ActiveChat] Settings/memories suggestion added:', suggestion.suggested_title);
        // Remove the added suggestion from the list
        settingsMemoriesSuggestions = settingsMemoriesSuggestions.filter(
            s => !(s.app_id === suggestion.app_id && 
                   s.item_type === suggestion.item_type && 
                   s.suggested_title === suggestion.suggested_title)
        );
    }

    // Handler for when user rejects a settings/memories suggestion
    // Removes the suggestion from the list (hash is already persisted by the SettingsMemoriesSuggestions component)
    function handleSettingsMemorySuggestionRejected(suggestion: import('../types/apps').SuggestedSettingsMemoryEntry) {
        console.info('[ActiveChat] Settings/memories suggestion rejected:', suggestion.suggested_title);
        // Remove the rejected suggestion from the list
        settingsMemoriesSuggestions = settingsMemoriesSuggestions.filter(
            s => !(s.app_id === suggestion.app_id && 
                   s.item_type === suggestion.item_type && 
                   s.suggested_title === suggestion.suggested_title)
        );
    }

    // Handler for when user opens a suggestion to customize (deep link to create form with prefill)
    // Removes the suggestion from the list so it does not show twice
    function handleSettingsMemorySuggestionOpenForCustomize(suggestion: import('../types/apps').SuggestedSettingsMemoryEntry) {
        console.info('[ActiveChat] Settings/memories suggestion open for customize:', suggestion.suggested_title);
        settingsMemoriesSuggestions = settingsMemoriesSuggestions.filter(
            s => !(s.app_id === suggestion.app_id && 
                   s.item_type === suggestion.item_type && 
                   s.suggested_title === suggestion.suggested_title)
        );
    }

    // Handler for post-processing completed event
    async function handlePostProcessingCompleted(event: CustomEvent) {
        const { chatId, followUpSuggestions: newSuggestions, suggestedSettingsMemories: newSettingsMemories } = event.detail;
        console.info('[ActiveChat] 📬 Post-processing completed event received:', {
            chatId,
            currentChatId: currentChat?.chat_id,
            match: currentChat?.chat_id === chatId,
            newSuggestionsCount: newSuggestions?.length || 0,
            newSuggestionsType: typeof newSuggestions,
            isArray: Array.isArray(newSuggestions),
            currentFollowUpCount: followUpSuggestions.length,
            newSettingsMemoriesCount: newSettingsMemories?.length || 0
        });

        // CRITICAL FIX: Always reload suggestions from database for the current chat
        // This ensures we get the latest state even if there are timing issues or state mismatches
        // The database is the source of truth after post-processing completes
        const isCurrentChat = currentChat?.chat_id === chatId;
        
        // Always try to reload from database if it's the current chat, even if suggestions aren't in event
        // This handles cases where the event arrives before database is updated
        if (isCurrentChat) {
            try {
                // Small delay to ensure database transaction has completed
                // Post-processing handler saves to DB, but transaction might not be committed yet
                await new Promise(resolve => setTimeout(resolve, 100));
                
                // Reload chat from database to get the latest encrypted suggestions
                const freshChat = await chatDB.getChat(chatId);
                if (freshChat) {
                    // Update currentChat with latest metadata
                    currentChat = { ...currentChat, ...freshChat };
                    console.debug('[ActiveChat] Refreshed currentChat with latest metadata from database after post-processing');
                    
                    // Load follow-up suggestions from the database (source of truth)
                    // Check for cleartext suggestions first (demo chats - should be rare in post-processing)
                    if (freshChat.follow_up_request_suggestions) {
                        try {
                            const suggestions = JSON.parse(freshChat.follow_up_request_suggestions);
                            if (suggestions && suggestions.length > 0) {
                                followUpSuggestions = suggestions;
                                console.info('[ActiveChat] ✅ Loaded cleartext follow-up suggestions after post-processing:', suggestions.length);
                            }
                        } catch (parseError) {
                            console.error('[ActiveChat] Failed to parse cleartext follow-up suggestions:', parseError);
                        }
                    } else if (freshChat.encrypted_follow_up_request_suggestions) {
                        const chatKey = chatDB.getOrGenerateChatKey(chatId);
                        const { decryptArrayWithChatKey } = await import('../services/cryptoService');
                        const decryptedSuggestions = await decryptArrayWithChatKey(
                            freshChat.encrypted_follow_up_request_suggestions,
                            chatKey
                        );
                        
                        if (decryptedSuggestions && decryptedSuggestions.length > 0) {
                            followUpSuggestions = decryptedSuggestions;
                            console.info('[ActiveChat] ✅ Loaded follow-up suggestions from database after post-processing:', decryptedSuggestions.length);
                        } else {
                            // Fallback: use suggestions from event if database decryption fails
                            if (newSuggestions && Array.isArray(newSuggestions) && newSuggestions.length > 0) {
                                followUpSuggestions = newSuggestions;
                                console.info('[ActiveChat] ✅ Fallback: Updated followUpSuggestions from event:', $state.snapshot(followUpSuggestions));
                            } else {
                                followUpSuggestions = [];
                                console.debug('[ActiveChat] No follow-up suggestions found in database or event');
                            }
                        }
                    } else if (newSuggestions && Array.isArray(newSuggestions) && newSuggestions.length > 0) {
                        // Fallback: use suggestions from event if database doesn't have them yet
                        followUpSuggestions = newSuggestions;
                        console.info('[ActiveChat] ✅ Fallback: Updated followUpSuggestions from event (database not updated yet):', $state.snapshot(followUpSuggestions));
                    } else {
                        followUpSuggestions = [];
                        console.debug('[ActiveChat] No follow-up suggestions found');
                    }
                    
                    // Load settings/memories suggestions from database
                    // These are shown as suggestion cards below the AI response
                    rejectedSuggestionHashes = freshChat.rejected_suggestion_hashes ?? null;
                    
                    if (freshChat.encrypted_settings_memories_suggestions) {
                        try {
                            const chatKey = chatDB.getOrGenerateChatKey(chatId);
                            const { decryptWithChatKey } = await import('../services/cryptoService');
                            const decryptedJson = await decryptWithChatKey(
                                freshChat.encrypted_settings_memories_suggestions,
                                chatKey
                            );
                            
                            if (decryptedJson) {
                                const parsed = JSON.parse(decryptedJson);
                                if (Array.isArray(parsed) && parsed.length > 0) {
                                    settingsMemoriesSuggestions = parsed;
                                    console.info('[ActiveChat] ✅ Loaded settings/memories suggestions from database:', parsed.length);
                                } else {
                                    settingsMemoriesSuggestions = [];
                                }
                            } else {
                                settingsMemoriesSuggestions = [];
                            }
                        } catch (decryptError) {
                            console.error('[ActiveChat] Failed to decrypt settings/memories suggestions:', decryptError);
                            // Fallback to event data
                            if (newSettingsMemories && Array.isArray(newSettingsMemories) && newSettingsMemories.length > 0) {
                                settingsMemoriesSuggestions = newSettingsMemories;
                                console.info('[ActiveChat] ✅ Fallback: Using settings/memories suggestions from event');
                            } else {
                                settingsMemoriesSuggestions = [];
                            }
                        }
                    } else if (newSettingsMemories && Array.isArray(newSettingsMemories) && newSettingsMemories.length > 0) {
                        // Fallback: use suggestions from event if database doesn't have them yet
                        settingsMemoriesSuggestions = newSettingsMemories;
                        console.info('[ActiveChat] ✅ Fallback: Using settings/memories suggestions from event (database not updated yet)');
                    } else {
                        settingsMemoriesSuggestions = [];
                        console.debug('[ActiveChat] No settings/memories suggestions found');
                    }
                } else {
                    console.warn('[ActiveChat] Chat not found in database after post-processing:', chatId);
                    // Fallback: use suggestions from event if chat not found
                    if (newSuggestions && Array.isArray(newSuggestions) && newSuggestions.length > 0) {
                        followUpSuggestions = newSuggestions;
                        console.info('[ActiveChat] ✅ Fallback: Updated followUpSuggestions from event (chat not in DB):', $state.snapshot(followUpSuggestions));
                    }
                    if (newSettingsMemories && Array.isArray(newSettingsMemories) && newSettingsMemories.length > 0) {
                        settingsMemoriesSuggestions = newSettingsMemories;
                        console.info('[ActiveChat] ✅ Fallback: Using settings/memories suggestions from event (chat not in DB)');
                    }
                }
            } catch (error) {
                console.error('[ActiveChat] Failed to reload suggestions from database after post-processing:', error);
                // Fallback: use suggestions from event if database reload fails
                if (newSuggestions && Array.isArray(newSuggestions) && newSuggestions.length > 0) {
                    followUpSuggestions = newSuggestions;
                    console.info('[ActiveChat] ✅ Fallback: Updated followUpSuggestions from event (database error):', $state.snapshot(followUpSuggestions));
                }
                if (newSettingsMemories && Array.isArray(newSettingsMemories) && newSettingsMemories.length > 0) {
                    settingsMemoriesSuggestions = newSettingsMemories;
                    console.info('[ActiveChat] ✅ Fallback: Using settings/memories suggestions from event (database error)');
                }
            }
        } else {
            console.debug('[ActiveChat] Post-processing completed for different chat, not updating suggestions');
        }
    }

    // Add handler for closing code fullscreen
    function handleCloseCodeFullscreen() {
        showCodeFullscreen = false;
    }

    // Subscribe to store values
    // Add class when menu is open AND in mobile view AND chat is visible (not in login/signup mode)
    // The dimmed effect should only apply when the main chat is visible, not during signup/login
    let isDimmed = $derived(($panelState && $panelState.isSettingsOpen) && $isMobileView && showChat);

    // Add transition for the login wrapper
    let loginTransitionProps = {
        duration: 300,
        y: 20,
        opacity: 0
    };

    // Create a reference for the ChatHistory component using $state
    let chatHistoryRef = $state<ChatHistoryRef | null>(null);
    // Create a reference for the MessageInput component using $state
    let messageInputFieldRef = $state<MessageInputFieldRef | null>(null);

    let isFullscreen = $state(false);
    // $: messages = chatHistoryRef?.messages || []; // Removed, messages will be managed in currentMessages

    // Add state for message input height using $state
    let messageInputHeight = $state(0);

    let showWelcome = $state(true);

    // ─── Resume Last Chat ───────────────────────────────────────────────
    // Local state for the "Continue where you left off" card on the new chat screen.
    // Shows the chat matching $userProfile.last_opened (most recently opened/viewed chat).
    // Refreshes every time the user returns to the welcome screen or last_opened changes.
    let resumeChatData = $state<Chat | null>(null);
    let resumeChatTitle = $state<string | null>(null);
    let resumeChatCategory = $state<string | null>(null);
    let resumeChatIcon = $state<string | null>(null);

    /**
     * Load the last-opened chat from IndexedDB using $userProfile.last_opened.
     * Decrypts title, category, and icon for the resume card display.
     * Skips draft chats (no title and no messages) so only real chats with
     * content are shown in the "Continue where you left off" card.
     * Returns true if a non-draft chat was found and loaded.
     */
    async function loadResumeChatFromDB(lastOpenedId: string): Promise<boolean> {
        try {
            await chatDB.init();

            // Look up the specific chat by ID from last_opened
            const chat = await chatDB.getChat(lastOpenedId);
            if (!chat) return false;

            // Decrypt title, category, and icon using the chat key
            let decryptedTitle: string | null = null;
            let decryptedCategory: string | null = null;
            let decryptedIcon: string | null = null;

            const { decryptWithChatKey, decryptChatKeyWithMasterKey } = await import('../services/cryptoService');
            let chatKey = chatDB.getChatKey(chat.chat_id);
            if (!chatKey && chat.encrypted_chat_key) {
                chatKey = await decryptChatKeyWithMasterKey(chat.encrypted_chat_key);
                if (chatKey) {
                    chatDB.setChatKey(chat.chat_id, chatKey);
                }
            }

            if (chatKey) {
                // Decrypt title
                if (chat.encrypted_title) {
                    try {
                        decryptedTitle = await decryptWithChatKey(chat.encrypted_title, chatKey);
                    } catch {
                        // Title decryption failed – fall through to default
                    }
                }
                // Decrypt category
                if (chat.encrypted_category) {
                    try {
                        decryptedCategory = await decryptWithChatKey(chat.encrypted_category, chatKey);
                    } catch {
                        // Category decryption failed – will use fallback
                    }
                }
                // Decrypt icon
                if (chat.encrypted_icon) {
                    try {
                        decryptedIcon = await decryptWithChatKey(chat.encrypted_icon, chatKey);
                    } catch {
                        // Icon decryption failed – will use fallback
                    }
                }
            }

            // Determine if this chat has a real title (plaintext for demo chats, or decrypted)
            const hasTitle = !!(chat.title || decryptedTitle);

            // Skip draft chats: chats with no title and no messages are drafts.
            // Only show the resume card for chats that have actual content.
            if (!hasTitle) {
                const lastMessage = await chatDB.getLastMessageForChat(chat.chat_id);
                if (!lastMessage) {
                    console.info(`[ActiveChat] Skipping draft chat (no title, no messages): ${chat.chat_id}`);
                    return false;
                }
            }

            // Use cleartext fields as fallback (demo chats have these set directly)
            const displayTitle = chat.title || decryptedTitle || 'Untitled Chat';
            const displayCategory = chat.category || decryptedCategory || null;
            const displayIcon = chat.icon || decryptedIcon || null;

            resumeChatData = chat;
            resumeChatTitle = displayTitle;
            resumeChatCategory = displayCategory;
            resumeChatIcon = displayIcon;
            console.info(`[ActiveChat] Resume chat loaded: "${displayTitle}" (${chat.chat_id}), category: ${displayCategory}, icon: ${displayIcon}`);
            return true;
        } catch (error) {
            console.warn('[ActiveChat] Error loading resume chat from IndexedDB:', error);
            return false;
        }
    }

    // Refresh the resume card every time the welcome screen appears for an authenticated user.
    // Reacts to $userProfile.last_opened changes so opening a chat updates the card on return.
    // Retries a few times to handle sync delays on fresh login (IndexedDB may be empty initially).
    $effect(() => {
        const isWelcome = showWelcome;
        const isAuth = $authStore.isAuthenticated;
        const lastOpened = $userProfile.last_opened;

        // Only show resume card when on welcome screen, authenticated, and last_opened is a real chat ID
        // (not empty, not '/chat/new' which means the user was already on the new chat screen)
        if (!isWelcome || !isAuth || !lastOpened || lastOpened === '/chat/new') {
            resumeChatData = null;
            resumeChatTitle = null;
            resumeChatCategory = null;
            resumeChatIcon = null;
            return;
        }

        let cancelled = false;
        const maxAttempts = 6;
        const delayMs = 500; // retry every 500ms for up to 3s

        const tryLoad = async (attempt: number) => {
            if (cancelled) return;
            const found = await loadResumeChatFromDB(lastOpened);
            if (!found && !cancelled && attempt < maxAttempts) {
                setTimeout(() => tryLoad(attempt + 1), delayMs);
            }
        };

        tryLoad(1);

        return () => { cancelled = true; };
    });

    // ─── Phase 1 Sync Bridge ──────────────────────────────────────────────
    // When Phase 1 sync completes, Chats.svelte stores the resume chat data
    // in phasedSyncState. This $effect bridges that store to our local state,
    // ensuring the resume card appears even if the initial IndexedDB retry loop
    // above has already exhausted (sync may take longer than 3 seconds on slow
    // connections or cold starts after login).
    $effect(() => {
        const syncState = $phasedSyncState;
        const isWelcome = showWelcome;
        const isAuth = $authStore.isAuthenticated;

        // Only sync from phasedSyncState when on the welcome screen, authenticated,
        // and we don't already have resume data loaded from IndexedDB
        if (isWelcome && isAuth && syncState.resumeChatData && !resumeChatData) {
            resumeChatData = syncState.resumeChatData;
            resumeChatTitle = syncState.resumeChatTitle;
            resumeChatCategory = syncState.resumeChatCategory;
            resumeChatIcon = syncState.resumeChatIcon;
            console.info(`[ActiveChat] Resume chat synced from Phase 1 store: "${syncState.resumeChatTitle}" (${syncState.resumeChatData.chat_id})`);
        }
    });

    // ─── End Phase 1 Sync Bridge ──────────────────────────────────────────

    // Add state variable for scaling animation on the container using $state
    let activeScaling = $state(false);

    // Reactive trigger for AI task state changes - incremented when AI tasks start/end
    // Note: Prefixed with underscore as linter reports unused, but it's used as a reactivity trigger
    let _aiTaskStateTrigger = 0;

    // ─── Progressive AI Status Indicator ─────────────────────────────────
    // Tracks the current phase of the message processing pipeline for the
    // centered status indicator in ChatHistory.
    // Lifecycle: sending → processing (real-time step cards) → typing → null (streaming)
    let processingPhase = $state<ProcessingPhase>(null);
    // Whether the current message being processed is for a new chat (no title yet).
    // Determines the initial spinner text (new chat starts with "Generating chat title...").
    let isNewChatProcessing = $state(false);
    // Mate name captured from the mate_selected preprocessing step, used for the
    // "{Mate} is typing..." spinner text after model_selected arrives.
    let selectedPreprocessingMateName = $state<string | null>(null);
    // Timestamp of the last completed preprocessing step card, used to enforce
    // a minimum display time (~1500ms) before transitioning to the typing phase.
    let lastStepCardTimestamp = $state(0);

    /**
     * Clear the processing phase state.
     * Called on chat switch, unmount, error, or when streaming begins.
     */
    function clearProcessingPhase() {
        processingPhase = null;
        selectedPreprocessingMateName = null;
        lastStepCardTimestamp = 0;
    }

    /**
     * Start the real-time processing phase.
     *
     * Sets the initial spinner text immediately (first expected step).
     * The actual step cards are populated by preprocessingStep WebSocket events
     * (dispatched by chatSyncService → handlePreprocessingStepImpl as CustomEvents).
     *
     * For new chats: first spinner shows "Generating chat title..."
     * For existing chats: first spinner shows "Analyzing your message..."
     *
     * Steps arrive in a burst after the single preprocessing LLM call resolves.
     * Non-skipped steps are added as completed cards above the spinner.
     * If events don't arrive, ai_typing_started still fires and transitions the overlay — same as before.
     */
    function startProcessingStepProgression(isNewChat: boolean) {
        // Set the initial spinner text immediately
        const initialText = isNewChat
            ? $text('enter_message.status.generating_title')
            : $text('enter_message.status.analyzing_message');

        processingPhase = {
            phase: 'processing',
            statusLines: [initialText],
            showIcon: true,
            completedSteps: [],
        };
    }

    /**
     * Apply the typing phase transition to the processing overlay.
     * Builds status lines from resolved mate/model/provider info and transitions
     * processingPhase from 'processing' → 'typing'.
     * Extracted as a named function so it can be called both immediately and after a
     * minimum display delay (when step cards need time to be read).
     */
    function applyTypingPhaseTransition(
        resolvedCategory: string | undefined,
        resolvedModelName: string | undefined,
        resolvedProviderName: string | undefined,
        resolvedServerRegion: string | undefined,
    ) {
        if (resolvedCategory) {
            const mateName = $text('mates.' + resolvedCategory);
            const displayModelName = resolvedModelName ? getModelDisplayName(resolvedModelName) : '';
            const displayProviderName = resolvedProviderName || '';
            const displayServerRegion = resolvedServerRegion || '';

            // Build region flag for display
            const getRegionFlag = (region: string): string => {
                switch (region) {
                    case 'EU': return '\u{1F1EA}\u{1F1FA}';
                    case 'US': return '\u{1F1FA}\u{1F1F8}';
                    case 'APAC': return '\u{1F30F}';
                    default: return '';
                }
            };
            const regionFlag = displayServerRegion ? getRegionFlag(displayServerRegion) : '';

            const lines: string[] = [
                $text('enter_message.is_typing').replace('{mate}', mateName)
            ];
            // Line 2: model name
            if (displayModelName) {
                lines.push(displayModelName);
            }
            // Line 3: "via {provider} {flag}"
            if (displayProviderName) {
                const providerLine = regionFlag ? `via ${displayProviderName} ${regionFlag}` : `via ${displayProviderName}`;
                lines.push(providerLine);
            }

            processingPhase = { phase: 'typing', statusLines: lines, showIcon: true };
            console.debug('[ActiveChat] Processing phase set to TYPING', { mateName, displayModelName, displayProviderName, displayServerRegion, lineCount: lines.length });
        }
    }

    // Track if the message input has content (draft) using $state
    let messageInputHasContent = $state(false);
    // Track live input text for incremental search in new chat suggestions
    let liveInputText = $state('');
    
    // Track if user is at bottom of chat (from scrolledToBottom event)
    // Initialize to false to prevent MessageInput from appearing expanded on initial load
    // Will be set correctly by loadChat() or handleScrollPositionUI() once scroll position is determined
    let isAtBottom = $state(false);
    
    // Track if user is at top of chat (for scroll-to-top button visibility)
    let isAtTop = $state(true);
    
    // Track if message input is focused (for showing follow-up suggestions)
    let messageInputFocused = $state(false);

    // Track follow-up suggestions for the current chat
    let followUpSuggestions = $state<string[]>([]);
    
    // Track settings/memories suggestions for the current chat
    // These are suggested entries generated during AI post-processing Phase 2
    // Shown as horizontally scrollable cards below the last AI response
    let settingsMemoriesSuggestions = $state<import('../types/apps').SuggestedSettingsMemoryEntry[]>([]);
    
    // Track rejected suggestion hashes for client-side filtering
    let rejectedSuggestionHashes = $state<string[] | null>(null);
    
    // Track if user has sent a message this session (for push notification banner)
    // Banner should show after user's first message is sent
    let userSentFirstMessage = $state(false);

    // Track container width for responsive design (JS-based instead of CSS media queries)
    let containerWidth = $state(0);
    
    // Handler for logout event - declared at component level for cleanup
    let handleLogoutEvent: (() => void) | null = null;
    
    // Derived responsive breakpoint states based on actual container width
    // This provides reliable responsive behavior regardless of viewport size
    let isNarrow = $derived(containerWidth > 0 && containerWidth <= 730);
    let isMedium = $derived(containerWidth > 730 && containerWidth <= 1099);
    let isWide = $derived(containerWidth > 1099 && containerWidth <= 1700);
    let isExtraWide = $derived(containerWidth > 1700);
    
    // Side-by-side mode: When container is >= 1024px, show fullscreen embeds side-by-side with chat
    // instead of as overlays. This threshold accommodates iPad landscape (1024px+) and wider displays.
    // The chat panel is fixed at 400px, leaving 600+ px for the embed fullscreen content.
    let isUltraWide = $derived(containerWidth >= 1024);
    
    // Force overlay mode: When true, forces the embed fullscreen to use overlay mode even on ultra-wide screens
    // This is toggled by the "minimize chat" button in the chat's top bar when in side-by-side mode
    // User can click this to temporarily hide the chat and show only the embed fullscreen
    let forceOverlayMode = $state(false);
    
    // Determine if we should use side-by-side layout for fullscreen embeds
    // Only use side-by-side when ultra-wide AND an embed fullscreen is open AND not forcing overlay mode
    let showSideBySideFullscreen = $derived(isUltraWide && showEmbedFullscreen && embedFullscreenData && !forceOverlayMode);
    
    // Determine if we should show the "Show Chat" button in fullscreen embed views
    // Shows when ultra-wide screen has an embed fullscreen open but chat is hidden (forceOverlayMode)
    let showChatButtonInFullscreen = $derived(isUltraWide && showEmbedFullscreen && embedFullscreenData && forceOverlayMode);
    
    // ===========================================
    // Side-by-side Animation System
    // ===========================================
    // Controls smooth transitions between:
    // 1. Full-width chat <-> side-by-side (chat + fullscreen panel)
    // 2. Side-by-side <-> fullscreen only (chat minimized)
    //
    // Animation states track visual layout independently from logical state
    // to allow exit animations to complete before elements are removed
    
    // Animation duration in ms (keep in sync with CSS)
    const SIDE_BY_SIDE_ANIMATION_DURATION = 400;
    
    // Visual state for animations - may differ from logical state during transitions
    let sideBySideVisualState = $state<'full-chat' | 'side-by-side' | 'full-embed'>('full-chat');
    let sideBySideAnimating = $state(false);
    let sideBySideAnimationDirection = $state<'enter' | 'exit' | 'minimize' | 'restore'>('enter');
    
    // Track previous logical state to detect changes
    let prevShowSideBySideFullscreen = $state(false);
    let prevForceOverlayMode = $state(false);
    
    // Effect to handle side-by-side transition animations
    $effect(() => {
        const currentSideBySide = showSideBySideFullscreen;
        const currentForceOverlay = forceOverlayMode;
        
        // Detect state transitions
        const wasFullChat = !prevShowSideBySideFullscreen;
        const wasSideBySide = prevShowSideBySideFullscreen && !prevForceOverlayMode;
        const wasFullEmbed = prevShowSideBySideFullscreen && prevForceOverlayMode;
        
        const isFullChat = !currentSideBySide && !currentForceOverlay;
        const isSideBySide = currentSideBySide && !currentForceOverlay;
        const isFullEmbed = currentSideBySide && currentForceOverlay;
        
        // Determine transition type
        if (wasFullChat && isSideBySide) {
            // Opening embed fullscreen: full-chat -> side-by-side
            sideBySideAnimationDirection = 'enter';
            sideBySideAnimating = true;
            sideBySideVisualState = 'side-by-side';
            setTimeout(() => { sideBySideAnimating = false; }, SIDE_BY_SIDE_ANIMATION_DURATION);
        } else if (wasSideBySide && isFullChat) {
            // Closing embed fullscreen: side-by-side -> full-chat
            sideBySideAnimationDirection = 'exit';
            sideBySideAnimating = true;
            // Keep visual state as side-by-side during animation, then switch
            setTimeout(() => { 
                sideBySideAnimating = false;
                sideBySideVisualState = 'full-chat';
            }, SIDE_BY_SIDE_ANIMATION_DURATION);
        } else if (wasSideBySide && isFullEmbed) {
            // Minimizing chat: side-by-side -> full-embed
            sideBySideAnimationDirection = 'minimize';
            sideBySideAnimating = true;
            setTimeout(() => { 
                sideBySideAnimating = false;
                sideBySideVisualState = 'full-embed';
            }, SIDE_BY_SIDE_ANIMATION_DURATION);
        } else if (wasFullEmbed && isSideBySide) {
            // Restoring chat: full-embed -> side-by-side
            sideBySideAnimationDirection = 'restore';
            sideBySideAnimating = true;
            sideBySideVisualState = 'side-by-side';
            setTimeout(() => { sideBySideAnimating = false; }, SIDE_BY_SIDE_ANIMATION_DURATION);
        } else if (!sideBySideAnimating) {
            // Direct state change without animation (e.g., initial load, screen resize)
            if (isSideBySide) {
                sideBySideVisualState = 'side-by-side';
            } else if (isFullEmbed) {
                sideBySideVisualState = 'full-embed';
            } else {
                sideBySideVisualState = 'full-chat';
            }
        }
        
        prevShowSideBySideFullscreen = currentSideBySide;
        prevForceOverlayMode = currentForceOverlay;
    });
    
    // Derived states for template - based on visual state for smooth animations
    let showSideBySideLayout = $derived(
        sideBySideVisualState === 'side-by-side' || 
        (sideBySideAnimating && (sideBySideAnimationDirection === 'enter' || sideBySideAnimationDirection === 'exit'))
    );
    let showChatInSideBySide = $derived(
        sideBySideVisualState !== 'full-embed' ||
        (sideBySideAnimating && sideBySideAnimationDirection === 'restore')
    );
    
    // Effective narrow mode: True when chat container is narrow OR when in side-by-side mode
    // In side-by-side mode, the chat is limited to 400px which requires narrow/mobile styling
    // This is used for container-based responsive behavior instead of viewport-based
    let isEffectivelyNarrow = $derived(isNarrow || showSideBySideLayout);

    // Hide the welcome greeting and resume-chat card on mobile when the keyboard is open.
    // This frees up vertical space so the input area isn't squeezed against the keyboard.
    let hideWelcomeForKeyboard = $derived(messageInputFocused && isEffectivelyNarrow);

    // Effective chat width: The actual width of the chat area
    // In side-by-side mode, the chat is constrained to 400px regardless of container width
    // This is passed to ChatHistory/ChatMessage for proper responsive behavior
    let effectiveChatWidth = $derived(showSideBySideLayout ? 400 : containerWidth);

    // Debug suggestions visibility
    $effect(() => {
        console.debug('[ActiveChat] Suggestions visibility check:', {
            showWelcome,
            showActionButtons,
            isAtBottom,
            messageInputFocused,
            messageInputHasContent,
            followUpSuggestionsCount: followUpSuggestions.length,
            shouldShowFollowUp: showFollowUpSuggestions,
            shouldShowNewChat: showWelcome && showActionButtons
        });
    });

    // Reactive variable to determine when to show the create chat button using Svelte 5 $derived.
    // The button appears when the chat history is not empty or when there's a draft.
    let createButtonVisible = $derived(!showWelcome || messageInputHasContent);
    
    // Add state for current chat and messages using $state - MUST be declared before $derived that uses them
    let currentChat = $state<Chat | null>(null);
    let currentMessages = $state<ChatMessageModel[]>([]); // Holds messages for the currentChat - MUST use $state for Svelte 5 reactivity
    // CRITICAL: Must use $state() for Svelte 5 reactivity - otherwise store subscription updates
    // won't trigger re-evaluation of $derived values that depend on this variable
    let currentTypingStatus = $state<AITypingStatus | null>(null);
    
    // Thinking/Reasoning state for thinking models (Gemini, Anthropic Claude)
    // Map of task_id -> thinking content, streaming status, and signature metadata
    let thinkingContentByTask = $state<Map<string, { content: string; isStreaming: boolean; signature?: string | null; totalTokens?: number | null }>>(new Map());
    
    // ===========================================
    // Embed Navigation Derived States
    // ===========================================
    // These derived values enable navigation between embeds in the current chat
    
    // Derived list of all embed IDs in the current chat (in order of appearance)
    // This updates whenever currentMessages changes
    let chatEmbedIds = $derived(extractEmbedIdsFromMessages(currentMessages));
    
    // Derived current embed index - finds position of current embed in the chat's embed list
    let currentEmbedIndex = $derived.by(() => {
        if (!embedFullscreenData?.embedId || chatEmbedIds.length === 0) {
            return -1;
        }
        return chatEmbedIds.indexOf(embedFullscreenData.embedId);
    });
    
    // Derived navigation states - determine if prev/next buttons should be shown
    let hasPreviousEmbed = $derived(currentEmbedIndex > 0);
    let hasNextEmbed = $derived(currentEmbedIndex >= 0 && currentEmbedIndex < chatEmbedIds.length - 1);
    
    // Reactive variable to determine when to show action buttons in MessageInput
    // Shows when: input has content OR input is focused
    // This ensures buttons are hidden by default until user actively interacts with the input
    let showActionButtons = $derived(
        messageInputHasContent || 
        messageInputFocused
    );
    
    // Reactive variable to determine when to show follow-up suggestions
    // Only show when user has explicitly focused the message input (clicked to type)
    let showFollowUpSuggestions = $derived(!showWelcome && messageInputFocused && followUpSuggestions.length > 0);

    // PII visibility state: tracks whether current chat has sensitive data and if it's revealed
    // Only show the toggle button when the chat actually contains PII-anonymized messages
    let chatHasPII = $derived.by(() => {
        if (!currentMessages || currentMessages.length === 0) return false;
        return currentMessages.some(m => m.pii_mappings && m.pii_mappings.length > 0);
    });
    // Subscribe to PII visibility store to get reactive state updates
    let piiRevealedMap = $state<Map<string, boolean>>(new Map());
    const unsubPiiVisibility = piiVisibilityStore.subscribe(map => {
        piiRevealedMap = map;
    });
    let piiRevealed = $derived(currentChat?.chat_id ? (piiRevealedMap.get(currentChat.chat_id) ?? false) : false);

    /**
     * Cumulative PII mappings from all user messages in the current chat.
     * Mirrors the same derivation in ChatHistory.svelte so that embed components
     * (both imperatively-mounted previews via embedPIIStore, and template-bound
     * fullscreen components via props) receive the same mapping data.
     */
    let cumulativePIIMappingsArray = $derived.by(() => {
        const allMappings: PIIMapping[] = [];
        for (const msg of currentMessages) {
            if (msg.role === 'user' && msg.pii_mappings && msg.pii_mappings.length > 0) {
                allMappings.push(...msg.pii_mappings);
            }
        }
        return allMappings;
    });

    /**
     * Keep the global embedPIIStore in sync with the current chat's PII state.
     * This drives the imperatively-mounted preview components (DocsEmbedPreview,
     * CodeEmbedPreview, SheetEmbedPreview) which cannot receive reactive props.
     * Runs whenever the cumulative mappings or the reveal toggle changes.
     */
    $effect(() => {
        if (currentChat?.chat_id) {
            setEmbedPIIState(cumulativePIIMappingsArray, piiRevealed);
        } else {
            resetEmbedPIIState();
        }
    });

    /** Toggle PII visibility for the current chat */
    function handleTogglePIIVisibility() {
        if (currentChat?.chat_id) {
            piiVisibilityStore.toggle(currentChat.chat_id);
        }
    }
    
    // Effect to reload follow-up suggestions when MessageInput is focused but suggestions are empty
    // This handles the case where suggestions were stored in the database but weren't loaded
    // in-memory (e.g., after post-processing completes but the event handler didn't fire)
    $effect(() => {
        if (messageInputFocused && !showWelcome && currentChat?.chat_id && followUpSuggestions.length === 0) {
            // CRITICAL: Skip suggestion reload if logout is in progress
            // This prevents database access attempts during logout cleanup
            if ($isLoggingOut) {
                console.debug('[ActiveChat] Skipping suggestion reload - logout in progress');
                return;
            }

            // Check for cleartext suggestions first (demo chats)
            if (currentChat.follow_up_request_suggestions) {
                console.debug('[ActiveChat] Loading cleartext follow-up suggestions for demo chat');
                try {
                    const suggestions = JSON.parse(currentChat.follow_up_request_suggestions);
                    if (suggestions && suggestions.length > 0) {
                        followUpSuggestions = suggestions;
                        console.info('[ActiveChat] Loaded cleartext follow-up suggestions on focus:', suggestions.length);
                    }
                } catch (error) {
                    console.error('[ActiveChat] Failed to parse cleartext follow-up suggestions:', error);
                }
            } else if (currentChat.encrypted_follow_up_request_suggestions) {
                // Try to reload encrypted suggestions for regular chats
                console.debug('[ActiveChat] MessageInput focused but no suggestions - attempting to reload from database');
                // Use an IIFE to handle async operations
                (async () => {
                    try {
                        const chatKey = chatDB.getOrGenerateChatKey(currentChat.chat_id);
                        const { decryptArrayWithChatKey } = await import('../services/cryptoService');
                        const decryptedSuggestions = await decryptArrayWithChatKey(
                            currentChat.encrypted_follow_up_request_suggestions, 
                            chatKey
                        );
                        if (decryptedSuggestions && decryptedSuggestions.length > 0) {
                            followUpSuggestions = decryptedSuggestions;
                            console.info('[ActiveChat] Reloaded follow-up suggestions on focus:', decryptedSuggestions.length);
                        }
                    } catch (error) {
                        console.error('[ActiveChat] Failed to reload follow-up suggestions on focus:', error);
                    }
                })();
            } else {
                // Try to refresh chat from database in case it was updated
                console.debug('[ActiveChat] No suggestions in currentChat - checking database');
                (async () => {
                    try {
                        const freshChat = await chatDB.getChat(currentChat.chat_id);
                        // Check for cleartext suggestions first (demo chats)
                        if (freshChat?.follow_up_request_suggestions) {
                            try {
                                const suggestions = JSON.parse(freshChat.follow_up_request_suggestions);
                                if (suggestions && suggestions.length > 0) {
                                    followUpSuggestions = suggestions;
                                    currentChat = { ...currentChat, ...freshChat };
                                    console.info('[ActiveChat] Loaded cleartext follow-up suggestions from fresh database read:', suggestions.length);
                                }
                            } catch (parseError) {
                                console.error('[ActiveChat] Failed to parse cleartext follow-up suggestions:', parseError);
                            }
                        } else if (freshChat?.encrypted_follow_up_request_suggestions) {
                            const chatKey = chatDB.getOrGenerateChatKey(currentChat.chat_id);
                            const { decryptArrayWithChatKey } = await import('../services/cryptoService');
                            const decryptedSuggestions = await decryptArrayWithChatKey(
                                freshChat.encrypted_follow_up_request_suggestions, 
                                chatKey
                            );
                            if (decryptedSuggestions && decryptedSuggestions.length > 0) {
                                followUpSuggestions = decryptedSuggestions;
                                // Also update currentChat to have the latest data
                                currentChat = { ...currentChat, ...freshChat };
                                console.info('[ActiveChat] Loaded follow-up suggestions from fresh database read:', decryptedSuggestions.length);
                            }
                        }
                    } catch (error) {
                        console.error('[ActiveChat] Failed to load suggestions from database on focus:', error);
                    }
                })();
            }
        }
    });
    
    // Removed loading state - no more loading screen
    
    // Generate a temporary chat ID for draft saving when no chat is loaded
    // This ensures the draft service always has a chat ID to work with
    let temporaryChatId = $state<string | null>(null);

    // Subscribe to AI typing store
    const unsubscribeAiTyping = aiTypingStore.subscribe(value => { // Store unsubscribe function
        currentTypingStatus = value;
    });

    // Subscribe to draftEditorUIState to handle newly created chats
    const unsubscribeDraftState = draftEditorUIState.subscribe(async value => {
        if (value.newlyCreatedChatIdToSelect) {
            console.debug(`[ActiveChat] draftEditorUIState signals new chat to select: ${value.newlyCreatedChatIdToSelect}`);
            // Load the newly created chat
            const newChat = await chatDB.getChat(value.newlyCreatedChatIdToSelect);
            if (newChat) {
                currentChat = newChat;
                // Clear temporary chat ID since we now have a real chat
                temporaryChatId = null;
                console.debug("[ActiveChat] Loaded newly created chat, cleared temporary chat ID");
                
                // CRITICAL: Sync liveInputText after new chat is created and loaded
                // This ensures the search term is preserved when a new chat is created from a draft
                setTimeout(() => {
                    if (messageInputFieldRef) {
                        try {
                            const currentText = messageInputFieldRef.getTextContent();
                            if (currentText.trim().length > 0 && currentText !== liveInputText) {
                                liveInputText = currentText;
                                console.debug('[ActiveChat] Synced liveInputText after new chat creation:', { 
                                    text: currentText, 
                                    length: currentText.length 
                                });
                            }
                        } catch (error) {
                            console.warn('[ActiveChat] Failed to sync liveInputText after new chat creation:', error);
                        }
                    }
                }, 150); // Delay to ensure editor content is stable after chat creation
                
                // Notify backend about the active chat
                chatSyncService.sendSetActiveChat(currentChat.chat_id);
                
                // Update URL hash with the new chat ID
                // This ensures the URL reflects the active chat even when
                // Chats.svelte is not mounted (e.g., sidebar closed on mobile)
                activeChatStore.setActiveChat(currentChat.chat_id);
                console.debug("[ActiveChat] Updated URL hash via draftEditorUIState for chat:", currentChat.chat_id);
            }
            // Reset the signal
            draftEditorUIState.update(s => ({ ...s, newlyCreatedChatIdToSelect: null }));
        }
    });

    // Reactive variable for typing indicator lines (shown at the bottom, above message input).
    // PROGRESSIVE STATUS INDICATOR: The centered overlay (processingPhase) handles:
    //   - "Sending..." → "Generating chat title..." → "Selecting AI model..." → "{Mate} is typing..."
    // The bottom indicator only shows during STREAMING (when processingPhase is null but AI is still typing).
    // Exception: "Waiting for you..." is always shown at the bottom (not part of the centered flow).
    //
    // Returns an array of lines matching the centered overlay format:
    //   Line 1 (primary):   "{mate} is typing..."
    //   Line 2 (secondary): "Powered by {model_name}"
    //   Line 3 (tertiary):  "via {provider} {flag}"
    let typingIndicatorLines = $derived((() => {
        // _aiTaskStateTrigger is a top-level reactive variable.
        // Its change will trigger re-evaluation of this derived value.
        void _aiTaskStateTrigger;
        
        // Check if there's a message in waiting_for_user state (e.g., insufficient credits, app settings permission)
        const hasWaitingForUserMessage = currentMessages.some(m => 
            m.status === 'waiting_for_user' && m.chat_id === currentChat?.chat_id
        );
        
        // Show "Waiting for you..." if chat is paused waiting for user action
        // This is ALWAYS shown at the bottom (not part of the centered indicator flow)
        if (hasWaitingForUserMessage) {
            const result = $text('enter_message.waiting_for_user');
            console.debug('[ActiveChat] Showing waiting_for_user indicator:', result);
            return [result]; // Single line
        }
        
        // When the centered indicator is active (processingPhase is not null),
        // hide the bottom typing indicator to avoid duplicate text.
        // The centered overlay handles sending, processing steps, and typing phases.
        if (processingPhase !== null) {
            return [];
        }
        
        // Show detailed AI typing indicator once streaming has started
        // (processingPhase is null, meaning the centered indicator has faded out,
        //  but aiTypingStore still shows isTyping = true during streaming)
        if (currentTypingStatus?.isTyping && currentTypingStatus.chatId === currentChat?.chat_id && currentTypingStatus.category) {
            const mateName = $text('mates.' + currentTypingStatus.category);
            const modelName = currentTypingStatus.modelName || ''; 
            const providerName = currentTypingStatus.providerName || '';
            const serverRegion = currentTypingStatus.serverRegion || '';
            
            // Get region flag for display (e.g., "EU" -> "🇪🇺", "US" -> "🇺🇸", "APAC" -> "🌏")
            const getRegionFlag = (region: string): string => {
                switch (region) {
                    case 'EU': return '🇪🇺';
                    case 'US': return '🇺🇸';
                    case 'APAC': return '🌏';
                    default: return '';
                }
            };
            
            // Build multi-line indicator matching the centered overlay format:
            //   Line 1: "{mate} is typing..."
            //   Line 2: "Powered by {model_name}" (if available)
            //   Line 3: "via {provider} {flag}" (if available)
            const lines: string[] = [
                $text('enter_message.is_typing').replace('{mate}', mateName)
            ];
            
            // Line 2: "Powered by {model_name}" — convert technical IDs to human-readable names
            const displayModelName = modelName ? getModelDisplayName(modelName) : '';
            if (displayModelName) {
                lines.push(`Powered by ${displayModelName}`);
            }
            
            // Line 3: "via {provider} {flag}" — with country flag at the bottom
            if (providerName) {
                const regionFlag = serverRegion ? getRegionFlag(serverRegion) : '';
                const providerLine = regionFlag ? `via ${providerName} ${regionFlag}` : `via ${providerName}`;
                lines.push(providerLine);
            }
            
            console.debug('[ActiveChat] AI typing indicator lines:', lines);
            return lines;
        }
        console.debug('[ActiveChat] Typing indicator: no status to show');
        return []; // No indicator
    })());

    // Track the current status type for CSS styling (shimmer animation) on the BOTTOM indicator.
    // Returns: 'typing' | 'waiting_for_user' | null
    // 'sending' and 'processing' are no longer shown at the bottom — they're in the centered overlay.
    let typingIndicatorStatusType = $derived.by(() => {
        void _aiTaskStateTrigger;
        
        // "Waiting for you..." is always shown at the bottom
        const hasWaitingForUserMessage = currentMessages.some(m => 
            m.status === 'waiting_for_user' && m.chat_id === currentChat?.chat_id
        );
        if (hasWaitingForUserMessage) return 'processing'; // Reuse 'processing' CSS class for shimmer effect
        
        // When centered indicator is active, bottom shows nothing
        if (processingPhase !== null) return null;
        
        // During streaming, show the typing shimmer
        if (currentTypingStatus?.isTyping && currentTypingStatus.chatId === currentChat?.chat_id) {
            return 'typing';
        }
        
        return null;
    });


    // Convert plain text to Tiptap JSON for UI rendering only
    // CRITICAL: This is only for UI display, never stored in database
    // Prefixed with underscore as currently unused but kept for potential future use
    function _plainTextToTiptapJson(text: string): TiptapJSON {
        return {
            type: 'doc',
            content: [
                {
                    type: 'paragraph',
                    content: text ? [{ type: 'text', text: text }] : [],
                },
            ],
        };
    }

    // Handler for AI message chunks (streaming)
    async function handleAiMessageChunk(event: CustomEvent) {
        // 🔍 STREAMING DEBUG: Log handler invocation immediately
        console.log(`[ActiveChat] 🎯 HANDLER INVOKED | event received at ${new Date().toISOString()}`);
        
        const chunk = event.detail as AiMessageChunkPayload; // AIMessageUpdatePayload
        const timestamp = new Date().toISOString();
        const contentLength = chunk.full_content_so_far?.length || 0;
        
        // 🔍 STREAMING DEBUG: Log chunk processing start
        console.log(
            `[ActiveChat] 🟡 CHUNK PROCESSING START | ` +
            `seq: ${chunk.sequence} | ` +
            `chat_id: ${chunk.chat_id} | ` +
            `message_id: ${chunk.message_id} | ` +
            `content_length: ${contentLength} chars | ` +
            `is_final: ${chunk.is_final_chunk} | ` +
            `timestamp: ${timestamp}`
        );
        
        console.debug(`[ActiveChat] handleAiMessageChunk: Event for chat_id: ${chunk.chat_id}. Current active chat_id: ${currentChat?.chat_id}`);
        console.log(
            `[ActiveChat] 🔍 CHAT STATE CHECK | ` +
            `currentChat exists: ${!!currentChat} | ` +
            `currentChat.chat_id: ${currentChat?.chat_id || 'null'} | ` +
            `chunk.chat_id: ${chunk.chat_id} | ` +
            `match: ${currentChat?.chat_id === chunk.chat_id}`
        );

        // NOTE: When creating a brand-new chat, AI chunks can arrive before `currentChat` is set.
        // Fall back to `currentMessages` so we don't drop fast error responses (e.g. credit limits).
        const effectiveChatId = currentChat?.chat_id || currentMessages?.[0]?.chat_id || null;

        if (!effectiveChatId || effectiveChatId !== chunk.chat_id) {
            console.warn(
                `[ActiveChat] ⚠️ CHUNK IGNORED (wrong chat) | ` +
                `seq: ${chunk.sequence} | ` +
                `effective_chat: ${effectiveChatId || 'null'} | ` +
                `chunk_chat: ${chunk.chat_id} | ` +
                `currentChat exists: ${!!currentChat}`
            );
            return;
        }

        // FALLBACK: Mark thinking as complete when we start receiving the actual response
        // This ensures the "Thinking..." state ends even if thinking_complete event is missed
        // The message_id in the chunk should match the task_id used for thinking
        const thinkingEntry = thinkingContentByTask.get(chunk.message_id);
        if (thinkingEntry && thinkingEntry.isStreaming) {
            console.log(`[ActiveChat] 🧠 Marking thinking as complete (fallback) | message_id: ${chunk.message_id}`);
            thinkingContentByTask.set(chunk.message_id, {
                content: thinkingEntry.content,
                isStreaming: false,
                signature: thinkingEntry.signature,
                totalTokens: thinkingEntry.totalTokens
            });
            // Force reactivity by creating new Map
            thinkingContentByTask = new Map(thinkingContentByTask);
        }

        // Operate on currentMessages state
        let targetMessageIndex = currentMessages.findIndex(m => m.message_id === chunk.message_id);
        let targetMessage: ChatMessageModel | null = targetMessageIndex !== -1 ? { ...currentMessages[targetMessageIndex] } : null;

        let messageToSave: ChatMessageModel | null = null;
        let isNewMessageInStream = false;
        let previousContentLengthForPersistence = 0;
        let newContentLengthForPersistence = 0;

        if (!targetMessage) {
            // Detect if this is a system rejection message (e.g., insufficient credits)
            // These should be rendered as system notices, not as assistant bubbles
            const isRejectionMessage = !!chunk.rejection_reason;
            
            // Create a streaming AI message even if sequence is not 1 to avoid dropping chunks
            const fallbackCategory = currentTypingStatus?.chatId === chunk.chat_id ? currentTypingStatus.category : undefined;
            const fallbackModelName = currentTypingStatus?.chatId === chunk.chat_id ? currentTypingStatus.modelName : undefined;
            const newAiMessage: ChatMessageModel = {
                message_id: chunk.message_id,
                chat_id: chunk.chat_id, // Ensure this is correct
                user_message_id: chunk.user_message_id,
                // System rejection messages (e.g., insufficient credits) use role 'system' 
                // so they render as smaller system notices instead of assistant bubbles
                role: isRejectionMessage ? 'system' : 'assistant',
                category: chunk.category || fallbackCategory,
                model_name: chunk.model_name || fallbackModelName || undefined,
                content: chunk.full_content_so_far || '', // Store as markdown string, not Tiptap JSON
                // System rejection messages get 'waiting_for_user' status so the chat shows
                // "Waiting for you..." instead of "Sending..." in the sidebar and typing indicator
                status: isRejectionMessage ? 'waiting_for_user' : 'streaming',
                created_at: Math.floor(Date.now() / 1000),
                // Required encrypted fields (will be populated by encryptMessageFields)
                encrypted_content: '', // Will be set by encryption
                // encrypted_sender_name not needed for assistant messages
                encrypted_category: undefined
            };

            console.debug(`[ActiveChat] Created new AI message with model_name: "${newAiMessage.model_name}" for message ${newAiMessage.message_id}`, {
                chunkModelName: chunk.model_name,
                fallbackModelName: fallbackModelName,
                finalModelName: newAiMessage.model_name,
                chatId: chunk.chat_id
            });
            currentMessages = [...currentMessages, newAiMessage];
            messageToSave = newAiMessage;
            isNewMessageInStream = true;
            previousContentLengthForPersistence = 0;
            newContentLengthForPersistence = newAiMessage.content.length;
            
            // ─── Progressive AI Status Indicator: Clear after render ─────
            // Wait one Svelte tick so the new assistant message is rendered in the DOM
            // before fading out the centered overlay. This prevents a visual gap where
            // neither the overlay nor the message bubble is visible.
            tick().then(() => {
                clearProcessingPhase();
                console.debug('[ActiveChat] Processing phase cleared (first streaming chunk rendered)');
            });
            
            console.log(
                `[ActiveChat] 🆕 NEW MESSAGE CREATED | ` +
                `seq: ${chunk.sequence} | ` +
                `message_id: ${chunk.message_id} | ` +
                `content_length: ${newAiMessage.content.length} chars`
            );
            console.debug('[ActiveChat] Created new AI message for streaming:', newAiMessage);
        } else {
            // Update existing message
            const previousLength = targetMessage.content?.length || 0;
            const newLength = chunk.full_content_so_far?.length || 0;
            const lengthDiff = newLength - previousLength;
            const fallbackModelName = currentTypingStatus?.chatId === chunk.chat_id ? currentTypingStatus.modelName : undefined;
            
            // Only update content if full_content_so_far is not empty,
            // or if it's the first chunk (sequence 1) where it might legitimately start empty.
            if (chunk.full_content_so_far || chunk.sequence === 1) {
                // CRITICAL: Store AI response as markdown string, not Tiptap JSON
                targetMessage.content = chunk.full_content_so_far || '';
            }
            // If this is a rejection message, update role and status accordingly
            if (chunk.rejection_reason && targetMessage.role !== 'system') {
                targetMessage.role = 'system';
                targetMessage.status = 'waiting_for_user';
            } else if (targetMessage.status !== 'streaming' && !chunk.rejection_reason) {
                targetMessage.status = 'streaming';
            }
            // Update model_name if we have a new value and current value is missing or undefined
            const newModelName = chunk.model_name || fallbackModelName;
            if (!targetMessage.model_name && newModelName) {
                targetMessage.model_name = newModelName;
                console.debug(`[ActiveChat] Updated message ${targetMessage.message_id} with model_name: "${targetMessage.model_name}"`, {
                    chunkModelName: chunk.model_name,
                    fallbackModelName: fallbackModelName,
                    finalModelName: targetMessage.model_name
                });
            }
            currentMessages[targetMessageIndex] = targetMessage;
            currentMessages = [...currentMessages]; // New array reference for Svelte reactivity
            messageToSave = targetMessage;
            previousContentLengthForPersistence = previousLength;
            newContentLengthForPersistence = targetMessage.content?.length || 0;
            
            // 🔍 STREAMING DEBUG: Log content update
            console.log(
                `[ActiveChat] 📝 MESSAGE UPDATED | ` +
                `seq: ${chunk.sequence} | ` +
                `message_id: ${chunk.message_id} | ` +
                `previous_length: ${previousLength} chars | ` +
                `new_length: ${newLength} chars | ` +
                `diff: ${lengthDiff > 0 ? '+' : ''}${lengthDiff} chars`
            );
        }
        
        // Update UI
        if (chatHistoryRef) {
            console.log(
                `[ActiveChat] 🎨 UI UPDATE | ` +
                `seq: ${chunk.sequence} | ` +
                `message_id: ${chunk.message_id} | ` +
                `calling chatHistoryRef.updateMessages() with ${currentMessages.length} messages`
            );
            chatHistoryRef.updateMessages(currentMessages);
        } else {
            console.warn(`[ActiveChat] ⚠️ chatHistoryRef is null, cannot update UI (seq: ${chunk.sequence})`);
        }

        // Save to IndexedDB or incognito service
        if (messageToSave) {
            try {
                const saveStartTime = performance.now();
                
                // Check if this is an incognito chat
                const { incognitoChatService } = await import('../services/incognitoChatService');
                let isIncognitoChat = false;
                try {
                    const incognitoChat = await incognitoChatService.getChat(messageToSave.chat_id);
                    if (incognitoChat) {
                        isIncognitoChat = true;
                    }
                } catch {
                    // Not an incognito chat - silently ignore
                }
                
                if (isIncognitoChat) {
                    // Save to incognito service
                    const existingMessages = await incognitoChatService.getMessagesForChat(messageToSave.chat_id);
                    const existingMessage = existingMessages.find(m => m.message_id === messageToSave.message_id);
                    if (existingMessage && !isNewMessageInStream) {
                        // Update existing message
                        const messageIndex = existingMessages.findIndex(m => m.message_id === messageToSave.message_id);
                        existingMessages[messageIndex] = messageToSave;
                    } else {
                        // Add new message
                        existingMessages.push(messageToSave);
                    }
                    await incognitoChatService.storeMessages(messageToSave.chat_id, existingMessages);
                    const saveDuration = performance.now() - saveStartTime;
                    console.log(
                        `[ActiveChat] ✅ INCOGNITO SAVE COMPLETE | ` +
                        `seq: ${chunk.sequence} | ` +
                        `message_id: ${messageToSave.message_id} | ` +
                        `duration: ${saveDuration.toFixed(2)}ms`
                    );
                } else {
                    // Save to IndexedDB
                    // Do not "skip on existence": we need to persist streaming content updates
                    // (placeholders often exist before the first chunk arrives).
                    // We save on: first chunk, final chunk, first-content-after-empty, and
                    // every 5th chunk as a safety net so content isn't lost if the final
                    // chunk is missed (e.g., WebSocket disconnect during streaming).
                    const isPeriodicSave = chunk.sequence > 0 && chunk.sequence % 5 === 0;
                    const shouldPersistChunk =
                        isNewMessageInStream ||
                        chunk.is_final_chunk ||
                        isPeriodicSave ||
                        (previousContentLengthForPersistence === 0 && newContentLengthForPersistence > 0);

                    if (shouldPersistChunk) {
                    console.log(
                        `[ActiveChat] 💾 DB SAVE START | ` +
                        `seq: ${chunk.sequence} | ` +
                        `message_id: ${messageToSave.message_id} | ` +
                        `isNew: ${isNewMessageInStream} | ` +
                        `content_length: ${messageToSave.content.length} chars`
                    );
                    console.debug(`[ActiveChat] About to save message with model_name: "${messageToSave.model_name}" for message ${messageToSave.message_id}`);
                    await chatDB.saveMessage(messageToSave); // saveMessage handles both add and update
                    const saveDuration = performance.now() - saveStartTime;
                    console.log(
                        `[ActiveChat] ✅ DB SAVE COMPLETE | ` +
                        `seq: ${chunk.sequence} | ` +
                        `message_id: ${messageToSave.message_id} | ` +
                        `duration: ${saveDuration.toFixed(2)}ms`
                    );
                    } else {
                        console.log(
                            `[ActiveChat] 💾 DB SAVE SKIPPED (no-op chunk) | ` +
                            `seq: ${chunk.sequence} | ` +
                            `message_id: ${messageToSave.message_id} | ` +
                            `prev_len: ${previousContentLengthForPersistence} | new_len: ${newContentLengthForPersistence}`
                        );
                    }
                }
            } catch (error) {
                console.error(
                    `[ActiveChat] ❌ DB SAVE ERROR | ` +
                    `seq: ${chunk.sequence} | ` +
                    `message_id: ${messageToSave.message_id} | ` +
                    `error:`, error
                );
            }
        }

        if (chunk.is_final_chunk) {
            console.log(
                `[ActiveChat] 🏁 FINAL CHUNK PROCESSED | ` +
                `seq: ${chunk.sequence} | ` +
                `message_id: ${chunk.message_id} | ` +
                `total_content_length: ${chunk.full_content_so_far?.length || 0} chars`
            );
            console.debug('[ActiveChat] Final AI chunk marker received for message_id:', chunk.message_id);
            const finalMessageInArray = currentMessages.find(m => m.message_id === chunk.message_id);
            if (finalMessageInArray) {
                // CRITICAL FIX: Ensure model_name is preserved in final message
                const fallbackModelName = currentTypingStatus?.chatId === chunk.chat_id ? currentTypingStatus.modelName : undefined;
                const finalModelName = finalMessageInArray.model_name || chunk.model_name || fallbackModelName;

                // Attach thinking metadata to the final message so it persists across devices.
                const thinkingEntry = thinkingContentByTask.get(chunk.message_id);
                // For rejection messages (e.g., insufficient credits), keep 'waiting_for_user' status
                // so the chat shows "Waiting for you..." instead of appearing as a completed response
                const isRejection = !!chunk.rejection_reason;
                const finalStatus = isRejection ? 'waiting_for_user' as const : 'synced' as const;
                const updatedFinalMessage = {
                    ...finalMessageInArray,
                    status: finalStatus,
                    // Preserve role as 'system' for rejection messages
                    role: isRejection ? 'system' as const : finalMessageInArray.role,
                    model_name: finalModelName, // Explicitly preserve/set model_name
                    thinking_content: thinkingEntry?.content || finalMessageInArray.thinking_content,
                    thinking_signature: thinkingEntry?.signature || finalMessageInArray.thinking_signature,
                    thinking_token_count: thinkingEntry?.totalTokens ?? finalMessageInArray.thinking_token_count,
                    has_thinking: !!(thinkingEntry?.content || finalMessageInArray.thinking_content)
                };

                console.debug(`[ActiveChat] Final chunk - preserving model_name: "${finalModelName}" for message ${chunk.message_id}`, {
                    originalModelName: finalMessageInArray.model_name,
                    chunkModelName: chunk.model_name,
                    fallbackModelName: fallbackModelName,
                    finalModelName: finalModelName
                });
                
                // Update in currentMessages array for UI
                const finalMessageIndex = currentMessages.findIndex(m => m.message_id === chunk.message_id);
                if (finalMessageIndex !== -1) {
                    currentMessages[finalMessageIndex] = updatedFinalMessage;
                    currentMessages = [...currentMessages]; // Ensure reactivity for UI
                }

                // CRITICAL FIX: Also update the corresponding user message status from 'sending' to appropriate status
                // For rejection messages (e.g., insufficient credits): set to 'waiting_for_user' so the sidebar shows "Waiting for you..."
                // For normal responses: set to 'synced' to prevent infinite "Sending..." state
                if (chunk.user_message_id) {
                    const userMessageIndex = currentMessages.findIndex(m => m.message_id === chunk.user_message_id);
                    const userMessageStatus = isRejection ? 'waiting_for_user' as const : 'synced' as const;
                    if (userMessageIndex !== -1 && (currentMessages[userMessageIndex].status === 'sending' || currentMessages[userMessageIndex].status === 'processing')) {
                        const updatedUserMessage = { ...currentMessages[userMessageIndex], status: userMessageStatus };
                        currentMessages[userMessageIndex] = updatedUserMessage;
                        currentMessages = [...currentMessages]; // Ensure reactivity for UI

                        // Save updated user message status to DB
                        try {
                            const { incognitoChatService } = await import('../services/incognitoChatService');
                            let isIncognitoChat = false;
                            try {
                                const incognitoChat = await incognitoChatService.getChat(updatedUserMessage.chat_id);
                                if (incognitoChat) {
                                    isIncognitoChat = true;
                                }
                            } catch {
                                // Not an incognito chat - silently ignore
                            }

                            if (isIncognitoChat) {
                                const existingMessages = await incognitoChatService.getMessagesForChat(updatedUserMessage.chat_id);
                                const messageIndex = existingMessages.findIndex(m => m.message_id === updatedUserMessage.message_id);
                                if (messageIndex !== -1) {
                                    existingMessages[messageIndex] = updatedUserMessage;
                                    await incognitoChatService.storeMessages(updatedUserMessage.chat_id, existingMessages);
                                }
                            } else {
                                await chatDB.saveMessage(updatedUserMessage);
                            }
                            console.debug('[ActiveChat] Updated user message status to synced:', updatedUserMessage.message_id);
                            
                            // CRITICAL: Update the chatListCache so the sidebar shows the correct state.
                            // For rejection messages (e.g., insufficient credits): cache the USER message
                            // so the sidebar can display "Credits needed..." + user message content.
                            // For normal responses: invalidate so the sidebar refreshes from DB.
                            if (isRejection) {
                                chatListCache.setLastMessage(updatedUserMessage.chat_id, updatedUserMessage);
                            } else {
                                chatListCache.invalidateLastMessage(updatedUserMessage.chat_id);
                            }
                        } catch (error) {
                            console.error('[ActiveChat] Error updating user message status:', error);
                        }
                    }
                }

                // Save status update to DB or incognito service
                try {
                    console.debug('[ActiveChat] Updating final AI message status:', updatedFinalMessage);
                    
                    // Check if this is an incognito chat
                    const { incognitoChatService } = await import('../services/incognitoChatService');
                    let isIncognitoChat = false;
                    try {
                        const incognitoChat = await incognitoChatService.getChat(updatedFinalMessage.chat_id);
                        if (incognitoChat) {
                            isIncognitoChat = true;
                        }
                    } catch {
                        // Not an incognito chat - silently ignore
                    }
                    
                    if (isIncognitoChat) {
                        // Save to incognito service
                        const existingMessages = await incognitoChatService.getMessagesForChat(updatedFinalMessage.chat_id);
                        const existingMessage = existingMessages.find(m => m.message_id === updatedFinalMessage.message_id);
                        if (!existingMessage || existingMessage.status !== 'synced') {
                            // Update or add the message
                            if (existingMessage) {
                                // Update existing message
                                const messageIndex = existingMessages.findIndex(m => m.message_id === updatedFinalMessage.message_id);
                                existingMessages[messageIndex] = updatedFinalMessage;
                            } else {
                                // Add new message
                                existingMessages.push(updatedFinalMessage);
                            }
                            await incognitoChatService.storeMessages(updatedFinalMessage.chat_id, existingMessages);
                        } else {
                            console.debug('[ActiveChat] Incognito message already has synced status, skipping save');
                        }
                    } else {
                        // Save to IndexedDB
                        // Only save if the status actually changed to prevent unnecessary saves
                        const existingMessage = await chatDB.getMessage(updatedFinalMessage.message_id);
                        if (!existingMessage || existingMessage.status !== 'synced') {
                            await chatDB.saveMessage(updatedFinalMessage);
                        } else {
                            console.debug('[ActiveChat] Message already has synced status, skipping save');
                        }
                    }
                } catch (error) {
                    console.error('[ActiveChat] Error updating final AI message status:', error);
                }
                
                // CRITICAL: Send encrypted AI response back to server for Directus storage (zero-knowledge architecture)
                // Skip for incognito chats (they're not stored on the server)
                // This uses a separate event type 'ai_response_completed' to avoid triggering AI processing
                if (!currentChat?.is_incognito) {
                    try {
                        console.debug('[ActiveChat] Sending completed AI response to server for encrypted Directus storage:', {
                            messageId: updatedFinalMessage.message_id,
                            chatId: updatedFinalMessage.chat_id,
                            contentLength: updatedFinalMessage.content?.length || 0
                        });
                        await chatSyncService.sendCompletedAIResponse(updatedFinalMessage);
                    } catch (error) {
                        console.error('[ActiveChat] Error sending completed AI response to server:', error);
                    }
                } else {
                    console.debug('[ActiveChat] Skipping server storage for incognito chat - not persisted on server');
                }
                
                if (chatHistoryRef) {
                    chatHistoryRef.updateMessages(currentMessages);
                }
            }
        }
    }

    // --- Thinking/Reasoning Handlers for Thinking Models (Gemini, Anthropic Claude) ---
    
    /**
     * Handle thinking content chunks from thinking models.
     * Accumulates thinking content and triggers UI update.
     * 
     * CRITICAL FIX: Creates a placeholder assistant message when thinking arrives
     * before the main AI response stream. This ensures the thinking/reasoning
     * content is displayed immediately rather than waiting for the first text chunk.
     */
    function handleAiThinkingChunk(event: CustomEvent) {
        const chunk = event.detail as { task_id: string; chat_id: string; content: string; message_id?: string };
        
        // Only process if for current chat
        if (chunk.chat_id !== currentChat?.chat_id) {
            console.debug(`[ActiveChat] Thinking chunk for different chat (${chunk.chat_id}), ignoring`);
            return;
        }
        
        // Use message_id if available, otherwise fall back to task_id (they should be the same)
        const messageId = chunk.message_id || chunk.task_id;
        
        console.log(`[ActiveChat] 🧠 Thinking chunk received | task_id: ${chunk.task_id} | message_id: ${messageId} | length: ${chunk.content?.length || 0}`);
        
        // CRITICAL: Check if an assistant message exists for this task_id/message_id
        // If not, create a placeholder message so the thinking content can be displayed
        // This fixes the issue where thinking content doesn't show until the main response starts
        const existingMessage = currentMessages.find(m => m.message_id === messageId);
        if (!existingMessage) {
            // Get model name from typing status if available
            const fallbackCategory = currentTypingStatus?.chatId === chunk.chat_id ? currentTypingStatus.category : undefined;
            const fallbackModelName = currentTypingStatus?.chatId === chunk.chat_id ? currentTypingStatus.modelName : undefined;
            
            // Create a placeholder assistant message for the thinking phase
            const placeholderMessage: ChatMessageModel = {
                message_id: messageId,
                chat_id: chunk.chat_id,
                role: 'assistant',
                category: fallbackCategory,
                model_name: fallbackModelName,
                content: '', // Empty content - thinking will be shown via thinkingContentByTask
                status: 'streaming', // Mark as streaming so UI shows appropriate state
                created_at: Math.floor(Date.now() / 1000),
                encrypted_content: '',
            };
            
            console.log(`[ActiveChat] 🧠 Created placeholder message for thinking | message_id: ${messageId}`);
            currentMessages = [...currentMessages, placeholderMessage];
            
            // ─── Progressive AI Status Indicator: Clear after render ─────
            // Wait one Svelte tick so the thinking placeholder is rendered in the DOM
            // before fading out the centered overlay.
            tick().then(() => {
                clearProcessingPhase();
                console.debug('[ActiveChat] Processing phase cleared (thinking placeholder rendered)');
            });
        }
        
        // Update thinking content map using message_id (same as task_id)
        const existing = thinkingContentByTask.get(messageId);
        const newContent = (existing?.content || '') + (chunk.content || '');
        
        thinkingContentByTask.set(messageId, {
            content: newContent,
            isStreaming: true,
            signature: existing?.signature,
            totalTokens: existing?.totalTokens
        });
        
        // Force reactivity by creating new Map
        thinkingContentByTask = new Map(thinkingContentByTask);
        
        // Update UI if chatHistoryRef exists
        if (chatHistoryRef) {
            chatHistoryRef.updateMessages(currentMessages);
        }
    }
    
    /**
     * Handle thinking completion from thinking models.
     * Marks thinking as complete (no longer streaming).
     */
    function handleAiThinkingComplete(event: CustomEvent) {
        const payload = event.detail as { task_id: string; chat_id: string; message_id?: string; signature?: string; total_tokens?: number };
        
        // Only process if for current chat
        if (payload.chat_id !== currentChat?.chat_id) {
            console.debug(`[ActiveChat] Thinking complete for different chat (${payload.chat_id}), ignoring`);
            return;
        }
        
        // Use message_id if available, otherwise fall back to task_id (they should be the same)
        const messageId = payload.message_id || payload.task_id;
        
        console.log(`[ActiveChat] 🧠 Thinking complete | task_id: ${payload.task_id} | message_id: ${messageId} | tokens: ${payload.total_tokens || 'unknown'}`);
        
        // Mark thinking as complete (no longer streaming)
        const existing = thinkingContentByTask.get(messageId);
        if (existing) {
            thinkingContentByTask.set(messageId, {
                content: existing.content,
                isStreaming: false,
                signature: payload.signature ?? existing.signature,
                totalTokens: payload.total_tokens ?? existing.totalTokens
            });
            
            // Force reactivity by creating new Map
            thinkingContentByTask = new Map(thinkingContentByTask);
        }
        
        // Update UI if chatHistoryRef exists
        if (chatHistoryRef) {
            chatHistoryRef.updateMessages(currentMessages);
        }
    }
    // --- End Thinking/Reasoning Handlers ---

    // Handle draft saved event
    function handleDraftSaved(event: CustomEvent) {
        const { chat } = event.detail;
        // Create and dispatch a custom event that bubbles up to window
        const customEvent = new CustomEvent('chatUpdated', {
            detail: { chat },
            bubbles: true,
            composed: true
        });
        window.dispatchEvent(customEvent);

        const isNewChat = !currentChat?.chat_id && chat?.chat_id; // Check if it was a new chat
        currentChat = chat;
        console.debug("[ActiveChat] Draft saved, updating currentChat:", currentChat);

        // CRITICAL: Sync liveInputText with current editor content after draft save
        // This ensures the search in new chat suggestions stays in sync even after debounced draft saves
        // The textchange event might not fire after draft saves, so we manually sync here
        if (messageInputFieldRef) {
            try {
                const currentText = messageInputFieldRef.getTextContent();
                if (currentText !== liveInputText) {
                    liveInputText = currentText;
                    console.debug('[ActiveChat] Synced liveInputText after draft save:', { 
                        text: currentText, 
                        length: currentText.length 
                    });
                }
            } catch (error) {
                console.warn('[ActiveChat] Failed to sync liveInputText after draft save:', error);
            }
        }

        if (isNewChat) {
            console.debug("[ActiveChat] New chat created from draft, dispatching chatSelected:", chat);
            dispatch('chatSelected', { chat }); // Dispatch to parent (e.g. a component that embeds ActiveChat and Chats)
                                                // This might need to be a window event if Chats.svelte is not a direct parent
                                                // For now, let's assume a parent might handle this or we adjust Chats.svelte to listen to window.
            // To ensure Chats.svelte (if not a direct parent) can pick this up:
            const globalSelectEvent = new CustomEvent('globalChatSelected', {
                detail: { chat },
                bubbles: true,
                composed: true
            });
            window.dispatchEvent(globalSelectEvent);
        }
    }

    /**
     * Handler for input height changes
     * @param event CustomEvent with height detail
     */
    function handleInputHeightChange(event: CustomEvent) {
        messageInputHeight = event.detail.height;
    }

    /**
     * Handler for when MessageInput dispatches the sendMessage event.
     * It receives the message payload and calls addMessage() on the chat history.
     *
     * Expected message payload:
     * {
     *   id: string,
     *   role: string, // typically "user" for the sending user
     *   messageParts: MessagePart[]
     * }
     */
    async function handleSendMessage(event: CustomEvent) {
        const { message, newChat } = event.detail as { message: ChatMessageModel, newChat?: Chat };

        // Hide follow-up suggestions until new ones are received
        followUpSuggestions = [];
        
        // Hide settings/memories suggestions when user sends a new message
        // New suggestions will be generated during post-processing
        settingsMemoriesSuggestions = [];
        
        // Reset live input text to clear search term for suggestions
        // This ensures suggestions show the default 3 when input is focused again
        liveInputText = '';
        console.debug("[ActiveChat] handleSendMessage: Reset liveInputText after sending message");
        
        // Mark that user has sent first message this session (triggers push notification banner)
        if (!userSentFirstMessage) {
            userSentFirstMessage = true;
            console.debug("[ActiveChat] handleSendMessage: User sent first message, banner can now show");
        }

        console.debug("[ActiveChat] handleSendMessage: Received message payload:", message);
        
        // CRITICAL: Handle new chat activation immediately to ensure UI is in sync with backend events
        // This must also run when we're currently in welcome/new-chat state (currentChat is null),
        // even if sendHandlers didn't include `newChat` (e.g., when a draft chat shell existed in DB).
        if (newChat || !currentChat?.chat_id) {
            console.info("[ActiveChat] handleSendMessage: New chat detected, setting currentChat and initializing messages.", newChat);
            
            // CRITICAL: Close any open fullscreen views when creating a new chat
            // This ensures fullscreen views don't persist when a new chat is created
            if (showCodeFullscreen) {
                console.debug('[ActiveChat] Closing code fullscreen view due to new chat creation');
                showCodeFullscreen = false;
            }
            if (showEmbedFullscreen) {
                console.debug('[ActiveChat] Closing embed fullscreen view due to new chat creation');
                showEmbedFullscreen = false;
                embedFullscreenData = null;
            }
            
            // Force update currentChat immediately (fallback to DB if newChat wasn't provided)
            if (newChat) {
                currentChat = newChat;
            } else {
                // If the chat already exists (e.g., as a draft shell), load it now so streaming chunks aren't dropped
                try {
                    const { incognitoChatService } = await import('../services/incognitoChatService');
                    const incognitoChat = await incognitoChatService.getChat(message.chat_id);
                    if (incognitoChat) {
                        currentChat = incognitoChat as Chat;
                    } else {
                        const dbChat = await chatDB.getChat(message.chat_id);
                        if (dbChat) {
                            currentChat = dbChat as Chat;
                        } else {
                            // Minimal fallback to keep UI consistent; DB should catch up shortly
                            currentChat = { chat_id: message.chat_id } as Chat;
                        }
                    }
                } catch (err) {
                    console.warn('[ActiveChat] Failed to load chat for sent message; using minimal fallback:', err);
                    currentChat = { chat_id: message.chat_id } as Chat;
                }
            }
            currentMessages = [message]; // Initialize messages with the first message
            
            // Clear temporary chat ID since we now have a real chat
            temporaryChatId = null;
            console.debug("[ActiveChat] New chat created from message, cleared temporary chat ID");
            
            // CRITICAL: Update the URL hash directly with the new chat ID.
            // Don't rely solely on Chats.svelte's globalChatSelected handler since
            // Chats.svelte may not be mounted (e.g., sidebar closed on mobile).
            activeChatStore.setActiveChat(currentChat.chat_id);
            console.debug("[ActiveChat] Updated URL hash with new chat ID:", currentChat.chat_id);
            
            // Notify backend about the active chat, but only if not in signup flow
            // CRITICAL: Don't send set_active_chat if authenticated user is in signup flow - this would overwrite last_opened
            // Non-authenticated users can send set_active_chat for demo chats
            if (!$authStore.isAuthenticated || !$isInSignupProcess) {
                chatSyncService.sendSetActiveChat(currentChat.chat_id);
            } else {
                console.debug('[ActiveChat] Authenticated user is in signup flow - skipping set_active_chat for new chat to preserve last_opened path');
            }
            
            // Dispatch global event to update UI (sidebar highlights)
            // Use currentChat instead of newChat since newChat may be undefined
            // when the chat was loaded from DB rather than passed from sendHandlers
            const globalChatSelectedEvent = new CustomEvent('globalChatSelected', {
                detail: { chat: currentChat },
                bubbles: true,
                composed: true
            });
            window.dispatchEvent(globalChatSelectedEvent);
            console.debug("[ActiveChat] Dispatched globalChatSelected for new chat");
        } else {
            // This is a message for an existing, already active chat
            // Ensure we don't duplicate the message if it's already in currentMessages
            if (!currentMessages.some(m => m.message_id === message.message_id)) {
                currentMessages = [...currentMessages, message];
            }
        }

        // ─── Progressive AI Status Indicator: Start with 'sending' phase ─────
        // Determine if this is a new chat (no title yet) to decide which processing
        // steps to show later when ai_task_initiated arrives.
        const chatForNewCheck = newChat || currentChat;
        isNewChatProcessing = !chatForNewCheck?.title_v || chatForNewCheck.title_v === 0;
        
        // Start the centered status indicator immediately with "Sending..."
        processingPhase = {
            phase: 'sending',
            statusLines: [$text('enter_message.sending')]
        };
        console.debug('[ActiveChat] Processing phase set to SENDING', { isNewChat: isNewChatProcessing });

        if (chatHistoryRef) {
            console.debug("[ActiveChat] handleSendMessage: Updating ChatHistory with messages:", currentMessages);
            chatHistoryRef.updateMessages(currentMessages);
        }
        showWelcome = false;

        // The message is already saved to DB by sendHandlers.ts (or chatSyncService for the message part)
        // if it's a new chat, the chat metadata (including the first message) is saved.
        // If it's an existing chat, sendHandlers.ts calls addMessageToChat.
        // So, no need to call chatDB.saveMessage(message) here again.
        // The primary role here is to update the UI state (currentMessages, currentChat).
        
        // Error handling for the initial message save (done in sendHandlers or sendNewMessage)
        // should ideally update the message status in DB, and that change should flow
        // back via messageStatusChanged event if sendNewMessage fails at WebSocket level.
        // For now, we assume sendHandlers.ts and chatSyncService.sendNewMessage handle their DB ops.
    }

    /**
     * Handler for messages change event from ChatHistory
     * Controls welcome message visibility
     */
    function handleMessagesChange(event: CustomEvent) {
        const { hasMessages } = event.detail;
        showWelcome = !hasMessages;
    }

    /**
     * Handler for when the create icon is clicked.
     */
    async function handleNewChatClick() {
        console.debug("[ActiveChat] New chat creation initiated");
        // Reset current chat metadata and messages
        currentChat = null;
        currentMessages = [];
        showWelcome = true; // Show welcome message for new chat
        isAtBottom = false; // Reset to hide action buttons for new chat (user needs to interact first)
        
        // Clear any active processing phase indicator
        clearProcessingPhase();
        
        // Generate a new temporary chat ID for the new chat
        temporaryChatId = crypto.randomUUID();
        console.debug("[ActiveChat] Generated new temporary chat ID for new chat:", temporaryChatId);
        
        // Update phased sync state to indicate we're in "new chat" mode
        // CRITICAL: Use sentinel value (not null) to explicitly indicate user chose new chat
        // This prevents sync phases from auto-selecting the old chat
        phasedSyncState.setCurrentActiveChatId(NEW_CHAT_SENTINEL);
        
        // CRITICAL: Mark that user made an explicit choice to go to new chat
        // This ensures sync phases NEVER override the user's choice
        phasedSyncState.markUserMadeExplicitChoice();

        chatSyncService.sendSetActiveChat(null); // Notify backend that no chat is active
        
        if (chatHistoryRef) {
            chatHistoryRef.updateMessages([]); // Clear messages in ChatHistory
        }
        // Clear the MessageInput content (if available)
        // CRITICAL: Pass preserveContext: true to prevent deleting the previous chat's draft
        // When starting a new chat, we want to keep the previous chat's draft intact
        // We're just clearing the editor for the new chat, not deleting drafts
        // Focus will be handled separately below only for desktop devices
        if (messageInputFieldRef?.clearMessageField) {
            await messageInputFieldRef.clearMessageField(false, true);
        }
        
        // CRITICAL: Set the new temporary chat ID in draft state
        // This ensures that when the user types in the new chat, the draft service uses this chat ID
        // This allows separate drafts for new chats vs demo chats
        draftEditorUIState.update(s => ({
            ...s,
            currentChatId: temporaryChatId, // Set to the new temporary chat ID for the new chat
            newlyCreatedChatIdToSelect: null // Clear any pending selection
        }));
        console.debug("[ActiveChat] Set currentChatId in draft state to new temporary chat ID:", temporaryChatId);
        // Reset live input text state to clear search term for NewChatSuggestions
        // This ensures suggestions show the random 3 instead of filtering with old search term
        liveInputText = '';
        messageInputHasContent = false;
        console.debug("[ActiveChat] Reset liveInputText and messageInputHasContent");
        
        // Auto-focus the message input field on desktop devices only
        // On touch devices, users must manually tap to focus to avoid unwanted keyboard popups
        if (isDesktop() && messageInputFieldRef) {
            // Use a small delay to ensure the editor is ready after clearing
            setTimeout(() => {
                if (messageInputFieldRef) {
                    messageInputFieldRef.focus();
                    console.debug("[ActiveChat] Auto-focused message input on desktop after new chat creation");
                }
            }, 100);
        } else {
            console.debug("[ActiveChat] Skipping auto-focus - touch device or messageInputFieldRef not available");
        }
        
        // Trigger container scale down
        activeScaling = true;
        setTimeout(() => {
            activeScaling = false;
        }, 200); // Scale effect duration in ms (adjust if needed)

        // Dispatch an event to notify that a new chat is initiated and current selection should be cleared
        dispatch('chatDeselected'); // This can be listened to by Chats.svelte if it's a parent
        // Or use a window event for broader scope
        const globalDeselectEvent = new CustomEvent('globalChatDeselected', {
            bubbles: true,
            composed: true
        });
        window.dispatchEvent(globalDeselectEvent);
        console.debug("[ActiveChat] Dispatched chatDeselected / globalChatDeselected");

        // Also clear the persistent active chat store so side panel highlight resets
        // even if the Chats panel is not currently mounted to receive the event.
        // This prevents the previously selected chat from remaining highlighted.
        try {
            activeChatStore.clearActiveChat();
            console.debug('[ActiveChat] Cleared persistent activeChatStore after starting a new chat');
        } catch (err) {
            console.error('[ActiveChat] Failed to clear activeChatStore on new chat:', err);
        }
    }

    // Expose a helper so parents can reset the UI to the new chat state (e.g., after deletions)
    export async function resetToNewChat() {
        if (!currentChat && showWelcome) {
            return; // Already in a clean state
        }
        await handleNewChatClick();
    }

    /**
     * Handler for resuming the last chat from the "Resume last chat?" UI.
     * Loads the chat stored in local resumeChatData and clears the resume state.
     */
    async function handleResumeLastChat() {
        if (!resumeChatData) {
            console.warn('[ActiveChat] No resume chat data available');
            return;
        }

        const chatToResume = resumeChatData;
        console.info(`[ActiveChat] Resuming last chat: ${chatToResume.chat_id}`);

        // Clear local resume state and the phased sync store
        resumeChatData = null;
        resumeChatTitle = null;
        resumeChatCategory = null;
        resumeChatIcon = null;
        phasedSyncState.clearResumeChatData();

        // Mark that we've loaded the initial chat (prevents further auto-selection)
        phasedSyncState.markInitialChatLoaded();

        // Update the active chat store
        activeChatStore.setActiveChat(chatToResume.chat_id);

        // Load the chat
        await loadChat(chatToResume);

        // Dispatch event to notify Chats.svelte to update selection
        const globalSelectEvent = new CustomEvent('globalChatSelected', {
            bubbles: true,
            composed: true,
            detail: { chatId: chatToResume.chat_id }
        });
        window.dispatchEvent(globalSelectEvent);

        console.debug('[ActiveChat] Resume chat loaded and events dispatched');
    }

    /**
     * Handler for opening the for-everyone intro chat from the new chat screen.
     * Shown only to non-authenticated users so they can easily get back to the explainer intro (e.g. on mobile).
     */
    async function handleOpenIntroChat() {
        const welcomeDemo = DEMO_CHATS.find((chat) => chat.chat_id === 'demo-for-everyone');
        if (!welcomeDemo) {
            console.warn('[ActiveChat] demo-for-everyone not found in DEMO_CHATS');
            return;
        }
        const translatedWelcomeDemo = translateDemoChat(welcomeDemo);
        const welcomeChat = convertDemoChatToChat(translatedWelcomeDemo);
        phasedSyncState.markInitialChatLoaded();
        activeChatStore.setActiveChat('demo-for-everyone');
        await loadChat(welcomeChat);
        const globalSelectEvent = new CustomEvent('globalChatSelected', {
            bubbles: true,
            composed: true,
            detail: { chatId: 'demo-for-everyone' }
        });
        window.dispatchEvent(globalSelectEvent);
        console.debug('[ActiveChat] Loaded demo-for-everyone from intro link');
    }

    // Note: handleDismissResumeChat removed – the resume card is always visible
    // on the new chat screen (user is already in "new chat" mode, no need to dismiss).

    /**
     * Handler for the share button click.
     * Opens the settings menu and navigates to the share submenu.
     * This allows users to share the current chat with various options
     * like password protection and time limits.
     */
    async function handleShareChat() {
        console.debug("[ActiveChat] Share chat button clicked, opening share settings");
        
        // Ensure the current chat ID is set in the activeChatStore
        // This allows SettingsShare component to access the chat ID
        if (currentChat?.chat_id) {
            activeChatStore.setActiveChat(currentChat.chat_id);
            console.debug("[ActiveChat] Set active chat in store:", currentChat.chat_id);
        } else {
            console.warn("[ActiveChat] No current chat available to share");
        }
        
        // CRITICAL: Set settingsMenuVisible to true FIRST
        // Settings.svelte watches settingsMenuVisible store and will sync isMenuVisible
        // The deep link effect in Settings.svelte will also ensure the menu is open
        // This must be set before the deep link to ensure proper sequencing
        settingsMenuVisible.set(true);
        
        // CRITICAL: Also open via panelState for consistency
        // This ensures the panel state is properly tracked
        panelState.openSettings();
        
        // CRITICAL: Wait for store update to propagate and DOM to update
        // This ensures the Settings component's effect has time to sync isMenuVisible
        // and the menu is actually visible in the DOM before setting the deep link
        await tick();
        await new Promise(resolve => setTimeout(resolve, 100));
        
        // Navigate to the share settings submenu
        // The settingsDeepLink store triggers the Settings component to:
        // 1. Open the menu if not already open (line 1103 in Settings.svelte)
        // 2. Navigate to the specified path after a brief delay (line 1117)
        // Use 'shared/share' to navigate to the share submenu under Shared
        settingsDeepLink.set('shared/share');
    }

    /**
     * Handler for the report issue button click.
     * Opens the settings menu and navigates to the report issue page.
     * This ensures the settings menu is properly opened on mobile devices.
     */
    async function handleReportIssue() {
        console.debug("[ActiveChat] Report issue button clicked, opening report issue settings");
        
        // CRITICAL: Set settingsMenuVisible to true FIRST
        // Settings.svelte watches settingsMenuVisible store and will sync isMenuVisible
        // The deep link effect in Settings.svelte will also ensure the menu is open
        // This must be set before the deep link to ensure proper sequencing
        settingsMenuVisible.set(true);
        
        // CRITICAL: Also open via panelState for consistency
        // This ensures the panel state is properly tracked
        panelState.openSettings();
        
        // CRITICAL: Wait for store update to propagate and DOM to update
        // This ensures the Settings component's effect has time to sync isMenuVisible
        // and the menu is actually visible in the DOM before setting the deep link
        await tick();
        await new Promise(resolve => setTimeout(resolve, 100));
        
        // Navigate to the report issue settings page
        // The settingsDeepLink store triggers the Settings component to:
        // 1. Open the menu if not already open (line 1103 in Settings.svelte)
        // 2. Navigate to the specified path after a brief delay (line 1117)
        settingsDeepLink.set('report_issue');
    }

    /**
     * Handler for minimizing the chat in side-by-side mode.
     * When in ultra-wide mode with side-by-side layout, this hides the chat
     * and shows only the embed fullscreen in overlay mode.
     * The user can restore the chat by clicking the "chat" button in the fullscreen view.
     */
    function handleMinimizeChat() {
        console.debug('[ActiveChat] Minimize chat clicked - switching to overlay mode');
        forceOverlayMode = true;
    }
    
    /**
     * Handler for showing the chat from fullscreen view.
     * Called when user clicks the "chat" button in the embed fullscreen view.
     * Restores the side-by-side layout by disabling overlay mode.
     */
    function handleShowChat() {
        console.debug('[ActiveChat] Show chat clicked - switching to side-by-side mode');
        forceOverlayMode = false;
    }

    // Update handler for chat updates to be more selective
    async function handleChatUpdated(event: CustomEvent) {
        const detail = event.detail as ChatUpdatedDetail; 
        const incomingChatId = detail.chat_id;
        const incomingChatMetadata = detail.chat as Chat | undefined;
        const incomingMessages = detail.messages as ChatMessageModel[] | undefined;
        console.debug(`[ActiveChat] handleChatUpdated: Event for chat_id: ${incomingChatId}. Current active chat_id: ${currentChat?.chat_id}. Event detail:`, detail);

        if (!incomingChatId || !currentChat || currentChat.chat_id !== incomingChatId) {
            console.warn('[ActiveChat] handleChatUpdated: Event for non-active chat, no current chat, or chat_id mismatch. Current:', currentChat?.chat_id, 'Event chat_id:', incomingChatId, 'Ignoring.');
            return;
        }
        
        console.debug('[ActiveChat] handleChatUpdated: Processing event for active chat.');
        // let messagesNeedRefresh = false; // No longer relying on this for DB reload within this handler
        // let previousMessagesV = currentChat?.messages_v; // Not needed for direct comparison here anymore

        if (incomingChatMetadata) {
            console.debug("[ActiveChat] handleChatUpdated: Updating currentChat with metadata from event:", incomingChatMetadata);
            currentChat = { ...currentChat, ...incomingChatMetadata }; // Merge, prioritizing incoming. This updates messages_v etc.
        } else {
            console.debug("[ActiveChat] 'chatUpdated' event received without full chat metadata, only chat_id:", incomingChatId, "Detail type:", detail.type);
        }

        let messagesUpdatedInPlace = false;

        if (detail.newMessage) {
            const newMessage = detail.newMessage as ChatMessageModel;
            const existingMessageIndex = currentMessages.findIndex(m => m.message_id === newMessage.message_id);

            if (currentChat?.chat_id === newMessage.chat_id) {
                if (existingMessageIndex !== -1) {
                    // Message exists, update it by merging, prioritizing incoming data, especially content and status
                    console.debug("[ActiveChat] handleChatUpdated: Event contains newMessage. Updating existing message in currentMessages:", newMessage);
                    // Preserve potentially client-side only or more up-to-date fields from existing if not in newMessage
                    const updatedMessage = { ...currentMessages[existingMessageIndex], ...newMessage };
                    currentMessages[existingMessageIndex] = updatedMessage;
                    currentMessages = [...currentMessages]; // Ensure Svelte reactivity by creating a new array reference
                    messagesUpdatedInPlace = true;
                } else {
                    // Message doesn't exist, add it
                    console.debug("[ActiveChat] handleChatUpdated: Event contains newMessage. Adding new message to currentMessages:", newMessage);
                    currentMessages = [...currentMessages, newMessage];
                    messagesUpdatedInPlace = true;
                }
            } else {
                console.warn("[ActiveChat] handleChatUpdated: newMessage for a different chat_id. Current:", currentChat?.chat_id, "NewMessage's:", newMessage.chat_id, "Ignoring newMessage.");
            }
        } else if (incomingMessages && incomingMessages.length > 0) {
            // This case is typically for initial sync or batch updates, where replacing the whole array is intended.
            console.debug("[ActiveChat] handleChatUpdated: Event included full messages array. Replacing currentMessages.", incomingMessages);
            currentMessages = incomingMessages; // Assume incomingMessages is the new source of truth
            messagesUpdatedInPlace = true;
        }

        if (messagesUpdatedInPlace) {
            if (chatHistoryRef) {
                console.debug('[ActiveChat] handleChatUpdated: Calling chatHistoryRef.updateMessages with new currentMessages.');
                chatHistoryRef.updateMessages(currentMessages);
            }
            showWelcome = currentMessages.length === 0;
        } else if (detail.messagesUpdated && currentChat?.chat_id) {
            // SAFETY NET: messagesUpdated flag is set (e.g. by batch sync) but no inline
            // messages were provided in the event.  Reload from IndexedDB so the display
            // never goes stale after a sync writes new/updated messages to the DB.
            console.debug('[ActiveChat] handleChatUpdated: messagesUpdated=true but no messages in event. Reloading from IndexedDB for chat:', currentChat.chat_id);
            try {
                const freshMessages: ChatMessageModel[] = await chatDB.getMessagesForChat(currentChat.chat_id);

                // Preserve any in-flight streaming messages — the DB won't have
                // the latest streaming content, so keep our local copies.
                const streamingMessages = currentMessages.filter(m => m.status === 'streaming');
                if (streamingMessages.length > 0) {
                    for (const streamingMsg of streamingMessages) {
                        const idx = freshMessages.findIndex(m => m.message_id === streamingMsg.message_id);
                        if (idx !== -1) {
                            freshMessages[idx] = streamingMsg;
                        } else {
                            freshMessages.push(streamingMsg);
                        }
                    }
                    console.debug(`[ActiveChat] handleChatUpdated: Preserved ${streamingMessages.length} streaming message(s) during IndexedDB reload`);
                }

                // Only update if the message set actually changed to avoid unnecessary re-renders
                const currentIds = currentMessages.map(m => m.message_id).sort().join(',');
                const freshIds = freshMessages.map(m => m.message_id).sort().join(',');
                if (currentIds !== freshIds || freshMessages.length !== currentMessages.length) {
                    console.info(`[ActiveChat] handleChatUpdated: Message set changed after IndexedDB reload (${currentMessages.length} → ${freshMessages.length}). Updating display.`);
                    currentMessages = freshMessages;
                    if (chatHistoryRef) {
                        chatHistoryRef.updateMessages(currentMessages);
                    }
                    showWelcome = currentMessages.length === 0;
                } else {
                    console.debug('[ActiveChat] handleChatUpdated: IndexedDB reload returned same message set. No display update needed.');
                }
            } catch (error) {
                console.error('[ActiveChat] handleChatUpdated: Failed to reload messages from IndexedDB:', error);
            }
        } else {
            console.debug('[ActiveChat] handleChatUpdated: No direct message updates (newMessage or incomingMessages) were applied from the event. Full event.detail:', JSON.parse(JSON.stringify(detail)));
            // If currentChat metadata (like title or messages_v) was updated, UI elements bound to currentChat will react.
            // No explicit call to chatHistoryRef.updateMessages if currentMessages array reference hasn't changed.
        }
    }

    // Prefixed with underscore as currently unused but kept for potential future use
    async function _loadMessagesForCurrentChat() {
        if (currentChat?.chat_id) {
            console.debug(`[ActiveChat] Reloading messages for chat: ${currentChat.chat_id}`);
            currentMessages = await chatDB.getMessagesForChat(currentChat.chat_id);
            if (chatHistoryRef) {
                chatHistoryRef.updateMessages(currentMessages);
            }
            showWelcome = currentMessages.length === 0;
        }
    }

    // Preserve optional helpers for debugging and future UI workflows without triggering linter noise.
    const preservedHelperRefs = { _plainTextToTiptapJson, _loadMessagesForCurrentChat };
    void preservedHelperRefs;

    // Handle message status changes without full reload
    async function handleMessageStatusChanged(event: CustomEvent) {
        const { chatId, messageId, status, chat: chatMetadata } = event.detail as { chatId: string, messageId: string, status: MessageStatus, chat?: Chat };
        console.debug(`[ActiveChat] handleMessageStatusChanged: Event for chatId: ${chatId}, messageId: ${messageId}, status: ${status}. Current active chat_id: ${currentChat?.chat_id}. Event detail:`, event.detail);
        
        if (!currentChat || currentChat.chat_id !== chatId) {
            console.warn('[ActiveChat] handleMessageStatusChanged: Event for non-active chat, no current chat, or chat_id mismatch. Current:', currentChat?.chat_id, 'Event chatId:', chatId, 'Ignoring.');
            return;
        }
        console.debug('[ActiveChat] handleMessageStatusChanged: Processing event for active chat.');

        if (chatMetadata) {
            console.debug('[ActiveChat] handleMessageStatusChanged: Updating currentChat with metadata from event:', chatMetadata);
            // Only update fields that are defined to avoid overwriting with undefined values
            const validMetadata = Object.fromEntries(
                Object.entries(chatMetadata).filter(([, value]) => value !== undefined)
            );
            currentChat = { ...currentChat, ...validMetadata }; // Ensure currentChat is updated with latest metadata like messages_v
        }
        
        const messageIndex = currentMessages.findIndex(m => m.message_id === messageId);
        if (messageIndex !== -1) {
            // Create a new message object with updated status to ensure child components react
            const updatedMessage = { ...currentMessages[messageIndex], status };
            
            // Create a new array for currentMessages to trigger Svelte's reactivity
            const newMessagesArray = [...currentMessages];
            newMessagesArray[messageIndex] = updatedMessage;
            currentMessages = newMessagesArray;
            
            console.debug(`[ActiveChat] handleMessageStatusChanged: Message ${messageId} status updated to ${status} in local currentMessages. New array assigned.`);

            // DB save is already handled by chatSyncServiceHandlersChatUpdates.ts which triggered this event.
            // No need to call chatDB.saveMessage(updatedMessage) here.

            if (chatHistoryRef) {
                console.debug('[ActiveChat] handleMessageStatusChanged: Calling chatHistoryRef.updateMessages with updated currentMessages.');
                chatHistoryRef.updateMessages(currentMessages);
            }
        } else {
            console.warn(`[ActiveChat] handleMessageStatusChanged: Message ${messageId} not found in currentMessages. This might happen if the message wasn't added to UI yet or chat switched.`);
        }
    }

    // Scroll position tracking handlers
    let scrollSaveDebounceTimer: ReturnType<typeof setTimeout> | null = null;
    let lastSavedMessageId: string | null = null;

    // Handle immediate UI state updates from ChatHistory (no debounce)
    function handleScrollPositionUI(event: CustomEvent) {
        const { isAtBottom: atBottom, isAtTop: atTop } = event.detail;
        // Immediately update UI state for responsive button visibility
        isAtBottom = atBottom;
        isAtTop = atTop;
    }
    
    // Handle scroll position changes from ChatHistory (debounced for saving)
    function handleScrollPositionChanged(event: CustomEvent) {
        const { message_id } = event.detail;
        
        // Only save if the message ID has actually changed
        if (lastSavedMessageId === message_id) {
            return;
        }
        
        // Debounce saves (1 second)
        if (scrollSaveDebounceTimer) clearTimeout(scrollSaveDebounceTimer);
        
        scrollSaveDebounceTimer = setTimeout(async () => {
            if (!currentChat?.chat_id) return;
            
            // Skip scroll position updates for public chats (demo + legal - they're not stored in IndexedDB or server)
            if (isPublicChat(currentChat.chat_id)) {
                console.debug(`[ActiveChat] Skipping scroll position save for public chat: ${currentChat.chat_id}`);
                return;
            }
            
            try {
                // Save to IndexedDB
                await chatDB.updateChatScrollPosition(
                    currentChat.chat_id,
                    message_id
                );
                
                // Send to server (updates cache, Directus only on cache expiry)
                await chatSyncService.sendScrollPositionUpdate(
                    currentChat.chat_id,
                    message_id
                );
                
                // Update the last saved message ID to prevent duplicate saves
                lastSavedMessageId = message_id;
                
                console.debug(`[ActiveChat] Saved scroll position for chat ${currentChat.chat_id}: message ${message_id}`);
            } catch (error) {
                console.error('[ActiveChat] Error saving scroll position:', error);
            }
        }, 1000);
    }

    // Handle scrolled to bottom (mark as read)
    async function handleScrolledToBottom() {
        // Update isAtBottom state to show action buttons
        isAtBottom = true;
        
        if (!currentChat?.chat_id) return;
        
        // Skip read status updates for public chats (demo + legal) or non-authenticated users
        if (isPublicChat(currentChat.chat_id) || !$authStore.isAuthenticated) {
            console.debug(`[ActiveChat] Skipping read status update for ${isPublicChat(currentChat.chat_id) ? 'public chat' : 'non-authenticated user'}: ${currentChat.chat_id}`);
            return;
        }
        
        try {
            // Update unread count to 0 (mark as read)
            await chatDB.updateChatReadStatus(currentChat.chat_id, 0);
            
            // Send to server
            await chatSyncService.sendChatReadStatus(currentChat.chat_id, 0);
            
            // Update local state
            currentChat = { ...currentChat, unread_count: 0 };
            
            console.debug(`[ActiveChat] Marked chat ${currentChat.chat_id} as read (unread_count = 0)`);
        } catch (error) {
            console.error('[ActiveChat] Error marking chat as read:', error);
        }
    }

    // Update the loadChat function
    export async function loadChat(chat: Chat) {
        // Clear any active processing phase indicator from the previous chat
        clearProcessingPhase();
        
        // CRITICAL: Close any open fullscreen views when switching chats
        // This ensures fullscreen views don't persist when user switches to a different chat
        if (showCodeFullscreen) {
            console.debug('[ActiveChat] Closing code fullscreen view due to chat switch');
            showCodeFullscreen = false;
        }
        if (showEmbedFullscreen) {
            console.debug('[ActiveChat] Closing embed fullscreen view due to chat switch');
            showEmbedFullscreen = false;
            embedFullscreenData = null;
        }
        
        // CRITICAL: Close video player when switching chats (only if NOT in PiP mode)
        // In PiP mode, video should keep playing as user browses other chats
        const videoState = get(videoIframeStore);
        if (videoState.isActive && !videoState.isPipMode) {
            console.debug('[ActiveChat] Closing video player due to chat switch (not in PiP mode)');
            videoIframeStore.closeWithFadeOut(300);
        } else if (videoState.isActive && videoState.isPipMode) {
            // In PiP mode, video keeps playing - user can continue watching while browsing chats
            console.debug('[ActiveChat] Video in PiP mode - keeping video playing during chat switch');
        }
        
        // NOTE: Permission dialog is NOT cleared on chat switch.
        // ChatHistory.svelte's shouldShowPermissionDialog derived state already checks
        // $currentPermissionRequest.chatId === currentChatId, so the dialog naturally
        // hides when switching to a different chat and reappears when switching back.
        // This preserves the pending request so users can return to the original chat
        // and still approve/reject the request.
        
        // For public chats (demo/legal) and incognito chats, skip database access - use the chat object directly
        // This is critical during logout when database is being deleted
        let freshChat: Chat | null = null;
        if (isPublicChat(chat.chat_id)) {
            // Public chats don't need database access - use the provided chat object
            freshChat = chat;
            console.debug(`[ActiveChat] Loading public chat ${chat.chat_id} - skipping database access`);
        } else if (chat.is_incognito) {
            // Incognito chats are stored in sessionStorage, not IndexedDB
            // Try to get fresh data from incognitoChatService, but use provided chat as fallback
            try {
                const incognitoChat = await incognitoChatService.getChat(chat.chat_id);
                freshChat = incognitoChat || chat;
                console.debug(`[ActiveChat] Loading incognito chat ${chat.chat_id} - using incognitoChatService`);
            } catch (error) {
                console.debug(`[ActiveChat] Error loading incognito chat ${chat.chat_id}, using provided chat object:`, error);
                freshChat = chat;
            }
        } else if (!$authStore.isAuthenticated) {
            // CRITICAL: For non-authenticated users, check if this is a sessionStorage-only chat
            // (new chat with draft that doesn't exist in database yet)
            const sessionDraft = loadSessionStorageDraft(chat.chat_id);
            if (sessionDraft) {
                // This is a sessionStorage-only chat - use the provided chat object directly
                freshChat = chat;
                console.debug(`[ActiveChat] Loading sessionStorage-only chat ${chat.chat_id} - skipping database access`);
            } else {
                // Try to get from database (might be a real chat that was created before)
                try {
                    freshChat = await chatDB.getChat(chat.chat_id);
                } catch (error) {
                    // If database is unavailable, use the provided chat object
                    console.debug(`[ActiveChat] Database unavailable for ${chat.chat_id}, using provided chat object:`, error);
                    freshChat = chat;
                }
            }
        } else {
            // For authenticated users, try to get fresh data from database
            // But handle the case where database is being deleted (e.g., during logout)
            try {
                freshChat = await chatDB.getChat(chat.chat_id);
            } catch (error) {
                // If database is unavailable (e.g., being deleted), use the provided chat object
                console.debug(`[ActiveChat] Database unavailable for ${chat.chat_id}, using provided chat object:`, error);
                freshChat = chat;
            }
        }
        currentChat = freshChat || chat; // currentChat is now just metadata
        
        // CRITICAL: Clear liveInputText when switching chats to prevent stale search terms
        // This ensures followup suggestions show correctly when switching from a new chat with draft to a demo chat
        liveInputText = '';
        console.debug("[ActiveChat] Cleared liveInputText when switching to chat:", chat.chat_id);
        
        // Update phased sync state to track the current active chat
        // This prevents Phase 1 from auto-selecting a different chat when the panel is reopened
        phasedSyncState.setCurrentActiveChatId(chat.chat_id);
        
        // Mark that initial chat has been loaded - this prevents sync phases from overriding user's view
        phasedSyncState.markInitialChatLoaded();
        
        // CRITICAL: Only clear temporaryChatId if this is not a sessionStorage-only chat
        // SessionStorage-only chats (new chats with drafts) should keep their temporaryChatId
        // so drafts can be saved and loaded correctly
        if (!$authStore.isAuthenticated) {
            const sessionDraft = loadSessionStorageDraft(chat.chat_id);
            if (!sessionDraft) {
                // This is a real chat (not sessionStorage-only), clear temporaryChatId
                temporaryChatId = null;
                console.debug("[ActiveChat] Loaded real chat, cleared temporary chat ID");
            } else {
                // This is a sessionStorage-only chat, keep temporaryChatId for draft saving
                // Also update draft state to use this chat ID
                draftEditorUIState.update(s => ({
                    ...s,
                    currentChatId: chat.chat_id
                }));
                console.debug("[ActiveChat] SessionStorage-only chat, keeping temporary chat ID for draft saving:", chat.chat_id);
            }
        } else {
            // Authenticated user - always clear temporaryChatId for real chats
            temporaryChatId = null;
            console.debug("[ActiveChat] Loaded real chat, cleared temporary chat ID");
        }
        
        // Reset scroll position tracking for new chat
        lastSavedMessageId = null;
        
        let newMessages: ChatMessageModel[] = [];
        if (currentChat?.chat_id) {
            // Check if this is a public chat (demo or legal) - load messages from static bundle instead of IndexedDB
            if (isPublicChat(currentChat.chat_id)) {
                console.debug(`[ActiveChat] Loading public chat messages for: ${currentChat.chat_id}`);
                // Pass both DEMO_CHATS and LEGAL_CHATS to getDemoMessages
                newMessages = getDemoMessages(currentChat.chat_id, DEMO_CHATS, LEGAL_CHATS);
                console.debug(`[ActiveChat] Loaded ${newMessages.length} messages for ${currentChat.chat_id}`);
                
                // CRITICAL: For public chats, ensure we always have messages loaded
                // If getDemoMessages returns empty, log a warning
                if (newMessages.length === 0) {
                    console.warn(`[ActiveChat] WARNING: No messages found for ${currentChat.chat_id}. Available public chats:`, [...DEMO_CHATS, ...LEGAL_CHATS].map(c => c.chat_id));
                }
            } else if (currentChat.is_incognito) {
                // Incognito chats - load messages from incognitoChatService (sessionStorage)
                try {
                    newMessages = await incognitoChatService.getMessagesForChat(currentChat.chat_id);
                    console.debug(`[ActiveChat] Loaded ${newMessages.length} messages from incognitoChatService for ${currentChat.chat_id}`);
                } catch (error) {
                    console.error(`[ActiveChat] Error loading incognito chat messages for ${currentChat.chat_id}:`, error);
                    newMessages = [];
                }
            } else if (!$authStore.isAuthenticated) {
                // CRITICAL: For non-authenticated users, check if this is a sessionStorage-only chat
                // (new chat with draft that doesn't exist in database yet)
                const sessionDraft = loadSessionStorageDraft(currentChat.chat_id);
                if (sessionDraft) {
                    // SessionStorage-only chat - no messages yet (user hasn't sent any)
                    newMessages = [];
                    console.debug(`[ActiveChat] SessionStorage-only chat ${currentChat.chat_id} - no messages (new chat with draft only)`);
                } else {
                    // Try to load messages from IndexedDB (might be a real chat)
                    try {
                        newMessages = await chatDB.getMessagesForChat(currentChat.chat_id);
                        console.debug(`[ActiveChat] Loaded ${newMessages.length} messages from IndexedDB for ${currentChat.chat_id}`);
                    } catch (error) {
                        // If database is unavailable, use empty messages
                        console.debug(`[ActiveChat] Database unavailable for messages, using empty array:`, error);
                        newMessages = [];
                    }
                }
            } else {
                // For authenticated users, load messages from IndexedDB
                // Handle case where database might be unavailable (e.g., during logout/deletion)
                try {
                    newMessages = await chatDB.getMessagesForChat(currentChat.chat_id);
                    console.debug(`[ActiveChat] Loaded ${newMessages.length} messages from IndexedDB for ${currentChat.chat_id}`);
                } catch (error) {
                    // If database is unavailable (e.g., being deleted during logout), use empty messages
                    console.debug(`[ActiveChat] Database unavailable for messages, using empty array:`, error);
                    newMessages = [];
                }
            }
        }
        
        // CRITICAL: Preserve in-flight messages when reloading the SAME chat
        // During AI streaming or right after sending a message, various events (chatUpdated, etc.)
        // can trigger loadChat() calls which would wipe out:
        //   - Streaming messages being rendered in real-time
        //   - User messages that haven't been persisted to IndexedDB yet (sending/processing)
        // We detect these active messages for THIS chat and merge them into newMessages.
        const isReloadingSameChat = currentChat?.chat_id === chat.chat_id;
        const existingInFlightMessages = currentMessages.filter(
            m => m.chat_id === chat.chat_id && (
                m.status === 'streaming' ||
                m.status === 'sending' ||
                m.status === 'processing'
            )
        );
        
        if (isReloadingSameChat && existingInFlightMessages.length > 0) {
            console.debug(`[ActiveChat] loadChat: Preserving ${existingInFlightMessages.length} in-flight message(s) during reload of same chat ${chat.chat_id} (statuses: ${existingInFlightMessages.map(m => m.status).join(', ')})`);
            
            // CRITICAL: If currentMessages consists ONLY of in-flight messages for this chat, it means
            // handleSendMessage just initialised the view (e.g. after converting a demo chat to a real
            // chat).  At this point sendHandlers has already copied the demo history into IndexedDB so
            // any DB read would return demo messages + the new user message — making them appear as
            // "follow-up" messages to the demo conversation in the UI.
            //
            // In this case we skip the DB reload entirely: the in-memory currentMessages set by
            // handleSendMessage is already correct (only the new user message), and subsequent server
            // events (ai_response_storage_confirmed, chatUpdated with newMessage, etc.) will append
            // the AI reply through the normal streaming path.  On reload the DB is the source of
            // truth and loadChat is called with a clean slate, which is correct behaviour.
            const allCurrentMessagesAreInFlight = currentMessages.length > 0 &&
                currentMessages.every(m => m.chat_id === chat.chat_id && (
                    m.status === 'streaming' ||
                    m.status === 'sending' ||
                    m.status === 'processing'
                ));
            if (allCurrentMessagesAreInFlight) {
                console.info(`[ActiveChat] loadChat: currentMessages contains ONLY in-flight message(s) for ${chat.chat_id} — skipping DB reload to prevent demo history bleed-through. Keeping handleSendMessage-initialised view.`);
                // Return early — skip currentMessages = newMessages below.
                // We still need to update currentChat metadata so the header/title are correct.
                currentChat = freshChat ?? chat;
                // showWelcome should already be false (set by handleSendMessage); ensure it stays that way.
                showWelcome = false;
                return;
            }

            // Normal case: merge in-flight messages with messages from database.
            // The database may not have these messages yet, or may have stale content.
            for (const inFlightMsg of existingInFlightMessages) {
                const dbMsgIndex = newMessages.findIndex(m => m.message_id === inFlightMsg.message_id);
                if (dbMsgIndex !== -1) {
                    // Message exists in DB but our in-flight version is more up-to-date
                    newMessages[dbMsgIndex] = inFlightMsg;
                    console.debug(`[ActiveChat] loadChat: Replaced DB message ${inFlightMsg.message_id} with in-flight version (status=${inFlightMsg.status}, ${inFlightMsg.content?.length || 0} chars)`);
                } else {
                    // In-flight message not yet in DB - append it
                    newMessages.push(inFlightMsg);
                    console.debug(`[ActiveChat] loadChat: Appended in-flight message ${inFlightMsg.message_id} (status=${inFlightMsg.status}, ${inFlightMsg.content?.length || 0} chars)`);
                }
            }
        }
        
        // SANITIZE STALE MESSAGE STATUSES: After a page reload, messages may be stuck
        // in transient states ('processing', 'sending', 'streaming') in IndexedDB if the
        // AI task was dispatched but the worker never picked it up, or the page was closed
        // mid-flight (e.g., during focus mode countdown before continuation arrives).
        // Reset these to 'synced' so the typing indicator doesn't show permanently.
        // The phased sync will reconcile with the server's authoritative state.
        let sanitizedCount = 0;
        for (let i = 0; i < newMessages.length; i++) {
            const msg = newMessages[i];
            // User messages stuck in processing/sending
            if (msg.role === 'user' && (msg.status === 'processing' || msg.status === 'sending')) {
                newMessages[i] = { ...msg, status: 'synced' as const };
                sanitizedCount++;
                chatDB.saveMessage(newMessages[i]).catch(error => {
                    console.error(`[ActiveChat] Error sanitizing stale ${msg.status} message ${msg.message_id}:`, error);
                });
            }
            // Assistant messages stuck in streaming (e.g., page reload during focus mode
            // countdown before continuation task arrives). If the message has content
            // (embed reference), transition to synced so the embed is visible. If empty,
            // also transition so the typing indicator doesn't persist.
            if (msg.role === 'assistant' && msg.status === 'streaming') {
                newMessages[i] = { ...msg, status: 'synced' as const };
                sanitizedCount++;
                chatDB.saveMessage(newMessages[i]).catch(error => {
                    console.error(`[ActiveChat] Error sanitizing stale streaming assistant message ${msg.message_id}:`, error);
                });
            }
        }
        if (sanitizedCount > 0) {
            console.warn(`[ActiveChat] loadChat: Sanitized ${sanitizedCount} stale message(s) to synced status`);
        }

        currentMessages = newMessages;

        // Hide welcome screen when we have messages to display
        // This ensures public chats (demo + legal, like welcome chat) show their content immediately
        // CRITICAL: For public chats, always hide welcome screen if chat is loaded
        // (even if messages are empty, we still want to show the chat interface)
        if (currentChat?.chat_id && isPublicChat(currentChat.chat_id)) {
            // Public chats should always show their content, never the welcome screen
            showWelcome = false;
            console.debug(`[ActiveChat] Public chat loaded: forcing showWelcome=false for ${currentChat.chat_id}`);
        } else {
            // For real chats, show welcome only if there are no messages
            showWelcome = currentMessages.length === 0;
        }
        console.debug(`[ActiveChat] loadChat: showWelcome=${showWelcome}, messageCount=${currentMessages.length}, chatId=${currentChat?.chat_id}`);
        
        // Don't set isAtBottom here - it will be updated by handleScrollPositionUI
        // after the actual scroll position is restored below
        // Initialize to false to prevent MessageInput from appearing expanded prematurely
        isAtBottom = false;

        // Load follow-up suggestions from chat metadata
        // CRITICAL: For public chats (demo + legal), always use original suggestions from static bundle
        // Never load user-modified suggestions from database (even if stored) to prevent showing user responses
        if (isPublicChat(currentChat.chat_id)) {
            // For public chats, get original suggestions from static bundle, not from database
            const publicChatSource = DEMO_CHATS.find(c => c.chat_id === currentChat.chat_id) || 
                                     LEGAL_CHATS.find(c => c.chat_id === currentChat.chat_id);
            if (publicChatSource && publicChatSource.follow_up_suggestions) {
                // Translate suggestions if needed (demo chats use translation keys)
                const translatedChat = translateDemoChat(publicChatSource);
                followUpSuggestions = translatedChat.follow_up_suggestions || [];
                console.debug('[ActiveChat] Loaded original public chat follow-up suggestions from static bundle:', $state.snapshot(followUpSuggestions));
            } else if (currentChat.follow_up_request_suggestions) {
                // For community demo chats (from server), use cleartext suggestions stored on chat object
                // ARCHITECTURE: Community demo chats use cleartext fields (not encrypted_* fields)
                try {
                    followUpSuggestions = JSON.parse(currentChat.follow_up_request_suggestions);
                    console.debug('[ActiveChat] Loaded community demo chat follow-up suggestions from cleartext:', $state.snapshot(followUpSuggestions));
                } catch (error) {
                    console.error('[ActiveChat] Failed to parse community demo follow-up suggestions:', error);
                    followUpSuggestions = [];
                }
            } else {
                followUpSuggestions = [];
            }
        } else if (currentChat.follow_up_request_suggestions) {
            // For chats with cleartext follow-up suggestions (should be rare outside demo context)
            try {
                followUpSuggestions = JSON.parse(currentChat.follow_up_request_suggestions);
                console.debug('[ActiveChat] Loaded follow-up suggestions from cleartext field:', $state.snapshot(followUpSuggestions));
            } catch (error) {
                console.error('[ActiveChat] Failed to parse cleartext follow-up suggestions:', error);
                followUpSuggestions = [];
            }
        } else if (currentChat.encrypted_follow_up_request_suggestions) {
            // For real chats, decrypt the suggestions from database
            try {
                const chatKey = chatDB.getOrGenerateChatKey(currentChat.chat_id);
                const { decryptArrayWithChatKey } = await import('../services/cryptoService');
                followUpSuggestions = await decryptArrayWithChatKey(currentChat.encrypted_follow_up_request_suggestions, chatKey) || [];
                console.debug('[ActiveChat] Loaded follow-up suggestions from database:', $state.snapshot(followUpSuggestions));
            } catch (error) {
                console.error('[ActiveChat] Failed to load follow-up suggestions:', error);
                followUpSuggestions = [];
            }
        } else {
            followUpSuggestions = [];
        }

        // Load settings/memories suggestions from chat metadata
        // ARCHITECTURE: Settings/memories suggestions are always encrypted for real chats
        // Public chats don't have settings/memories suggestions (they're demo content)
        if (!isPublicChat(currentChat.chat_id) && currentChat.encrypted_settings_memories_suggestions) {
            // Load rejected hashes first (these are stored in cleartext)
            rejectedSuggestionHashes = currentChat.rejected_suggestion_hashes ?? null;
            
            try {
                const chatKey = chatDB.getOrGenerateChatKey(currentChat.chat_id);
                const { decryptWithChatKey } = await import('../services/cryptoService');
                const decryptedJson = await decryptWithChatKey(
                    currentChat.encrypted_settings_memories_suggestions,
                    chatKey
                );
                
                if (decryptedJson) {
                    const parsed = JSON.parse(decryptedJson);
                    if (Array.isArray(parsed) && parsed.length > 0) {
                        settingsMemoriesSuggestions = parsed;
                        console.debug('[ActiveChat] Loaded settings/memories suggestions from database:', parsed.length);
                    } else {
                        settingsMemoriesSuggestions = [];
                    }
                } else {
                    settingsMemoriesSuggestions = [];
                }
            } catch (error) {
                console.error('[ActiveChat] Failed to load settings/memories suggestions:', error);
                settingsMemoriesSuggestions = [];
            }
        } else {
            // Public chats or chats without suggestions - clear the state
            settingsMemoriesSuggestions = [];
            rejectedSuggestionHashes = null;
        }

        if (chatHistoryRef) {
            // Update messages
            chatHistoryRef.updateMessages(currentMessages);
            
            // Wait for messages to render, then restore scroll position
            // After restoration, isAtBottom will be updated by handleScrollPositionUI
            // We set it explicitly here as a fallback, but handleScrollPositionUI will override
            // if it fires (which it should after scroll restoration completes)
            setTimeout(() => {
                // Ensure currentChat is still valid (might be null if database was deleted)
                if (!currentChat?.chat_id) {
                    console.warn('[ActiveChat] currentChat is null in setTimeout - cannot restore scroll position');
                    return;
                }
                
                // For public chats (demo + legal), always scroll to top (user hasn't read them yet)
                // Also scroll to top for shared chats on non-authenticated devices (they can't reuse scroll position)
                if (isPublicChat(currentChat.chat_id) || !$authStore.isAuthenticated) {
                    chatHistoryRef.scrollToTop();
                    console.debug(`[ActiveChat] ${isPublicChat(currentChat.chat_id) ? 'Public chat' : 'Shared chat on non-authenticated device'} - scrolled to top (unread)`);
                    // After scrolling to top, explicitly set isAtBottom to false
                    // handleScrollPositionUI will confirm this after scroll completes
                    setTimeout(() => {
                        isAtBottom = false;
                        console.debug('[ActiveChat] Set isAtBottom=false after scrolling to top');
                    }, 200); // Slightly longer delay to ensure scroll completes
                } else if (currentChat.last_visible_message_id) {
                    // Restore scroll position for real chats
                    // User was scrolled up, so isAtBottom should be false
                    chatHistoryRef.restoreScrollPosition(currentChat.last_visible_message_id);
                    // After restoration, explicitly set isAtBottom to false
                    // handleScrollPositionUI will update it if the actual scroll position differs
                    setTimeout(() => {
                        isAtBottom = false;
                        console.debug('[ActiveChat] Set isAtBottom=false after restoring scroll position (user was scrolled up)');
                    }, 200); // Wait for scroll restoration to complete
                } else {
                    // No saved position - scroll to bottom (newest messages)
                    // User should see the latest messages, so isAtBottom should be true
                    chatHistoryRef.scrollToBottom();
                    // After scrolling to bottom, explicitly set isAtBottom to true
                    // handleScrollPositionUI will confirm this after scroll completes
                    setTimeout(() => {
                        isAtBottom = true;
                        console.debug('[ActiveChat] Set isAtBottom=true after scrolling to bottom (no saved position)');
                    }, 200); // Wait for scroll to complete
                }
            }, 100); // Short wait for messages to render
        }
 
        // CRITICAL: Load drafts from sessionStorage for non-authenticated users (demo chats)
        // For authenticated users, load encrypted drafts from IndexedDB
        // CRITICAL: messageInputFieldRef may not be bound yet during initial page load (component not fully mounted).
        // Retry with increasing delays to ensure draft restoration isn't silently skipped.
        const restoreDraftWithRetry = async (retriesLeft = 10): Promise<void> => {
            if (!messageInputFieldRef) {
                if (retriesLeft > 0) {
                    console.debug(`[ActiveChat] messageInputFieldRef not ready for draft restore, retrying (${retriesLeft} retries left)`);
                    await new Promise(resolve => setTimeout(resolve, 50));
                    return restoreDraftWithRetry(retriesLeft - 1);
                } else {
                    console.warn(`[ActiveChat] messageInputFieldRef still not available after retries - draft restoration skipped for chat ${currentChat?.chat_id}`);
                    return;
                }
            }
            
            if (!currentChat?.chat_id) return;
            
            if (!$authStore.isAuthenticated) {
                // Non-authenticated user: check sessionStorage for draft
                const sessionDraft = loadSessionStorageDraft(currentChat.chat_id);
                const sessionDraftMarkdown = getSessionStorageDraftMarkdown(currentChat.chat_id);
                if (sessionDraft) {
                    console.debug(`[ActiveChat] Loading sessionStorage draft for demo chat ${currentChat.chat_id}`);
                    setTimeout(() => {
                        messageInputFieldRef.setDraftContent(currentChat.chat_id, sessionDraft, 0, false);
                        // CRITICAL: Restore the original markdown from the stored draft to preserve user input
                        // This ensures URLs and other content are preserved exactly as the user typed them
                        if (sessionDraftMarkdown && messageInputFieldRef.setOriginalMarkdown) {
                            messageInputFieldRef.setOriginalMarkdown(sessionDraftMarkdown);
                        }
                    }, 50);
                } else {
                    console.debug(`[ActiveChat] No sessionStorage draft found for demo chat ${currentChat.chat_id}. Setting context and clearing editor.`);
                    // CRITICAL: Even when there's no draft, we must update the draft service's context to the new demo chat ID
                    // This ensures that when the user types in this demo chat, the draft is saved to the correct chat ID
                    // Without this, the draft service might still use the previous chat's ID, causing drafts to overwrite each other
                    setTimeout(() => {
                        // Set the draft context to the new demo chat ID, even though there's no draft content
                        // This ensures the draft service knows which chat ID to use when saving drafts
                        messageInputFieldRef.setDraftContent(currentChat.chat_id, null, 0, false);
                        console.debug(`[ActiveChat] Updated draft context to demo chat ${currentChat.chat_id} (no draft content)`);
                    }, 50);
                }
            } else {
                // Authenticated user: load encrypted draft from IndexedDB
                // Access the encrypted draft directly from the currentChat object.
                // The currentChat object should have been populated with encrypted_draft_md and draft_v
                // by the time it's passed to this function or fetched by chatDB.getChat().
                const encryptedDraftMd = currentChat?.encrypted_draft_md;
                const draftVersion = currentChat?.draft_v;

                if (encryptedDraftMd) {
                    console.debug(`[ActiveChat] Loading current user's encrypted draft for chat ${currentChat.chat_id}, version: ${draftVersion}`);
                    
                    // Decrypt the draft content and convert to TipTap JSON
                    try {
                        const decryptedMarkdown = await decryptWithMasterKey(encryptedDraftMd);
                        if (decryptedMarkdown) {
                            // Parse markdown to TipTap JSON for the editor
                            const draftContentJSON = parse_message(decryptedMarkdown, 'write', { unifiedParsingEnabled: true });
                            console.debug(`[ActiveChat] Successfully decrypted and parsed draft content for chat ${currentChat.chat_id}`);
                            
                            setTimeout(() => {
                                // Pass the decrypted and parsed TipTap JSON content
                                messageInputFieldRef.setDraftContent(currentChat.chat_id, draftContentJSON, draftVersion, false);
                            }, 50);
                        } else {
                            console.error(`[ActiveChat] Failed to decrypt draft for chat ${currentChat.chat_id} - master key not available`);
                            // CRITICAL: Preserve context when clearing - we're just switching to a chat with no draft
                            await messageInputFieldRef.clearMessageField(false, true);
                        }
                    } catch (error) {
                        console.error(`[ActiveChat] Error decrypting/parsing draft for chat ${currentChat.chat_id}:`, error);
                        // CRITICAL: Preserve context when clearing - we're just switching to a chat with no draft
                        await messageInputFieldRef.clearMessageField(false, true);
                    }
                } else {
                    console.debug(`[ActiveChat] No draft found for current user in chat ${currentChat.chat_id}. Clearing editor.`);
                    // CRITICAL: Preserve context when clearing - we're just switching to a chat with no draft
                    await messageInputFieldRef.clearMessageField(false, true);
                }
            }
        };
        await restoreDraftWithRetry();
        
        // Notify backend about the active chat, but only if WebSocket is connected
        // CRITICAL: Don't send set_active_chat if user is in signup flow - this would overwrite last_opened
        // and cause the user to skip remaining signup steps
        // Only skip for authenticated users in signup - non-authenticated users can load demo chats normally
        if ($authStore.isAuthenticated && $isInSignupProcess) {
            console.debug('[ActiveChat] User is in signup flow - skipping set_active_chat to preserve last_opened path');
        } else {
            // If not connected yet (e.g., instant load from cache on page reload), the notification
            // will be queued and sent when connection is established
            const chatIdToNotify = currentChat?.chat_id || null;
            
            if ($websocketStatus.status === 'connected') {
                // WebSocket is connected, send immediately
                chatSyncService.sendSetActiveChat(chatIdToNotify);
            } else {
                // WebSocket not connected yet, queue the notification to send once connected
                console.debug('[ActiveChat] WebSocket not connected, will notify server about active chat once connected');
                
                // Use a one-time listener to send the notification when WebSocket connects
                const sendNotificationOnConnect = () => {
                    // CRITICAL: Check again if user is still in signup flow when WebSocket connects
                    if ($authStore.isAuthenticated && $isInSignupProcess) {
                        console.debug('[ActiveChat] User is in signup flow - skipping deferred set_active_chat to preserve last_opened path');
                        chatSyncService.removeEventListener('webSocketConnected', sendNotificationOnConnect as EventListenerCallback);
                        return;
                    }
                    console.debug('[ActiveChat] WebSocket connected, sending deferred active chat notification');
                    chatSyncService.sendSetActiveChat(chatIdToNotify);
                    // Remove the listener after sending
                    chatSyncService.removeEventListener('webSocketConnected', sendNotificationOnConnect as EventListenerCallback);
                };
                
                chatSyncService.addEventListener('webSocketConnected', sendNotificationOnConnect as EventListenerCallback);
            }
        }
    }

    onMount(() => {
        const initialize = async () => {
            // Initialize app but skip auth initialization since it's already done in +page.svelte
            await initializeApp({ skipAuthInitialization: true });
            
            // Check server status to determine if payment is enabled (for signup status bar)
            try {
                const { getApiEndpoint } = await import('../config/api');
                const response = await fetch(getApiEndpoint('/v1/settings/server-status'));
                if (response.ok) {
                    const status = await response.json();
                    // Use is_self_hosted from request-based validation (more accurate than paymentEnabled)
                    // This correctly identifies localhost and other self-hosted instances
                    isSelfHosted = status.is_self_hosted || false;
                    // CRITICAL: If self-hosted, payment is ALWAYS disabled
                    // This overrides any environment-based logic that might enable payment for localhost in dev mode
                    if (isSelfHosted) {
                        paymentEnabled = false;
                    } else {
                        paymentEnabled = status.payment_enabled || false;
                    }
                    console.log(`[ActiveChat] Payment enabled: ${paymentEnabled}, is_self_hosted: ${isSelfHosted}, domain: ${status.domain || 'localhost'}`);
                } else {
                    console.warn('[ActiveChat] Failed to fetch server status, defaulting to payment enabled');
                    paymentEnabled = true; // Default to enabled if check fails
                    isSelfHosted = false; // Default to not self-hosted if check fails
                }
            } catch (error) {
                console.error('[ActiveChat] Error checking server status:', error);
                paymentEnabled = true; // Default to enabled if check fails
                isSelfHosted = false; // Default to not self-hosted if check fails
            }
            
            // Generate a temporary chat ID for draft saving if no chat is loaded
            // This ensures the draft service always has a chat ID to work with
            if (!currentChat?.chat_id && !temporaryChatId) {
                temporaryChatId = crypto.randomUUID();
                console.debug("[ActiveChat] Generated temporary chat ID for draft saving:", temporaryChatId);
            }
            
            // Check if the user is in the middle of a signup process (based on last_opened)
            // Only rely on explicit signup paths to avoid forcing passkey users back into OTP setup
            if ($authStore.isAuthenticated && isSignupPath($userProfile.last_opened)) {
                console.debug("User detected in signup process:", {
                    last_opened: $userProfile.last_opened,
                    tfa_enabled: $userProfile.tfa_enabled
                });
                // Set the signup process state to true so the signup component shows in Login
                isInSignupProcess.set(true);
                
                // Open login interface to show signup flow
                loginInterfaceOpen.set(true);
                
                // Extract step from last_opened to ensure we're on the right step
                const step = getStepFromPath($userProfile.last_opened);
                console.debug("Setting signup step to:", step);
                currentSignupStep.set(step);
            }
            
            // CRITICAL FALLBACK: Load welcome demo chat for non-authenticated users if no chat is loaded
            // This ensures the welcome chat loads on mobile where Chats.svelte doesn't mount
            // Only load if:
            // 1. User is not authenticated
            // 2. No current chat is loaded
            // 3. No chat is in the activeChatStore (to avoid duplicate loading)
            // 4. Not in signup process
            // 5. Not in "new chat" mode (phasedSyncState sentinel value)
            // 6. No existing sessionStorage drafts (user has unsaved work)
            const isInNewChatMode = get(phasedSyncState).currentActiveChatId === NEW_CHAT_SENTINEL;
            const hasSessionStorageDrafts = getAllDraftChatIdsWithDrafts().length > 0;
            
            if (!$authStore.isAuthenticated && !currentChat?.chat_id && !$activeChatStore && !$isInSignupProcess && !isInNewChatMode && !hasSessionStorageDrafts) {
                console.debug("[ActiveChat] [NON-AUTH] Fallback: Loading welcome demo chat (mobile fallback)");
                const welcomeDemo = DEMO_CHATS.find(chat => chat.chat_id === 'demo-for-everyone');
                if (welcomeDemo) {
                    // Translate the demo chat to the user's locale
                    const translatedWelcomeDemo = translateDemoChat(welcomeDemo);
                    const welcomeChat = convertDemoChatToChat(translatedWelcomeDemo);
                    
                    // Use a small delay to ensure component is fully initialized
                    setTimeout(() => {
                        // Check if deep link processing is happening
                        if (get(deepLinkProcessing)) {
                            console.debug("[ActiveChat] [NON-AUTH] Skipping welcome chat - deep link processing in progress");
                            return;
                        }
                        
                        // Re-check new chat mode and drafts after delay (user might have started typing)
                        const isStillInNewChatMode = get(phasedSyncState).currentActiveChatId === NEW_CHAT_SENTINEL;
                        const stillHasSessionStorageDrafts = getAllDraftChatIdsWithDrafts().length > 0;
                        if (isStillInNewChatMode || stillHasSessionStorageDrafts) {
                            console.debug("[ActiveChat] [NON-AUTH] Fallback: Skipping - user is in new chat mode or has drafts", { isStillInNewChatMode, stillHasSessionStorageDrafts });
                            return;
                        }

                        // Double-check that chat still isn't loaded (might have been loaded by +page.svelte)
                        // CRITICAL: Check if ANY chat is selected in activeChatStore, not just demo-for-everyone
                        // This prevents overwriting draft chats or other non-demo chats that are being loaded
                        if (!currentChat?.chat_id && !$activeChatStore) {
                            activeChatStore.setActiveChat('demo-for-everyone');
                            loadChat(welcomeChat);
                            console.info("[ActiveChat] [NON-AUTH] ✅ Fallback: Welcome chat loaded successfully");
                        } else {
                            console.info("[ActiveChat] [NON-AUTH] Fallback: Chat already selected, skipping", { currentChatId: currentChat?.chat_id, storeValue: $activeChatStore });
                        }
                    }, 100);
                }
            } else if (!$authStore.isAuthenticated && !currentChat?.chat_id && !$activeChatStore && !$isInSignupProcess && hasSessionStorageDrafts && !isInNewChatMode) {
                // CRITICAL: User has sessionStorage drafts but no chat is loaded (mobile fallback path)
                // On mobile, Chats.svelte doesn't mount, so the draft chat is never auto-selected.
                // We must actively load the most recent draft chat so the user sees their unsaved work.
                console.debug("[ActiveChat] [NON-AUTH] Fallback: Loading most recent sessionStorage draft chat (mobile fallback)");
                const draftChatIds = getAllDraftChatIdsWithDrafts();
                if (draftChatIds.length > 0) {
                    const mostRecentDraftId = draftChatIds[draftChatIds.length - 1];
                    const draftContent = loadSessionStorageDraft(mostRecentDraftId);
                    
                    if (draftContent) {
                        const now = Math.floor(Date.now() / 1000);
                        const virtualChat: Chat = {
                            chat_id: mostRecentDraftId,
                            encrypted_title: null,
                            messages_v: 0,
                            title_v: 0,
                            draft_v: 0,
                            encrypted_draft_md: null,
                            encrypted_draft_preview: null,
                            last_edited_overall_timestamp: now,
                            unread_count: 0,
                            created_at: now,
                            updated_at: now,
                            processing_metadata: false,
                            waiting_for_metadata: false,
                            encrypted_category: null,
                            encrypted_icon: null
                        };
                        
                        setTimeout(() => {
                            // Re-check that no chat has been loaded in the meantime
                            if (!currentChat?.chat_id && !$activeChatStore) {
                                phasedSyncState.setCurrentActiveChatId(NEW_CHAT_SENTINEL);
                                activeChatStore.setActiveChat(mostRecentDraftId);
                                loadChat(virtualChat);
                                console.info("[ActiveChat] [NON-AUTH] ✅ Fallback: Draft chat loaded successfully:", mostRecentDraftId);
                            } else {
                                console.debug("[ActiveChat] [NON-AUTH] Fallback: Chat already loaded, skipping draft restore");
                            }
                        }, 100);
                    }
                }
            } else if (!$authStore.isAuthenticated && (isInNewChatMode || hasSessionStorageDrafts)) {
                console.debug("[ActiveChat] [NON-AUTH] Fallback skipped - user has draft or is in new chat mode", { isInNewChatMode, hasSessionStorageDrafts });
            }
        };

        initialize();
        
        // Listen for event to open login interface from header button
        const handleOpenLoginInterface = () => {
            console.debug("[ActiveChat] Opening login interface from header button");
            loginInterfaceOpen.set(true);
            // Close chats panel when opening login
            if ($panelState.isActivityHistoryOpen) {
                // If panel is open, explicitly close it
                panelState.toggleChats();
            }
        };

        // Listen for event to open signup interface from message input button
        const handleOpenSignupInterface = () => {
            console.debug("[ActiveChat] Opening signup interface (alpha disclaimer) from message input button");
            // Set signup state directly to alpha disclaimer
            currentSignupStep.set(STEP_ALPHA_DISCLAIMER);
            isInSignupProcess.set(true);
            loginInterfaceOpen.set(true);
            
            // Close chats panel when opening signup
            if ($panelState.isActivityHistoryOpen) {
                panelState.toggleChats();
            }
        };
        
        // Listen for event to close login interface (e.g., from Demo button)
        const handleCloseLoginInterface = async () => {
            console.debug("[ActiveChat] Closing login interface, showing demo chat");
            
            // CRITICAL: Do NOT close login interface if user is in signup process
            // They need to complete signup, so the interface must stay open
            if ($isInSignupProcess) {
                console.debug("[ActiveChat] User is in signup process - preventing login interface from closing");
                return;
            }
            
            // CRITICAL: Close settings menu if it's open to prevent grey overlay from persisting
            // This ensures the dimmed class is removed from .active-chat-container on mobile
            // The Settings component's effect will remove the dimmed class when settingsMenuVisible is set to false
            settingsMenuVisible.set(false);
            panelState.closeSettings();
            
            // CRITICAL: Explicitly remove dimmed class as a defensive measure
            // This ensures the grey overlay is removed even if Settings component's effect hasn't run yet
            if (typeof window !== 'undefined') {
                const activeChatContainer = document.querySelector('.active-chat-container');
                if (activeChatContainer) {
                    activeChatContainer.classList.remove('dimmed');
                    console.debug("[ActiveChat] Explicitly removed dimmed class from .active-chat-container");
                }
            }
            
            console.debug("[ActiveChat] Closed settings menu when closing login interface");
            
            // CRITICAL FIX: Clear pending draft from sessionStorage when user leaves login process
            // This ensures the draft doesn't get restored if user clicks "Demo" to go back
            try {
                const pendingDraft = sessionStorage.getItem('pendingDraftAfterSignup');
                if (pendingDraft) {
                    sessionStorage.removeItem('pendingDraftAfterSignup');
                    console.debug("[ActiveChat] Cleared pendingDraftAfterSignup from sessionStorage");
                }
            } catch (error) {
                console.warn("[ActiveChat] Error clearing pendingDraftAfterSignup:", error);
            }
            
            // PRIVACY: Clear liveInputText when user leaves login flow
            // This ensures follow-up suggestions show properly when returning to demo chat
            liveInputText = '';
            console.debug("[ActiveChat] Cleared liveInputText when closing login interface");
            
            // CRITICAL: Clear message input field to ensure it's empty when returning from login
            // This prevents old suggestion text from filtering out follow-up suggestions
            if (messageInputFieldRef) {
                await messageInputFieldRef.clearMessageField(false);
                // Manually update liveInputText since clearMessageField uses clearContent(false) 
                // which doesn't trigger update events that would normally update liveInputText
                liveInputText = '';
                console.debug("[ActiveChat] Cleared message input field and liveInputText when closing login interface");
            }
            
            loginInterfaceOpen.set(false);
            
            // CRITICAL FIX: Clear current chat state first to ensure clean reload
            // This prevents the "new chat" interface from showing when returning to demo
            currentChat = null;
            currentMessages = [];
            showWelcome = false; // Explicitly set to false for public chat
            activeChatStore.setActiveChat('demo-for-everyone');
            
            // Wait a tick to ensure state is cleared before loading new chat
            await tick();
            
            // Load default demo chat (welcome chat)
            const welcomeChat = DEMO_CHATS.find(chat => chat.chat_id === 'demo-for-everyone');
            if (welcomeChat) {
                const chat = convertDemoChatToChat(translateDemoChat(welcomeChat));
                // Await loadChat to ensure chat is fully loaded before dispatching selection event
                await loadChat(chat);
                // Ensure showWelcome is false after loading public chat (defensive)
                showWelcome = false;
                
                // CRITICAL: Dispatch globalChatSelected event to mark chat as active in sidebar
                // This ensures the chat is highlighted in the Chats component
                // Dispatch immediately - the Chats component listens for this event even when panel is closed
                const globalChatSelectedEvent = new CustomEvent('globalChatSelected', {
                    detail: { chat },
                    bubbles: true,
                    composed: true
                });
                window.dispatchEvent(globalChatSelectedEvent);
                console.debug("[ActiveChat] Dispatched globalChatSelected for demo-for-everyone chat");
                
                // Also wait a bit and dispatch again in case Chats component mounts after panel opens
                // This handles the case where the panel opens and Chats component mounts after our first dispatch
                setTimeout(() => {
                    window.dispatchEvent(globalChatSelectedEvent);
                    console.debug("[ActiveChat] Re-dispatched globalChatSelected for demo-for-everyone chat (after delay)");
                }, 300); // Longer delay to ensure Chats component is mounted if panel was opened
                
                console.debug("[ActiveChat] ✅ Welcome demo chat loaded after closing login interface");
            } else {
                console.warn("[ActiveChat] Welcome demo chat not found in DEMO_CHATS");
            }
            
            // Only open chats panel on desktop (not mobile) when closing login interface
            // On mobile, let the user manually open the panel if they want to see the chat list
            // Do this AFTER loading the chat so the event is dispatched first
            if (!$panelState.isActivityHistoryOpen && !$isMobileView) {
                panelState.toggleChats();
            }
        };
        
        // Listen for event to load demo chat after logout from signup
        const handleLoadDemoChat = () => {
            console.debug("[ActiveChat] Loading demo chat after logout from signup");

            // Ensure login interface is closed
            loginInterfaceOpen.set(false);
            // Load default demo chat
            const welcomeChat = DEMO_CHATS.find(chat => chat.chat_id === 'demo-for-everyone');
            if (welcomeChat) {
                const chat = convertDemoChatToChat(translateDemoChat(welcomeChat));
                // Clear current chat first
                currentChat = null;
                currentMessages = [];
                activeChatStore.setActiveChat('demo-for-everyone');
                loadChat(chat);
                console.debug("[ActiveChat] ✅ Demo chat loaded after logout from signup");
            }
        };
        
        window.addEventListener('openLoginInterface', handleOpenLoginInterface);
        window.addEventListener('openSignupInterface', handleOpenSignupInterface);
        
        // Add event listener for embed fullscreen events
        const embedFullscreenHandler = (event: CustomEvent) => {
            handleEmbedFullscreen(event);
        };
        document.addEventListener('embedfullscreen', embedFullscreenHandler as EventListenerCallback);
        
        // --- Focus mode event listeners ---
        // Handle focus mode rejection (user clicked during countdown to cancel activation)
        // With the deferred activation architecture, this sends "focus_mode_rejected" to the
        // backend which consumes the pending context and fires a non-focus continuation task.
        // If the auto-confirm already ran, it falls back to deactivating the already-active mode.
        const focusModeRejectedHandler = async (event: CustomEvent) => {
            const { focusId, focusModeName } = event.detail || {};
            const chatId = currentChat?.chat_id;
            console.debug('[ActiveChat] Focus mode rejected:', focusId, focusModeName);
            
            // Send rejection to backend via WebSocket (new deferred activation protocol)
            // The backend will either:
            // a) Consume the pending context and fire a non-focus continuation task
            // b) Fall back to deactivation if auto-confirm already ran
            if (chatId && focusId) {
                try {
                    const { webSocketService } = await import('../services/websocketService');
                    webSocketService.sendMessage('focus_mode_rejected', {
                        chat_id: chatId,
                        focus_id: focusId,
                    });
                    console.debug('[ActiveChat] Sent focus_mode_rejected to backend');
                } catch (e) {
                    console.error('[ActiveChat] Error sending focus_mode_rejected:', e);
                }
            }
            
            // Add a persisted system message indicating the rejection
            handleFocusModeSystemMessage(focusId, focusModeName, 'rejected');
        };
        document.addEventListener('focusModeRejected', focusModeRejectedHandler as EventListenerCallback);
        
        // Handle focus mode deactivation (user clicked "Deactivate" in context menu)
        const focusModeDeactivatedHandler = (event: CustomEvent) => {
            const { focusId } = event.detail || {};
            console.debug('[ActiveChat] Focus mode deactivated:', focusId);
            handleFocusModeDeactivation(focusId);
        };
        document.addEventListener('focusModeDeactivated', focusModeDeactivatedHandler as EventListenerCallback);
        
        // Handle focus mode details request (user clicked "Details" in context menu)
        const focusModeDetailsHandler = (event: CustomEvent) => {
            const { focusId, appId } = event.detail || {};
            console.debug('[ActiveChat] Focus mode details requested:', focusId, appId);
            handleFocusModeDetailsNavigation(focusId, appId);
        };
        document.addEventListener('focusModeDetailsRequested', focusModeDetailsHandler as EventListenerCallback);
        
        // Handle focus mode context menu (right-click or long-press on focus mode embed)
        // Opens the FocusModeContextMenu component at the event coordinates.
        const focusModeContextMenuHandler = (event: CustomEvent) => {
            const { focusId, appId, focusModeName, isActivated, isRejected, event: originalEvent } = event.detail || {};
            console.debug('[ActiveChat] Focus mode context menu requested:', { focusId, isActivated, isRejected });
            
            // Don't show context menu for already-rejected embeds
            if (isRejected) return;
            
            // Get coordinates from the original mouse/touch event
            let x = 0;
            let y = 0;
            if (originalEvent instanceof MouseEvent) {
                x = originalEvent.clientX;
                y = originalEvent.clientY;
            } else if (originalEvent instanceof TouchEvent && originalEvent.touches.length > 0) {
                x = originalEvent.touches[0].clientX;
                y = originalEvent.touches[0].clientY;
            } else if (originalEvent instanceof TouchEvent && originalEvent.changedTouches?.length > 0) {
                x = originalEvent.changedTouches[0].clientX;
                y = originalEvent.changedTouches[0].clientY;
            }
            
            focusModeContextMenuX = x;
            focusModeContextMenuY = y;
            focusModeContextMenuIsActivated = !!isActivated;
            focusModeContextMenuFocusId = focusId || '';
            focusModeContextMenuAppId = appId || '';
            focusModeContextMenuFocusModeName = focusModeName || '';
            showFocusModeContextMenu = true;
        };
        document.addEventListener('focusModeContextMenu', focusModeContextMenuHandler as EventListenerCallback);
        
        // Add event listener for video PiP restore fullscreen events
        // This is triggered when user clicks the overlay on PiP video (via VideoIframe component)
        const videoPipRestoreHandler = () => {
            handlePipOverlayClick();
        };
        document.addEventListener('videopip-restore-fullscreen', videoPipRestoreHandler as EventListenerCallback);
        
        // Add event listeners for login interface and demo chat
        window.addEventListener('closeLoginInterface', handleCloseLoginInterface);
        window.addEventListener('loadDemoChat', handleLoadDemoChat);
        
        // NOTE: Cleanup for embedFullscreenHandler, videoPipRestoreHandler, and login interface event listeners
        // is done in the final return statement at the end of onMount (around line 3329).
        // DO NOT add a return statement here as it would prevent the rest of onMount from executing,
        // including critical event listener registrations like aiMessageChunk.
        
        // CRITICAL: Sync liveInputText with editor content after draft saves
        // This ensures the search in new chat suggestions stays in sync even after debounced draft saves
        // The textchange event might not fire after draft saves, so we listen for draft save events
        const handleDraftSaveSync = () => {
            // Use a delay to ensure the editor content is stable after the save
            // Longer delay for first saves (new chat creation) to ensure editor is fully initialized
            const delay = 200; // Increased delay to handle new chat creation
            setTimeout(() => {
                if (messageInputFieldRef) {
                    try {
                        const currentText = messageInputFieldRef.getTextContent();
                        // CRITICAL: Only sync if editor has content OR if we're clearing (editor empty and liveInputText was set)
                        // This prevents clearing liveInputText when editor content is temporarily unavailable during chat creation
                        if (currentText !== liveInputText) {
                            // If editor has content, always sync to it
                            if (currentText.trim().length > 0) {
                                liveInputText = currentText;
                                console.debug('[ActiveChat] Synced liveInputText after draft save event (editor has content):', { 
                                    text: currentText, 
                                    length: currentText.length 
                                });
                            } else if (liveInputText.trim().length === 0) {
                                // Both are empty, no need to sync
                                console.debug('[ActiveChat] Both editor and liveInputText are empty, skipping sync');
                            } else {
                                // Editor is empty but liveInputText has content - this might be during chat creation
                                // Don't clear liveInputText immediately, wait a bit more and check again
                                setTimeout(() => {
                                    if (messageInputFieldRef) {
                                        const retryText = messageInputFieldRef.getTextContent();
                                        if (retryText.trim().length > 0) {
                                            // Editor now has content, sync to it
                                            liveInputText = retryText;
                                            console.debug('[ActiveChat] Synced liveInputText after retry (editor now has content):', { 
                                                text: retryText, 
                                                length: retryText.length 
                                            });
                                        } else {
                                            // Editor is still empty, but only clear if user actually cleared it
                                            // (This prevents clearing during chat creation)
                                            console.debug('[ActiveChat] Editor still empty after retry, preserving liveInputText to prevent clearing during chat creation');
                                        }
                                    }
                                }, 100); // Additional retry delay
                            }
                        }
                    } catch (error) {
                        console.warn('[ActiveChat] Failed to sync liveInputText after draft save event:', error);
                    }
                }
            }, delay);
        };
        
        // Listen for local chat list changes (dispatched when drafts are saved)
        window.addEventListener('localChatListChanged', handleDraftSaveSync);

        // ─── Preprocessing step: refresh currentChat from DB ──────────────────────────
        // When a preprocessing step (title_generated, mate_selected) arrives, we fire
        // localChatListChanged with reason="preprocessing_step". Here we reload the active
        // chat from the local DB so the header title/category/icon updates immediately.
        const handlePreprocessingChatRefresh = async (event: Event) => {
            const detail = (event as CustomEvent).detail;
            if (detail?.reason !== 'preprocessing_step') return;
            const targetChatId = detail?.chatId;
            if (!targetChatId || targetChatId !== currentChat?.chat_id) return;

            try {
                const freshChat = await chatDB.getChat(targetChatId);
                if (freshChat) {
                    currentChat = { ...currentChat, ...freshChat };
                    console.debug('[ActiveChat] Refreshed currentChat after preprocessing step:', detail.reason, targetChatId);
                }
            } catch (err) {
                console.warn('[ActiveChat] Failed to refresh currentChat after preprocessing step:', err);
            }
        };
        window.addEventListener('localChatListChanged', handlePreprocessingChatRefresh);
        
        // Listen for logout event to clear user chat and load demo chat
        // CRITICAL: This handler must work reliably on mobile, even if component isn't fully initialized
        handleLogoutEvent = async () => {
            console.debug('[ActiveChat] Logout event received - clearing user chat and loading demo chat');
            
            try {
                // Clear current chat state immediately (before database deletion)
                // This ensures UI updates right away, even on mobile
                currentChat = null;
                currentMessages = [];
                followUpSuggestions = []; // Clear follow-up suggestions to prevent showing user responses
                settingsMemoriesSuggestions = []; // Clear settings/memories suggestions
                rejectedSuggestionHashes = null;
                showWelcome = true; // Show welcome screen for new demo chat
                isAtBottom = false;
                
                // Clear the persistent store
                activeChatStore.clearActiveChat();
                
                // CRITICAL: Clear message input field to prevent showing user's previous draft
                // This is especially important on mobile where the input might still be visible
                if (messageInputFieldRef) {
                    try {
                        await messageInputFieldRef.clearMessageField(false, false);
                    } catch (error) {
                        console.warn('[ActiveChat] Error clearing message input during logout:', error);
                        // Continue even if clearing input fails
                    }
                }
                
                // Load default demo chat (welcome chat) - use static bundle, not database
                const welcomeDemo = DEMO_CHATS.find(chat => chat.chat_id === 'demo-for-everyone');
                if (welcomeDemo) {
                    // Translate the demo chat to the user's locale
                    const translatedWelcomeDemo = translateDemoChat(welcomeDemo);
                    const welcomeChat = convertDemoChatToChat(translatedWelcomeDemo);
                    
                    // Set active chat and load welcome chat
                    activeChatStore.setActiveChat('demo-for-everyone');
                    
                    // Use a small delay to ensure state is cleared and component is ready
                    // This is especially important on mobile where component initialization might be slower
                    await tick();
                    
                    // CRITICAL: Mark phased sync as completed for non-authenticated users
                    // This prevents "Loading chats..." from showing after logout
                    phasedSyncState.markSyncCompleted();
                    console.debug('[ActiveChat] Marked phased sync as completed after logout (non-auth user)');
                    
                    // CRITICAL: Ensure loadChat is called even if there are errors
                    // Wrap in try-catch to handle any potential errors gracefully
                    try {
                        await loadChat(welcomeChat);
                        console.debug('[ActiveChat] ✅ Demo welcome chat loaded after logout');
                    } catch (loadError) {
                        console.error('[ActiveChat] Error loading demo chat after logout:', loadError);
                        // Even if loadChat fails, ensure UI shows welcome state
                        // CRITICAL: Close any open fullscreen views in fallback path too
                        if (showCodeFullscreen) {
                            console.debug('[ActiveChat] Closing code fullscreen view in fallback path');
                            showCodeFullscreen = false;
                        }
                        if (showEmbedFullscreen) {
                            console.debug('[ActiveChat] Closing embed fullscreen view in fallback path');
                            showEmbedFullscreen = false;
                            embedFullscreenData = null;
                        }
                        showWelcome = true;
                        currentChat = welcomeChat; // Set chat object directly as fallback
                        currentMessages = getDemoMessages('demo-for-everyone', DEMO_CHATS, LEGAL_CHATS);
                        if (chatHistoryRef) {
                            chatHistoryRef.updateMessages(currentMessages);
                        }
                    }
                } else {
                    console.warn('[ActiveChat] Welcome demo chat not found in DEMO_CHATS');
                    // Fallback: ensure welcome screen is shown even if demo chat not found
                    showWelcome = true;
                    // Mark phased sync as completed even if demo chat not found
                    phasedSyncState.markSyncCompleted();
                    console.debug('[ActiveChat] Marked phased sync as completed after logout (fallback path)');
                }
            } catch (error) {
                console.error('[ActiveChat] Error in logout event handler:', error);
                // Fallback: ensure UI is cleared even if handler fails
                currentChat = null;
                currentMessages = [];
                showWelcome = true;
                activeChatStore.clearActiveChat();
                // Mark phased sync as completed even if handler fails
                phasedSyncState.markSyncCompleted();
                console.debug('[ActiveChat] Marked phased sync as completed after logout (error fallback)');
            }
        };
        window.addEventListener('userLoggingOut', handleLogoutEvent);
        
        // Listen for triggerNewChat event (from incognito info screen)
        const handleTriggerNewChat = () => {
            console.debug('[ActiveChat] triggerNewChat event received - creating new chat');
            handleNewChatClick();
        };
        window.addEventListener('triggerNewChat', handleTriggerNewChat);
        
        // Listen for hiddenChatsLocked and hiddenChatsAutoLocked events - if current chat is hidden, close it and show new chat window
        // This handler works for both manual lock and auto-lock (after inactivity)
        const handleHiddenChatsLocked = async () => {
            // Add a small delay to ensure the lock operation has completed
            await tick();
            
            if (!currentChat) {
                console.debug('[ActiveChat] Hidden chats locked but no current chat - no action needed');
                return;
            }
            
            const chatId = currentChat.chat_id;
            
            // Skip for public chats (demo/legal) and incognito chats - they can't be hidden
            if (isPublicChat(chatId) || currentChat.is_incognito) {
                console.debug('[ActiveChat] Hidden chats locked but current chat is public/incognito - no action needed');
                return;
            }
            
            // Check if current chat is marked as hidden (property might be set)
            const chatIsHidden = (currentChat as HiddenChatFlag).is_hidden === true;
            
            // If chat is explicitly marked as hidden, close it immediately
            if (chatIsHidden) {
                console.debug('[ActiveChat] Hidden chats locked and current chat is marked as hidden - closing chat and showing new chat window', {
                    chatId: chatId
                });
                await handleNewChatClick();
                return;
            }
            
            // Refresh chat from database to get updated state (is_hidden might be set during decryption)
            if ($authStore.isAuthenticated && currentChat.encrypted_chat_key) {
                try {
                    const freshChat = await chatDB.getChat(chatId);
                    if (freshChat && (freshChat as HiddenChatFlag).is_hidden === true) {
                        console.debug('[ActiveChat] Hidden chats locked and fresh chat from DB is marked as hidden - closing chat and showing new chat window', {
                            chatId: chatId
                        });
                        await handleNewChatClick();
                        return;
                    }
                } catch (error) {
                    console.debug('[ActiveChat] Error refreshing chat from DB to check hidden status:', error);
                }
            }
            
            // Also check if the chat has an encrypted_chat_key and verify if it can be decrypted with master key
            // If it can't be decrypted with master key and hidden chats are locked, it's a hidden chat
            if (currentChat.encrypted_chat_key && $authStore.isAuthenticated) {
                try {
                    const { hiddenChatService } = await import('../services/hiddenChatService');
                    const { decryptChatKeyWithMasterKey } = await import('../services/cryptoService');
                    
                    // Verify hidden chats are actually locked (double-check)
                    if (!hiddenChatService.isUnlocked()) {
                        // Try to decrypt with master key - if it fails, it's a hidden chat
                        try {
                            const masterKeyDecrypt = await decryptChatKeyWithMasterKey(currentChat.encrypted_chat_key);
                            if (!masterKeyDecrypt) {
                                // Can't decrypt with master key and hidden chats are locked - this is a hidden chat
                                console.debug('[ActiveChat] Hidden chats locked and current chat cannot be decrypted with master key - closing chat and showing new chat window', {
                                    chatId: chatId
                                });
                                await handleNewChatClick();
                                return;
                            }
                        } catch (decryptError) {
                            // Decryption with master key failed - this is likely a hidden chat
                            console.debug('[ActiveChat] Hidden chats locked and current chat decryption with master key failed - closing chat and showing new chat window', {
                                chatId: chatId,
                                error: decryptError
                            });
                            await handleNewChatClick();
                            return;
                        }
                    }
                } catch (error) {
                    console.warn('[ActiveChat] Error checking if chat requires hidden key:', error);
                }
            }
            
            // If we get here, the chat is not hidden or can be decrypted with master key
            console.debug('[ActiveChat] Hidden chats locked but current chat is not hidden - no action needed', {
                chatId: chatId,
                is_hidden: chatIsHidden
            });
        };
        window.addEventListener('hiddenChatsLocked', handleHiddenChatsLocked);
        window.addEventListener('hiddenChatsAutoLocked', handleHiddenChatsLocked);
        
        // Add language change listener to reload public chats (demo + legal + community demos) when language changes
        const handleLanguageChange = async () => {
            try {
                // CRITICAL: Use $state.snapshot to get current value in async context
                const snapshotChat = $state.snapshot(currentChat);
                
                if (!snapshotChat || !isPublicChat(snapshotChat.chat_id)) {
                    return;
                }
                
                // CRITICAL: Wait for translations to be fully loaded before re-translating
                // waitLocale() ensures the translation files are loaded for the new locale
                // This is essential for getDemoMessages to get the correct translations
                await waitLocale();
                
                // Wait multiple ticks to ensure locale store and translation store are fully updated
                // The _ store is derived from locale, so it needs time to update
                await tick();
                await tick(); // Extra tick to ensure derived stores have updated
                
                // CRITICAL: Force a read of the translation store to ensure it's updated
                // This ensures get(_) will get the new translation function
                const { _: translationStore } = await import('svelte-i18n');
                get(translationStore); // Ensure translation store is updated
                
                // Import community demo store functions
                const { getCommunityDemoMessages, communityDemoStore } = await import('../demo_chats');
                
                // Check if this is a community demo chat (demo-1, demo-2, etc.)
                // Community demos are fetched from server with language-specific translations
                // ARCHITECTURE: Community demos use a pattern-based ID check (startsWith 'demo-')
                // but exclude static intro chats which are in DEMO_CHATS
                const isStatic = DEMO_CHATS.some(c => c.chat_id === snapshotChat.chat_id);
                if (snapshotChat.chat_id.startsWith('demo-') && !isStatic) {
                    console.debug('[ActiveChat] Language changed - reloading community demo:', snapshotChat.chat_id);
                    
                    // ARCHITECTURE: Community demos are reloaded by Chats.svelte when language changes
                    // The 'language-changed' event triggers loadDemoChatsFromServer(true) in Chats.svelte
                    // which clears the cache and fetches demos in the new language
                    // We need to wait for that reload to complete before we can get the new messages
                    
                    // Wait for Chats.svelte to finish reloading the community demos
                    // We use waitForLoadingComplete() which waits for the store's loading flag to clear
                    await communityDemoStore.waitForLoadingComplete();
                    
                    // Get the reloaded messages from communityDemoStore
                    const newMessages = getCommunityDemoMessages(snapshotChat.chat_id);
                    
                    if (newMessages.length > 0) {
                        console.debug(`[ActiveChat] Reloaded ${newMessages.length} messages for community demo ${snapshotChat.chat_id}`);
                        
                        // CRITICAL: Force new array reference to ensure reactivity
                        currentMessages = newMessages.map(msg => ({ ...msg }));
                        
                        // Update chat history display
                        if (chatHistoryRef) {
                            chatHistoryRef.updateMessages(currentMessages);
                        } else {
                            console.warn('[ActiveChat] chatHistoryRef is null - cannot update messages');
                        }
                    } else {
                        console.warn('[ActiveChat] No messages found for community demo after language change:', snapshotChat.chat_id);
                        console.debug('[ActiveChat] Community demos may still be loading - messages will update when available');
                    }
                    
                    return;
                }
                
                // Find the static public chat (check both DEMO_CHATS and LEGAL_CHATS) and translate it
                // Use snapshotChat to ensure we have the current value
                let publicChat = DEMO_CHATS.find(chat => chat.chat_id === snapshotChat.chat_id);
                if (!publicChat) {
                    publicChat = LEGAL_CHATS.find(chat => chat.chat_id === snapshotChat.chat_id);
                }
                if (publicChat) {
                    // CRITICAL: Re-translate the chat with the new locale
                    // translateDemoChat uses get(text) which reads from the locale store
                    // By waiting for waitLocale() and tick() above, we ensure translations are loaded and store is updated
                    const translatedChat = translateDemoChat(publicChat);
                    
                    // Reload the public chat messages with new translations (check both DEMO_CHATS and LEGAL_CHATS)
                    // getDemoMessages internally calls translateDemoChat again, which will use the updated locale
                    const newMessages = getDemoMessages(snapshotChat.chat_id, DEMO_CHATS, LEGAL_CHATS);
                    
                    // CRITICAL: Force new array reference to ensure reactivity
                    // This ensures ChatHistory detects the change even if message IDs are the same
                    // Also ensure each message object is new to force re-rendering
                    currentMessages = newMessages.map(msg => ({ ...msg }));
                    
                    // Reload follow-up suggestions with new translations
                    if (translatedChat.follow_up_suggestions) {
                        followUpSuggestions = translatedChat.follow_up_suggestions;
                    }
                    
                    // Update chat history display - this will force re-processing
                    if (chatHistoryRef) {
                        chatHistoryRef.updateMessages(currentMessages);
                    } else {
                        console.warn('[ActiveChat] chatHistoryRef is null - cannot update messages');
                    }
                } else {
                    console.warn('[ActiveChat] Public chat not found in DEMO_CHATS or LEGAL_CHATS:', snapshotChat.chat_id);
                }
            } catch (error) {
                console.error('[ActiveChat] Error in language change handler:', error);
            }
        };
        
        // Listen to both events to catch language changes
        // 'language-changed' fires immediately, 'language-changed-complete' fires after a delay
        window.addEventListener('language-changed', handleLanguageChange);
        window.addEventListener('language-changed-complete', handleLanguageChange);

        // Listen for the dislike/retry prompt from ChatMessage's report-bad-answer flow
        window.addEventListener('setRetryMessage', handleSetRetryMessage);

        // Add event listeners for both chat updates and message status changes
        const chatUpdateHandler = ((event: CustomEvent) => {
            handleChatUpdated(event);
        }) as EventListenerCallback;

        const messageStatusHandler = ((event: CustomEvent) => {
            // Call the component's own method which correctly updates currentMessages,
            // saves to DB, and calls chatHistoryRef.updateMessages()
            handleMessageStatusChanged(event); 
        }) as EventListenerCallback;

        // Listen to events directly from chatSyncService
        chatSyncService.addEventListener('chatUpdated', chatUpdateHandler);
        chatSyncService.addEventListener('messageStatusChanged', messageStatusHandler);
        
        // Add listener for AI message chunks
        console.log('[ActiveChat] 📌 Registering aiMessageChunk event listener');
        chatSyncService.addEventListener('aiMessageChunk', handleAiMessageChunk as EventListenerCallback);
        console.log('[ActiveChat] ✅ aiMessageChunk event listener registered');
        
        // Add listeners for AI thinking/reasoning content (Gemini, Anthropic Claude)
        console.log('[ActiveChat] 📌 Registering thinking event listeners');
        chatSyncService.addEventListener('aiThinkingChunk', handleAiThinkingChunk as EventListenerCallback);
        chatSyncService.addEventListener('aiThinkingComplete', handleAiThinkingComplete as EventListenerCallback);
        console.log('[ActiveChat] ✅ Thinking event listeners registered');

        // Add listeners for AI task state changes
        const aiTaskInitiatedHandler = (async (event: CustomEvent<AITaskInitiatedPayload>) => {
            const { chat_id, user_message_id } = event.detail;
            if (chat_id === currentChat?.chat_id) {
                const messageIndex = currentMessages.findIndex(m => m.message_id === user_message_id);
                if (messageIndex !== -1) {
                    const updatedMessage = { ...currentMessages[messageIndex], status: 'processing' as const };
                    currentMessages[messageIndex] = updatedMessage;
                    currentMessages = [...currentMessages]; // Trigger reactivity

                    // Save status update to DB (only the user message, not the placeholder)
                    try {
                        await chatDB.saveMessage(updatedMessage);
                    } catch (error) {
                        console.error('[ActiveChat] Error updating user message status to processing in DB:', error);
                    }

                    if (chatHistoryRef) {
                        chatHistoryRef.updateMessages(currentMessages);
                    }
                }
                
                // ─── Progressive AI Status Indicator: Transition to 'processing' phase ─────
                // Start the timed step progression with appropriate steps for new/existing chat
                startProcessingStepProgression(isNewChatProcessing);
                console.debug('[ActiveChat] Processing phase set to PROCESSING', { isNewChat: isNewChatProcessing });
                
                _aiTaskStateTrigger++;
            }
        }) as EventListenerCallback;

        const aiTaskEndedHandler = ((event: CustomEvent<{ chatId: string }>) => {
            if (event.detail.chatId === currentChat?.chat_id) {
                _aiTaskStateTrigger++;
                
                // ─── Progressive AI Status Indicator: Clear on task end (safety fallback) ─────
                clearProcessingPhase();
                
                // FALLBACK: Mark ALL thinking entries as complete when AI task ends
                // This ensures no thinking state is left in "streaming" mode after the task finishes
                let hasStreamingThinking = false;
                thinkingContentByTask.forEach((entry, taskId) => {
                    if (entry.isStreaming) {
                        hasStreamingThinking = true;
                        thinkingContentByTask.set(taskId, {
                            content: entry.content,
                            isStreaming: false,
                            signature: entry.signature,
                            totalTokens: entry.totalTokens
                        });
                        console.log(`[ActiveChat] 🧠 Marking thinking as complete (task ended fallback) | task_id: ${taskId}`);
                    }
                });
                
                // Force reactivity if we made changes
                if (hasStreamingThinking) {
                    thinkingContentByTask = new Map(thinkingContentByTask);
                    if (chatHistoryRef) {
                        chatHistoryRef.updateMessages(currentMessages);
                    }
                }
            }
        }) as EventListenerCallback;

        const aiTypingStartedHandler = (async (event: CustomEvent) => {
            const { chat_id, user_message_id, category, model_name, provider_name, server_region, is_continuation } = event.detail;
            console.log('[ActiveChat] aiTypingStartedHandler fired', { 
                chat_id, 
                currentChatId: currentChat?.chat_id,
                eventPayload: { category, model_name, provider_name, server_region, is_continuation },
                storeStatus: currentTypingStatus ? { 
                    isTyping: currentTypingStatus.isTyping, 
                    chatId: currentTypingStatus.chatId, 
                    category: currentTypingStatus.category,
                    modelName: currentTypingStatus.modelName,
                    providerName: currentTypingStatus.providerName,
                    serverRegion: currentTypingStatus.serverRegion
                } : null
            });
            if (chat_id === currentChat?.chat_id) {
                const messageIndex = currentMessages.findIndex(m => m.message_id === user_message_id);
                // Update user message status to synced from both 'processing' and 'waiting_for_user'
                // (waiting_for_user is set when paused for app settings permission or credit issues)
                if (messageIndex !== -1 && (currentMessages[messageIndex].status === 'processing' || currentMessages[messageIndex].status === 'waiting_for_user')) {
                    const updatedMessage = { ...currentMessages[messageIndex], status: 'synced' as const };
                    currentMessages[messageIndex] = updatedMessage;
                    currentMessages = [...currentMessages];

                    try {
                        await chatDB.saveMessage(updatedMessage);
                    } catch (error) {
                        console.error('[ActiveChat] Error updating user message status to synced in DB:', error);
                    }

                    if (chatHistoryRef) {
                        chatHistoryRef.updateMessages(currentMessages);
                    }
                }
                
                // ─── Progressive AI Status Indicator: Transition to 'typing' phase ─────
                // For continuation tasks (e.g., after focus mode auto-confirm), skip the centered
                // typing indicator. The assistant message already exists (with the focus embed),
                // so showing a centered "is typing..." overlay over it would be confusing.
                // The bottom inline indicator will handle the typing status during streaming.
                if (is_continuation) {
                    console.debug('[ActiveChat] Skipping centered typing indicator for continuation task');
                    // Ensure the centered indicator is cleared (in case it was somehow active)
                    clearProcessingPhase();
                } else {
                    // Transition to typing phase with mate/model info from the server.
                    // This replaces the processing overlay (step cards + spinner) with the typing indicator.
                    // Build the typing phase with resolved text lines:
                    //   Line 1: "{mate} is typing..."
                    //   Line 2: model display name (e.g., "Gemini 3 Flash")
                    //   Line 3: "via {provider} {flag}" (e.g., "via Google 🇺🇸")
                    //
                    // IMPORTANT: Use event.detail (the original WebSocket payload) as primary data source
                    // for model/provider info, with the store as fallback. This avoids any potential
                    // timing/reactivity issues where the $state variable hasn't updated yet when
                    // the custom event handler fires.
                    const resolvedCategory = category || currentTypingStatus?.category;
                    const resolvedModelName = model_name || currentTypingStatus?.modelName;
                    const resolvedProviderName = provider_name || currentTypingStatus?.providerName;
                    const resolvedServerRegion = server_region || currentTypingStatus?.serverRegion;
                    
                    console.log('[ActiveChat] Typing phase transition data', {
                        fromEvent: { category, model_name, provider_name, server_region },
                        fromStore: { 
                            category: currentTypingStatus?.category, 
                            modelName: currentTypingStatus?.modelName, 
                            providerName: currentTypingStatus?.providerName, 
                            serverRegion: currentTypingStatus?.serverRegion 
                        },
                        resolved: { resolvedCategory, resolvedModelName, resolvedProviderName, resolvedServerRegion },
                        currentProcessingPhase: processingPhase?.phase
                    });

                    // ─── Minimum display time for step cards ─────────────────────────────
                    // When preprocessing step cards are visible (completedSteps > 0), enforce
                    // a minimum display time of 1500ms before transitioning to the typing phase.
                    // This ensures users can actually read the accumulated step cards before
                    // they disappear. The step events arrive in a burst (from one LLM call),
                    // so without this delay the cards would flash and immediately be replaced.
                    const hasVisibleStepCards = processingPhase?.phase === 'processing'
                        && processingPhase.completedSteps.length > 0;
                    if (hasVisibleStepCards && lastStepCardTimestamp > 0) {
                        const elapsed = Date.now() - lastStepCardTimestamp;
                        const MIN_STEP_DISPLAY_MS = 1500;
                        if (elapsed < MIN_STEP_DISPLAY_MS) {
                            const remainingDelay = MIN_STEP_DISPLAY_MS - elapsed;
                            console.debug(`[ActiveChat] Delaying typing transition by ${remainingDelay}ms to show step cards`);
                            // Capture the current chat_id to avoid stale transitions after chat switch
                            const transitionChatId = chat_id;
                            setTimeout(() => {
                                // Only apply if we're still on the same chat and in processing phase
                                if (currentChat?.chat_id !== transitionChatId) return;
                                if (processingPhase?.phase !== 'processing') return;
                                applyTypingPhaseTransition(resolvedCategory, resolvedModelName, resolvedProviderName, resolvedServerRegion);
                            }, remainingDelay);
                            // Skip the immediate transition below
                            return;
                        }
                    }

                    applyTypingPhaseTransition(resolvedCategory, resolvedModelName, resolvedProviderName, resolvedServerRegion);
                }
            }
        }) as EventListenerCallback;

        // Handle chat deletion - if the currently active chat is deleted, reset to new chat
        const chatDeletedHandler = ((event: CustomEvent) => {
            const { chat_id } = event.detail;
            console.debug('[ActiveChat] Received chatDeleted event for chat:', chat_id, 'Current chat:', currentChat?.chat_id);
            
            if (currentChat && chat_id === currentChat.chat_id) {
                console.info('[ActiveChat] Currently active chat was deleted. Resetting to new chat state.');
                // Reset to new chat state using the existing handler
                handleNewChatClick();
            }
        }) as EventListenerCallback;

        // Handle single message deletion (from this device or broadcast from another device)
        const messageDeletedHandler = ((event: CustomEvent) => {
            const { chatId, messageId } = event.detail;
            if (chatId !== currentChat?.chat_id) return;

            console.debug(`[ActiveChat] Received messageDeleted event for message ${messageId} in chat ${chatId}`);
            // Remove the deleted message from the current messages array
            const beforeCount = currentMessages.length;
            currentMessages = currentMessages.filter(m => m.message_id !== messageId);

            if (currentMessages.length < beforeCount) {
                console.info(`[ActiveChat] Removed message ${messageId} from UI (${beforeCount} -> ${currentMessages.length})`);
                if (chatHistoryRef) {
                    chatHistoryRef.updateMessages(currentMessages);
                }
            }
        }) as EventListenerCallback;

        chatSyncService.addEventListener('aiTaskInitiated', aiTaskInitiatedHandler);
        chatSyncService.addEventListener('aiTypingStarted', aiTypingStartedHandler);
        chatSyncService.addEventListener('aiTaskEnded', aiTaskEndedHandler);
        chatSyncService.addEventListener('chatDeleted', chatDeletedHandler);
        chatSyncService.addEventListener('messageDeleted', messageDeletedHandler);

        // ─── Real-time preprocessing step events ─────────────────────────────────────────
        // The backend emits preprocessing_step events (title_generated, mate_selected,
        // model_selected) after the single preprocessing LLM call resolves.
        // handlePreprocessingStepImpl in chatSyncServiceHandlersAI.ts dispatches these as
        // "preprocessingStep" CustomEvents on window. We listen here to update the
        // processingPhase.completedSteps array with each non-skipped step card.
        const preprocessingStepHandler = ((event: CustomEvent<PreprocessorStepResult>) => {
            const step = event.detail;
            console.debug('[ActiveChat] preprocessingStep event received', step);

            // Only update if we're still in the processing phase (not yet typing or null)
            if (processingPhase?.phase !== 'processing') return;

            // Skipped steps are silently ignored — no card rendered
            if (step.skipped) {
                console.debug('[ActiveChat] Skipping preprocessing step (skipped=true):', step.step);
                return;
            }

            // Capture mate name from the mate_selected step for later use in
            // "{Mate} is typing..." spinner text after model_selected.
            if (step.step === 'mate_selected' && step.data?.mate_name) {
                selectedPreprocessingMateName = step.data.mate_name;
            }

            // Advance the spinner text to the next expected step.
            // After model_selected (final step), show "{Mate} is typing..." using the
            // mate name from the earlier mate_selected step (or category fallback).
            const nextStepText = (() => {
                switch (step.step) {
                    case 'title_generated':
                        return $text('enter_message.status.selecting_mate');
                    case 'mate_selected':
                        return $text('enter_message.status.selecting_model');
                    case 'model_selected': {
                        // Use the mate name captured from the earlier mate_selected step,
                        // falling back to category-based mate name from the step data or
                        // "Analyzing your message..." if no mate info is available yet.
                        const mateName = selectedPreprocessingMateName
                            || (step.data?.mate_category ? $text('mates.' + step.data.mate_category) : null);
                        if (mateName) {
                            return $text('enter_message.is_typing').replace('{mate}', mateName);
                        }
                        return $text('enter_message.status.analyzing_message');
                    }
                    default:
                        return processingPhase.statusLines[0];
                }
            })();

            // Record the timestamp of this step card so we can enforce a minimum
            // display time before transitioning to the typing phase.
            lastStepCardTimestamp = Date.now();

            // Accumulate this completed step and advance the spinner
            processingPhase = {
                phase: 'processing',
                statusLines: [nextStepText],
                showIcon: true,
                completedSteps: [...processingPhase.completedSteps, step],
            };

            console.debug('[ActiveChat] Processing phase updated with completed step:', step.step, '| completedSteps count:', processingPhase.completedSteps.length);
        }) as EventListenerCallback;

        window.addEventListener('preprocessingStep', preprocessingStepHandler);
        
        // STREAM INTERRUPTION RECOVERY: When the WebSocket reconnects after a disconnect
        // that interrupted an active AI stream, finalize any streaming messages in the current
        // chat by saving their current content to the DB and marking them as 'synced'.
        // The subsequent phased sync will deliver the server-persisted version.
        const aiStreamInterruptedHandler = (async (event: CustomEvent) => {
            const { chatId } = event.detail;
            if (chatId !== currentChat?.chat_id) return;

            console.warn(`[ActiveChat] AI stream interrupted for current chat ${chatId} - finalizing streaming/processing messages`);
            for (const msg of currentMessages) {
                // Recover messages stuck in 'streaming' (stream was interrupted mid-flight)
                // AND 'processing' (task was dispatched but worker never picked it up / crashed)
                if (msg.status === 'streaming' || (msg.role === 'user' && msg.status === 'processing')) {
                    const finalized = { ...msg, status: 'synced' as const };
                    const msgIndex = currentMessages.findIndex(m => m.message_id === msg.message_id);
                    if (msgIndex !== -1) {
                        currentMessages[msgIndex] = finalized;
                    }
                    try {
                        await chatDB.saveMessage(finalized);
                        console.info(`[ActiveChat] Finalized interrupted ${msg.status} message ${msg.message_id} (${msg.content?.length || 0} chars saved)`);
                    } catch (error) {
                        console.error(`[ActiveChat] Error finalizing interrupted message ${msg.message_id}:`, error);
                    }
                }
            }
            currentMessages = [...currentMessages];
            if (chatHistoryRef) {
                chatHistoryRef.updateMessages(currentMessages);
            }
        }) as EventListenerCallback;
        chatSyncService.addEventListener('aiStreamInterrupted', aiStreamInterruptedHandler);

        const postProcessingHandler = handlePostProcessingCompleted as EventListenerCallback;
        chatSyncService.addEventListener('postProcessingCompleted', postProcessingHandler);
        console.debug('[ActiveChat] ✅ Registered postProcessingCompleted event listener');
        
        // CRITICAL: Listen for embed updates to force re-render when embed data arrives
        // During streaming, embed NodeViews are created with "processing" status before the
        // actual embed data arrives. When `send_embed_data` stores the embed and dispatches
        // `embedUpdated`, we need to force a re-render so the embed content is displayed.
        const embedUpdatedHandler = ((event: CustomEvent) => {
            const { chat_id, message_id, embed_id, status, isProcessing } = event.detail;
            
            // Only process if this embed is for the current chat
            if (!currentChat || currentChat.chat_id !== chat_id) {
                console.debug(`[ActiveChat] embedUpdated for different chat (${chat_id}), ignoring`);
                return;
            }
            
            console.info(`[ActiveChat] 🔄 embedUpdated received for embed ${embed_id} (status=${status}, isProcessing=${isProcessing})`);
            
            // Force a re-render of messages by updating the ChatHistory component
            // This will cause Tiptap to re-render embed NodeViews, which will now find
            // the embed data in the store and display the actual content instead of "Processing..."
            if (chatHistoryRef && currentMessages.length > 0) {
                // CRITICAL: For error/cancelled embeds, check if the error is already tracked.
                // If so, skip the re-render to prevent an infinite loop where:
                //   error embed -> re-render -> resolveEmbed() -> request_embed -> send_embed_data(error)
                //   -> embedUpdated(error) -> re-render -> ...
                if (status === 'error' || status === 'cancelled') {
                    const targetMsg = currentMessages.find(
                        msg => msg.message_id === message_id || msg.status === 'streaming' || msg.role === 'assistant'
                    );
                    if (targetMsg) {
                        const existingErrors: Set<string> = (targetMsg as MessageWithEmbedMeta)._embedErrors ?? new Set();
                        if (existingErrors.has(embed_id)) {
                            console.debug(`[ActiveChat] Error already tracked for embed ${embed_id}, skipping re-render to prevent loop`);
                            return;
                        }
                    }
                }
                
                // Create new message array references to force Svelte reactivity
                // CRITICAL: We need to create NEW content objects to break reference equality
                // so that ChatHistory detects the change and re-renders ReadOnlyMessage components
                currentMessages = currentMessages.map(msg => {
                    // Only update the specific message that contains this embed
                    // For now, update all streaming/assistant messages to be safe
                    if (msg.message_id === message_id || msg.status === 'streaming' || msg.role === 'assistant') {
                        const updated: typeof msg = {
                            ...msg,
                            // Add a timestamp to force content re-processing
                            _embedUpdateTimestamp: Date.now()
                        };
                        // Track embed errors on the message so ChatMessage can show an error banner
                        // instead of rendering the broken embed card
                        if (status === 'error') {
                            const existingErrors: Set<string> = (msg as MessageWithEmbedMeta)._embedErrors ?? new Set();
                            existingErrors.add(embed_id);
                            (updated as MessageWithEmbedMeta)._embedErrors = existingErrors;
                            console.info(`[ActiveChat] Tracked embed error on message ${message_id}: embed ${embed_id}`);
                        }
                        return updated;
                    }
                    return msg;
                });
                
                chatHistoryRef.updateMessages(currentMessages);
                console.debug(`[ActiveChat] 🔄 Forced message re-render after embed update for ${embed_id}`);
            }
        }) as EventListenerCallback;
        
        chatSyncService.addEventListener('embedUpdated', embedUpdatedHandler);
        console.debug('[ActiveChat] ✅ Registered embedUpdated event listener');
        
        // Handle skill preview updates - add app cards to messages
        const handleSkillPreviewUpdate = async (event: CustomEvent) => {
            const { task_id, previewData, chat_id, message_id } = event.detail as SkillPreviewDetail;
            
            // Only process if this preview is for the current chat
            if (!currentChat || currentChat.chat_id !== chat_id) {
                console.debug('[ActiveChat] Skill preview update for different chat, ignoring');
                return;
            }
            
            // Find the message by message_id
            let messageIndex = currentMessages.findIndex(m => m.message_id === message_id);
            
            // If message doesn't exist yet, create a placeholder assistant message
            // This happens when skill preview arrives BEFORE the first streaming chunk
            // (new architecture: placeholder embed is yielded immediately when tool call is detected)
            if (messageIndex === -1) {
                console.debug('[ActiveChat] Creating placeholder assistant message for skill preview:', message_id);
                
                // Find the user message to get user_message_id (should be the last user message)
                const lastUserMessage = [...currentMessages].reverse().find(m => m.role === 'user');
                
                // Create placeholder assistant message
                const placeholderMessage: ChatMessageModel = {
                    message_id: message_id,
                    chat_id: chat_id,
                    user_message_id: lastUserMessage?.message_id,
                    role: 'assistant',
                    content: '', // Empty content - will be filled by streaming chunks
                    status: 'streaming',
                    created_at: Math.floor(Date.now() / 1000),
                    encrypted_content: '',
                    encrypted_category: undefined
                };
                
                // Add the placeholder message to currentMessages
                currentMessages = [...currentMessages, placeholderMessage];
                
                // Save to DB
                try {
                    await chatDB.saveMessage(placeholderMessage);
                    console.debug('[ActiveChat] Saved placeholder assistant message to DB');
                } catch (error) {
                    console.error('[ActiveChat] Error saving placeholder assistant message to DB:', error);
                }
                
                // Update ChatHistory
                if (chatHistoryRef) {
                    chatHistoryRef.updateMessages(currentMessages);
                }
                
                // Now find the newly added message
                messageIndex = currentMessages.findIndex(m => m.message_id === message_id);
            }
            
            if (messageIndex === -1) {
                console.warn('[ActiveChat] Failed to find or create message for skill preview:', message_id);
                return;
            }
            
            // Create app card from skill preview data
            let appCard: AppCardEntry | null = null;
            if (previewData.app_id === 'web' && previewData.skill_id === 'search') {
                // Create WebSearchEmbedPreview card
                appCard = {
                    component: WebSearchEmbedPreview,
                    props: {
                        id: task_id,
                        previewData: previewData,
                        isMobile: $isMobileView,
                        onFullscreen: () => {
                            // Open fullscreen view
                            showCodeFullscreen = false; // Close code fullscreen if open
                            // Set fullscreen data for web search
                            embedFullscreenData = {
                                embedType: 'app-skill-use',
                                embedData: { status: toEmbedStatus(previewData.status) },
                                decodedContent: previewData as unknown as EmbedDecodedContent
                            };
                            showEmbedFullscreen = true;
                            console.debug('[ActiveChat] Opening fullscreen for web search skill:', task_id);
                        }
                    }
                };
            } else if (previewData.app_id === 'videos' && previewData.skill_id === 'get_transcript') {
                // Create VideoTranscriptEmbedPreview card
                appCard = {
                    component: VideoTranscriptEmbedPreview,
                    props: {
                        id: task_id,
                        previewData: previewData,
                        isMobile: $isMobileView,
                        onFullscreen: () => {
                            // Open fullscreen view
                            showCodeFullscreen = false; // Close code fullscreen if open
                            // Set fullscreen data for video transcript
                            embedFullscreenData = {
                                embedType: 'app-skill-use',
                                embedData: { status: toEmbedStatus(previewData.status) },
                                decodedContent: previewData as unknown as EmbedDecodedContent
                            };
                            showEmbedFullscreen = true;
                            console.debug('[ActiveChat] Opening fullscreen for video transcript skill:', task_id);
                        }
                    }
                };
            }
            
            if (appCard) {
                // Update the message with the app card
                const updatedMessages = [...currentMessages];
                const message = updatedMessages[messageIndex] as MessageWithAppCards;
                
                // Initialize appCards array if it doesn't exist
                if (!message.appCards) {
                    message.appCards = [];
                }
                
                // Check if this task_id already has a card (update existing)
                const existingCardIndex = message.appCards.findIndex(
                    (card) => card.props?.id === task_id
                );
                
                if (existingCardIndex !== -1) {
                    // Update existing card
                    message.appCards[existingCardIndex] = appCard;
                } else {
                    // Add new card
                    message.appCards.push(appCard);
                }
                
                // Update messages
                currentMessages = updatedMessages;
                
                // Update ChatHistory
                if (chatHistoryRef) {
                    chatHistoryRef.updateMessages(currentMessages);
                }
                
                console.debug('[ActiveChat] Added/updated skill preview card for message:', message_id);
            }
        };
        
        skillPreviewService.addEventListener('skillPreviewUpdate', handleSkillPreviewUpdate as EventListenerCallback);

        return () => {
            // Remove listeners from chatSyncService
            chatSyncService.removeEventListener('chatUpdated', chatUpdateHandler);
            chatSyncService.removeEventListener('messageStatusChanged', messageStatusHandler);
            unsubscribeAiTyping(); // Unsubscribe from AI typing store
            unsubscribeDraftState(); // Unsubscribe from draft state
            chatSyncService.removeEventListener('aiMessageChunk', handleAiMessageChunk as EventListenerCallback); // Remove listener
            chatSyncService.removeEventListener('aiTaskInitiated', aiTaskInitiatedHandler);
            chatSyncService.removeEventListener('aiTypingStarted', aiTypingStartedHandler);
            chatSyncService.removeEventListener('aiTaskEnded', aiTaskEndedHandler);
            // Remove thinking/reasoning event listeners
            chatSyncService.removeEventListener('aiThinkingChunk', handleAiThinkingChunk as EventListenerCallback);
            chatSyncService.removeEventListener('aiThinkingComplete', handleAiThinkingComplete as EventListenerCallback);
            chatSyncService.removeEventListener('chatDeleted', chatDeletedHandler);
            chatSyncService.removeEventListener('messageDeleted', messageDeletedHandler);
            window.removeEventListener('preprocessingStep', preprocessingStepHandler);
            chatSyncService.removeEventListener('postProcessingCompleted', handlePostProcessingCompleted as EventListenerCallback);
            chatSyncService.removeEventListener('aiStreamInterrupted', aiStreamInterruptedHandler);
            chatSyncService.removeEventListener('embedUpdated', embedUpdatedHandler);
            skillPreviewService.removeEventListener('skillPreviewUpdate', handleSkillPreviewUpdate as EventListenerCallback);
            // Remove language change listener
            window.removeEventListener('language-changed', handleLanguageChange);
            window.removeEventListener('language-changed-complete', handleLanguageChange);
            // Remove login interface event listeners
            window.removeEventListener('openLoginInterface', handleOpenLoginInterface as EventListenerCallback);
            window.removeEventListener('openSignupInterface', handleOpenSignupInterface as EventListenerCallback);
            window.removeEventListener('closeLoginInterface', handleCloseLoginInterface as EventListenerCallback);
            window.removeEventListener('loadDemoChat', handleLoadDemoChat as EventListenerCallback);
            // Remove draft save sync listener
            window.removeEventListener('localChatListChanged', handleDraftSaveSync as EventListenerCallback);
            // Remove preprocessing step chat refresh listener
            window.removeEventListener('localChatListChanged', handlePreprocessingChatRefresh as EventListenerCallback);
            if (handleLogoutEvent) {
                window.removeEventListener('userLoggingOut', handleLogoutEvent as EventListenerCallback);
            }
            window.removeEventListener('triggerNewChat', handleTriggerNewChat as EventListenerCallback);
            window.removeEventListener('hiddenChatsLocked', handleHiddenChatsLocked as EventListenerCallback);
            window.removeEventListener('hiddenChatsAutoLocked', handleHiddenChatsLocked as EventListenerCallback);
            window.removeEventListener('setRetryMessage', handleSetRetryMessage);
            // Remove embed and video PiP fullscreen listeners
            document.removeEventListener('embedfullscreen', embedFullscreenHandler as EventListenerCallback);
            document.removeEventListener('videopip-restore-fullscreen', videoPipRestoreHandler as EventListenerCallback);
            // Remove focus mode event listeners
            document.removeEventListener('focusModeRejected', focusModeRejectedHandler as EventListenerCallback);
            document.removeEventListener('focusModeDeactivated', focusModeDeactivatedHandler as EventListenerCallback);
            document.removeEventListener('focusModeDetailsRequested', focusModeDetailsHandler as EventListenerCallback);
            document.removeEventListener('focusModeContextMenu', focusModeContextMenuHandler as EventListenerCallback);
        };
    });

    onDestroy(() => {
        // Ensure all subscriptions and listeners are cleaned up if not done in onMount's return
        // This is a fallback, prefer cleanup in onMount's return.
        // Note: unsubscribeAiTyping and removeEventListener for aiMessageChunk are already in onMount's return.
        // If chatUpdated and messageStatusChanged were missed in onMount's return, they would need to be here.
        // However, with the change above, all relevant listeners are cleaned up in onMount's return.
        // For safety, we can leave the existing lines or remove them if confident.
        // To be safe and ensure no double-unsubscribe issues if onMount's return is ever bypassed:
        // (Though Svelte's lifecycle should prevent this)
        // unsubscribeAiTyping(); // Already in onMount return
        // chatSyncService.removeEventListener('aiMessageChunk', handleAiMessageChunk as EventListenerCallback); // Already in onMount return
        
        // Unsubscribe from PII visibility store
        unsubPiiVisibility();
        
        // Clean up processing phase timers
        clearProcessingPhase();
    });
</script>

<div 
    class="active-chat-container" 
    class:dimmed={isDimmed} 
    class:login-mode={!showChat} 
    class:scaled={activeScaling}
    class:narrow={isEffectivelyNarrow}
    class:medium={isMedium && !showSideBySideLayout}
    class:wide={isWide && !showSideBySideLayout}
    class:extra-wide={isExtraWide}
    class:side-by-side-active={showSideBySideLayout}
    bind:clientWidth={containerWidth}
>
    {#if !showChat}
        <!-- Signup status bar - only show during signup process, not on basics or alpha disclaimer steps -->
        <!-- Moved to be a child of active-chat-container for better positioning with gradient -->
        {#if $isInSignupProcess && $currentSignupStep !== STEP_BASICS && $currentSignupStep !== STEP_ALPHA_DISCLAIMER}
            <div class="status-wrapper" transition:fade={fadeParams}>
                <SignupStatusbar currentStepName={$currentSignupStep} stepSequenceOverride={stepSequence} paymentEnabled={paymentEnabled} isSelfHosted={isSelfHosted} />
            </div>
        {/if}
        
        <div 
            class="login-wrapper" 
            in:fly={loginTransitionProps} 
            out:fade={{ duration: 200 }}
        >
            <Login on:loginSuccess={handleLoginSuccess} on:logout={handleLogout} />
        </div>
    {:else}
        <div 
            in:fade={{ duration: 300 }} 
            out:fade={{ duration: 200 }}
            class="content-container"
            class:side-by-side={showSideBySideLayout}
        >
            <!-- Main content wrapper that will handle the fullscreen layout -->
            <!-- When side-by-side mode is active, chat takes left portion with smooth transition -->
            <!-- Animation classes control enter/exit/minimize/restore transitions -->
            {#if showChatInSideBySide || !showSideBySideLayout}
            <div 
                class="chat-wrapper" 
                class:fullscreen={isFullscreen} 
                class:side-by-side-chat={showSideBySideLayout}
                class:side-by-side-entering={sideBySideAnimating && sideBySideAnimationDirection === 'enter'}
                class:side-by-side-exiting={sideBySideAnimating && sideBySideAnimationDirection === 'exit'}
                class:side-by-side-minimizing={sideBySideAnimating && sideBySideAnimationDirection === 'minimize'}
                class:side-by-side-restoring={sideBySideAnimating && sideBySideAnimationDirection === 'restore'}
            >
                <!-- Incognito mode banner - shows for incognito chats or new chats when incognito mode is active -->
                {#if currentChat?.is_incognito || (showWelcome && $incognitoMode)}
                    <div class="incognito-banner">
                        <div class="incognito-banner-icon">
                            <div class="icon settings_size subsetting_icon subsetting_icon_incognito"></div>
                        </div>
                        <span class="incognito-banner-text">{$text('settings.incognito')}</span>
                    </div>
                {/if}
                
                <!-- Left side container for chat history and buttons -->
                <div class="chat-side">
                    <div class="top-buttons">
                        <!-- Left side buttons -->
                        <div class="left-buttons">
                            {#if createButtonVisible}
                                <!-- New chat CTA button: same color as Send, pill shape, white icon; label visible on larger screens only -->
                                <div class="new-chat-button-wrapper new-chat-cta-wrapper">
                                    <button
                                        class="new-chat-cta-button"
                                        aria-label={$text('chat.new_chat')}
                                        onclick={handleNewChatClick}
                                        in:fade={{ duration: 300 }}
                                        use:tooltip
                                    >
                                        <span class="clickable-icon icon_create new-chat-cta-icon"></span>
                                        <span class="new-chat-cta-label">{$text('chat.new_chat')}</span>
                                    </button>
                                </div>
                            {/if}
                            {#if !showWelcome}
                                <!-- Share button - opens settings menu with share submenu -->
                                <!-- Use same wrapper design as new chat button -->
                                <div class="new-chat-button-wrapper">
                                    <button
                                        class="clickable-icon icon_share top-button"
                                        aria-label={$text('chat.share')}
                                        onclick={handleShareChat}
                                        use:tooltip
                                        style="margin: 5px;"
                                    >
                                    </button>
                                </div>
                            {/if}
                            <div class="new-chat-button-wrapper">
                                <button
                                    class="clickable-icon icon_bug top-button"
                                    aria-label={$text('header.report_issue')}
                                    onclick={handleReportIssue}
                                    use:tooltip
                                    style="margin: 5px;"
                                >
                                </button>
                            </div>
                        </div>

                        <!-- Right side buttons -->
                        <div class="right-buttons">
                            <!-- PII hide/unhide toggle - only shows when chat has sensitive data -->
                            {#if chatHasPII && !showWelcome}
                                <div class="new-chat-button-wrapper">
                                    <button
                                        class="clickable-icon {piiRevealed ? 'icon_visible' : 'icon_hidden'} top-button"
                                        class:pii-toggle-active={piiRevealed}
                                        aria-label={piiRevealed
                                            ? $text('chat.pii_hide')
                                            : $text('chat.pii_show')}
                                        onclick={handleTogglePIIVisibility}
                                        use:tooltip
                                        style="margin: 5px;"
                                    >
                                    </button>
                                </div>
                            {/if}
                            <!-- Minimize chat button - only shows in side-by-side mode -->
                            <!-- When clicked, hides the chat and shows only the embed fullscreen (overlay mode) -->
                            {#if showSideBySideFullscreen}
                                <div class="new-chat-button-wrapper">
                                    <button
                                        class="clickable-icon icon_minimize top-button"
                                        aria-label={$text('chat.minimize')}
                                        onclick={handleMinimizeChat}
                                        use:tooltip
                                        style="margin: 5px;"
                                    >
                                    </button>
                                </div>
                            {/if}
                            
                            <!-- Activate buttons once features are implemented -->
                            <!-- Video call button -->
                            <!-- <button 
                                class="clickable-icon icon_video_call top-button" 
                                aria-label={$text('chat.start_video_call')}
                                use:tooltip
                            ></button> -->
                            <!-- Audio call button -->
                            <!-- <button 
                                class="clickable-icon icon_call top-button" 
                                aria-label={$text('chat.start_audio_call')}
                                use:tooltip
                            ></button> -->
                        </div>
                    </div>

                    <!-- Welcome greeting – always visible on the new chat screen -->
                    <!-- Also hide on mobile when keyboard is open to free up vertical space -->
                    {#if showWelcome && !hideWelcomeForKeyboard}
                        <div
                            class="center-content"
                            transition:fade={{ duration: 300 }}
                        >
                            <div class="team-profile">
                                <!-- <div class="team-image" class:disabled={!isTeamEnabled}></div> -->
                                <div class="welcome-text">
                                    <h2>
                                        {#each welcomeHeadingParts as part, index}
                                            <span>{part}</span>{#if index < welcomeHeadingParts.length - 1}<br>{/if}
                                        {/each}
                                    </h2>
                                    <!-- Subtitle: "Continue where you left off" when resume chat, "Back to the intro" above for-everyone card for non-auth, else default prompt -->
                                    {#if resumeChatData}
                                        <p>{$text('chats.resume_last_chat.title')}</p>
                                    {:else if !$authStore.isAuthenticated}
                                        <p>{$text('chats.back_to_intro.title')}</p>
                                    {:else}
                                        <p>
                                            {#each welcomePromptParts as part, index}
                                                <span>{part}</span>{#if index < welcomePromptParts.length - 1}<br>{/if}
                                            {/each}
                                        </p>
                                    {/if}
                                </div>
                            </div>

                            <!-- Resume card: shown below greeting when there's a chat to resume (authenticated users only) -->
                            {#if resumeChatData}
                                {@const category = resumeChatCategory || 'general_knowledge'}
                                {@const gradientColors = getCategoryGradientColors(category)}
                                {@const iconName = getValidIconName(resumeChatIcon || '', category)}
                                {@const IconComponent = getLucideIcon(iconName)}
                                {@const ChevronRight = getLucideIcon('chevron-right')}
                                <button 
                                    class="resume-chat-card"
                                    onclick={handleResumeLastChat}
                                    type="button"
                                >
                                    <div 
                                        class="resume-chat-category-circle"
                                        style={gradientColors ? `background: linear-gradient(135deg, ${gradientColors.start}, ${gradientColors.end})` : 'background: #cccccc'}
                                    >
                                        <div class="resume-chat-category-icon">
                                            <IconComponent size={16} color="white" />
                                        </div>
                                    </div>
                                    <div class="resume-chat-content">
                                        <span class="resume-chat-title">{resumeChatTitle || 'Untitled Chat'}</span>
                                    </div>
                                    <div class="resume-chat-arrow">
                                        <ChevronRight size={16} color="var(--color-grey-50)" />
                                    </div>
                                </button>
                            <!-- Same card as above, for non-auth: link to for-everyone chat (same design as "last chat" card) -->
                            {:else if !$authStore.isAuthenticated}
                                {@const gradientColors = getCategoryGradientColors('openmates_official')}
                                {@const iconName = getValidIconName('sparkles', 'openmates_official')}
                                {@const IconComponent = getLucideIcon(iconName)}
                                {@const ChevronRight = getLucideIcon('chevron-right')}
                                <button 
                                    class="resume-chat-card"
                                    onclick={handleOpenIntroChat}
                                    type="button"
                                >
                                    <div 
                                        class="resume-chat-category-circle"
                                        style={gradientColors ? `background: linear-gradient(135deg, ${gradientColors.start}, ${gradientColors.end})` : 'background: #cccccc'}
                                    >
                                        <div class="resume-chat-category-icon">
                                            <IconComponent size={16} color="white" />
                                        </div>
                                    </div>
                                    <div class="resume-chat-content">
                                        <span class="resume-chat-title">{$text('demo_chats.for_everyone.title')}</span>
                                    </div>
                                    <div class="resume-chat-arrow">
                                        <ChevronRight size={16} color="var(--color-grey-50)" />
                                    </div>
                                </button>
                            {/if}
                        </div>
                    {/if}

                    <ChatHistory
                        bind:this={chatHistoryRef}
                        messageInputHeight={isFullscreen ? 0 : messageInputHeight + 40}
                        containerWidth={effectiveChatWidth}
                        currentChatId={currentChat?.chat_id}
                        {processingPhase}
                        {thinkingContentByTask}
                        {settingsMemoriesSuggestions}
                        {rejectedSuggestionHashes}
                        onSuggestionAdded={handleSettingsMemorySuggestionAdded}
                        onSuggestionRejected={handleSettingsMemorySuggestionRejected}
                        onSuggestionOpenForCustomize={handleSettingsMemorySuggestionOpenForCustomize}
                        on:messagesChange={handleMessagesChange}
                        on:chatUpdated={handleChatUpdated}
                        on:scrollPositionUI={handleScrollPositionUI}
                        on:scrollPositionChanged={handleScrollPositionChanged}
                        on:scrolledToBottom={handleScrolledToBottom}
                    />

                    <!-- Scroll-to-top button: visible when not at top and chat has messages -->
                    {#if !showWelcome && !isAtTop}
                        <button
                            class="scroll-nav-button scroll-to-top-button"
                            aria-label="Scroll to top"
                            onclick={() => chatHistoryRef?.scrollToTop()}
                        >
                            <span class="scroll-nav-icon scroll-nav-icon-up"></span>
                        </button>
                    {/if}

                    <!-- Scroll-to-bottom button: visible when not at bottom and chat has messages -->
                    {#if !showWelcome && !isAtBottom}
                        <button
                            class="scroll-nav-button scroll-to-bottom-button"
                            aria-label="Scroll to bottom"
                            onclick={() => chatHistoryRef?.scrollToBottom(true)}
                        >
                            <span class="scroll-nav-icon"></span>
                        </button>
                    {/if}
                </div>

                <!-- Right side container for message input -->
                <div class="message-input-wrapper">
                    {#if typingIndicatorLines.length > 0}
                        <div 
                            class="typing-indicator"
                            class:status-sending={typingIndicatorStatusType === 'sending'}
                            class:status-processing={typingIndicatorStatusType === 'processing'}
                            class:status-typing={typingIndicatorStatusType === 'typing'}
                            transition:fade={{ duration: 200 }}
                        >
                            {#each typingIndicatorLines as line, index}
                                <span class={index === 0 ? 'indicator-primary-line' : index === 1 ? 'indicator-secondary-line' : 'indicator-tertiary-line'}>{line}</span>
                            {/each}
                        </div>
                    {/if}

                    <div class="message-input-container">
                        <!-- New chat suggestions when no chat is open and user is at bottom/input active -->
                        <!-- Show immediately with default suggestions, then swap to user's real suggestions once sync completes -->
                        <!-- No longer gated behind initialSyncCompleted - NewChatSuggestions handles fallback to defaults -->
                        {#if showWelcome}
                            <NewChatSuggestions
                                messageInputContent={liveInputText}
                                onSuggestionClick={handleSuggestionClick}
                            />
                        {/if}

                        <!-- Banner for non-incognito chats when incognito mode is active -->
                        {#if $incognitoMode && currentChat && !currentChat.is_incognito && !showWelcome}
                            <div class="incognito-mode-applies-banner" transition:fade={{ duration: 200 }}>
                                <div class="incognito-mode-applies-icon">
                                    <div class="icon settings_size subsetting_icon subsetting_icon_incognito"></div>
                                </div>
                                <span class="incognito-mode-applies-text">
                                    {$text('settings.incognito_mode_applies_to_new_chats_only')}
                                </span>
                            </div>
                        {/if}

                        <!-- Push notification permission banner - shows after user sends first message -->
                        <!-- Only shown when: push is supported, permission not decided, user sent first message -->
                        {#if $shouldShowPushBanner && userSentFirstMessage && currentChat}
                            <PushNotificationBanner />
                        {/if}

                        <!-- Follow-up suggestions when input is focused -->
                        {#if showFollowUpSuggestions}
                            <FollowUpSuggestions
                                suggestions={followUpSuggestions}
                                messageInputContent={liveInputText}
                                onSuggestionClick={handleSuggestionClick}
                            />
                        {/if}

                        <!-- App settings/memories permission dialog has been moved to ChatHistory.svelte -->
                        <!-- This allows it to scroll with messages instead of being fixed at the bottom -->

                        <!-- Read-only indicator for shared chats -->
                        {#if currentChat && !chatOwnershipResolved && $authStore.isAuthenticated}
                            <div class="read-only-indicator" transition:fade={{ duration: 200 }}>
                                <div class="read-only-icon">🔒</div>
                                <p class="read-only-text">{$text('chat.read_only_shared')}</p>
                            </div>
                        {/if}

                        <!-- Pass currentChat?.id or temporaryChatId to MessageInput -->
                        <!-- Only show message input if user owns the chat or is not authenticated -->
                        {#if chatOwnershipResolved || !$authStore.isAuthenticated}
                            <MessageInput 
                                bind:this={messageInputFieldRef}
                                currentChatId={currentChat?.chat_id || temporaryChatId}
                                showActionButtons={showActionButtons}
                                on:codefullscreen={handleCodeFullscreen}
                                on:imagefullscreen={handleImageFullscreen}
                                on:sendMessage={handleSendMessage}
                                on:heightchange={handleInputHeightChange}
                                on:draftSaved={handleDraftSaved}
                                on:textchange={(e) => { 
                                    const t = (e.detail?.text || '');
                                    console.debug('[ActiveChat] textchange event received:', { text: t, length: t.length });
                                    liveInputText = t;
                                    // NOTE: messageInputHasContent is NOT set here from text alone —
                                    // bind:hasContent below is the authoritative source and correctly
                                    // accounts for embeds (images, files) even when there is no text.
                                }}
                                bind:isFullscreen
                                bind:hasContent={messageInputHasContent}
                                bind:isFocused={messageInputFocused}
                            />
                        {/if}
                    </div>
                </div>
            </div>
            {/if}

            {#if showCodeFullscreen}
                <CodeFullscreen 
                    code={fullscreenCodeData.code}
                    filename={fullscreenCodeData.filename}
                    language={fullscreenCodeData.language}
                    lineCount={fullscreenCodeData.lineCount}
                    onClose={handleCloseCodeFullscreen}
                />
            {/if}

            {#if showUploadedImageFullscreen}
                <UploadedImageFullscreen
                    src={uploadedImageFullscreenData.src}
                    s3BaseUrl={uploadedImageFullscreenData.s3BaseUrl}
                    files={uploadedImageFullscreenData.s3Files as { preview?: { s3_key: string; width: number; height: number; format: string }; full?: { s3_key: string; width: number; height: number; format: string }; original?: { s3_key: string; width: number; height: number; format: string } } | undefined}
                    aesKey={uploadedImageFullscreenData.aesKey}
                    aesNonce={uploadedImageFullscreenData.aesNonce}
                    filename={uploadedImageFullscreenData.filename}
                    isAuthenticated={uploadedImageFullscreenData.isAuthenticated}
                    fileSize={uploadedImageFullscreenData.fileSize}
                    fileType={uploadedImageFullscreenData.fileType}
                    onClose={handleCloseUploadedImageFullscreen}
                />
            {/if}
            
            <!-- Embed fullscreen view (app-skill-use, website, etc.) -->
            <!-- Container switches between overlay mode (default) and side panel mode (ultra-wide screens) -->
            <!-- Side-by-side mode shows embed next to chat for better large display usage -->
            <!-- Smooth transition: chat shrinks while fullscreen panel grows simultaneously -->
            {#if showEmbedFullscreen && embedFullscreenData}
                <div 
                    class="fullscreen-embed-container"
                    class:side-panel={showSideBySideLayout}
                    class:overlay-mode={!showSideBySideLayout}
                    class:side-by-side-entering={sideBySideAnimating && sideBySideAnimationDirection === 'enter'}
                    class:side-by-side-exiting={sideBySideAnimating && sideBySideAnimationDirection === 'exit'}
                    class:side-by-side-minimizing={sideBySideAnimating && sideBySideAnimationDirection === 'minimize'}
                    class:side-by-side-restoring={sideBySideAnimating && sideBySideAnimationDirection === 'restore'}
                >
                <!-- Key block forces complete recreation when embed changes -->
                <!-- This resets internal component state (e.g., selectedWebsite in WebSearchEmbedFullscreen) -->
                <!-- Without this, switching between same-type embeds would preserve stale child overlay state -->
                {#key embedFullscreenData.embedId}
                {#if embedFullscreenData.embedType === 'app-skill-use'}
                    {@const skillId = embedFullscreenData.decodedContent?.skill_id || ''}
                    {@const appId = embedFullscreenData.decodedContent?.app_id || ''}
                    
                    {#if appId === 'web' && skillId === 'search'}
                        <!-- Web Search Fullscreen -->
                        <!-- Pass embedIds for proper child embed loading (has extra_snippets, page_age, etc.) -->
                        <!-- Falls back to results if embedIds not available (legacy embeds) -->
                        <WebSearchEmbedFullscreen 
                            query={embedFullscreenData.decodedContent?.query || ''}
                            provider={embedFullscreenData.decodedContent?.provider || 'Brave'}
                            embedIds={embedFullscreenData.decodedContent?.embed_ids || embedFullscreenData.embedData?.embed_ids}
                            results={getWebSearchResults(embedFullscreenData.decodedContent?.results)}
                            status={normalizeEmbedStatus(embedFullscreenData.embedData?.status ?? embedFullscreenData.decodedContent?.status)}
                            errorMessage={typeof embedFullscreenData.decodedContent?.error === 'string' ? embedFullscreenData.decodedContent.error : ''}
                            embedId={embedFullscreenData.embedId}
                            onClose={handleCloseEmbedFullscreen}
                            {hasPreviousEmbed}
                            {hasNextEmbed}
                            onNavigatePrevious={handleNavigatePreviousEmbed}
                            onNavigateNext={handleNavigateNextEmbed}
                            showChatButton={showChatButtonInFullscreen}
                            onShowChat={handleShowChat}
                        />
                    {:else if appId === 'news' && skillId === 'search'}
                        <!-- News Search Fullscreen -->
                        <!-- Pass embedIds for proper child embed loading -->
                        <NewsSearchEmbedFullscreen 
                            query={embedFullscreenData.decodedContent?.query || ''}
                            provider={embedFullscreenData.decodedContent?.provider || 'Brave'}
                            embedIds={embedFullscreenData.decodedContent?.embed_ids || embedFullscreenData.embedData?.embed_ids}
                            results={getNewsSearchResults(embedFullscreenData.decodedContent?.results)}
                            embedId={embedFullscreenData.embedId}
                            onClose={handleCloseEmbedFullscreen}
                            {hasPreviousEmbed}
                            {hasNextEmbed}
                            onNavigatePrevious={handleNavigatePreviousEmbed}
                            onNavigateNext={handleNavigateNextEmbed}
                            showChatButton={showChatButtonInFullscreen}
                            onShowChat={handleShowChat}
                        />
                    {:else if appId === 'videos' && skillId === 'search'}
                        <!-- Videos Search Fullscreen -->
                        <!-- Pass embedIds for proper child embed loading -->
                        <VideosSearchEmbedFullscreen 
                            query={embedFullscreenData.decodedContent?.query || ''}
                            provider={embedFullscreenData.decodedContent?.provider || 'Brave'}
                            embedIds={embedFullscreenData.decodedContent?.embed_ids || embedFullscreenData.embedData?.embed_ids}
                            results={getVideoSearchResults(embedFullscreenData.decodedContent?.results)}
                            embedId={embedFullscreenData.embedId}
                            onClose={handleCloseEmbedFullscreen}
                            {hasPreviousEmbed}
                            {hasNextEmbed}
                            onNavigatePrevious={handleNavigatePreviousEmbed}
                            onNavigateNext={handleNavigateNextEmbed}
                            showChatButton={showChatButtonInFullscreen}
                            onShowChat={handleShowChat}
                        />
                    {:else if appId === 'maps' && skillId === 'search'}
                        <!-- Maps Search Fullscreen -->
                        <!-- Pass embedIds for proper child embed loading -->
                        <MapsSearchEmbedFullscreen 
                            query={embedFullscreenData.decodedContent?.query || ''}
                            provider={embedFullscreenData.decodedContent?.provider || 'Google'}
                            embedIds={embedFullscreenData.decodedContent?.embed_ids || embedFullscreenData.embedData?.embed_ids}
                            results={getPlaceSearchResults(embedFullscreenData.decodedContent?.results)}
                            embedId={embedFullscreenData.embedId}
                            onClose={handleCloseEmbedFullscreen}
                            {hasPreviousEmbed}
                            {hasNextEmbed}
                            onNavigatePrevious={handleNavigatePreviousEmbed}
                            onNavigateNext={handleNavigateNextEmbed}
                            showChatButton={showChatButtonInFullscreen}
                            onShowChat={handleShowChat}
                        />
                    {:else if appId === 'travel' && skillId === 'search_connections'}
                        <!-- Travel Search Connections Fullscreen -->
                        <TravelSearchEmbedFullscreen 
                            query={embedFullscreenData.decodedContent?.query || ''}
                            provider={embedFullscreenData.decodedContent?.provider || 'Google'}
                            embedIds={embedFullscreenData.decodedContent?.embed_ids || embedFullscreenData.embedData?.embed_ids}
                            results={getTravelConnectionResults(embedFullscreenData.decodedContent?.results)}
                            status={normalizeEmbedStatus(embedFullscreenData.embedData?.status ?? embedFullscreenData.decodedContent?.status)}
                            errorMessage={typeof embedFullscreenData.decodedContent?.error === 'string' ? embedFullscreenData.decodedContent.error : ''}
                            embedId={embedFullscreenData.embedId}
                            onClose={handleCloseEmbedFullscreen}
                            {hasPreviousEmbed}
                            {hasNextEmbed}
                            onNavigatePrevious={handleNavigatePreviousEmbed}
                            onNavigateNext={handleNavigateNextEmbed}
                            showChatButton={showChatButtonInFullscreen}
                            onShowChat={handleShowChat}
                        />
                    {:else if appId === 'travel' && skillId === 'price_calendar'}
                        <!-- Travel Price Calendar Fullscreen -->
                        <TravelPriceCalendarEmbedFullscreen
                            query={embedFullscreenData.decodedContent?.query || ''}
                            results={Array.isArray(embedFullscreenData.decodedContent?.results) ? embedFullscreenData.decodedContent.results : []}
                            status={normalizeEmbedStatus(embedFullscreenData.embedData?.status ?? embedFullscreenData.decodedContent?.status)}
                            errorMessage={typeof embedFullscreenData.decodedContent?.error === 'string' ? embedFullscreenData.decodedContent.error : ''}
                            embedId={embedFullscreenData.embedId}
                            onClose={handleCloseEmbedFullscreen}
                            {hasPreviousEmbed}
                            {hasNextEmbed}
                            onNavigatePrevious={handleNavigatePreviousEmbed}
                            onNavigateNext={handleNavigateNextEmbed}
                            showChatButton={showChatButtonInFullscreen}
                            onShowChat={handleShowChat}
                        />
                    {:else if appId === 'travel' && skillId === 'search_stays'}
                        <!-- Travel Search Stays Fullscreen -->
                        <TravelStaysEmbedFullscreen
                            query={embedFullscreenData.decodedContent?.query || ''}
                            provider={embedFullscreenData.decodedContent?.provider || 'Google'}
                            embedIds={embedFullscreenData.decodedContent?.embed_ids || embedFullscreenData.embedData?.embed_ids}
                            results={Array.isArray(embedFullscreenData.decodedContent?.results) ? embedFullscreenData.decodedContent.results as unknown[] : []}
                            status={normalizeEmbedStatus(embedFullscreenData.embedData?.status ?? embedFullscreenData.decodedContent?.status)}
                            errorMessage={typeof embedFullscreenData.decodedContent?.error === 'string' ? embedFullscreenData.decodedContent.error : ''}
                            embedId={embedFullscreenData.embedId}
                            onClose={handleCloseEmbedFullscreen}
                            {hasPreviousEmbed}
                            {hasNextEmbed}
                            onNavigatePrevious={handleNavigatePreviousEmbed}
                            onNavigateNext={handleNavigateNextEmbed}
                            showChatButton={showChatButtonInFullscreen}
                            onShowChat={handleShowChat}
                        />
                    {:else if appId === 'videos' && skillId === 'get_transcript'}
                        <!-- Video Transcript Fullscreen -->
                        {@const previewData: VideoTranscriptSkillPreviewData = {
                            app_id: 'videos',
                            skill_id: 'get_transcript',
                            status: (embedFullscreenData.embedData?.status || 'finished') as VideoTranscriptSkillPreviewData['status'],
                            results: getVideoTranscriptResults(embedFullscreenData.decodedContent?.results),
                            video_count: embedFullscreenData.decodedContent?.video_count || 0,
                            success_count: embedFullscreenData.decodedContent?.success_count || 0,
                            failed_count: embedFullscreenData.decodedContent?.failed_count || 0
                        }}
                        {@const debugRender = (() => {
                            console.debug('[ActiveChat] Rendering VideoTranscriptEmbedFullscreen:', {
                                appId,
                                skillId,
                                hasPreviewData: !!previewData,
                                resultsCount: previewData.results?.length || 0
                            });
                            return null;
                        })()}
                        {debugRender}
                        <VideoTranscriptEmbedFullscreen 
                            previewData={previewData}
                            embedId={embedFullscreenData.embedId}
                            onClose={handleCloseEmbedFullscreen}
                            {hasPreviousEmbed}
                            {hasNextEmbed}
                            onNavigatePrevious={handleNavigatePreviousEmbed}
                            onNavigateNext={handleNavigateNextEmbed}
                            showChatButton={showChatButtonInFullscreen}
                            onShowChat={handleShowChat}
                        />
                    {:else if appId === 'web' && skillId === 'read'}
                        <!-- Web Read Fullscreen -->
                        <!-- Pass URL from decoded content (from processing placeholder or original_metadata) -->
                        {@const webReadResults = getWebReadResults(embedFullscreenData.decodedContent?.results)}
                        {@const webReadUrl = embedFullscreenData.decodedContent?.url || 
                            embedFullscreenData.decodedContent?.original_metadata?.url || 
                            webReadResults?.[0]?.url || ''}
                        {@const previewData: WebReadPreviewData = {
                            app_id: 'web',
                            skill_id: 'read',
                            status: (embedFullscreenData.embedData?.status || 'finished') as WebReadPreviewData['status'],
                            results: webReadResults,
                            url: webReadUrl
                        }}
                        <WebReadEmbedFullscreen 
                            previewData={previewData}
                            url={webReadUrl}
                            embedId={embedFullscreenData.embedId}
                            onClose={handleCloseEmbedFullscreen}
                            {hasPreviousEmbed}
                            {hasNextEmbed}
                            onNavigatePrevious={handleNavigatePreviousEmbed}
                            onNavigateNext={handleNavigateNextEmbed}
                            showChatButton={showChatButtonInFullscreen}
                            onShowChat={handleShowChat}
                        />
                    {:else if appId === 'code' && skillId === 'get_docs'}
                        <!-- Code Get Docs Fullscreen -->
                        {@const CodeGetDocsEmbedFullscreenPromise = import('./embeds/code/CodeGetDocsEmbedFullscreen.svelte')}
                        {#await CodeGetDocsEmbedFullscreenPromise then module}
                            {@const CodeGetDocsEmbedFullscreen = module.default}
                            {@const previewData: CodeGetDocsSkillPreviewData = {
                                app_id: 'code',
                                skill_id: 'get_docs',
                                status: (embedFullscreenData.embedData?.status || 'finished') as CodeGetDocsSkillPreviewData['status'],
                                results: getCodeDocsResults(embedFullscreenData.decodedContent?.results),
                                library: embedFullscreenData.decodedContent?.library || ''
                            }}
                            {@const debugRender = (() => {
                                console.debug('[ActiveChat] Rendering CodeGetDocsEmbedFullscreen:', {
                                    appId,
                                    skillId,
                                    hasPreviewData: !!previewData,
                                    resultsCount: previewData.results?.length || 0,
                                    library: previewData.library
                                });
                                return null;
                            })()}
                            {debugRender}
                            <CodeGetDocsEmbedFullscreen 
                                previewData={previewData}
                                results={embedFullscreenData.decodedContent?.results || []}
                                library={embedFullscreenData.decodedContent?.library || ''}
                                embedId={embedFullscreenData.embedId}
                                onClose={handleCloseEmbedFullscreen}
                                {hasPreviousEmbed}
                                {hasNextEmbed}
                                onNavigatePrevious={handleNavigatePreviousEmbed}
                                onNavigateNext={handleNavigateNextEmbed}
                                showChatButton={showChatButtonInFullscreen}
                                onShowChat={handleShowChat}
                            />
                        {/await}
                    {:else if appId === 'reminder' && skillId === 'set-reminder'}
                        <!-- Reminder Set Fullscreen -->
                        {@const reminderId = coerceString(embedFullscreenData.decodedContent?.reminder_id ?? embedFullscreenData.attrs?.reminderId, '')}
                        {@const triggerAtFormatted = coerceString(embedFullscreenData.decodedContent?.trigger_at_formatted ?? embedFullscreenData.attrs?.triggerAtFormatted, '')}
                        {@const triggerAt = coerceNumber(embedFullscreenData.decodedContent?.trigger_at ?? embedFullscreenData.attrs?.triggerAt, 0)}
                        {@const targetType = (embedFullscreenData.decodedContent?.target_type ?? embedFullscreenData.attrs?.targetType) as 'new_chat' | 'existing_chat' | undefined}
                        {@const isRepeating = Boolean(embedFullscreenData.decodedContent?.is_repeating ?? embedFullscreenData.attrs?.isRepeating)}
                        {@const message = coerceString(embedFullscreenData.decodedContent?.message ?? embedFullscreenData.attrs?.message, '')}
                        {@const emailNotificationWarning = coerceString(embedFullscreenData.decodedContent?.email_notification_warning ?? embedFullscreenData.attrs?.emailNotificationWarning, '')}
                        {@const error = coerceString(embedFullscreenData.decodedContent?.error ?? embedFullscreenData.attrs?.error, '')}
                        <ReminderEmbedFullscreen 
                            reminderId={reminderId || undefined}
                            triggerAtFormatted={triggerAtFormatted || undefined}
                            triggerAt={triggerAt || undefined}
                            targetType={targetType}
                            {isRepeating}
                            message={message || undefined}
                            emailNotificationWarning={emailNotificationWarning || undefined}
                            error={error || undefined}
                            embedId={embedFullscreenData.embedId}
                            onClose={handleCloseEmbedFullscreen}
                            {hasPreviousEmbed}
                            {hasNextEmbed}
                            onNavigatePrevious={handleNavigatePreviousEmbed}
                            onNavigateNext={handleNavigateNextEmbed}
                            showChatButton={showChatButtonInFullscreen}
                            onShowChat={handleShowChat}
                        />
                    {:else if appId === 'images' && (skillId === 'generate' || skillId === 'generate_draft')}
                        <!-- Image Generate Fullscreen -->
                        {@const imgContent = (embedFullscreenData.decodedContent || {}) as Record<string, unknown>}
                        <ImageGenerateEmbedFullscreen
                            prompt={String(imgContent.prompt || '')}
                            model={String(imgContent.model || '')}
                            aspectRatio={String(imgContent.aspect_ratio || '')}
                            s3BaseUrl={String(imgContent.s3_base_url || '')}
                            files={imgContent.files as { preview?: { s3_key: string; width: number; height: number; format: string }; full?: { s3_key: string; width: number; height: number; format: string }; original?: { s3_key: string; width: number; height: number; format: string } } | undefined}
                            aesKey={String(imgContent.aes_key || '')}
                            aesNonce={String(imgContent.aes_nonce || '')}
                            status={embedFullscreenData.embedData?.status || 'finished'}
                            error={String(imgContent.error || '')}
                            onClose={handleCloseEmbedFullscreen}
                            embedId={embedFullscreenData.embedId}
                            skillId={skillId === 'generate_draft' ? 'generate_draft' : 'generate'}
                            generatedAt={imgContent.generated_at ? String(imgContent.generated_at) : undefined}
                            {hasPreviousEmbed}
                            {hasNextEmbed}
                            onNavigatePrevious={handleNavigatePreviousEmbed}
                            onNavigateNext={handleNavigateNextEmbed}
                            showChatButton={showChatButtonInFullscreen}
                            onShowChat={handleShowChat}
                        />
                    {:else}
                        <!-- Generic app skill fullscreen (fallback) -->
                        <div class="embed-fullscreen-fallback">
                            <div class="fullscreen-header">
                                <button onclick={handleCloseEmbedFullscreen}>Close</button>
                            </div>
                            <div class="fullscreen-content">
                                <pre>{JSON.stringify(embedFullscreenData.decodedContent, null, 2)}</pre>
                            </div>
                        </div>
                    {/if}
                {:else if embedFullscreenData.embedType === 'website'}
                    <!-- Website Fullscreen -->
                    {#if embedFullscreenData.decodedContent?.url || embedFullscreenData.attrs?.url}
                        <WebsiteEmbedFullscreen 
                            url={embedFullscreenData.decodedContent?.url || embedFullscreenData.attrs?.url || ''}
                            title={embedFullscreenData.decodedContent?.title || embedFullscreenData.attrs?.title}
                            description={embedFullscreenData.decodedContent?.description || embedFullscreenData.attrs?.description}
                            favicon={embedFullscreenData.decodedContent?.meta_url_favicon || embedFullscreenData.decodedContent?.favicon || embedFullscreenData.attrs?.favicon}
                            image={embedFullscreenData.decodedContent?.thumbnail_original || embedFullscreenData.decodedContent?.image || embedFullscreenData.attrs?.image}
                            extra_snippets={embedFullscreenData.decodedContent?.extra_snippets}
                            meta_url_favicon={embedFullscreenData.decodedContent?.meta_url_favicon}
                            thumbnail_original={embedFullscreenData.decodedContent?.thumbnail_original}
                            dataDate={embedFullscreenData.decodedContent?.page_age}
                            embedId={embedFullscreenData.embedId}
                            onClose={handleCloseEmbedFullscreen}
                            {hasPreviousEmbed}
                            {hasNextEmbed}
                            onNavigatePrevious={handleNavigatePreviousEmbed}
                            onNavigateNext={handleNavigateNextEmbed}
                            showChatButton={showChatButtonInFullscreen}
                            onShowChat={handleShowChat}
                        />
                    {/if}
                {:else if embedFullscreenData.embedType === 'code-code'}
                    <!-- Code Fullscreen -->
                    {#if embedFullscreenData.decodedContent?.code || embedFullscreenData.attrs?.code}
                        {@const codeContent = coerceString(embedFullscreenData.decodedContent?.code ?? embedFullscreenData.attrs?.code, '')}
                        {@const codeLanguage = coerceString(embedFullscreenData.decodedContent?.language ?? embedFullscreenData.attrs?.language, '')}
                        {@const codeFilename = coerceString(embedFullscreenData.decodedContent?.filename ?? embedFullscreenData.attrs?.filename, '')}
                        {@const codeLineCount = coerceNumber(embedFullscreenData.decodedContent?.lineCount ?? embedFullscreenData.attrs?.lineCount, 0)}
                        <CodeEmbedFullscreen 
                             codeContent={codeContent}
                             language={codeLanguage}
                             filename={codeFilename}
                             lineCount={codeLineCount}
                             embedId={embedFullscreenData.embedId}
                             onClose={handleCloseEmbedFullscreen}
                             {hasPreviousEmbed}
                             {hasNextEmbed}
                             onNavigatePrevious={handleNavigatePreviousEmbed}
                             onNavigateNext={handleNavigateNextEmbed}
                             showChatButton={showChatButtonInFullscreen}
                             onShowChat={handleShowChat}
                             piiMappings={cumulativePIIMappingsArray}
                             piiRevealed={piiRevealed}
                         />
                    {/if}
                {:else if embedFullscreenData.embedType === 'docs-doc'}
                    <!-- Document Fullscreen -->
                    {#if embedFullscreenData.decodedContent?.html || embedFullscreenData.attrs?.code}
                        {@const htmlContent = coerceString(embedFullscreenData.decodedContent?.html ?? embedFullscreenData.attrs?.code, '')}
                        {@const docTitle = coerceString(embedFullscreenData.decodedContent?.title ?? embedFullscreenData.attrs?.title, '')}
                        {@const docWordCount = coerceNumber(embedFullscreenData.decodedContent?.word_count ?? embedFullscreenData.attrs?.wordCount, 0)}
                        <DocsEmbedFullscreen 
                             htmlContent={htmlContent}
                             title={docTitle}
                             wordCount={docWordCount}
                             embedId={embedFullscreenData.embedId}
                             onClose={handleCloseEmbedFullscreen}
                             {hasPreviousEmbed}
                             {hasNextEmbed}
                             onNavigatePrevious={handleNavigatePreviousEmbed}
                             onNavigateNext={handleNavigateNextEmbed}
                             showChatButton={showChatButtonInFullscreen}
                             onShowChat={handleShowChat}
                             piiMappings={cumulativePIIMappingsArray}
                             piiRevealed={piiRevealed}
                         />
                    {/if}
                {:else if embedFullscreenData.embedType === 'sheets-sheet'}
                    <!-- Sheet/Table Fullscreen -->
                    <!-- TOON content uses: table (markdown), title, row_count, col_count -->
                    <!-- Fallback to legacy fields (code, rows, cols) for backward compatibility -->
                    {#if embedFullscreenData.decodedContent?.table || embedFullscreenData.decodedContent?.code || embedFullscreenData.attrs?.code}
                        {@const sheetContent = coerceString(embedFullscreenData.decodedContent?.table ?? embedFullscreenData.decodedContent?.code ?? embedFullscreenData.attrs?.code, '')}
                        {@const sheetTitle = coerceString(embedFullscreenData.decodedContent?.title ?? embedFullscreenData.attrs?.title, '')}
                        {@const sheetRows = coerceNumber(embedFullscreenData.decodedContent?.row_count ?? embedFullscreenData.decodedContent?.rows ?? embedFullscreenData.attrs?.rows, 0)}
                        {@const sheetCols = coerceNumber(embedFullscreenData.decodedContent?.col_count ?? embedFullscreenData.decodedContent?.cols ?? embedFullscreenData.attrs?.cols, 0)}
                        <SheetEmbedFullscreen 
                             tableContent={sheetContent}
                             title={sheetTitle}
                             rowCount={sheetRows}
                             colCount={sheetCols}
                             embedId={embedFullscreenData.embedId}
                             onClose={handleCloseEmbedFullscreen}
                             {hasPreviousEmbed}
                             {hasNextEmbed}
                             onNavigatePrevious={handleNavigatePreviousEmbed}
                             onNavigateNext={handleNavigateNextEmbed}
                             showChatButton={showChatButtonInFullscreen}
                             onShowChat={handleShowChat}
                             piiMappings={cumulativePIIMappingsArray}
                             piiRevealed={piiRevealed}
                        />
                    {/if}
                {:else if embedFullscreenData.embedType === 'videos-video'}
                    <!-- Video Fullscreen -->
                    <!-- Constructs VideoMetadata from decodedContent (backend TOON format: snake_case) -->
                    <!-- This ensures all video details (channel, duration, thumbnail, etc.) display in fullscreen -->
                    {#if embedFullscreenData.decodedContent?.url || embedFullscreenData.attrs?.url}
                        {@const VideoEmbedFullscreenPromise = import('../components/embeds/videos/VideoEmbedFullscreen.svelte')}
                        {#await VideoEmbedFullscreenPromise then module}
                            {@const VideoEmbedFullscreen = module.default}
                            {@const videoUrl = coerceString(embedFullscreenData.decodedContent?.url ?? embedFullscreenData.attrs?.url, '')}
                            {@const videoTitle = coerceString(embedFullscreenData.decodedContent?.title ?? embedFullscreenData.attrs?.title, '')}
                            {@const videoId = coerceString(
                                embedFullscreenData.decodedContent?.video_id ??
                                embedFullscreenData.decodedContent?.videoId ??
                                embedFullscreenData.attrs?.videoId,
                                ''
                            )}
                            {@const restoreFromPip = embedFullscreenData.restoreFromPip || false}
                            <!-- Construct VideoMetadata from decoded content (snake_case -> camelCase) -->
                            {@const videoMetadata = {
                                videoId,
                                title: videoTitle,
                                description: coerceString(embedFullscreenData.decodedContent?.description, ''),
                                channelName: coerceString(embedFullscreenData.decodedContent?.channel_name, ''),
                                channelId: coerceString(embedFullscreenData.decodedContent?.channel_id, ''),
                                thumbnailUrl: coerceString(embedFullscreenData.decodedContent?.thumbnail, ''),
                                duration: (embedFullscreenData.decodedContent?.duration_seconds || embedFullscreenData.decodedContent?.duration_formatted) ? {
                                    totalSeconds: coerceNumber(embedFullscreenData.decodedContent?.duration_seconds, 0),
                                    formatted: coerceString(embedFullscreenData.decodedContent?.duration_formatted, '')
                                } : undefined,
                                viewCount: coerceNumber(embedFullscreenData.decodedContent?.view_count, 0),
                                likeCount: coerceNumber(embedFullscreenData.decodedContent?.like_count, 0),
                                publishedAt: coerceString(embedFullscreenData.decodedContent?.published_at, '')
                            }}
                            <VideoEmbedFullscreen
                                url={videoUrl}
                                title={videoTitle}
                                videoId={videoId}
                                embedId={embedFullscreenData.embedId}
                                restoreFromPip={restoreFromPip}
                                onClose={handleCloseEmbedFullscreen}
                                {hasPreviousEmbed}
                                {hasNextEmbed}
                                onNavigatePrevious={handleNavigatePreviousEmbed}
                                onNavigateNext={handleNavigateNextEmbed}
                                showChatButton={showChatButtonInFullscreen}
                                onShowChat={handleShowChat}
                                metadata={videoMetadata}
                            />
                        {/await}
                    {/if}
                {:else}
                    <!-- Fallback for unknown embed types -->
                    <div class="embed-fullscreen-fallback">
                        <div class="fullscreen-header">
                            <button onclick={handleCloseEmbedFullscreen}>Close</button>
                        </div>
                        <div class="fullscreen-content">
                            <p>Fullscreen view not available for embed type: {embedFullscreenData.embedType}</p>
                        </div>
                    </div>
                {/if}
                {/key}
                </div>
            {/if}
            
            <!-- 
                Standalone VideoIframe component - CSS-based PiP
                
                This component is ALWAYS rendered in the same DOM position within ActiveChat.
                PiP mode is achieved purely through CSS class changes (no DOM movement).
                The iframe is never destroyed or reloaded during PiP transitions.
                
                The wrapper container provides:
                - Fullscreen mode: positioned at top, centered (via .video-iframe-fullscreen-container)
                - PiP mode: absolute position top-right within ActiveChat (via .pip-mode class)
                - Fade-out: opacity transition when closing (via .fade-out class)
                
                Using position: absolute (not fixed) ensures the PiP moves with ActiveChat
                when the settings panel opens/closes.
            -->
            {#if (videoIframeState.isActive || videoIframeState.isClosing) && videoIframeState.videoId && videoIframeState.embedUrl}
                {@const VideoIframePromise = import('../components/embeds/videos/VideoIframe.svelte')}
                {#await VideoIframePromise then module}
                    {@const VideoIframe = module.default}
                    <div 
                        class="video-iframe-fullscreen-container" 
                        class:pip-mode={videoIframeState.isPipMode}
                        class:fade-out={videoIframeState.isClosing}
                    >
                        <VideoIframe
                            videoId={videoIframeState.videoId}
                            title={videoIframeState.title || 'Video'}
                            embedUrl={videoIframeState.embedUrl}
                            isPipMode={videoIframeState.isPipMode}
                            onPipOverlayClick={handlePipOverlayClick}
                        />
                    </div>
                {/await}
            {/if}
            
            <KeyboardShortcuts
                on:newChat={handleNewChatClick}
                on:focusInput={() => messageInputFieldRef.focus()}
                on:scrollToTop={() => chatHistoryRef.scrollToTop()}
                on:scrollToBottom={() => chatHistoryRef.scrollToBottom()}
            />
        </div>
    {/if}
</div>

<!-- Focus mode context menu (body-appended, shown on right-click/long-press on focus mode embeds) -->
<FocusModeContextMenu
    x={focusModeContextMenuX}
    y={focusModeContextMenuY}
    show={showFocusModeContextMenu}
    isActivated={focusModeContextMenuIsActivated}
    focusModeName={focusModeContextMenuFocusModeName}
    onClose={() => { showFocusModeContextMenu = false; }}
    onCancelOrStop={() => {
        showFocusModeContextMenu = false;
        if (focusModeContextMenuIsActivated) {
            // Already activated — dispatch deactivation event (same as "Stop Focus Mode")
            document.dispatchEvent(new CustomEvent('focusModeDeactivated', {
                bubbles: true,
                detail: { focusId: focusModeContextMenuFocusId, appId: focusModeContextMenuAppId },
            }));
            // Add "Stopped X focus mode." persisted system message
            handleFocusModeSystemMessage(focusModeContextMenuFocusId, focusModeContextMenuFocusModeName, 'stopped');
        } else {
            // Still in countdown — dispatch rejection event (same as clicking to cancel)
            document.dispatchEvent(new CustomEvent('focusModeRejected', {
                bubbles: true,
                detail: { focusId: focusModeContextMenuFocusId, focusModeName: focusModeContextMenuFocusModeName, appId: focusModeContextMenuAppId },
            }));
        }
    }}
    onDetails={() => {
        showFocusModeContextMenu = false;
        handleFocusModeDetailsNavigation(focusModeContextMenuFocusId, focusModeContextMenuAppId);
    }}
/>

<style>
    /* 
     * Responsive design: Uses JavaScript-based width detection for true container-based responsiveness.
     * Container width is bound to a reactive variable, and classes are applied dynamically.
     * This approach works reliably across all browsers and adapts to actual available space.
     * 
     * Breakpoints:
     * - narrow: 0-730px
     * - medium: 731-1099px
     * - wide: 1100-1700px
     * - extra-wide: 1701px+
     */
    .active-chat-container {
        background-color: var(--color-grey-20);
        border-radius: 17px;
        flex-grow: 1;
        position: relative;
        min-height: 0;
        height: 100%;
        box-shadow: 0 0 12px rgba(0, 0, 0, 0.25);
        transition: opacity 0.3s ease;
        overflow: hidden;
        box-sizing: border-box;
    }

    /* Responsive adjustments for narrow and medium containers */
    .active-chat-container.narrow,
    .active-chat-container.medium {
        margin-right: 0;
    }

    .active-chat-container.login-mode {
        background-color: var(--color-grey-20);
    }

    /* On mobile during login/signup, extend container to bottom and remove bottom border-radius */
    /* @media (max-width: 600px) { */
    /*         .active-chat-container.login-mode { */
    /*             border-bottom-left-radius: 0; */
    /*             border-bottom-right-radius: 0; */
    /*             /* Ensure it extends to the bottom of the viewport */
    /*             min-height: 100vh; */
    /*             min-height: 100dvh; */
    /*         } */
    /*     } */

    .content-container {
        display: flex;
        flex-direction: column;
        height: 100%;
        position: relative;
    }
    
    /* ===========================================
       Side-by-Side Layout for Wide Screens (>=1024px)
       Shows embed fullscreen next to chat instead of overlay
       Threshold set for iPad landscape (1024px+) and wider displays
       =========================================== */
    
    /* When side-by-side mode is active, content-container uses row layout */
    .content-container.side-by-side {
        flex-direction: row;
        gap: 10px; /* Gap between chat card and fullscreen card */
    }
    
    /* ===========================================
       Chat Wrapper Animations for Side-by-Side Mode
       =========================================== */
    
    /* Chat wrapper base styles for side-by-side mode */
    /* When side-by-side is active, chat shrinks to 400px to make room for fullscreen panel */
    .chat-wrapper.side-by-side-chat {
        flex: 0 0 400px;
        max-width: 400px;
        min-width: 400px; /* Fixed width for consistent layout */
        position: relative;
        /* Rounded edges to look like a separate card (chat remains in main container) */
        border-radius: 17px;
        overflow: hidden;
        /* Ensure background is always visible during animation */
        background-color: var(--color-grey-20);
        box-shadow: 0 0 12px rgba(0, 0, 0, 0.25);
    }
    
    /* ENTER: Opening fullscreen - chat shrinks from full-width to 400px */
    .chat-wrapper.side-by-side-entering {
        animation: chatShrink 0.4s cubic-bezier(0.4, 0, 0.2, 1) forwards;
    }
    
    /* EXIT: Closing fullscreen - chat expands from 400px back to full-width */
    .chat-wrapper.side-by-side-exiting {
        animation: chatExpand 0.4s cubic-bezier(0.4, 0, 0.2, 1) forwards;
    }
    
    /* MINIMIZE: Hide chat - chat shrinks from 400px to 0 and fades out */
    .chat-wrapper.side-by-side-minimizing {
        animation: chatMinimize 0.4s cubic-bezier(0.4, 0, 0.2, 1) forwards;
    }
    
    /* RESTORE: Show chat - chat grows from 0 to 400px and fades in */
    .chat-wrapper.side-by-side-restoring {
        animation: chatRestore 0.4s cubic-bezier(0.4, 0, 0.2, 1) forwards;
    }
    
    @keyframes chatShrink {
        from {
            flex: 1 1 100%;
            max-width: 100%;
            min-width: 0;
            border-radius: 0;
            box-shadow: none;
        }
        to {
            flex: 0 0 400px;
            max-width: 400px;
            min-width: 400px;
            border-radius: 17px;
            box-shadow: 0 0 12px rgba(0, 0, 0, 0.25);
        }
    }
    
    @keyframes chatExpand {
        from {
            flex: 0 0 400px;
            max-width: 400px;
            min-width: 400px;
            border-radius: 17px;
            box-shadow: 0 0 12px rgba(0, 0, 0, 0.25);
        }
        to {
            flex: 1 1 100%;
            max-width: 100%;
            min-width: 0;
            border-radius: 0;
            box-shadow: none;
        }
    }
    
    @keyframes chatMinimize {
        from {
            flex: 0 0 400px;
            max-width: 400px;
            min-width: 400px;
            opacity: 1;
        }
        to {
            flex: 0 0 0px;
            max-width: 0px;
            min-width: 0px;
            opacity: 0;
        }
    }
    
    @keyframes chatRestore {
        from {
            flex: 0 0 0px;
            max-width: 0px;
            min-width: 0px;
            opacity: 0;
        }
        to {
            flex: 0 0 400px;
            max-width: 400px;
            min-width: 400px;
            opacity: 1;
        }
    }
    
    /* Top buttons layout in side-by-side mode */
    /* Keep buttons at normal left position, span full width for space-between to work */
    .chat-wrapper.side-by-side-chat .top-buttons {
        top: 10px;
        left: 10px;
        right: 10px; /* Span full width so space-between distributes left/right buttons properly */
    }
    
    .chat-wrapper.side-by-side-chat .message-input-container {
        padding: 10px;
    }
    
    .chat-wrapper.side-by-side-chat .typing-indicator {
        font-size: 0.75rem;
    }
    
    .chat-wrapper.side-by-side-chat .center-content {
        top: 30%;
    }
    
    /* ===========================================
       Fullscreen Panel Animations
       =========================================== */
    
    /* Fullscreen embed container - handles both overlay and side panel modes */
    .fullscreen-embed-container {
        position: relative;
        height: 100%;
    }
    
    /* Overlay mode (default): Absolute positioning over everything */
    .fullscreen-embed-container.overlay-mode {
        position: absolute;
        top: 0;
        left: 0;
        right: 0;
        bottom: 0;
        z-index: 100;
    }
    
    /* Side panel mode: Flex child taking remaining space - styled as separate card */
    .fullscreen-embed-container.side-panel {
        flex: 1;
        min-width: 0;
        position: relative;
        z-index: 1;
        /* Card styling - matches active-chat-container design */
        background-color: var(--color-grey-20);
        border-radius: 17px;
        box-shadow: 0 0 12px rgba(0, 0, 0, 0.25);
        overflow: hidden;
    }
    
    /* ENTER: Panel reveals from left edge (grows leftward as chat shrinks) */
    .fullscreen-embed-container.side-panel.side-by-side-entering {
        animation: panelReveal 0.4s cubic-bezier(0.4, 0, 0.2, 1) forwards;
    }
    
    /* EXIT: Panel hides to left edge (shrinks rightward as chat expands) */
    .fullscreen-embed-container.side-panel.side-by-side-exiting {
        animation: panelHide 0.4s cubic-bezier(0.4, 0, 0.2, 1) forwards;
    }
    
    /* MINIMIZE: Panel expands to full width (chat is hidden) */
    .fullscreen-embed-container.side-panel.side-by-side-minimizing {
        animation: panelExpandFull 0.4s cubic-bezier(0.4, 0, 0.2, 1) forwards;
    }
    
    /* RESTORE: Panel shrinks back to partial width (chat is shown) */
    .fullscreen-embed-container.side-panel.side-by-side-restoring {
        animation: panelShrinkPartial 0.4s cubic-bezier(0.4, 0, 0.2, 1) forwards;
    }
    
    @keyframes panelReveal {
        from {
            clip-path: inset(0 0 0 100%);
            opacity: 0;
        }
        to {
            clip-path: inset(0 0 0 0);
            opacity: 1;
        }
    }
    
    @keyframes panelHide {
        from {
            clip-path: inset(0 0 0 0);
            opacity: 1;
        }
        to {
            clip-path: inset(0 0 0 100%);
            opacity: 0;
        }
    }
    
    @keyframes panelExpandFull {
        from {
            /* Panel already at flex: 1 */
        }
        to {
            /* Panel stays at flex: 1, just gets more space as chat disappears */
        }
    }
    
    @keyframes panelShrinkPartial {
        from {
            /* Panel at full width */
        }
        to {
            /* Panel returns to partial width */
        }
    }
    
    /* Override UnifiedEmbedFullscreen overlay styles when in side panel mode */
    /* The :global is needed because the overlay class is in the child component */
    .fullscreen-embed-container.side-panel :global(.unified-embed-fullscreen-overlay) {
        position: relative;
        top: auto;
        left: auto;
        right: auto;
        bottom: auto;
        height: 100%;
        /* Remove margin since we want it to fill the card container */
        margin: 0;
        /* Border radius handled by parent container */
        border-radius: 0;
        /* Remove shadow since parent has it */
        box-shadow: none;
        transform: none !important; /* Override animation transforms */
        opacity: 1 !important;
        /* Remove the opening animation since we have slide-in on container */
    }
    
    /* In side-panel mode, the fullscreen should use all available space */
    .fullscreen-embed-container.side-panel :global(.unified-embed-fullscreen-overlay.animating-in) {
        transform: none !important;
    }
    
    /* Active chat container adjustments when side-by-side is active */
    /* The container itself becomes the outer wrapper, chat + fullscreen are cards inside */
    .active-chat-container.side-by-side-active {
        background-color: var(--color-grey-0); /* Lighter background to show separation */
        box-shadow: none; /* Remove shadow since child cards have shadows */
        padding: 10px; /* Add padding to show gap around cards */
    }
    
    /* Ensure content-container fills the padded area */
    .active-chat-container.side-by-side-active .content-container {
        height: 100%;
    }
    
    /* Chat wrapper in side-by-side mode - background/shadow now in base .side-by-side-chat class */
    /* to ensure visibility during animation */

    .center-content {
        position: absolute;
        top: 40%;
        left: 50%;
        transform: translate(-50%, -50%);
        text-align: center;
        /* Render above ChatHistory (which is also position:absolute and comes after in DOM) */
        z-index: 1;
        /* Allow clicks to pass through the non-interactive parts to ChatHistory underneath,
           but re-enable pointer-events on interactive children (resume card button) */
        pointer-events: none;
        display: flex;
        flex-direction: column;
        align-items: center;
    }

    /* Adjust welcome content position for narrow containers */
    .active-chat-container.narrow .center-content {
        top: 30%;
    }

    .team-profile {
        display: flex;
        flex-direction: column;
        align-items: center;
        gap: 20px;
    }


    .welcome-text h2 {
        margin: 0;
        color: var(--color-grey-80);
        font-size: 24px;
        font-weight: 600;
    }

    .welcome-text p {
        margin: 8px 0 0;
        color: var(--color-grey-60);
        font-size: 16px;
    }

    .message-input-wrapper {
        position: relative; /* For absolute positioning of typing indicator if needed */
    }

    .typing-indicator {
        display: flex;
        flex-direction: column;
        align-items: center;
        gap: 2px;
        text-align: center;
        font-size: 0.8rem;
        color: var(--color-grey-60);
        padding: 6px 12px 4px;
        font-style: italic;
        /* Gradient background so the text remains readable when positioned over chat messages.
           Uses the page background color (--color-grey-0) fading from transparent at the top. */
        background: linear-gradient(
            to bottom,
            transparent 0%,
            var(--color-grey-0, #fff) 40%
        );
        position: relative;
        z-index: 1;
    }
    
    /* Primary line: "{mate} is typing..." — prominent */
    .typing-indicator .indicator-primary-line {
        font-size: 0.8rem;
    }
    
    /* Secondary line: "Powered by {model}" — smaller, subtler */
    .typing-indicator .indicator-secondary-line {
        font-size: 0.7rem;
        opacity: 0.8;
    }
    
    /* Tertiary line: "via {provider} {flag}" — smallest, most subtle */
    .typing-indicator .indicator-tertiary-line {
        font-size: 0.65rem;
        opacity: 0.65;
    }
    
    /* Shimmer animation for the bottom typing indicator during streaming */
    .typing-indicator.status-processing,
    .typing-indicator.status-typing {
        color: var(--color-grey-50);
    }
    
    /* Apply shimmer to the text spans inside the typing indicator */
    .typing-indicator.status-typing span,
    .typing-indicator.status-processing span {
        background: linear-gradient(
            90deg,
            var(--color-grey-60) 0%,
            var(--color-grey-60) 40%,
            var(--color-grey-40) 50%,
            var(--color-grey-60) 60%,
            var(--color-grey-60) 100%
        );
        background-size: 200% 100%;
        background-clip: text;
        -webkit-background-clip: text;
        color: transparent;
        animation: typing-indicator-shimmer 1.5s infinite linear;
    }
    
    @keyframes typing-indicator-shimmer {
        0% {
            background-position: 200% 0;
        }
        100% {
            background-position: -200% 0;
        }
    }
    
    /* Resume chat card - shown in center-content below welcome greeting */
    .resume-chat-card {
        display: flex;
        align-items: center;
        gap: 12px;
        width: 100%;
        max-width: 400px;
        padding: 12px 16px;
        margin-top: 16px;
        background-color: var(--color-grey-10);
        border: 1px solid var(--color-grey-30);
        border-radius: 12px;
        cursor: pointer;
        transition: all 0.2s ease;
        text-align: left;
        pointer-events: auto; /* Re-enable clicks (parent center-content has pointer-events: none) */
    }

    .resume-chat-card:hover {
        background-color: var(--color-grey-15);
        border-color: var(--color-grey-40);
        transform: translateY(-1px);
        box-shadow: 0 2px 8px rgba(0, 0, 0, 0.08);
    }

    .resume-chat-card:active {
        transform: translateY(0);
        box-shadow: none;
    }

    /* Category gradient circle matching Chat.svelte sidebar design */
    .resume-chat-category-circle {
        width: 28px;
        height: 28px;
        border-radius: 50%;
        display: flex;
        align-items: center;
        justify-content: center;
        box-shadow: 0px 2px 4px rgba(0, 0, 0, 0.1);
        flex-shrink: 0;
    }

    .resume-chat-category-icon {
        width: 16px;
        height: 16px;
        display: flex;
        align-items: center;
        justify-content: center;
    }

    .resume-chat-content {
        flex: 1;
        min-width: 0;
        overflow: hidden;
    }

    .resume-chat-title {
        font-size: 15px;
        font-weight: 500;
        color: var(--color-grey-90);
        white-space: nowrap;
        overflow: hidden;
        text-overflow: ellipsis;
        display: block;
    }

    .resume-chat-arrow {
        display: flex;
        align-items: center;
        justify-content: center;
        flex-shrink: 0;
        opacity: 0.5;
    }

    
    /* Read-only indicator for shared chats */
    .read-only-indicator {
        display: flex;
        flex-direction: column;
        align-items: center;
        justify-content: center;
        padding: 24px 16px;
        margin-bottom: 12px;
        background-color: var(--color-grey-10, #f0f0f0);
        border: 1px solid var(--color-grey-30, #d0d0d0);
        border-radius: 8px;
        text-align: center;
    }
    
    .read-only-icon {
        font-size: 32px;
        margin-bottom: 12px;
        opacity: 0.7;
    }
    
    .read-only-text {
        font-size: 14px;
        color: var(--color-grey-70, #666);
        margin: 0;
        line-height: 1.5;
        max-width: 500px;
    }

    .message-input-container {
        position: relative;
        display: flex;
        flex-direction: column;
        align-items: center;
        padding: 15px;
    }

    .chat-wrapper:not(.fullscreen) .message-input-wrapper { /* Changed from .message-input-container */
        position: absolute;
        bottom: 0;
        left: 0;
        right: 0;
    }
    

    .chat-wrapper.fullscreen .message-input-wrapper { /* Changed from .message-input-container */
        width: 35%;
        min-width: 400px;
        padding: 20px;
        align-items: flex-start;
        display: flex; /* To allow typing indicator above input */
        flex-direction: column;
    }
    
    .chat-wrapper.fullscreen .message-input-container {
         width: 100%; /* Input container takes full width of its wrapper */
    }


    .message-input-container :global(> *) {
        max-width: 629px;
        width: 100%;
    }

    /* Adjust input padding and typing indicator for narrow containers */
    .active-chat-container.narrow .message-input-container {
        padding: 10px;
    }
    
    .active-chat-container.narrow .typing-indicator {
        font-size: 0.75rem;
    }


    .active-chat-container.dimmed {
        opacity: 0.3;
    }

    /* Incognito mode banner - full width, 20px height at top of chat */
    .incognito-banner {
        width: 100%;
        height: 20px;
        background-color: var(--color-grey-30);
        display: flex;
        align-items: center;
        justify-content: center;
        gap: 6px;
        padding: 0 12px;
        flex-shrink: 0;
    }

    .incognito-banner-icon {
        width: 16px;
        height: 16px;
        display: flex;
        align-items: center;
        justify-content: center;
        flex-shrink: 0;
    }

    .incognito-banner-text {
        font-size: 12px;
        font-weight: 500;
        color: var(--color-grey-70);
        white-space: nowrap;
    }

    /* Banner for non-incognito chats when incognito mode is active */
    .incognito-mode-applies-banner {
        width: 100%;
        min-height: 40px;
        background-color: var(--color-grey-15);
        border: 1px solid var(--color-grey-30);
        border-radius: 8px;
        display: flex;
        align-items: center;
        justify-content: flex-start;
        gap: 10px;
        padding: 10px 14px;
        margin-bottom: 12px;
        flex-shrink: 0;
    }

    .incognito-mode-applies-icon {
        width: 20px;
        height: 20px;
        display: flex;
        align-items: center;
        justify-content: center;
        flex-shrink: 0;
        opacity: 0.7;
    }

    .incognito-mode-applies-text {
        font-size: 13px;
        font-weight: 400;
        color: var(--color-grey-70);
        line-height: 1.4;
        flex: 1;
    }

    .chat-wrapper {
        position: relative;
        display: flex;
        flex-direction: column;
        height: 100%;
        transition: all 0.3s ease;
    }

    /* 
     * Fullscreen layout: Side-by-side chat history and input for extra-wide containers.
     * Default: Stacked layout for narrow, medium, and wide containers.
     */
    .active-chat-container.extra-wide .chat-wrapper.fullscreen {
        flex-direction: row;
    }

    .active-chat-container.extra-wide .chat-wrapper.fullscreen .chat-side {
        width: 65%;
        padding-right: 20px;
    }

    .active-chat-container.extra-wide .chat-wrapper.fullscreen .message-input-wrapper {
        width: 35%;
        min-width: 400px;
        padding: 20px;
        align-items: flex-start;
    }

    /* Stacked layout for narrow, medium, and wide containers (default fullscreen behavior) */
    .active-chat-container.narrow .chat-wrapper.fullscreen,
    .active-chat-container.medium .chat-wrapper.fullscreen,
    .active-chat-container.wide .chat-wrapper.fullscreen {
        flex-direction: column;
    }

    .active-chat-container.narrow .chat-wrapper.fullscreen .chat-side,
    .active-chat-container.medium .chat-wrapper.fullscreen .chat-side,
    .active-chat-container.wide .chat-wrapper.fullscreen .chat-side {
        width: 100%;
        padding-right: 0;
    }

    .active-chat-container.narrow .chat-wrapper.fullscreen .message-input-wrapper,
    .active-chat-container.medium .chat-wrapper.fullscreen .message-input-wrapper,
    .active-chat-container.wide .chat-wrapper.fullscreen .message-input-wrapper {
        position: absolute;
        bottom: 0;
        left: 0;
        right: 0;
        width: 100%;
        /* padding for message-input-container is already 15px */
    }

    .chat-side {
        position: relative;
        display: flex;
        flex-direction: column;
        flex: 1;
        min-width: 0;
        height: 100%;
        overflow: hidden;
        container-type: inline-size;
        container-name: chat-side;
    }

    /* Scroll navigation buttons - round, icon-only, subtle grey.
       Overrides global button styles from buttons.css (padding, min-width, height, shadow, etc.) */
    .scroll-nav-button {
        position: absolute;
        left: 50%;
        transform: translateX(-50%);
        z-index: 2;
        width: 32px;
        height: 32px;
        min-width: 32px;
        border-radius: 50%;
        border: none;
        background-color: var(--color-grey-20);
        cursor: pointer;
        display: flex;
        align-items: center;
        justify-content: center;
        opacity: 0.7;
        transition: opacity 0.2s ease;
        padding: 0;
        margin: 0;
        filter: none;
    }

    .scroll-nav-button:hover {
        opacity: 1;
        scale: none;
        background-color: var(--color-grey-20);
    }

    .scroll-nav-button:active {
        scale: none;
        filter: none;
        background-color: var(--color-grey-25);
    }

    .scroll-to-top-button {
        top: 50px;
    }

    .scroll-to-bottom-button {
        bottom: 80px;
    }

    /* Dropdown arrow icon using CSS mask (reuses existing dropdown.svg) */
    .scroll-nav-icon {
        display: block;
        width: 12px;
        height: 12px;
        background-color: var(--color-grey-60);
        -webkit-mask-image: url('@openmates/ui/static/icons/dropdown.svg');
        mask-image: url('@openmates/ui/static/icons/dropdown.svg');
        mask-size: contain;
        mask-position: center;
        mask-repeat: no-repeat;
    }

    /* Rotate the icon 180deg for scroll-to-top (arrow points up) */
    .scroll-nav-icon-up {
        transform: rotate(180deg);
    }

    .top-buttons {
        position: absolute;
        top: 15px;
        left: 15px;
        display: flex;
        justify-content: space-between; /* Distribute space between left and right buttons */
        z-index: 1;
    }

    /* Adjust top-buttons position on small screens */
    @media (max-width: 730px) {
        .top-buttons {
            top: 10px;
            left: 10px;
        }
    }

    /* Add styles for left and right button containers */
    .left-buttons {
        display: flex;
        gap: 10px; /* Space between buttons */
    }

    .right-buttons {
        display: flex;
        gap: 25px; /* Space between buttons */
    }

    /* PII toggle button: subtle orange tint when PII is revealed (warns sensitive data exposed) */
    .pii-toggle-active {
        background-color: rgba(245, 158, 11, 0.3) !important;
    }

    /* Background wrapper for new chat button to ensure it's always visible */
    .new-chat-button-wrapper {
        background-color: var(--color-grey-10);
        border-radius: 40px;
        padding: 8px;
        box-shadow: 0 2px 8px rgba(0, 0, 0, 0.15);
        display: flex;
        align-items: center;
        justify-content: center;
    }

    /* New chat CTA: no extra wrapper background so the pill button stands out */
    .new-chat-cta-wrapper {
        background-color: transparent;
        box-shadow: none;
        padding: 0;
    }

    /* New chat button - same CTA color as Send, fully rounded (pill), white icon and text.
       Override global button styles from buttons.css (min-width, height, padding, filter).
       Height (41px) matches the icon buttons next to it (.new-chat-button-wrapper has 8px padding + 25px icon). */
    .new-chat-cta-button {
        display: inline-flex;
        align-items: center;
        justify-content: center;
        gap: 8px;
        min-width: 0;
        height: 41px;
        padding: 8px 16px;
        border: none;
        border-radius: 9999px;
        background-color: var(--color-button-primary);
        color: white;
        font-weight: 500;
        cursor: pointer;
        transition: background-color 0.15s ease-in-out, transform 0.15s ease-in-out;
        box-shadow: 0 2px 8px rgba(0, 0, 0, 0.15);
        margin-right: 0;
    }

    .new-chat-cta-button:hover {
        background-color: var(--color-button-primary-hover);
        transform: scale(1.02);
    }

    .new-chat-cta-button:active {
        background-color: var(--color-button-primary-pressed);
        transform: scale(0.98);
        box-shadow: none;
    }

    .new-chat-cta-button .new-chat-cta-icon {
        width: 20px;
        height: 20px;
        flex-shrink: 0;
        background: white;
        -webkit-mask-image: url('@openmates/ui/static/icons/create.svg');
        mask-image: url('@openmates/ui/static/icons/create.svg');
        -webkit-mask-size: contain;
        mask-size: contain;
        -webkit-mask-position: center;
        mask-position: center;
        -webkit-mask-repeat: no-repeat;
        mask-repeat: no-repeat;
    }

    /* "New chat" label: visible when chat-side is wide enough */
    .new-chat-cta-label {
        white-space: nowrap;
    }

    /* Mobile layout when chat-side container is narrower than 550px (container query, not viewport) */
    @container chat-side (max-width: 550px) {
        .new-chat-cta-label {
            display: none;
        }

        /* Circle shape: match .new-chat-button-wrapper height (41px) */
        .new-chat-cta-button {
            min-width: 0;
            width: 41px;
            height: 41px;
            padding: 8px;
            box-sizing: border-box;
        }
    }

    .login-wrapper {
        position: absolute; /* Absolute to fill container */
        top: 0;
        left: 0;
        right: 0;
        bottom: 0;
        display: flex;
        flex-direction: column; /* Column layout for Login component */
        align-items: stretch;
        justify-content: stretch;
        height: 100%;
        overflow-y: auto; /* Enable vertical scrolling when content exceeds viewport */
        overflow-x: hidden; /* Prevent horizontal scrolling */
        -webkit-overflow-scrolling: touch; /* Smooth scrolling on iOS */
        max-height: 830px;
    }

    /* Center login-wrapper vertically in active-chat-container on screens with height over 1000px */
    @media (min-height: 1000px) {
        .login-wrapper {
            /* Center the wrapper itself vertically instead of filling from top to bottom */
            top: 50%;
            bottom: auto;
            transform: translateY(-50%); /* Center vertically */
            height: auto; /* Let height be determined by content and max-height */
            justify-content: center; /* Center content vertically inside wrapper */
            overflow-y: visible; /* Allow content to overflow naturally */
            overflow-x: visible;
        }
    }


    /* Add scaling transition for the active-chat-container when a new chat is created */
    .active-chat-container {
        transition: transform 0.2s ease-in-out, opacity 0.3s ease; /* added transform transition */
    }

    .active-chat-container.scaled {
        transform: scale(0.95);
    }
    
    /* ===========================================
       Video Picture-in-Picture (PiP) Styles - CSS-based transitions
       =========================================== */
    
    /*
     * VideoIframe is wrapped in .video-iframe-fullscreen-container
     * This container handles the positioning:
     * - Fullscreen mode: positioned at top-center (matching thumbnail position in fullscreen view)
     * - PiP mode: absolute position top-right of ActiveChat (moves with container)
     *
     * Using position: absolute (not fixed) ensures PiP moves with ActiveChat
     * when settings panel opens/closes.
     */
    
    /* Fullscreen mode container - positioned at top to match thumbnail position */
    .video-iframe-fullscreen-container {
        position: absolute;
        /* Position at top, centered horizontally - matches thumbnail position in fullscreen view */
        top: 80px; /* Below header */
        left: 50%;
        transform: translateX(-50%);
        width: calc(100% - 40px); /* Account for padding */
        max-width: 780px;
        box-sizing: border-box;
        z-index: 100; /* Below fullscreen buttons but above chat content */
        pointer-events: auto;
        
        /* Smooth transition for position changes */
        transition: 
            opacity 0.3s ease-out,
            top 0.5s cubic-bezier(0.4, 0, 0.2, 1),
            left 0.5s cubic-bezier(0.4, 0, 0.2, 1),
            right 0.5s cubic-bezier(0.4, 0, 0.2, 1),
            transform 0.5s cubic-bezier(0.4, 0, 0.2, 1),
            width 0.5s cubic-bezier(0.4, 0, 0.2, 1),
            max-width 0.5s cubic-bezier(0.4, 0, 0.2, 1);
    }
    
    /* Fade out class for cleanup animation */
    .video-iframe-fullscreen-container.fade-out {
        opacity: 0;
        pointer-events: none;
    }
    
    /* PiP mode container - absolute position top-right within ActiveChat */
    .video-iframe-fullscreen-container.pip-mode {
        position: absolute;
        top: 20px;
        left: auto;
        right: 20px;
        transform: none;
        width: 320px;
        max-width: 320px;
        z-index: 1000; /* Above everything in ActiveChat */
    }
    
    /* Responsive PiP for small screens */
    @media (max-width: 480px) {
        .video-iframe-fullscreen-container.pip-mode {
            width: 240px;
            max-width: 240px;
            top: 10px;
            right: 10px;
        }
    }

</style>
