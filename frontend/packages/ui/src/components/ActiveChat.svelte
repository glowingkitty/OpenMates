<script lang="ts">
    import MessageInput from './enter_message/MessageInput.svelte';
    import CodeFullscreen from './fullscreen_previews/CodeFullscreen.svelte';
    import ChatHistory from './ChatHistory.svelte';
    import NewChatSuggestions from './NewChatSuggestions.svelte';
    import FollowUpSuggestions from './FollowUpSuggestions.svelte';
    import { isMobileView, loginInterfaceOpen } from '../stores/uiStateStore';
    import Login from './Login.svelte';
    import { text } from '@repo/ui';
    import { fade, fly } from 'svelte/transition';
    import { createEventDispatcher, tick, onMount, onDestroy } from 'svelte'; // Added onDestroy
    import { authStore, logout } from '../stores/authStore'; // Import logout action
    import { panelState } from '../stores/panelStateStore'; // Added import
    import type { Chat, Message as ChatMessageModel, TiptapJSON, MessageStatus, AITaskInitiatedPayload } from '../types/chat'; // Added Message, TiptapJSON, MessageStatus, AITaskInitiatedPayload
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
    import VideoTranscriptEmbedPreview from './embeds/videos/VideoTranscriptEmbedPreview.svelte';
    import VideoTranscriptEmbedFullscreen from './embeds/videos/VideoTranscriptEmbedFullscreen.svelte';
    import WebReadEmbedFullscreen from './embeds/web/WebReadEmbedFullscreen.svelte';
    import WebsiteEmbedFullscreen from './embeds/web/WebsiteEmbedFullscreen.svelte';
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
    import { parse_message } from '../message_parsing/parse_message'; // Import markdown parser
    import { loadSessionStorageDraft, getSessionStorageDraftMarkdown, migrateSessionStorageDraftsToIndexedDB } from '../services/drafts/sessionStorageDraftService'; // Import sessionStorage draft service
    import { draftEditorUIState } from '../services/drafts/draftState'; // Import draft state
    import { phasedSyncState } from '../stores/phasedSyncStateStore'; // Import phased sync state store
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
    import { isDesktop } from '../utils/platform'; // Import desktop detection for conditional auto-focus
    import { waitLocale } from 'svelte-i18n'; // Import waitLocale for waiting for translations to load
    import { get } from 'svelte/store'; // Import get to read store values
    import { extractEmbedReferences } from '../services/embedResolver'; // Import for embed navigation
    import { tipTapToCanonicalMarkdown } from '../message_parsing/serializers'; // Import for embed navigation
    
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
                currentUserId = (profile as any)?.user_id || null;
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
            const welcomeDemo = DEMO_CHATS.find(chat => chat.chat_id === 'demo-welcome');
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
                activeChatStore.setActiveChat('demo-welcome');
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
            if (currentChat && !isPublicChat(currentChat.chat_id)) {
                // Check if this is a shared chat (has chat key in cache or is in sessionStorage shared_chats)
                // chatDB.getChatKey is synchronous, so we can check immediately
                const chatKey = chatDB.getChatKey(currentChat.chat_id);
                const sharedChatIds = typeof sessionStorage !== 'undefined' 
                    ? JSON.parse(sessionStorage.getItem('shared_chats') || '[]')
                    : [];
                const isSharedChat = chatKey !== null || sharedChatIds.includes(currentChat.chat_id);
                
                if (isSharedChat && !$isLoggingOut) {
                    // This is a shared chat - don't clear it, it's valid for non-auth users
                    // EXCEPTION: If we're explicitly logging out, always switch to demo-welcome
                    console.debug('[ActiveChat] Auth state changed to unauthenticated - keeping shared chat:', currentChat.chat_id);
                    return; // Keep the shared chat loaded
                }

                if (isSharedChat && $isLoggingOut) {
                    console.debug('[ActiveChat] Auth state changed during logout - clearing shared chat and loading demo-welcome:', currentChat.chat_id);
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

                        const welcomeDemo = DEMO_CHATS.find(chat => chat.chat_id === 'demo-welcome');
                        if (welcomeDemo) {
                            const translatedWelcomeDemo = translateDemoChat(welcomeDemo);
                            const welcomeChat = convertDemoChatToChat(translatedWelcomeDemo);
                            activeChatStore.setActiveChat('demo-welcome');
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
    
    // Add state for embed fullscreen
    let showEmbedFullscreen = $state(false);
    let embedFullscreenData = $state<any>(null);
    
    // Debug: Track state changes
    $effect(() => {
        console.debug('[ActiveChat] showEmbedFullscreen changed:', showEmbedFullscreen, 'embedFullscreenData:', !!embedFullscreenData);
    });
    
    // Handler for embed fullscreen events (from embed renderers)
    async function handleEmbedFullscreen(event: CustomEvent) {
        console.debug('[ActiveChat] Received embedfullscreen event:', event.detail);
        
        const { embedId, embedData, decodedContent, embedType, attrs } = event.detail;
        
        // ALWAYS reload from EmbedStore when embedId is provided to ensure we get the latest data
        // The embed might have been updated since the preview was rendered (e.g., processing -> finished)
        // The event's embedData/decodedContent might be stale (captured at render time before skill results arrived)
        let finalEmbedData = embedData;
        let finalDecodedContent = decodedContent;
        
        if (embedId) {
            try {
                const { resolveEmbed, decodeToonContent } = await import('../services/embedResolver');
                const freshEmbedData = await resolveEmbed(embedId);
                
                if (freshEmbedData) {
                    // Use fresh data from EmbedStore
                    finalEmbedData = freshEmbedData;
                    
                    if (freshEmbedData.content) {
                        finalDecodedContent = await decodeToonContent(freshEmbedData.content);
                    }
                    
                    console.debug('[ActiveChat] Loaded fresh embed data from EmbedStore:', {
                        embedId,
                        status: freshEmbedData.status,
                        hasResults: !!finalDecodedContent?.results,
                        resultsCount: finalDecodedContent?.results?.length || 0
                    });
                } else if (!finalEmbedData) {
                    // Only error if we have no data at all
                    console.error('[ActiveChat] Embed not found in EmbedStore and no fallback data:', embedId);
                    return;
                }
            } catch (error) {
                console.error('[ActiveChat] Error loading embed for fullscreen:', error);
                // Fall back to event data if available
                if (!finalEmbedData) {
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
                    return 'app-skill-use';
                case 'app-skill-use':
                    return 'app-skill-use';
                case 'web-website':
                case 'website':
                    return 'website';
                case 'code':
                case 'code-code':
                    return 'code-code';
                case 'videos-video':
                    return 'videos-video';
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
            
            if (appId === 'web' && skillId === 'search' && childEmbedIds.length > 0) {
console.debug('[ActiveChat] Loading child website embeds for web search fullscreen:', childEmbedIds);
                try {
                    const { loadEmbeds, decodeToonContent: decodeToon } = await import('../services/embedResolver');
                    const childEmbeds = await loadEmbeds(childEmbedIds);
                    
                    // Transform child embeds to WebSearchResult format
                    const results = await Promise.all(childEmbeds.map(async (embed) => {
                        const websiteContent = embed.content ? await decodeToon(embed.content) : null;
                        if (!websiteContent) return null;
                        
                        return {
                            type: 'search_result' as const,
                            title: websiteContent.title || '',
                            url: websiteContent.url || '',
                            snippet: websiteContent.description || websiteContent.extra_snippets || '',
                            hash: embed.embed_id || '',
                            favicon_url: websiteContent.meta_url_favicon || websiteContent.favicon || '',
                            preview_image_url: websiteContent.thumbnail_original || websiteContent.image || ''
                        };
                    }));
                    
                    // Filter out nulls and add to decoded content
                    finalDecodedContent.results = results.filter(r => r !== null);
                    console.info('[ActiveChat] Loaded', finalDecodedContent.results.length, 'website results for web search fullscreen:', 
                        finalDecodedContent.results.map(r => ({ title: r?.title?.substring(0, 30), url: r?.url })));
                } catch (error) {
                    console.error('[ActiveChat] Error loading child embeds for web search:', error);
                    // Continue without results - fullscreen will show "No results" message
                }
            } else if (appId === 'maps' && skillId === 'search' && childEmbedIds.length > 0) {
                console.debug('[ActiveChat] Loading child place embeds for maps search fullscreen:', childEmbedIds);
                try {
                    const { loadEmbeds, decodeToonContent: decodeToon } = await import('../services/embedResolver');
                    const childEmbeds = await loadEmbeds(childEmbedIds);
                    
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
                    console.info('[ActiveChat] Loaded', finalDecodedContent.results.length, 'place results for maps search fullscreen:', 
                        finalDecodedContent.results.map(r => ({ name: r?.displayName?.substring(0, 30), address: r?.formattedAddress })));
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
        const pipThumbnailUrl = currentState.thumbnailUrl || (pipVideoId ? `https://img.youtube.com/vi/${pipVideoId}/maxresdefault.jpg` : '');
        
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
                    if (freshChat.encrypted_follow_up_request_suggestions) {
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
                } else {
                    console.warn('[ActiveChat] Chat not found in database after post-processing:', chatId);
                    // Fallback: use suggestions from event if chat not found
                    if (newSuggestions && Array.isArray(newSuggestions) && newSuggestions.length > 0) {
                        followUpSuggestions = newSuggestions;
                        console.info('[ActiveChat] ✅ Fallback: Updated followUpSuggestions from event (chat not in DB):', $state.snapshot(followUpSuggestions));
                    }
                }
            } catch (error) {
                console.error('[ActiveChat] Failed to reload follow-up suggestions from database after post-processing:', error);
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
    let chatHistoryRef = $state<any>(null);
    // Create a reference for the MessageInput component using $state
    let messageInputFieldRef = $state<any>(null);

    let isFullscreen = $state(false);
    // $: messages = chatHistoryRef?.messages || []; // Removed, messages will be managed in currentMessages

    // Add state for message input height using $state
    let messageInputHeight = $state(0);

    let showWelcome = $state(true);

    // Add state variable for scaling animation on the container using $state
    let activeScaling = $state(false);

    // Reactive trigger for AI task state changes - incremented when AI tasks start/end
    // Note: Prefixed with underscore as linter reports unused, but it's used as a reactivity trigger
    let _aiTaskStateTrigger = 0;

    // Track if the message input has content (draft) using $state
    let messageInputHasContent = $state(false);
    // Track live input text for incremental search in new chat suggestions
    let liveInputText = $state('');
    
    // Track if user is at bottom of chat (from scrolledToBottom event)
    // Initialize to false to prevent MessageInput from appearing expanded on initial load
    // Will be set correctly by loadChat() or handleScrollPositionUI() once scroll position is determined
    let isAtBottom = $state(false);
    
    // Track if message input is focused (for showing follow-up suggestions)
    let messageInputFocused = $state(false);

    // Track follow-up suggestions for the current chat
    let followUpSuggestions = $state<string[]>([]);

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
    
    // Ultra-wide mode: When container is > 1300px, show fullscreen embeds side-by-side with chat
    // instead of as overlays. This provides a better experience on large displays.
    let isUltraWide = $derived(containerWidth > 1300);
    
    // Determine if we should use side-by-side layout for fullscreen embeds
    // Only use side-by-side when ultra-wide AND an embed fullscreen is open
    let showSideBySideFullscreen = $derived(isUltraWide && showEmbedFullscreen && embedFullscreenData);
    
    // Effective narrow mode: True when chat container is narrow OR when in side-by-side mode
    // In side-by-side mode, the chat is limited to 400px which requires narrow/mobile styling
    // This is used for container-based responsive behavior instead of viewport-based
    let isEffectivelyNarrow = $derived(isNarrow || showSideBySideFullscreen);
    
    // Effective chat width: The actual width of the chat area
    // In side-by-side mode, the chat is constrained to 400px regardless of container width
    // This is passed to ChatHistory/ChatMessage for proper responsive behavior
    let effectiveChatWidth = $derived(showSideBySideFullscreen ? 400 : containerWidth);

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
    let currentTypingStatus: AITypingStatus | null = null;
    
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
    
    // Effect to reload follow-up suggestions when MessageInput is focused but suggestions are empty
    // This handles the case where suggestions were stored in the database but weren't loaded
    // in-memory (e.g., after post-processing completes but the event handler didn't fire)
    $effect(() => {
        if (messageInputFocused && !showWelcome && currentChat?.chat_id && followUpSuggestions.length === 0) {
            // Only try to reload if we have encrypted suggestions in the chat
            if (currentChat.encrypted_follow_up_request_suggestions) {
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
                console.debug('[ActiveChat] No encrypted suggestions in currentChat - checking database');
                (async () => {
                    try {
                        const freshChat = await chatDB.getChat(currentChat.chat_id);
                        if (freshChat?.encrypted_follow_up_request_suggestions) {
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
            }
            // Reset the signal
            draftEditorUIState.update(s => ({ ...s, newlyCreatedChatIdToSelect: null }));
        }
    });

    // Reactive variable for typing indicator text
    // Shows: "Processing..." when user message is being processed
    // Then shows: "{mate} is typing...<br>Powered by {model_name} via {provider_name}" when AI is responding
    // Using Svelte 5 $derived for typing indicator text
    let typingIndicatorText = $derived((() => {
        // _aiTaskStateTrigger is a top-level reactive variable.
        // Its change will trigger re-evaluation of this derived value.
        
        // Check if there's a processing message (user message waiting for AI to start)
        const hasProcessingMessage = currentMessages.some(m => 
            m.role === 'user' && m.status === 'processing' && m.chat_id === currentChat?.chat_id
        );
        
        // Debug logging for typing indicator
        console.debug('[ActiveChat] Typing indicator check:', {
            hasProcessingMessage,
            isTyping: currentTypingStatus?.isTyping,
            typingChatId: currentTypingStatus?.chatId,
            currentChatId: currentChat?.chat_id,
            category: currentTypingStatus?.category,
            modelName: currentTypingStatus?.modelName,
            providerName: currentTypingStatus?.providerName
        });
        
        // Show "Processing..." if there's a user message in processing state
        if (hasProcessingMessage) {
            const result = $text('enter_message.processing.text');
            console.debug('[ActiveChat] Showing processing indicator:', result);
            return result;
        }
        
        // Show detailed AI typing indicator once AI has started responding
        if (currentTypingStatus?.isTyping && currentTypingStatus.chatId === currentChat?.chat_id && currentTypingStatus.category) {
            const mateName = $text('mates.' + currentTypingStatus.category + '.text');
            // Use server name from provider config (falls back to "AI" if not provided)
            // The backend should provide the server name (e.g., "Cerebras", "OpenRouter", "Mistral") 
            // instead of generic "AI" - this comes from the provider config's server.name field
            const modelName = currentTypingStatus.modelName || ''; 
            const providerName = currentTypingStatus.providerName || '';
            
            // If we don't have model or provider name, just show the typing indicator without "Powered by"
            if (!modelName && !providerName) {
                return $text('enter_message.is_typing.text').replace('{mate}', mateName);
            }
            
            // Use translation key with placeholders for model and provider names
            // Format: "{mate} is typing...<br>Powered by {model_name} via {provider_name}"
            const result = $text('enter_message.is_typing_powered_by.text')
                .replace('{mate}', mateName)
                .replace('{model_name}', modelName)
                .replace('{provider_name}', providerName);
            
            console.debug('[ActiveChat] AI typing indicator text generated:', result);
            return result;
        }
        console.debug('[ActiveChat] Typing indicator: no status to show');
        return null; // No indicator
    })());


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
        
        const chunk = event.detail as any; // AIMessageUpdatePayload
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

        // Operate on currentMessages state
        let targetMessageIndex = currentMessages.findIndex(m => m.message_id === chunk.message_id);
        let targetMessage: ChatMessageModel | null = targetMessageIndex !== -1 ? { ...currentMessages[targetMessageIndex] } : null;

        let messageToSave: ChatMessageModel | null = null;
        let isNewMessageInStream = false;
        let previousContentLengthForPersistence = 0;
        let newContentLengthForPersistence = 0;

        if (!targetMessage) {
            // Create a streaming AI message even if sequence is not 1 to avoid dropping chunks
            const fallbackCategory = currentTypingStatus?.chatId === chunk.chat_id ? currentTypingStatus.category : undefined;
            const fallbackModelName = currentTypingStatus?.chatId === chunk.chat_id ? currentTypingStatus.modelName : undefined;
            const newAiMessage: ChatMessageModel = {
                message_id: chunk.message_id,
                chat_id: chunk.chat_id, // Ensure this is correct
                user_message_id: chunk.user_message_id,
                role: 'assistant',
                category: chunk.category || fallbackCategory,
                model_name: chunk.model_name || fallbackModelName || undefined,
                content: chunk.full_content_so_far || '', // Store as markdown string, not Tiptap JSON
                status: 'streaming',
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
            if (targetMessage.status !== 'streaming') {
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
                    const shouldPersistChunk =
                        isNewMessageInStream ||
                        chunk.is_final_chunk ||
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

                const updatedFinalMessage = {
                    ...finalMessageInArray,
                    status: 'synced' as const,
                    model_name: finalModelName // Explicitly preserve/set model_name
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

                // CRITICAL FIX: Also update the corresponding user message status from 'sending' to 'synced'
                // This prevents the infinite "Sending..." state when the AI responds (including error responses)
                if (chunk.user_message_id) {
                    const userMessageIndex = currentMessages.findIndex(m => m.message_id === chunk.user_message_id);
                    if (userMessageIndex !== -1 && currentMessages[userMessageIndex].status === 'sending') {
                        const updatedUserMessage = { ...currentMessages[userMessageIndex], status: 'synced' as const };
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
        
        // Reset live input text to clear search term for suggestions
        // This ensures suggestions show the default 3 when input is focused again
        liveInputText = '';
        console.debug("[ActiveChat] handleSendMessage: Reset liveInputText after sending message");

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
                        currentChat = incognitoChat as any;
                    } else {
                        const dbChat = await chatDB.getChat(message.chat_id);
                        if (dbChat) {
                            currentChat = dbChat as any;
                        } else {
                            // Minimal fallback to keep UI consistent; DB should catch up shortly
                            currentChat = { chat_id: message.chat_id } as any;
                        }
                    }
                } catch (err) {
                    console.warn('[ActiveChat] Failed to load chat for sent message; using minimal fallback:', err);
                    currentChat = { chat_id: message.chat_id } as any;
                }
            }
            currentMessages = [message]; // Initialize messages with the first message
            
            // Clear temporary chat ID since we now have a real chat
            temporaryChatId = null;
            console.debug("[ActiveChat] New chat created from message, cleared temporary chat ID");
            
            // Notify backend about the active chat, but only if not in signup flow
            // CRITICAL: Don't send set_active_chat if authenticated user is in signup flow - this would overwrite last_opened
            // Non-authenticated users can send set_active_chat for demo chats
            if (!$authStore.isAuthenticated || !$isInSignupProcess) {
                chatSyncService.sendSetActiveChat(currentChat.chat_id);
            } else {
                console.debug('[ActiveChat] Authenticated user is in signup flow - skipping set_active_chat for new chat to preserve last_opened path');
            }
            
            // Dispatch global event to update UI (sidebar highlights) and URL
            const globalChatSelectedEvent = new CustomEvent('globalChatSelected', {
                detail: { chat: newChat },
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
        
        // Generate a new temporary chat ID for the new chat
        temporaryChatId = crypto.randomUUID();
        console.debug("[ActiveChat] Generated new temporary chat ID for new chat:", temporaryChatId);
        
        // Update phased sync state to indicate we're in "new chat" mode
        // This prevents Phase 1 from auto-selecting the old chat when panel reopens
        phasedSyncState.setCurrentActiveChatId(null);

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

    // Update handler for chat updates to be more selective
    async function handleChatUpdated(event: CustomEvent) {
        const detail = event.detail as any; 
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
        } else {
            console.debug('[ActiveChat] handleChatUpdated: No direct message updates (newMessage or incomingMessages) were applied from the event. Full event.detail:', JSON.parse(JSON.stringify(detail)));
            // If currentChat metadata (like title or messages_v) was updated, UI elements bound to currentChat will react.
            // No explicit call to chatHistoryRef.updateMessages if currentMessages array reference hasn't changed.
            // If messages_v changed and a full refresh is TRULY needed (e.g. server indicates a major desync not covered by specific message events),
            // that would be a separate, more explicit mechanism or a different event type.
        }
        // Removed the messages_v based reload from DB here. Updates should come from explicit message data in events.
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
                Object.entries(chatMetadata).filter(([_key, value]) => value !== undefined)
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
    let scrollSaveDebounceTimer: NodeJS.Timeout | null = null;
    let lastSavedMessageId: string | null = null;

    // Handle immediate UI state updates from ChatHistory (no debounce)
    function handleScrollPositionUI(event: CustomEvent) {
        const { isAtBottom: atBottom } = event.detail;
        // Immediately update UI state for responsive button visibility
        isAtBottom = atBottom;
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
        
        // CRITICAL: Preserve streaming messages when reloading the SAME chat
        // During AI streaming, various events (chatUpdated, etc.) can trigger loadChat() calls
        // which would wipe out the streaming message being rendered in real-time.
        // We detect if there's an active streaming message for THIS chat and merge it into newMessages.
        const isReloadingSameChat = currentChat?.chat_id === chat.chat_id;
        const existingStreamingMessages = currentMessages.filter(m => m.status === 'streaming' && m.chat_id === chat.chat_id);
        
        if (isReloadingSameChat && existingStreamingMessages.length > 0) {
            console.debug(`[ActiveChat] loadChat: Preserving ${existingStreamingMessages.length} streaming message(s) during reload of same chat ${chat.chat_id}`);
            
            // Merge streaming messages with messages from database
            // The database won't have the latest streaming content, so we use our local copy
            for (const streamingMsg of existingStreamingMessages) {
                const dbMsgIndex = newMessages.findIndex(m => m.message_id === streamingMsg.message_id);
                if (dbMsgIndex !== -1) {
                    // Message exists in DB but our streaming version is more up-to-date
                    newMessages[dbMsgIndex] = streamingMsg;
                    console.debug(`[ActiveChat] loadChat: Replaced DB message ${streamingMsg.message_id} with streaming version (${streamingMsg.content?.length || 0} chars)`);
                } else {
                    // Streaming message not yet in DB - append it
                    newMessages.push(streamingMsg);
                    console.debug(`[ActiveChat] loadChat: Appended streaming message ${streamingMsg.message_id} (${streamingMsg.content?.length || 0} chars)`);
                }
            }
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
            } else {
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
        if (messageInputFieldRef) {
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
        }
        
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
                        chatSyncService.removeEventListener('webSocketConnected', sendNotificationOnConnect as EventListener);
                        return;
                    }
                    console.debug('[ActiveChat] WebSocket connected, sending deferred active chat notification');
                    chatSyncService.sendSetActiveChat(chatIdToNotify);
                    // Remove the listener after sending
                    chatSyncService.removeEventListener('webSocketConnected', sendNotificationOnConnect as EventListener);
                };
                
                chatSyncService.addEventListener('webSocketConnected', sendNotificationOnConnect as EventListener);
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
            if (!$authStore.isAuthenticated && !currentChat?.chat_id && !$activeChatStore && !$isInSignupProcess) {
                console.debug("[ActiveChat] [NON-AUTH] Fallback: Loading welcome demo chat (mobile fallback)");
                const welcomeDemo = DEMO_CHATS.find(chat => chat.chat_id === 'demo-welcome');
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

                        // Double-check that chat still isn't loaded (might have been loaded by +page.svelte)
                        if (!currentChat?.chat_id && $activeChatStore !== 'demo-welcome') {
                            activeChatStore.setActiveChat('demo-welcome');
                            loadChat(welcomeChat);
                            console.info("[ActiveChat] [NON-AUTH] ✅ Fallback: Welcome chat loaded successfully");
                        } else {
                            console.info("[ActiveChat] [NON-AUTH] Fallback: Welcome chat already loaded, skipping");
                        }
                    }, 100);
                }
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
            activeChatStore.setActiveChat('demo-welcome');
            
            // Wait a tick to ensure state is cleared before loading new chat
            await tick();
            
            // Load default demo chat (welcome chat)
            const welcomeChat = DEMO_CHATS.find(chat => chat.chat_id === 'demo-welcome');
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
                console.debug("[ActiveChat] Dispatched globalChatSelected for demo-welcome chat");
                
                // Also wait a bit and dispatch again in case Chats component mounts after panel opens
                // This handles the case where the panel opens and Chats component mounts after our first dispatch
                setTimeout(() => {
                    window.dispatchEvent(globalChatSelectedEvent);
                    console.debug("[ActiveChat] Re-dispatched globalChatSelected for demo-welcome chat (after delay)");
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
            const welcomeChat = DEMO_CHATS.find(chat => chat.chat_id === 'demo-welcome');
            if (welcomeChat) {
                const chat = convertDemoChatToChat(translateDemoChat(welcomeChat));
                // Clear current chat first
                currentChat = null;
                currentMessages = [];
                activeChatStore.setActiveChat('demo-welcome');
                loadChat(chat);
                console.debug("[ActiveChat] ✅ Demo chat loaded after logout from signup");
            }
        };
        
        window.addEventListener('openLoginInterface', handleOpenLoginInterface);
        
        // Add event listener for embed fullscreen events
        const embedFullscreenHandler = (event: CustomEvent) => {
            handleEmbedFullscreen(event);
        };
        document.addEventListener('embedfullscreen', embedFullscreenHandler as EventListener);
        
        // Add event listener for video PiP restore fullscreen events
        // This is triggered when user clicks the overlay on PiP video (via VideoIframe component)
        const videoPipRestoreHandler = (_event: CustomEvent) => {
            handlePipOverlayClick();
        };
        document.addEventListener('videopip-restore-fullscreen', videoPipRestoreHandler as EventListener);
        
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
                const welcomeDemo = DEMO_CHATS.find(chat => chat.chat_id === 'demo-welcome');
                if (welcomeDemo) {
                    // Translate the demo chat to the user's locale
                    const translatedWelcomeDemo = translateDemoChat(welcomeDemo);
                    const welcomeChat = convertDemoChatToChat(translatedWelcomeDemo);
                    
                    // Set active chat and load welcome chat
                    activeChatStore.setActiveChat('demo-welcome');
                    
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
                        currentMessages = getDemoMessages('demo-welcome', DEMO_CHATS, LEGAL_CHATS);
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
            const chatIsHidden = (currentChat as any).is_hidden === true;
            
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
                    if (freshChat && (freshChat as any).is_hidden === true) {
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
        
        // Add language change listener to reload public chats (demo + legal) when language changes
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
                
                // Find the public chat (check both DEMO_CHATS and LEGAL_CHATS) and translate it
                // Use snapshotChat to ensure we have the current value
                let publicChat = DEMO_CHATS.find(chat => chat.chat_id === snapshotChat.chat_id);
                if (!publicChat) {
                    publicChat = LEGAL_CHATS.find(chat => chat.chat_id === snapshotChat.chat_id);
                }
                if (publicChat) {
                    // CRITICAL: Re-translate the chat with the new locale
                    // translateDemoChat uses get(_) which reads from the locale store
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

        // Add event listeners for both chat updates and message status changes
        const chatUpdateHandler = ((event: CustomEvent) => {
            handleChatUpdated(event);
        }) as EventListener;

        const messageStatusHandler = ((event: CustomEvent) => {
            // Call the component's own method which correctly updates currentMessages,
            // saves to DB, and calls chatHistoryRef.updateMessages()
            handleMessageStatusChanged(event); 
        }) as EventListener;

        // Listen to events directly from chatSyncService
        chatSyncService.addEventListener('chatUpdated', chatUpdateHandler);
        chatSyncService.addEventListener('messageStatusChanged', messageStatusHandler);
        
        // Add listener for AI message chunks
        console.log('[ActiveChat] 📌 Registering aiMessageChunk event listener');
        chatSyncService.addEventListener('aiMessageChunk', handleAiMessageChunk as EventListener);
        console.log('[ActiveChat] ✅ aiMessageChunk event listener registered');

        // Add listeners for AI task state changes
        const aiTaskInitiatedHandler = (async (event: CustomEvent<AITaskInitiatedPayload>) => {
            const { chat_id, user_message_id } = event.detail;
            if (chat_id === currentChat?.chat_id) {
                const messageIndex = currentMessages.findIndex(m => m.message_id === user_message_id);
                if (messageIndex !== -1) {
                    const updatedMessage = { ...currentMessages[messageIndex], status: 'processing' as const };
                    currentMessages[messageIndex] = updatedMessage;
                    currentMessages = [...currentMessages]; // Trigger reactivity

                    // Save status update to DB
                    try {
                        await chatDB.saveMessage(updatedMessage);
                    } catch (error) {
                        console.error('[ActiveChat] Error updating user message status to processing in DB:', error);
                    }

                    if (chatHistoryRef) {
                        chatHistoryRef.updateMessages(currentMessages);
                    }
                }
                _aiTaskStateTrigger++;
            }
        }) as EventListener;

        const aiTaskEndedHandler = ((event: CustomEvent<{ chatId: string }>) => {
            if (event.detail.chatId === currentChat?.chat_id) {
                _aiTaskStateTrigger++;
            }
        }) as EventListener;

        const aiTypingStartedHandler = (async (event: CustomEvent) => {
            const { chat_id, user_message_id } = event.detail;
            if (chat_id === currentChat?.chat_id) {
                const messageIndex = currentMessages.findIndex(m => m.message_id === user_message_id);
                if (messageIndex !== -1 && currentMessages[messageIndex].status === 'processing') {
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
            }
        }) as EventListener;

        // Handle chat deletion - if the currently active chat is deleted, reset to new chat
        const chatDeletedHandler = ((event: CustomEvent) => {
            const { chat_id } = event.detail;
            console.debug('[ActiveChat] Received chatDeleted event for chat:', chat_id, 'Current chat:', currentChat?.chat_id);
            
            if (currentChat && chat_id === currentChat.chat_id) {
                console.info('[ActiveChat] Currently active chat was deleted. Resetting to new chat state.');
                // Reset to new chat state using the existing handler
                handleNewChatClick();
            }
        }) as EventListener;

        chatSyncService.addEventListener('aiTaskInitiated', aiTaskInitiatedHandler);
        chatSyncService.addEventListener('aiTypingStarted', aiTypingStartedHandler);
        chatSyncService.addEventListener('aiTaskEnded', aiTaskEndedHandler);
        chatSyncService.addEventListener('chatDeleted', chatDeletedHandler);
        const postProcessingHandler = handlePostProcessingCompleted as EventListener;
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
                // Create new message array references to force Svelte reactivity
                // CRITICAL: We need to create NEW content objects to break reference equality
                // so that ChatHistory detects the change and re-renders ReadOnlyMessage components
                currentMessages = currentMessages.map(msg => {
                    // Only update the specific message that contains this embed
                    // For now, update all streaming/assistant messages to be safe
                    if (msg.message_id === message_id || msg.status === 'streaming' || msg.role === 'assistant') {
                        return {
                            ...msg,
                            // Add a timestamp to force content re-processing
                            _embedUpdateTimestamp: Date.now()
                        };
                    }
                    return msg;
                });
                
                chatHistoryRef.updateMessages(currentMessages);
                console.debug(`[ActiveChat] 🔄 Forced message re-render after embed update for ${embed_id}`);
            }
        }) as EventListener;
        
        chatSyncService.addEventListener('embedUpdated', embedUpdatedHandler);
        console.debug('[ActiveChat] ✅ Registered embedUpdated event listener');
        
        // Handle skill preview updates - add app cards to messages
        const handleSkillPreviewUpdate = async (event: CustomEvent) => {
            const { task_id, previewData, chat_id, message_id } = event.detail;
            
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
            let appCard: any = null;
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
                                decodedContent: previewData
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
                                decodedContent: previewData
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
                const message = updatedMessages[messageIndex];
                
                // Initialize appCards array if it doesn't exist
                if (!(message as any).appCards) {
                    (message as any).appCards = [];
                }
                
                // Check if this task_id already has a card (update existing)
                const existingCardIndex = (message as any).appCards.findIndex(
                    (card: any) => card.props?.id === task_id
                );
                
                if (existingCardIndex !== -1) {
                    // Update existing card
                    (message as any).appCards[existingCardIndex] = appCard;
                } else {
                    // Add new card
                    (message as any).appCards.push(appCard);
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
        
        skillPreviewService.addEventListener('skillPreviewUpdate', handleSkillPreviewUpdate as EventListener);

        return () => {
            // Remove listeners from chatSyncService
            chatSyncService.removeEventListener('chatUpdated', chatUpdateHandler);
            chatSyncService.removeEventListener('messageStatusChanged', messageStatusHandler);
            unsubscribeAiTyping(); // Unsubscribe from AI typing store
            unsubscribeDraftState(); // Unsubscribe from draft state
            chatSyncService.removeEventListener('aiMessageChunk', handleAiMessageChunk as EventListener); // Remove listener
            chatSyncService.removeEventListener('aiTaskInitiated', aiTaskInitiatedHandler);
            chatSyncService.removeEventListener('aiTypingStarted', aiTypingStartedHandler);
            chatSyncService.removeEventListener('aiTaskEnded', aiTaskEndedHandler);
            chatSyncService.removeEventListener('chatDeleted', chatDeletedHandler);
            chatSyncService.removeEventListener('postProcessingCompleted', handlePostProcessingCompleted as EventListener);
            chatSyncService.removeEventListener('embedUpdated', embedUpdatedHandler);
            skillPreviewService.removeEventListener('skillPreviewUpdate', handleSkillPreviewUpdate as EventListener);
            // Remove language change listener
            window.removeEventListener('language-changed', handleLanguageChange);
            window.removeEventListener('language-changed-complete', handleLanguageChange);
            // Remove login interface event listeners
            window.removeEventListener('openLoginInterface', handleOpenLoginInterface as EventListener);
            window.removeEventListener('closeLoginInterface', handleCloseLoginInterface as EventListener);
            window.removeEventListener('loadDemoChat', handleLoadDemoChat as EventListener);
            // Remove draft save sync listener
            window.removeEventListener('localChatListChanged', handleDraftSaveSync as EventListener);
            if (handleLogoutEvent) {
                window.removeEventListener('userLoggingOut', handleLogoutEvent as EventListener);
            }
            window.removeEventListener('triggerNewChat', handleTriggerNewChat as EventListener);
            window.removeEventListener('hiddenChatsLocked', handleHiddenChatsLocked as EventListener);
            window.removeEventListener('hiddenChatsAutoLocked', handleHiddenChatsLocked as EventListener);
            // Remove embed and video PiP fullscreen listeners
            document.removeEventListener('embedfullscreen', embedFullscreenHandler as EventListener);
            document.removeEventListener('videopip-restore-fullscreen', videoPipRestoreHandler as EventListener);
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
        // chatSyncService.removeEventListener('aiMessageChunk', handleAiMessageChunk as EventListener); // Already in onMount return
    });
</script>

<div 
    class="active-chat-container" 
    class:dimmed={isDimmed} 
    class:login-mode={!showChat} 
    class:scaled={activeScaling}
    class:narrow={isEffectivelyNarrow}
    class:medium={isMedium && !showSideBySideFullscreen}
    class:wide={isWide && !showSideBySideFullscreen}
    class:extra-wide={isExtraWide}
    class:side-by-side-active={showSideBySideFullscreen}
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
            class:side-by-side={showSideBySideFullscreen}
        >
            <!-- Main content wrapper that will handle the fullscreen layout -->
            <!-- When side-by-side mode is active, chat takes left portion -->
            <div class="chat-wrapper" class:fullscreen={isFullscreen} class:side-by-side-chat={showSideBySideFullscreen}>
                <!-- Incognito mode banner - shows for incognito chats or new chats when incognito mode is active -->
                {#if currentChat?.is_incognito || (showWelcome && $incognitoMode)}
                    <div class="incognito-banner">
                        <div class="incognito-banner-icon">
                            <div class="icon settings_size subsetting_icon subsetting_icon_incognito"></div>
                        </div>
                        <span class="incognito-banner-text">{$text('settings.incognito.text')}</span>
                    </div>
                {/if}
                
                <!-- Left side container for chat history and buttons -->
                <div class="chat-side">
                    <div class="top-buttons">
                        <!-- Left side buttons -->
                        <div class="left-buttons">
                            {#if createButtonVisible}
                                <!-- Background container for new chat button to ensure visibility -->
                                <div class="new-chat-button-wrapper">
                                    <button 
                                        class="clickable-icon icon_create top-button" 
                                        aria-label={$text('chat.new_chat.text')}
                                        onclick={handleNewChatClick}
                                        in:fade={{ duration: 300 }}
                                        use:tooltip
                                        style="margin: 5px;"
                                    >
                                    </button>
                                </div>
                            {/if}
                            {#if !showWelcome}
                                <!-- Share button - opens settings menu with share submenu -->
                                <!-- Use same wrapper design as new chat button -->
                                <div class="new-chat-button-wrapper">
                                    <button
                                        class="clickable-icon icon_share top-button"
                                        aria-label={$text('chat.share.text')}
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
                                    aria-label={$text('header.report_issue.text')}
                                    onclick={handleReportIssue}
                                    use:tooltip
                                    style="margin: 5px;"
                                >
                                </button>
                            </div>
                        </div>

                        <!-- Right side buttons -->
                        <div class="right-buttons">
                            <!-- Bug icon for reporting issues -->
                            
                            <!-- Activate buttons once features are implemented -->
                            <!-- Video call button -->
                            <!-- <button 
                                class="clickable-icon icon_video_call top-button" 
                                aria-label={$text('chat.start_video_call.text')}
                                use:tooltip
                            ></button> -->
                            <!-- Audio call button -->
                            <!-- <button 
                                class="clickable-icon icon_call top-button" 
                                aria-label={$text('chat.start_audio_call.text')}
                                use:tooltip
                            ></button> -->
                        </div>
                    </div>

                    <!-- Update the welcome content to use transition and showWelcome -->
                    {#if showWelcome}
                        <div
                            class="center-content"
                            transition:fade={{ duration: 300 }}
                        >
                            <div class="team-profile">
                                <!-- <div class="team-image" class:disabled={!isTeamEnabled}></div> -->
                                <div class="welcome-text">
                                    <h2>{@html username ? $text('chat.welcome.hey_user.text').replace('{username}', username) : $text('chat.welcome.hey_guest.text')}</h2>
                                    <p>{@html $text('chat.welcome.what_do_you_need_help_with.text')}</p>
                                </div>
                            </div>
                        </div>
                    {/if}

                    <ChatHistory
                        bind:this={chatHistoryRef}
                        messageInputHeight={isFullscreen ? 0 : messageInputHeight + 40}
                        containerWidth={effectiveChatWidth}
                        on:messagesChange={handleMessagesChange}
                        on:chatUpdated={handleChatUpdated}
                        on:scrollPositionUI={handleScrollPositionUI}
                        on:scrollPositionChanged={handleScrollPositionChanged}
                        on:scrolledToBottom={handleScrolledToBottom}
                    />
                </div>

                <!-- Right side container for message input -->
                <div class="message-input-wrapper">
                    {#if typingIndicatorText}
                        <div class="typing-indicator" transition:fade={{ duration: 200 }}>
                            {@html typingIndicatorText}
                        </div>
                    {/if}

                    <div class="message-input-container">
                        <!-- Show loading message while initial sync is in progress -->
                        {#if showWelcome && !$phasedSyncState.initialSyncCompleted}
                            <div class="sync-loading-message" transition:fade={{ duration: 200 }}>
                                Loading chats...
                            </div>
                        {/if}
                        
                        <!-- New chat suggestions when no chat is open and user is at bottom/input active -->
                        <!-- Only show after initial sync is complete to avoid database race conditions -->
                        <!-- Show whenever we're in welcome mode (no current chat) AND sync is complete -->
                        {#if showWelcome && $phasedSyncState.initialSyncCompleted}
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
                                    {$text('settings.incognito_mode_applies_to_new_chats_only.text', { default: 'Incognito Mode applies to new chats only. Not this chat.' })}
                                </span>
                            </div>
                        {/if}

                        <!-- Follow-up suggestions when input is focused -->
                        {#if showFollowUpSuggestions}
                            <FollowUpSuggestions
                                suggestions={followUpSuggestions}
                                messageInputContent={liveInputText}
                                onSuggestionClick={handleSuggestionClick}
                            />
                        {/if}

                        <!-- Read-only indicator for shared chats -->
                        {#if currentChat && !chatOwnershipResolved && $authStore.isAuthenticated}
                            <div class="read-only-indicator" transition:fade={{ duration: 200 }}>
                                <div class="read-only-icon">🔒</div>
                                <p class="read-only-text">{$text('chat.read_only_shared.text', { default: 'This shared chat is read-only. You cannot send messages.' })}</p>
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
                                on:sendMessage={handleSendMessage}
                                on:heightchange={handleInputHeightChange}
                                on:draftSaved={handleDraftSaved}
                                on:textchange={(e) => { 
                                    const t = (e.detail?.text || '');
                                    console.debug('[ActiveChat] textchange event received:', { text: t, length: t.length });
                                    liveInputText = t;
                                    messageInputHasContent = t.trim().length > 0; 
                                }}
                                bind:isFullscreen
                                bind:hasContent={messageInputHasContent}
                                bind:isFocused={messageInputFocused}
                            />
                        {/if}
                    </div>
                </div>
            </div>

            {#if showCodeFullscreen}
                <CodeFullscreen 
                    code={fullscreenCodeData.code}
                    filename={fullscreenCodeData.filename}
                    language={fullscreenCodeData.language}
                    lineCount={fullscreenCodeData.lineCount}
                    onClose={handleCloseCodeFullscreen}
                />
            {/if}
            
            <!-- Embed fullscreen view (app-skill-use, website, etc.) -->
            <!-- Container switches between overlay mode (default) and side panel mode (ultra-wide screens) -->
            <!-- Side-by-side mode shows embed next to chat for better large display usage -->
            {#if showEmbedFullscreen && embedFullscreenData}
                <div 
                    class="fullscreen-embed-container"
                    class:side-panel={showSideBySideFullscreen}
                    class:overlay-mode={!showSideBySideFullscreen}
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
                            results={embedFullscreenData.decodedContent?.results || []}
                            embedId={embedFullscreenData.embedId}
                            onClose={handleCloseEmbedFullscreen}
                            {hasPreviousEmbed}
                            {hasNextEmbed}
                            onNavigatePrevious={handleNavigatePreviousEmbed}
                            onNavigateNext={handleNavigateNextEmbed}
                        />
                    {:else if appId === 'news' && skillId === 'search'}
                        <!-- News Search Fullscreen -->
                        <!-- Pass embedIds for proper child embed loading -->
                        <NewsSearchEmbedFullscreen 
                            query={embedFullscreenData.decodedContent?.query || ''}
                            provider={embedFullscreenData.decodedContent?.provider || 'Brave'}
                            embedIds={embedFullscreenData.decodedContent?.embed_ids || embedFullscreenData.embedData?.embed_ids}
                            results={embedFullscreenData.decodedContent?.results || []}
                            embedId={embedFullscreenData.embedId}
                            onClose={handleCloseEmbedFullscreen}
                            {hasPreviousEmbed}
                            {hasNextEmbed}
                            onNavigatePrevious={handleNavigatePreviousEmbed}
                            onNavigateNext={handleNavigateNextEmbed}
                        />
                    {:else if appId === 'videos' && skillId === 'search'}
                        <!-- Videos Search Fullscreen -->
                        <!-- Pass embedIds for proper child embed loading -->
                        <VideosSearchEmbedFullscreen 
                            query={embedFullscreenData.decodedContent?.query || ''}
                            provider={embedFullscreenData.decodedContent?.provider || 'Brave'}
                            embedIds={embedFullscreenData.decodedContent?.embed_ids || embedFullscreenData.embedData?.embed_ids}
                            results={embedFullscreenData.decodedContent?.results || []}
                            embedId={embedFullscreenData.embedId}
                            onClose={handleCloseEmbedFullscreen}
                            {hasPreviousEmbed}
                            {hasNextEmbed}
                            onNavigatePrevious={handleNavigatePreviousEmbed}
                            onNavigateNext={handleNavigateNextEmbed}
                        />
                    {:else if appId === 'maps' && skillId === 'search'}
                        <!-- Maps Search Fullscreen -->
                        <!-- Pass embedIds for proper child embed loading -->
                        <MapsSearchEmbedFullscreen 
                            query={embedFullscreenData.decodedContent?.query || ''}
                            provider={embedFullscreenData.decodedContent?.provider || 'Google'}
                            embedIds={embedFullscreenData.decodedContent?.embed_ids || embedFullscreenData.embedData?.embed_ids}
                            results={embedFullscreenData.decodedContent?.results || []}
                            embedId={embedFullscreenData.embedId}
                            onClose={handleCloseEmbedFullscreen}
                            {hasPreviousEmbed}
                            {hasNextEmbed}
                            onNavigatePrevious={handleNavigatePreviousEmbed}
                            onNavigateNext={handleNavigateNextEmbed}
                        />
                    {:else if appId === 'videos' && skillId === 'get_transcript'}
                        <!-- Video Transcript Fullscreen -->
                        {@const previewData = {
                            app_id: appId,
                            skill_id: skillId,
                            status: embedFullscreenData.embedData?.status || 'finished',
                            results: embedFullscreenData.decodedContent?.results || [],
                            video_count: embedFullscreenData.decodedContent?.video_count || 0,
                            success_count: embedFullscreenData.decodedContent?.success_count || 0,
                            failed_count: embedFullscreenData.decodedContent?.failed_count || 0
                        }}
                        {@const _debugRender = (() => {
                            console.debug('[ActiveChat] Rendering VideoTranscriptEmbedFullscreen:', {
                                appId,
                                skillId,
                                hasPreviewData: !!previewData,
                                resultsCount: previewData.results?.length || 0
                            });
                            return null;
                        })()}
                        <VideoTranscriptEmbedFullscreen 
                            previewData={previewData}
                            embedId={embedFullscreenData.embedId}
                            onClose={handleCloseEmbedFullscreen}
                            {hasPreviousEmbed}
                            {hasNextEmbed}
                            onNavigatePrevious={handleNavigatePreviousEmbed}
                            onNavigateNext={handleNavigateNextEmbed}
                        />
                    {:else if appId === 'web' && skillId === 'read'}
                        <!-- Web Read Fullscreen -->
                        <!-- Pass URL from decoded content (from processing placeholder or original_metadata) -->
                        {@const webReadUrl = embedFullscreenData.decodedContent?.url || 
                            embedFullscreenData.decodedContent?.original_metadata?.url || 
                            embedFullscreenData.decodedContent?.results?.[0]?.url || ''}
                        {@const previewData = {
                            app_id: appId,
                            skill_id: skillId,
                            status: embedFullscreenData.embedData?.status || 'finished',
                            results: embedFullscreenData.decodedContent?.results || [],
                            url: webReadUrl
                        }}
                        <WebReadEmbedFullscreen 
                            previewData={previewData}
                            url={webReadUrl}
                            onClose={handleCloseEmbedFullscreen}
                            {hasPreviousEmbed}
                            {hasNextEmbed}
                            onNavigatePrevious={handleNavigatePreviousEmbed}
                            onNavigateNext={handleNavigateNextEmbed}
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
                        />
                    {/if}
                {:else if embedFullscreenData.embedType === 'code-code'}
                    <!-- Code Fullscreen -->
                    {#if embedFullscreenData.decodedContent?.code || embedFullscreenData.attrs?.code}
                        <CodeEmbedFullscreen 
                            codeContent={embedFullscreenData.decodedContent?.code || embedFullscreenData.attrs?.code || ''}
                            language={embedFullscreenData.decodedContent?.language || embedFullscreenData.attrs?.language}
                            filename={embedFullscreenData.decodedContent?.filename || embedFullscreenData.attrs?.filename}
                            lineCount={embedFullscreenData.decodedContent?.lineCount || embedFullscreenData.attrs?.lineCount || 0}
                            embedId={embedFullscreenData.embedId}
                            onClose={handleCloseEmbedFullscreen}
                            {hasPreviousEmbed}
                            {hasNextEmbed}
                            onNavigatePrevious={handleNavigatePreviousEmbed}
                            onNavigateNext={handleNavigateNextEmbed}
                        />
                    {/if}
                {:else if embedFullscreenData.embedType === 'videos-video'}
                    <!-- Video Fullscreen -->
                    {#if embedFullscreenData.decodedContent?.url || embedFullscreenData.attrs?.url}
                        {@const VideoEmbedFullscreenPromise = import('../components/embeds/videos/VideoEmbedFullscreen.svelte')}
                        {#await VideoEmbedFullscreenPromise then module}
                            {@const VideoEmbedFullscreen = module.default}
                            {@const videoUrl = embedFullscreenData.decodedContent?.url || embedFullscreenData.attrs?.url || ''}
                            {@const videoTitle = embedFullscreenData.decodedContent?.title || embedFullscreenData.attrs?.title}
                            {@const videoId = embedFullscreenData.decodedContent?.videoId || embedFullscreenData.attrs?.videoId}
                            {@const restoreFromPip = embedFullscreenData.restoreFromPip || false}
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
       Side-by-Side Layout for Ultra-Wide Screens (>1300px)
       Shows embed fullscreen next to chat instead of overlay
       =========================================== */
    
    /* When side-by-side mode is active, content-container uses row layout */
    .content-container.side-by-side {
        flex-direction: row;
        gap: 10px; /* Gap between chat card and fullscreen card */
    }
    
    /* Chat wrapper shrinks to make room for side panel - limited to 400px for maximum fullscreen space */
    /* At 400px width, the chat should use narrow/mobile-like styling */
    .chat-wrapper.side-by-side-chat {
        flex: 0 0 400px;
        max-width: 400px;
        min-width: 400px; /* Fixed width for consistent layout */
        position: relative;
        /* Rounded edges to look like a separate card (chat remains in main container) */
        border-radius: 17px;
        overflow: hidden;
        transition: flex 0.4s cubic-bezier(0.4, 0, 0.2, 1), 
                    max-width 0.4s cubic-bezier(0.4, 0, 0.2, 1),
                    min-width 0.4s cubic-bezier(0.4, 0, 0.2, 1);
    }
    
    /* Force narrow/mobile styling on chat wrapper in side-by-side mode */
    /* This ensures mobile-friendly layouts are used when chat is 400px wide */
    .chat-wrapper.side-by-side-chat .top-buttons {
        top: 10px;
        left: 10px;
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
        /* Smooth transition when appearing/disappearing */
        animation: slideInFromRight 0.4s cubic-bezier(0.4, 0, 0.2, 1);
    }
    
    /* Animation for side panel appearing */
    @keyframes slideInFromRight {
        from {
            opacity: 0;
            transform: translateX(20px);
        }
        to {
            opacity: 1;
            transform: translateX(0);
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
    
    /* Chat wrapper in side-by-side mode should look like a card */
    .active-chat-container.side-by-side-active .chat-wrapper.side-by-side-chat {
        background-color: var(--color-grey-20);
        box-shadow: 0 0 12px rgba(0, 0, 0, 0.25);
    }

    .center-content {
        position: absolute;
        top: 40%;
        left: 50%;
        transform: translate(-50%, -50%);
        text-align: center;
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
        text-align: center;
        font-size: 0.8rem;
        color: var(--color-grey-60);
        padding: 4px 0;
        height: 20px; /* Allocate space to prevent layout shift */
        font-style: italic;
    }
    
    .sync-loading-message {
        text-align: center;
        font-size: 0.85rem;
        color: var(--color-grey-60);
        padding: 8px 16px;
        margin-bottom: 12px;
        background-color: var(--color-grey-15);
        border-radius: 8px;
        font-style: italic;
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
