<script lang="ts">
    import MessageInput from './enter_message/MessageInput.svelte';
    import CodeFullscreen from './fullscreen_previews/CodeFullscreen.svelte';
    import ChatHistory from './ChatHistory.svelte';
    import { isMobileView } from '../stores/uiStateStore';
    import Login from './Login.svelte';
    import { text } from '@repo/ui';
    import { fade, fly } from 'svelte/transition';
    import { createEventDispatcher, tick, onMount } from 'svelte';
    import { authStore } from '../stores/authStore';
    import { panelState } from '../stores/panelStateStore'; // Added import
    import type { Chat } from '../types/chat';
    import { tooltip } from '../actions/tooltip';
    import { chatDB } from '../services/db';
    import KeyboardShortcuts from './KeyboardShortcuts.svelte';
    import { userProfile, loadUserProfileFromDB } from '../stores/userProfile';
    import { isInSignupProcess, currentSignupStep, getStepFromPath, isLoggingOut } from '../stores/signupState';
    import { initializeApp } from '../app';
    
    const dispatch = createEventDispatcher();
    
    // Get username from the store
    $: username = $userProfile.username || 'Guest';

    // Add state for code fullscreen
    let showCodeFullscreen = false;
    let fullscreenCodeData = {
        code: '',
        filename: '',
        language: '',
        lineCount: 0
    };

    // Add state to track logout from signup
    let isLoggingOutFromSignup = false;

    function handleLoginSuccess(event) {
        const { user, inSignupFlow } = event.detail;
        console.debug("Login success, in signup flow:", inSignupFlow);
    }

    // Modify handleLogout to track signup state and reset signup step
    async function handleLogout() {
        // Set the flag if we're in signup process
        isLoggingOutFromSignup = $isInSignupProcess;
        isLoggingOut.set(true);
        
        // Reset signup step to 1
        currentSignupStep.set(1);
        
        try {
            await authStore.logout();
        } catch (error) {
            console.error('Error during logout:', error);
            authStore.logout();
        }
        
        // Keep the flags active for a moment to prevent UI flash
        setTimeout(() => {
            isLoggingOut.set(false);
        }, 500);
    }

    // Fix the reactive statement to properly handle logout during signup
    $: showChat = $authStore.isAuthenticated && 
                  !$isInSignupProcess && 
                  !isLoggingOutFromSignup &&
                  !$isLoggingOut && 
                  // Use userProfile instead of authStore.user
                  $userProfile.last_opened?.startsWith('/signup/') !== true;

    // Update this line to properly handle all edge cases
    $: showLogin = !showChat || 
                   !$authStore.isAuthenticated || 
                   $isInSignupProcess || 
                   isLoggingOutFromSignup ||
                   $isLoggingOut;

    // Reset the flags when auth state changes
    $: if (!$authStore.isAuthenticated) {
        isLoggingOutFromSignup = false;
    }

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

    // Add handler for closing code fullscreen
    function handleCloseCodeFullscreen() {
        showCodeFullscreen = false;
    }

    // Subscribe to store values
    // Add class when menu is open AND in mobile view
    $: isDimmed = ($panelState && $panelState.isSettingsOpen) && $isMobileView;

    // Add transition for the login wrapper
    let loginTransitionProps = {
        duration: 300,
        y: 20,
        opacity: 0
    };

    // Create a reference for the ChatHistory component
    let chatHistoryRef: any;
    // Create a reference for the MessageInput component
    let messageInputFieldRef: any;

    let isFullscreen = false;
    $: messages = chatHistoryRef?.messages || [];

    // Add state for message input height
    let messageInputHeight = 0;

    let showWelcome = true;

    // Add state variable for scaling animation on the container
    let activeScaling = false;

    // Create a local variable to bind the MessageInput's exported property.
    let messageInputHasContent = false;
    
    // Reactive variable to determine when to show the create chat button.
    // The button appears when either the chat history is not empty (showWelcome is false)
    // OR the MessageInput has content.
    $: createButtonVisible = !showWelcome || messageInputHasContent;

    // Add state for current chat
    let currentChat: Chat | null = null;

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
    function handleSendMessage(event: CustomEvent) {
        const message = event.detail;
        console.debug("[ActiveChat] Adding message:", message);
        chatHistoryRef.addMessage(message);
        showWelcome = false;
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
        // Reset current chat
        currentChat = null;
        // Trigger chat history fade-out and cleaning:
        if (chatHistoryRef?.clearMessages) {
            chatHistoryRef.clearMessages();
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
    }

    // Add a handler for the share button click.
    // This function will be triggered when the share button is clicked.
    function handleShareChat() {
        // Using console.debug for logging in Svelte.
        console.debug("[ActiveChat] Share chat button clicked.");
        // TODO: Insert the actual share logic here if needed.
    }

    // Update handler for chat updates to be more selective
    function handleChatUpdated(event: CustomEvent) {
        const { chat } = event.detail;
        if (!chat || currentChat?.chat_id !== chat.chat_id) return;
        
        console.debug("[ActiveChat] Updating chat messages");
        currentChat = chat;
        
        // Always force a messages update to ensure UI is in sync
        if (chatHistoryRef) {
            chatHistoryRef.updateMessages(chat.messages || []);
        }
    }

    // Handle message status changes without full reload
    function handleMessageStatusChanged(event: CustomEvent) {
        const { chatId, messageId, status } = event.detail;
        if (currentChat?.chat_id !== chatId) return;
        
        // Only update the specific message's status
        chatHistoryRef?.updateMessageStatus(messageId, status);
    }

    // Update the loadChat function
    export async function loadChat(chat: Chat) {
        const freshChat = await chatDB.getChat(chat.chat_id); // Get fresh chat data (without draft)
        currentChat = freshChat || chat;
        showWelcome = false;

        if (chatHistoryRef) {
            await chatHistoryRef.clearMessages();
            if (currentChat.messages?.length) {
                chatHistoryRef.updateMessages(currentChat.messages);
            }
        }

        // Fetch the current user's draft for this chat from IndexedDB.
        // The user context is implicit for client-side DB.
        const userDraft = await chatDB.getUserChatDraft(currentChat.chat_id);

        if (messageInputFieldRef && userDraft?.draft_json) {
            console.debug(`[ActiveChat] Loading current user's draft for chat ${currentChat.chat_id}, version: ${userDraft.version}`);
            messageInputHasContent = true;
            setTimeout(() => {
                // Assuming setDraftContent now takes (chatId, draftContent, draftVersion, isNewDraft)
                messageInputFieldRef.setDraftContent(currentChat.chat_id, userDraft.draft_json, userDraft.version, false);
            }, 50);
        } else if (messageInputFieldRef) {
            console.debug(`[ActiveChat] No draft found for current user in chat ${currentChat.chat_id}. Clearing editor.`);
            messageInputFieldRef.clearMessageField(false);
            messageInputHasContent = false;
        }
    }

    onMount(() => {
        const initialize = async () => {
            // Initialize app but skip auth initialization since it's already done in +page.svelte
            await initializeApp({ skipAuthInitialization: true });
            
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
            const { chatId, messageId, status, chat } = event.detail;
            if (currentChat?.chat_id === chatId) {
                // Update chat with new status
                currentChat = chat;
                // Update message status in chat history
                chatHistoryRef?.updateMessageStatus(messageId, status);
            }
        }) as EventListener;

        window.addEventListener('chatUpdated', chatUpdateHandler);
        window.addEventListener('messageStatusChanged', messageStatusHandler);

        return () => {
            window.removeEventListener('chatUpdated', chatUpdateHandler);
            window.removeEventListener('messageStatusChanged', messageStatusHandler);
        };
    });
</script>

<div class="active-chat-container" class:dimmed={isDimmed} class:login-mode={showLogin} class:scaled={activeScaling}>
    {#if showLogin}
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
                                    on:click={handleNewChatClick}
                                    in:fade={{ duration: 300 }}
                                    use:tooltip
                                >
                                </button>
                            {/if}
                            {#if !showWelcome}
                                <button
                                    class="clickable-icon icon_share top-button"
                                    aria-label={$text('chat.share.text')}
                                    on:click={handleShareChat}
                                    use:tooltip
                                >
                                </button>
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
                        on:messagesStatusChanged={handleMessageStatusChanged}
                    />
                </div>

                <!-- Right side container for message input -->
                <div class="message-input-container">
                    <!-- Pass currentChat?.id to MessageInput -->
                    <MessageInput 
                        bind:this={messageInputFieldRef}
                        bind:hasContent={messageInputHasContent}
                        currentChatId={currentChat?.chat_id}
                        on:codefullscreen={handleCodeFullscreen}
                        on:sendMessage={handleSendMessage}
                        on:heightchange={handleInputHeightChange}
                        on:draftSaved={handleDraftSaved}
                        bind:isFullscreen
                    />
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

    .team-profile {
        display: flex;
        flex-direction: column;
        align-items: center;
        gap: 20px;
    }

    .team-image {
        width: 175px;
        height: 175px;
        border-radius: 50%;
        background-image: url('@openmates/ui/static/images/placeholders/teamprofileimage.png');
        background-size: cover;
        background-position: center;
        background-repeat: no-repeat;
        box-shadow: 0 4px 12px rgba(0, 0, 0, 0.15);
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

    .message-input-container {
        position: relative;
        display: flex;
        justify-content: center;
        padding: 15px;
    }

    .chat-wrapper:not(.fullscreen) .message-input-container {
        position: absolute;
        bottom: 0;
        left: 0;
        right: 0;
    }

    .chat-wrapper.fullscreen .message-input-container {
        width: 35%;
        min-width: 400px;
        padding: 20px;
        align-items: flex-start;
    }

    .message-input-container :global(> *) {
        max-width: 629px;
        width: 100%;
    }

    @media (max-width: 730px) {
        .message-input-container {
            padding: 10px;
        }
    }

    .team-image.disabled {
        opacity: 0;
        filter: grayscale(100%);
        transition: all 0.3s ease;
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

        .chat-wrapper.fullscreen .message-input-container {
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

        .chat-wrapper.fullscreen .message-input-container {
            position: absolute;
            bottom: 0;
            left: 0;
            right: 0;
            width: 100%;
            padding: 15px;
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
        right: 20px;
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
