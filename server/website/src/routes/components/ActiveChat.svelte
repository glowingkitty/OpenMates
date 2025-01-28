<script lang="ts">
    import EnterMessageField from './enter_message/EnterMessageField.svelte';
    import FullscreenCodePreview from './enter_message/in_message_previews/FullscreenCodePreview.svelte';
    import { teamEnabled, settingsMenuVisible, isMobileView } from './Settings.svelte';
    import Login from './Login.svelte';
    import { _ } from 'svelte-i18n'; // Import translation function
    import { fade, fly } from 'svelte/transition';
    import { createEventDispatcher } from 'svelte';
    import { isAuthenticated } from '../../lib/stores/authState';

    const dispatch = createEventDispatcher();

    // Add state for code fullscreen
    let showCodeFullscreen = false;
    let fullscreenCodeData = {
        code: '',
        filename: '',
        language: ''
    };

    // No need for local isLoggedIn prop, use the store value directly
    $: isLoggedIn = $isAuthenticated;

    function handleLoginSuccess() {
        dispatch('loginSuccess');
    }

    // Add handler for code fullscreen
    function handleCodeFullscreen(event: CustomEvent) {
        fullscreenCodeData = event.detail;
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
</script>

<div class="active-chat-container" class:dimmed={isDimmed} class:login-mode={!$isAuthenticated}>
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
        >
            <button 
                class="clickable-icon icon_create top-button left" 
                aria-label={$_('chat.new_chat.text')}
            ></button>
            <button 
                class="clickable-icon icon_call top-button right" 
                aria-label={$_('chat.start_audio_call.text')}
            ></button>
            <!-- Center content wrapper -->
            <div class="center-content">
                <div class="team-profile">
                    <div class="team-image" class:disabled={!isTeamEnabled}></div>
                    <div class="welcome-text">
                        <h2>{$_('chat.welcome.hey.text')} Kitty!</h2>
                        <p>{$_('chat.welcome.what_do_you_need_help_with.text')}</p>
                    </div>
                </div>
            </div>

            {#if showCodeFullscreen}
                <FullscreenCodePreview 
                    code={fullscreenCodeData.code}
                    filename={fullscreenCodeData.filename}
                    language={fullscreenCodeData.language}
                    onClose={handleCloseCodeFullscreen}
                />
            {/if}

            <!-- Message input field positioned at bottom center -->
            <div class="message-input-wrapper">
                <EnterMessageField on:codefullscreen={handleCodeFullscreen} />
            </div>
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
        padding-top: 90px; /* Add fixed padding for header */
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

    .center-content {
        position: absolute;
        top: 40%;
        left: 50%;
        transform: translate(-50%, -50%);
        text-align: center;
        user-select: none;
        -webkit-user-select: none;
        -moz-user-select: none;
        -ms-user-select: none;
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
        background-image: url('/images/placeholders/teamprofileimage.png');
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

    .message-input-wrapper {
        position: absolute;
        bottom: 15px;
        left: 15px;
        right: 15px;
        display: flex;
        justify-content: center;
    }

    .message-input-wrapper :global(> *) {
        max-width: 629px;
        width: 100%;
    }

    .team-image.disabled {
        opacity: 0;
        filter: grayscale(100%);
        transition: all 0.3s ease;
    }

    .active-chat-container.dimmed {
        opacity: 0.3;
    }

    /* Add new styles for button positioning */
    .top-button {
        position: absolute;
        top: 20px;
    }

    .top-button.left {
        left: 20px;
    }

    .top-button.right {
        right: 20px;
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
</style>
