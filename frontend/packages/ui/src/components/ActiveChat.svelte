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
    import WebSearchSkillPreview from './app_skills/WebSearchSkillPreview.svelte';
    import WebSearchSkillFullscreen from './app_skills/WebSearchSkillFullscreen.svelte';
    import VideoTranscriptSkillPreview from './app_skills/VideoTranscriptSkillPreview.svelte';
    import VideoTranscriptSkillFullscreen from './app_skills/VideoTranscriptSkillFullscreen.svelte';
    import WebsiteFullscreen from './embeds/WebsiteFullscreen.svelte';
    import { userProfile, loadUserProfileFromDB } from '../stores/userProfile';
    import { isInSignupProcess, currentSignupStep, getStepFromPath, isLoggingOut, isSignupPath } from '../stores/signupState';
    import { initializeApp } from '../app';
    import { aiTypingStore, type AITypingStatus } from '../stores/aiTypingStore'; // Import the new store
    import { decryptWithMasterKey } from '../services/cryptoService'; // Import decryption function
    import { parse_message } from '../message_parsing/parse_message'; // Import markdown parser
    import { loadSessionStorageDraft, migrateSessionStorageDraftsToIndexedDB } from '../services/drafts/sessionStorageDraftService'; // Import sessionStorage draft service
    import { draftEditorUIState } from '../services/drafts/draftState'; // Import draft state
    import { phasedSyncState } from '../stores/phasedSyncStateStore'; // Import phased sync state store
    import { websocketStatus } from '../stores/websocketStatusStore'; // Import WebSocket status for connection checks
    import { activeChatStore } from '../stores/activeChatStore'; // For clearing persistent active chat selection
    import { DEMO_CHATS, LEGAL_CHATS, getDemoMessages, isPublicChat, translateDemoChat } from '../demo_chats'; // Import demo chat utilities
    import { convertDemoChatToChat } from '../demo_chats/convertToChat'; // Import conversion function
    import { isDesktop } from '../utils/platform'; // Import desktop detection for conditional auto-focus
    
    const dispatch = createEventDispatcher();
    
    // Get username from the store using Svelte 5 $derived
    // Use empty string for non-authenticated users - translation will handle "Hey there!" vs "Hey {username}!"
    let username = $derived($userProfile.username || '');

    // Add state for code fullscreen using $state
    let showCodeFullscreen = $state(false);
    let fullscreenCodeData = $state({
        code: '',
        filename: '',
        language: '',
        lineCount: 0
    });

    // Add state to track logout from signup
    let isLoggingOutFromSignup = false;

    async function handleLoginSuccess(event) {
        const { user, inSignupFlow } = event.detail;
        console.debug("Login success, in signup flow:", inSignupFlow);
        
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
    }

    // Modify handleLogout to track signup state and reset signup step
    async function handleLogout() {
        // Set the flag if we're in signup process
        isLoggingOutFromSignup = $isInSignupProcess;
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
            isLoggingOutFromSignup = false;
            
            // CRITICAL: Backup handler for logout - ensures demo chat loads even if userLoggingOut event wasn't caught
            // This is especially important on mobile where event timing might be off
            // Only trigger if we have a current chat that's not a demo chat (user was logged in)
            if (currentChat && !isPublicChat(currentChat.chat_id)) {
                console.debug('[ActiveChat] Auth state changed to unauthenticated - clearing user chat and loading demo chat (backup handler)');
                
                // Clear current chat state
                currentChat = null;
                currentMessages = [];
                followUpSuggestions = [];
                showWelcome = true;
                isAtBottom = false;
                
                // Clear the persistent store
                activeChatStore.clearActiveChat();
                
                // Load demo welcome chat
                (async () => {
                    try {
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
            if ($loginInterfaceOpen) {
                loginInterfaceOpen.set(false);
                // Only open chats panel on desktop (not mobile) when closing login interface after successful login
                // On mobile, let the user manually open the panel if they want to see the chat list
                if (!$panelState.isActivityHistoryOpen && !$isMobileView) {
                    panelState.toggleChats();
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
                    } catch (e) {
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
    
    // Handler for embed fullscreen events (from embed renderers)
    async function handleEmbedFullscreen(event: CustomEvent) {
        console.debug('[ActiveChat] Received embedfullscreen event:', event.detail);
        
        const { embedId, embedData, decodedContent, embedType, attrs } = event.detail;
        
        // If embedData is not provided, load it from EmbedStore
        let finalEmbedData = embedData;
        let finalDecodedContent = decodedContent;
        
        if (!finalEmbedData && embedId) {
            try {
                const { resolveEmbed, decodeToonContent } = await import('../services/embedResolver');
                finalEmbedData = await resolveEmbed(embedId);
                
                if (finalEmbedData && finalEmbedData.content) {
                    finalDecodedContent = await decodeToonContent(finalEmbedData.content);
                }
            } catch (error) {
                console.error('[ActiveChat] Error loading embed for fullscreen:', error);
                return;
            }
        }
        
        // Store fullscreen data
        embedFullscreenData = {
            embedId,
            embedData: finalEmbedData,
            decodedContent: finalDecodedContent,
            embedType,
            attrs
        };
        
        showEmbedFullscreen = true;
        console.debug('[ActiveChat] Opening embed fullscreen:', embedType, embedId);
    }
    
    // Handler for closing embed fullscreen
    function handleCloseEmbedFullscreen() {
        showEmbedFullscreen = false;
        embedFullscreenData = null;
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
        console.debug('[ActiveChat] Post-processing completed for chat:', chatId);
        console.debug('[ActiveChat] Received follow-up suggestions:', newSuggestions);

        // Update follow-up suggestions if this is the active chat
        if (currentChat?.chat_id === chatId && newSuggestions && Array.isArray(newSuggestions)) {
            followUpSuggestions = newSuggestions;
            console.debug('[ActiveChat] Updated followUpSuggestions:', $state.snapshot(followUpSuggestions));
            
            // Also reload currentChat from database to ensure it has the latest encrypted metadata
            // This prevents a mismatch between the in-memory currentChat and the database state
            try {
                const freshChat = await chatDB.getChat(chatId);
                if (freshChat) {
                    currentChat = { ...currentChat, ...freshChat };
                    console.debug('[ActiveChat] Refreshed currentChat with latest metadata from database after post-processing');
                }
            } catch (error) {
                console.error('[ActiveChat] Failed to refresh currentChat after post-processing:', error);
            }
        }
    }

    // Add handler for closing code fullscreen
    function handleCloseCodeFullscreen() {
        showCodeFullscreen = false;
    }

    // Subscribe to store values
    // Add class when menu is open AND in mobile view using Svelte 5 $derived
    let isDimmed = $derived(($panelState && $panelState.isSettingsOpen) && $isMobileView);

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

    let aiTaskStateTrigger = 0; // Reactive trigger for AI task state changes

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
        // aiTaskStateTrigger is a top-level reactive variable.
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
            const modelName = currentTypingStatus.modelName || 'AI'; 
            const providerName = currentTypingStatus.providerName || 'AI';
            
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
    function plainTextToTiptapJson(text: string): TiptapJSON {
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
        const chunk = event.detail as any; // AIMessageUpdatePayload
        console.debug(`[ActiveChat] handleAiMessageChunk: Event for chat_id: ${chunk.chat_id}. Current active chat_id: ${currentChat?.chat_id}`);

        if (!currentChat || currentChat.chat_id !== chunk.chat_id) {
            console.warn('[ActiveChat] handleAiMessageChunk: Received AI chunk for non-active chat or no current chat. Current:', currentChat?.chat_id, 'Chunk:', chunk.chat_id, 'Ignoring.');
            return;
        }

        // console.debug('[ActiveChat] handleAiMessageChunk: Processing AI message chunk for active chat:', chunk);

        // Operate on currentMessages state
        let targetMessageIndex = currentMessages.findIndex(m => m.message_id === chunk.message_id);
        let targetMessage: ChatMessageModel | null = targetMessageIndex !== -1 ? { ...currentMessages[targetMessageIndex] } : null;

        let messageToSave: ChatMessageModel | null = null;
        let isNewMessageInStream = false;

        if (!targetMessage) {
            // Create new message if first chunk or no AI message yet, or last message was user's
            if (chunk.sequence === 1 || currentMessages.length === 0 || (currentMessages.length > 0 && currentMessages[currentMessages.length - 1].role === 'user')) {
                // CRITICAL: Store AI response as markdown string, not Tiptap JSON
                // Tiptap JSON is only for UI rendering, never stored in database
                const newAiMessage: ChatMessageModel = {
                    message_id: chunk.message_id,
                    chat_id: chunk.chat_id, // Ensure this is correct
                    user_message_id: chunk.user_message_id,
                    role: 'assistant',
                    category: currentTypingStatus?.chatId === chunk.chat_id ? currentTypingStatus.category : undefined,
                    content: chunk.full_content_so_far || '', // Store as markdown string, not Tiptap JSON
                    status: 'streaming',
                    created_at: Math.floor(Date.now() / 1000),
                    // Required encrypted fields (will be populated by encryptMessageFields)
                    encrypted_content: '', // Will be set by encryption
                    // encrypted_sender_name not needed for assistant messages
                    encrypted_category: undefined
                };
                currentMessages = [...currentMessages, newAiMessage];
                messageToSave = newAiMessage;
                isNewMessageInStream = true;
                console.debug('[ActiveChat] Created new AI message for streaming:', newAiMessage);
            } else {
                console.warn('[ActiveChat] AI chunk received for unknown message_id, but not first chunk and last message not user. Ignoring.', chunk);
                return;
            }
        } else {
            // Update existing message
            // Only update content if full_content_so_far is not empty,
            // or if it's the first chunk (sequence 1) where it might legitimately start empty.
            if (chunk.full_content_so_far || chunk.sequence === 1) {
                // CRITICAL: Store AI response as markdown string, not Tiptap JSON
                targetMessage.content = chunk.full_content_so_far || '';
            }
            if (targetMessage.status !== 'streaming') {
                targetMessage.status = 'streaming';
            }
            currentMessages[targetMessageIndex] = targetMessage;
            currentMessages = [...currentMessages]; // New array reference for Svelte reactivity
            messageToSave = targetMessage;
        }
        
        // Update UI
        if (chatHistoryRef) {
            chatHistoryRef.updateMessages(currentMessages);
        }

        // Save to IndexedDB
        if (messageToSave) {
            try {
                // Check if this message already exists to prevent duplicates
                const existingMessage = await chatDB.getMessage(messageToSave.message_id);
                if (existingMessage && !isNewMessageInStream) {
                    console.debug(`[ActiveChat] Message ${messageToSave.message_id} already exists in DB, skipping duplicate save`);
                } else {
                    console.debug(`[ActiveChat] Saving/Updating AI message to DB (isNew: ${isNewMessageInStream}):`, messageToSave);
                    await chatDB.saveMessage(messageToSave); // saveMessage handles both add and update
                }
            } catch (error) {
                console.error('[ActiveChat] Error saving/updating AI message to DB:', error);
            }
        }

        if (chunk.is_final_chunk) {
            console.debug('[ActiveChat] Final AI chunk marker received for message_id:', chunk.message_id);
            const finalMessageInArray = currentMessages.find(m => m.message_id === chunk.message_id);
            if (finalMessageInArray) {
                const updatedFinalMessage = { ...finalMessageInArray, status: 'synced' as const };
                
                // Update in currentMessages array for UI
                const finalMessageIndex = currentMessages.findIndex(m => m.message_id === chunk.message_id);
                if (finalMessageIndex !== -1) {
                    currentMessages[finalMessageIndex] = updatedFinalMessage;
                    currentMessages = [...currentMessages]; // Ensure reactivity for UI
                }

                // Save status update to DB
                try {
                    console.debug('[ActiveChat] Updating final AI message status in DB:', updatedFinalMessage);
                    // Only save if the status actually changed to prevent unnecessary saves
                    const existingMessage = await chatDB.getMessage(updatedFinalMessage.message_id);
                    if (!existingMessage || existingMessage.status !== 'synced') {
                        await chatDB.saveMessage(updatedFinalMessage);
                    } else {
                        console.debug('[ActiveChat] Message already has synced status, skipping save');
                    }
                } catch (error) {
                    console.error('[ActiveChat] Error updating final AI message status to DB:', error);
                }
                
                // CRITICAL: Send encrypted AI response back to server for Directus storage (zero-knowledge architecture)
                // This uses a separate event type 'ai_response_completed' to avoid triggering AI processing
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
        if (newChat) {
            console.debug("[ActiveChat] handleSendMessage: New chat detected, setting currentChat and initializing messages.", newChat);
            currentChat = newChat; // Immediately set currentChat if a new chat was created
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
            currentMessages = [...currentMessages, message];
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
        
        // CRITICAL: Clear currentChatId in draft state after preserving context
        // This ensures that when the user types in the new chat, a new chat ID will be generated
        // instead of using the previous chat's ID (which would overwrite the previous draft)
        // We've already preserved the previous chat's draft above, so it's safe to clear the chat ID
        draftEditorUIState.update(s => ({
            ...s,
            currentChatId: null, // Clear chat ID so a new one is generated when user types
            newlyCreatedChatIdToSelect: null // Clear any pending selection
        }));
        console.debug("[ActiveChat] Cleared currentChatId in draft state for new chat");
        // Reset live input text state to clear search term for NewChatSuggestions
        // This ensures suggestions show the random 3 instead of filtering with old search term
        liveInputText = '';
        messageInputHasContent = false;
        console.debug("[ActiveChat] Reset liveInputText and messageInputHasContent");
        
        // Focus the message input field on desktop devices only
        // On touch devices (iPhone/iPad), programmatic focus doesn't trigger the virtual keyboard
        // and can cause unwanted layout shifts. Users expect to manually tap the input on mobile.
        if (isDesktop()) {
            setTimeout(() => {
                if (messageInputFieldRef?.focus) {
                    messageInputFieldRef.focus();
                    console.debug("[ActiveChat] Focused message input after new chat creation (desktop)");
                }
            }, 100); // Small delay to ensure DOM is ready
        } else {
            console.debug("[ActiveChat] Skipping auto-focus on touch device - user will tap input manually");
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

    // Add a handler for the share button click.
    // This function will be triggered when the share button is clicked.
    function handleShareChat() {
        // Using console.debug for logging in Svelte.
        console.debug("[ActiveChat] Share chat button clicked.");
        // TODO: Insert the actual share logic here if needed.
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

    async function loadMessagesForCurrentChat() {
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
                Object.entries(chatMetadata).filter(([key, value]) => value !== undefined)
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
        // For public chats (demo/legal), skip database access - use the chat object directly
        // This is critical during logout when database is being deleted
        let freshChat: Chat | null = null;
        if (isPublicChat(chat.chat_id)) {
            // Public chats don't need database access - use the provided chat object
            freshChat = chat;
            console.debug(`[ActiveChat] Loading public chat ${chat.chat_id} - skipping database access`);
        } else {
            // For real chats, try to get fresh data from database
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
        
        // Clear temporary chat ID since we now have a real chat
        temporaryChatId = null;
        console.debug("[ActiveChat] Loaded real chat, cleared temporary chat ID");
        
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
            } else {
                // For real chats, load messages from IndexedDB
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
                if (isPublicChat(currentChat.chat_id)) {
                    chatHistoryRef.scrollToTop();
                    console.debug('[ActiveChat] Public chat - scrolled to top (unread)');
                    // After scrolling to top, explicitly set isAtBottom to false
                    // handleScrollPositionUI will confirm this after scroll completes
                    setTimeout(() => {
                        isAtBottom = false;
                        console.debug('[ActiveChat] Set isAtBottom=false after scrolling demo chat to top');
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
                if (sessionDraft) {
                    console.debug(`[ActiveChat] Loading sessionStorage draft for demo chat ${currentChat.chat_id}`);
                    setTimeout(() => {
                        messageInputFieldRef.setDraftContent(currentChat.chat_id, sessionDraft, 0, false);
                    }, 50);
                } else {
                    console.debug(`[ActiveChat] No sessionStorage draft found for demo chat ${currentChat.chat_id}. Clearing editor.`);
                    // CRITICAL: Preserve context when clearing - we're just switching to a chat with no draft
                    // This prevents deleting the previous chat's draft during context switches
                    await messageInputFieldRef.clearMessageField(false, true);
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
            
            // Generate a temporary chat ID for draft saving if no chat is loaded
            // This ensures the draft service always has a chat ID to work with
            if (!currentChat?.chat_id && !temporaryChatId) {
                temporaryChatId = crypto.randomUUID();
                console.debug("[ActiveChat] Generated temporary chat ID for draft saving:", temporaryChatId);
            }
            
            // Check if the user is in the middle of a signup process (based on last_opened)
            // Also check if tfa_enabled is false (signup incomplete)
            if ($authStore.isAuthenticated && 
                (isSignupPath($userProfile.last_opened) || $userProfile.tfa_enabled === false)) {
                console.debug("User detected in signup process:", {
                    last_opened: $userProfile.last_opened,
                    tfa_enabled: $userProfile.tfa_enabled
                });
                // Set the signup process state to true so the signup component shows in Login
                isInSignupProcess.set(true);
                
                // Open login interface to show signup flow
                loginInterfaceOpen.set(true);
                
                // Extract step from last_opened to ensure we're on the right step
                if (isSignupPath($userProfile.last_opened)) {
                    const step = getStepFromPath($userProfile.last_opened);
                    console.debug("Setting signup step to:", step);
                    currentSignupStep.set(step);
                } else if ($userProfile.tfa_enabled === false) {
                    // If tfa_enabled is false but last_opened doesn't indicate signup,
                    // default to one_time_codes step (OTP setup)
                    console.debug("tfa_enabled is false, defaulting to one_time_codes step");
                    currentSignupStep.set('one_time_codes');
                }
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
                        // Double-check that chat still isn't loaded (might have been loaded by +page.svelte)
                        if (!currentChat?.chat_id && $activeChatStore !== 'demo-welcome') {
                            activeChatStore.setActiveChat('demo-welcome');
                            loadChat(welcomeChat);
                            console.debug("[ActiveChat] [NON-AUTH] ✅ Fallback: Welcome chat loaded successfully");
                        } else {
                            console.debug("[ActiveChat] [NON-AUTH] Fallback: Welcome chat already loaded, skipping");
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
        
        // Add event listeners for login interface and demo chat
        window.addEventListener('closeLoginInterface', handleCloseLoginInterface);
        window.addEventListener('loadDemoChat', handleLoadDemoChat);
        
        // Cleanup on destroy
        return () => {
            document.removeEventListener('embedfullscreen', embedFullscreenHandler as EventListener);
            window.removeEventListener('openLoginInterface', handleOpenLoginInterface as EventListener);
            window.removeEventListener('closeLoginInterface', handleCloseLoginInterface as EventListener);
            window.removeEventListener('loadDemoChat', handleLoadDemoChat as EventListener);
        };
        
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
                    
                    // CRITICAL: Ensure loadChat is called even if there are errors
                    // Wrap in try-catch to handle any potential errors gracefully
                    try {
                        await loadChat(welcomeChat);
                        console.debug('[ActiveChat] ✅ Demo welcome chat loaded after logout');
                    } catch (loadError) {
                        console.error('[ActiveChat] Error loading demo chat after logout:', loadError);
                        // Even if loadChat fails, ensure UI shows welcome state
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
                }
            } catch (error) {
                console.error('[ActiveChat] Error in logout event handler:', error);
                // Fallback: ensure UI is cleared even if handler fails
                currentChat = null;
                currentMessages = [];
                showWelcome = true;
                activeChatStore.clearActiveChat();
            }
        };
        window.addEventListener('userLoggingOut', handleLogoutEvent);
        
        // Add language change listener to reload public chats (demo + legal) when language changes
        const handleLanguageChange = async () => {
            if (currentChat && isPublicChat(currentChat.chat_id)) {
                console.debug('[ActiveChat] Language changed, reloading public chat:', currentChat.chat_id);
                
                // Find the public chat (check both DEMO_CHATS and LEGAL_CHATS) and translate it
                let publicChat = DEMO_CHATS.find(chat => chat.chat_id === currentChat.chat_id);
                if (!publicChat) {
                    publicChat = LEGAL_CHATS.find(chat => chat.chat_id === currentChat.chat_id);
                }
                if (publicChat) {
                    const translatedChat = translateDemoChat(publicChat);
                    
                    // Reload the public chat messages with new translations (check both DEMO_CHATS and LEGAL_CHATS)
                    const newMessages = getDemoMessages(currentChat.chat_id, DEMO_CHATS, LEGAL_CHATS);
                    currentMessages = newMessages;
                    
                    // Reload follow-up suggestions with new translations
                    if (translatedChat.follow_up_suggestions) {
                        followUpSuggestions = translatedChat.follow_up_suggestions;
                        console.debug('[ActiveChat] Reloaded follow-up suggestions:', $state.snapshot(followUpSuggestions));
                    }
                    
                    // Update chat history display
                    if (chatHistoryRef) {
                        chatHistoryRef.updateMessages(currentMessages);
                    }
                }
            }
        };
        
        window.addEventListener('language-changed', handleLanguageChange);

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
        chatSyncService.addEventListener('aiMessageChunk', handleAiMessageChunk as EventListener);

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
                aiTaskStateTrigger++;
            }
        }) as EventListener;

        const aiTaskEndedHandler = ((event: CustomEvent<{ chatId: string }>) => {
            if (event.detail.chatId === currentChat?.chat_id) {
                aiTaskStateTrigger++;
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
        chatSyncService.addEventListener('postProcessingCompleted', handlePostProcessingCompleted as EventListener);
        
        // Handle skill preview updates - add app cards to messages
        const handleSkillPreviewUpdate = (event: CustomEvent) => {
            const { task_id, previewData, chat_id, message_id } = event.detail;
            
            // Only process if this preview is for the current chat
            if (!currentChat || currentChat.chat_id !== chat_id) {
                console.debug('[ActiveChat] Skill preview update for different chat, ignoring');
                return;
            }
            
            // Find the message by message_id
            const messageIndex = currentMessages.findIndex(m => m.message_id === message_id);
            if (messageIndex === -1) {
                console.debug('[ActiveChat] Message not found for skill preview update:', message_id);
                return;
            }
            
            // Create app card from skill preview data
            let appCard: any = null;
            if (previewData.app_id === 'web' && previewData.skill_id === 'search') {
                // Create WebSearchSkillPreview card
                appCard = {
                    component: WebSearchSkillPreview,
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
                // Create VideoTranscriptSkillPreview card
                appCard = {
                    component: VideoTranscriptSkillPreview,
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
            skillPreviewService.removeEventListener('skillPreviewUpdate', handleSkillPreviewUpdate as EventListener);
            // Remove language change listener
            window.removeEventListener('language-changed', handleLanguageChange);
            // Remove login interface event listeners
            window.removeEventListener('openLoginInterface', handleOpenLoginInterface as EventListener);
            window.removeEventListener('closeLoginInterface', handleCloseLoginInterface as EventListener);
            window.removeEventListener('loadDemoChat', handleLoadDemoChat as EventListener);
            // Remove draft save sync listener
            window.removeEventListener('localChatListChanged', handleDraftSaveSync as EventListener);
            if (handleLogoutEvent) {
                window.removeEventListener('userLoggingOut', handleLogoutEvent as EventListener);
            }
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
    class:narrow={isNarrow}
    class:medium={isMedium}
    class:wide={isWide}
    class:extra-wide={isExtraWide}
    bind:clientWidth={containerWidth}
>
    {#if !showChat}
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
        >
            <!-- Main content wrapper that will handle the fullscreen layout -->
            <div class="chat-wrapper" class:fullscreen={isFullscreen}>
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
                                <!-- TODO uncomment once share feature is implemented -->
                                <!-- <button
                                    class="clickable-icon icon_share top-button"
                                    aria-label={$text('chat.share.text')}
                                    onclick={handleShareChat}
                                    use:tooltip
                                >
                                </button> -->
                            {/if}
                        </div>

                        <!-- Right side buttons -->
                        <div class="right-buttons">
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
                        containerWidth={containerWidth}
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

                        <!-- Follow-up suggestions when input is focused -->
                        {#if showFollowUpSuggestions}
                            <FollowUpSuggestions
                                suggestions={followUpSuggestions}
                                messageInputContent={liveInputText}
                                onSuggestionClick={handleSuggestionClick}
                            />
                        {/if}

                        <!-- Pass currentChat?.id or temporaryChatId to MessageInput -->
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
            {#if showEmbedFullscreen && embedFullscreenData}
                {#if embedFullscreenData.embedType === 'app-skill-use'}
                    {@const skillId = embedFullscreenData.decodedContent?.skill_id || ''}
                    {@const appId = embedFullscreenData.decodedContent?.app_id || ''}
                    
                    {#if appId === 'web' && skillId === 'search'}
                        <!-- Web Search Fullscreen -->
                        {@const previewData = {
                            app_id: appId,
                            skill_id: skillId,
                            query: embedFullscreenData.decodedContent?.query || '',
                            provider: embedFullscreenData.decodedContent?.provider || 'Brave',
                            status: embedFullscreenData.embedData?.status || 'finished',
                            results: embedFullscreenData.decodedContent?.results || []
                        }}
                        <WebSearchSkillFullscreen 
                            previewData={previewData}
                            onClose={handleCloseEmbedFullscreen}
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
                        <VideoTranscriptSkillFullscreen 
                            previewData={previewData}
                            onClose={handleCloseEmbedFullscreen}
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
                    {@const websiteData = {
                        url: embedFullscreenData.decodedContent?.url || embedFullscreenData.attrs?.url || '',
                        title: embedFullscreenData.decodedContent?.title || embedFullscreenData.attrs?.title,
                        description: embedFullscreenData.decodedContent?.description || embedFullscreenData.attrs?.description,
                        favicon: embedFullscreenData.decodedContent?.meta_url_favicon || embedFullscreenData.decodedContent?.favicon || embedFullscreenData.attrs?.favicon,
                        image: embedFullscreenData.decodedContent?.thumbnail_original || embedFullscreenData.decodedContent?.image || embedFullscreenData.attrs?.image,
                        snippets: embedFullscreenData.decodedContent?.snippets,
                        meta_url_favicon: embedFullscreenData.decodedContent?.meta_url_favicon,
                        thumbnail_original: embedFullscreenData.decodedContent?.thumbnail_original
                    }}
                    {#if websiteData.url}
                        <WebsiteFullscreen 
                            websiteData={websiteData}
                            onClose={handleCloseEmbedFullscreen}
                        />
                    {/if}
                {/if}
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
    @media (max-width: 600px) {
        .active-chat-container.login-mode {
            border-bottom-left-radius: 0;
            border-bottom-right-radius: 0;
            /* Ensure it extends to the bottom of the viewport */
            min-height: 100vh;
            min-height: 100dvh;
        }
    }

    .content-container {
        display: flex;
        flex-direction: column;
        height: 100%;
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
        gap: 25px; /* Space between buttons */
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
        position: absolute;
        top: 0;
        left: 0;
        right: 0;
        bottom: 0;
        display: flex;
        align-items: stretch;
        justify-content: stretch;
        height: 100%;
        overflow: hidden;
    }

    /* Enable scrolling on mobile devices to prevent content cutoff */
    @media (max-width: 730px) {
        .login-wrapper {
            overflow-y: auto;
            overflow-x: hidden;
            -webkit-overflow-scrolling: touch; /* Smooth scrolling on iOS */
            height: 100%; /* Keep height 100% but allow scrolling when content exceeds */
            min-height: 100vh;
            min-height: 100dvh; /* Ensure it extends to bottom of viewport */
            align-items: flex-start; /* Align content to top instead of center */
        }
    }

    /* Add scaling transition for the active-chat-container when a new chat is created */
    .active-chat-container {
        transition: transform 0.2s ease-in-out, opacity 0.3s ease; /* added transform transition */
    }

    .active-chat-container.scaled {
        transform: scale(0.95);
    }

</style>
