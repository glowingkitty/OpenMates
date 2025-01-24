<script>
    import EnterMessageField from './enter_message/EnterMessageField.svelte';
    import { teamEnabled, settingsMenuVisible, isMobileView } from './Settings.svelte';
    import { _ } from 'svelte-i18n'; // Import translation function

    // Subscribe to store values
    $: isTeamEnabled = $teamEnabled;
    // Add class when menu is open AND in mobile view
    $: isDimmed = $settingsMenuVisible && $isMobileView;
    let isMessageFieldFullscreen = false;
</script>

<div class="active-chat-container" class:dimmed={isDimmed} class:fullscreen-mode={isMessageFieldFullscreen}>
    <button 
        class="clickable-icon icon_create top-button left" 
        aria-label={$_('chat.new_chat.text')}
    ></button>
    <button 
        class="clickable-icon icon_call top-button right" 
        aria-label={$_('chat.start_audio_call.text')}
    ></button>
    <!-- Center content wrapper -->
    <div class="center-content" class:hidden={isMessageFieldFullscreen}>
        <div class="team-profile">
            <div class="team-image" class:disabled={!isTeamEnabled}></div>
            <div class="welcome-text">
                <h2>{$_('chat.welcome.hey.text')} Kitty!</h2>
                <p>{$_('chat.welcome.what_do_you_need_help_with.text')}</p>
            </div>
        </div>
    </div>

    <!-- Message input field positioned at bottom center -->
    <div class="message-input-wrapper" class:fullscreen={isMessageFieldFullscreen}>
        <EnterMessageField 
            isFullscreen={isMessageFieldFullscreen}
            onFullscreenChange={(fullscreen) => isMessageFieldFullscreen = fullscreen}
        />
    </div>
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
        /* Add right margin for mobile when menu is open */
        @media (max-width: 1099px) {
            margin-right: 0;
        }
        transition: opacity 0.3s ease;
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

    .message-input-wrapper.fullscreen {
        top: 0;
        bottom: 0;
        left: 0;
        right: 0;
        padding: 15px;
        background-color: var(--color-grey-20);
    }

    .message-input-wrapper.fullscreen :global(> *) {
        max-width: none;
        height: 100%;
    }

    .center-content.hidden {
        display: none;
    }

    .active-chat-container.fullscreen-mode .top-button {
        display: none;
    }
</style>
