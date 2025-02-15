<script lang="ts">
    import MessageInput from './enter_message/MessageInput.svelte';
    import CodeFullscreen from './fullscreen_previews/CodeFullscreen.svelte';
    import ChatHistory from './ChatHistory.svelte';
    import { teamEnabled, settingsMenuVisible, isMobileView } from './Settings.svelte';
    import Login from './Login.svelte';
    import { _ } from 'svelte-i18n'; // Import translation function
    import { fade, fly } from 'svelte/transition';
    import { createEventDispatcher, tick } from 'svelte';
    import { isAuthenticated } from '../stores/authState';
    import type { Chat } from '../types/chat';
    import { tooltip } from '../actions/tooltip';
    import { chatDB } from '../services/db';
    import KeyboardShortcuts from './KeyboardShortcuts.svelte'; // Import the new component
    const dispatch = createEventDispatcher();

    // Add state for code fullscreen
    let showCodeFullscreen = false;
    let fullscreenCodeData = {
        code: '',
        filename: '',
        language: '',
        lineCount: 0
    };

    // No need for local isLoggedIn prop, use the store value directly
    $: isLoggedIn = $isAuthenticated;

    function handleLoginSuccess() {
        dispatch('loginSuccess');
    }

    // Add handler for code fullscreen
    function handleCodeFullscreen(event: CustomEvent) {
        console.log('Received code fullscreen event:', event.detail);
        fullscreenCodeData = {
            code: event.detail.code,
            filename: event.detail.filename,
            language: event.detail.language,
            lineCount: event.detail.lineCount // Make sure we're capturing the line count
        };
        console.log('Set fullscreen data:', fullscreenCodeData);
        showCodeFullscreen = true;
    }

    // Add handler for closing code fullscreen
    function handleCloseCodeFullscreen() {
        showCodeFullscreen = false;
    }

    // Subscribe to store values
    $: isTeamEnabled = $teamEnabled;
    // Add class when menu is open AND in mobile view
    $: isDimmed = $settingsMenuVisible && $isMobileView;

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

        // *** KEY CHANGE: Update currentChat when a new draft is saved ***
        currentChat = chat;
        console.log("[ActiveChat] Draft saved, updating currentChat:", currentChat);
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
        // Add the new message to the chat history
        chatHistoryRef.addMessage(event.detail);
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
        console.log("[ActiveChat] New chat creation initiated");
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
    }

    // Add a handler for the share button click.
    // This function will be triggered when the share button is clicked.
    function handleShareChat() {
        // Using console.log for logging in Svelte.
        console.log("[ActiveChat] Share chat button clicked.");
        // TODO: Insert the actual share logic here if needed.
    }

    // Update the loadChat function
    export async function loadChat(chat: Chat) {
        console.log("[ActiveChat] Loading chat:", chat.id);
        currentChat = chat;
        showWelcome = false;

        if (chatHistoryRef) {
            // Clear existing messages AND wait for completion
            await chatHistoryRef.clearMessages();

            // Now it's safe to add messages
            // Use optional chaining and nullish coalescing operator in case chat or messages is null/undefined.
            for (const msg of chat?.messages ?? []) {
                chatHistoryRef.addMessage(msg);
                await tick(); // Still a good idea for smooth scrolling
            }
        }

        // Handle the draft content
        if (messageInputFieldRef && chat.isDraft && chat.draftContent) {
            console.log("[ActiveChat] Setting draft content:", chat.draftContent);
            messageInputHasContent = true;
            // Add a small delay to ensure the editor is initialized
            setTimeout(() => {
                messageInputFieldRef.setDraftContent(chat.draftContent, false);
            }, 100);
        } else if (messageInputFieldRef) {
            // If it's not a draft or has no draft content, clear the field without focusing
            messageInputFieldRef.clearMessageField(false);
            messageInputHasContent = false;
        }
    }
</script>

<div class="active-chat-container" class:dimmed={isDimmed} class:login-mode={!$isAuthenticated} class:scaled={activeScaling}>
    {#if !$isAuthenticated}
        <div 
            class="login-wrapper" 
            in:fly={loginTransitionProps} 
            out:fade={{ duration: 200 }}
        >
            <Login on:loginSuccess={handleLoginSuccess} />
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
                                    aria-label={$_('chat.new_chat.text')}
                                    on:click={handleNewChatClick}
                                    in:fade={{ duration: 300 }}
                                    use:tooltip
                                >
                                </button>
                            {/if}
                            {#if !showWelcome}
                                <button
                                    class="clickable-icon icon_share top-button"
                                    aria-label={$_('chat.share.text')}
                                    on:click={handleShareChat}
                                    use:tooltip
                                >
                                </button>
                            {/if}
                        </div>

                        <!-- Right side buttons -->
                        <div class="right-buttons">
                            <!-- Video call button -->
                            <button 
                                class="clickable-icon icon_video_call top-button" 
                                aria-label={$_('chat.start_video_call.text')}
                                use:tooltip
                            >
                            </button>
                            <!-- Audio call button -->
                            <button 
                                class="clickable-icon icon_call top-button" 
                                aria-label={$_('chat.start_audio_call.text')}
                                use:tooltip
                            >
                            </button>
                        </div>
                    </div>

                    <!-- Update the welcome content to use transition and showWelcome -->
                    {#if showWelcome}
                        <div 
                            class="center-content"
                            transition:fade={{ duration: 300 }}
                        >
                            <div class="team-profile">
                                <div class="team-image" class:disabled={!isTeamEnabled}></div>
                                <div class="welcome-text">
                                    <h2>{$_('chat.welcome.hey.text')} Kitty!</h2>
                                    <p>{$_('chat.welcome.what_do_you_need_help_with.text')}</p>
                                </div>
                            </div>
                        </div>
                    {/if}

                    <ChatHistory 
                        bind:this={chatHistoryRef} 
                        messageInputHeight={isFullscreen ? 0 : messageInputHeight + 40}
                        on:messagesChange={handleMessagesChange}
                    />
                </div>

                <!-- Right side container for message input -->
                <div class="message-input-container">
                    <!-- Pass currentChat?.id to MessageInput -->
                    <MessageInput 
                        bind:this={messageInputFieldRef}
                        bind:hasContent={messageInputHasContent}
                        currentChatId={currentChat?.id}
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
        user-select: none;
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
