<script lang="ts">
    import MessageInput from './enter_message/MessageInput.svelte';
    import CodeFullscreen from './fullscreen_previews/CodeFullscreen.svelte';
    import ChatHistory from './ChatHistory.svelte';
    import NewChatSuggestions from './NewChatSuggestions.svelte';
    import ChatSearchSuggestions from './ChatSearchSuggestions.svelte';
    // FollowUpSuggestions has been moved to ChatHistory.svelte (rendered below last assistant message)
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
    import { chatKeyManager } from '../services/encryption/ChatKeyManager';
    import { chatSyncService } from '../services/chatSyncService'; // Import chatSyncService
    import { skillPreviewService } from '../services/skillPreviewService'; // Import skillPreviewService
    import KeyboardShortcuts from './KeyboardShortcuts.svelte';
    import WebSearchEmbedPreview from './embeds/web/WebSearchEmbedPreview.svelte';
    import VideoTranscriptEmbedPreview from './embeds/videos/VideoTranscriptEmbedPreview.svelte';
    import PDFEmbedFullscreen from './embeds/pdf/PDFEmbedFullscreen.svelte';
    import ImageEmbedFullscreen from './embeds/images/ImageEmbedFullscreen.svelte';
    import PdfReadEmbedFullscreen from './embeds/pdf/PdfReadEmbedFullscreen.svelte';
    import PdfSearchEmbedFullscreen from './embeds/pdf/PdfSearchEmbedFullscreen.svelte';
    import RecordingEmbedFullscreen from './embeds/audio/RecordingEmbedFullscreen.svelte';
    import { resolveRegistryKey, hasFullscreenComponent, loadFullscreenComponent } from '../services/embedFullscreenResolver';
    import { normalizeEmbedType as registryNormalizeEmbedType } from '../data/embedRegistry.generated';
    import FocusModeContextMenu from './embeds/FocusModeContextMenu.svelte';
    import { appSkillsStore } from '../stores/appSkillsStore'; // For resolving active focus mode name in header banner
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
    import { modelsMetadata } from '../data/modelsMetadata'; // For reasoning model detection in typing indicator
    import { parse_message } from '../message_parsing/parse_message'; // Import markdown parser
    import { loadSessionStorageDraft, getSessionStorageDraftMarkdown, migrateSessionStorageDraftsToIndexedDB, getAllDraftChatIdsWithDrafts } from '../services/drafts/sessionStorageDraftService'; // Import sessionStorage draft service
    import { draftEditorUIState } from '../services/drafts/draftState'; // Import draft state
    import { clearCurrentDraft } from '../services/drafts/draftSave'; // For cleaning up draft when navigating to existing chat
    import { phasedSyncState, NEW_CHAT_SENTINEL } from '../stores/phasedSyncStateStore'; // Import phased sync state store and sentinel value
    import { websocketStatus } from '../stores/websocketStatusStore'; // Import WebSocket status for connection checks
    import { activeChatStore, deepLinkProcessing } from '../stores/activeChatStore'; // For clearing persistent active chat selection
    import { reminderContext } from '../stores/reminderContextStore';
    import { activeEmbedStore } from '../stores/activeEmbedStore'; // For managing embed URL hash
    import {
        skillStoreExampleFullscreenStore,
        closeSkillStoreExampleFullscreen,
    } from '../stores/skillStoreExampleFullscreenStore'; // Synthetic fullscreen state from app-store skill examples
    import {
        chatVideoFullscreenStore,
        closeChatVideoFullscreen,
    } from '../stores/chatVideoFullscreenStore';
    import DirectVideoEmbedFullscreen from '../components/embeds/videos/DirectVideoEmbedFullscreen.svelte';
    import { settingsDeepLink } from '../stores/settingsDeepLinkStore'; // For opening settings to specific page (share)
    import { settingsMenuVisible } from '../components/Settings.svelte'; // Import settingsMenuVisible store to control Settings visibility
    import { chatDebugStore } from '../stores/chatDebugStore';
    import { videoIframeStore } from '../stores/videoIframeStore'; // For standalone VideoIframe component with CSS-based PiP
    import { DEMO_CHATS, LEGAL_CHATS, getDemoMessages, isPublicChat, isNewsletterChat, isLegalChat, translateDemoChat, getAllExampleChats, isExampleChat } from '../demo_chats';
    import ChatContextMenu from './chats/ChatContextMenu.svelte'; // Context menu for resume chat cards
    import { copyChatToClipboard } from '../services/chatExportService'; // For context menu copy action
    import { downloadChatAsZip } from '../services/zipExportService'; // For context menu download action
    import { notificationStore } from '../stores/notificationStore'; // For context menu action feedback
    import { convertDemoChatToChat } from '../demo_chats/convertToChat'; // Import conversion function
    import { incognitoChatService } from '../services/incognitoChatService'; // Import incognito chat service
    import { incognitoMode } from '../stores/incognitoModeStore'; // Import incognito mode store
    import { piiVisibilityStore } from '../stores/piiVisibilityStore'; // Import PII visibility store for hide/unhide toggle
    import { setEmbedPIIState, resetEmbedPIIState } from '../stores/embedPIIStore'; // Update embed PII state for preview/fullscreen components
    import type { PIIMapping } from '../types/chat'; // PII mapping type
    import { isDesktop } from '../utils/platform'; // Import desktop detection for conditional auto-focus
    import { getCategoryGradientColors, getValidIconName, getLucideIcon } from '../utils/categoryUtils'; // For resume card category gradient circle
    import { waitLocale, locale } from 'svelte-i18n'; // Import waitLocale for waiting for translations to load
    import { get } from 'svelte/store'; // Import get to read store values
    import { searchTextHighlightStore, codeLineHighlightStore } from '../stores/messageHighlightStore'; // For source quote text + code line highlighting in embed fullscreen
    import { extractEmbedReferences } from '../services/embedResolver'; // Import for embed navigation
    import { tipTapToCanonicalMarkdown } from '../message_parsing/serializers'; // Import for embed navigation
    import PushNotificationBanner from './PushNotificationBanner.svelte'; // Import push notification banner component
    import { shouldShowPushBanner } from '../stores/pushNotificationStore'; // Import push notification store for banner visibility
    import DailyInspirationBanner from './DailyInspirationBanner.svelte'; // Daily inspiration carousel above welcome screen
    import Not404Screen from './Not404Screen.svelte'; // 404 not-found screen shown when user lands on an unknown URL
    import ForkProgressBanner from './chats/ForkProgressBanner.svelte'; // Slim banner shown while a fork is in progress
    import { forkProgressStore } from '../stores/forkProgressStore'; // Global fork progress — used to show banner on source chat
    import { notFoundPathStore } from '../stores/notFoundPathStore'; // 404 not-found path — set when user lands on unknown URL
    import { openSearch, setSearchQuery } from '../stores/searchStore'; // For 404 search handler
    import { pendingMentionStore } from '../stores/pendingMentionStore'; // For inserting @skill mentions from suggestion clicks
    import type { DailyInspiration } from '../stores/dailyInspirationStore'; // Type for inspiration handler
    import { chatListCache } from '../services/chatListCache'; // For invalidating stale 'sending' status in sidebar cache
    import { updateNavFromCache } from '../stores/chatNavigationStore'; // Populate prev/next nav state from cache when sidebar hasn't been opened yet
    import { sortChats } from './chats/utils/chatSortUtils'; // For recent-chats horizontal scroll sort order
    import { chatMetadataCache } from '../services/chatMetadataCache'; // For decrypting recent chat titles
    import type {
        WebSearchSkillPreviewData,
        VideoTranscriptSkillPreviewData,
    } from '../types/appSkills';
    import type { EmbedStoreEntry } from '../message_parsing/types';
    import { proxyImage, MAX_WIDTH_VIDEO_FULLSCREEN } from '../utils/imageProxy';
    
    // Lightweight type aliases to keep complex event payloads and component refs explicit.
    type EventListenerCallback = (event: Event) => void;
    type UserProfileRecord = { user_id?: string | null };
    type HiddenChatFlag = { is_hidden?: boolean | null };

    const OG_EXAMPLE_SHARED_CHAT_CUTTLEFISH = 'shared_chat_cuttlefish';

    function isOgExampleSharedChatCuttlefish(): boolean {
        if (typeof window === 'undefined') {
            return false;
        }
        const searchParams = new URLSearchParams(window.location.search);
        return searchParams.get('og') === '1' && searchParams.get('og_example') === OG_EXAMPLE_SHARED_CHAT_CUTTLEFISH;
    }

    function getOgExampleResumeChat(): Chat {
        const nowTs = Math.floor(Date.now() / 1000);
        return {
            chat_id: 'c3343b34-c645-4576-be38-87bef9d0b899',
            encrypted_title: null,
            messages_v: 0,
            title_v: 0,
            last_edited_overall_timestamp: nowTs,
            unread_count: 0,
            created_at: nowTs,
            updated_at: nowTs,
            title: 'Cuttlefish Camouflage Mechanism',
            chat_summary: 'Exploring cuttlefish camouflage mechanisms and examples.',
            category: 'general_knowledge',
            icon: 'sparkles'
        };
    }

    type ChatHistoryRef = {
        updateMessages: (messages: ChatMessageModel[], isNewChat?: boolean) => void;
        scrollToTop: () => void;
        scrollToBottom: (smooth?: boolean) => void;
        restoreScrollPosition: (messageId: string) => void;
        scrollToLatestAssistantMessage: () => void;
        triggerNewChatUserMessageScroll: () => void;
    };

    type MessageInputFieldRef = {
        setDraftContent: (chatId: string | undefined, content: TiptapJSON | string | null, version: number, isRemote: boolean) => void;
        setSuggestionText: (text: string) => void;
        setOriginalMarkdown?: (markdown: string) => void;
        setCurrentChatContext?: (chatId: string | null, content: TiptapJSON | null, version: number) => void;
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
        /** Child embed to auto-focus when the search fullscreen opens (from inline badge click) */
        focusChildEmbedId?: string | null;
        /** Quote text to highlight in the fullscreen content (from source quote block click) */
        highlightQuoteText?: string | null;
        /** Line range to highlight in a code embed fullscreen (from #L42 / #L10-L20 suffix) */
        focusLineRange?: { start: number; end: number } | null;
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
        /** Child embed to auto-focus when the search fullscreen opens (from inline badge click) */
        focusChildEmbedId?: string | null;
        /** Quote text to highlight in the fullscreen content (from source quote block click) */
        highlightQuoteText?: string | null;
        /** Line range to highlight in a code embed fullscreen (from #L42 / #L10-L20 suffix) */
        focusLineRange?: { start: number; end: number } | null;
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
    type MessageWithEmbedMeta = ChatMessageModel & {
        _embedErrors?: Set<string>;
        _embedUpdateTimestamp?: number;
    };

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
    let isAdminUser = $derived($userProfile.is_admin === true);

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
    // Track last-seen auth state to detect actual login/logout transitions.
    // Only reset currentUserId when auth state truly changes, preventing the infinite loop where:
    // $effect resets → checkChatOwnership reads & writes currentUserId → effect re-triggers → ∞
    let lastAuthState = $state<boolean | null>(null);
    
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
        const isAuth = $authStore.isAuthenticated;
        
        // Only reset cached user ID when auth state actually CHANGES (login/logout transition),
        // not on every effect run. Unconditional reset caused an infinite loop:
        // reset null → checkChatOwnership reads currentUserId (tracked) → fetches from DB →
        // writes currentUserId → effect re-triggers → reset null → ∞
        if (isAuth !== lastAuthState) {
            lastAuthState = isAuth;
            currentUserId = null;
        }
        
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

    // Wikipedia fullscreen — triggered by clicking a wiki inline link in an assistant message
    let showWikiFullscreen = $state(false);
    let wikiFullscreenData = $state<{
        wikiTitle: string;
        wikidataId?: string | null;
        displayText: string;
        thumbnailUrl?: string | null;
        description?: string | null;
    } | null>(null);

    // PDF embed fullscreen — triggered by clicking a finished PDF embed (editor or read-only)
    let showPdfEmbedFullscreen = $state(false);
    let pdfFullscreenData = $state<{ embedId?: string; filename?: string; pageCount?: number }>({});

    // PDF read fullscreen — triggered by clicking a finished pdf.read skill embed
    let showPdfReadFullscreen = $state(false);
    let pdfReadFullscreenData = $state<{
        embedId?: string;
        filename?: string;
        pagesReturned?: number[];
        pagesSkipped?: number[];
        textContent?: string;
    }>({});

    // PDF search fullscreen — triggered by clicking a finished pdf.search skill embed
    let showPdfSearchFullscreen = $state(false);
    let pdfSearchFullscreenData = $state<{
        embedId?: string;
        filename?: string;
        query?: string;
        totalMatches?: number;
        truncated?: boolean;
        matches?: Array<{ page_num?: number; match_text?: string; context?: string; char_offset?: number }>;
    }>({});

    // Recording embed fullscreen — triggered by clicking a finished voice recording embed
    let showRecordingFullscreen = $state(false);
    let recordingFullscreenData = $state<{
        transcript?: string;
        blobUrl?: string;
        filename?: string;
        duration?: string;
        s3Files?: Record<string, { s3_key: string; size_bytes: number }>;
        s3BaseUrl?: string;
        aesKey?: string;
        aesNonce?: string;
        embedId?: string;
        /** Transcription model name (e.g. 'voxtral-mini-2602') */
        model?: string;
        /** True when the embed is still in the editor (pre-send), enabling transcript editing */
        isEditable?: boolean;
    }>({});

    // Image embed fullscreen — triggered by clicking an in-editor upload embed
    let showImageEmbedFullscreen = $state(false);
    let imageEmbedFullscreenData = $state<{
        src?: string;
        filename?: string;
        s3Files?: Record<string, { s3_key: string; width: number; height: number; size_bytes: number; format: string }>;
        s3BaseUrl?: string;
        aesKey?: string;
        aesNonce?: string;
        isAuthenticated?: boolean;
        fileSize?: number;
        fileType?: string;
        aiDetection?: { ai_generated: number; provider: string } | null;
    }>({});

    // Note: isLoggingOutFromSignup state removed as it was set but never read

    async function handleLoginSuccess(event) {
        const { user, inSignupFlow } = event.detail;
        console.debug("[ActiveChat] [1/3] handleLoginSuccess entry — inSignupFlow:", inSignupFlow);

        // CRITICAL: Set signup state BEFORE updating auth state
        // This ensures signup state is preserved and login interface stays open
        try {
            if (inSignupFlow && user?.last_opened) {
                const { currentSignupStep, isInSignupProcess, getStepFromPath } = await import('../stores/signupState');
                const step = getStepFromPath(user.last_opened);
                currentSignupStep.set(step);
                isInSignupProcess.set(true);
                // Ensure login interface is open to show signup flow
                const { loginInterfaceOpen } = await import('../stores/uiStateStore');
                loginInterfaceOpen.set(true);
                console.debug('[ActiveChat] Set signup state after login:', step);
            } else {
                // CRITICAL: Reset isInSignupProcess when login succeeds outside of signup flow.
                // The header "Login / Sign Up" button sets isInSignupProcess=true (via openSignupInterface event).
                // If the user switches to the Login tab and authenticates (password or passkey), isInSignupProcess
                // remains true, causing the $effect to keep the login interface open instead of closing it.
                // This manifests as "login failed" — the session is established but the UI doesn't transition.
                // Regression fix: commit 9068fc6f1 added this reset but it was still behind a dynamic import
                // that could fail, preventing the auth state update below from transitioning the UI.
                const { isInSignupProcess: isInSignup } = await import('../stores/signupState');
                if (get(isInSignup)) {
                    console.debug('[ActiveChat] Resetting isInSignupProcess to false - login succeeded outside signup flow');
                    isInSignup.set(false);
                }
            }
        } catch (signupStateErr) {
            // Non-fatal: if signup state check fails, proceed with auth state update.
            // The $effect will still close the login interface since isInSignupProcess defaults to false.
            console.error('[ActiveChat] Failed to update signup state during login:', signupStateErr);
        }

        // CRITICAL: Update the authentication state after successful login.
        // This MUST always run — it sets authStore.isAuthenticated=true which triggers
        // the $effect that closes loginInterfaceOpen and transitions to the chat editor.
        // Wrapped in its own try-catch to guarantee execution even if the import above failed.
        console.debug("[ActiveChat] [2/3] Calling setAuthenticatedState");
        try {
            const { setAuthenticatedState } = await import('../stores/authSessionActions');
            setAuthenticatedState();
        } catch (authStateErr) {
            // Last resort: if dynamic import fails, update authStore directly
            console.error('[ActiveChat] Failed to import setAuthenticatedState, falling back to direct authStore update:', authStateErr);
            authStore.update((state) => ({ ...state, isAuthenticated: true, isInitialized: true }));
        }
        console.debug("[ActiveChat] [3/3] Authentication state updated — authStore.isAuthenticated should now be true");
        
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
                // Remove the pending deep link from sessionStorage
                sessionStorage.removeItem('pendingDeepLink');
                
                // Process the deep link by dispatching a custom event that +page.svelte can listen to
                // This ensures the deep link is processed after auth state is fully updated
                // Use a small delay to ensure auth state propagation is complete
                setTimeout(() => {
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

                // OG image mode (?og=1): skip demo-for-everyone so the welcome screen stays visible
                if (typeof window !== 'undefined' && new URLSearchParams(window.location.search).get('og') === '1') {
                    console.debug('[ActiveChat] Skipping handleLogout demo load - og=1 mode');
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

            // OG image mode (?og=1): skip demo-for-everyone auto-load so the welcome screen
            // (daily inspiration + for-everyone card) stays visible in /dev/og-image iframes.
            if (typeof window !== 'undefined' && new URLSearchParams(window.location.search).get('og') === '1') {
                console.debug('[ActiveChat] Skipping auth state effect - og=1 mode (welcome screen should stay visible)');
                return;
            }
            
            if (currentChat && !isPublicChat(currentChat.chat_id)) {
                // Check if this is a shared chat (has chat key in cache or is in sessionStorage shared_chats)
                // chatKeyManager.getKeySync is synchronous, so we can check immediately
                const chatKey = chatKeyManager.getKeySync(currentChat.chat_id);
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

                        // OG image mode (?og=1): skip demo-for-everyone so the welcome screen stays visible
                        if (typeof window !== 'undefined' && new URLSearchParams(window.location.search).get('og') === '1') {
                            console.debug('[ActiveChat] Skipping backup auth handler demo load - og=1 mode');
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
                console.debug('[ActiveChat] $effect: authStore.isAuthenticated=true, closing loginInterfaceOpen (isInSignupProcess=' + $isInSignupProcess + ')');
                loginInterfaceOpen.set(false);
                // Only open chats panel on desktop (not mobile) when closing login interface after successful login
                // On mobile, let the user manually open the panel if they want to see the chat list
                if (!$panelState.isActivityHistoryOpen && !$isMobileView) {
                    panelState.toggleChats();
                }
                // CRITICAL: Fully clear the previously loaded demo chat (e.g. 'demo-for-everyone')
                // on login transition.
                //
                // Why this matters (OPE-354):
                // The non-authenticated view of the app keeps `currentChat` set to the
                // `demo-for-everyone` welcome chat so the demo content renders before login.
                // After authentication succeeds we need a clean welcome screen so the first
                // message the user sends creates a genuinely fresh chat.
                //
                // If we only reset the header (old behavior), `currentChat.chat_id` stays as
                // `demo-for-everyone`. That ID is then passed into MessageInput → handleSend
                // → sendHandlers.ts, which detects it via `isPublicChat(chatIdToUse)` and
                // triggers the "Demo Duplication Flow": every demo message ("Digital team
                // mates for everyone …") gets copied into the user's brand-new chat. The
                // result is the wedged "Creating new chat …" banner sitting on top of the
                // leaked demo history that OPE-354 surfaced in 6 E2E tests.
                //
                // The duplication flow is intentional for unauthenticated users reading the
                // demo — it lets them continue the conversation as a regular chat. Once the
                // user is authenticated the correct path is: fresh welcome screen → fresh
                // chat on first send → phased sync can still load last_opened afterwards.
                if (isPublicChat(currentChat?.chat_id ?? '')) {
                    console.debug('[ActiveChat] Clearing demo chat on login transition (OPE-354)');
                    resetChatHeaderState();
                    currentChat = null;
                    currentMessages = [];
                    followUpSuggestions = [];
                    showWelcome = true;
                    activeChatStore.clearActiveChat();
                    if (chatHistoryRef) {
                        chatHistoryRef.updateMessages([]);
                    }
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

    function handlePdfFullscreen(event: CustomEvent) {
        console.debug('[ActiveChat] Received pdffullscreen event:', event.detail);
        pdfFullscreenData = {
            embedId: event.detail.embedId,
            filename: event.detail.filename,
            pageCount: event.detail.pageCount,
        };
        showPdfEmbedFullscreen = true;
    }

    function handleClosePdfFullscreen() {
        showPdfEmbedFullscreen = false;
        pdfFullscreenData = {};
    }

    function handlePdfReadFullscreen(event: CustomEvent) {
        console.debug('[ActiveChat] Received pdfreadfullscreen event:', event.detail);
        pdfReadFullscreenData = {
            embedId: event.detail.embedId,
            filename: event.detail.filename,
            pagesReturned: event.detail.pagesReturned,
            pagesSkipped: event.detail.pagesSkipped,
            textContent: event.detail.textContent,
        };
        showPdfReadFullscreen = true;
    }

    function handleClosePdfReadFullscreen() {
        showPdfReadFullscreen = false;
        pdfReadFullscreenData = {};
    }

    function handlePdfSearchFullscreen(event: CustomEvent) {
        console.debug('[ActiveChat] Received pdfsearchfullscreen event:', event.detail);
        pdfSearchFullscreenData = {
            embedId: event.detail.embedId,
            filename: event.detail.filename,
            query: event.detail.query,
            totalMatches: event.detail.totalMatches,
            truncated: event.detail.truncated,
            matches: event.detail.matches,
        };
        showPdfSearchFullscreen = true;
    }

    function handleClosePdfSearchFullscreen() {
        showPdfSearchFullscreen = false;
        pdfSearchFullscreenData = {};
    }

    function handleImageFullscreen(event: CustomEvent) {
        console.debug('[ActiveChat] Received imagefullscreen event:', event.detail);
        imageEmbedFullscreenData = {
            src: event.detail.src,
            filename: event.detail.filename,
            s3Files: event.detail.s3Files,
            s3BaseUrl: event.detail.s3BaseUrl,
            aesKey: event.detail.aesKey,
            aesNonce: event.detail.aesNonce,
            isAuthenticated: event.detail.isAuthenticated,
            fileSize: event.detail.fileSize,
            fileType: event.detail.fileType,
            aiDetection: event.detail.aiDetection ?? null,
        };
        showImageEmbedFullscreen = true;
    }

    function handleCloseImageEmbedFullscreen() {
        showImageEmbedFullscreen = false;
        imageEmbedFullscreenData = {};
    }

    function handleRecordingFullscreen(event: CustomEvent) {
        console.debug('[ActiveChat] Received recordingfullscreen event:', event.detail);
        recordingFullscreenData = {
            transcript: event.detail.transcript,
            blobUrl: event.detail.blobUrl,
            filename: event.detail.filename,
            duration: event.detail.duration,
            s3Files: event.detail.s3Files,
            s3BaseUrl: event.detail.s3BaseUrl,
            aesKey: event.detail.aesKey,
            aesNonce: event.detail.aesNonce,
            embedId: event.detail.embedId,
            model: event.detail.model,
            isEditable: event.detail.isEditable === true,
        };
        showRecordingFullscreen = true;
    }

    /**
     * Handle transcript edits from RecordingEmbedFullscreen (pre-send context).
     * Fires 'updaterecordingtranscript' CustomEvent on document so MessageInput.svelte
     * can update the embed node attrs in the TipTap editor.
     */
    function handleRecordingTranscriptChange(embedId: string, newTranscript: string) {
        document.dispatchEvent(
            new CustomEvent('updaterecordingtranscript', {
                bubbles: true,
                composed: true,
                detail: { embedId, transcript: newTranscript },
            }),
        );
    }

    function handleCloseRecordingFullscreen() {
        showRecordingFullscreen = false;
        recordingFullscreenData = {};
    }

    // Add state for embed fullscreen
    let showEmbedFullscreen = $state(false);
    let embedFullscreenData = $state<EmbedFullscreenState>(null);

    /**
     * Subscribe to the app-store skill example fullscreen store and mount
     * the synthetic example inside the normal fullscreen container so it
     * behaves exactly like a real chat embed (slide-up animation,
     * data-driven routing, child drilldown, download/copy, etc.).
     *
     * Sharing is implicitly disabled because synthetic examples have no
     * real embed id in the embed store — the share button in
     * EmbedTopBar only activates for embeds with a resolvable id.
     */
    $effect(() => {
        const example = $skillStoreExampleFullscreenStore;
        if (!example) return;
        embedFullscreenData = {
            embedId: example.embedId,
            embedType: 'app-skill-use',
            decodedContent: example.decodedContent,
            attrs: { app_id: example.appId, skill_id: example.skillId },
            embedData: { status: 'finished' },
            focusChildEmbedId: null,
            highlightQuoteText: null,
            focusLineRange: null,
        };
        showEmbedFullscreen = true;
    });

    /**
     * Direction of the last embed navigation gesture.
     * Used to drive the directional slide-in animation in UnifiedEmbedFullscreen:
     *   'next'     → new embed slides in from the right
     *   'previous' → new embed slides in from the left
     *   null       → normal scale-up open animation (first open / close → reopen)
     * Reset to null immediately after the navigation handler resolves so that
     * subsequent opens from chat history use the default scale animation.
     */
    let embedNavigateDirection = $state<'next' | 'previous' | null>(null);
    
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
            const { chatSyncService: importedChatSyncService } = await import('../services/chatSyncService');
            
            // Generate message ID (format: last 10 chars of chat_id + uuid)
            const chatIdSuffix = chatId.slice(-10);
            const messageId = `${chatIdSuffix}-${crypto.randomUUID()}`;
            const now = Math.floor(Date.now() / 1000);
            
            // Encrypt content with chat key (zero-knowledge architecture)
            const chatKey = await chatKeyManager.getKey(chatId);
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
    
    // Handler for Wikipedia fullscreen events (from WikiInlineLink).
    // Only one fullscreen can be open at a time — close any regular embed fullscreen
    // before opening the wiki fullscreen. Updating wikiFullscreenData while wiki is
    // already open replaces the article (via the {#key} block in the template).
    function handleWikiFullscreen(event: CustomEvent) {
        const detail = event.detail as {
            wikiTitle: string;
            wikidataId?: string | null;
            displayText: string;
            thumbnailUrl?: string | null;
            description?: string | null;
        };
        // Close any regular embed fullscreen first (mutual exclusivity)
        if (showEmbedFullscreen) {
            showEmbedFullscreen = false;
            embedFullscreenData = null;
        }
        wikiFullscreenData = detail;
        showWikiFullscreen = true;
        console.debug('[ActiveChat] Opening Wikipedia fullscreen for:', detail.wikiTitle);
    }

    // Handler for embed fullscreen events (from embed renderers)
    async function handleEmbedFullscreen(event: CustomEvent) {
        console.debug('[ActiveChat] Received embedfullscreen event:', event.detail);
        const detail = event.detail as EmbedFullscreenEventDetail;
        const { embedId, embedData, decodedContent, embedType, attrs, focusChildEmbedId, highlightQuoteText, focusLineRange } = detail;

        // Close any open Wikipedia fullscreen first (mutual exclusivity — only one at a time)
        if (showWikiFullscreen) {
            showWikiFullscreen = false;
            wikiFullscreenData = null;
        }

        // CRITICAL: Set the URL hash guard BEFORE any async work.
        //
        // activeEmbedStore.setActiveEmbed() does two things:
        //   1. Records a timestamp used by isProgrammaticEmbedHashUpdate() as a 100ms guard window
        //   2. Writes window.location.hash → fires a hashchange event
        //
        // If we call setActiveEmbed() only AFTER the async resolve/decrypt/child-embed work
        // (which can take 200–600ms for web search with 10 child embeds), the guard window has
        // already expired by the time the hashchange fires.  handleHashChange() then falls through
        // to processDeepLink → loadChat() (closes the fullscreen) → handleEmbedDeepLink()
        // (reopens it), producing the visible open → close → open flickering.
        //
        // Moving the call here, synchronously, ensures the guard is live before the hash write,
        // so the resulting hashchange is blocked immediately.
        if (embedId) {
            activeEmbedStore.setActiveEmbed(embedId, currentChat?.chat_id ?? null);
            console.debug('[ActiveChat] Early URL hash guard set for embed:', embedId, 'chatId:', currentChat?.chat_id);
        }
        
        // ALWAYS reload from EmbedStore when embedId is provided to ensure we get the latest data.
        // The embed might have been updated since the preview was rendered (e.g., processing -> finished).
        // The event's embedData/decodedContent might be stale (captured at render time before skill results arrived).
        let finalEmbedData = embedData;
        let finalDecodedContent = decodedContent;
        
        if (embedId) {
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
                    // Clean up the URL hash that was set eagerly before async resolution —
                    // without this, the URL shows #embed-id=xxx but no fullscreen renders.
                    activeEmbedStore.clearActiveEmbed();
                    return;
                }
            } catch (error) {
                console.error('[ActiveChat] Error loading embed for fullscreen:', error);
                // Fall back to event data if available
                if (!finalEmbedData && !finalDecodedContent) {
                    // Clean up the URL hash — resolution failed and no fallback data exists
                    activeEmbedStore.clearActiveEmbed();
                    return;
                }
            }
        }
        
        // Normalize embed types from different sources:
        // - Renderers use UI types (e.g. "code-code", "app-skill-use")
        // - Some synced/stored embeds can expose server types (e.g. "code", "app_skill_use")
        // - Deep links dispatch a placeholder type, but we can infer from stored embed when needed
        // Use the generated normalizeEmbedType from embedRegistry to map server types → frontend types.
        // This replaces the local hardcoded switch that grew stale with each new embed type.
        const normalizeEmbedType = (t: string | null | undefined): string | null => {
            if (!t) return null;
            return registryNormalizeEmbedType(t);
        };
        
        let resolvedEmbedType = normalizeEmbedType(embedType) || embedType;
        const inferredType = normalizeEmbedType(finalEmbedData?.type) || finalEmbedData?.type;
        
        // Use inferred type from embed data when:
        // 1. No type was provided in the event (null/undefined) - e.g., navigation between embeds
        // 2. Type is a placeholder (app-skill-use) and we can infer more specific type from stored data
        if (inferredType && (!resolvedEmbedType || resolvedEmbedType === 'app-skill-use' || resolvedEmbedType === 'app_skill_use')) {
            resolvedEmbedType = inferredType;
        }
        
        // Secondary type refinement: if the resolved type is still 'app-skill-use' but the
        // decoded content's own 'type' field reveals a more specific embed type (e.g. 'code',
        // 'document', 'sheet'), override resolvedEmbedType accordingly.
        //
        // This fixes the case where an AI-generated code (or doc/sheet) embed is stored with
        // embed type 'app-skill-use' (because the server tagged it at the app-skill-use layer)
        // but the TOON content itself carries 'type: "code"'. Without this override, navigating
        // to such an embed via the header arrows correctly reaches the embed but renders the
        // generic app-skill-use fallback (JSON dump) instead of the CodeEmbedFullscreen.
        //
        // IMPORTANT: Only refine to known top-level embed types that have their own fullscreen
        // component. Content sub-types like 'image' (used inside images/generate TOON content to
        // denote the output format) are NOT valid top-level embed types and must NOT override
        // 'app-skill-use' — doing so causes the fullscreen branch to be skipped entirely because
        // no template case handles embedType === 'image'.
        const validTopLevelEmbedTypes = new Set(['web-website', 'code-code', 'docs-doc', 'videos-video', 'sheets-sheet', 'maps', 'math-plot']);
        if (resolvedEmbedType === 'app-skill-use' && finalDecodedContent) {
            const contentType = typeof finalDecodedContent.type === 'string' ? finalDecodedContent.type : null;
            if (contentType) {
                const refinedType = normalizeEmbedType(contentType);
                if (refinedType && refinedType !== 'app-skill-use' && validTopLevelEmbedTypes.has(refinedType)) {
                    console.debug('[ActiveChat] Refining embed type from app-skill-use using decoded content type:', {
                        contentType,
                        refinedType
                    });
                    resolvedEmbedType = refinedType;
                } else if (refinedType && refinedType !== 'app-skill-use' && !validTopLevelEmbedTypes.has(refinedType)) {
                    console.debug('[ActiveChat] Skipping embed type refinement: content type is a sub-type, not a top-level embed type:', {
                        contentType,
                        refinedType
                    });
                }
            }
        }
        
        // If we already have this embed open with the same child focus target, ignore duplicate
        // events (e.g. hashchange deep-link echoes). But if focusChildEmbedId differs — meaning
        // the user clicked a different inline badge that points to a different child result of the
        // same parent embed — allow the update through so the fullscreen can switch to that child.
        const alreadyOpenSameChild =
            showEmbedFullscreen &&
            embedFullscreenData?.embedId === embedId &&
            embedFullscreenData?.embedType === resolvedEmbedType &&
            (embedFullscreenData?.focusChildEmbedId ?? null) === (focusChildEmbedId ?? null);
        if (alreadyOpenSameChild) {
            console.debug('[ActiveChat] Ignoring duplicate embedfullscreen event for already-open embed:', {
                embedId,
                resolvedEmbedType,
                focusChildEmbedId
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
                    const websiteResults = Array.isArray(finalDecodedContent.results) ? finalDecodedContent.results : [];
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
                    const placeResults = Array.isArray(finalDecodedContent.results) ? finalDecodedContent.results : [];
                    console.info('[ActiveChat] Loaded', placeResults.length, 'place results for maps search fullscreen:',
                        placeResults.map((r: Record<string, unknown>) => ({ name: String(r?.displayName ?? '').substring(0, 30), address: r?.formattedAddress })));
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
        
        // Set both state variables synchronously in one block so Svelte batches them
        // into a single reactive update. An intermediate microtask (await Promise.resolve)
        // between the two assignments previously caused the {#key} block to re-key while
        // showEmbedFullscreen was still true from a prior embed, triggering spurious
        // destroy/create cycles (visible as the overlay opening and closing 2–5 times).
        embedFullscreenData = {
            embedId,
            embedData: finalEmbedData,
            decodedContent: finalDecodedContent,
            embedType: resolvedEmbedType,
            attrs,
            // Forwarded from EmbedInlineLink when an inline badge references a child embed.
            // The search fullscreen components use this to auto-open the specific result overlay.
            focusChildEmbedId: focusChildEmbedId ?? null,
            // Forwarded from SourceQuoteBlock when a verified source quote is clicked.
            // The fullscreen uses this to scroll to and highlight the quoted text.
            highlightQuoteText: highlightQuoteText ?? null,
            // Forwarded from EmbedInlineLink when a code embed link has a #L42 / #L10-L20 suffix.
            // CodeEmbedFullscreen uses this to highlight + auto-scroll to the target lines.
            focusLineRange: focusLineRange ?? null
        };
        showEmbedFullscreen = true;
        
        // If this was triggered by a source quote click, set the search highlight store
        // so UnifiedEmbedFullscreen's existing highlight mechanism scrolls to + highlights
        // the quoted text within the embed content. This is cleared on fullscreen close.
        if (highlightQuoteText) {
            searchTextHighlightStore.set(highlightQuoteText);
        }

        // If this was triggered by a code embed inline link with a line range suffix,
        // set the code line highlight store so CodeEmbedFullscreen can highlight
        // and auto-scroll to the target lines. Cleared on fullscreen close.
        if (focusLineRange) {
            codeLineHighlightStore.set(focusLineRange);
        }
        
        // URL hash was already set at the top of this function (before async work) to ensure
        // the programmatic-update guard was live before the hashchange fired.  No second call needed.
        
        console.debug('[ActiveChat] Opening embed fullscreen:', resolvedEmbedType, embedId, 'showEmbedFullscreen:', showEmbedFullscreen, 'embedFullscreenData:', !!embedFullscreenData, 'focusChildEmbedId:', focusChildEmbedId);
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
        
        // Clear source quote highlight if it was set (from SourceQuoteBlock click).
        // Only clear if the highlight was set by this feature (not by the search bar).
        if (embedFullscreenData?.highlightQuoteText) {
            searchTextHighlightStore.set(null);
        }

        // Clear code line highlight if it was set (from inline link #L suffix).
        if (embedFullscreenData?.focusLineRange) {
            codeLineHighlightStore.set(null);
        }
        
        showEmbedFullscreen = false;
        embedFullscreenData = null;

        // Clear any active app-store skill example so the $effect doesn't
        // immediately re-mount the synthetic embed.
        closeSkillStoreExampleFullscreen();

        // Reset forceOverlayMode when embed is closed
        // This ensures the next time an embed is opened, it uses the default layout based on screen size
        forceOverlayMode = false;

        // Clear embed store state — clearActiveEmbed() uses replaceState internally,
        // which clears the entire hash (including the chat-id part) without firing hashchange.
        activeEmbedStore.clearActiveEmbed();
        console.debug('[ActiveChat] Cleared embed from URL hash');

        // Restore the chat-only URL hash (#chat-id=X).
        // CRITICAL: Use history.replaceState instead of activeChatStore.setActiveChat to
        // avoid firing a hashchange event. setActiveChat sets window.location.hash which
        // triggers handleHashChange → loadChat → resetChatHeaderState, clearing the chat
        // header (title + summary) until the chat is reopened. The activeChatStore value
        // is already correct (set when the chat was opened), so we only need to restore
        // the URL hash for bookmarkability.
        if (currentChat && currentChat.chat_id) {
            history.replaceState(null, '', `#chat-id=${currentChat.chat_id}`);
            console.debug('[ActiveChat] Restored chat URL hash after closing embed:', currentChat.chat_id);
        }
    }
    
    // ===========================================
    // Embed Navigation Logic
    // ===========================================
    // Extracts embed IDs from chat messages and provides navigation between them
    
    /**
     * Extract all embed IDs from messages in **visual** order.
     *
     * The data (markdown) order lists embeds oldest-first, but grouped
     * embeds are rendered reversed (most-recent-first — see
     * GroupRenderer.ts line ~346).  To make the fullscreen prev/next
     * arrows match what the user sees on screen, we reverse each
     * consecutive run of same-type groupable embeds before returning.
     *
     * Groupable types that get reversed: web-website, videos-video,
     * code-code, docs-doc, sheets-sheet, app-skill-use.
     * Single (ungrouped) embeds keep their original order.
     *
     * @param messages - Array of chat messages
     * @returns Array of embed IDs in visual (on-screen) order
     */
    function extractEmbedIdsFromMessages(messages: ChatMessageModel[]): string[] {
        // Collect embed refs with their types so we can detect app-skill-use runs.
        const embedRefs: Array<{ type: string; embed_id: string }> = [];
        
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
        
        const seenIds = new Set<string>();
        
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
                if (!seenIds.has(ref.embed_id)) {
                    seenIds.add(ref.embed_id);
                    embedRefs.push({ type: ref.type, embed_id: ref.embed_id });
                }
            }
        }
        
        // Build the visual-order list by reversing consecutive runs of same-type
        // embeds.  GroupRenderer.ts reverses ALL group types before rendering
        // (most-recent-first), so we mirror that reversal here so the
        // fullscreen prev/next arrows match the on-screen layout.
        //
        // Groupable types: web-website, videos-video, code-code, docs-doc,
        // sheets-sheet, app-skill-use (see groupHandlers.ts).
        // For app-skill-use, ANY consecutive app-skill-use embeds form a
        // single group regardless of app_id/skill_id.  For other types,
        // only consecutive embeds of the exact same type form a group.
        const GROUPABLE_TYPES = new Set([
            'web-website', 'videos-video', 'code-code',
            'docs-doc', 'sheets-sheet', 'app-skill-use',
        ]);
        
        const visualOrderIds: string[] = [];
        let currentRun: string[] = [];
        let currentRunType: string | null = null;
        
        const flushRun = () => {
            if (currentRun.length > 1) {
                // Multiple consecutive same-type embeds form a group that is
                // rendered reversed — mirror that reversal for navigation.
                visualOrderIds.push(...currentRun.reverse());
            } else if (currentRun.length === 1) {
                // Single embed — no group, no reversal needed.
                visualOrderIds.push(currentRun[0]);
            }
            currentRun = [];
            currentRunType = null;
        };
        
        for (const ref of embedRefs) {
            if (!GROUPABLE_TYPES.has(ref.type)) {
                // Non-groupable embed type — flush any active run, add as-is
                flushRun();
                visualOrderIds.push(ref.embed_id);
                continue;
            }
            
            // Consecutive embeds of the same groupable type form a visual group.
            // (For app-skill-use this also holds — all app-skill-use are same type.)
            const canContinueRun = currentRunType === ref.type;
            
            if (currentRun.length > 0 && !canContinueRun) {
                flushRun();
            }
            
            currentRun.push(ref.embed_id);
            currentRunType = ref.type;
        }
        // Flush any trailing run
        flushRun();
        
        return visualOrderIds;
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
        
        // Signal slide-from-left animation for the incoming embed
        embedNavigateDirection = 'previous';
        
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
        
        // Reset so subsequent open-from-chat-history uses the default scale animation
        embedNavigateDirection = null;
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
        
        // Signal slide-from-right animation for the incoming embed
        embedNavigateDirection = 'next';
        
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
        
        // Reset so subsequent open-from-chat-history uses the default scale animation
        embedNavigateDirection = null;
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
    type PipCorner = 'top-left' | 'top-right' | 'bottom-left' | 'bottom-right';
    let pipCorner = $state<PipCorner>('top-right');

    function handleMovePipToCorner(corner: PipCorner) {
        if (!videoIframeState.isPipMode) {
            return;
        }
        pipCorner = corner;
    }

    let videoIframeContainerInlineStyle = $derived.by(() => {
        if (videoIframeState.isPipMode) {
            return '';
        }

        const anchor = videoIframeState.fullscreenAnchor;
        if (!anchor) {
            return '';
        }

        return `top: ${anchor.top}px; left: ${anchor.left}px; width: ${anchor.width}px; max-width: ${anchor.width}px; transform: none;`;
    });
    
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
        let pipThumbnailUrl = currentState.thumbnailUrl;
        if (!pipThumbnailUrl && pipVideoId) {
            // Construct raw URL and proxy it
            const rawThumbnailUrl = `https://img.youtube.com/vi/${pipVideoId}/maxresdefault.jpg`;
            pipThumbnailUrl = proxyImage(rawThumbnailUrl, MAX_WIDTH_VIDEO_FULLSCREEN);
        } else if (pipThumbnailUrl && (pipThumbnailUrl.includes('img.youtube.com') || pipThumbnailUrl.includes('i.ytimg.com'))) {
            // If it's a direct YouTube URL, proxy it
            pipThumbnailUrl = proxyImage(pipThumbnailUrl, MAX_WIDTH_VIDEO_FULLSCREEN);
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

    // Handler for suggestion click - copies suggestion to message input.
    // When mentionSyntax is provided (e.g. "@skill:web:search"), we insert the
    // body text first, then set pendingMentionStore so MessageInput inserts the
    // @mention chip at the START of the editor. This places the mention before
    // the body text (e.g. "@Travel-Search Show me flights..."), which avoids
    // false positives from the PII/sensitive-data detector (an @mention at the
    // end of text can look like an email address).
    function handleSuggestionClick(suggestion: string, mentionSyntax?: string) {
        console.debug('[ActiveChat] Suggestion clicked:', suggestion, mentionSyntax ? `(mention: ${mentionSyntax})` : '');
        if (messageInputFieldRef) {
            if (mentionSyntax) {
                // 1. Insert body text first so the editor has content.
                messageInputFieldRef.setSuggestionText(suggestion);
                // 2. Set pending mention — the $effect in MessageInput will insert
                //    the @mention chip at the START of the editor, pushing body text
                //    to the right. A trailing space is added after the chip.
                tick().then(() => {
                    pendingMentionStore.set(mentionSyntax);
                    tick().then(() => {
                        messageInputFieldRef?.focus();
                    });
                });
            } else {
                // No mention — insert plain text as before
                messageInputFieldRef.setSuggestionText(suggestion);
                messageInputFieldRef.focus();
            }
        }
    }

    /**
     * Navigate to an existing chat when selected from the suggestion area's chat search results.
     * Fetches the full Chat object from IndexedDB and loads it via loadChat(), matching the
     * same flow as clicking a chat in the sidebar (Chats.svelte handleChatClick).
     */
    async function handleChatNavigate(chatId: string) {
        console.debug('[ActiveChat] Chat navigate from suggestion area:', chatId);
        try {
            // Clean up the current draft before navigating — prevents garbage draft chats
            // from accumulating when the user searches and clicks an existing chat instead of sending.
            await clearCurrentDraft();

            await chatDB.init();
            const chat = await chatDB.getChat(chatId);
            if (!chat) {
                console.warn('[ActiveChat] Chat not found in IndexedDB:', chatId);
                return;
            }
            activeChatStore.setActiveChat(chatId);
            await loadChat(chat);
            window.dispatchEvent(new CustomEvent('globalChatSelected', {
                bubbles: true, composed: true, detail: { chatId }
            }));
        } catch (error) {
            console.error('[ActiveChat] Failed to navigate to chat:', chatId, error);
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

    // Handler for post-processing completed event
    async function handlePostProcessingCompleted(event: CustomEvent) {
        const { chatId, followUpSuggestions: newSuggestions } = event.detail;
        console.info('[ActiveChat] 📬 Post-processing completed event received:', {
            chatId,
            currentChatId: currentChat?.chat_id,
            match: currentChat?.chat_id === chatId,
            newSuggestionsCount: newSuggestions?.length || 0,
            newSuggestionsType: typeof newSuggestions,
            isArray: Array.isArray(newSuggestions),
            currentFollowUpCount: followUpSuggestions.length
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
                        const chatKey = chatKeyManager.getKeySync(chatId);
                        if (!chatKey) {
                            console.debug('[ActiveChat] No chat key for follow-up suggestions decrypt, using event fallback');
                            if (newSuggestions && Array.isArray(newSuggestions) && newSuggestions.length > 0) {
                                followUpSuggestions = newSuggestions;
                            } else {
                                followUpSuggestions = [];
                            }
                        } else {
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
                        }
                    } else if (newSuggestions && Array.isArray(newSuggestions) && newSuggestions.length > 0) {
                        // Fallback: use suggestions from event if database doesn't have them yet
                        followUpSuggestions = newSuggestions;
                        console.info('[ActiveChat] ✅ Fallback: Updated followUpSuggestions from event (database not updated yet):', $state.snapshot(followUpSuggestions));
                    } else {
                        followUpSuggestions = [];
                        console.debug('[ActiveChat] No follow-up suggestions found');
                    }

                } else {
                    console.warn('[ActiveChat] Chat not found in database after post-processing:', chatId);
                    // Fallback: use suggestions from event if chat not found
                    if (newSuggestions && Array.isArray(newSuggestions) && newSuggestions.length > 0) {
                        followUpSuggestions = newSuggestions;
                        console.info('[ActiveChat] ✅ Fallback: Updated followUpSuggestions from event (chat not in DB):', $state.snapshot(followUpSuggestions));
                    }

                }
            } catch (error) {
                console.error('[ActiveChat] Failed to reload suggestions from database after post-processing:', error);
                // Fallback: use suggestions from event if database reload fails
                if (newSuggestions && Array.isArray(newSuggestions) && newSuggestions.length > 0) {
                    followUpSuggestions = newSuggestions;
                    console.info('[ActiveChat] ✅ Fallback: Updated followUpSuggestions from event (database error):', $state.snapshot(followUpSuggestions));
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

    // Bounding rect of the active-chat-container element.
    // Passed to MessageInput so it can compute position:fixed coordinates when
    // expanding into fullscreen mode on narrow screens.
    // Updated on container resize (containerWidth changes) and window scroll/resize.
    let activeChatContainerEl = $state<HTMLElement | null>(null);
    let containerRect = $state<DOMRect | null>(null);

    /** Update containerRect from the current bounding rect of the container element. */
    function updateContainerRect() {
        if (activeChatContainerEl) {
            containerRect = activeChatContainerEl.getBoundingClientRect();
        }
    }

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
    let resumeChatSummary = $state<string | null>(null);
    // When the last-opened chat was credits-rejected (no title, waiting_for_user),
    // show the "Credits needed..." label + user message preview instead of category circle + title.
    let resumeChatIsCreditsError = $state(false);
    let resumeChatUserMessagePreview = $state<string | null>(null);

    // ─── Resume Card Context Menu ────────────────────────────────────
    // Right-click / long-press context menu for resume chat cards on welcome screen
    let resumeCardContextMenuShow = $state(false);
    let resumeCardContextMenuX = $state(0);
    let resumeCardContextMenuY = $state(0);
    let resumeCardContextMenuChat = $state<Chat | null>(null);
    let resumeCardContextMenuDownloading = $state(false);

    function handleResumeCardContextMenu(event: MouseEvent, chat: Chat) {
        event.preventDefault();
        event.stopPropagation();
        resumeCardContextMenuX = event.clientX;
        resumeCardContextMenuY = event.clientY;
        resumeCardContextMenuChat = chat;
        resumeCardContextMenuShow = true;
    }

    // Long-press support for touch devices
    let resumeCardTouchTimer: number | undefined;
    let resumeCardTouchStartX = 0;
    let resumeCardTouchStartY = 0;

    function handleResumeCardTouchStart(event: TouchEvent, chat: Chat) {
        if (event.touches.length !== 1) return;
        const touch = event.touches[0];
        resumeCardTouchStartX = touch.clientX;
        resumeCardTouchStartY = touch.clientY;
        resumeCardTouchTimer = window.setTimeout(() => {
            resumeCardContextMenuX = resumeCardTouchStartX;
            resumeCardContextMenuY = resumeCardTouchStartY;
            resumeCardContextMenuChat = chat;
            resumeCardContextMenuShow = true;
            if (navigator.vibrate) navigator.vibrate(50);
        }, 500);
    }

    function handleResumeCardTouchMove(event: TouchEvent) {
        if (!resumeCardTouchTimer) return;
        const touch = event.touches[0];
        const dx = Math.abs(touch.clientX - resumeCardTouchStartX);
        const dy = Math.abs(touch.clientY - resumeCardTouchStartY);
        if (dx > 10 || dy > 10) {
            clearTimeout(resumeCardTouchTimer);
            resumeCardTouchTimer = undefined;
        }
    }

    function handleResumeCardTouchEnd(event: TouchEvent) {
        if (resumeCardContextMenuShow) {
            event.preventDefault();
            event.stopPropagation();
        }
        if (resumeCardTouchTimer) {
            clearTimeout(resumeCardTouchTimer);
            resumeCardTouchTimer = undefined;
        }
    }

    /** Handle context menu actions for resume chat cards */
    async function handleResumeCardContextMenuAction(event: CustomEvent<string>) {
        const action = event.detail;
        const chat = resumeCardContextMenuChat;
        if (!chat) { resumeCardContextMenuShow = false; return; }

        switch (action) {
            case 'close':
                resumeCardContextMenuShow = false;
                break;
            case 'download': {
                resumeCardContextMenuDownloading = true;
                try {
                    // Public chats (demo/legal) use static bundle; regular chats use IndexedDB
                    const messages = isPublicChat(chat.chat_id)
                        ? getDemoMessages(chat.chat_id, DEMO_CHATS, LEGAL_CHATS)
                        : await chatDB.getMessagesForChat(chat.chat_id);
                    await downloadChatAsZip(chat, messages);
                    notificationStore.success('Chat downloaded successfully');
                } catch (err) {
                    console.error('[ActiveChat] Download failed:', err);
                    notificationStore.error('Download failed');
                } finally {
                    resumeCardContextMenuDownloading = false;
                    resumeCardContextMenuShow = false;
                }
                break;
            }
            case 'copy': {
                try {
                    const messages = isPublicChat(chat.chat_id)
                        ? getDemoMessages(chat.chat_id, DEMO_CHATS, LEGAL_CHATS)
                        : await chatDB.getMessagesForChat(chat.chat_id);
                    await copyChatToClipboard(chat, messages);
                    notificationStore.success('Chat copied to clipboard');
                } catch (err) {
                    console.error('[ActiveChat] Copy failed:', err);
                    notificationStore.error('Copy failed');
                }
                resumeCardContextMenuShow = false;
                break;
            }
            case 'delete': {
                // Demo/legal chats: hide via userProfile; regular chats: delete from DB
                if (isPublicChat(chat.chat_id)) {
                    if (!$authStore.isAuthenticated) {
                        notificationStore.error('Please sign up to customize your experience');
                        resumeCardContextMenuShow = false;
                        return;
                    }
                    const currentHidden = $userProfile.hidden_demo_chats || [];
                    if (!currentHidden.includes(chat.chat_id)) {
                        const updatedHidden = [...currentHidden, chat.chat_id];
                        userProfile.update(profile => ({ ...profile, hidden_demo_chats: updatedHidden }));
                        const { userDB: udb } = await import('../services/userDB');
                        await udb.updateUserData({ hidden_demo_chats: updatedHidden });
                        notificationStore.success('Chat hidden successfully');
                    }
                } else {
                    // Delete regular chat — mirrors Chat.svelte handleDeleteChat
                    try {
                        const chatIdToDelete = chat.chat_id;
                        // Delete from IndexedDB first (optimistic)
                        await chatDB.deleteChat(chatIdToDelete);
                        // Dispatch chatDeleted for UI update
                        chatSyncService.dispatchEvent(new CustomEvent('chatDeleted', { detail: { chat_id: chatIdToDelete } }));
                        // Send server-side delete via WebSocket
                        chatSyncService.sendDeleteChat(chatIdToDelete);
                        notificationStore.success('Chat deleted');
                        // Clear resume card if it was the deleted chat
                        if (resumeChatData?.chat_id === chatIdToDelete) {
                            resumeChatData = null;
                        }
                        // Remove from recentChats array
                        recentChats = recentChats.filter(rc => rc.chat.chat_id !== chatIdToDelete);
                    } catch (err) {
                        console.error('[ActiveChat] Delete failed:', err);
                        notificationStore.error('Failed to delete chat');
                    }
                }
                resumeCardContextMenuShow = false;
                break;
            }
            case 'hide': {
                try {
                    const { hiddenChatService } = await import('../services/hiddenChatService');
                    if (!hiddenChatService.isUnlocked()) {
                        window.dispatchEvent(new CustomEvent('showOverscrollUnlockForHide', {
                            detail: { chatId: chat.chat_id }
                        }));
                        resumeCardContextMenuShow = false;
                        break;
                    }
                    let chatKey = await chatKeyManager.getKey(chat.chat_id);
                    if (!chatKey && chat.encrypted_chat_key) {
                        const result = await hiddenChatService.tryDecryptChatKey(chat.encrypted_chat_key);
                        if (result.chatKey) {
                            chatKey = result.chatKey;
                            chatDB.setChatKey(chat.chat_id, chatKey);
                            if (result.isHidden) {
                                notificationStore.success('Chat is already hidden');
                                resumeCardContextMenuShow = false;
                                break;
                            }
                        }
                    }
                    if (!chatKey) {
                        notificationStore.error('Failed to hide chat. Chat key not found.');
                        resumeCardContextMenuShow = false;
                        break;
                    }
                    const encryptedChatKey = await hiddenChatService.encryptChatKeyWithCombinedSecret(chatKey);
                    if (!encryptedChatKey) {
                        notificationStore.error('Failed to hide chat. Encryption failed.');
                        resumeCardContextMenuShow = false;
                        break;
                    }
                    await chatDB.updateChat({ ...chat, encrypted_chat_key: encryptedChatKey });
                    chatListCache.markDirty();
                    await chatSyncService.sendUpdateEncryptedChatKey(chat.chat_id, encryptedChatKey);
                    try { await chatDB.hideNewChatSuggestionsForChat(chat.chat_id); } catch (_e) { /* non-fatal */ }
                    window.dispatchEvent(new CustomEvent('chatHidden', { detail: { chat_id: chat.chat_id } }));
                    if (resumeChatData?.chat_id === chat.chat_id) resumeChatData = null;
                    recentChats = recentChats.filter(rc => rc.chat.chat_id !== chat.chat_id);
                    notificationStore.success('Chat hidden successfully');
                } catch (err) {
                    console.error('[ActiveChat] Hide failed:', err);
                    notificationStore.error('Failed to hide chat');
                }
                resumeCardContextMenuShow = false;
                break;
            }
            case 'unhide': {
                try {
                    const { hiddenChatService } = await import('../services/hiddenChatService');
                    if (!hiddenChatService.isUnlocked()) {
                        notificationStore.error('Please unlock hidden chats first to unhide this chat.');
                        resumeCardContextMenuShow = false;
                        break;
                    }
                    const success = await hiddenChatService.unhideChat(chat.chat_id);
                    if (success) {
                        try { await chatDB.unhideNewChatSuggestionsForChat(chat.chat_id); } catch (_e) { /* non-fatal */ }
                        chatListCache.markDirty();
                        window.dispatchEvent(new CustomEvent('chatUnhidden', { detail: { chat_id: chat.chat_id } }));
                        notificationStore.success('Chat unhidden successfully');
                    } else {
                        notificationStore.error('Failed to unhide chat.');
                    }
                } catch (err) {
                    console.error('[ActiveChat] Unhide failed:', err);
                    notificationStore.error('Failed to unhide chat');
                }
                resumeCardContextMenuShow = false;
                break;
            }
            case 'pin': {
                try {
                    const chatId = chat.chat_id;
                    const updatedChat = { ...chat, pinned: true };
                    await chatDB.updateChat(updatedChat);
                    chatListCache.markDirty();
                    const { LOCAL_CHAT_LIST_CHANGED_EVENT } = await import('../services/drafts/draftConstants');
                    window.dispatchEvent(new CustomEvent(LOCAL_CHAT_LIST_CHANGED_EVENT, {
                        detail: { chat_id: chatId, pinned: true }
                    }));
                    const { webSocketService } = await import('../services/websocketService');
                    if (webSocketService.isConnected()) {
                        webSocketService.sendMessage('update_chat', { chat_id: chatId, pinned: true });
                    }
                    // Update local UI state so pin badge appears immediately
                    if (resumeChatData?.chat_id === chatId) {
                        resumeChatData = updatedChat;
                    }
                    recentChats = recentChats.map(rc =>
                        rc.chat.chat_id === chatId ? { ...rc, chat: { ...rc.chat, pinned: true } } : rc
                    );
                } catch (err) {
                    console.error('[ActiveChat] Pin failed:', err);
                    notificationStore.error('Failed to pin chat');
                }
                resumeCardContextMenuShow = false;
                break;
            }
            case 'unpin': {
                try {
                    const chatId = chat.chat_id;
                    const updatedChat = { ...chat, pinned: false };
                    await chatDB.updateChat(updatedChat);
                    chatListCache.markDirty();
                    const { LOCAL_CHAT_LIST_CHANGED_EVENT } = await import('../services/drafts/draftConstants');
                    window.dispatchEvent(new CustomEvent(LOCAL_CHAT_LIST_CHANGED_EVENT, {
                        detail: { chat_id: chatId, pinned: false }
                    }));
                    const { webSocketService } = await import('../services/websocketService');
                    if (webSocketService.isConnected()) {
                        webSocketService.sendMessage('update_chat', { chat_id: chatId, pinned: false });
                    }
                    // Update local UI state so pin badge disappears immediately
                    if (resumeChatData?.chat_id === chatId) {
                        resumeChatData = updatedChat;
                    }
                    recentChats = recentChats.map(rc =>
                        rc.chat.chat_id === chatId ? { ...rc, chat: { ...rc.chat, pinned: false } } : rc
                    );
                } catch (err) {
                    console.error('[ActiveChat] Unpin failed:', err);
                    notificationStore.error('Failed to unpin chat');
                }
                resumeCardContextMenuShow = false;
                break;
            }
            case 'markUnread': {
                try {
                    const chatId = chat.chat_id;
                    const { unreadMessagesStore } = await import('../stores/unreadMessagesStore');
                    unreadMessagesStore.clearUnread(chatId);
                    unreadMessagesStore.incrementUnread(chatId);
                    await chatDB.updateChat({ ...chat, unread_count: 1 });
                    chatListCache.markDirty();
                    const { LOCAL_CHAT_LIST_CHANGED_EVENT } = await import('../services/drafts/draftConstants');
                    window.dispatchEvent(new CustomEvent(LOCAL_CHAT_LIST_CHANGED_EVENT, {
                        detail: { chat_id: chatId, unread_count: 1 }
                    }));
                    await chatSyncService.sendChatReadStatus(chatId, 1);
                } catch (err) {
                    console.error('[ActiveChat] Mark unread failed:', err);
                    notificationStore.error('Failed to mark chat as unread');
                }
                resumeCardContextMenuShow = false;
                break;
            }
            case 'markRead': {
                try {
                    const chatId = chat.chat_id;
                    const { unreadMessagesStore } = await import('../stores/unreadMessagesStore');
                    unreadMessagesStore.clearUnread(chatId);
                    await chatDB.updateChat({ ...chat, unread_count: 0 });
                    chatListCache.markDirty();
                    const { LOCAL_CHAT_LIST_CHANGED_EVENT } = await import('../services/drafts/draftConstants');
                    window.dispatchEvent(new CustomEvent(LOCAL_CHAT_LIST_CHANGED_EVENT, {
                        detail: { chat_id: chatId, unread_count: 0 }
                    }));
                    await chatSyncService.sendChatReadStatus(chatId, 0);
                } catch (err) {
                    console.error('[ActiveChat] Mark read failed:', err);
                    notificationStore.error('Failed to mark chat as read');
                }
                resumeCardContextMenuShow = false;
                break;
            }
            default:
                // enterSelectMode, selectChat, unselect — not applicable on welcome screen
                resumeCardContextMenuShow = false;
                break;
        }
    }

    // ─── Recent Chats Horizontal Scroll ────────────────────────────────
    // Additional recent chats shown alongside the primary resume card in
    // a horizontal scrollable row.  The resume card is always first/centered;
    // extra chats scroll to the right.
    type RecentChatMeta = {
        chat: Chat;
        title: string | null;
        category: string | null;
        icon: string | null;
        summary: string | null;
        /** Decrypted draft preview text — set only for draft-only chats (no title, no messages). */
        draftPreview: string | null;
    };
    let recentChats = $state<RecentChatMeta[]>([]);
    let recentChatsScrollEl = $state<HTMLElement | null>(null);
    // Set to true the first time the user manually scrolls the carousel so
    // that reactive effects don't snap it back to the initial position.
    let recentChatsScrolledByUser = false;
    const RECENT_CHATS_TOTAL = 10;
    // Incremented by event handlers (chatDeleted, chatUpdated, syncComplete,
    // visibilitychange) to trigger the $effect that calls loadRecentChats().
    let carouselInvalidationCounter = $state(0);
    // Debounce timer for carousel refreshes — prevents redundant IndexedDB reads
    // during rapid sync events (matching Chats.svelte's 300ms debounce pattern).
    let _carouselRefreshTimer: ReturnType<typeof setTimeout> | null = null;

    /**
     * Load up to RECENT_CHATS_TOTAL recent real chats from IndexedDB.
     * The first entry (last-opened) is excluded because it's shown as the
     * primary resume card — this list only contains the *remaining* chats.
     */
    async function loadRecentChats(): Promise<void> {
        if (!$authStore.isAuthenticated) return;
        try {
            await chatDB.init();
            // Always read from IndexedDB — chatListCache is designed for sidebar
            // (Chats.svelte) remount performance, not the welcome screen. Using
            // the cache here causes stale sort order when returning from a chat.
            let chats: Chat[] = await chatDB.getAllChats();
            const filteredChats = chats.filter((c) => !isPublicChat(c.chat_id));
            const sorted = sortChats(filteredChats, []);

            // Exclude the primary resume chat (it's rendered separately)
            // and the currently active/open chat (avoid showing a draft that's
            // already visible in the message input).
            const lastOpenedId = $userProfile.last_opened;
            const currentActiveChatId = activeChatStore.get();
            const hasResumeChat = lastOpenedId && sorted.some((c) => c.chat_id === lastOpenedId);
            const remaining = sorted.filter((c) =>
                c.chat_id !== lastOpenedId && c.chat_id !== currentActiveChatId
            );
            const limit = hasResumeChat ? RECENT_CHATS_TOTAL - 1 : RECENT_CHATS_TOTAL;
            const topChats = remaining.slice(0, limit);

            const metas: RecentChatMeta[] = await Promise.all(
                topChats.map(async (chat) => {
                    // Draft-only chat: no title, has encrypted draft content
                    // Decrypt the preview so the carousel can show "Draft: {preview}"
                    // instead of "Untitled chat"
                    const isDraftOnly = !chat.title && !chat.encrypted_title && chat.encrypted_draft_md;
                    let draftPreview: string | null = null;

                    if (isDraftOnly) {
                        try {
                            // Prefer the shorter preview; fall back to full draft markdown
                            const toDecrypt = chat.encrypted_draft_preview || chat.encrypted_draft_md;
                            if (toDecrypt) {
                                draftPreview = await decryptWithMasterKey(toDecrypt);
                            }
                        } catch {
                            draftPreview = null;
                        }
                    }

                    if (chat.title) {
                        return { chat, title: chat.title, category: chat.category ?? null, icon: chat.icon ?? null, summary: chat.chat_summary ?? null, draftPreview };
                    }
                    try {
                        const meta = await chatMetadataCache.getDecryptedMetadata(chat);
                        return { chat, title: meta?.title ?? null, category: meta?.category ?? null, icon: meta?.icon ?? null, summary: meta?.summary ?? null, draftPreview: draftPreview ?? meta?.draftPreview ?? null };
                    } catch {
                        return { chat, title: null, category: null, icon: null, summary: null, draftPreview };
                    }
                })
            );
            recentChats = metas;
        } catch (err) {
            console.warn('[ActiveChat] Failed to load recent chats:', err);
        }
    }

    /**
     * Scroll the container so the first card (the primary resume card) is
     * horizontally centred.
     */
    async function centerFirstRecentChat(): Promise<void> {
        if (!recentChatsScrollEl) return;
        await tick();
        const container = recentChatsScrollEl;
        const firstItem = container.querySelector('.resume-chat-large-card, .resume-chat-card') as HTMLElement | null;
        if (!firstItem) return;
        const containerWidth = container.offsetWidth;
        const itemLeft = firstItem.offsetLeft;
        const itemWidth = firstItem.offsetWidth;
        const scrollTarget = itemLeft - (containerWidth / 2) + (itemWidth / 2);
        container.scrollLeft = Math.max(0, scrollTarget);
    }

    /**
     * Build the scrollable intro list for non-authenticated users.
     * Combines static DEMO_CHATS (intro chats, excluding legal) with
     * example chats (static, always available), in that order.
     * Returns Chat[] ready for rendering with the standard card components.
     */
    function loadNonAuthRecentChats(): RecentChatMeta[] {
        // 1. Static intro chats (DEMO_CHATS = INTRO_CHATS, already excludes LEGAL_CHATS)
        const introMetas: RecentChatMeta[] = DEMO_CHATS.map((demoChat) => {
            const translated = translateDemoChat(demoChat);
            const chat = convertDemoChatToChat(translated);
            return {
                chat,
                title: translated.title ?? null,
                category: translated.metadata.category ?? null,
                icon: translated.metadata.icon_names?.[0] ?? null,
                summary: translated.description ?? null,
                draftPreview: null,
            };
        });

        // 2. Example chats (static, always available, no legal chats)
        const communityMetas: RecentChatMeta[] = getAllExampleChats().map((chat) => ({
            chat,
            title: chat.title ?? null,
            category: chat.category ?? null,
            icon: chat.icon?.split(',')[0] ?? null,
            summary: chat.chat_summary ?? null,
            draftPreview: null,
        }));

        return [...introMetas, ...communityMetas];
    }

    // State for non-authenticated users' intro + example chats scroll list
    let nonAuthRecentChats = $state<RecentChatMeta[]>([]);

    /**
     * Debounced wrapper for loadRecentChats — coalesces rapid sync events into
     * a single IndexedDB read (300ms window, matching Chats.svelte pattern).
     */
    function loadRecentChatsDebounced(): void {
        if (_carouselRefreshTimer) clearTimeout(_carouselRefreshTimer);
        _carouselRefreshTimer = setTimeout(() => {
            _carouselRefreshTimer = null;
            loadRecentChats().then(() => {
                if (!recentChatsScrolledByUser) centerFirstRecentChat();
            });
        }, 300);
    }

    // Refresh recent chats when welcome screen appears or auth/sync changes.
    // Reset the user-scroll guard each time fresh data is loaded so the newly
    // centred card is correct for the new data set.
    $effect(() => {
        const isWelcome = showWelcome;
        const isAuth = $authStore.isAuthenticated;
        void $phasedSyncState.initialSyncCompleted;
        void $userProfile.last_opened;
        void $userProfile.total_chat_count;
        // Re-run when carousel is invalidated by cross-device events
        void carouselInvalidationCounter;
        if (!isWelcome) {
            recentChats = [];
            nonAuthRecentChats = [];
            return;
        }
        if (isAuth) {
            nonAuthRecentChats = [];
            recentChatsScrolledByUser = false;
            loadRecentChatsDebounced();
        } else {
            recentChats = [];
            recentChatsScrolledByUser = false;
            nonAuthRecentChats = loadNonAuthRecentChats();
            centerFirstRecentChat();
        }
    });

    // Center when the scroll element or data first becomes available.
    // Attach a one-shot scroll listener so we stop auto-centering once the
    // user has intentionally swiped the carousel (prevents snap-back).
    $effect(() => {
        const el = recentChatsScrollEl;
        void recentChats.length;
        void nonAuthRecentChats.length;
        void resumeChatData;
        if (!el) return;

        if (!recentChatsScrolledByUser) {
            centerFirstRecentChat();
        }

        function onUserScroll() {
            recentChatsScrolledByUser = true;
            el!.removeEventListener('scroll', onUserScroll);
        }
        el.addEventListener('scroll', onUserScroll, { passive: true });
        return () => el.removeEventListener('scroll', onUserScroll);
    });

    /**
     * Open a chat from the recent-chats scroll list.
     * Uses the same pattern as handleResumeLastChat.
     */
    async function handleOpenRecentChat(chat: Chat) {
        console.info(`[ActiveChat] Opening recent chat: ${chat.chat_id}`);
        phasedSyncState.markInitialChatLoaded();
        activeChatStore.setActiveChat(chat.chat_id);
        await loadChat(chat);
        window.dispatchEvent(new CustomEvent('globalChatSelected', {
            bubbles: true, composed: true, detail: { chatId: chat.chat_id }
        }));
    }

    /**
     * Load the last-opened chat from IndexedDB using $userProfile.last_opened.
     * Decrypts title, category, icon, and summary for the resume card display.
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

            // Decrypt title, category, icon, and summary using the chat key
            let decryptedTitle: string | null = null;
            let decryptedCategory: string | null = null;
            let decryptedIcon: string | null = null;
            let decryptedSummary: string | null = null;

            const { decryptWithChatKey, decryptChatKeyWithMasterKey } = await import('../services/cryptoService');
            let chatKey = await chatKeyManager.getKey(chat.chat_id);
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
                        decryptedTitle = await decryptWithChatKey(chat.encrypted_title, chatKey, { chatId: chat.chat_id, fieldName: 'encrypted_title' });
                    } catch {
                        // Title decryption failed – fall through to default
                    }
                }
                // Decrypt category
                if (chat.encrypted_category) {
                    try {
                        decryptedCategory = await decryptWithChatKey(chat.encrypted_category, chatKey, { chatId: chat.chat_id, fieldName: 'encrypted_category' });
                    } catch {
                        // Category decryption failed – will use fallback
                    }
                }
                // Decrypt icon
                if (chat.encrypted_icon) {
                    try {
                        decryptedIcon = await decryptWithChatKey(chat.encrypted_icon, chatKey, { chatId: chat.chat_id, fieldName: 'encrypted_icon' });
                    } catch {
                        // Icon decryption failed – will use fallback
                    }
                }
                // Decrypt summary (used in the large gradient card on tall viewports)
                if (chat.encrypted_chat_summary) {
                    try {
                        decryptedSummary = await decryptWithChatKey(chat.encrypted_chat_summary, chatKey, { chatId: chat.chat_id, fieldName: 'encrypted_chat_summary' });
                    } catch {
                        // Summary decryption failed – card will show title only
                    }
                }
            }

            // Determine if this chat has a real title (plaintext for demo chats, or decrypted)
            const hasTitle = !!(chat.title || decryptedTitle);

            // Always fetch the last message when no title — needed both for the draft-skip
            // check and for detecting credits-rejection state.
            // For titled chats we also fetch if we need to check for credits error.
            const lastMessage = await chatDB.getLastMessageForChat(chat.chat_id);

            // Skip draft chats: chats with no title and no messages are drafts.
            // Only show the resume card for chats that have actual content.
            if (!hasTitle && !lastMessage) {
                console.info(`[ActiveChat] Skipping draft chat (no title, no messages): ${chat.chat_id}`);
                return false;
            }

            // Detect credits-rejection state: the last message is 'waiting_for_user'.
            // This happens when the user sent a message but had insufficient credits.
            // In this case show "Credits needed..." + user message preview instead of
            // the category circle + title (which would show a misleading "Untitled Chat").
            const isCreditsError = lastMessage?.status === 'waiting_for_user';

            if (isCreditsError) {
                // Extract the user message preview from the last message.
                // The last message could be the system rejection (role:'system') or the user
                // message itself (role:'user') depending on timing — handle both.
                let userPreview: string | null = null;
                if (lastMessage?.role === 'user') {
                    userPreview = typeof lastMessage.content === 'string' ? lastMessage.content : null;
                } else if (lastMessage?.role === 'system' && lastMessage.user_message_id) {
                    try {
                        const userMsg = await chatDB.getMessage(lastMessage.user_message_id);
                        if (userMsg?.content) {
                            userPreview = typeof userMsg.content === 'string' ? userMsg.content : null;
                        }
                    } catch {
                        // Ignore — preview will be null
                    }
                }

                resumeChatData = chat;
                resumeChatTitle = null;
                resumeChatCategory = null;
                resumeChatIcon = null;
                resumeChatSummary = null;
                resumeChatIsCreditsError = true;
                resumeChatUserMessagePreview = userPreview;
                console.info(`[ActiveChat] Resume chat is credits-error state: ${chat.chat_id}, preview: "${userPreview}"`);
                return true;
            }

            // Normal path: use cleartext fields as fallback (demo chats have these set directly)
            const displayTitle = chat.title || decryptedTitle || get(text)('common.untitled_chat');
            const displayCategory = chat.category || decryptedCategory || null;
            const displayIcon = chat.icon || decryptedIcon || null;
            const displaySummary = chat.chat_summary || decryptedSummary || null;

            resumeChatData = chat;
            resumeChatTitle = displayTitle;
            resumeChatCategory = displayCategory;
            resumeChatIcon = displayIcon;
            resumeChatSummary = displaySummary;
            resumeChatIsCreditsError = false;
            resumeChatUserMessagePreview = null;
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
        // Read activeChatStore to make this effect reactive to it
        const currentActiveChat = $activeChatStore;
        const isOgExample = isOgExampleSharedChatCuttlefish();

        if (isOgExample && isWelcome && !currentActiveChat) {
            const chat = getOgExampleResumeChat();
            resumeChatData = chat;
            resumeChatTitle = chat.title || $text('common.untitled_chat');
            resumeChatCategory = chat.category || 'general_knowledge';
            resumeChatIcon = chat.icon || 'sparkles';
            resumeChatSummary = chat.chat_summary || null;
            resumeChatIsCreditsError = false;
            resumeChatUserMessagePreview = null;
            return;
        }

        // Only show resume card when on welcome screen, authenticated, and last_opened is a real chat ID
        // (not empty, not '/chat/new' which means the user was already on the new chat screen,
        //  not a demo/legal chat which are client-side static content)
        if (!isWelcome || !isAuth || !lastOpened || lastOpened === '/chat/new' || isPublicChat(lastOpened)) {
            resumeChatData = null;
            resumeChatTitle = null;
            resumeChatCategory = null;
            resumeChatIcon = null;
            resumeChatSummary = null;
            resumeChatIsCreditsError = false;
            resumeChatUserMessagePreview = null;
            return;
        }

        // DEFENSE-IN-DEPTH: If a chat is already active in the store, don't populate
        // resume card data — the user is viewing a chat, not the welcome screen.
        // This guards against stale reactivity triggers where showWelcome is still true
        // but the store was set by another code path moments before the UI re-renders.
        if (currentActiveChat) {
            console.debug(`[ActiveChat] Skipping resume card population — activeChatStore already set to "${currentActiveChat}"`);
            return;
        }

        let cancelled = false;
        // Retry up to 20 times (10 seconds total) to handle cross-device sync
        // where last_opened_updated arrives before Phase 2/3 delivers the chat data.
        // Previous 6-attempt / 3-second window was too short on slow connections.
        const maxAttempts = 20;
        const delayMs = 500; // retry every 500ms for up to 10s

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
    // When Phase 1 sync completes or a cross-device last_opened_updated broadcast
    // arrives, Chats.svelte / chatSyncService stores the resume chat data in
    // phasedSyncState. This $effect bridges that store to our local state,
    // ensuring the resume card appears (and updates) in real-time.
    //
    // NOTE: The `!resumeChatData` guard was intentionally removed so that
    // cross-device last_opened_updated broadcasts can refresh an already-
    // populated resume card. Without this, only the first population fires
    // and subsequent cross-device updates are silently ignored.
    $effect(() => {
        const syncState = $phasedSyncState;
        const isWelcome = showWelcome;
        const isAuth = $authStore.isAuthenticated;
        const currentActiveChat = $activeChatStore;
        const lastOpened = $userProfile.last_opened;

        // Sync from phasedSyncState when on the welcome screen, authenticated,
        // no chat is currently active, and phasedSyncState has resume data.
        // Allows repeated updates (cross-device) by NOT guarding on !resumeChatData.
        if (isWelcome && isAuth && !currentActiveChat && syncState.resumeChatData) {
            // Skip if the same chat is already displayed (no need to re-assign)
            if (resumeChatData?.chat_id === syncState.resumeChatData.chat_id) {
                return;
            }
            // CRITICAL: Only apply sync bridge data if it matches the current last_opened.
            // phasedSyncState.resumeChatData is set during Phase 1 sync or cross-device
            // broadcasts and may be stale when the user opened a different chat locally.
            // Without this guard, navigating Chat A → "New Chat" would show the old
            // Phase 1 resume chat instead of Chat A, because the sync bridge fires
            // immediately (sync) while loadResumeChatFromDB runs async.
            if (lastOpened && syncState.resumeChatData.chat_id !== lastOpened) {
                console.debug(`[ActiveChat] Skipping sync bridge — stale resumeChatData (${syncState.resumeChatData.chat_id}) doesn't match last_opened (${lastOpened})`);
                return;
            }
            resumeChatData = syncState.resumeChatData;
            resumeChatTitle = syncState.resumeChatTitle;
            resumeChatCategory = syncState.resumeChatCategory;
            resumeChatIcon = syncState.resumeChatIcon;
            // Reset credits-error state and summary (will be populated by loadResumeChatFromDB if needed)
            resumeChatSummary = null;
            resumeChatIsCreditsError = false;
            resumeChatUserMessagePreview = null;
            console.info(`[ActiveChat] Resume chat synced from phasedSyncState: "${syncState.resumeChatTitle}" (${syncState.resumeChatData.chat_id})`);
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
    // Whether we are currently showing the "Generating title..." placeholder in the chat header.
    // Set to true when a new-chat message is sent; cleared when title/category/icon arrive.
    let isNewChatGeneratingTitle = $state(false);
    // Whether the first message on this new chat was rejected due to insufficient credits.
    // When true: isNewChatGeneratingTitle is false and the banner shows "Not enough credits".
    // Cleared on next message send or chat switch.
    let isNewChatCreditsError = $state(false);
    // Whether the user now has credits again after a credits rejection.
    // Set to true when isNewChatCreditsError is active and userProfile.credits becomes > 0.
    // Triggers the system message to switch from "Buy Credits" to "Resend message" mode.
    // Cleared together with isNewChatCreditsError on resend, follow-up send, or chat switch.
    let isCreditsRestored = $state(false);
    // Decrypted chat header metadata for new chats, populated once the server sends title/category/icon.
    let activeChatDecryptedTitle = $state<string>('');
    let activeChatDecryptedCategory = $state<string | null>(null);
    let activeChatDecryptedIcon = $state<string | null>(null);
    // Decrypted chat summary shown in the header below the title (available after post-processing).
    let activeChatDecryptedSummary = $state<string | null>(null);
    // Mate name captured from the mate_selected preprocessing step, used for the
    // "{Mate} is typing..." spinner text after model_selected arrives.
    let selectedPreprocessingMateName = $state<string | null>(null);
    // Timestamp of the last completed preprocessing step card, used to enforce
    // a minimum display time (~1500ms) before transitioning to the typing phase.
    let lastStepCardTimestamp = $state(0);
    // Timestamp when the processing phase overlay first became visible.
    // Used to enforce a minimum display time before clearing the overlay when
    // the first streaming chunk (thinking or response) arrives, so users have
    // enough time to read the step cards (title, mate, model).
    let processingPhaseStartTimestamp = 0;
    // Minimum time (ms) the overlay must remain visible once step cards have
    // appeared before it can be cleared by an incoming chunk.
    const MIN_OVERLAY_DISPLAY_MS = 2500;

    /**
     * Clear the processing phase state.
     * Called on chat switch, unmount, error, or when streaming begins.
     */
    function clearProcessingPhase() {
        processingPhase = null;
        selectedPreprocessingMateName = null;
        lastStepCardTimestamp = 0;
        processingPhaseStartTimestamp = 0;
        // Do NOT clear isNewChatGeneratingTitle / activeChatDecrypted* here —
        // those are cleared explicitly on chat switch via resetChatHeaderState().
    }

    /**
     * Reset the chat header state (new-chat title/category/icon placeholder).
     * Called when switching to a different chat or starting a fresh new chat.
     * Must be separate from clearProcessingPhase so that the header remains
     * visible even after streaming begins (clearProcessingPhase fires early).
     */
    function resetChatHeaderState() {
        isNewChatGeneratingTitle = false;
        isNewChatCreditsError = false;
        isCreditsRestored = false;
        activeChatDecryptedTitle = '';
        activeChatDecryptedCategory = null;
        activeChatDecryptedIcon = null;
        activeChatDecryptedSummary = null;
    }

    // ─── Credits restoration detection ─────────────────────────────────────────
    //
    // When a chat is in the credits-error state (isNewChatCreditsError=true) and the
    // user's credit balance becomes positive again (via a user_credits_updated WebSocket
    // event → userProfile store update), we flip isCreditsRestored so the system message
    // in ChatMessage.svelte can switch from "Buy Credits" to "Resend message" mode.
    // The effect only ever sets isCreditsRestored to true — clearing happens explicitly
    // in resetChatHeaderState(), handleResendAfterCreditsRestored(), and handleSendMessage().
    $effect(() => {
        const credits = $userProfile.credits;
        if (isNewChatCreditsError && credits > 0) {
            isCreditsRestored = true;
            console.debug('[ActiveChat] Credits restored while credits-error state is active — showing resend UI');
        }
    });

    /**
     * Called when the user clicks "Resend message" in the credits-restored banner.
     *
     * Steps:
     *   1. Remove the system rejection message from both the UI array and IndexedDB.
     *   2. Reset the original user message status from 'waiting_for_user' → 'sending'.
     *   3. Reset all credits-error header state so the banner returns to "Creating new chat…".
     *   4. Start the processing phase indicator.
     *   5. Re-send the user message via chatSyncService.sendNewMessage().
     *
     * After this, the normal AI response flow takes over: the backend processes the
     * message, generates a title/category/icon, and the chat looks like any other chat.
     */
    async function handleResendAfterCreditsRestored() {
        if (!currentChat) return;

        console.debug('[ActiveChat] handleResendAfterCreditsRestored: starting resend flow');

        // 1. Find and remove the system rejection message
        const systemMsgIndex = currentMessages.findIndex(
            m => m.status === 'waiting_for_user' && (m.role === 'system' || m.role === 'assistant')
        );
        if (systemMsgIndex !== -1) {
            const systemMsg = currentMessages[systemMsgIndex];
            currentMessages = currentMessages.filter((_, i) => i !== systemMsgIndex);
            chatDB.deleteMessage(systemMsg.message_id).catch(err => {
                console.warn('[ActiveChat] handleResendAfterCreditsRestored: failed to delete system rejection message from DB:', err);
            });
            console.debug('[ActiveChat] handleResendAfterCreditsRestored: removed system rejection message', systemMsg.message_id);
        }

        // 2. Find the last user message (the one that was originally rejected)
        const userMsg = [...currentMessages].reverse().find(m => m.role === 'user');
        if (!userMsg) {
            console.warn('[ActiveChat] handleResendAfterCreditsRestored: no user message found to resend');
            return;
        }

        // 3. Reset user message status to 'sending' in UI and DB
        const userMsgIndex = currentMessages.findIndex(m => m.message_id === userMsg.message_id);
        if (userMsgIndex !== -1) {
            const updatedUserMsg = { ...currentMessages[userMsgIndex], status: 'sending' as const };
            currentMessages[userMsgIndex] = updatedUserMsg;
            currentMessages = [...currentMessages];
            chatDB.updateMessageStatus(userMsg.message_id, 'sending').catch(err => {
                console.warn('[ActiveChat] handleResendAfterCreditsRestored: failed to update user message status in DB:', err);
            });
        }

        // 4. Reset credits-error header state → back to loading shimmer
        isNewChatCreditsError = false;
        isCreditsRestored = false;
        isNewChatGeneratingTitle = true;
        isNewChatProcessing = true;
        activeChatDecryptedTitle = '';
        activeChatDecryptedCategory = null;
        activeChatDecryptedIcon = null;
        activeChatDecryptedSummary = null;

        // 5. Start the processing phase indicator
        processingPhase = {
            phase: 'sending',
            statusLines: [$text('enter_message.sending')]
        };

        // 6. Re-send via WebSocket — identical to the automatic offline-retry path
        try {
            await chatSyncService.sendNewMessage(userMsg);
            console.debug('[ActiveChat] handleResendAfterCreditsRestored: message re-sent successfully', userMsg.message_id);
        } catch (err) {
            console.error('[ActiveChat] handleResendAfterCreditsRestored: failed to re-send message:', err);
        }
    }

    /**
     * Clear the processing phase, but only after the overlay has been visible for
     * at least MIN_OVERLAY_DISPLAY_MS since the processing phase started.
     * If the minimum time hasn't elapsed yet, schedules a delayed clear.
     * Always waits one Svelte tick first so the incoming content is already rendered
     * before the overlay fades out (prevents a blank-screen flash).
     *
     * This ensures the step cards (chat title, selected mate, model) are readable
     * before they disappear, even when the AI responds very quickly.
     *
     * @param capturedChatId - The chat_id at the time the chunk arrived.
     *   Used to avoid stale clears after a chat switch.
     */
    function clearProcessingPhaseWhenReady(capturedChatId: string | null) {
        tick().then(() => {
            // Abort if the user switched chats in the meantime
            if (currentChat?.chat_id !== capturedChatId) return;

            // Enforce minimum overlay display time so step cards stay readable.
            // processingPhaseStartTimestamp is 0 if no step progression started
            // (e.g., continuation tasks), in which case we clear immediately.
            if (processingPhaseStartTimestamp > 0) {
                const elapsed = Date.now() - processingPhaseStartTimestamp;
                if (elapsed < MIN_OVERLAY_DISPLAY_MS) {
                    const remainingDelay = MIN_OVERLAY_DISPLAY_MS - elapsed;
                    console.debug(`[ActiveChat] Delaying overlay clear by ${remainingDelay}ms so step cards stay visible`);
                    setTimeout(() => {
                        if (currentChat?.chat_id !== capturedChatId) return;
                        clearProcessingPhase();
                        console.debug('[ActiveChat] Processing phase cleared (delayed, min display elapsed)');
                    }, remainingDelay);
                    return;
                }
            }

            clearProcessingPhase();
            console.debug('[ActiveChat] Processing phase cleared (first streaming content rendered)');
        });
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
            ? $text('common.processing')
            : $text('enter_message.status.analyzing_message');

        // Record when the overlay first became visible so we can enforce a minimum
        // display time before clearing it when the first streaming chunk arrives.
        processingPhaseStartTimestamp = Date.now();

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

            // Build region flag for display — must match all region values in backend/providers/*.yml
            const getRegionFlag = (region: string): string => {
                switch (region) {
                    case 'EU': return '\u{1F1EA}\u{1F1FA}';
                    case 'US': return '\u{1F1FA}\u{1F1F8}';
                    case 'APAC': return '\u{1F30F}';
                    case 'global': return '\u{1F310}';
                    case 'Local': return '\u{1F3E0}';
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

            // Carry forward completedSteps from the processing phase so the step cards
            // (chat title, selected mate, selected model) remain visible during the typing phase.
            // They only disappear when the overlay clears (first streaming chunk + min display time).
            const carrySteps = processingPhase?.phase === 'processing'
                ? processingPhase.completedSteps
                : (processingPhase?.phase === 'typing' ? processingPhase.completedSteps : []);
            processingPhase = { phase: 'typing', statusLines: lines, showIcon: true, completedSteps: carrySteps };
            console.debug('[ActiveChat] Processing phase set to TYPING', { mateName, displayModelName, displayProviderName, displayServerRegion, lineCount: lines.length, completedSteps: carrySteps.length });
        }
    }

    // Track if the message input has content (draft) using $state
    let messageInputHasContent = $state(false);
    // Track live input text for incremental search in new chat suggestions
    let liveInputText = $state('');
    // Track whether the map location selector is open in MessageInput.
    // When true, NewChatSuggestions must be hidden (per UX requirement).
    let messageInputMapsOpen = $state(false);
    
    // Track if user is at bottom of chat (from scrolledToBottom event)
    // Initialize to false to prevent MessageInput from appearing expanded on initial load
    // Will be set correctly by loadChat() or handleScrollPositionUI() once scroll position is determined
    let isAtBottom = $state(false);
    
    // Track if user is at top of chat (for scroll-to-top button visibility)
    let isAtTop = $state(true);
    
    // Track if message input is focused (for showing follow-up suggestions)
    let messageInputFocused = $state(false);

    // Track whether this runtime is touch-capable (phone/tablet).
    let isTouchEnvironment = $state(false);

    // Track viewport height for small-screen adjustments (e.g. hide suggestions on short screens).
    // Initialised at mount and kept in sync via resize listener in onMount below.
    let viewportHeight = $state(typeof window !== 'undefined' ? window.innerHeight : 800);

    /** Keep viewportHeight reactive on window resize. Registered/cleaned up in onMount. */
    function handleViewportResize() {
        // iOS Safari keyboard open/close can emit transient resize values that
        // trigger layout oscillation. While the input is focused, keep the
        // previous viewportHeight stable.
        if (messageInputFocused && isTouchEnvironment) {
            return;
        }
        viewportHeight = window.innerHeight;
    }

    /**
     * True when the viewport is tall enough to comfortably show the large
     * ChatEmbedPreview-style gradient card for the resume-chat link.
     * Threshold: ≥800px covers iPad vertical (768–1024px) and large monitors.
     * Below this threshold the compact horizontal card is shown instead.
     */
    let isTallViewport = $derived(viewportHeight >= 800);

    // Hover tilt effect for the large welcome-screen chat preview card.
    // Mirrors UnifiedEmbedPreview's 3D hover behavior.
    let resumeLargeCardElement = $state<HTMLButtonElement | null>(null);
    let isResumeLargeCardHovering = $state(false);
    let resumeLargeCardMouseX = $state(0); // Normalized -1..1
    let resumeLargeCardMouseY = $state(0); // Normalized -1..1

    const RESUME_CARD_TILT_MAX_ANGLE = 3;
    const RESUME_CARD_TILT_PERSPECTIVE = 800;
    const RESUME_CARD_TILT_SCALE = 0.985;

    let resumeLargeCardTiltTransform = $derived.by(() => {
        if (!isResumeLargeCardHovering) {
            return '';
        }

        const rotateY = resumeLargeCardMouseX * RESUME_CARD_TILT_MAX_ANGLE;
        const rotateX = -resumeLargeCardMouseY * RESUME_CARD_TILT_MAX_ANGLE;

        return `perspective(${RESUME_CARD_TILT_PERSPECTIVE}px) rotateX(${rotateX}deg) rotateY(${rotateY}deg) scale(${RESUME_CARD_TILT_SCALE})`;
    });

    /**
     * Build the inline style string for the large resume card.
     * Accepts a background CSS declaration and an optional gradient color pair.
     * Emits --orb-color-a / --orb-color-b CSS custom properties consumed by
     * the living gradient orb animation (same system as ChatHeader + DailyInspirationBanner).
     */
    function getResumeCardGradientStyle(
        orbColors?: { start: string; end: string } | null,
    ): string {
        const start = orbColors?.start ?? '#4867cd';
        const end = orbColors?.end ?? '#a0beff';

        return [
            `background: linear-gradient(135deg, ${start}, ${end})`,
            `--orb-color-a: ${start}`,
            `--orb-color-b: ${end}`,
        ].join('; ');
    }

    function getResumeLargeCardStyle(
        orbColors?: { start: string; end: string } | null,
    ): string {
        const parts = [getResumeCardGradientStyle(orbColors)];
        if (resumeLargeCardTiltTransform) {
            parts.push(`transform: ${resumeLargeCardTiltTransform}`);
        }
        return parts.join('; ');
    }

    function handleResumeLargeCardMouseEnter(e: MouseEvent) {
        isResumeLargeCardHovering = true;
        updateResumeLargeCardMousePosition(e);
    }

    function handleResumeLargeCardMouseMove(e: MouseEvent) {
        if (!isResumeLargeCardHovering || !resumeLargeCardElement) {
            return;
        }

        updateResumeLargeCardMousePosition(e);
    }

    function handleResumeLargeCardMouseLeave() {
        isResumeLargeCardHovering = false;
        resumeLargeCardMouseX = 0;
        resumeLargeCardMouseY = 0;
    }

    function updateResumeLargeCardMousePosition(e: MouseEvent) {
        if (!resumeLargeCardElement) {
            return;
        }

        const rect = resumeLargeCardElement.getBoundingClientRect();
        resumeLargeCardMouseX = ((e.clientX - rect.left) / rect.width - 0.5) * 2;
        resumeLargeCardMouseY = ((e.clientY - rect.top) / rect.height - 0.5) * 2;
    }

    // ─── Per-card tilt state for the recent-chats scroll ─────────────────
    // Each card gets its own independent tilt instance so they tilt
    // independently while the user hovers.
    class RecentChatTiltState {
        el = $state<HTMLButtonElement | null>(null);
        hovering = $state(false);
        mouseX = $state(0);
        mouseY = $state(0);

        get tiltTransform(): string {
            if (!this.hovering) return '';
            const rotateY = this.mouseX * RESUME_CARD_TILT_MAX_ANGLE;
            const rotateX = -this.mouseY * RESUME_CARD_TILT_MAX_ANGLE;
            return `perspective(${RESUME_CARD_TILT_PERSPECTIVE}px) rotateX(${rotateX}deg) rotateY(${rotateY}deg) scale(${RESUME_CARD_TILT_SCALE})`;
        }

        onMouseEnter(e: MouseEvent) { this.hovering = true; this.updatePosition(e); }
        onMouseMove(e: MouseEvent) { if (!this.hovering || !this.el) return; this.updatePosition(e); }
        onMouseLeave() { this.hovering = false; this.mouseX = 0; this.mouseY = 0; }

        private updatePosition(e: MouseEvent) {
            if (!this.el) return;
            const rect = this.el.getBoundingClientRect();
            this.mouseX = ((e.clientX - rect.left) / rect.width - 0.5) * 2;
            this.mouseY = ((e.clientY - rect.top) / rect.height - 0.5) * 2;
        }
    }

    let recentChatTiltStates = $derived(
        recentChats.map(() => new RecentChatTiltState())
    );

    // Separate tilt state array for non-authenticated users' intro+example chats carousel
    let nonAuthChatTiltStates = $derived(
        nonAuthRecentChats.map(() => new RecentChatTiltState())
    );

    // ─── Height-based suggestions overlap detection ──────────────────────────
    // Reliable DOM-measurement approach: measure whether the new-chat suggestions
    // (rendered above the message input) would visually overlap the resume-chat
    // card / welcome greeting below them.
    //
    // When overlap would occur we hide suggestions by default and only reveal them
    // when the message input is focused.  On focus we also hide the daily
    // inspiration banner + welcome greeting so there is enough room.
    //
    // Element refs — bound in the template.
    let chatSideEl = $state<HTMLElement | null>(null);
    let welcomeContentEl = $state<HTMLElement | null>(null);
    let messageInputContainerEl = $state<HTMLElement | null>(null);

    /**
     * True when the new-chat suggestions would overlap the welcome / resume-chat
     * content if both were visible simultaneously.
     *
     * Recalculated via a ResizeObserver on chatSideEl (see onMount below).
     * The estimate uses the measured height of the welcome content block plus a
     * ~140px allowance for the suggestions panel itself.
     */
    let suggestionsWouldOverlapWelcome = $state(false);

    // Sticky focus state: stays true for 150ms after blur so that the
    // suggestions visibility condition doesn't flicker when the user clicks
    // outside the message input (overlap recalc needs time to settle).
    let messageInputRecentlyFocused = $state(false);
    let blurTimer: number | undefined;

    $effect(() => {
        if (messageInputFocused) {
            if (blurTimer) clearTimeout(blurTimer);
            messageInputRecentlyFocused = true;
        } else {
            blurTimer = window.setTimeout(() => {
                messageInputRecentlyFocused = false;
            }, 150);
        }
    });

    // Cache the last measured welcome content height so that when the welcome
    // block is hidden (hideWelcomeForKeyboard fades it to invisible), we can still
    // use its height for overlap calculations. Without this, hiding the welcome
    // causes welcomeHeight=0 → no overlap → show welcome → overlap again → hide
    // → infinite flicker loop.
    let lastKnownWelcomeHeight = 0;

    // Estimated height the suggestions panel occupies (header + 3 items + margin).
    // Used as the minimum clearance we require between the welcome block bottom
    // and the message-input top before we consider the layout "tight".
    const SUGGESTIONS_APPROX_HEIGHT = 150;

    /**
     * Re-measure whether suggestions would overlap the welcome content.
     * Called by the ResizeObserver and whenever relevant state changes.
     */
    function recalculateSuggestionsOverlap() {
        // While typing on touch devices, avoid overlap re-measurement churn that
        // can cause welcome/suggestions visibility oscillation during keyboard
        // animation on iOS Safari.
        if (messageInputFocused && isTouchEnvironment) {
            return;
        }

        if (!chatSideEl) {
            suggestionsWouldOverlapWelcome = false;
            return;
        }

        const containerRect = chatSideEl.getBoundingClientRect();
        const containerHeight = containerRect.height;

        // Height of the welcome content block (greeting + resume card).
        // When the element is visible, measure it and cache the value.
        // When hidden (e.g. showWelcome=false removed it from DOM), use the
        // cached height so the overlap calculation remains stable — otherwise the
        // cycle hide→welcomeHeight=0→noOverlap→show→overlap→hide causes flicker.
        const measuredWelcomeHeight = welcomeContentEl ? welcomeContentEl.getBoundingClientRect().height : 0;
        if (measuredWelcomeHeight > 0) {
            lastKnownWelcomeHeight = measuredWelcomeHeight;
        }
        const welcomeHeight = measuredWelcomeHeight > 0 ? measuredWelcomeHeight : lastKnownWelcomeHeight;

        // Height of just the message input itself (NOT the container, which also holds
        // NewChatSuggestions). Using messageInputContainerEl here would create a feedback
        // loop: suggestions visible → container taller → gap smaller → hide suggestions →
        // container shorter → gap larger → show suggestions → repeat → effect_update_depth_exceeded.
        // Instead we use messageInputHeight (dispatched by MessageInput) which measures only
        // the editor/toolbar area, plus a ~60px allowance for padding and action bar.
        const inputHeight = messageInputHeight + 60;

        // The welcome block is vertically centered (top: 50% + 60px transform).
        // Approximate its bottom edge position within the container.
        const welcomeCenter = containerHeight * 0.5 + 60;
        const welcomeBottom = welcomeCenter + welcomeHeight / 2;

        // Available gap between welcome bottom and the message input top.
        const inputTop = containerHeight - inputHeight;
        const availableGap = inputTop - welcomeBottom;

        const wouldOverlap = availableGap < SUGGESTIONS_APPROX_HEIGHT;

        if (wouldOverlap !== suggestionsWouldOverlapWelcome) {
            suggestionsWouldOverlapWelcome = wouldOverlap;
        }
    }

    // Track follow-up suggestions for the current chat
    let followUpSuggestions = $state<string[]>([]);
    
    // Track settings/memories suggestions for the current chat
    // These are suggested entries generated during AI post-processing Phase 2
    // Shown as horizontally scrollable cards below the last AI response
    
    // Track rejected suggestion hashes for client-side filtering
    
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

    // Keep containerRect in sync whenever containerWidth changes (i.e., on resize).
    // Reading containerWidth here registers it as a dependency so the effect re-runs on resize.
    $effect(() => {
        if (containerWidth >= 0) updateContainerRect();
    });

    // Force overlay mode: When true, forces the embed fullscreen to use overlay mode even on ultra-wide screens
    // This is toggled by the "minimize chat" button in the chat's top bar when in side-by-side mode
    // User can click this to temporarily hide the chat and show only the embed fullscreen
    let forceOverlayMode = $state(false);
    
    // Determine if we should use side-by-side layout for fullscreen embeds
    // Only use side-by-side when ultra-wide AND a fullscreen is open (embed, wiki, or chat video) AND not forcing overlay mode
    let showSideBySideFullscreen = $derived(isUltraWide && ((showEmbedFullscreen && embedFullscreenData) || (showWikiFullscreen && wikiFullscreenData) || $chatVideoFullscreenStore) && !forceOverlayMode);

    // Determine if we should show the "Show Chat" button in fullscreen embed views
    // Shows when ultra-wide screen has a fullscreen open but chat is hidden (forceOverlayMode)
    let showChatButtonInFullscreen = $derived(isUltraWide && ((showEmbedFullscreen && embedFullscreenData) || (showWikiFullscreen && wikiFullscreenData) || $chatVideoFullscreenStore) && forceOverlayMode);
    
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

    // Hide the welcome greeting and resume-chat card when the keyboard is open (mobile) OR
    // when the suggestions panel would overlap the welcome content and the input is focused.
    // In both cases the user has signalled intent to type — hiding the greeting frees up
    // vertical space so the suggestions are visible without collision.
    let hideWelcomeForKeyboard = $derived(
        messageInputFocused && (isTouchEnvironment || isEffectivelyNarrow || suggestionsWouldOverlapWelcome)
    );

    // Effective chat width: The actual width of the chat area
    // In side-by-side mode, the chat is constrained to 400px regardless of container width
    // This is passed to ChatHistory/ChatMessage for proper responsive behavior
    let effectiveChatWidth = $derived(showSideBySideLayout ? 400 : containerWidth);

    // Re-run overlap detection when layout-affecting state changes:
    // - messageInputHeight changes (keyboard open/close, input grows/shrinks)
    // - resumeChatData changes (resume card appears/disappears, affecting welcome block height)
    // - showWelcome changes (welcome content added/removed)
    // - viewportHeight changes (window resize)
    $effect(() => {
        // Access reactive dependencies explicitly so the effect re-runs on changes
        void messageInputHeight;
        void resumeChatData;
        void showWelcome;
        void viewportHeight;
        // chatSideEl must be available (set after mount)
        if (chatSideEl) {
            recalculateSuggestionsOverlap();
        }
    });

    // Reactive variable to determine when to show the create chat button using Svelte 5 $derived.
    // The button appears when the chat history is not empty or when there's a draft.
    let createButtonVisible = $derived(!showWelcome || messageInputHasContent);
    
    // Add state for current chat and messages using $state - MUST be declared before $derived that uses them
    let currentChat = $state<Chat | null>(null);
    let currentMessages = $state<ChatMessageModel[]>([]); // Holds messages for the currentChat - MUST use $state for Svelte 5 reactivity

    // Generation counter to prevent stale loadChat() completions from overwriting currentMessages.
    // Each loadChat() call increments this; if the counter has moved on by the time async work
    // completes, the stale call bails out instead of writing wrong messages into the view.
    let loadChatGeneration = 0;
    let lastDebugChatInspectionId = $state<string | null>(null);

    // Decrypted active focus mode ID for the current chat (e.g. "jobs-career_insights").
    // Updated whenever the chat changes or a focus_mode_activated / focusModeDeactivated event fires.
    // Used to render the "Focus active" header banner in the chat view.
    let activeFocusId = $state<string | null>(null);
    // App ID extracted from the active focus ID (e.g. "jobs" from "jobs-career_insights")
    let activeFocusAppId = $derived(activeFocusId ? activeFocusId.split('-')[0] : null);
    // Focus mode key within the app (e.g. "career_insights" from "jobs-career_insights")
    let activeFocusModeKey = $derived(activeFocusId ? activeFocusId.split('-').slice(1).join('-') : null);
    // Resolved focus mode metadata for the banner name translation
    let activeFocusModeMetadata = $derived.by(() => {
        if (!activeFocusAppId || !activeFocusModeKey) return null;
        const apps = appSkillsStore.getState().apps;
        const app = apps[activeFocusAppId];
        return app?.focus_modes?.find(f => f.id === activeFocusModeKey) ?? null;
    });
    // CRITICAL: Must use $state() for Svelte 5 reactivity - otherwise store subscription updates
    // won't trigger re-evaluation of $derived values that depend on this variable
    let currentTypingStatus = $state<AITypingStatus | null>(null);

    // Derive whether assistant is currently typing in this chat (drives rainbow glow on container)
    let isAssistantTyping = $derived(
        currentTypingStatus?.isTyping === true &&
        currentTypingStatus?.chatId === currentChat?.chat_id
    );

    // Thinking/Reasoning state for thinking models (Gemini, Anthropic Claude)
    // Map of task_id -> thinking content, streaming status, and signature metadata
    let thinkingContentByTask = $state<Map<string, { content: string; isStreaming: boolean; signature?: string | null; totalTokens?: number | null }>>(new Map());
    // Tracks message IDs that currently show synthetic thinking placeholder text.
    // This lets us replace (not append) on first real chunk and avoid persisting placeholders.
    let thinkingPlaceholderMessageIds = $state<Set<string>>(new Set());

    // eslint-disable-next-line @typescript-eslint/no-unused-vars
    function isThinkingModel(modelName?: string | null, providerName?: string | null): boolean {
        const normalizedModel = (modelName || '').toLowerCase();
        const normalizedProvider = (providerName || '').toLowerCase();
        return (
            normalizedModel.includes('gemini') ||
            normalizedModel.includes('claude') ||
            normalizedProvider.includes('anthropic')
        );
    }

    // eslint-disable-next-line @typescript-eslint/no-unused-vars
    function ensureThinkingPlaceholder(messageId: string, chatId: string, category?: string, modelName?: string) {
        // Translated placeholder text for user-facing display
        const placeholderText = $text('chat.thinking.placeholder');

        const existingMessage = currentMessages.find(m => m.message_id === messageId);
        if (!existingMessage) {
            const placeholderMessage: ChatMessageModel = {
                message_id: messageId,
                chat_id: chatId,
                role: 'assistant',
                category,
                model_name: modelName,
                content: '',
                status: 'streaming',
                created_at: Math.floor(Date.now() / 1000),
                encrypted_content: '',
                // Set thinking fields directly on the message so the ThinkingSection
                // renders immediately even before the thinkingContentByTask prop
                // propagates to ChatHistory (Svelte 5 props update in the next
                // render cycle, but updateMessages runs imperatively).
                thinking_content: placeholderText,
                has_thinking: true,
            };
            currentMessages = [...currentMessages, placeholderMessage];
            clearProcessingPhaseWhenReady(chatId);
        }

        if (!thinkingContentByTask.has(messageId)) {
            thinkingContentByTask.set(messageId, {
                content: placeholderText,
                isStreaming: true,
            });
            thinkingContentByTask = new Map(thinkingContentByTask);
        }

        const nextPlaceholderIds = new Set(thinkingPlaceholderMessageIds);
        nextPlaceholderIds.add(messageId);
        thinkingPlaceholderMessageIds = nextPlaceholderIds;

        // Use tick() so the thinkingContentByTask prop has propagated to
        // ChatHistory by the time it processes the new messages array.
        // Without this, the imperative updateMessages runs before Svelte
        // delivers the updated prop, causing the ThinkingSection to not
        // render on the first frame.
        tick().then(() => {
            if (chatHistoryRef) {
                chatHistoryRef.updateMessages(currentMessages);
            }
        });
    }
    
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
    
    // Reactive variable to determine when to show follow-up suggestions in ChatHistory.
    // Show whenever there are suggestions and the welcome screen is not active.
    // No longer requires messageInputFocused — suggestions are visible below the last
    // assistant message without the user having to click the input first.
    let showFollowUpSuggestions = $derived(!showWelcome && followUpSuggestions.length > 0);

    // Load and refresh the active focus ID whenever the current chat changes.
    // Uses chatMetadataCache to decrypt encrypted_active_focus_id from IndexedDB.
    $effect(() => {
        const chatId = currentChat?.chat_id;
        if (!chatId) {
            activeFocusId = null;
            return;
        }
        // Read asynchronously — use the cached value if available
        (async () => {
            try {
                const { chatMetadataCache } = await import('../services/chatMetadataCache');
                const metadata = await chatMetadataCache.getDecryptedMetadata(currentChat!);
                // Only update if the chat hasn't changed since we started loading
                if (currentChat?.chat_id === chatId) {
                    activeFocusId = metadata?.activeFocusId ?? null;
                }
            } catch (e) {
                console.warn('[ActiveChat] Could not load active focus ID:', e);
                activeFocusId = null;
            }
        })();
    });

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
    
    // Effect to reload follow-up suggestions when MessageInput is focused but suggestions are empty.
    // This handles several failure modes on page reload:
    //   1. Key timing: loadChat ran before loadChatKeysFromDatabase completed, decryption failed
    //   2. Stale currentChat: a chatUpdated event spread a partial object that cleared encrypted_follow_up_request_suggestions
    //   3. Post-processing race: event fired but DB write hadn't committed yet at loadChat time
    //
    // Strategy: always do a fresh DB read as the authoritative source.
    // - For cleartext (demo chats): parse from currentChat directly (no DB read needed)
    // - For real chats: always read from IndexedDB to get the latest version, then decrypt
    //   This avoids relying on potentially stale in-memory currentChat metadata.
    $effect(() => {
        if (messageInputFocused && !showWelcome && currentChat?.chat_id && followUpSuggestions.length === 0) {
            // CRITICAL: Skip suggestion reload if logout is in progress
            // This prevents database access attempts during logout cleanup
            if ($isLoggingOut) {
                console.debug('[ActiveChat] Skipping suggestion reload - logout in progress');
                return;
            }

            // Check for cleartext suggestions first (demo chats) — these are always on currentChat
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
            } else {
                // For all real chats: always do a fresh DB read.
                // This is the robust path that handles key-timing races (where loadChat ran before
                // the master key was available to decrypt the chat key), stale currentChat (where a
                // chatUpdated spread cleared encrypted_follow_up_request_suggestions from memory),
                // and post-processing races. By reading from IndexedDB at focus time, we use the
                // most up-to-date data and the chat keys should be fully loaded by now.
                console.debug('[ActiveChat] MessageInput focused, suggestions empty — reading from IndexedDB');
                (async () => {
                    try {
                        const freshChat = await chatDB.getChat(currentChat.chat_id);
                        // Check for cleartext suggestions on fresh read (example chats)
                        if (freshChat?.follow_up_request_suggestions) {
                            try {
                                const suggestions = JSON.parse(freshChat.follow_up_request_suggestions);
                                if (suggestions && suggestions.length > 0) {
                                    followUpSuggestions = suggestions;
                                    currentChat = { ...currentChat, ...freshChat };
                                    console.info('[ActiveChat] Loaded cleartext follow-up suggestions from fresh DB read:', suggestions.length);
                                }
                            } catch (parseError) {
                                console.error('[ActiveChat] Failed to parse cleartext follow-up suggestions from fresh DB read:', parseError);
                            }
                        } else if (freshChat?.encrypted_follow_up_request_suggestions) {
                            // Use chatKeyManager: by the time the user has focused the input,
                            // loadChatKeysFromDatabase should have completed and the correct key is cached.
                            const chatKey = chatKeyManager.getKeySync(currentChat.chat_id);
                            if (!chatKey) {
                                console.debug('[ActiveChat] No chat key for focus-reload suggestions decrypt, skipping');
                                return;
                            }
                            const { decryptArrayWithChatKey } = await import('../services/cryptoService');
                            const decryptedSuggestions = await decryptArrayWithChatKey(
                                freshChat.encrypted_follow_up_request_suggestions,
                                chatKey
                            );
                            if (decryptedSuggestions && decryptedSuggestions.length > 0) {
                                followUpSuggestions = decryptedSuggestions;
                                // Sync currentChat so subsequent checks see the field
                                currentChat = { ...currentChat, ...freshChat };
                                console.info('[ActiveChat] Loaded follow-up suggestions from fresh DB read on focus:', decryptedSuggestions.length);
                            } else {
                                console.debug('[ActiveChat] Fresh DB read returned no decryptable suggestions for', currentChat.chat_id);
                            }
                        } else {
                            console.debug('[ActiveChat] No follow-up suggestions found in DB for', currentChat.chat_id);
                        }
                    } catch (error) {
                        console.error('[ActiveChat] Failed to load suggestions from DB on focus:', error);
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
    //
    // Returns an array of lines matching the centered overlay format:
    //   Line 1 (primary):   "{mate} is typing..."
    //   Line 2 (secondary): "Powered by {model_name}"
    //   Line 3 (tertiary):  "via {provider} {flag}"
    let typingIndicatorLines = $derived((() => {
        // _aiTaskStateTrigger is a top-level reactive variable.
        // Its change will trigger re-evaluation of this derived value.
        void _aiTaskStateTrigger;
        
        // When the centered indicator is active (processingPhase is not null),
        // hide the bottom typing indicator to avoid duplicate text.
        // The centered overlay handles sending, processing steps, and typing phases.
        // Exception: 'compressing' phase shows the shimmer in the bottom indicator
        // since there is no centered overlay for compression.
        if (processingPhase !== null && processingPhase.phase !== 'compressing') {
            return [];
        }
        
        // Show "Compressing chat..." shimmer during chat compression
        if (processingPhase?.phase === 'compressing') {
            return processingPhase.statusLines;
        }
        
        // Show detailed AI typing indicator once streaming has started
        // (processingPhase is null, meaning the centered indicator has faded out,
        //  but aiTypingStore still shows isTyping = true during streaming)
        if (currentTypingStatus?.isTyping && currentTypingStatus.chatId === currentChat?.chat_id && currentTypingStatus.category) {
            const mateName = $text('mates.' + currentTypingStatus.category);
            const modelName = currentTypingStatus.modelName || ''; 
            const providerName = currentTypingStatus.providerName || '';
            const serverRegion = currentTypingStatus.serverRegion || '';
            
            // Get region flag for display — must match all region values in backend/providers/*.yml
            const getRegionFlag = (region: string): string => {
                switch (region) {
                    case 'EU': return '🇪🇺';
                    case 'US': return '🇺🇸';
                    case 'APAC': return '🌏';
                    case 'global': return '🌐';
                    case 'Local': return '🏠';
                    default: return '';
                }
            };
            
            // Build multi-line indicator matching the centered overlay format:
            //   Line 1: "{mate} is typing..." or "{mate} is thinking..." for reasoning models
            //   Line 2: "Powered by {model_name}" (if available)
            //   Line 3: "via {provider} {flag}" (if available)
            // Check if the current model is a reasoning/thinking model (same logic as Chat.svelte)
            const isReasoningModelForIndicator = (() => {
                if (!modelName) return false;
                const model = modelsMetadata.find(m => m.name === modelName || m.id === modelName);
                return model?.reasoning === true;
            })();
            const primaryLine = isReasoningModelForIndicator
                ? $text('enter_message.is_thinking').replace('{mate}', mateName)
                : $text('enter_message.is_typing').replace('{mate}', mateName);
            const lines: string[] = [primaryLine];
            
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
    // Returns: 'typing' | null
    // 'sending', 'processing', and 'waiting_for_user' are no longer shown at the bottom.
    let typingIndicatorStatusType = $derived.by(() => {
        void _aiTaskStateTrigger;
        
        
        // When centered indicator is active, bottom shows nothing
        // Exception: 'compressing' phase shows as 'typing' shimmer at the bottom
        if (processingPhase !== null && processingPhase.phase !== 'compressing') return null;
        
        if (processingPhase?.phase === 'compressing') return 'typing';
        
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
            // Wait until the new assistant message is rendered in the DOM before fading
            // out the centered overlay. Also enforces a minimum display time so step
            // cards (title, mate, model) remain readable before disappearing.
            clearProcessingPhaseWhenReady(chunk.chat_id);
            
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
                // Guard: skip content update if the cumulative content is shorter than what we already
                // have. This should never happen with correct cumulative streaming, but Gemini
                // multimodal responses have been observed to produce garbled/corrupted intermediate
                // chunks (token-ID sequences) whose accumulated length regresses. Skipping them keeps
                // the displayed text coherent and prevents Tiptap render breakage on mobile.
                const wouldShrink = newLength > 0 && newLength < previousLength;
                if (wouldShrink) {
                    console.warn(
                        `[ActiveChat] ⚠️ Skipping content regression | seq: ${chunk.sequence} | ` +
                        `prev_len: ${previousLength} → new_len: ${newLength} (diff: ${lengthDiff})`
                    );
                } else {
                    // CRITICAL: Store AI response as markdown string, not Tiptap JSON
                    targetMessage.content = chunk.full_content_so_far || '';
                }
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
            // Patch category if the message was created before ai_typing_started arrived and the
            // backend now sends category on every chunk (fix for race condition in issue #5dc543b0).
            if (chunk.category && !targetMessage.category) {
                targetMessage.category = chunk.category;
                console.debug(`[ActiveChat] Patched category on existing message ${targetMessage.message_id}: "${targetMessage.category}"`);
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
                const hasOnlyPlaceholderThinking =
                    thinkingPlaceholderMessageIds.has(chunk.message_id);
                const finalThinkingContent = hasOnlyPlaceholderThinking
                    ? finalMessageInArray.thinking_content
                    : (thinkingEntry?.content || finalMessageInArray.thinking_content);
                const finalThinkingSignature = hasOnlyPlaceholderThinking
                    ? finalMessageInArray.thinking_signature
                    : (thinkingEntry?.signature || finalMessageInArray.thinking_signature);
                const finalThinkingTokenCount = hasOnlyPlaceholderThinking
                    ? finalMessageInArray.thinking_token_count
                    : (thinkingEntry?.totalTokens ?? finalMessageInArray.thinking_token_count);
                // For rejection messages (e.g., insufficient credits), keep 'waiting_for_user' status
                // so the chat shows "Waiting for you..." instead of appearing as a completed response
                const isRejection = !!chunk.rejection_reason;
                const finalStatus = isRejection ? 'waiting_for_user' as const : 'synced' as const;

                // If this was a credits rejection on a new chat, transition the header banner
                // from "Creating new chat..." (loading shimmer) to "Not enough credits" (static).
                // isNewChatProcessing is still true here — it's only reset on chat switch / new-chat-click.
                if (isRejection && chunk.rejection_reason === 'insufficient_credits' && isNewChatProcessing) {
                    isNewChatGeneratingTitle = false;
                    isNewChatCreditsError = true;
                    console.debug('[ActiveChat] Credits rejection on new chat — transitioning header to credits error state');
                }
                // For rejection messages: invalidate the sidebar cache so the stale
                // last-message entry is cleared. The chatUpdated dispatch that re-triggers
                // updateDisplayInfo in Chat.svelte is deferred until AFTER we've populated
                // the cache with the user message (status: 'waiting_for_user') below —
                // that way Chat.svelte always sees the correct state on its first read.
                if (isRejection) {
                    chatListCache.invalidateLastMessage(chunk.chat_id);
                }
                // CRITICAL: Use the server's full_content_so_far from the final chunk as
                // the definitive content. This bypasses the streaming regression guard
                // (line ~3651) which may have blocked a shorter (but correct) content update
                // from QUOTE_VERIFY. Without this, stripped quotes reappear on reload because
                // the client persists the unverified pre-strip content.
                // See: embed source quote verification in stream_consumer.py
                const serverVerifiedContent = chunk.full_content_so_far;
                const finalContent = serverVerifiedContent != null
                    ? serverVerifiedContent
                    : finalMessageInArray.content;

                const updatedFinalMessage = {
                    ...finalMessageInArray,
                    content: finalContent,
                    status: finalStatus,
                    // Preserve role as 'system' for rejection messages
                    role: isRejection ? 'system' as const : finalMessageInArray.role,
                    model_name: finalModelName, // Explicitly preserve/set model_name
                    thinking_content: finalThinkingContent,
                    thinking_signature: finalThinkingSignature,
                    thinking_token_count: finalThinkingTokenCount,
                    has_thinking: !!finalThinkingContent
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
                // For rejection messages (e.g., insufficient credits): set to 'waiting_for_user' so the sidebar shows "Credits needed..."
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
                                // Now that the cache has the user message with status 'waiting_for_user',
                                // notify the sidebar so Chat.svelte re-runs updateDisplayInfo and sees
                                // "Credits needed..." + the user message preview.
                                // This dispatch is intentionally placed AFTER setLastMessage so Chat.svelte
                                // always hits the populated cache (avoiding the earlier timing race where
                                // the dispatch fired before the cache was ready).
                                chatSyncService.dispatchEvent(new CustomEvent('chatUpdated', {
                                    detail: { chat_id: updatedUserMessage.chat_id, type: 'message_status_changed' }
                                }));
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
            // Wait until the thinking placeholder is rendered in the DOM before fading
            // out the centered overlay. Also enforces a minimum display time so step
            // cards (title, mate, model) remain readable before disappearing.
            clearProcessingPhaseWhenReady(chunk.chat_id);
        }
        
        // Update thinking content map using message_id (same as task_id)
        const existing = thinkingContentByTask.get(messageId);
        const hasPlaceholder = thinkingPlaceholderMessageIds.has(messageId);
        const incomingChunk = chunk.content || '';
        const hasIncomingThinkingText = incomingChunk.trim().length > 0;
        const newContent = hasPlaceholder
            ? (hasIncomingThinkingText ? incomingChunk : (existing?.content || ''))
            : (existing?.content || '') + incomingChunk;

        if (hasPlaceholder && hasIncomingThinkingText) {
            const nextPlaceholderIds = new Set(thinkingPlaceholderMessageIds);
            nextPlaceholderIds.delete(messageId);
            thinkingPlaceholderMessageIds = nextPlaceholderIds;
        }
        
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
            if (thinkingPlaceholderMessageIds.has(messageId)) {
                thinkingContentByTask.delete(messageId);
                thinkingContentByTask = new Map(thinkingContentByTask);

                const nextPlaceholderIds = new Set(thinkingPlaceholderMessageIds);
                nextPlaceholderIds.delete(messageId);
                thinkingPlaceholderMessageIds = nextPlaceholderIds;

                if (chatHistoryRef) {
                    chatHistoryRef.updateMessages(currentMessages);
                }
                return;
            }

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
        const { message, newChat, isEditSend, editCreatedAt } = event.detail as {
            message: ChatMessageModel,
            newChat?: Chat,
            isEditSend?: boolean,
            editCreatedAt?: number,
        };

        // Edit mode: truncate currentMessages to remove messages from the edit point
        if (isEditSend && editCreatedAt !== undefined && currentChat?.chat_id) {
            currentMessages = currentMessages.filter(
                m => (m.original_message?.created_at ?? m.created_at ?? 0) < editCreatedAt
            );
            console.debug('[ActiveChat] Edit mode: truncated messages before edit point, remaining:', currentMessages.length);
        }

        // Hide follow-up suggestions until new ones are received
        followUpSuggestions = [];
        
        // Hide settings/memories suggestions when user sends a new message
        // New suggestions will be generated during post-processing
        
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
            // This is a message for an existing, already active chat.
            // If there is a credits rejection system message still present (the user is
            // sending a follow-up instead of clicking "Resend"), remove it first so the
            // chat looks clean: original user message → new user message → AI response.
            if (isNewChatCreditsError || isCreditsRestored) {
                const rejectionIdx = currentMessages.findIndex(
                    m => m.status === 'waiting_for_user' && (m.role === 'system' || m.role === 'assistant')
                );
                if (rejectionIdx !== -1) {
                    const rejectionMsg = currentMessages[rejectionIdx];
                    currentMessages = currentMessages.filter((_, i) => i !== rejectionIdx);
                    chatDB.deleteMessage(rejectionMsg.message_id).catch(err => {
                        console.warn('[ActiveChat] handleSendMessage: failed to delete credits rejection message from DB:', err);
                    });
                    console.debug('[ActiveChat] handleSendMessage: removed credits rejection message before follow-up send', rejectionMsg.message_id);
                }
                isNewChatCreditsError = false;
                isCreditsRestored = false;
            }

            // Ensure we don't duplicate the message if it's already in currentMessages
            if (!currentMessages.some(m => m.message_id === message.message_id)) {
                currentMessages = [...currentMessages, message];
            }
        }

        // RESILIENCE: Ensure activeChatStore is consistent with currentChat after message send.
        // After handleNewChatClick clears activeChatStore to null and then a message is sent,
        // the new-chat branch above should set activeChatStore. But if the existing-chat branch
        // ran instead (e.g., because currentChat was already set by a prior operation), we may
        // have activeChatStore=null while currentChat has the correct chat_id. This causes AI
        // streaming responses to be treated as "background" messages (wrong chat routing) because
        // chatSyncServiceHandlersAI checks activeChatStore to decide foreground vs background.
        //
        // CRITICAL: Only fix when activeChatStore holds a *different* chat ID (genuine mismatch).
        // If activeChatStore is null the user intentionally navigated to "new chat" mode AFTER this
        // handleSendMessage started — do NOT override that by writing the old chat ID back into the
        // store and URL hash. Doing so triggers hashchange → handleChatDeepLink → loadChat which
        // auto-reopens the previous chat while the user is already composing a new one.
        const storeValueAfterSend = activeChatStore.get();
        if (currentChat?.chat_id && storeValueAfterSend !== null && storeValueAfterSend !== currentChat.chat_id) {
            console.warn(`[ActiveChat] handleSendMessage: activeChatStore mismatch after send — ` +
                `store=${storeValueAfterSend}, currentChat=${currentChat.chat_id}. Fixing.`);
            activeChatStore.setActiveChat(currentChat.chat_id);
        }

        // ─── Progressive AI Status Indicator: Start with 'sending' phase ─────
        // Determine if this is a new chat (no title yet) to decide which processing
        // steps to show later when ai_task_initiated arrives.
        const chatForNewCheck = newChat || currentChat;
        // A chat is "new" (needs title generation) only if:
        //   1. Its title_v is 0 or missing (server hasn't generated a title yet), AND
        //   2. We haven't already received and decrypted a title via a prior WebSocket event.
        //
        // The second condition is critical: after the first message the server sends a
        // title_updated/metadata_updated event which decrypts the title into
        // activeChatDecryptedTitle — but does NOT reliably update currentChat.title_v to 1
        // in the local IndexedDB record. On a follow-up message, chatForNewCheck.title_v
        // is therefore still 0, which incorrectly triggers isNewChatProcessing=true and
        // overwrites activeChatDecryptedTitle with '' — causing the header to flash back
        // to the "Creating new chat…" shimmer even though a real title is already shown.
        // Guarding on activeChatDecryptedTitle prevents this false positive.
        isNewChatProcessing = (!chatForNewCheck?.title_v || chatForNewCheck.title_v === 0)
            && !activeChatDecryptedTitle;

        // If this is a new chat, show the "Generating title..." placeholder in the chat header.
        // This is cleared once the title/category/icon arrive via a title_updated or metadata_updated event.
        // Also resets any prior credits error state so the banner returns to loading.
        if (isNewChatProcessing) {
            isNewChatGeneratingTitle = true;
            isNewChatCreditsError = false;
            isCreditsRestored = false;
            activeChatDecryptedTitle = '';
            activeChatDecryptedCategory = null;
            activeChatDecryptedIcon = null;
            activeChatDecryptedSummary = null;
        }
        
        // Start the centered status indicator immediately with "Sending..."
        processingPhase = {
            phase: 'sending',
            statusLines: [$text('enter_message.sending')]
        };
        console.debug('[ActiveChat] Processing phase set to SENDING', { isNewChat: isNewChatProcessing });

        if (chatHistoryRef) {
            console.debug("[ActiveChat] handleSendMessage: Updating ChatHistory with messages:", currentMessages);
            // Pass isNewChatProcessing so ChatHistory can use the extended 2 s scroll
            // delay for new chats, letting the user see the "Creating new chat…" header
            // transition before the view scrolls down to the user message.
            chatHistoryRef.updateMessages(currentMessages, isNewChatProcessing);
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

    // ── 404 Not-Found Screen handlers ──────────────────────────────────────────
    /**
     * Called by Not404Screen when the user picks the Search option.
     * Clears the 404 state, opens the Chats sidebar and activates the search bar
     * pre-filled with the derived query string.
     */
    function handle404Search(query: string) {
        notFoundPathStore.set(null);
        panelState.openChats();
        openSearch({ closeChatsOnEscape: false });
        setSearchQuery(query);
    }

    /**
     * Called by Not404Screen when the user picks the Ask AI option.
     * Clears the 404 state, ensures we are on a clean new-chat screen, then
     * injects the pre-filled message into the message input via setSuggestionText.
     */
    async function handle404AskAI(message: string) {
        notFoundPathStore.set(null);
        if (currentChat) {
            await handleNewChatClick();
        }
        await tick();
        messageInputFieldRef?.setSuggestionText(message);
        messageInputFieldRef?.focus();
    }

    /**
     * Handler for when the create icon is clicked.
     */
    async function handleNewChatClick() {
        console.debug("[ActiveChat] New chat creation initiated");
        // CRITICAL: Clear activeChatStore BEFORE setting showWelcome = true.
        // The resume card $effect guards on $activeChatStore — if it's still set
        // when showWelcome triggers the effect, the guard returns early and the
        // resume card never loads, leaving stale data from the sync bridge.
        try {
            activeChatStore.clearActiveChat();
        } catch (err) {
            console.error('[ActiveChat] Failed to clear activeChatStore on new chat:', err);
        }
        // Reset current chat metadata and messages
        currentChat = null;
        currentMessages = [];
        showWelcome = true; // Show welcome message for new chat
        isAtBottom = false; // Reset to hide action buttons for new chat (user needs to interact first)
        
        // Clear any active processing phase indicator
        clearProcessingPhase();
        // Reset the chat header state (new-chat title placeholder) for the fresh chat
        resetChatHeaderState();
        
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

        // activeChatStore was already cleared at the top of handleNewChatClick()
        // (before showWelcome = true) to ensure the resume card effect sees it.
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
        resumeChatSummary = null;
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

    // Note: handleDismissResumeChat removed – the resume card is always visible
    // on the new chat screen (user is already in "new chat" mode, no need to dismiss).

    /**
     * Handler for clicking a Daily Inspiration banner.
     *
     * Creates a local-only chat (zero-knowledge: encrypted title + first assistant
     * message) immediately, without triggering an LLM request. The user can then
     * read the inspiration and send their own reply to start the actual conversation.
     *
     * Steps:
     *  1. Generate a new chat UUID + chat encryption key
     *  2. Encrypt the phrase as the chat title
     *  3. Persist the Chat record to IndexedDB
     *  4. Build and encrypt a first assistant message containing the phrase
     *     (and YouTube video embed markdown if a video is attached)
     *  5. Save the message to IndexedDB
     *  6. Navigate to the new chat
     */
    async function handleStartChatFromInspiration(inspiration: DailyInspiration) {
        console.info('[ActiveChat] Starting chat from daily inspiration:', inspiration.inspiration_id);

        // Unauthenticated users: open the signup screen (alpha disclaimer step) so they
        // can register and then start using inspirations.
        // Same pattern as handleOpenSignupInterface (message-input signup button).
        if (!$authStore.isAuthenticated) {
            console.debug('[ActiveChat] Guest clicked inspiration banner – opening signup interface');
            currentSignupStep.set(STEP_ALPHA_DISCLAIMER);
            isInSignupProcess.set(true);
            loginInterfaceOpen.set(true);
            if ($panelState.isActivityHistoryOpen) {
                panelState.toggleChats();
            }
            return;
        }

        // ── Deduplication: if this inspiration already has an opened chat, navigate
        //    to it instead of creating a duplicate. Verify the chat still exists in
        //    IndexedDB first (it may have been pruned or not yet synced).
        if (inspiration.is_opened && inspiration.opened_chat_id) {
            const existingChatId = inspiration.opened_chat_id;
            try {
                const existingChat = await chatDB.getChat(existingChatId);
                if (existingChat) {
                    console.info(
                        `[ActiveChat] Inspiration ${inspiration.inspiration_id} already opened — navigating to existing chat ${existingChatId}`,
                    );
                    phasedSyncState.markInitialChatLoaded();
                    activeChatStore.setActiveChat(existingChatId);
                    await loadChat(existingChat);

                    // Warm the embed key cache from IndexedDB so UnifiedEmbedPreview
                    // can decrypt after navigating back to this chat in the same session.
                    //
                    // Without this, if the user navigates away and back, embedKeyCache is
                    // empty (it's in-memory only). When phase 2/3 sync calls putEncrypted()
                    // it replaces the cached decrypted entry with an encrypted-only entry.
                    // The next refetchFromStore() then calls getEmbedKey() → cache miss →
                    // falls back to IndexedDB, which works. BUT if we call setEmbedKeyInCache()
                    // now we avoid that extra IndexedDB round-trip and guarantee the key is
                    // available for immediate use even if IndexedDB is slow or busy.
                    //
                    // IMPORTANT: We must pass hashedChatId (not undefined) to getEmbedKey().
                    // Some inspiration embeds only have a 'chat' key in IDB (no 'master' key).
                    // getEmbedKey(id, undefined) only tries the master slot first and skips
                    // chat-type keys when no hashedChatId is provided — so it returns null
                    // for chat-key-only embeds. Passing the real hashedChatId lets it fall
                    // through to the matching chat-key entry.
                    //
                    // This mirrors the IndexedDB recovery path in the new-chat code below
                    // (the `embedKeyForWrap` recovery block in the `if (reusedEmbedId)` branch).
                    if (inspiration.embed_id) {
                        try {
                            const { embedStore } = await import('../services/embedStore');
                            const { computeSHA256 } = await import('../message_parsing/utils');
                            const cachedKey = embedStore.getEmbedKeyFromCache(inspiration.embed_id);
                            if (!cachedKey) {
                                // Compute the hashed chat ID so getEmbedKey() can match
                                // chat-type key entries in addition to master-type entries.
                                const hashedExistingChatId = await computeSHA256(existingChatId);
                                const recoveredKey = await embedStore.getEmbedKey(
                                    inspiration.embed_id,
                                    hashedExistingChatId,
                                );
                                if (recoveredKey) {
                                    embedStore.setEmbedKeyInCache(
                                        inspiration.embed_id,
                                        recoveredKey,
                                        hashedExistingChatId,
                                    );
                                    console.info(
                                        `[ActiveChat] ✅ Warmed embed key cache from IndexedDB for dedup path (embed ${inspiration.embed_id})`,
                                    );
                                } else {
                                    console.warn(
                                        `[ActiveChat] Could not recover embed key for ${inspiration.embed_id} — embed may show error on re-mount`,
                                    );
                                }
                            }
                        } catch (embedKeyErr) {
                            // Non-fatal: embed will attempt IndexedDB lookup on its own when it renders
                            console.warn(
                                '[ActiveChat] Failed to warm embed key cache in dedup path (non-fatal):',
                                embedKeyErr,
                            );
                        }
                    }

                    return;
                }
                // Chat not found locally — fall through to create a new one.
                // This can happen on a fresh device where the chat hasn't synced yet.
                console.info(
                    `[ActiveChat] Inspiration ${inspiration.inspiration_id} marked as opened but chat ${existingChatId} not found locally — creating new chat`,
                );
            } catch (lookupErr) {
                console.warn(
                    `[ActiveChat] Error looking up existing inspiration chat ${existingChatId}:`,
                    lookupErr,
                );
                // Fall through to create a new chat
            }
        }

        try {
            const { generateChatKey, encryptWithChatKey } = await import('../services/cryptoService');
            const { createEmbedReferenceBlock } = await import('../components/enter_message/services/urlMetadataService');
            const { encode: toonEncode } = await import('@toon-format/toon');
            const { embedStore } = await import('../services/embedStore');
            const { generateUUID } = await import('../message_parsing/utils');

            const chatId = crypto.randomUUID();
            const chatKey = generateChatKey();
            if (!chatKey) {
                console.error('[ActiveChat] Failed to generate chat key for inspiration chat');
                return;
            }

            // Store chat key so subsequent reads work
            chatDB.setChatKey(chatId, chatKey);

            const now = Math.floor(Date.now() / 1000);
            const nowMs = Date.now();
            const phrase = inspiration.phrase;
            // Use the concise title for the chat sidebar (falls back to phrase for
            // older inspirations that don't have a separate title field)
            const chatTitle = inspiration.title || phrase;

            // Encrypt the chat title (short title for sidebar display)
            const encryptedTitle = await encryptWithChatKey(chatTitle, chatKey);

            // Build the first assistant message content.
            // Use the rich assistant_response if available (generated by the LLM to explain
            // the topic and invite further exploration), falling back to the phrase if not.
            // If a video is available, create a proper embed with the rich metadata
            // from the inspiration (title, channel, views, duration, etc.) instead
            // of just pasting a bare URL. This gives the user a full YouTube embed
            // card immediately, without waiting for an API call or server round-trip.
            const firstMessageText = inspiration.assistant_response ?? phrase;
            let messageContent = firstMessageText;
            // Track whether we reused a pre-stored inspiration embed (needed for
            // chat key wrapper creation after the chat and message are created)
            let reusedEmbedId: string | null = null;
            // Captured embed data for cross-device sync — populated in the
            // reusedEmbedId block below, consumed by sendSyncInspirationChat
            // so other devices receive the embed + keys inline with the broadcast
            // instead of racing against a Directus round-trip.
            let inspirationEmbedForSync: import('../services/chatSyncServiceSenders').InspirationEmbedData | undefined;
            if (inspiration.video) {
                const video = inspiration.video;
                const videoUrl = `https://www.youtube.com/watch?v=${video.youtube_id}`;

                // CRITICAL: Reuse the pre-stored inspiration embed if it exists.
                // persistInspirations() already created and encrypted this embed with an
                // embed key + master key wrapper and synced it to Directus. Creating a NEW
                // embed here would abandon the original (with its keys) and produce an
                // embed that has no server-side key wrappers — causing decryption failures
                // on other devices. By reusing the existing embed_id we keep the key chain
                // intact and can add a chat key wrapper below.
                const existingEmbedId = inspiration.embed_id;
                const embedId = existingEmbedId || generateUUID();

                if (existingEmbedId) {
                    reusedEmbedId = existingEmbedId;
                    console.info(
                        `[ActiveChat] Reusing pre-stored inspiration embed ${existingEmbedId} (not creating a new one)`,
                    );
                } else {
                    console.info(
                        `[ActiveChat] No pre-stored embed_id on inspiration — creating new embed ${embedId}`,
                    );
                }

                // Format duration if available (e.g. 273 → "4:33")
                let durationFormatted: string | null = null;
                if (video.duration_seconds != null) {
                    const mins = Math.floor(video.duration_seconds / 60);
                    const secs = video.duration_seconds % 60;
                    durationFormatted = `${mins}:${secs.toString().padStart(2, '0')}`;
                }

                // Build the embed content using the same TOON schema as createStaticYouTubeEmbed
                // but populated with the rich metadata we already have from the inspiration.
                const embedContent = {
                    url: videoUrl,
                    video_id: video.youtube_id,
                    title: video.title || null,
                    description: null,
                    channel_name: video.channel_name || null,
                    channel_id: null,
                    channel_thumbnail: null,
                    thumbnail: video.thumbnail_url || null,
                    duration_seconds: video.duration_seconds ?? null,
                    duration_formatted: durationFormatted,
                    view_count: video.view_count ?? null,
                    like_count: null,
                    published_at: video.published_at || null,
                    fetched_at: new Date().toISOString(),
                };

                // Encode as TOON for storage efficiency (same as urlMetadataService)
                let toonContent: string;
                try {
                    toonContent = toonEncode(embedContent);
                } catch {
                    toonContent = JSON.stringify(embedContent);
                }

                const embedData = {
                    embed_id: embedId,
                    type: 'video',
                    status: 'finished',
                    content: toonContent,
                    text_preview: video.title || 'YouTube Video',
                    createdAt: nowMs,
                    updatedAt: nowMs,
                };

                // Store the embed in EmbedStore (same namespace as regular YouTube embeds).
                // For reused embeds this overwrites the local copy with up-to-date metadata.
                try {
                    await embedStore.put(`embed:${embedId}`, embedData, 'videos-video');
                    console.info(`[ActiveChat] Stored inspiration video embed in EmbedStore: ${embedId}`);
                } catch (embedErr) {
                    console.error('[ActiveChat] Failed to store inspiration embed:', embedErr);
                }

                // Build the embed reference block and include it in the message content.
                // The message rendering pipeline uses this JSON block to resolve + display
                // the embed card inline, exactly like embeds created by the URL metadata service.
                const embedReference = createEmbedReferenceBlock('video', embedId, videoUrl);
                messageContent = `${firstMessageText}\n\n${embedReference}`;
            }

            const encryptedContent = await encryptWithChatKey(messageContent, chatKey);

            // Encrypt category and icon for proper mate display
            const encryptedCategory = await encryptWithChatKey(inspiration.category, chatKey);

            // Build the Chat object (mirrors the shape used by reminder handler)
            // IMPORTANT: both title_v and messages_v are set to 1 (not 0) because:
            // - title_v: 1  → the chat already has a title at creation time. Setting 0 would
            //   cause follow-up handling to regenerate the title from the user's follow-up text,
            //   overwriting the original inspiration title.
            // - messages_v: 1 → the inspiration assistant message is saved to IndexedDB immediately
            //   below (chatDB.saveMessage). Setting 0 here misrepresents the message count and
            //   prevents the backend's "request_chat_history" guard from triggering when the Redis
            //   AI cache is empty (it checks messages_v >= 1 to know history exists somewhere).
            //   Without history, the AI sees only the follow-up message and responds out of context.
            // Both values match what sync_inspiration_chat already sends to the server:
            // chatSyncServiceSenders.ts → sendSyncInspirationChatImpl: messages_v: 1, title_v: 1.
            const newChat = {
                chat_id: chatId,
                title: chatTitle,        // Short title for sidebar display
                encrypted_title: encryptedTitle,
                created_at: now,
                updated_at: now,
                messages_v: 1,
                title_v: 1,
                last_edited_overall_timestamp: now,
                unread_count: 0,
                encrypted_category: encryptedCategory,
                category: inspiration.category,
            };

            await chatDB.updateChat(newChat as import('../types/chat').Chat);

            // Build and save the first assistant message
            const messageId = `${chatId.slice(-10)}-${crypto.randomUUID()}`;
            const assistantMessage = {
                message_id: messageId,
                chat_id: chatId,
                role: 'assistant' as const,
                content: messageContent,    // Cleartext for local display
                encrypted_content: encryptedContent,
                encrypted_category: encryptedCategory,
                category: inspiration.category,
                created_at: now,
                status: 'synced' as const,
            };

            await chatDB.saveMessage(assistantMessage);

            console.info(`[ActiveChat] Created inspiration chat ${chatId} with message ${messageId}`);

            // ── Add chat key wrapper + update hashed_chat_id in Directus ──
            // If we reused a pre-stored inspiration embed, associate it with the
            // newly created chat so the phased sync pipeline (which queries
            // embed_keys by hashed_chat_id) can deliver the key to other devices.
            // This is the same pattern used by normal embeds in handleSendEmbedDataImpl().
            if (reusedEmbedId) {
                try {
                    const { computeSHA256 } = await import('../message_parsing/utils');
                    const {
                        generateEmbedKey,
                        wrapEmbedKeyWithChatKey,
                        wrapEmbedKeyWithMasterKey,
                        encryptWithEmbedKey,
                    } = await import('../services/cryptoService');
                    const {
                        sendStoreEmbedKeysImpl,
                        sendStoreEmbedImpl,
                    } = await import('../services/chatSyncServiceSenders');

                    const profile = await userDB.getUserProfile();
                    const currentUserId = profile?.user_id || '';
                    const hashedChatId = await computeSHA256(chatId);
                    const hashedEmbedId = await computeSHA256(reusedEmbedId);
                    const hashedMessageId = await computeSHA256(messageId);
                    const hashedUserId = await computeSHA256(currentUserId);

                    // Retrieve the existing embed key from cache (set by persistInspirations).
                    // If not in cache (e.g., page reload), first try to recover it from
                    // IndexedDB via the master key wrapper that persistInspirations stored.
                    // Only generate a fresh key (and re-encrypt the content) when BOTH the
                    // memory cache AND IndexedDB are empty — e.g. after clearing browser data.
                    //
                    // Why this matters: if we generate a new key while the existing
                    // encrypted_content in IndexedDB/Directus was written with the old key,
                    // we write the new key into the cache before completing re-encryption.
                    // Any embed render that fires in the window between setEmbedKeyInCache()
                    // and sendStoreEmbedImpl() will try to decrypt old ciphertext with the
                    // new key → AES-GCM auth tag mismatch → embed shows "Error" status.
                    let embedKeyForWrap = embedStore.getEmbedKeyFromCache(reusedEmbedId);
                    let needsReEncrypt = false;

                    if (!embedKeyForWrap) {
                        // Cache miss (e.g. tab reload wiped the in-memory embedKeyCache).
                        // Try to unwrap the existing master key wrapper from IndexedDB.
                        // getEmbedKey() checks IndexedDB and unwraps via the master key —
                        // if this succeeds we can use the original key and skip re-encryption,
                        // keeping the already-stored encrypted_content consistent.
                        console.info(
                            `[ActiveChat] Embed key not in cache for ${reusedEmbedId} — trying IndexedDB recovery`,
                        );
                        const recoveredKey = await embedStore.getEmbedKey(reusedEmbedId, undefined);
                        if (recoveredKey) {
                            embedKeyForWrap = recoveredKey;
                            console.info(
                                `[ActiveChat] ✅ Recovered embed key from IndexedDB for ${reusedEmbedId} — no re-encryption needed`,
                            );
                        } else {
                            // IndexedDB also empty (e.g., browser data cleared or first-time
                            // cross-device). Generate a fresh key and re-encrypt the content
                            // so the new key wrapper and the stored ciphertext are in sync.
                            console.info(
                                `[ActiveChat] IndexedDB recovery failed for ${reusedEmbedId} — generating fresh key and re-encrypting`,
                            );
                            embedKeyForWrap = generateEmbedKey();
                            needsReEncrypt = true;
                        }
                    }

                    // Create a chat key wrapper (this is what was missing before)
                    const wrappedChatKey = await wrapEmbedKeyWithChatKey(embedKeyForWrap, chatKey);

                    // Also create/refresh the master key wrapper
                    const wrappedMasterKey = await wrapEmbedKeyWithMasterKey(embedKeyForWrap);

                    // Cache the embed key for local decryption
                    embedStore.setEmbedKeyInCache(reusedEmbedId, embedKeyForWrap, undefined);

                    const embedKeyTimestamp = Math.floor(Date.now() / 1000);

                    // Store BOTH key wrappers (master + chat) locally and on server
                    const embedKeysForStorage: import('../services/embedStore').EmbedKeyEntry[] = [
                        {
                            hashed_embed_id: hashedEmbedId,
                            key_type: 'master',
                            hashed_chat_id: null,
                            encrypted_embed_key: wrappedMasterKey,
                            hashed_user_id: hashedUserId,
                            created_at: embedKeyTimestamp,
                        },
                        {
                            hashed_embed_id: hashedEmbedId,
                            key_type: 'chat',
                            hashed_chat_id: hashedChatId,
                            encrypted_embed_key: wrappedChatKey,
                            hashed_user_id: hashedUserId,
                            created_at: embedKeyTimestamp,
                        },
                    ];
                    await embedStore.storeEmbedKeys(embedKeysForStorage);

                    // Send key wrappers to Directus (the dedup logic on the server will
                    // skip the master key if it already exists and create the new chat key)
                    const { chatSyncService: syncService } = await import('../services/chatSyncService');
                    if (syncService) {
                        await sendStoreEmbedKeysImpl(syncService, {
                            keys: embedKeysForStorage,
                        });
                    }

                    // Update the embed's hashed_chat_id and hashed_message_id in Directus
                    // so the phased sync pipeline can discover it when syncing this chat.
                    // If we also need to re-encrypt (cache miss), include the new encrypted content.
                    const embedUpdatePayload: Record<string, unknown> = {
                        embed_id: reusedEmbedId,
                        hashed_chat_id: hashedChatId,
                        hashed_message_id: hashedMessageId,
                        hashed_user_id: hashedUserId,
                        updated_at: embedKeyTimestamp,
                    };

                    if (needsReEncrypt && inspiration.video) {
                        const video = inspiration.video;
                        const videoUrl = `https://www.youtube.com/watch?v=${video.youtube_id}`;
                        let durationFmt: string | null = null;
                        if (video.duration_seconds != null) {
                            const m = Math.floor(video.duration_seconds / 60);
                            const s = video.duration_seconds % 60;
                            durationFmt = `${m}:${s.toString().padStart(2, '0')}`;
                        }
                        const embedContentObj = {
                            url: videoUrl,
                            video_id: video.youtube_id,
                            title: video.title || null,
                            description: null,
                            channel_name: video.channel_name || null,
                            channel_id: null,
                            channel_thumbnail: null,
                            thumbnail: video.thumbnail_url || null,
                            duration_seconds: video.duration_seconds ?? null,
                            duration_formatted: durationFmt,
                            view_count: video.view_count ?? null,
                            like_count: null,
                            published_at: video.published_at || null,
                            fetched_at: new Date().toISOString(),
                        };
                        let toonStr: string;
                        try {
                            toonStr = (await import('@toon-format/toon')).encode(embedContentObj);
                        } catch {
                            toonStr = JSON.stringify(embedContentObj);
                        }

                        const encContent = await encryptWithEmbedKey(toonStr, embedKeyForWrap);
                        const encType = await encryptWithEmbedKey('video', embedKeyForWrap);
                        const encPreview = await encryptWithEmbedKey(
                            video.title || 'YouTube Video', embedKeyForWrap,
                        );
                        if (encContent) embedUpdatePayload.encrypted_content = encContent;
                        if (encType) embedUpdatePayload.encrypted_type = encType;
                        if (encPreview) embedUpdatePayload.encrypted_text_preview = encPreview;
                    }

                    if (syncService) {
                        await sendStoreEmbedImpl(
                            syncService,
                            embedUpdatePayload as unknown as import('../types/chat').StoreEmbedPayload,
                        );
                    }

                    console.info(
                        `[ActiveChat] ✅ Associated inspiration embed ${reusedEmbedId} with chat ${chatId} ` +
                        `(added chat key wrapper + updated hashed_chat_id in Directus)` +
                        (needsReEncrypt ? ' [re-encrypted with fresh key]' : ''),
                    );

                    // ── Capture embed data for cross-device sync ─────────────────
                    // Build the encrypted embed payload so sendSyncInspirationChat
                    // can include it in the broadcast. This lets the receiving
                    // device store the embed + keys immediately — no Directus
                    // round-trip required. Without this, a quick device switch
                    // after opening an inspiration often fails because store_embed
                    // hasn't reached Directus yet when the second device calls
                    // request_embed.
                    try {
                        // Get or create the encrypted embed fields for the sync payload.
                        // If needsReEncrypt was true, embedUpdatePayload already has them.
                        // Otherwise, encrypt the content with the embed key now.
                        let encEmbedContent = embedUpdatePayload.encrypted_content as string | undefined;
                        let encEmbedType = embedUpdatePayload.encrypted_type as string | undefined;
                        let encEmbedPreview = embedUpdatePayload.encrypted_text_preview as string | undefined;

                        if (!encEmbedContent && inspiration.video) {
                            // Normal path (no re-encrypt needed): encrypt the embed content
                            // using the original embed key so the receiving device can decrypt.
                            const video = inspiration.video;
                            const videoUrl = `https://www.youtube.com/watch?v=${video.youtube_id}`;
                            let dFmt: string | null = null;
                            if (video.duration_seconds != null) {
                                const mn = Math.floor(video.duration_seconds / 60);
                                const sc = video.duration_seconds % 60;
                                dFmt = `${mn}:${sc.toString().padStart(2, '0')}`;
                            }
                            const embedObj = {
                                url: videoUrl,
                                video_id: video.youtube_id,
                                title: video.title || null,
                                description: null,
                                channel_name: video.channel_name || null,
                                channel_id: null,
                                channel_thumbnail: null,
                                thumbnail: video.thumbnail_url || null,
                                duration_seconds: video.duration_seconds ?? null,
                                duration_formatted: dFmt,
                                view_count: video.view_count ?? null,
                                like_count: null,
                                published_at: video.published_at || null,
                                fetched_at: new Date().toISOString(),
                            };
                            let tStr: string;
                            try {
                                tStr = (await import('@toon-format/toon')).encode(embedObj);
                            } catch {
                                tStr = JSON.stringify(embedObj);
                            }

                            encEmbedContent = await encryptWithEmbedKey(tStr, embedKeyForWrap) ?? undefined;
                            encEmbedType = await encryptWithEmbedKey('video', embedKeyForWrap) ?? undefined;
                            encEmbedPreview = await encryptWithEmbedKey(
                                video.title || 'YouTube Video', embedKeyForWrap,
                            ) ?? undefined;
                        }

                        if (encEmbedContent && encEmbedType) {
                            inspirationEmbedForSync = {
                                embed_id: reusedEmbedId,
                                encrypted_content: encEmbedContent,
                                encrypted_type: encEmbedType,
                                encrypted_text_preview: encEmbedPreview || '',
                                embed_keys: embedKeysForStorage,
                            };
                            console.info(
                                `[ActiveChat] Prepared inspiration embed ${reusedEmbedId} for cross-device sync`,
                            );
                        }
                    } catch (embedSyncErr) {
                        // Non-fatal: second device falls back to request_embed
                        console.warn(
                            '[ActiveChat] Failed to prepare embed for cross-device sync (non-fatal):',
                            embedSyncErr,
                        );
                    }
                } catch (keyErr) {
                    // Non-fatal: the embed is stored locally and works on this device.
                    // Other devices can use the request_embed safety net to get the key.
                    console.error(
                        '[ActiveChat] Failed to create chat key wrapper for inspiration embed (non-fatal):',
                        keyErr,
                    );
                }
            }

            // Mark the inspiration as opened — the carousel stays visible but the
            // next unopened entry becomes the default. Do this before navigating
            // so the banner updates immediately if the user goes back.
            const { dailyInspirationStore: inspirationStore } = await import('../stores/dailyInspirationStore');
            const { markInspirationOpenedInIndexedDB, markInspirationOpenedOnAPI } = await import('../services/dailyInspirationDB');

            // Hashed chat ID used as the opened_chat_id reference
            const openedChatId = chatId;

            // Update the Svelte store immediately (optimistic update)
            inspirationStore.markOpened(inspiration.inspiration_id, openedChatId);

            // Persist to IndexedDB and API in the background (non-blocking, non-fatal)
            markInspirationOpenedInIndexedDB(inspiration.inspiration_id, openedChatId).catch((err: unknown) => {
                console.error('[ActiveChat] Failed to mark inspiration opened in IndexedDB:', err);
            });
            markInspirationOpenedOnAPI(
                inspiration.inspiration_id,
                openedChatId,
                inspiration.video?.youtube_id,
            ).catch((err: unknown) => {
                console.error('[ActiveChat] Failed to mark inspiration opened on API:', err);
            });

            // ── Follow-up suggestions ──────────────────────────────────────────
            // Use LLM-generated follow-up suggestions stored on the inspiration object.
            // These are generated at inspiration creation time (same LLM call as
            // assistant_response), making them specific to the actual topic.
            // Falls back to a humanised title if the inspiration predates this feature
            // or if the LLM failed to generate suggestions.
            let encryptedFollowUpSuggestions: string | null = null;
            try {
                const { encryptWithChatKey: encryptSuggestions } = await import('../services/cryptoService');

                // Use LLM suggestions if available; otherwise fall back to a humanised title.
                const llmSuggestions = inspiration.follow_up_suggestions;
                const hasSuggestions = Array.isArray(llmSuggestions) && llmSuggestions.length > 0;
                const topicLabel = inspiration.title
                    ?? (inspiration.phrase ? inspiration.phrase.split('.')[0] : null)
                    ?? inspiration.category.replace(/_/g, ' ');
                const rawSuggestions: string[] = hasSuggestions
                    ? llmSuggestions!
                    : [
                        `Tell me more about ${topicLabel}`,
                        `What are the practical implications of this?`,
                        `What should I explore next about ${topicLabel}?`,
                    ];

                if (!hasSuggestions) {
                    console.debug(
                        '[ActiveChat] No LLM follow-up suggestions on inspiration — using fallback for:',
                        inspiration.inspiration_id,
                    );
                }

                const encBlob = await encryptSuggestions(
                    JSON.stringify(rawSuggestions),
                    chatKey,
                );
                if (encBlob) {
                    encryptedFollowUpSuggestions = encBlob;
                    const chatWithSuggestions = {
                        ...(newChat as import('../types/chat').Chat),
                        encrypted_follow_up_request_suggestions: encBlob,
                    };
                    await chatDB.updateChat(chatWithSuggestions);
                    // Make suggestions available in the UI immediately
                    followUpSuggestions = rawSuggestions;
                    console.debug(
                        '[ActiveChat] Stored follow-up suggestions for inspiration chat:',
                        rawSuggestions.length,
                        hasSuggestions ? '(LLM-generated)' : '(fallback)',
                    );
                }
            } catch (suggErr) {
                // Non-fatal — suggestions are a nice-to-have
                console.warn('[ActiveChat] Failed to store follow-up suggestions for inspiration chat:', suggErr);
            }

            // Navigate to the new chat (same pattern as handleResumeLastChat)
            phasedSyncState.markInitialChatLoaded();
            activeChatStore.setActiveChat(chatId);
            await loadChat(newChat as import('../types/chat').Chat);

            // Notify Chats.svelte sidebar so the new chat appears immediately.
            // chatListCache.upsertChat inserts the chat at the top of the cached list,
            // then localChatListChanged triggers Chats.svelte to re-render.
            chatListCache.upsertChat(newChat as import('../types/chat').Chat);
            window.dispatchEvent(new CustomEvent('localChatListChanged', {
                bubbles: true,
                composed: true,
                detail: { reason: 'inspiration_chat_created', chatId },
            }));
            window.dispatchEvent(new CustomEvent('globalChatSelected', {
                bubbles: true,
                composed: true,
                detail: { chatId },
            }));

            // ── Cross-device sync ────────────────────────────────────────────────
            // The chat was created locally (IndexedDB only). Sync it to the server
            // so that other devices can see it via phased sync or the broadcast.
            // 1. Update last_opened on the server (resume card on other devices).
            // 2. Send the encrypted chat + message for cross-device broadcast.
            try {
                const { encryptChatKeyWithMasterKey } = await import('../services/cryptoService');
                const encryptedChatKey = await encryptChatKeyWithMasterKey(chatKey);

                // Notify server of the active chat (updates last_opened in Redis + Directus)
                chatSyncService.sendSetActiveChat(chatId);

                // Sync the full chat + first message for cross-device visibility.
                // Include the inspiration embed data + keys so other devices can
                // store and decrypt the embed immediately without a Directus round-trip.
                if (encryptedChatKey) {
                    chatSyncService.sendSyncInspirationChat(
                        chatId,
                        messageId,
                        messageContent,
                        inspiration.category,
                        encryptedTitle,
                        encryptedCategory,
                        encryptedContent,
                        encryptedChatKey,
                        now,
                        encryptedFollowUpSuggestions ?? undefined,
                        inspirationEmbedForSync,
                    );
                } else {
                    console.warn('[ActiveChat] Could not encrypt chat key for inspiration chat sync — chat will sync on next phased sync');
                }
            } catch (syncErr) {
                // Non-fatal — chat still works locally, will sync eventually
                console.warn('[ActiveChat] Failed to sync inspiration chat to server:', syncErr);
            }

        } catch (err) {
            console.error('[ActiveChat] Error creating chat from inspiration:', err);
        }
    }

    /**
     * Handler for clicking the video embed area inside a Daily Inspiration banner.
     *
     * Opens the video directly in the VideoEmbedFullscreen viewer without first
     * creating a chat. Works for both authenticated users (embed_id from persistInspirations)
     * and unauthenticated users (synthetic tmp- embed key, falls back to inline decodedContent).
     */
    async function handleInspirationEmbedFullscreen(inspiration: DailyInspiration) {
        if (!inspiration.video?.youtube_id) {
            console.debug('[ActiveChat] Inspiration has no video, ignoring embed fullscreen request');
            return;
        }

        const storedEmbedId = inspiration.embed_id;

        // For unauthenticated users (or before persistInspirations has run), embed_id is null.
        // In that case we use a synthetic temporary key based on the youtube_id so
        // handleEmbedFullscreen can still open the video — it will fall back to the
        // inline decodedContent we provide below (resolveEmbed returns null for tmp- keys,
        // which is the intended fallback path).
        const embedId = storedEmbedId
            ? `embed:${storedEmbedId}`
            : `embed:tmp-${inspiration.video.youtube_id}`;
        const video = inspiration.video;
        const videoId = video.youtube_id;
        const videoUrl = `https://www.youtube.com/watch?v=${videoId}`;

        // Format duration if available
        let durationFormatted: string | undefined;
        if (video.duration_seconds != null) {
            const mins = Math.floor(video.duration_seconds / 60);
            const secs = video.duration_seconds % 60;
            durationFormatted = `${mins}:${secs.toString().padStart(2, '0')}`;
        }

        const syntheticEvent = new CustomEvent('embedfullscreen', {
            detail: {
                embedId,
                embedData: {
                    embed_id: storedEmbedId,
                    type: 'videos-video',
                    status: 'finished',
                },
                // Pass decodedContent inline as a fallback — handleEmbedFullscreen will
                // re-load from EmbedStore using the real embedId for up-to-date data.
                decodedContent: {
                    url: videoUrl,
                    video_id: videoId,
                    title: video.title ?? undefined,
                    channel_name: video.channel_name ?? undefined,
                    thumbnail: video.thumbnail_url ?? undefined,
                    duration_seconds: video.duration_seconds ?? undefined,
                    duration_formatted: durationFormatted,
                    view_count: video.view_count ?? undefined,
                    published_at: video.published_at ?? undefined,
                },
                embedType: 'videos-video',
                attrs: {
                    url: videoUrl,
                    title: video.title ?? undefined,
                    videoId,
                },
            },
        });

        console.debug('[ActiveChat] Opening inspiration video in fullscreen:', videoId, 'embedId:', embedId);
        await handleEmbedFullscreen(syntheticEvent as CustomEvent);
    }

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
     * Handler for the reminders bell button click.
     * Opens the settings menu and navigates to the reminders management page.
     */
    async function handleOpenReminders() {
        console.debug("[ActiveChat] Reminders button clicked, opening reminder settings");

        // Store chat context so SettingsReminders can render the chat preview
        if (currentChat?.chat_id) {
            activeChatStore.setActiveChat(currentChat.chat_id);
            reminderContext.set({ chatId: currentChat.chat_id });
        }

        settingsMenuVisible.set(true);
        panelState.openSettings();

        await tick();
        await new Promise(resolve => setTimeout(resolve, 100));

        settingsDeepLink.set('app_store/reminder/create');
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

    async function handleToggleDebugMode() {
        if (!isAdminUser) return;
        await chatDebugStore.toggle({ chatId: currentChat?.chat_id });
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

    // Keep debug chat report aligned with the currently opened chat.
    // When debug mode is active and the user changes chats, trigger a fresh window.debug.chat run.
    $effect(() => {
        const activeChatId = currentChat?.chat_id ?? null;
        const debugActive = $chatDebugStore.rawTextMode;

        if (!debugActive || !isAdminUser) {
            lastDebugChatInspectionId = null;
            return;
        }

        if (!activeChatId) return;
        if (lastDebugChatInspectionId === activeChatId) return;

        lastDebugChatInspectionId = activeChatId;
        void chatDebugStore.runChatDebug(activeChatId);
    });

    // Update handler for chat updates to be more selective
    async function handleChatUpdated(event: CustomEvent) {
        const detail = event.detail as ChatUpdatedDetail;
        const incomingChatId = detail.chat_id;
        const incomingChatMetadata = detail.chat as Chat | undefined;
        const incomingMessages = detail.messages as ChatMessageModel[] | undefined;
        console.debug(`[ActiveChat] handleChatUpdated: Event for chat_id: ${incomingChatId}. Current active chat_id: ${currentChat?.chat_id}. Event detail:`, detail);

        // ─── Welcome screen carousel/resume card updates ─────────────────────
        // When on the welcome screen (no active chat), metadata and message
        // changes from other devices should refresh the carousel and resume card.
        if (showWelcome && !currentChat) {
            const carouselRelevantTypes = ['title_updated', 'metadata_updated', 'post_processing_metadata', 'message_added', 'draft', 'draft_deleted'];
            if (incomingChatId && carouselRelevantTypes.includes(detail.type || '')) {
                carouselInvalidationCounter++;
            }
            // Re-decrypt resume card if its title/category/icon changed
            if (resumeChatData?.chat_id === incomingChatId &&
                (detail.type === 'title_updated' || detail.type === 'metadata_updated' || detail.type === 'post_processing_metadata')) {
                loadResumeChatFromDB(resumeChatData.chat_id);
            }
            // Don't return — fall through only if there's a currentChat
        }

        if (!incomingChatId || !currentChat || currentChat.chat_id !== incomingChatId) {
            console.warn('[ActiveChat] handleChatUpdated: Event for non-active chat, no current chat, or chat_id mismatch. Current:', currentChat?.chat_id, 'Event chat_id:', incomingChatId, 'Ignoring.');
            return;
        }

        // RACE CONDITION GUARD: During the async gap in loadChat() (between setting currentChat
        // and setting currentMessages), currentMessages may still hold messages from the PREVIOUS
        // chat. If we process a chatUpdated event now, we'd append/merge the new chat's messages
        // into the old chat's message array — causing cross-chat message leaks (e.g. demo-for-everyone
        // messages appearing inside a real chat). Detect this by checking if currentMessages[0]
        // belongs to a different chat than currentChat.
        if (currentMessages.length > 0 && detail.newMessage) {
            const firstMsgChatId = currentMessages[0]?.chat_id;
            if (firstMsgChatId && firstMsgChatId !== currentChat.chat_id) {
                console.warn(`[ActiveChat] handleChatUpdated: currentMessages belongs to ${firstMsgChatId} but currentChat is ${currentChat.chat_id} — loadChat async gap detected. Skipping newMessage append to prevent cross-chat message leak.`);
                return;
            }
        }

        console.debug('[ActiveChat] handleChatUpdated: Processing event for active chat.');

        // ─── Chat Header: decrypt & display title/category/icon when they arrive ───────
        // When we sent a message for a new chat, isNewChatGeneratingTitle is true and the
        // chat header shows a "Generating title..." placeholder. Once the server sends the
        // encrypted title (title_updated) or category/icon (metadata_updated), decrypt and
        // populate the header — then hide the placeholder.
        // ─── Incognito chat header: apply plaintext metadata directly ────────────────
        // Incognito chats don't go through the encryption post-processing pipeline,
        // so title/category/icon arrive as plaintext fields in the chatUpdated event
        // dispatched by chatSyncServiceHandlersAI after ai_typing_started.
        if (isNewChatGeneratingTitle && currentChat?.is_incognito && incomingChatMetadata && detail.type === 'metadata_updated') {
            const incognitoCategory = incomingChatMetadata.category || null;
            const incognitoTitle = (typeof incomingChatMetadata.title === 'string' ? incomingChatMetadata.title : '') || '';
            const rawIncognitoIcon = incomingChatMetadata.icon || null;
            const incognitoIcon = rawIncognitoIcon ? (rawIncognitoIcon.split(',')[0]?.trim() || null) : null;
            if (incognitoCategory) {
                activeChatDecryptedTitle = incognitoTitle;
                activeChatDecryptedCategory = incognitoCategory;
                activeChatDecryptedIcon = incognitoIcon;
                isNewChatGeneratingTitle = false;
                console.info('[ActiveChat] handleChatUpdated: Incognito chat header ready (plaintext):', incognitoTitle, incognitoCategory, incognitoIcon);
                if (chatHistoryRef) {
                    setTimeout(() => {
                        chatHistoryRef?.triggerNewChatUserMessageScroll();
                    }, 3000);
                }
            }
        }

        if (isNewChatGeneratingTitle && !currentChat?.is_incognito && incomingChatMetadata && (detail.type === 'title_updated' || detail.type === 'metadata_updated')) {
            const chatToDecrypt = incomingChatMetadata;
            console.debug(`[ActiveChat] handleChatUpdated: Decrypting chat header metadata (type=${detail.type})`, chatToDecrypt);
            try {
                const { decryptWithChatKey, decryptChatKeyWithMasterKey } = await import('../services/cryptoService');
                // Safe key retrieval: never generate a new key for an existing chat.
                // 1. Try in-memory cache first (covers the common case on the sender device).
                // 2. If absent but encrypted_chat_key is present, decrypt it with the master key.
                // 3. Only fall back to getOrGenerateChatKey if there truly is no stored key
                //    (should not happen here, but avoids a silent null dereference).
                let chatKey: Uint8Array | null = await chatKeyManager.getKey(incomingChatId);
                if (!chatKey && chatToDecrypt.encrypted_chat_key) {
                    try {
                        const k = await decryptChatKeyWithMasterKey(chatToDecrypt.encrypted_chat_key);
                        if (k) { chatKey = k; chatDB.setChatKey(incomingChatId, k); }
                    } catch (keyErr) {
                        console.error(`[ActiveChat] handleChatUpdated: Failed to decrypt chat key from encrypted_chat_key: chat_id=${incomingChatId} field=encrypted_chat_key`, keyErr);
                    }
                }
                if (!chatKey) {
                    // Last resort: try chatKeyManager async load from IDB
                    chatKey = await chatKeyManager.getKey(incomingChatId);
                    if (!chatKey) {
                        console.warn('[ActiveChat] handleChatUpdated: No chat key available for', incomingChatId, '— skipping header decryption');
                    }
                }
                if (chatKey) {
                    let decryptedTitle = activeChatDecryptedTitle;
                    let decryptedCategory = activeChatDecryptedCategory;
                    let decryptedIcon = activeChatDecryptedIcon;

                    if (chatToDecrypt.encrypted_title) {
                        try { decryptedTitle = await decryptWithChatKey(chatToDecrypt.encrypted_title, chatKey, { chatId: incomingChatId, fieldName: 'encrypted_title' }) ?? ''; } catch { /* keep previous */ }
                    }
                    if (chatToDecrypt.encrypted_category) {
                        try { decryptedCategory = await decryptWithChatKey(chatToDecrypt.encrypted_category, chatKey, { chatId: incomingChatId, fieldName: 'encrypted_category' }); } catch { /* keep previous */ }
                    }
                    if (chatToDecrypt.encrypted_icon) {
                        try { decryptedIcon = await decryptWithChatKey(chatToDecrypt.encrypted_icon, chatKey, { chatId: incomingChatId, fieldName: 'encrypted_icon' }); } catch { /* keep previous */ }
                    }

                    activeChatDecryptedTitle = decryptedTitle ?? '';
                    activeChatDecryptedCategory = decryptedCategory;
                    activeChatDecryptedIcon = decryptedIcon;

                    // Once we have at least a title, reveal the full card and hide the placeholder.
                    if (activeChatDecryptedTitle && activeChatDecryptedCategory) {
                        isNewChatGeneratingTitle = false;
                        console.info('[ActiveChat] Chat header ready:', activeChatDecryptedTitle, activeChatDecryptedCategory, activeChatDecryptedIcon);
                        // Scroll the user message to the top of the viewport 3 s after the
                        // title/category/icon are visible.  This gives the user time to see
                        // the "Creating new chat…" → generated-title transition before the
                        // view scrolls down to make room for the AI response.
                        if (chatHistoryRef) {
                            setTimeout(() => {
                                chatHistoryRef?.triggerNewChatUserMessageScroll();
                            }, 3000);
                        }
                    }
                }
            } catch (err) {
                console.error(`[ActiveChat] handleChatUpdated: Failed to decrypt chat header metadata: chat_id=${incomingChatId}`, err);
            }
        }

        // ─── Chat Header: update summary + title when post-processing completes ────
        // Summary and updated title arrive via post_processing_metadata after the main
        // header is already shown. Decrypt and display them immediately so the header
        // updates live without needing to close and reopen the chat.
        if (detail.type === 'post_processing_metadata' && (incomingChatMetadata?.encrypted_chat_summary || incomingChatMetadata?.encrypted_title)) {
            try {
                const { decryptWithChatKey, decryptChatKeyWithMasterKey } = await import('../services/cryptoService');
                // Safe key retrieval — same pattern as the title_updated handler above.
                let postProcKey: Uint8Array | null = await chatKeyManager.getKey(incomingChatId);
                if (!postProcKey && incomingChatMetadata.encrypted_chat_key) {
                    try {
                        const k = await decryptChatKeyWithMasterKey(incomingChatMetadata.encrypted_chat_key);
                        if (k) { postProcKey = k; chatDB.setChatKey(incomingChatId, k); }
                    } catch (keyErr) {
                        console.error(`[ActiveChat] handleChatUpdated: Failed to decrypt chat key for post-processing: chat_id=${incomingChatId} field=encrypted_chat_key`, keyErr);
                    }
                }
                if (!postProcKey) {
                    postProcKey = await chatKeyManager.getKey(incomingChatId);
                    if (!postProcKey) {
                        console.warn('[ActiveChat] handleChatUpdated: No chat key for post-processing decrypt of', incomingChatId);
                    }
                }
                if (postProcKey) {
                    // Decrypt summary if present
                    if (incomingChatMetadata.encrypted_chat_summary) {
                        const decryptedSummary = await decryptWithChatKey(incomingChatMetadata.encrypted_chat_summary, postProcKey, { chatId: incomingChatId, fieldName: 'encrypted_chat_summary' });
                        if (decryptedSummary) {
                            activeChatDecryptedSummary = decryptedSummary;
                            console.debug('[ActiveChat] Chat header summary updated:', decryptedSummary.substring(0, 60) + '...');
                        }
                    }
                    // OPE-265: Decrypt updated title if post-processing detected conversation drift
                    if (incomingChatMetadata.encrypted_title) {
                        const decryptedTitle = await decryptWithChatKey(incomingChatMetadata.encrypted_title, postProcKey, { chatId: incomingChatId, fieldName: 'encrypted_title' });
                        if (decryptedTitle) {
                            activeChatDecryptedTitle = decryptedTitle;
                            console.debug('[ActiveChat] Chat header title updated from post-processing:', decryptedTitle);
                        }
                    }
                }
            } catch (err) {
                console.error(`[ActiveChat] handleChatUpdated: Failed to decrypt post-processing metadata: chat_id=${incomingChatId}`, err);
            }
        }

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
            //
            // Guard: skip IDB reload if in-flight messages are active (demo→real conversion).
            // The IDB contains demo history alongside the new message — reloading would cause
            // demo messages to bleed into the real conversation. The streaming path will handle
            // message updates until all messages settle to 'synced'.
            const hasActiveInFlight = currentMessages.some(m =>
                m.chat_id === currentChat?.chat_id && (
                    m.status === 'streaming' ||
                    m.status === 'sending' ||
                    m.status === 'processing'
                )
            );
            if (hasActiveInFlight) {
                console.debug(`[ActiveChat] handleChatUpdated: messagesUpdated=true but ${currentMessages.filter(m => m.status === 'streaming' || m.status === 'sending' || m.status === 'processing').length} in-flight message(s) present — skipping IDB reload to prevent demo history bleed-through.`);
                // Still update chat metadata if provided
                if (detail.chat) {
                    currentChat = { ...currentChat, ...detail.chat } as typeof currentChat;
                }
                return;
            }
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
     export async function loadChat(chat: Chat, options?: { scrollToLatestResponse?: boolean; scrollToTop?: boolean }) {
         // RACE CONDITION GUARD: Increment generation counter so concurrent/stale calls bail out.
         // Between setting currentChat (immediate) and setting currentMessages (after async DB reads),
         // chatUpdated events can see the new currentChat but operate on the old currentMessages.
         // On slow devices (iPad), this window can be 100-500ms, long enough for sync events to
         // append messages from the wrong chat. The generation counter prevents stale completions
         // from overwriting currentMessages after a newer loadChat has started.
         const thisLoadGeneration = ++loadChatGeneration;

         // Clear any active processing phase indicator from the previous chat
         clearProcessingPhase();
         // Reset the chat header state when switching to any chat.
         // For new chats, handleSendMessage will set isNewChatGeneratingTitle=true.
         // For existing chats, we decrypt title/category/icon below (after currentChat is set).
         //
         // CRITICAL: Skip resetChatHeaderState when loadChat is called for the already-active chat
         // while the new-chat header is still showing (isNewChatGeneratingTitle=true or streaming
         // messages are in flight). This happens because sendHandlers.ts sets
         // draftEditorUIState.newlyCreatedChatIdToSelect which causes Chats.svelte to call
         // handleChatClick → dispatch chatSelected → +page.svelte calls loadChat() — all
         // while the AI response is still streaming. Without this guard, resetChatHeaderState()
         // clears isNewChatGeneratingTitle and the banner disappears mid-stream.
         const isSameActiveChat = chat.chat_id === currentChat?.chat_id;
         const isNewChatHeaderActive = isNewChatGeneratingTitle || isNewChatCreditsError;
         const hasStreamingMessages = currentMessages.some(m => m.status === 'streaming');
         // When loadChat re-runs for the already-active chat (e.g. after closing a fullscreen
         // embed that restored the URL hash, or any hashchange echo), the decrypted header
         // fields already reflect this chat. Resetting them would blank the title/summary
         // until the async decrypt branch below refills them — a visible flicker. Skip the
         // reset whenever the header is already valid for this chat.
         const headerAlreadyLoadedForSameChat = isSameActiveChat
             && !!activeChatDecryptedTitle
             && !!activeChatDecryptedCategory;
         if (!(isSameActiveChat && (isNewChatHeaderActive || hasStreamingMessages || headerAlreadyLoadedForSameChat))) {
             resetChatHeaderState();
         } else {
             console.debug('[ActiveChat] loadChat: skipping resetChatHeaderState — same chat, header/streaming active or header already loaded', {
                 chat_id: chat.chat_id,
                 isNewChatGeneratingTitle,
                 isNewChatCreditsError,
                 hasStreamingMessages,
                 headerAlreadyLoadedForSameChat,
             });
         }

         // Ensure the chatNavigationStore has up-to-date prev/next state even when
         // Chats.svelte (the sidebar) has never been opened. On mobile the sidebar
         // starts closed, so the store would otherwise have hasPrev=false/hasNext=false
         // until the user opens the sidebar at least once.
         updateNavFromCache(chat.chat_id);

         // Load this chat's highlights from IndexedDB into the in-memory store
         // so the ChatHeader pill + in-message overlays render without waiting
         // for a WS round-trip. Fire-and-forget — highlight render isn't on the
         // critical path for opening the chat.
         void (async () => {
             try {
                 const { getHighlightsForChat } = await import('../services/db/messageHighlights');
                 const { loadHighlightsForChat } = await import('../stores/messageHighlightsStore');
                 const rows = await getHighlightsForChat(chatDB, chat.chat_id);
                 loadHighlightsForChat(chat.chat_id, rows);
             } catch (err) {
                 console.warn('[ActiveChat] Failed to load message_highlights for chat', chat.chat_id, err);
             }
         })();

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
        if (showWikiFullscreen) {
            showWikiFullscreen = false;
            wikiFullscreenData = null;
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

         // ─── Chat Header: restore title/category/icon for all chat types ────────────────
         // Universal header restoration: handles public/demo, incognito, and regular chats.
         // isNewChatGeneratingTitle stays false here — it is only set in handleSendMessage
         // when the user just sent the first message of a brand-new chat.
         //
         // Data sources by chat type:
         //   - Public/demo chats: plaintext chat.title, chat.category, chat.icon (comma-separated)
         //   - Incognito chats:   plaintext chat.category, chat.icon (title may be absent on new ones)
         //   - Regular chats:     decrypt encrypted_title, encrypted_category, encrypted_icon;
         //                        also accept plaintext category/icon as fallback for older chats
         //
         // IMPORTANT: freshChat from IndexedDB may be missing encrypted_title/encrypted_category
         // when the chat was only partially synced (e.g. Phase 1 / load-more chats are built
         // in-memory from the server payload and never written to IndexedDB — so chatDB.getChat
         // returns a stale or partial record).  In that case the original `chat` argument from
         // the sidebar still has the full encrypted metadata from the server.  We merge them so
         // the header always has the best available data without touching currentChat (messages
         // and version counters must still come from the DB).
         const chatForHeader = currentChat
             ? {
                   ...currentChat,
                   encrypted_title: currentChat.encrypted_title ?? chat.encrypted_title,
                   encrypted_category: currentChat.encrypted_category ?? chat.encrypted_category,
                   encrypted_icon: currentChat.encrypted_icon ?? chat.encrypted_icon,
                   encrypted_chat_summary: currentChat.encrypted_chat_summary ?? chat.encrypted_chat_summary,
                   title: currentChat.title ?? chat.title,
                   category: currentChat.category ?? chat.category,
                   icon: currentChat.icon ?? chat.icon,
               }
             : currentChat;
         if (chatForHeader) {
              if (isPublicChat(chatForHeader.chat_id)) {
                  // Public chats (demo/legal/community): all metadata is cleartext
                  const t = typeof chatForHeader.title === 'string' ? chatForHeader.title : '';
                  const c = chatForHeader.category || null;
                  // icon is stored as a comma-separated string — use the first icon name only
                  const rawIcon = chatForHeader.icon || null;
                  const ic = rawIcon ? (rawIcon.split(',')[0]?.trim() || null) : null;
                  // summary is also cleartext for public chats
                  const s = chatForHeader.chat_summary || null;
                  if (t && c) {
                      activeChatDecryptedTitle = t;
                      activeChatDecryptedCategory = c;
                      activeChatDecryptedIcon = ic;
                      activeChatDecryptedSummary = s;
                      console.debug('[ActiveChat] loadChat: Restored chat header for public chat:', t, c, ic);
                  }
              } else if (chatForHeader.is_incognito) {
                  // Incognito chats: category and icon are plaintext; title may be blank on new ones
                  const t = typeof chatForHeader.title === 'string' ? chatForHeader.title : '';
                  const c = chatForHeader.category || null;
                  const rawIcon = chatForHeader.icon || null;
                  const ic = rawIcon ? (rawIcon.split(',')[0]?.trim() || null) : null;
                  // Show header whenever we have at least a category (title can be empty early on)
                  if (c) {
                      activeChatDecryptedTitle = t;
                      activeChatDecryptedCategory = c;
                      activeChatDecryptedIcon = ic;
                      // Incognito chats do not persist a summary
                      activeChatDecryptedSummary = null;
                      console.debug('[ActiveChat] loadChat: Restored chat header for incognito chat:', t, c, ic);
                  }
              } else {
                  // Regular encrypted chats: decrypt encrypted fields.
                  // We no longer require title_v > 0 because some chats may have category/icon
                  // set even when title_v is missing or 0 (e.g. received via older sync path).
                  // Try to decrypt whenever any encrypted metadata (or plaintext fallback) exists.
                  const hasEncryptedTitle = !!chatForHeader.encrypted_title;
                  const hasEncryptedCategory = !!chatForHeader.encrypted_category;
                  const hasPlaintextCategory = !!chatForHeader.category;
                  if (hasEncryptedTitle || hasEncryptedCategory || hasPlaintextCategory) {
                      try {
                          const { decryptWithChatKey, decryptChatKeyWithMasterKey } = await import('../services/cryptoService');
                          // Safe key retrieval — critical for secondary devices that receive chats
                          // via phased sync (where the in-memory cache may be cold).
                          //
                          // NEVER call getOrGenerateChatKey() directly on an existing chat: if the
                          // cache is cold it silently generates a NEW random key, causing every
                          // encrypted header field to decrypt to null → chat header stays hidden.
                          //
                          // Correct order:
                          //   1. Check in-memory cache (fast, covers warm-cache case).
                          //   2. If absent but encrypted_chat_key present, decrypt it with the
                          //      master key and populate the cache.
                          //   3. Only generate a new key if there is genuinely no stored key
                          //      (brand-new chat created on this device before server confirmed).
                          let chatKey: Uint8Array | null = await chatKeyManager.getKey(chatForHeader.chat_id);
                          if (!chatKey && chatForHeader.encrypted_chat_key) {
                              try {
                                  const k = await decryptChatKeyWithMasterKey(chatForHeader.encrypted_chat_key);
                                  if (k) {
                                      chatKey = k;
                                      chatDB.setChatKey(chatForHeader.chat_id, k);
                                      console.debug('[ActiveChat] loadChat: Recovered chat key from encrypted_chat_key for', chatForHeader.chat_id);
                                  }
                              } catch (keyErr) {
                                  console.error(`[ActiveChat] loadChat: Failed to decrypt chat key from encrypted_chat_key: chat_id=${chatForHeader.chat_id} field=encrypted_chat_key`, keyErr);
                              }
                          }
                          if (!chatKey) {
                              // Try async load from IDB via ChatKeyManager
                              chatKey = await chatKeyManager.getKey(chatForHeader.chat_id);
                              if (!chatKey) {
                                  console.warn('[ActiveChat] loadChat: No chat key available for', chatForHeader.chat_id, '— header will show placeholders');
                              }
                          }
                          if (chatKey) {
                              let t = '';
                              let c: string | null = null;
                              let ic: string | null = null;
                              let s: string | null = null;
                              if (chatForHeader.encrypted_title) {
                                  try { t = await decryptWithChatKey(chatForHeader.encrypted_title, chatKey, { chatId: chatForHeader.chat_id, fieldName: 'encrypted_title' }) ?? ''; } catch { /* keep blank */ }
                              }
                              if (chatForHeader.encrypted_category) {
                                  try { c = await decryptWithChatKey(chatForHeader.encrypted_category, chatKey, { chatId: chatForHeader.chat_id, fieldName: 'encrypted_category' }); } catch { /* keep null */ }
                              } else if (chatForHeader.category) {
                                  // Fallback: plaintext category (older chats or partial sync)
                                  c = chatForHeader.category;
                              }
                              if (chatForHeader.encrypted_icon) {
                                  try { ic = await decryptWithChatKey(chatForHeader.encrypted_icon, chatKey, { chatId: chatForHeader.chat_id, fieldName: 'encrypted_icon' }); } catch { /* keep null */ }
                              } else if (chatForHeader.icon) {
                                  // Fallback: plaintext icon (older chats or partial sync)
                                  ic = chatForHeader.icon.split(',')[0]?.trim() || null;
                              }
                              if (chatForHeader.encrypted_chat_summary) {
                                  try { s = await decryptWithChatKey(chatForHeader.encrypted_chat_summary, chatKey, { chatId: chatForHeader.chat_id, fieldName: 'encrypted_chat_summary' }); } catch { /* keep null */ }
                              }
                              if (t && c) {
                                  activeChatDecryptedTitle = t;
                                  activeChatDecryptedCategory = c;
                                  activeChatDecryptedIcon = ic;
                                  activeChatDecryptedSummary = s;
                                  console.debug('[ActiveChat] loadChat: Restored chat header for existing chat:', t, c, ic);
                              }
                          }
                      } catch (err) {
                          console.error(`[ActiveChat] loadChat: Failed to decrypt header for existing chat: chat_id=${chatForHeader.chat_id}`, err);
                      }
                  }
              }
         }

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
        
        // CRITICAL: Reset thinking state when switching chats.
        // If the user navigated away while a thinking stream was in progress for this chat,
        // the thinkingContentByTask map still holds the stale entry with isStreaming=true.
        // handleAiThinkingComplete is ignored for background chats (different chat_id), so
        // without this reset the thinking block keeps showing "Thinking..." indefinitely.
        // The thinking content is persisted to IndexedDB by chatSyncServiceHandlersAI and
        // will be loaded via msg.original_message?.thinking_content with isStreaming=false.
        thinkingContentByTask = new Map();
        thinkingPlaceholderMessageIds = new Set();
        
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

                // On-demand message loading: if this chat has no messages locally (metadata-only
                // or older chat not in IndexedDB), request messages from the server.
                // The server response (chat_content_batch_response) saves messages to IndexedDB
                // and dispatches chatUpdated with messagesUpdated=true, which triggers
                // handleChatUpdated to reload messages from IDB into the view.
                if (newMessages.length === 0 && currentChat.chat_id && !isPublicChat(currentChat.chat_id)) {
                    console.info(`[ActiveChat] No local messages for ${currentChat.chat_id} — requesting from server (on-demand loading)`);
                    try {
                        await chatSyncService.requestChatContentBatch_FOR_HANDLERS_ONLY([currentChat.chat_id]);
                    } catch (err) {
                        console.error(`[ActiveChat] Failed to request messages from server for ${currentChat.chat_id}:`, err);
                    }
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
            
            // CRITICAL: If currentMessages were set by handleSendMessage (demo→real chat conversion),
            // skip the DB reload. The DB now contains demo history messages alongside the new user
            // message, which would cause demo messages to bleed into the real conversation UI.
            //
            // Detection: currentMessages has only messages for THIS chat and at least one is still
            // in-flight (streaming/sending/processing). The original guard only fired when ALL messages
            // were in-flight, but after chat_message_confirmed the user message transitions to 'synced'
            // while the AI message is still 'streaming' — broadened to catch that race too.
            const allMessagesForThisChat = currentMessages.length > 0 &&
                currentMessages.every(m => m.chat_id === chat.chat_id);
            const hasAnyInFlight = currentMessages.some(m =>
                m.status === 'streaming' ||
                m.status === 'sending' ||
                m.status === 'processing'
            );
            // Only skip DB reload when messages are exclusively for this chat AND at least one
            // is still in-flight (the conversation is actively being created/streamed). This
            // prevents demo history bleed-through while allowing normal reloads of settled chats.
            if (allMessagesForThisChat && hasAnyInFlight) {
                console.info(`[ActiveChat] loadChat: currentMessages for ${chat.chat_id} has in-flight message(s) — skipping DB reload to prevent demo history bleed-through. Keeping handleSendMessage-initialised view.`);
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

        // ─── Restore credits error header and status for chats that were rejected ──
        // When switching back to a chat that had a credits rejection, the header state
        // was cleared by resetChatHeaderState(). Detect this by checking if:
        //   1) The chat has no title/category (backend never sent them due to rejection), AND
        //   2) There's a system/assistant message with waiting_for_user OR a role='system'
        //      message whose status was corrupted to 'delivered'/'synced' by phased sync.
        //
        // WHY STATUS CORRUPTION HAPPENS: Directus has no status column, so phased sync
        // messages arrive with no status and prepareMessagesForStorage() assigns 'delivered'
        // as the default. Previously this overwrote 'waiting_for_user' in IndexedDB (now
        // fixed in shouldUpdateMessage), but messages already stored with the wrong status
        // must be repaired here on load.
        //
        // Defensive fallback: also detect from a user message with waiting_for_user alone,
        // for cases where the system message's IDB save failed.
        if (!activeChatDecryptedTitle && !activeChatDecryptedCategory && newMessages.length > 0) {
            const hasSystemRejection = newMessages.some(m =>
                m.status === 'waiting_for_user' && (m.role === 'system' || m.role === 'assistant')
            );
            // Detect system messages whose status was corrupted by phased sync:
            // In a credits-rejected chat (no title/category), a role='system' message must
            // have been a rejection notice — restore its status to 'waiting_for_user'.
            const corruptedSystemMessages = !hasSystemRejection
                ? newMessages.filter(m =>
                    m.role === 'system' && (m.status === 'delivered' || m.status === 'synced')
                )
                : [];
            // Fallback: detect from user message alone (system message may be missing from IDB)
            const hasUserWaitingAlone = !hasSystemRejection && corruptedSystemMessages.length === 0 && newMessages.some(m =>
                m.status === 'waiting_for_user' && m.role === 'user'
            );
            if (hasSystemRejection || corruptedSystemMessages.length > 0 || hasUserWaitingAlone) {
                isNewChatCreditsError = true;
                // Repair corrupted system message statuses in memory (before assigning to currentMessages)
                // and persist the fix to IndexedDB so future reloads are also correct.
                if (corruptedSystemMessages.length > 0) {
                    for (const msg of corruptedSystemMessages) {
                        const idx = newMessages.findIndex(m => m.message_id === msg.message_id);
                        if (idx !== -1) {
                            newMessages[idx] = { ...newMessages[idx], status: 'waiting_for_user' };
                            chatDB.saveMessage(newMessages[idx]).catch(error => {
                                console.error(`[ActiveChat] loadChat: Failed to repair corrupted system message status for ${msg.message_id}:`, error);
                            });
                        }
                    }
                    console.debug('[ActiveChat] loadChat: Repaired corrupted system message status(es) to waiting_for_user', {
                        count: corruptedSystemMessages.length,
                        ids: corruptedSystemMessages.map(m => m.message_id)
                    });
                }
                console.debug('[ActiveChat] loadChat: Restored credits error header for chat with rejection message', {
                    hasSystemRejection,
                    corruptedSystemMessagesRepaired: corruptedSystemMessages.length,
                    hasUserWaitingAlone
                });
            }
        }

        // RACE CONDITION GUARD: If another loadChat() was called while we were awaiting
        // DB reads / decryption, this completion is stale — bail out to prevent overwriting
        // currentMessages with messages from the wrong chat.
        if (thisLoadGeneration !== loadChatGeneration) {
            console.warn(`[ActiveChat] loadChat: Stale completion for ${chat.chat_id} (gen ${thisLoadGeneration}, current ${loadChatGeneration}) — aborting to prevent message mixup`);
            return;
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

        // ─── Autoplay video deep link ────────────────────────────────────
        // Hash format: #chat-id=<id>&autoplay-video
        // Triggers fullscreen video playback for chats with video metadata.
        if (typeof window !== 'undefined' && window.location.hash.includes('autoplay-video') && currentChat?.chat_id) {
            const { openChatVideoFullscreen } = await import('../stores/chatVideoFullscreenStore');
            const { getVideoForLocale } = await import('../demo_chats/data/videos');
            const allChats = [...DEMO_CHATS, ...LEGAL_CHATS];
            const demoChat = allChats.find(c => c.chat_id === currentChat.chat_id);
            const videoKey = demoChat?.metadata?.video_key;
            const currentLocale = typeof $locale === 'string' ? $locale : 'en';
            const videoEntry = videoKey ? getVideoForLocale(videoKey, currentLocale) : null;
            const mp4Url = videoEntry?.mp4_url ?? demoChat?.metadata?.video_mp4_url;
            if (mp4Url) {
                openChatVideoFullscreen({
                    mp4Url,
                    title: activeChatDecryptedTitle || '',
                    chatId: currentChat.chat_id,
                });
                console.debug('[ActiveChat] Autoplay video triggered from deep link for chat:', currentChat.chat_id);
            }
        }

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
                // For example chats, use cleartext suggestions stored on chat object
                // ARCHITECTURE: Example chats use cleartext fields (not encrypted_* fields)
                try {
                    followUpSuggestions = JSON.parse(currentChat.follow_up_request_suggestions);
                    console.debug('[ActiveChat] Loaded example chat follow-up suggestions from cleartext:', $state.snapshot(followUpSuggestions));
                } catch (error) {
                    console.error('[ActiveChat] Failed to parse example chat follow-up suggestions:', error);
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
                const chatKey = chatKeyManager.getKeySync(currentChat.chat_id);
                if (!chatKey) {
                    console.debug('[ActiveChat] No chat key for follow-up suggestions in loadChat, skipping');
                    followUpSuggestions = [];
                } else {
                    const { decryptArrayWithChatKey } = await import('../services/cryptoService');
                    followUpSuggestions = await decryptArrayWithChatKey(currentChat.encrypted_follow_up_request_suggestions, chatKey) || [];
                }
                console.debug('[ActiveChat] Loaded follow-up suggestions from database:', $state.snapshot(followUpSuggestions));
            } catch (error) {
                console.error('[ActiveChat] Failed to load follow-up suggestions:', error);
                followUpSuggestions = [];
            }
        } else {
            followUpSuggestions = [];
        }



        if (chatHistoryRef) {
            // Update messages
            chatHistoryRef.updateMessages(currentMessages);
            
            // Wait for messages to render, then restore scroll position
            // After restoration, isAtBottom will be updated by handleScrollPositionUI
            // We set it explicitly here as a fallback, but handleScrollPositionUI will override
            // if it fires (which it should after scroll restoration completes)
            setTimeout(() => {
                // Ensure currentChat and chatHistoryRef are still valid
                // (might be null if component unmounted or database was deleted)
                if (!currentChat?.chat_id) {
                    console.warn('[ActiveChat] currentChat is null in setTimeout - cannot restore scroll position');
                    return;
                }
                if (!chatHistoryRef) {
                    console.debug('[ActiveChat] chatHistoryRef is null in setTimeout - component may have unmounted');
                    return;
                }

                // When navigating via ChatHeader arrows, always scroll to top so the
                // banner is visible (user expects to see the chat from the beginning).
                if (options?.scrollToTop) {
                    chatHistoryRef.scrollToTop();
                    console.debug('[ActiveChat] ChatHeader arrow navigation - scrolled to top');
                    setTimeout(() => {
                        isAtBottom = false;
                        console.debug('[ActiveChat] Set isAtBottom=false after ChatHeader arrow scrollToTop');
                    }, 200);
                // When coming from a background-chat notification, scroll to the top of the
                // latest assistant message so the user can read the reply from the beginning.
                } else if (options?.scrollToLatestResponse) {
                    chatHistoryRef.scrollToLatestAssistantMessage();
                    console.debug('[ActiveChat] Notification navigation - scrolled to top of latest assistant message');
                    setTimeout(() => {
                        isAtBottom = false;
                        console.debug('[ActiveChat] Set isAtBottom=false after scrolling to latest assistant message');
                    }, 200);
                // For public chats (demo + legal), always scroll to top (user hasn't read them yet)
                // Also scroll to top for shared chats on non-authenticated devices (they can't reuse scroll position)
                } else if (isPublicChat(currentChat.chat_id) || !$authStore.isAuthenticated) {
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
                    // No saved position - scroll to top so the user reads the conversation
                    // from the beginning (most natural for first-time opening a chat).
                    // If the user had previously scrolled to the bottom, last_visible_message_id
                    // would have been saved pointing to the last message, so the restoreScrollPosition
                    // branch above handles that case — this branch only fires on first open.
                    chatHistoryRef.scrollToTop();
                    // After scrolling to top, explicitly set isAtBottom to false
                    // handleScrollPositionUI will update it if the actual scroll position differs
                    setTimeout(() => {
                        isAtBottom = false;
                        console.debug('[ActiveChat] Set isAtBottom=false after scrolling to top (no saved position - first open)');
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
                const encryptedDraftPreview = currentChat?.encrypted_draft_preview;
                const draftVersion = currentChat?.draft_v;

                // Check if we have draft content via preview even if markdown is empty.
                // This happens when draft has only embeds (like images) that serialized to empty markdown
                // but the preview was correctly saved with "[Image]" token.
                const hasDraftPreview = !!(encryptedDraftPreview && encryptedDraftPreview.trim().length > 0);
                const hasEmptyMarkdownDraft = encryptedDraftMd === '' || encryptedDraftMd === null || encryptedDraftMd === undefined;

                if (hasEmptyMarkdownDraft && hasDraftPreview) {
                    // Draft has content (shown as "[Image]" in preview) but markdown is empty
                    // due to serialization returning "" for embeds without contentRef at save time.
                    // Load embeds from EmbedStore and reconstruct the TipTap JSON.
                    console.debug(`[ActiveChat] Draft has empty markdown but preview exists ("${encryptedDraftPreview}") - reconstructing from EmbedStore for chat ${currentChat.chat_id}`);
                    
                    try {
                        // Import EmbedStore and computeSHA256
                        const { embedStore } = await import('../services/embedStore');
                        const { computeSHA256 } = await import('../message_parsing/utils');
                        
                        const hashedChatId = await computeSHA256(currentChat.chat_id);
                        const chatEmbeds = await embedStore.getEmbedsByHashedChatId(hashedChatId);
                        
                        if (chatEmbeds && chatEmbeds.length > 0) {
                            // Reconstruct TipTap JSON with embed nodes
                            const embedNodes = [];
                            for (const embed of chatEmbeds) {
                                if (embed.embed_id) {
                                    embedNodes.push({
                                        type: 'embed',
                                        attrs: {
                                            type: embed.type || 'image',
                                            contentRef: `embed:${embed.embed_id}`,
                                        },
                                    });
                                }
                            }
                            
                            if (embedNodes.length > 0) {
                                const draftContentJSON = {
                                    type: 'doc',
                                    content: embedNodes,
                                };
                                
                                console.debug(`[ActiveChat] Reconstructed ${embedNodes.length} embed nodes from EmbedStore for chat ${currentChat.chat_id}`);
                                
                                if (messageInputFieldRef) {
                                    setTimeout(() => {
                                        messageInputFieldRef.setDraftContent(currentChat.chat_id, draftContentJSON, draftVersion || 1, false);
                                    }, 50);
                                }
                            } else {
                                // No embeds found in store, just set context
                                if (messageInputFieldRef) {
                                    setTimeout(() => {
                                        messageInputFieldRef.setCurrentChatContext(currentChat.chat_id, null, draftVersion || 0);
                                    }, 50);
                                }
                            }
                        } else {
                            // No embeds in store, just set context
                            console.debug(`[ActiveChat] No embeds found in EmbedStore for chat ${currentChat.chat_id}, setting context only`);
                            if (messageInputFieldRef) {
                                setTimeout(() => {
                                    messageInputFieldRef.setCurrentChatContext(currentChat.chat_id, null, draftVersion || 0);
                                }, 50);
                            }
                        }
                    } catch (error) {
                        console.error(`[ActiveChat] Error reconstructing draft from EmbedStore:`, error);
                        // Fallback: just set context
                        if (messageInputFieldRef) {
                            setTimeout(() => {
                                messageInputFieldRef.setCurrentChatContext(currentChat.chat_id, null, draftVersion || 0);
                            }, 50);
                        }
                    }
                } else if (encryptedDraftMd) {
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
            // OG image mode (?og=1): skip demo-for-everyone so the welcome screen stays visible
            if (typeof window !== 'undefined' && new URLSearchParams(window.location.search).get('og') === '1') {
                console.debug('[ActiveChat] Skipping loadDemoChat event - og=1 mode');
                return;
            }
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
        
        // Add event listener for embed fullscreen events (app-skill-use, code, video, etc.)
        // This fires via document.dispatchEvent so it works from both editor and read-only messages.
        const embedFullscreenHandler = (event: CustomEvent) => {
            handleEmbedFullscreen(event);
        };
        document.addEventListener('embedfullscreen', embedFullscreenHandler as EventListenerCallback);

        // Wikipedia fullscreen event — fired by WikiInlineLink when user clicks a wiki topic
        const wikiFullscreenHandler = (event: Event) => {
            handleWikiFullscreen(event as CustomEvent);
        };
        document.addEventListener('wikifullscreen', wikiFullscreenHandler as EventListenerCallback);

        // Add document-level listeners for image/PDF/recording fullscreen events.
        // These events bubble from TipTap node views (both editor and read-only messages).
        // The Svelte on:imagefullscreen / on:pdffullscreen / on:recordingfullscreen directives
        // on <MessageInput> only relay events from the editor context; the document listeners
        // here catch the same events when they originate from read-only chat messages.
        const imagefullscreenHandler = (event: Event) => {
            handleImageFullscreen(event as CustomEvent);
        };
        const pdffullscreenHandler = (event: Event) => {
            handlePdfFullscreen(event as CustomEvent);
        };
        const recordingfullscreenHandler = (event: Event) => {
            handleRecordingFullscreen(event as CustomEvent);
        };
        const pdfreadfullscreenHandler = (event: Event) => {
            handlePdfReadFullscreen(event as CustomEvent);
        };
        const pdfsearchfullscreenHandler = (event: Event) => {
            handlePdfSearchFullscreen(event as CustomEvent);
        };
        document.addEventListener('imagefullscreen', imagefullscreenHandler);
        document.addEventListener('pdffullscreen', pdffullscreenHandler);
        document.addEventListener('pdfreadfullscreen', pdfreadfullscreenHandler);
        document.addEventListener('pdfsearchfullscreen', pdfsearchfullscreenHandler);
        document.addEventListener('recordingfullscreen', recordingfullscreenHandler);
        
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
            // Clear the banner state immediately so the header banner disappears
            activeFocusId = null;
        };
        document.addEventListener('focusModeDeactivated', focusModeDeactivatedHandler as EventListenerCallback);
        
        // Listen for focus mode activation events from chatSyncService to update the banner
        const focusModeActivatedHandler = (event: CustomEvent) => {
            const { chat_id, focus_id } = event.detail || {};
            if (chat_id && focus_id && currentChat?.chat_id === chat_id) {
                console.debug('[ActiveChat] Focus mode activated, updating banner:', focus_id);
                activeFocusId = focus_id;
            }
        };
        chatSyncService.addEventListener('focusModeActivated', focusModeActivatedHandler as EventListenerCallback);
        
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
            // OG image mode (?og=1): skip demo-for-everyone so the welcome screen stays visible
            if (typeof window !== 'undefined' && new URLSearchParams(window.location.search).get('og') === '1') {
                console.debug('[ActiveChat] Skipping userLoggingOut handler - og=1 mode');
                return;
            }
            console.debug('[ActiveChat] Logout event received - clearing user chat and loading demo chat');
            
            try {
                // Clear current chat state immediately (before database deletion)
                // This ensures UI updates right away, even on mobile
                currentChat = null;
                currentMessages = [];
                followUpSuggestions = []; // Clear follow-up suggestions to prevent showing user responses
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
        
        // Listen for incognitoChatsDeleted event (when user disables incognito mode).
        // When incognito is disabled, all incognito chats are deleted from sessionStorage.
        // If the active chat is an incognito chat, we must reset the view to a new chat —
        // otherwise the incognito banner remains visible because currentChat.is_incognito is
        // still true. This handler is the authoritative reset in ActiveChat; the Chats.svelte
        // chatDeselected path is unreliable after re-login (selectedChatId may be null).
        const handleIncognitoChatsDeleted = () => {
            console.debug('[ActiveChat] incognitoChatsDeleted event received - resetting to new chat if needed');
            if (currentChat?.is_incognito) {
                console.debug('[ActiveChat] Current chat is incognito — clearing to new chat state after disable');
                handleNewChatClick();
            }
        };
        window.addEventListener('incognitoChatsDeleted', handleIncognitoChatsDeleted);
        
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
        
        // Add language change listener to reload public chats (demo + legal + example chats) when language changes
        const handleLanguageChange = async () => {
            try {
                // Refresh the welcome-screen recent-chats carousel so demo/example
                // chat titles re-translate to the new locale.
                carouselInvalidationCounter++;

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
                
                // Import example chat functions (static data, always available)
                const { getExampleChatMessages, isExampleChat } = await import('../demo_chats');

                // Check if this is an example chat (static, always available)
                if (isExampleChat(snapshotChat.chat_id)) {
                    console.debug('[ActiveChat] Language changed - reloading example chat:', snapshotChat.chat_id);

                    // Update the chat header title and summary to the new locale
                    const { getExampleChat } = await import('../demo_chats');
                    const translatedExampleChat = getExampleChat(snapshotChat.chat_id);
                    if (translatedExampleChat?.title) {
                        activeChatDecryptedTitle = translatedExampleChat.title;
                        activeChatDecryptedSummary = translatedExampleChat.chat_summary ?? null;
                    }

                    // Get the messages from the static example chat store (always available, no waiting needed)
                    const newMessages = getExampleChatMessages(snapshotChat.chat_id);

                    if (newMessages.length > 0) {
                        console.debug(`[ActiveChat] Reloaded ${newMessages.length} messages for example chat ${snapshotChat.chat_id}`);

                        // CRITICAL: Force new array reference to ensure reactivity
                        currentMessages = newMessages.map(msg => ({ ...msg }));

                        // Update chat history display
                        if (chatHistoryRef) {
                            chatHistoryRef.updateMessages(currentMessages);
                        } else {
                            console.warn('[ActiveChat] chatHistoryRef is null - cannot update messages');
                        }
                    } else {
                        console.warn('[ActiveChat] No messages found for example chat after language change:', snapshotChat.chat_id);
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
                    
                    // Update the chat header title and summary to the new locale
                    activeChatDecryptedTitle = translatedChat.title;
                    activeChatDecryptedSummary = translatedChat.description ?? null;

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
        
        // Detect touch-capable devices once per mount (used for keyboard
        // stabilization logic on iOS/iPadOS).
        isTouchEnvironment = 'ontouchstart' in window || navigator.maxTouchPoints > 0;

        // Listen to both events to catch language changes
        // 'language-changed' fires immediately, 'language-changed-complete' fires after a delay
        window.addEventListener('language-changed', handleLanguageChange);
        window.addEventListener('language-changed-complete', handleLanguageChange);

        // Listen for the dislike/retry prompt from ChatMessage's report-bad-answer flow
        window.addEventListener('setRetryMessage', handleSetRetryMessage);

        // Keep viewportHeight in sync so small-screen logic (e.g. hiding suggestions) is reactive.
        window.addEventListener('resize', handleViewportResize);

        // ── ResizeObserver for overlap detection ──────────────────────────────
        // Watches chatSideEl for size changes and recalculates whether the
        // new-chat suggestions would overlap the welcome / resume-chat content.
        // This is more reliable than a fixed viewport-height threshold because it
        // responds to actual DOM layout: varying banner heights, resume card
        // presence, font size, etc.
        let overlapObserver: ResizeObserver | null = null;
        if (chatSideEl) {
            overlapObserver = new ResizeObserver(() => {
                recalculateSuggestionsOverlap();
            });
            overlapObserver.observe(chatSideEl);
            // Initial measurement
            recalculateSuggestionsOverlap();
        }

        // Keep containerRect in sync with window scroll/resize so the fixed-position
        // MessageInput fullscreen always stays aligned with the container card.
        window.addEventListener('scroll', updateContainerRect, { passive: true });
        window.addEventListener('resize', updateContainerRect, { passive: true });
        // Initial population of containerRect — activeChatContainerEl is bound by this point.
        updateContainerRect();

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

                    // Save status update to DB — skip for incognito chats (messages are stored
                    // in sessionStorage via incognitoChatService, not in IndexedDB).
                    if (!currentChat?.is_incognito) {
                        try {
                            await chatDB.saveMessage(updatedMessage);
                        } catch (error) {
                            console.error('[ActiveChat] Error updating user message status to processing in DB:', error);
                        }
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

        const aiTaskEndedHandler = (async (event: CustomEvent<{ chatId: string; status?: string }>) => {
            if (event.detail.chatId === currentChat?.chat_id) {
                _aiTaskStateTrigger++;
                
                // ─── Progressive AI Status Indicator: Clear on task end (safety fallback) ─────
                clearProcessingPhase();
                
                // ─── Finalize streaming messages on cancellation ─────
                // When the user cancels an AI task, any assistant message with status='streaming'
                // must be transitioned to 'synced' immediately. Without this, the message stays
                // in 'streaming' state in memory and in IndexedDB, causing the chat history to
                // show an endless loading indicator and the sidebar to show stale state.
                // We do this for ALL task endings (not just cancellation) as a safety fallback
                // in case the final-chunk handler missed transitioning the message.
                //
                // PERSISTENCE ON CANCEL: If the cancelled message has content (partial response),
                // we also persist it to the server via sendCompletedAIResponse — exactly as if
                // the response had finished naturally. This ensures cross-device sync works even
                // when the user stops the response mid-stream.
                // Empty messages (cancel before any text streamed) are NOT persisted.
                let needsUpdate = false;
                const messagesToPersist: ChatMessageModel[] = [];
                for (let i = 0; i < currentMessages.length; i++) {
                    const msg = currentMessages[i];
                    if (msg.role === 'assistant' && msg.status === 'streaming') {
                        const finalized = { ...msg, status: 'synced' as const };
                        currentMessages[i] = finalized;
                        needsUpdate = true;
                        chatDB.saveMessage(finalized).catch(err => {
                            console.error(`[ActiveChat] aiTaskEndedHandler: Failed to save finalized message ${msg.message_id}:`, err);
                        });
                        console.info(`[ActiveChat] aiTaskEndedHandler: Finalized streaming message ${msg.message_id} → synced (task status: ${event.detail.status ?? 'unknown'})`);
                        // Queue for server persistence if there is actual content
                        if (finalized.content && finalized.content.trim().length > 0) {
                            messagesToPersist.push(finalized);
                        } else {
                            console.info(`[ActiveChat] aiTaskEndedHandler: Skipping server persistence for empty message ${msg.message_id} (cancelled before any text streamed)`);
                        }
                    }
                }
                if (needsUpdate) {
                    currentMessages = [...currentMessages];
                }

                // Persist partial responses to server for cross-device sync (non-incognito only)
                if (messagesToPersist.length > 0 && !currentChat?.is_incognito) {
                    for (const msg of messagesToPersist) {
                        try {
                            console.info(`[ActiveChat] aiTaskEndedHandler: Persisting partial AI response to server (cancel) — message_id: ${msg.message_id}, contentLength: ${msg.content?.length ?? 0}`);
                            await chatSyncService.sendCompletedAIResponse(msg);
                        } catch (err) {
                            console.error(`[ActiveChat] aiTaskEndedHandler: Failed to persist partial AI response ${msg.message_id} to server:`, err);
                        }
                    }
                }
                
                // FALLBACK: Mark ALL thinking entries as complete when AI task ends
                // This ensures no thinking state is left in "streaming" mode after the task finishes
                let hasStreamingThinking = false;
                thinkingContentByTask.forEach((entry, taskId) => {
                    if (thinkingPlaceholderMessageIds.has(taskId)) {
                        thinkingContentByTask.delete(taskId);
                        const nextPlaceholderIds = new Set(thinkingPlaceholderMessageIds);
                        nextPlaceholderIds.delete(taskId);
                        thinkingPlaceholderMessageIds = nextPlaceholderIds;
                        hasStreamingThinking = true;
                        return;
                    }

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
                if (hasStreamingThinking || needsUpdate) {
                    if (hasStreamingThinking) {
                        thinkingContentByTask = new Map(thinkingContentByTask);
                    }
                    if (chatHistoryRef) {
                        chatHistoryRef.updateMessages(currentMessages);
                    }
                }

                if ($chatDebugStore.rawTextMode && isAdminUser && currentChat?.chat_id) {
                    void chatDebugStore.runChatDebug(currentChat.chat_id);
                }
            }
        }) as EventListenerCallback;

        const aiTypingStartedHandler = (async (event: CustomEvent) => {
            // eslint-disable-next-line @typescript-eslint/no-unused-vars
            const { chat_id, user_message_id, message_id, category, model_name, provider_name, server_region, is_continuation } = event.detail;
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
                // NOTE: Do NOT call ensureThinkingPlaceholder here.
                // Showing a placeholder ThinkingSection before any real thinking chunks arrive
                // causes a blank/empty thinking block to flash in the UI. The thinking section
                // is created lazily in handleAiThinkingChunk on the first real chunk.

                const messageIndex = currentMessages.findIndex(m => m.message_id === user_message_id);
                // Update user message status to synced from both 'processing' and 'waiting_for_user'
                // (waiting_for_user is set when paused for app settings permission or credit issues)
                if (messageIndex !== -1 && (currentMessages[messageIndex].status === 'processing' || currentMessages[messageIndex].status === 'waiting_for_user')) {
                    const updatedMessage = { ...currentMessages[messageIndex], status: 'synced' as const };
                    currentMessages[messageIndex] = updatedMessage;
                    currentMessages = [...currentMessages];

                    // Save status update to DB — skip for incognito chats (messages are stored
                    // in sessionStorage via incognitoChatService, not in IndexedDB).
                    if (!currentChat?.is_incognito) {
                        try {
                            // $state.snapshot() converts the Svelte proxy to a plain object —
                            // IndexedDB structured clone cannot serialize $state proxies (DataCloneError).
                            await chatDB.saveMessage($state.snapshot(updatedMessage) as ChatMessageModel);
                        } catch (error) {
                            console.error('[ActiveChat] Error updating user message status to synced in DB:', error);
                        }
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

        // Handle chat deletion - if the currently active chat is deleted, reset to new chat.
        // Also handles carousel and resume card updates for cross-device sync.
        const chatDeletedHandler = ((event: CustomEvent) => {
            const { chat_id } = event.detail;
            console.debug('[ActiveChat] Received chatDeleted event for chat:', chat_id, 'Current chat:', currentChat?.chat_id);

            if (currentChat && chat_id === currentChat.chat_id) {
                console.info('[ActiveChat] Currently active chat was deleted. Resetting to new chat state.');
                // Reset to new chat state using the existing handler
                handleNewChatClick();
            }

            // ─── Carousel: remove deleted chat and trigger refresh ───────────
            const carouselIdx = recentChats.findIndex(rc => rc.chat.chat_id === chat_id);
            if (carouselIdx !== -1) {
                recentChats = recentChats.filter(rc => rc.chat.chat_id !== chat_id);
                carouselInvalidationCounter++;
                console.debug('[ActiveChat] Removed deleted chat from carousel:', chat_id);
            }

            // ─── Resume card: clear if it shows the deleted chat ─────────────
            if (resumeChatData?.chat_id === chat_id) {
                console.info('[ActiveChat] Resume card chat was deleted. Clearing and finding next best chat.');
                resumeChatData = null;
                resumeChatTitle = null;
                resumeChatCategory = null;
                resumeChatIcon = null;
                resumeChatSummary = null;
                resumeChatIsCreditsError = false;
                resumeChatUserMessagePreview = null;
                phasedSyncState.clearResumeChatData();
                // Find the next best chat from IndexedDB to show as resume card
                (async () => {
                    try {
                        await chatDB.init();
                        const chats = await chatDB.getAllChats();
                        const filtered = chats.filter(c => !isPublicChat(c.chat_id) && c.chat_id !== chat_id);
                        const sorted = sortChats(filtered, []);
                        if (sorted.length > 0) {
                            const nextBest = sorted[0];
                            const found = await loadResumeChatFromDB(nextBest.chat_id);
                            if (found) {
                                console.info('[ActiveChat] Promoted next best chat as resume card:', nextBest.chat_id);
                            }
                        }
                    } catch (err) {
                        console.warn('[ActiveChat] Error finding next resume chat after deletion:', err);
                    }
                })();
                carouselInvalidationCounter++;
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

        // ─── Cross-device sync: refresh carousel and resume card after sync completes ──
        // When the WebSocket reconnects (tab foregrounded, network restored), phased sync
        // delivers fresh chat data to IndexedDB. syncComplete fires after Phase 3 finishes —
        // trigger a carousel re-read so new/deleted/updated chats appear immediately.
        const syncCompleteHandler = (() => {
            if (showWelcome) {
                console.debug('[ActiveChat] syncComplete — refreshing carousel and resume card');
                carouselInvalidationCounter++;
                const lastOpened = $userProfile.last_opened;
                if (lastOpened && !isPublicChat(lastOpened)) {
                    loadResumeChatFromDB(lastOpened);
                }
            }
        }) as EventListenerCallback;
        chatSyncService.addEventListener('syncComplete', syncCompleteHandler);

        // ─── Tab visibility: refresh stale carousel when tab returns from background ──
        // When a tab is backgrounded and later foregrounded, the carousel may show stale
        // data (chats created/deleted/updated on other devices while backgrounded).
        // Wait 1.5s after visibility change to give WebSocket reconnect + sync time to
        // update IndexedDB, then trigger a full carousel re-read.
        let _visibilityTimer: ReturnType<typeof setTimeout> | null = null;
        const handleVisibilityChange = () => {
            if (document.visibilityState !== 'visible') return;
            if (!showWelcome) return;
            if (_visibilityTimer) clearTimeout(_visibilityTimer);
            _visibilityTimer = setTimeout(() => {
                _visibilityTimer = null;
                if (showWelcome) {
                    console.debug('[ActiveChat] Tab foregrounded — refreshing carousel and resume card');
                    carouselInvalidationCounter++;
                    const lastOpened = $userProfile.last_opened;
                    if (lastOpened && !isPublicChat(lastOpened)) {
                        loadResumeChatFromDB(lastOpened);
                    }
                }
            }, 1500);
        };
        document.addEventListener('visibilitychange', handleVisibilityChange);

        // ─── Chat Compression event handlers ─────────────────────────────────────────
        // When the AI worker detects a long chat history, it triggers compression before
        // preprocessing. These events update the processing phase to show a shimmer indicator.
        const compressionStartedHandler = ((event: CustomEvent) => {
            const { chat_id } = event.detail;
            if (chat_id === currentChat?.chat_id) {
                console.debug('[ActiveChat] Chat compression started for chat', chat_id);
                processingPhase = {
                    phase: 'compressing',
                    statusLines: [$text('chat.compression.compressing')]
                };
            }
        }) as EventListenerCallback;

        const compressionCompletedHandler = ((event: CustomEvent) => {
            const { chat_id, error, compressed_message_count } = event.detail;
            if (chat_id === currentChat?.chat_id) {
                if (error) {
                    console.warn('[ActiveChat] Chat compression failed for chat', chat_id, ':', error);
                } else {
                    console.debug('[ActiveChat] Chat compression completed for chat', chat_id,
                        `(${compressed_message_count} messages compressed)`);
                }
                // Clear the compressing phase — the normal sending → processing → typing
                // flow will take over from here as the AI task continues.
                if (processingPhase?.phase === 'compressing') {
                    processingPhase = {
                        phase: 'sending',
                        statusLines: [$text('enter_message.sending')]
                    };
                }
            }
        }) as EventListenerCallback;

        chatSyncService.addEventListener('chatCompressionStarted', compressionStartedHandler);
        chatSyncService.addEventListener('chatCompressionCompleted', compressionCompletedHandler);
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
                        const updated: MessageWithEmbedMeta = {
                            ...(msg as MessageWithEmbedMeta),
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
                                embedData: { status: previewData.status },
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
                                embedData: { status: previewData.status },
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

        // OPE-314: Re-decrypt messages when a chat key becomes available.
        // Handles the race condition where messages render before the master key
        // finishes loading, showing "[Decrypting...]" instead of content. When the
        // key arrives (via bulk_init retry, server sync, or cross-tab broadcast),
        // re-load the messages so they decrypt with the now-available key.
        const unsubscribeKeyReady = chatKeyManager.onKeyReady(async (readyChatId: string) => {
            if (currentChat?.chat_id !== readyChatId) return;

            // OPE-314: Re-decrypt pending messages
            if (currentMessages.some((m: Record<string, unknown>) => m._decryptionPending)) {
                console.info(`[ActiveChat] Key ready for chat ${readyChatId}, re-decrypting pending messages`);
                try {
                    const freshMessages = await chatDB.getMessagesForChat(readyChatId);
                    if (freshMessages && freshMessages.length > 0) {
                        currentMessages = freshMessages;
                        if (chatHistoryRef) {
                            chatHistoryRef.updateMessages(currentMessages);
                        }
                    }
                } catch (err) {
                    console.error(`[ActiveChat] Failed to re-decrypt messages for ${readyChatId}:`, err);
                }
            }

            // OPE-327: Re-decrypt chat header metadata (category/icon/title) when key arrives.
            // Without this, the ChatHeader stays in "Creating new chat..." shimmer forever
            // because activeChatDecryptedCategory remains null from the failed initial decrypt.
            if (!activeChatDecryptedCategory) {
                console.info(`[ActiveChat] Key ready for chat ${readyChatId}, re-decrypting header metadata`);
                try {
                    const chatForHeader = await chatDB.getChat(readyChatId);
                    if (chatForHeader) {
                        const chatKey = chatKeyManager.getKeySync(readyChatId);
                        if (chatKey) {
                            const { decryptWithChatKey } = await import('../services/cryptoService');
                            let t = '';
                            let c: string | null = null;
                            let ic: string | null = null;
                            let s: string | null = null;
                            if (chatForHeader.encrypted_title) {
                                try { t = await decryptWithChatKey(chatForHeader.encrypted_title, chatKey, { chatId: readyChatId, fieldName: 'encrypted_title' }) ?? ''; } catch { /* keep blank */ }
                            }
                            if (chatForHeader.encrypted_category) {
                                try { c = await decryptWithChatKey(chatForHeader.encrypted_category, chatKey, { chatId: readyChatId, fieldName: 'encrypted_category' }); } catch { /* keep null */ }
                            }
                            if (chatForHeader.encrypted_icon) {
                                try { ic = await decryptWithChatKey(chatForHeader.encrypted_icon, chatKey, { chatId: readyChatId, fieldName: 'encrypted_icon' }); } catch { /* keep null */ }
                            }
                            if (chatForHeader.encrypted_chat_summary) {
                                try { s = await decryptWithChatKey(chatForHeader.encrypted_chat_summary, chatKey, { chatId: readyChatId, fieldName: 'encrypted_chat_summary' }); } catch { /* keep null */ }
                            }
                            if (t && c) {
                                activeChatDecryptedTitle = t;
                                activeChatDecryptedCategory = c;
                                activeChatDecryptedIcon = ic;
                                activeChatDecryptedSummary = s;
                                isNewChatGeneratingTitle = false;
                                console.info(`[ActiveChat] Header re-decrypted for ${readyChatId}: title=${t}, category=${c}, icon=${ic}`);
                            }
                        }
                    }
                } catch (err) {
                    console.error(`[ActiveChat] Failed to re-decrypt header for ${readyChatId}:`, err);
                }
            }
        });

        return () => {
            // Remove listeners from chatSyncService
            chatSyncService.removeEventListener('chatUpdated', chatUpdateHandler);
            chatSyncService.removeEventListener('messageStatusChanged', messageStatusHandler);
            unsubscribeAiTyping(); // Unsubscribe from AI typing store
            unsubscribeDraftState(); // Unsubscribe from draft state
            chatSyncService.removeEventListener('aiMessageChunk', handleAiMessageChunk as EventListenerCallback); // Remove listener
            chatSyncService.removeEventListener('aiTaskInitiated', aiTaskInitiatedHandler);
            chatSyncService.removeEventListener('chatCompressionStarted', compressionStartedHandler);
            chatSyncService.removeEventListener('chatCompressionCompleted', compressionCompletedHandler);
            chatSyncService.removeEventListener('aiTypingStarted', aiTypingStartedHandler);
            chatSyncService.removeEventListener('aiTaskEnded', aiTaskEndedHandler);
            // Remove thinking/reasoning event listeners
            chatSyncService.removeEventListener('aiThinkingChunk', handleAiThinkingChunk as EventListenerCallback);
            chatSyncService.removeEventListener('aiThinkingComplete', handleAiThinkingComplete as EventListenerCallback);
            chatSyncService.removeEventListener('chatDeleted', chatDeletedHandler);
            chatSyncService.removeEventListener('messageDeleted', messageDeletedHandler);
            chatSyncService.removeEventListener('syncComplete', syncCompleteHandler);
            document.removeEventListener('visibilitychange', handleVisibilityChange);
            if (_visibilityTimer) clearTimeout(_visibilityTimer);
            if (_carouselRefreshTimer) clearTimeout(_carouselRefreshTimer);
            window.removeEventListener('preprocessingStep', preprocessingStepHandler);
            chatSyncService.removeEventListener('postProcessingCompleted', handlePostProcessingCompleted as EventListenerCallback);
            chatSyncService.removeEventListener('aiStreamInterrupted', aiStreamInterruptedHandler);
            chatSyncService.removeEventListener('embedUpdated', embedUpdatedHandler);
            skillPreviewService.removeEventListener('skillPreviewUpdate', handleSkillPreviewUpdate as EventListenerCallback);
            unsubscribeKeyReady(); // OPE-314: Remove key-ready re-decrypt listener
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
            window.removeEventListener('incognitoChatsDeleted', handleIncognitoChatsDeleted as EventListenerCallback);
            window.removeEventListener('hiddenChatsLocked', handleHiddenChatsLocked as EventListenerCallback);
            window.removeEventListener('hiddenChatsAutoLocked', handleHiddenChatsLocked as EventListenerCallback);
            window.removeEventListener('setRetryMessage', handleSetRetryMessage);
            // Remove embed and video PiP fullscreen listeners
            document.removeEventListener('embedfullscreen', embedFullscreenHandler as EventListenerCallback);
            document.removeEventListener('wikifullscreen', wikiFullscreenHandler as EventListenerCallback);
            document.removeEventListener('videopip-restore-fullscreen', videoPipRestoreHandler as EventListenerCallback);
            // Remove image/PDF/recording fullscreen document listeners
            document.removeEventListener('imagefullscreen', imagefullscreenHandler);
            document.removeEventListener('pdffullscreen', pdffullscreenHandler);
            document.removeEventListener('pdfreadfullscreen', pdfreadfullscreenHandler);
            document.removeEventListener('pdfsearchfullscreen', pdfsearchfullscreenHandler);
            document.removeEventListener('recordingfullscreen', recordingfullscreenHandler);
            // Remove focus mode event listeners
            document.removeEventListener('focusModeRejected', focusModeRejectedHandler as EventListenerCallback);
            document.removeEventListener('focusModeDeactivated', focusModeDeactivatedHandler as EventListenerCallback);
            document.removeEventListener('focusModeDetailsRequested', focusModeDetailsHandler as EventListenerCallback);
            document.removeEventListener('focusModeContextMenu', focusModeContextMenuHandler as EventListenerCallback);
            chatSyncService.removeEventListener('focusModeActivated', focusModeActivatedHandler as EventListenerCallback);
            // Remove viewport resize listener
            window.removeEventListener('resize', handleViewportResize);
            // Remove container rect update listeners
            window.removeEventListener('scroll', updateContainerRect);
            window.removeEventListener('resize', updateContainerRect);
            // Disconnect overlap ResizeObserver
            overlapObserver?.disconnect();
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
    data-testid="active-chat-container"
    data-authenticated={$authStore.isAuthenticated ? 'true' : 'false'}
    class:ai-typing={isAssistantTyping}
    class:dimmed={isDimmed}
    class:login-mode={!showChat}
    class:scaled={activeScaling}
    class:narrow={isEffectivelyNarrow}
    class:medium={isMedium && !showSideBySideLayout}
    class:wide={isWide && !showSideBySideLayout}
    class:extra-wide={isExtraWide}
    class:side-by-side-active={showSideBySideLayout}
    bind:clientWidth={containerWidth}
    bind:this={activeChatContainerEl}
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
            data-testid="login-wrapper"
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
                <!-- 404 Not-Found screen: shown exclusively when the user landed on an unknown URL.
                     Replaces both chat-side and message-input-wrapper entirely. -->
                {#if $notFoundPathStore !== null}
                    <Not404Screen
                        onSearch={handle404Search}
                        onAskAI={handle404AskAI}
                    />
                {:else}
                <!-- Left side container for chat history and buttons -->
                <div class="chat-side" bind:this={chatSideEl}>
                    <!-- Daily Inspiration banners – shown above welcome greeting on new chat screen -->
                    <!-- Faded out via CSS opacity transition when keyboard is open (same rule as welcome greeting) -->
                    <!-- Shown to ALL users: defaults for guests, personalized for authenticated users -->
                    <!-- Rendered FIRST so it appears above the top-buttons row on the welcome screen -->
                    {#if showWelcome}
                        <div class="daily-inspiration-area" class:welcome-hiding={hideWelcomeForKeyboard}>
                            <DailyInspirationBanner
                                onStartChat={handleStartChatFromInspiration}
                                onEmbedFullscreen={handleInspirationEmbedFullscreen}
                                containerWidth={effectiveChatWidth}
                            />
                        </div>
                    {/if}

                    <!-- Top action buttons row.
                         On the welcome screen (showWelcome=true): rendered in normal document flow
                         below the daily inspiration banner (top-buttons-flow class removes position:absolute).
                         On the active chat screen (showWelcome=false): absolutely positioned at top. -->
                    <div class="top-buttons" class:top-buttons-flow={showWelcome} class:welcome-hiding={showWelcome && hideWelcomeForKeyboard}>
                        <!-- Left side buttons -->
                        <div class="left-buttons">
                            {#if createButtonVisible}
                                <!-- New chat CTA button: same color as Send, pill shape, white icon; label visible on larger screens only -->
                                <div class="new-chat-button-wrapper new-chat-cta-wrapper">
                                    <button
                                        class="new-chat-cta-button"
                                        data-action="new-chat"
                                        data-testid="new-chat-button"
                                        aria-label={$text('common.new_chat')}
                                        onclick={handleNewChatClick}
                                        in:fade={{ duration: 300 }}
                                        use:tooltip
                                    >
                                        <span class="clickable-icon icon_create new-chat-cta-icon"></span>
                                        <span class="new-chat-cta-label">{$text('common.new_chat')}</span>
                                    </button>
                                </div>
                            {/if}
                            {#if !showWelcome}
                                <!-- Share button - opens settings menu with share submenu -->
                                <!-- Use same wrapper design as new chat button -->
                                <div class="new-chat-button-wrapper">
                                    <button
                                        class="clickable-icon icon_share top-button"
                                        data-testid="chat-share-button"
                                        aria-label={$text('chat.share')}
                                        onclick={handleShareChat}
                                        use:tooltip
                                    >
                                    </button>
                                </div>
                            {/if}
                            <div class="new-chat-button-wrapper">
                                <button
                                    data-testid="report-issue-button"
                                    class="clickable-icon icon_bug top-button"
                                    aria-label={$text('header.report_issue')}
                                    onclick={handleReportIssue}
                                    use:tooltip
                                >
                                </button>
                            </div>
                            {#if isAdminUser}
                                <div class="new-chat-button-wrapper">
                                    <button
                                        data-testid="start-debugging-button"
                                        class="clickable-icon icon_task top-button"
                                        class:debug-mode-active={$chatDebugStore.rawTextMode}
                                        aria-label={$chatDebugStore.rawTextMode ? $text('chats.context_menu.end_debugging') : $text('chats.context_menu.start_debugging')}
                                        onclick={handleToggleDebugMode}
                                        use:tooltip
                                    >
                                    </button>
                                </div>
                            {/if}
                            <!-- PII hide/unhide toggle - only shows when chat has sensitive data -->
                            {#if chatHasPII && !showWelcome}
                                <div class="new-chat-button-wrapper">
                                    <button
                                        data-testid="chat-pii-toggle"
                                        data-pii-revealed={piiRevealed ? 'true' : 'false'}
                                        class="clickable-icon {piiRevealed ? 'icon_visible' : 'icon_hidden'} top-button"
                                        class:pii-toggle-active={piiRevealed}
                                        aria-label={piiRevealed
                                            ? $text('chat.pii_hide')
                                            : $text('chat.pii_show')}
                                        onclick={handleTogglePIIVisibility}
                                        use:tooltip
                                    >
                                    </button>
                                </div>
                            {/if}
                        </div>

                        <!-- Right side buttons -->
                        <div class="right-buttons">
                            {#if !showWelcome && $authStore.isAuthenticated && currentChat?.chat_id && !isPublicChat(currentChat.chat_id)}
                                <div class="new-chat-button-wrapper">
                                    <button
                                        class="clickable-icon icon_reminder top-button"
                                        data-testid="chat-reminders-button"
                                        aria-label={$text('chat.reminders')}
                                        onclick={handleOpenReminders}
                                        use:tooltip
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
                    <!-- Faded out via CSS opacity transition when keyboard is open to free up visual space -->
                    {#if showWelcome}
                        <div
                            class="center-content"
                            class:welcome-hiding={hideWelcomeForKeyboard}
                            bind:this={welcomeContentEl}
                        >
                            <div class="team-profile">
                                <!-- <div class="team-image" class:disabled={!isTeamEnabled}></div> -->
                                <div class="welcome-text">
                                    <h2>
                                        {#each welcomeHeadingParts as part, index}
                                            <span>{part}</span>{#if index < welcomeHeadingParts.length - 1}<br>{/if}
                                        {/each}
                                    </h2>
                                    <!-- Subtitle: "Continue where you left off" when resume chat or recent chats, "Explore OpenMates:" for non-auth scrollable list, else default prompt -->
                                    {#if resumeChatData || ($authStore.isAuthenticated && recentChats.length > 0)}
                                        <p>{$text('chats.resume_last_chat.title')}</p>
                                    {:else if !$authStore.isAuthenticated}
                                        <p>{$text('chats.explore_openmates.title')}</p>
                                    {:else}
                                        <p>
                                            {#each welcomePromptParts as part, index}
                                                <span>{part}</span>{#if index < welcomePromptParts.length - 1}<br>{/if}
                                            {/each}
                                        </p>
                                    {/if}
                                </div>
                            </div>

                            <!-- Resume card + recent chats horizontal scroll (authenticated users) -->
                            {#if resumeChatData || ($authStore.isAuthenticated && recentChats.length > 0)}
                                <div
                                    class="recent-chats-scroll-container"
                                    data-testid="recent-chats-scroll-container"
                                    bind:this={recentChatsScrollEl}
                                >
                                    <!-- ── Primary resume card (most recent / last-opened) ── -->
                                    {#if resumeChatData}
                                        {#if isTallViewport && !resumeChatIsCreditsError}
                                            {@const category = resumeChatCategory || 'general_knowledge'}
                                            {@const gradientColors = getCategoryGradientColors(category)}
                                            {@const iconName = getValidIconName(resumeChatIcon || '', category)}
                                            {@const IconComponent = getLucideIcon(iconName)}
                                            <button
                                                bind:this={resumeLargeCardElement}
                                                class="resume-chat-large-card" data-testid="resume-chat-large-card"
                                                class:hovering={isResumeLargeCardHovering}
                                                style={getResumeLargeCardStyle(gradientColors)}
                                                onclick={handleResumeLastChat}
                                                oncontextmenu={(e) => { if (resumeChatData) handleResumeCardContextMenu(e, resumeChatData); }}
                                                ontouchstart={(e) => { if (resumeChatData) handleResumeCardTouchStart(e, resumeChatData); }}
                                                ontouchmove={handleResumeCardTouchMove}
                                                ontouchend={handleResumeCardTouchEnd}
                                                onmouseenter={handleResumeLargeCardMouseEnter}
                                                onmousemove={handleResumeLargeCardMouseMove}
                                                onmouseleave={handleResumeLargeCardMouseLeave}
                                                type="button"
                                            >
                                                {#if resumeChatData.pinned}
                                                    {@const PinIcon = getLucideIcon('pin')}
                                                    <div class="resume-card-pin-badge" data-testid="resume-card-pin">
                                                        <PinIcon size={18} color="white" />
                                                    </div>
                                                {/if}
                                                <div class="resume-large-orbs" aria-hidden="true">
                                                    <div class="resume-orb resume-orb-1"></div>
                                                    <div class="resume-orb resume-orb-2"></div>
                                                    <div class="resume-orb resume-orb-3"></div>
                                                </div>
                                                {#if IconComponent}
                                                    <div class="resume-large-deco resume-large-deco-left">
                                                        <IconComponent size={80} color="white" />
                                                    </div>
                                                    <div class="resume-large-deco resume-large-deco-right">
                                                        <IconComponent size={80} color="white" />
                                                    </div>
                                                {/if}
                                                <div class="resume-large-content">
                                                    {#if IconComponent}
                                                        <div class="resume-large-icon">
                                                            <IconComponent size={32} color="white" />
                                                        </div>
                                                    {/if}
                                                    <span class="resume-large-title" data-testid="resume-large-title">{resumeChatTitle || $text('common.untitled_chat')}</span>
                                                    {#if resumeChatSummary}
                                                        <p class="resume-large-summary">{resumeChatSummary}</p>
                                                    {/if}
                                                </div>
                                            </button>
                                        {:else}
                                            <!-- Compact card: short screens or credits-error state -->
                                            {@const ChevronRight = getLucideIcon('chevron-right')}
                                            {@const compactCategory = resumeChatCategory || 'general_knowledge'}
                                            {@const compactGradientColors = getCategoryGradientColors(compactCategory)}
                                            {@const compactIconName = getValidIconName(resumeChatIcon || '', compactCategory)}
                                            {@const CompactIconComponent = getLucideIcon(compactIconName)}
                                            <button
                                                class="resume-chat-card" data-testid="resume-chat-card"
                                                style={getResumeCardGradientStyle(compactGradientColors)}
                                                onclick={handleResumeLastChat}
                                                oncontextmenu={(e) => { if (resumeChatData) handleResumeCardContextMenu(e, resumeChatData); }}
                                                ontouchstart={(e) => { if (resumeChatData) handleResumeCardTouchStart(e, resumeChatData); }}
                                                ontouchmove={handleResumeCardTouchMove}
                                                ontouchend={handleResumeCardTouchEnd}
                                                type="button"
                                            >
                                                {#if resumeChatData.pinned}
                                                    {@const PinIconCompact = getLucideIcon('pin')}
                                                    <div class="resume-card-pin-badge compact" data-testid="resume-card-pin">
                                                        <PinIconCompact size={15} color="white" />
                                                    </div>
                                                {/if}
                                                {#if resumeChatIsCreditsError}
                                                    <div class="resume-chat-content resume-chat-credits-content">
                                                        <span class="resume-chat-credits-label">{$text('chat.credits_needed')}</span>
                                                        {#if resumeChatUserMessagePreview}
                                                            <span class="resume-chat-credits-preview">{resumeChatUserMessagePreview.slice(0, 60)}</span>
                                                        {/if}
                                                    </div>
                                                {:else}
                                                    <div class="resume-chat-compact-icon">
                                                        <CompactIconComponent size={18} color="rgba(255, 255, 255, 0.92)" />
                                                    </div>
                                                    <div class="resume-chat-content">
                                                        <span class="resume-chat-title" data-testid="resume-chat-title">{resumeChatTitle || $text('common.untitled_chat')}</span>
                                                    </div>
                                                {/if}
                                                <div class="resume-chat-arrow">
                                                    <ChevronRight size={16} color="rgba(255, 255, 255, 0.88)" />
                                                </div>
                                            </button>
                                        {/if}
                                    {/if}

                                    <!-- ── Additional recent chats (scrollable after primary card) ── -->
                                    <!-- Dedup: skip any chat already shown as the resume card to prevent
                                         duplicates when loadRecentChats and resumeChatData use different sources -->
                                    {#each recentChats.filter(m => m.chat.chat_id !== resumeChatData?.chat_id) as meta, i (meta.chat.chat_id)}
                                        {@const tilt = recentChatTiltStates[i]}
                                        {@const isDraft = !!meta.draftPreview && !meta.title}
                                        {@const category = meta.category || 'general_knowledge'}
                                        {@const gradientColors = isDraft ? null : getCategoryGradientColors(category)}
                                        {@const iconName = isDraft ? '' : getValidIconName(meta.icon || '', category)}
                                        {@const IconComponent = isDraft ? null : getLucideIcon(iconName)}
                                        {#if isDraft}
                                            <!-- Draft-only card: matches sidebar draft-only-layout (label + preview) -->
                                            <button
                                                class="resume-chat-card resume-chat-draft-card" data-testid="resume-chat-draft-card"
                                                data-chat-id={meta.chat.chat_id}
                                                onclick={() => handleOpenRecentChat(meta.chat)}
                                                oncontextmenu={(e) => handleResumeCardContextMenu(e, meta.chat)}
                                                ontouchstart={(e) => handleResumeCardTouchStart(e, meta.chat)}
                                                ontouchmove={handleResumeCardTouchMove}
                                                ontouchend={handleResumeCardTouchEnd}
                                                type="button"
                                            >
                                                <div class="resume-chat-content resume-chat-draft-content">
                                                    <span class="resume-chat-draft-label">{$text('enter_message.draft')}</span>
                                                    <span class="resume-chat-draft-preview">{meta.draftPreview.length > 80 ? meta.draftPreview.slice(0, 80) + '…' : meta.draftPreview}</span>
                                                </div>
                                            </button>
                                        {:else if isTallViewport}
                                            {@const bgStyle = getResumeCardGradientStyle(gradientColors)}
                                            {@const cardStyle = tilt?.tiltTransform
                                                ? `${bgStyle}; transform: ${tilt.tiltTransform}`
                                                : bgStyle}
                                            <button
                                                bind:this={tilt.el}
                                                class="resume-chat-large-card" data-testid="resume-chat-large-card"
                                                class:hovering={tilt?.hovering}
                                                type="button"
                                                style={cardStyle}
                                                data-chat-id={meta.chat.chat_id}
                                                data-pinned={meta.chat.pinned ? 'true' : 'false'}
                                                onclick={() => handleOpenRecentChat(meta.chat)}
                                                oncontextmenu={(e) => handleResumeCardContextMenu(e, meta.chat)}
                                                ontouchstart={(e) => handleResumeCardTouchStart(e, meta.chat)}
                                                ontouchmove={handleResumeCardTouchMove}
                                                ontouchend={handleResumeCardTouchEnd}
                                                onmouseenter={(e) => tilt?.onMouseEnter(e)}
                                                onmousemove={(e) => tilt?.onMouseMove(e)}
                                                onmouseleave={() => tilt?.onMouseLeave()}
                                            >
                                                {#if meta.chat.pinned}
                                                    {@const PinIcon = getLucideIcon('pin')}
                                                    <div class="resume-card-pin-badge" data-testid="resume-card-pin">
                                                        <PinIcon size={18} color="white" />
                                                    </div>
                                                {/if}
                                                <div class="resume-large-orbs" aria-hidden="true">
                                                    <div class="resume-orb resume-orb-1"></div>
                                                    <div class="resume-orb resume-orb-2"></div>
                                                    <div class="resume-orb resume-orb-3"></div>
                                                </div>
                                                {#if IconComponent}
                                                    <div class="resume-large-deco resume-large-deco-left">
                                                        <IconComponent size={80} color="white" />
                                                    </div>
                                                    <div class="resume-large-deco resume-large-deco-right">
                                                        <IconComponent size={80} color="white" />
                                                    </div>
                                                {/if}
                                                <div class="resume-large-content">
                                                    {#if IconComponent}
                                                        <div class="resume-large-icon">
                                                            <IconComponent size={32} color="white" />
                                                        </div>
                                                    {/if}
                                                    <span class="resume-large-title" data-testid="resume-large-title">{meta.title || $text('common.untitled_chat')}</span>
                                                    {#if meta.summary}
                                                        <p class="resume-large-summary">{meta.summary}</p>
                                                    {/if}
                                                </div>
                                            </button>
                                        {:else}
                                            <!-- Compact card for short viewports -->
                                            {@const ChevronRight = getLucideIcon('chevron-right')}
                                            <button
                                                class="resume-chat-card" data-testid="resume-chat-card"
                                                style={getResumeCardGradientStyle(gradientColors)}
                                                data-chat-id={meta.chat.chat_id}
                                                data-pinned={meta.chat.pinned ? 'true' : 'false'}
                                                onclick={() => handleOpenRecentChat(meta.chat)}
                                                oncontextmenu={(e) => handleResumeCardContextMenu(e, meta.chat)}
                                                ontouchstart={(e) => handleResumeCardTouchStart(e, meta.chat)}
                                                ontouchmove={handleResumeCardTouchMove}
                                                ontouchend={handleResumeCardTouchEnd}
                                                type="button"
                                            >
                                                {#if meta.chat.pinned}
                                                    {@const PinIcon = getLucideIcon('pin')}
                                                    <div class="resume-card-pin-badge compact" data-testid="resume-card-pin">
                                                        <PinIcon size={15} color="white" />
                                                    </div>
                                                {/if}
                                                <div class="resume-chat-compact-icon">
                                                    <IconComponent size={18} color="rgba(255, 255, 255, 0.92)" />
                                                </div>
                                                <div class="resume-chat-content">
                                                    <span class="resume-chat-title" data-testid="resume-chat-title">{meta.title || $text('common.untitled_chat')}</span>
                                                </div>
                                                <div class="resume-chat-arrow">
                                                    <ChevronRight size={16} color="rgba(255, 255, 255, 0.88)" />
                                                </div>
                                            </button>
                                        {/if}
                                    {/each}

                                    <!-- "+N more" overflow button (auth) -->
                                    {#if ($userProfile.total_chat_count ?? 0) > ((resumeChatData ? 1 : 0) + recentChats.length)}
                                        <button
                                            class="recent-chat-overflow"
                                            class:compact={!isTallViewport}
                                            type="button"
                                            onclick={() => panelState.toggleChats()}
                                        >
                                            +{($userProfile.total_chat_count ?? 0) - ((resumeChatData ? 1 : 0) + recentChats.length)}
                                        </button>
                                    {/if}
                                </div>
                            <!-- Non-auth: scrollable list of intro + example chats (same card design as auth recent chats) -->
                            {:else if !$authStore.isAuthenticated && nonAuthRecentChats.length > 0}
                                <div
                                    class="recent-chats-scroll-container"
                                    bind:this={recentChatsScrollEl}
                                >
                                    {#each nonAuthRecentChats as meta, i (meta.chat.chat_id)}
                                        {@const tilt = nonAuthChatTiltStates[i]}
                                        {@const category = meta.category || 'general_knowledge'}
                                        {@const gradientColors = getCategoryGradientColors(category)}
                                        {@const iconName = getValidIconName(meta.icon || '', category)}
                                        {@const IconComponent = getLucideIcon(iconName)}
                                        {#if isTallViewport}
                                            {@const bgStyle = getResumeCardGradientStyle(gradientColors)}
                                            {@const cardStyle = tilt?.tiltTransform
                                                ? `${bgStyle}; transform: ${tilt.tiltTransform}`
                                                : bgStyle}
                                            <button
                                                bind:this={tilt.el}
                                                class="resume-chat-large-card" data-testid="resume-chat-large-card"
                                                class:hovering={tilt?.hovering}
                                                type="button"
                                                style={cardStyle}
                                                onclick={() => handleOpenRecentChat(meta.chat)}
                                                oncontextmenu={(e) => handleResumeCardContextMenu(e, meta.chat)}
                                                ontouchstart={(e) => handleResumeCardTouchStart(e, meta.chat)}
                                                ontouchmove={handleResumeCardTouchMove}
                                                ontouchend={handleResumeCardTouchEnd}
                                                onmouseenter={(e) => tilt?.onMouseEnter(e)}
                                                onmousemove={(e) => tilt?.onMouseMove(e)}
                                                onmouseleave={() => tilt?.onMouseLeave()}
                                            >
                                                <div class="resume-large-orbs" aria-hidden="true">
                                                    <div class="resume-orb resume-orb-1"></div>
                                                    <div class="resume-orb resume-orb-2"></div>
                                                    <div class="resume-orb resume-orb-3"></div>
                                                </div>
                                                {#if IconComponent}
                                                    <div class="resume-large-deco resume-large-deco-left">
                                                        <IconComponent size={80} color="white" />
                                                    </div>
                                                    <div class="resume-large-deco resume-large-deco-right">
                                                        <IconComponent size={80} color="white" />
                                                    </div>
                                                {/if}
                                                <div class="resume-large-content">
                                                    {#if IconComponent}
                                                        <div class="resume-large-icon">
                                                            <IconComponent size={32} color="white" />
                                                        </div>
                                                    {/if}
                                                    <span class="resume-large-title" data-testid="resume-large-title">{meta.title || $text('common.untitled_chat')}</span>
                                                    {#if meta.summary}
                                                        <p class="resume-large-summary">{meta.summary}</p>
                                                    {/if}
                                                </div>
                                            </button>
                                        {:else}
                                            <!-- Compact card for short viewports -->
                                            {@const ChevronRight = getLucideIcon('chevron-right')}
                                            <button
                                                class="resume-chat-card" data-testid="resume-chat-card"
                                                style={getResumeCardGradientStyle(gradientColors)}
                                                onclick={() => handleOpenRecentChat(meta.chat)}
                                                oncontextmenu={(e) => handleResumeCardContextMenu(e, meta.chat)}
                                                ontouchstart={(e) => handleResumeCardTouchStart(e, meta.chat)}
                                                ontouchmove={handleResumeCardTouchMove}
                                                ontouchend={handleResumeCardTouchEnd}
                                                type="button"
                                            >
                                                <div class="resume-chat-compact-icon">
                                                    <IconComponent size={18} color="rgba(255, 255, 255, 0.92)" />
                                                </div>
                                                <div class="resume-chat-content">
                                                    <span class="resume-chat-title" data-testid="resume-chat-title">{meta.title || $text('common.untitled_chat')}</span>
                                                </div>
                                                <div class="resume-chat-arrow">
                                                    <ChevronRight size={16} color="rgba(255, 255, 255, 0.88)" />
                                                </div>
                                            </button>
                                        {/if}
                                    {/each}
                                </div>
                            {/if}
                        </div>
                    {/if}

                     <ChatHistory
                         bind:this={chatHistoryRef}
                         messageInputHeight={0}
                         containerWidth={effectiveChatWidth}
                         currentChatId={currentChat?.chat_id}
                         {processingPhase}
                         {thinkingContentByTask}
                         chatTitle={activeChatDecryptedTitle}
                         chatCategory={activeChatDecryptedCategory}
                         chatIcon={activeChatDecryptedIcon}
                         chatSummary={activeChatDecryptedSummary}
                         chatCreatedAt={currentChat && !isPublicChat(currentChat.chat_id) ? (currentChat.created_at ?? null) : null}
                         {isNewChatGeneratingTitle}
                         {isNewChatCreditsError}
                         {isCreditsRestored}
                         isIncognito={!!currentChat?.is_incognito}
                         isExampleChat={!!currentChat && isExampleChat(currentChat.chat_id)}
                         canAnnotate={!currentChat?.is_shared_by_others}
                         videoMp4Url={(() => { const allChats = [...DEMO_CHATS, ...LEGAL_CHATS]; const dc = currentChat?.chat_id ? allChats.find(c => c.chat_id === currentChat.chat_id) : null; return dc?.metadata?.video_mp4_url ?? null; })()}
                         backgroundFrames={(() => { const allChats = [...DEMO_CHATS, ...LEGAL_CHATS]; const dc = currentChat?.chat_id ? allChats.find(c => c.chat_id === currentChat.chat_id) : null; const frames = dc?.metadata?.background_frames; if (!frames) return null; const titleFrame = $locale?.startsWith('de') ? '/intro-frames/frame-00_DE.webp' : '/intro-frames/frame-00_EN.webp'; return [titleFrame, ...frames]; })()}
                         onPlayVideo={() => {
                             if (!currentChat?.chat_id) return;
                             const allChats = [...DEMO_CHATS, ...LEGAL_CHATS];
                             const dc = allChats.find(c => c.chat_id === currentChat.chat_id);
                             if (!dc?.metadata?.video_mp4_url) return;
                             Promise.all([
                                 import('../stores/chatVideoFullscreenStore'),
                                 import('../demo_chats/data/videos'),
                             ]).then(([{ openChatVideoFullscreen }, { getVideoForLocale }]) => {
                                 const videoKey = dc.metadata?.video_key;
                                 const localeVideo = videoKey ? getVideoForLocale(videoKey, $locale ?? 'en') : null;
                                 const mp4 = localeVideo?.mp4_url ?? dc.metadata?.video_mp4_url;
                                 if (mp4) {
                                     openChatVideoFullscreen({ mp4Url: mp4, title: activeChatDecryptedTitle || '', chatId: currentChat.chat_id });
                                 }
                             });
                         }}
                         onResend={handleResendAfterCreditsRestored}
                         followUpSuggestions={showFollowUpSuggestions ? followUpSuggestions : []}
                         onSuggestionClick={handleSuggestionClick}
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
                            data-testid="typing-indicator"
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

                    <div class="message-input-container" bind:this={messageInputContainerEl}>
                         <!-- New chat suggestions when no chat is open and user is at bottom/input active -->
                         <!-- Show immediately with default suggestions, then swap to user's real suggestions once sync completes -->
                         <!-- No longer gated behind initialSyncCompleted - NewChatSuggestions handles fallback to defaults -->
                         <!-- Hidden while the map location selector is open (messageInputMapsOpen) —
                              restored automatically when the map is closed and the input is still empty. -->
                         <!-- Height-based overlap guard: when the suggestions panel would visually
                              overlap the welcome greeting / resume-chat card below it, hide the
                              suggestions by default.  They are revealed only when the message input
                              is focused — at which point the welcome content is also hidden
                              (hideWelcomeForKeyboard), giving the suggestions room to breathe.
                              Legacy fallback: also hide on very short screens (≤670px viewport). -->
                         {#if showWelcome && !messageInputMapsOpen && (!suggestionsWouldOverlapWelcome || messageInputRecentlyFocused) && (viewportHeight > 670 || messageInputRecentlyFocused)}
                             <NewChatSuggestions
                                 messageInputContent={liveInputText}
                                 onSuggestionClick={handleSuggestionClick}
                                 onChatNavigate={handleChatNavigate}
                             />
                         {/if}


                        <!-- Banner for non-incognito chats when incognito mode is active -->
                        {#if $incognitoMode && currentChat && !currentChat.is_incognito && !showWelcome}
                            <div class="incognito-mode-applies-banner" transition:fade={{ duration: 200 }}>
                                <div class="incognito-mode-applies-icon">
                                    <div class="icon settings_size subsetting_icon incognito"></div>
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

                        <!-- Fork progress banner - shown while this chat is being used as a fork source -->
                        {#if currentChat?.chat_id && $forkProgressStore.status === 'running' && $forkProgressStore.sourceChatId === currentChat.chat_id}
                            <ForkProgressBanner />
                        {/if}

                        <!-- Follow-up suggestions have been moved to ChatHistory.svelte
                             so they appear below the last assistant message without requiring
                             the user to click the message input first. -->

                        <!-- App settings/memories permission dialog has been moved to ChatHistory.svelte -->
                        <!-- This allows it to scroll with messages instead of being fixed at the bottom -->

                        <!-- Read-only indicator for shared chats -->
                        {#if currentChat && !chatOwnershipResolved && $authStore.isAuthenticated}
                            <div class="read-only-indicator" transition:fade={{ duration: 200 }}>
                                <div class="read-only-icon">🔒</div>
                                <p class="read-only-text">{$text('chat.read_only_shared')}</p>
                            </div>
                        {/if}

                        <!-- Chat search suggestions — shown when typing in an open chat's message input.
                             Searches existing chats and shows matching results as horizontal cards.
                             Hidden entirely when no results found (unlike NewChatSuggestions which shows defaults). -->
                        {#if !showWelcome && !messageInputMapsOpen}
                            <ChatSearchSuggestions
                                messageInputContent={liveInputText}
                                onChatNavigate={handleChatNavigate}
                                currentChatId={currentChat?.chat_id}
                            />
                        {/if}

                        <!-- Pass currentChat?.id or temporaryChatId to MessageInput -->
                        <!-- Hide for newsletter/legal chats (read-only); show for demo/example/intro/regular chats -->
                        {#if !(currentChat && (isNewsletterChat(currentChat.chat_id) || isLegalChat(currentChat.chat_id))) && (chatOwnershipResolved || !$authStore.isAuthenticated)}
                            <MessageInput
                                bind:this={messageInputFieldRef}
                                currentChatId={currentChat?.chat_id || temporaryChatId}
                                showActionButtons={showActionButtons}
                                activeFocusId={!showWelcome ? activeFocusId : null}
                                activeFocusAppId={!showWelcome ? activeFocusAppId : null}
                                activeFocusModeMetadata={!showWelcome ? activeFocusModeMetadata : null}
                                onFocusPillDeepLink={() => {
                                    if (activeFocusAppId && activeFocusModeKey) {
                                        settingsDeepLink.set(`app_store/${activeFocusAppId}/focus/${activeFocusModeKey}`);
                                        panelState.openSettings();
                                    }
                                }}
                                onFocusPillDeactivate={() => {
                                    if (activeFocusId) {
                                        handleFocusModeDeactivation(activeFocusId);
                                        activeFocusId = null;
                                    }
                                }}
                                isIncognitoMode={!!(currentChat?.is_incognito || (showWelcome && $incognitoMode))}
                                onIncognitoPillDeactivate={() => {
                                    incognitoMode.set(false);
                                }}
                                on:codefullscreen={handleCodeFullscreen}
                                on:imagefullscreen={handleImageFullscreen}
                                on:pdffullscreen={handlePdfFullscreen}
                                on:recordingfullscreen={handleRecordingFullscreen}
                                on:sendMessage={handleSendMessage}
                                on:heightchange={handleInputHeightChange}
                                on:draftSaved={handleDraftSaved}
                                on:textchange={(e) => { 
                                    const t = (e.detail?.text || '');
                                    liveInputText = t;
                                    // NOTE: messageInputHasContent is NOT set here from text alone —
                                    // bind:hasContent below is the authoritative source and correctly
                                    // accounts for embeds (images, files) even when there is no text.
                                }}
                                 bind:isFullscreen
                                 bind:hasContent={messageInputHasContent}
                                 bind:isFocused={messageInputFocused}
                                 bind:isMapsOpen={messageInputMapsOpen}
                                 {containerRect}
                             />
                        {/if}
                    </div>
                </div>
                {/if}
            </div>
            {/if}

            {#if showWikiFullscreen && wikiFullscreenData}
                <div
                    class="fullscreen-embed-container"
                    class:side-panel={showSideBySideLayout}
                    class:overlay-mode={!showSideBySideLayout}
                    class:side-by-side-entering={sideBySideAnimating && sideBySideAnimationDirection === 'enter'}
                    class:side-by-side-exiting={sideBySideAnimating && sideBySideAnimationDirection === 'exit'}
                    class:side-by-side-minimizing={sideBySideAnimating && sideBySideAnimationDirection === 'minimize'}
                    class:side-by-side-restoring={sideBySideAnimating && sideBySideAnimationDirection === 'restore'}
                >
                    <!-- Key on wikiTitle so clicking another wiki link remounts the fullscreen
                         with the new article (fresh fetch, reset state) — same pattern as
                         regular embed fullscreen keyed on ${embedId}:${focusChildEmbedId}. -->
                    {#key wikiFullscreenData.wikiTitle}
                        {#await import('./embeds/wiki/WikipediaFullscreen.svelte') then module}
                            <module.default
                                wikiTitle={wikiFullscreenData.wikiTitle}
                                wikidataId={wikiFullscreenData.wikidataId}
                                displayText={wikiFullscreenData.displayText}
                                thumbnailUrl={wikiFullscreenData.thumbnailUrl}
                                description={wikiFullscreenData.description}
                                onClose={() => { showWikiFullscreen = false; wikiFullscreenData = null; }}
                            />
                        {/await}
                    {/key}
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

            {#if showImageEmbedFullscreen}
                <ImageEmbedFullscreen
                    data={{
                        decodedContent: {
                            src: imageEmbedFullscreenData.src,
                            s3_base_url: imageEmbedFullscreenData.s3BaseUrl,
                            files: imageEmbedFullscreenData.s3Files,
                            aes_key: imageEmbedFullscreenData.aesKey,
                            aes_nonce: imageEmbedFullscreenData.aesNonce,
                            filename: imageEmbedFullscreenData.filename,
                            is_authenticated: imageEmbedFullscreenData.isAuthenticated,
                            file_size: imageEmbedFullscreenData.fileSize,
                            file_type: imageEmbedFullscreenData.fileType,
                            ai_detection: imageEmbedFullscreenData.aiDetection,
                        },
                    }}
                    onClose={handleCloseImageEmbedFullscreen}
                />
            {/if}

            {#if showPdfEmbedFullscreen}
                <PDFEmbedFullscreen
                    data={{
                        decodedContent: {
                            filename: pdfFullscreenData.filename,
                            page_count: pdfFullscreenData.pageCount,
                        },
                    }}
                    embedId={pdfFullscreenData.embedId}
                    onClose={handleClosePdfFullscreen}
                />
            {/if}

            {#if showPdfReadFullscreen}
                <PdfReadEmbedFullscreen
                    embedId={pdfReadFullscreenData.embedId}
                    filename={pdfReadFullscreenData.filename}
                    pagesReturned={pdfReadFullscreenData.pagesReturned}
                    pagesSkipped={pdfReadFullscreenData.pagesSkipped}
                    textContent={pdfReadFullscreenData.textContent}
                    onClose={handleClosePdfReadFullscreen}
                />
            {/if}

            {#if showPdfSearchFullscreen}
                <PdfSearchEmbedFullscreen
                    embedId={pdfSearchFullscreenData.embedId}
                    filename={pdfSearchFullscreenData.filename}
                    query={pdfSearchFullscreenData.query}
                    totalMatches={pdfSearchFullscreenData.totalMatches}
                    truncated={pdfSearchFullscreenData.truncated}
                    matches={pdfSearchFullscreenData.matches}
                    onClose={handleClosePdfSearchFullscreen}
                />
            {/if}

            {#if showRecordingFullscreen}
                <RecordingEmbedFullscreen
                    data={{
                        decodedContent: {
                            transcript: recordingFullscreenData.transcript,
                            blob_url: recordingFullscreenData.blobUrl,
                            filename: recordingFullscreenData.filename,
                            duration: recordingFullscreenData.duration,
                            s3_files: recordingFullscreenData.s3Files,
                            s3_base_url: recordingFullscreenData.s3BaseUrl,
                            aes_key: recordingFullscreenData.aesKey,
                            aes_nonce: recordingFullscreenData.aesNonce,
                            model: recordingFullscreenData.model,
                        },
                    }}
                    embedId={recordingFullscreenData.embedId}
                    isEditable={recordingFullscreenData.isEditable}
                    onTranscriptChange={handleRecordingTranscriptChange}
                    onClose={handleCloseRecordingFullscreen}
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
                <!-- Sample data banner — shown only when previewing an app-store
                     skill example backed by synthetic fixture data (e.g. maps,
                     health, home, events). Helps users understand the people,
                     places and prices on these cards are not real. -->
                {#if embedFullscreenData?.decodedContent?.is_store_example}
                    <div class="store-example-banner" data-testid="store-example-banner">
                        {$text('settings.app_store_examples.banner.sample_data')}
                    </div>
                {/if}
                <!-- Key block forces complete recreation when embed changes -->
                <!-- This resets internal component state (e.g., selectedWebsite in WebSearchEmbedFullscreen) -->
                <!-- Without this, switching between same-type embeds would preserve stale child overlay state -->
                <!-- Also key on focusChildEmbedId: clicking a different inline badge of the same parent embed
                     (same embedId, same type) must still re-mount the fullscreen so it opens the correct child. -->
                {#key `${embedFullscreenData.embedId}:${embedFullscreenData.focusChildEmbedId ?? ''}`}
                <!-- Data-driven embed fullscreen routing via embedFullscreenResolver.
                     Each component receives a standardized `data` prop and extracts its own fields.
                     Architecture: docs/architecture/frontend/data-driven-embed-fullscreen-routing.md -->
                {@const registryKey = resolveRegistryKey(
                    registryNormalizeEmbedType(embedFullscreenData.embedType || ''),
                    embedFullscreenData.decodedContent ?? undefined
                )}
                {#if registryKey && hasFullscreenComponent(registryKey)}
                    {#await loadFullscreenComponent(registryKey) then FullscreenComponent}
                        {#if FullscreenComponent}
                            <FullscreenComponent
                                data={{
                                    decodedContent: embedFullscreenData.decodedContent ?? {},
                                    attrs: embedFullscreenData.attrs,
                                    embedData: embedFullscreenData.embedData,
                                    focusChildEmbedId: embedFullscreenData.focusChildEmbedId,
                                    restoreFromPip: embedFullscreenData.restoreFromPip,
                                    highlightQuoteText: embedFullscreenData.highlightQuoteText,
                                    focusLineRange: embedFullscreenData.focusLineRange,
                                }}
                                embedId={embedFullscreenData.embedId}
                                onClose={handleCloseEmbedFullscreen}
                                {hasPreviousEmbed}
                                {hasNextEmbed}
                                onNavigatePrevious={handleNavigatePreviousEmbed}
                                onNavigateNext={handleNavigateNextEmbed}
                                navigateDirection={embedNavigateDirection}
                                showChatButton={showChatButtonInFullscreen}
                                onShowChat={handleShowChat}
                                piiMappings={cumulativePIIMappingsArray}
                                piiRevealed={piiRevealed}
                                chatId={currentChat?.chat_id}
                            />
                        {/if}
                    {/await}
                {:else}
                    <!-- Fallback for unknown/unregistered embed types -->
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
                        class:pip-top-left={videoIframeState.isPipMode && pipCorner === 'top-left'}
                        class:pip-top-right={videoIframeState.isPipMode && pipCorner === 'top-right'}
                        class:pip-bottom-left={videoIframeState.isPipMode && pipCorner === 'bottom-left'}
                        class:pip-bottom-right={videoIframeState.isPipMode && pipCorner === 'bottom-right'}
                        class:fade-out={videoIframeState.isClosing}
                        style={videoIframeContainerInlineStyle}
                    >
                        <VideoIframe
                            videoId={videoIframeState.videoId}
                            title={videoIframeState.title || 'Video'}
                            embedUrl={videoIframeState.embedUrl}
                            isPipMode={videoIframeState.isPipMode}
                            onPipOverlayClick={handlePipOverlayClick}
                            onMoveToCorner={handleMovePipToCorner}
                        />
                    </div>
                {/await}
            {/if}
            
            <!-- Chat video fullscreen — any chat with a video in its metadata.
                 Uses the same .fullscreen-embed-container as wiki/embed fullscreens
                 so UnifiedEmbedFullscreen fills ActiveChat correctly (position:absolute). -->
            {#if $chatVideoFullscreenStore}
                <div
                    class="fullscreen-embed-container"
                    class:side-panel={showSideBySideLayout}
                    class:overlay-mode={!showSideBySideLayout}
                    data-testid="intro-video-fullscreen"
                >
                    <DirectVideoEmbedFullscreen
                        mp4Url={$chatVideoFullscreenStore.mp4Url}
                        title={$chatVideoFullscreenStore.title}
                        onClose={() => {
                            closeChatVideoFullscreen();
                            history.replaceState(null, '', window.location.pathname + window.location.search);
                        }}
                    />
                </div>
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

<!-- Resume Card Context Menu (right-click / long-press on welcome screen chat cards) -->
{#if resumeCardContextMenuShow && resumeCardContextMenuChat}
    <ChatContextMenu
        x={resumeCardContextMenuX}
        y={resumeCardContextMenuY}
        show={resumeCardContextMenuShow}
        chat={resumeCardContextMenuChat}
        hideDelete={false}
        hideCopy={false}
        hideDownload={false}
        downloading={resumeCardContextMenuDownloading}
        on:close={handleResumeCardContextMenuAction}
        on:download={handleResumeCardContextMenuAction}
        on:copy={handleResumeCardContextMenuAction}
        on:hide={handleResumeCardContextMenuAction}
        on:unhide={handleResumeCardContextMenuAction}
        on:pin={handleResumeCardContextMenuAction}
        on:unpin={handleResumeCardContextMenuAction}
        on:markUnread={handleResumeCardContextMenuAction}
        on:markRead={handleResumeCardContextMenuAction}
        on:delete={handleResumeCardContextMenuAction}
        on:enterSelectMode={handleResumeCardContextMenuAction}
        on:unselect={handleResumeCardContextMenuAction}
        on:selectChat={handleResumeCardContextMenuAction}
    />
{/if}

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
        transition: opacity 0.3s ease, box-shadow 0.6s ease;
        overflow: hidden;
        box-sizing: border-box;
    }

    /* ===========================================
       Rainbow border ring + outer glow while AI is typing
       Uses @property --chat-gradient-angle to animate the conic-gradient rotation
       (same technique as ThinkingSection — smooth gradient spin, no transform artifacts)

       Overlay approach: the ring is painted ON TOP of content via ::after at
       z-index: var(--z-index-dropdown-1) with pointer-events: none.  A CSS mask cuts out the interior
       so only a 2px ring is visible.  This avoids the old isolation/z-index:-1
       technique where child elements flush to the edges would cover the ring.
       =========================================== */

    @property --chat-gradient-angle {
        syntax: '<angle>';
        initial-value: 0deg;
        inherits: false;
    }

    /* ::after — rotating rainbow ring painted ON TOP of all content.
     * Always present but invisible (opacity: 0) until .ai-typing is added.
     * pointer-events: none so it never blocks clicks on content underneath.
     * CSS mask subtracts the inner area, leaving only a 2px border ring visible. */
    .active-chat-container::after {
        content: '';
        position: absolute;
        inset: 0;
        border-radius: 17px;
        background: conic-gradient(
            from var(--chat-gradient-angle, 0deg),
            #ff2d55, #ff6b2b, #ffd60a,
            #30d158, #32ade6, #bf5af2,
            #ff2d55
        );
        z-index: var(--z-index-dropdown-1);
        pointer-events: none;
        opacity: 0;
        filter: blur(1.5px);
        animation: chat-rainbow-spin 3s linear infinite;
        /* Ring mask: the padding creates the ring thickness (2px).
         * The two gradient layers + exclude composite subtract the content-box
         * from the border-box, leaving only the padded ring area visible. */
        padding: var(--spacing-1);
        -webkit-mask:
            linear-gradient(#fff 0 0) content-box,
            linear-gradient(#fff 0 0);
        -webkit-mask-composite: xor;
        mask:
            linear-gradient(#fff 0 0) content-box,
            linear-gradient(#fff 0 0);
        mask-composite: exclude;
    }

    .active-chat-container.ai-typing::after {
        opacity: 1;
    }

    @keyframes chat-rainbow-spin {
        from { --chat-gradient-angle: 0deg; }
        to   { --chat-gradient-angle: 360deg; }
    }

    /* Outer glow — soft static multi-color bloom that fades in with the border.
     * No color-cycling animation; the spinning border ring provides all the motion. */
    .active-chat-container.ai-typing {
        box-shadow:
            0 0  8px  2px rgba(191,  90, 242, 0.18),
            0 0 20px  6px rgba( 50, 173, 230, 0.12),
            0 0 40px 14px rgba(255,  45,  85, 0.08);
    }

    /* Dark mode: wider bloom, stronger opacity */
    :global(.dark) .active-chat-container.ai-typing {
        box-shadow:
            0 0 12px  4px rgba(191,  90, 242, 0.25),
            0 0 28px  8px rgba( 50, 173, 230, 0.16),
            0 0 48px 16px rgba(255,  45,  85, 0.10);
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
        gap: var(--spacing-5); /* Gap between chat card and fullscreen card */
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
        padding: var(--spacing-5);
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

    /* Sample-data banner — only rendered for synthetic app-store example
       embeds (is_store_example flag on decodedContent). Sits on top of
       the EmbedTopBar row via a high z-index + top offset that clears the
       action buttons. Pointer events disabled so the Close button stays
       clickable through it. */
    .store-example-banner {
        position: absolute;
        top: 12px;
        left: 50%;
        transform: translateX(-50%);
        z-index: calc(var(--z-index-dropdown) + 10);
        padding: 6px 14px;
        border-radius: 999px;
        background: rgba(0, 0, 0, 0.55);
        color: #fff;
        font-size: 0.78rem;
        font-weight: 500;
        line-height: 1.3;
        letter-spacing: 0.01em;
        white-space: nowrap;
        max-width: calc(100% - 160px);
        overflow: hidden;
        text-overflow: ellipsis;
        pointer-events: none;
        backdrop-filter: blur(8px);
        -webkit-backdrop-filter: blur(8px);
        box-shadow: 0 2px 8px rgba(0, 0, 0, 0.2);
    }
    
    /* Overlay mode (default): Absolute positioning over everything */
    .fullscreen-embed-container.overlay-mode {
        position: absolute;
        top: 0;
        left: 0;
        right: 0;
        bottom: 0;
        z-index: var(--z-index-dropdown);
    }
    
    /* Side panel mode: Flex child taking remaining space - styled as separate card */
    .fullscreen-embed-container.side-panel {
        flex: 1;
        min-width: 0;
        position: relative;
        z-index: var(--z-index-raised);
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
        padding: var(--spacing-5); /* Add padding to show gap around cards */
    }
    
    /* Ensure content-container fills the padded area */
    .active-chat-container.side-by-side-active .content-container {
        height: 100%;
    }
    
    /* Chat wrapper in side-by-side mode - background/shadow now in base .side-by-side-chat class */
    /* to ensure visibility during animation */

    .center-content {
        position: absolute;
        /*
         * Center vertically in the space below the daily inspiration banner.
         * Offset of 80px keeps welcome content clear of top-left actions.
         */
        top: calc(58% + 80px);
        left: 50%;
        transform: translate(-50%, -50%);
        text-align: center;
        /* Render above ChatHistory (which is also position:absolute and comes after in DOM) */
        z-index: var(--z-index-raised);
        /* Allow clicks to pass through the non-interactive parts to ChatHistory underneath,
           but re-enable pointer-events on interactive children (resume card button) */
        pointer-events: none;
        display: flex;
        flex-direction: column;
        align-items: center;
        /*
         * CRITICAL: must match the chat-side positioned ancestor width.
         * Without this, center-content has no explicit width and grows to match its
         * widest child (recent-chats-scroll-container). That child uses width:100% +
         * padding:calc(50%-150px), creating a circular dependency that inflates the
         * container to thousands of pixels — breaking centering and scroll entirely.
         */
        width: 100%;
    }

    .team-profile {
        display: flex;
        flex-direction: column;
        align-items: center;
        gap: var(--spacing-10);
    }


    .welcome-text h2 {
        margin: 0;
        color: var(--color-grey-80);
        font-size: var(--font-size-h2-mobile);
        font-weight: 600;
    }

    .welcome-text p {
        margin: 8px 0 0;
        color: var(--color-grey-60);
        font-size: var(--font-size-p);
    }

    .message-input-wrapper {
        position: relative; /* For absolute positioning of typing indicator if needed */
    }

    .typing-indicator {
        display: flex;
        flex-direction: column;
        align-items: center;
        justify-content: flex-end;
        gap: var(--spacing-1);
        text-align: center;
        font-size: 1rem;
        color: var(--color-grey-60);
        padding: var(--spacing-0) var(--spacing-8) var(--spacing-3);
        font-style: italic;
        /* Gradient background so the text remains readable when positioned over chat messages.
           Uses the active chat background color (--color-grey-20) fading from transparent at the top
           to match the chat area background seamlessly. Taller gradient to cover the larger text. */
        background: linear-gradient(
            to bottom,
            transparent 0%,
            transparent 14%,
            var(--color-grey-20) 56%,
            var(--color-grey-20) 100%
        );
        position: relative;
        z-index: var(--z-index-raised);
    }

    .typing-indicator + .message-input-container {
        padding-top: 0;
    }
    
    /* Primary line: "{mate} is typing..." — prominent */
    .typing-indicator .indicator-primary-line {
        font-size: 1rem;
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
    
    /* Horizontal scroll container for resume + recent chat cards */
    .recent-chats-scroll-container {
        display: flex;
        flex-direction: row;
        align-items: center;
        gap: var(--spacing-8);
        overflow-x: auto;
        overflow-y: hidden;
        -webkit-overflow-scrolling: touch;
        scroll-behavior: smooth;
        scrollbar-width: none;
        -ms-overflow-style: none;
        /* Left padding = half container width minus half card width (300/2=150)
           so the first card starts centred relative to the chat-wrapper.
           box-sizing: border-box ensures padding is included in width: 100%
           so the element never exceeds the center-content container bounds. */
        padding: 12px 48px 12px calc(50% - 150px);
        box-sizing: border-box;
        pointer-events: auto;
        width: 100%;
        max-width: 100%;
    }

    .recent-chats-scroll-container::-webkit-scrollbar {
        display: none;
    }

    /* Make resume-chat-card a fixed-width flex item inside scroll container */
    .recent-chats-scroll-container .resume-chat-card {
        min-width: 300px;
        max-width: 300px;
        flex-shrink: 0;
    }

    /* Make resume-chat-large-card a fixed-width flex item inside scroll container */
    .recent-chats-scroll-container .resume-chat-large-card {
        flex-shrink: 0;
    }

    /* "+N" overflow pill matching card height */
    .recent-chat-overflow {
        display: flex;
        align-items: center;
        justify-content: center;
        width: 56px;
        min-width: 56px;
        height: 200px;
        margin-top: var(--spacing-8);
        border-radius: var(--radius-8);
        background: var(--color-grey-20, rgba(0, 0, 0, 0.07));
        border: 1.5px dashed var(--color-grey-40);
        font-size: var(--font-size-small);
        font-weight: 700;
        color: var(--color-grey-60);
        cursor: pointer;
        flex-shrink: 0;
        transition: background var(--duration-fast) var(--easing-default), color var(--duration-fast) var(--easing-default);
        pointer-events: auto;
    }

    .recent-chat-overflow.compact {
        width: clamp(54px, 15vw, 66px);
        min-width: clamp(54px, 15vw, 66px);
        height: 44px;
        border-radius: 18px;
        padding: 0 10px;
        font-size: var(--font-size-xs);
        line-height: 1;
    }

    .recent-chat-overflow:hover {
        background: var(--color-grey-30, rgba(0, 0, 0, 0.12));
        color: var(--color-grey-80);
        border-color: var(--color-grey-50);
    }

    /* Resume chat card - shown in center-content below welcome greeting */
    .resume-chat-card {
        position: relative;
        display: flex;
        align-items: center;
        gap: var(--spacing-6);
        width: 100%;
        max-width: 400px;
        min-height: 44px;
        padding: var(--spacing-5) var(--spacing-8);
        background-color: transparent;
        border: 1px solid rgba(255, 255, 255, 0.14);
        border-radius: var(--radius-8);
        cursor: pointer;
        overflow: hidden;
        box-shadow:
            0 8px 24px rgba(0, 0, 0, 0.16),
            0 2px 6px rgba(0, 0, 0, 0.1);
        transition:
            background-position 0.25s ease,
            transform 0.15s ease-out,
            box-shadow 0.2s ease-out,
            border-color 0.2s ease;
        background-size: 140% 140%;
        background-position: 0% 50%;
        text-align: left;
        pointer-events: auto; /* Re-enable clicks (parent center-content has pointer-events: none) */
    }

    .resume-chat-card:hover {
        background-color: transparent;
        border-color: rgba(255, 255, 255, 0.24);
        background-position: 100% 50%;
        transform: translateY(-1px);
        box-shadow:
            0 10px 28px rgba(0, 0, 0, 0.18),
            0 3px 8px rgba(0, 0, 0, 0.12);
    }

    .resume-chat-card:active {
        background-color: transparent;
        transform: scale(0.98);
        box-shadow:
            0 4px 12px rgba(0, 0, 0, 0.12),
            0 1px 3px rgba(0, 0, 0, 0.08);
        filter: none;
    }

    .resume-chat-card:focus {
        outline: 2px solid rgba(255, 255, 255, 0.5);
        outline-offset: 2px;
    }

    /* Draft-only card: matches sidebar draft-only-layout (label + preview, no gradient) */
    .resume-chat-draft-card {
        background: var(--color-grey-4);
        border-color: var(--color-grey-10);
    }

    .resume-chat-draft-card:hover {
        background: var(--color-grey-6);
        border-color: var(--color-grey-15);
    }

    .resume-chat-draft-content {
        display: flex;
        flex-direction: column;
        gap: var(--spacing-1);
        flex: 1;
        min-width: 0;
    }

    .resume-chat-draft-label {
        font-size: var(--font-size-p);
        color: var(--color-grey-60);
        font-weight: 400;
    }

    .resume-chat-draft-preview {
        font-size: var(--font-size-p);
        font-weight: 500;
        color: var(--color-font-primary);
        overflow: hidden;
        text-overflow: ellipsis;
        white-space: nowrap;
    }

    /* Pin badge — top-right corner of large and compact cards */
    .resume-card-pin-badge {
        position: absolute;
        top: 12px;
        right: 12px;
        display: flex;
        align-items: center;
        justify-content: center;
        width: 32px;
        height: 32px;
        border-radius: 50%;
        background: rgba(255, 255, 255, 0.22);
        backdrop-filter: blur(4px);
        z-index: var(--z-index-raised-2);
    }

    .resume-card-pin-badge.compact {
        top: 50%;
        right: 38px;
        transform: translateY(-50%);
        width: 26px;
        height: 26px;
    }

    .resume-card-pin-badge :global(svg) {
        transform: rotate(45deg);
    }

    .resume-chat-compact-icon {
        width: 18px;
        min-width: 18px;
        height: 18px;
        display: flex;
        align-items: center;
        justify-content: center;
        flex-shrink: 0;
        opacity: 0.96;
    }

    .resume-chat-compact-icon :global(svg) {
        width: 18px;
        height: 18px;
    }

    .resume-chat-content {
        flex: 1;
        min-width: 0;
        overflow: hidden;
    }

    /* Credits-error variant of the resume card content — mirrors Chat.svelte draft-only-layout */
    .resume-chat-credits-content {
        display: flex;
        flex-direction: column;
    }

    .resume-chat-credits-label {
        font-size: var(--font-size-small);
        color: rgba(255, 255, 255, 0.78);
    }

    .resume-chat-credits-preview {
        font-size: null;
        font-weight: 600;
        color: rgba(255, 255, 255, 0.96);
        white-space: nowrap;
        overflow: hidden;
        text-overflow: ellipsis;
        display: block;
        margin-top: var(--spacing-1);
    }

    .resume-chat-title {
        font-size: null;
        font-weight: 600;
        color: rgba(255, 255, 255, 0.96);
        white-space: nowrap;
        overflow: hidden;
        text-overflow: ellipsis;
        display: block;
        text-shadow: 0 1px 4px rgba(0, 0, 0, 0.22);
    }

    .resume-chat-arrow {
        display: flex;
        align-items: center;
        justify-content: center;
        flex-shrink: 0;
        opacity: 0.82;
    }

    /* ===========================================
       Large gradient card — tall viewports (≥800px)
       Matches the ChatEmbedPreview design used in the
       for-everyone chat's linked-chat cards.
       =========================================== */

    .resume-chat-large-card {
        position: relative;
        /* Desktop dimensions match ChatEmbedPreview */
        width: 300px;
        min-width: 300px;
        max-width: 300px;
        height: 200px;
        min-height: 200px;
        max-height: 200px;
        border-radius: 30px;
        overflow: hidden;
        display: flex;
        align-items: center;
        justify-content: center;
        cursor: pointer;
        user-select: none;
        -webkit-user-select: none;
        -webkit-touch-callout: none;
        border: none;
        padding: 0;
        margin-right: 0;
        min-width: 0;
        filter: none;
        background-color: transparent;
        scale: 1;
        /* Re-enable pointer events (parent center-content has pointer-events: none) */
        pointer-events: auto;
        /* Shadow matching ChatEmbedPreview */
        box-shadow:
            0 8px 24px rgba(0, 0, 0, 0.16),
            0 2px 6px rgba(0, 0, 0, 0.1);
        transition:
            transform 0.15s ease-out,
            box-shadow 0.2s ease-out;
    }

    /* Override global button hover/active rules from styles/buttons.css */
    .resume-chat-large-card:hover,
    .resume-chat-large-card:active,
    .resume-chat-large-card.hovering {
        background-color: transparent;
        filter: none;
        scale: 1;
    }

    .resume-chat-large-card.hovering {
        box-shadow:
            0 4px 12px rgba(0, 0, 0, 0.12),
            0 1px 3px rgba(0, 0, 0, 0.08);
    }

    /* CSS fallback hover (non-JS scenarios) */
    .resume-chat-large-card:hover:not(.hovering) {
        transform: scale(0.98);
        box-shadow:
            0 4px 12px rgba(0, 0, 0, 0.12),
            0 1px 3px rgba(0, 0, 0, 0.08);
    }

    .resume-chat-large-card:active {
        transform: scale(0.96) !important;
        transition: transform 0.05s ease-out;
    }

    .resume-chat-large-card:focus {
        outline: 2px solid rgba(255, 255, 255, 0.5);
        outline-offset: 2px;
    }

    /* Centered content overlay */
    .resume-large-content {
        position: relative;
        z-index: var(--z-index-raised-3);
        display: flex;
        flex-direction: column;
        align-items: center;
        gap: var(--spacing-2);
        padding: var(--spacing-8) var(--spacing-12);
        max-width: 260px;
        width: 100%;
        /* Ensure text is readable over the gradient orbs */
        text-shadow: 0 1px 4px rgba(0, 0, 0, 0.3);
    }

    .resume-large-icon {
        width: 32px;
        height: 32px;
        display: flex;
        align-items: center;
        justify-content: center;
        flex-shrink: 0;
    }

    .resume-large-title {
        display: -webkit-box;
        -webkit-line-clamp: 2;
        line-clamp: 2;
        -webkit-box-orient: vertical;
        overflow: hidden;
        font-size: var(--font-size-p);
        font-weight: 700;
        /* Always white regardless of theme — sits on the branded gradient resume card. */
        color: var(--color-font-button);
        text-align: center;
        line-height: 1.3;
        max-width: 100%;
    }

    /* Summary line below the title — matches ChatEmbedPreview card-summary */
    .resume-large-summary {
        margin: 2px 0 0;
        font-size: var(--font-size-xxs);
        font-weight: 500;
        color: rgba(255, 255, 255, 0.85);
        line-height: 1.4;
        text-align: center;
        /* Clamp to 4 lines */
        display: -webkit-box;
        -webkit-line-clamp: 4;
        line-clamp: 4;
        -webkit-box-orient: vertical;
        overflow: hidden;
    }

    /* ── Living gradient orbs ──────────────────────────────────────────────────
       Same technique as ChatHeader.svelte and DailyInspirationBanner.svelte.
       The card is smaller (300×200px) so orbs are proportionally smaller too.
       --orb-color-a / --orb-color-b are set by getResumeLargeCardStyle(). */

    .resume-large-orbs {
        position: absolute;
        inset: 0;
        z-index: -1;
        pointer-events: none;
        overflow: hidden;
        border-radius: 30px; /* match card border-radius so orbs don't bleed */
    }

    .resume-orb {
        position: absolute;
        /* Orbs sized ~same as the card so they fill it generously */
        width: 280px;
        height: 240px;
        background: radial-gradient(
            ellipse at center,
            var(--orb-color-b) 0%,
            var(--orb-color-b) 40%,
            transparent 85%
        );
        filter: blur(22px);
        opacity: 0.35;
        will-change: transform, border-radius;
    }

    .resume-orb-1 {
        top: -60px;
        left: -70px;
        animation:
            orbMorph1 11s ease-in-out infinite,
            resumeOrbDrift1 19s ease-in-out infinite;
    }

    .resume-orb-2 {
        bottom: -80px;
        right: -80px;
        width: 260px;
        height: 220px;
        animation:
            orbMorph2 13s ease-in-out infinite,
            resumeOrbDrift2 23s ease-in-out infinite;
    }

    .resume-orb-3 {
        top: -10px;
        left: 25%;
        width: 200px;
        height: 180px;
        opacity: 0.38;
        animation:
            orbMorph3 17s ease-in-out infinite,
            resumeOrbDrift3 29s ease-in-out infinite;
    }

    /* Orb morph uses shared orbMorph1/2/3 keyframes (animations.css).
       Orb drift uses smaller resumeOrbDrift1/2/3 keyframes (animations.css). */
    @media (prefers-reduced-motion: reduce) {
        .resume-orb { animation: none !important; }
    }

    /* ── Large decorative icons at card corners ─────────────────────────────
       Two-phase: decoEnter (one-shot) → decoFloat (16s circular orbit).
       Smaller orbit radius than banners to suit the 300×200 card.
       Right icon starts half a cycle ahead for opposing orbital phase.
       All @keyframes in animations.css. */
    .resume-large-deco {
        position: absolute;
        width: 80px;
        height: 80px;
        display: flex;
        align-items: center;
        justify-content: center;
        z-index: var(--z-index-raised);
        pointer-events: none;
        /* Smaller orbit radius for the compact card */
        --float-rx: 7px;
        --float-ry: 8px;
        --deco-target-opacity: 0.3;
        animation:
            decoEnter 0.6s ease-out 0.1s both,
            decoFloat 16s linear 0.7s infinite;
    }

    .resume-large-deco-left {
        left: -10px;
        bottom: -8px;
        --deco-rotate: -15deg;
    }

    .resume-large-deco-right {
        right: -10px;
        bottom: -8px;
        --deco-rotate: 15deg;
        /* Negative delay: start as if 8s have already elapsed (half-cycle offset).
           Positive delay would freeze the icon for 8.7s then snap — use negative
           to begin mid-orbit immediately with no wait or jump. */
        animation-delay: 0.1s, -8s;
    }

    @media (prefers-reduced-motion: reduce) {
        .resume-large-deco {
            animation: decoEnter 0.6s ease-out 0.1s both !important;
        }
    }

    /* Ensure Lucide SVGs inside deco elements render at the right size */
    .resume-large-deco :global(svg) {
        width: 80px !important;
        height: 80px !important;
    }

    
    /* Read-only indicator for shared chats */
    .read-only-indicator {
        display: flex;
        flex-direction: column;
        align-items: center;
        justify-content: center;
        padding: var(--spacing-12) var(--spacing-8);
        margin-bottom: var(--spacing-6);
        background-color: var(--color-grey-10, #f0f0f0);
        border: 1px solid var(--color-grey-30, #d0d0d0);
        border-radius: var(--radius-3);
        text-align: center;
    }
    
    .read-only-icon {
        font-size: var(--font-size-xxxl);
        margin-bottom: var(--spacing-6);
        opacity: 0.7;
    }
    
    .read-only-text {
        font-size: var(--font-size-small);
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
        /* Flex child instead of position:absolute — this lets iOS Safari's
         * virtual keyboard push the input up naturally via dvh + flex layout,
         * instead of the input being anchored behind the keyboard. */
        flex-shrink: 0;
        width: 100%;
    }
    

    .chat-wrapper.fullscreen .message-input-wrapper { /* Changed from .message-input-container */
        width: 35%;
        min-width: 400px;
        padding: var(--spacing-10);
        align-items: flex-start;
        display: flex; /* To allow typing indicator above input */
        flex-direction: column;
    }
    
    .chat-wrapper.fullscreen .message-input-container {
         width: 100%; /* Input container takes full width of its wrapper */
    }


    .message-input-container :global(> *:not(.suggestions-wrapper)) {
        max-width: 629px;
        width: 100%;
    }

    /* Adjust input padding and typing indicator for narrow containers */
    .active-chat-container.narrow .message-input-container {
        padding: var(--spacing-5);
    }
    
    .active-chat-container.narrow .typing-indicator {
        font-size: 0.75rem;
    }


    .active-chat-container.dimmed {
        opacity: 0.3;
    }

    /* Banner for non-incognito chats when incognito mode is active */
    .incognito-mode-applies-banner {
        width: 100%;
        min-height: 40px;
        background-color: var(--color-grey-15);
        border: 1px solid var(--color-grey-30);
        border-radius: var(--radius-3);
        display: flex;
        align-items: center;
        justify-content: flex-start;
        gap: var(--spacing-5);
        padding: 10px 14px;
        margin-bottom: var(--spacing-6);
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
        font-size: var(--font-size-xs);
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
        transition: all var(--duration-slow) var(--easing-default);
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
        padding-right: var(--spacing-10);
    }

    .active-chat-container.extra-wide .chat-wrapper.fullscreen .message-input-wrapper {
        width: 35%;
        min-width: 400px;
        padding: var(--spacing-10);
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
        flex-shrink: 0;
        width: 100%;
        /* padding for message-input-container is already 15px */
    }

    .chat-side {
        position: relative;
        display: flex;
        flex-direction: column;
        flex: 1;
        min-width: 0;
        min-height: 0; /* Allow flex to shrink below content height (required for iOS keyboard) */
        overflow: hidden;
        container-type: inline-size;
        container-name: chat-side;
    }

    /* Scroll navigation buttons - wide touch-friendly strips at top/bottom edge.
       The visible icon stays centered; the hit area extends horizontally for easy touch/click.
       Overrides global button styles from buttons.css (padding, min-width, height, shadow, etc.) */
    .scroll-nav-button {
        position: absolute;
        left: 50%;
        transform: translateX(-50%);
        z-index: var(--z-index-raised-2);
        width: 120px;
        height: 36px;
        min-width: unset;
        border-radius: 18px;
        border: none;
        background-color: transparent;
        cursor: pointer;
        display: flex;
        align-items: center;
        justify-content: center;
        opacity: 0.7;
        transition: opacity var(--duration-normal) var(--easing-default), background-color var(--duration-normal) var(--easing-default);
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
        top: 18px;
    }

    .scroll-to-bottom-button {
        bottom: 0px;
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
        right: 15px;
        display: flex;
        justify-content: space-between; /* Distribute space between left and right buttons */
        z-index: var(--z-index-raised);
    }

    /*
     * On the welcome screen the top-buttons row is placed in normal document flow
     * below the daily inspiration banner (rendered before it in the DOM).
     * This removes the absolute positioning so buttons appear below the banner
     * instead of overlapping it.
     */
    .top-buttons.top-buttons-flow {
        position: static;
        padding: 10px 15px 0;
        /* Ensure full width to keep justify-content: space-between working */
        width: 100%;
        box-sizing: border-box;
    }

    /* Adjust top-buttons position on small screens (absolute mode only) */
    @media (max-width: 730px) {
        .top-buttons:not(.top-buttons-flow) {
            top: 10px;
            left: 10px;
            right: 10px;
        }
    }

    /*
     * RTL layout fixes for top-buttons:
     * - Absolute mode: anchor to the right edge instead of the left.
     * - Flow mode (welcome screen): reverse the flex row so the buttons
     *   visually appear on the right / inline-end side of the row.
     */
    :global([dir="rtl"]) .top-buttons:not(.top-buttons-flow) {
        left: 15px;
        right: 15px;
    }

    @media (max-width: 730px) {
        :global([dir="rtl"]) .top-buttons:not(.top-buttons-flow) {
            left: 10px;
            right: 10px;
        }
    }

    :global([dir="rtl"]) .top-buttons.top-buttons-flow {
        flex-direction: row-reverse;
    }

    /*
     * Daily inspiration area wrapper.
     * No padding — the banner spans edge-to-edge within the chat-side container.
     * Horizontal padding is handled inside DailyInspirationBanner.svelte's .banner-inner.
     */
    .daily-inspiration-area {
        width: 100%;
        box-sizing: border-box;
    }

    /* Welcome content fade transition: on short viewports, the daily inspiration
       and welcome greeting fade out via CSS opacity when the message input is
       focused, instead of being removed from DOM.  This avoids ResizeObserver
       churn that caused an infinite recalculation loop with {#if} DOM toggles.
       visibility:hidden is delayed by 200ms so it kicks in AFTER opacity reaches
       0, preventing interaction with invisible content.  On fade-in (class
       removed), visibility:visible applies immediately via the base 0s delay. */
    .daily-inspiration-area,
    .center-content,
    .top-buttons {
        transition: opacity 200ms ease, visibility 0s 0s;
    }

    .daily-inspiration-area.welcome-hiding,
    .center-content.welcome-hiding,
    .top-buttons.welcome-hiding {
        opacity: 0;
        visibility: hidden;
        transition: opacity 200ms ease, visibility 0s 200ms;
    }

    /* Add styles for left and right button containers */
    .left-buttons {
        display: flex;
        gap: var(--spacing-5); /* Space between buttons */
    }

    .right-buttons {
        display: flex;
        gap: 25px; /* Space between buttons */
    }

    /* PII toggle button: subtle orange tint when PII is revealed (warns sensitive data exposed) */
    .pii-toggle-active {
        background-color: rgba(245, 158, 11, 0.3) !important;
    }

    /* Admin debug mode button: highlighted while debug mode is active. */
    .debug-mode-active {
        background-color: var(--color-warning);
    }

    /* Background wrapper for new chat button to ensure it's always visible */
    .new-chat-button-wrapper {
        background-color: var(--color-grey-10);
        border-radius: 40px;
        padding: var(--spacing-4);
        box-shadow: 0 2px 8px rgba(0, 0, 0, 0.15);
        display: flex;
        align-items: center;
        justify-content: center;
        transition: transform var(--duration-fast) var(--easing-in-out), box-shadow var(--duration-fast) var(--easing-in-out);
        cursor: pointer;
    }

    .new-chat-button-wrapper:hover {
        transform: scale(1.08);
        box-shadow: 0 4px 12px rgba(0, 0, 0, 0.2);
    }

    .new-chat-button-wrapper:active {
        transform: scale(0.95);
        box-shadow: 0 1px 4px rgba(0, 0, 0, 0.1);
    }

    /* New chat CTA: no extra wrapper background so the pill button stands out.
       Also cancel the wrapper's hover/active scale — the button handles its own scaling. */
    .new-chat-cta-wrapper {
        background-color: transparent;
        box-shadow: none;
        padding: 0;
    }

    .new-chat-cta-wrapper:hover {
        transform: scale(1);
        box-shadow: none;
    }

    .new-chat-cta-wrapper:active {
        transform: scale(1);
        box-shadow: none;
    }

    /* New chat button - same CTA color as Send, fully rounded (pill), white icon and text.
       Override global button styles from buttons.css (min-width, height, padding, filter).
       Height (41px) matches the icon buttons next to it (.new-chat-button-wrapper has 8px padding + 25px icon). */
    .new-chat-cta-button {
        display: inline-flex;
        align-items: center;
        justify-content: center;
        gap: var(--spacing-4);
        min-width: 0;
        height: 41px;
        padding: var(--spacing-4) var(--spacing-8);
        border: none;
        border-radius: var(--radius-full);
        background-color: var(--color-button-primary);
        color: white;
        font-weight: 500;
        cursor: pointer;
        transition: background-color var(--duration-fast) var(--easing-in-out), transform var(--duration-fast) var(--easing-in-out);
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
            padding: var(--spacing-4);
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
        transition: transform var(--duration-normal) var(--easing-in-out), opacity var(--duration-slow) var(--easing-default); /* added transform transition */
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
        width: 100%;
        max-width: 780px;
        box-sizing: border-box;
        z-index: var(--z-index-dropdown); /* Below fullscreen buttons but above chat content */
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
        z-index: var(--z-index-modal); /* Above everything in ActiveChat */
    }

    .video-iframe-fullscreen-container.pip-mode.pip-top-left {
        top: 20px;
        left: 20px;
        right: auto;
    }

    .video-iframe-fullscreen-container.pip-mode.pip-top-right {
        top: 20px;
        left: auto;
        right: 20px;
    }

    .video-iframe-fullscreen-container.pip-mode.pip-bottom-left {
        top: auto;
        bottom: 20px;
        left: 20px;
        right: auto;
    }

    .video-iframe-fullscreen-container.pip-mode.pip-bottom-right {
        top: auto;
        bottom: 20px;
        left: auto;
        right: 20px;
    }

    /* Responsive PiP for small screens */
    @media (max-width: 480px) {
        .video-iframe-fullscreen-container.pip-mode {
            width: 240px;
            max-width: 240px;
            top: 10px;
            right: 10px;
        }

        .video-iframe-fullscreen-container.pip-mode.pip-top-left {
            top: 10px;
            left: 10px;
            right: auto;
        }

        .video-iframe-fullscreen-container.pip-mode.pip-top-right {
            top: 10px;
            right: 10px;
            left: auto;
        }

        .video-iframe-fullscreen-container.pip-mode.pip-bottom-left {
            bottom: 10px;
            left: 10px;
            right: auto;
            top: auto;
        }

        .video-iframe-fullscreen-container.pip-mode.pip-bottom-right {
            bottom: 10px;
            right: 10px;
            left: auto;
            top: auto;
        }
    }

</style>
