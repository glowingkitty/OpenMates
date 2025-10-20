<script lang="ts">
    import MessageInput from './enter_message/MessageInput.svelte';
    import CodeFullscreen from './fullscreen_previews/CodeFullscreen.svelte';
    import ChatHistory from './ChatHistory.svelte';
    import NewChatSuggestions from './NewChatSuggestions.svelte';
    import FollowUpSuggestions from './FollowUpSuggestions.svelte';
    import { isMobileView } from '../stores/uiStateStore';
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
    import KeyboardShortcuts from './KeyboardShortcuts.svelte';
    import { userProfile, loadUserProfileFromDB } from '../stores/userProfile';
    import { isInSignupProcess, currentSignupStep, getStepFromPath, isLoggingOut } from '../stores/signupState';
    import { initializeApp } from '../app';
    import { aiTypingStore, type AITypingStatus } from '../stores/aiTypingStore'; // Import the new store
    import { decryptWithMasterKey } from '../services/cryptoService'; // Import decryption function
    import { parse_message } from '../message_parsing/parse_message'; // Import markdown parser
    import { draftEditorUIState } from '../services/drafts/draftState'; // Import draft state
    import { phasedSyncState } from '../stores/phasedSyncStateStore'; // Import phased sync state store
    import { websocketStatus } from '../stores/websocketStatusStore'; // Import WebSocket status for connection checks
    import { activeChatStore } from '../stores/activeChatStore'; // For clearing persistent active chat selection
    
    const dispatch = createEventDispatcher();
    
    // Get username from the store using Svelte 5 $derived
    let username = $derived($userProfile.username || 'Guest');

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
        
        // Keep the flags active for a moment to prevent UI flash
        setTimeout(() => {
            isLoggingOut.set(false);
        }, 500);
    }

    // Fix the reactive statement to properly handle logout during signup using Svelte 5 $derived
    let showChat = $derived($authStore.isAuthenticated && !$isInSignupProcess);

    // Reset the flags when auth state changes using Svelte 5 $effect
    $effect(() => {
        if (!$authStore.isAuthenticated) {
            isLoggingOutFromSignup = false;
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
    let isAtBottom = $state(true); // Start as true (new chat or at bottom initially)
    
    // Track if message input is focused (for showing follow-up suggestions)
    let messageInputFocused = $state(false);

    // Track follow-up suggestions for the current chat
    let followUpSuggestions = $state<string[]>([]);

    // Debug suggestions visibility
    $effect(() => {
        console.debug('[ActiveChat] Suggestions visibility check:', {
            showWelcome,
            showActionButtons,
            isAtBottom,
            messageInputFocused,
            followUpSuggestionsCount: followUpSuggestions.length,
            shouldShowFollowUp: showFollowUpSuggestions,
            shouldShowNewChat: showWelcome && showActionButtons
        });
    });

    // Reactive variable to determine when to show the create chat button using Svelte 5 $derived.
    // The button appears when the chat history is not empty or when there's a draft.
    let createButtonVisible = $derived(!showWelcome || messageInputHasContent);
    
    // Reactive variable to determine when to show action buttons in MessageInput
    // Shows when: new chat (showWelcome) OR at bottom of chat OR user focuses input (handled in MessageInput)
    let showActionButtons = $derived(showWelcome || isAtBottom);
    
    // Reactive variable to determine when to show follow-up suggestions
    // Only show when message input is focused (not just when at bottom)
    let showFollowUpSuggestions = $derived(!showWelcome && messageInputFocused && followUpSuggestions.length > 0);

    // Add state for current chat using $state
    let currentChat = $state<Chat | null>(null);
    let currentMessages = $state<ChatMessageModel[]>([]); // Holds messages for the currentChat - MUST use $state for Svelte 5 reactivity
    let currentTypingStatus: AITypingStatus | null = null;
    
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
                
                // Notify backend about the active chat
                chatSyncService.sendSetActiveChat(currentChat.chat_id);
            }
            // Reset the signal
            draftEditorUIState.update(s => ({ ...s, newlyCreatedChatIdToSelect: null }));
        }
    });

    // Reactive variable for typing indicator text
    // Updated to show {mate} is typing (with model name) or "Processing..."
    // NB: AITypingStatus type definition (in '../stores/aiTypingStore.ts') and the aiTypingStore itself 
    // will need to be updated to include an optional 'modelName' field, e.g.:
    // export type AITypingStatus = { 
    //   isTyping: boolean, 
    //   category: string | null, 
    //   modelName?: string | null, // Added field
    //   chatId: string | null, 
    //   userMessageId: string | null, 
    //   aiMessageId: string | null 
    // };
    // Using Svelte 5 $derived for typing indicator text
    let typingIndicatorText = $derived((() => {
        // aiTaskStateTrigger is a top-level reactive variable.
        // Its change will trigger re-evaluation of this derived value.
        if (currentTypingStatus?.isTyping && currentTypingStatus.chatId === currentChat?.chat_id && currentTypingStatus.category) {
            const mateName = $text('mates.' + currentTypingStatus.category + '.text');
            // Default to "AI" if modelName is not provided or empty
            const modelName = currentTypingStatus.modelName || 'AI'; 
            
            // The translation string is: "{mate} is typing...\nPowered by {model_name}"
            let message = $text('enter_message.is_typing_powered_by.text')
                            .replace('{mate}', mateName)
                            .replace('{model_name}', modelName); // modelName will be "AI" if original was empty
            
            // No need to remove "Powered by" part anymore, as modelName defaults to "AI"
            return message;
        }
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

        console.debug("[ActiveChat] handleSendMessage: Received message payload:", message);
        if (newChat) {
            console.debug("[ActiveChat] handleSendMessage: New chat detected, setting currentChat and initializing messages.", newChat);
            currentChat = newChat; // Immediately set currentChat if a new chat was created
            currentMessages = [message]; // Initialize messages with the first message
            
            // Clear temporary chat ID since we now have a real chat
            temporaryChatId = null;
            console.debug("[ActiveChat] New chat created from message, cleared temporary chat ID");
            
            // Notify backend about the active chat
            chatSyncService.sendSetActiveChat(currentChat.chat_id);
            
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
    function handleNewChatClick() {
        console.debug("[ActiveChat] New chat creation initiated");
        // Reset current chat metadata and messages
        currentChat = null;
        currentMessages = [];
        showWelcome = true; // Show welcome message for new chat
        isAtBottom = true; // Reset to show action buttons for new chat
        
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
        if (messageInputFieldRef?.clearMessageField) {
            messageInputFieldRef.clearMessageField();
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
        const freshChat = await chatDB.getChat(chat.chat_id); // Get fresh chat data (without draft)
        currentChat = freshChat || chat; // currentChat is now just metadata
        
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
            newMessages = await chatDB.getMessagesForChat(currentChat.chat_id);
        }
        currentMessages = newMessages;

        showWelcome = currentMessages.length === 0;
        
        // Set isAtBottom based on whether we have a saved scroll position
        // If no saved position, we'll scroll to bottom, so show buttons
        // If there is a saved position, user was scrolled up, so hide buttons
        isAtBottom = !currentChat.last_visible_message_id;

        // Load follow-up suggestions from chat metadata
        if (currentChat.encrypted_follow_up_request_suggestions) {
            try {
                const chatKey = chatDB.getOrGenerateChatKey(currentChat.chat_id);
                const { decryptArrayWithChatKey } = await import('../services/cryptoService');
                followUpSuggestions = decryptArrayWithChatKey(currentChat.encrypted_follow_up_request_suggestions, chatKey) || [];
                console.debug('[ActiveChat] Loaded follow-up suggestions from database:', $state.snapshot(followUpSuggestions));
            } catch (error) {
                console.error('[ActiveChat] Failed to decrypt follow-up suggestions:', error);
                followUpSuggestions = [];
            }
        } else {
            followUpSuggestions = [];
        }

        if (chatHistoryRef) {
            // Update messages
            chatHistoryRef.updateMessages(currentMessages);
            
            // Wait for messages to render, then restore scroll position
            setTimeout(() => {
                // Restore scroll position after messages are rendered
                if (currentChat.last_visible_message_id) {
                    chatHistoryRef.restoreScrollPosition(currentChat.last_visible_message_id);
                } else {
                    // No saved position - scroll to bottom (newest messages)
                    chatHistoryRef.scrollToBottom();
                }
            }, 100); // Short wait for messages to render
        }
 
        // Access the encrypted draft directly from the currentChat object.
        // The currentChat object should have been populated with encrypted_draft_md and draft_v
        // by the time it's passed to this function or fetched by chatDB.getChat().
        const encryptedDraftMd = currentChat?.encrypted_draft_md;
        const draftVersion = currentChat?.draft_v;

        if (messageInputFieldRef && encryptedDraftMd) {
            console.debug(`[ActiveChat] Loading current user's encrypted draft for chat ${currentChat.chat_id}, version: ${draftVersion}`);
            
            // Decrypt the draft content and convert to TipTap JSON
            try {
                const decryptedMarkdown = decryptWithMasterKey(encryptedDraftMd);
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
                    messageInputFieldRef.clearMessageField(false);
                }
            } catch (error) {
                console.error(`[ActiveChat] Error decrypting/parsing draft for chat ${currentChat.chat_id}:`, error);
                messageInputFieldRef.clearMessageField(false);
            }
        } else if (messageInputFieldRef) {
            console.debug(`[ActiveChat] No draft found for current user in chat ${currentChat.chat_id}. Clearing editor.`);
            messageInputFieldRef.clearMessageField(false);
        }
        
        // Notify backend about the active chat, but only if WebSocket is connected
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
                console.debug('[ActiveChat] WebSocket connected, sending deferred active chat notification');
                chatSyncService.sendSetActiveChat(chatIdToNotify);
                // Remove the listener after sending
                chatSyncService.removeEventListener('webSocketConnected', sendNotificationOnConnect as EventListener);
            };
            
            chatSyncService.addEventListener('webSocketConnected', sendNotificationOnConnect as EventListener);
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
            if ($authStore.isAuthenticated && $userProfile.last_opened?.startsWith('/signup/')) {
                console.debug("User detected in signup process:", $userProfile.last_opened);
                // Set the signup process state to true so the signup component shows in Login
                isInSignupProcess.set(true);
                
                // Extract step from last_opened to ensure we're on the right step
                if ($userProfile.last_opened) {
                    const step = getStepFromPath($userProfile.last_opened);
                    console.debug("Setting signup step to:", step);
                    currentSignupStep.set(step);
                }
            }
        };

        initialize();

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

<div class="active-chat-container" class:dimmed={isDimmed} class:login-mode={!showChat} class:scaled={activeScaling}>
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
                                <button 
                                    class="clickable-icon icon_create top-button" 
                                    aria-label={$text('chat.new_chat.text')}
                                    onclick={handleNewChatClick}
                                    in:fade={{ duration: 300 }}
                                    use:tooltip
                                >
                                </button>
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
                                    <h2>{@html $text('chat.welcome.hey_user.text').replace('{username}', username)}</h2>
                                    <p>{@html $text('chat.welcome.what_do_you_need_help_with.text')}</p>
                                </div>
                            </div>
                        </div>
                    {/if}

                    <ChatHistory
                        bind:this={chatHistoryRef}
                        messageInputHeight={isFullscreen ? 0 : messageInputHeight + 40}
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
                                messageInputContent={messageInputHasContent ? messageInputFieldRef?.getTextContent?.() || '' : ''}
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

    /* Add right margin for mobile when menu is open */
    @media (max-width: 1099px) {
        .active-chat-container {
            margin-right: 0;
        }
    }

    .active-chat-container.login-mode {
        background-color: var(--color-grey-0);
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

    @media (max-width: 730px) {
        .center-content {
            top: 30%;
        }
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

    @media (max-width: 730px) {
        .message-input-container {
            padding: 10px;
        }
        .typing-indicator {
            font-size: 0.75rem;
        }
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

    /* Only apply side-by-side layout on screens wider than 1700px */
    @media (min-width: 1701px) {
        .chat-wrapper.fullscreen {
            flex-direction: row;
        }

        .chat-wrapper.fullscreen .chat-side {
            width: 65%;
            padding-right: 20px;
        }

        .chat-wrapper.fullscreen .message-input-wrapper { /* Changed from .message-input-container */
            width: 35%;
            min-width: 400px;
            padding: 20px;
            align-items: flex-start;
        }
    }

    /* Override fullscreen styles for screens <= 1700px */
    @media (max-width: 1700px) {
        .chat-wrapper.fullscreen {
            flex-direction: column;
        }

        .chat-wrapper.fullscreen .chat-side {
            width: 100%;
            padding-right: 0;
        }

        .chat-wrapper.fullscreen .message-input-wrapper { /* Changed from .message-input-container */
            position: absolute;
            bottom: 0;
            left: 0;
            right: 0;
            width: 100%;
            /* padding for message-input-container is already 15px */
        }
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
        top: 30px;
        left: 20px;
        display: flex;
        justify-content: space-between; /* Distribute space between left and right buttons */
        z-index: 1;
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

    /* Add scaling transition for the active-chat-container when a new chat is created */
    .active-chat-container {
        transition: transform 0.2s ease-in-out, opacity 0.3s ease; /* added transform transition */
    }

    .active-chat-container.scaled {
        transform: scale(0.95);
    }

</style>
