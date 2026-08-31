<!-- frontend/packages/ui/src/components/enter_message/ActionButtons.svelte -->
<!--
  Action buttons rendered at the bottom of the message field.

  Normal state:
    Left: [Files] [Maps]
    Right: [Camera] [Mic] [Send?]

  Audio recording starts on press/click. The recording overlay owns completion
  and cancellation through Finish/Cancel buttons plus Enter/Escape shortcuts.
-->
<script lang="ts">
    import { createEventDispatcher } from 'svelte';
    import { tooltip } from '../../actions/tooltip';
    import { fly } from 'svelte/transition';
    import { text } from '@repo/ui';

    interface Props {
        showSendButton?: boolean;
        isRecordButtonPressed?: boolean;
        isAuthenticated?: boolean;
        /** Allow signed-out text sends when anonymous free usage is active. */
        allowAnonymousTextSend?: boolean;
        /**
         * When true, the user is signed in but has zero credits.
         * The send button is replaced with a "Buy credits" button.
         */
        hasNoCredits?: boolean;
        /** Mic permission state — used by the parent for direct recording feedback. */
        micPermissionState?: 'unknown' | 'granted' | 'prompt' | 'denied';
        /** Deprecated hold-reminder flag kept for call-site compatibility. */
        highlightPressHold?: boolean;
        /** Whether the sketch overlay is currently open (highlights the sketch button). */
        isSketchOpen?: boolean;
        /** Label for the unauthenticated CTA shown instead of the send button. */
        unauthenticatedCtaLabel?: string;
        /** Show the auth CTA even when the editor only has a blocked pending upload. */
        forceUnauthenticatedCta?: boolean;
        /** Reserve the bottom-right stop/pause slot so mic/camera do not sit under it. */
        reserveTrailingControlSpace?: boolean;
        autoSpeakResponse?: boolean;
    }
    let {
        showSendButton = false,
        isRecordButtonPressed = false,
        isAuthenticated = true,
        allowAnonymousTextSend = false,
        hasNoCredits = false,
        isSketchOpen = false,
        unauthenticatedCtaLabel = $text('signup.sign_up'),
        forceUnauthenticatedCta = false,
        reserveTrailingControlSpace = false,
        autoSpeakResponse = false
    }: Props = $props();

    const dispatch = createEventDispatcher();

    function handleFileSelectClick() { dispatch('fileSelect'); }
    function handleLocationClick() { dispatch('locationClick'); }
    function handleCameraClick() { dispatch('cameraClick'); }
    function handleSketchClick() { dispatch('sketchClick'); }
    function handleSendMessageClick() { dispatch('sendMessage'); }
    function handleSignUpClick() { dispatch('signUpClick'); }
    function handleBuyCreditsClick() { dispatch('buyCreditsClick'); }
    function handleAssistantSpeechToggle() { dispatch('assistantSpeechToggle', { enabled: !autoSpeakResponse }); }

    // --- Record Button Handlers ---
    function handleRecordMouseDown(event: MouseEvent) { dispatch('recordMouseDown', { originalEvent: event }); }
    function handleRecordMouseUp(event: MouseEvent) { dispatch('recordMouseUp', { originalEvent: event }); }
    function handleRecordMouseLeave(event: MouseEvent) { dispatch('recordMouseLeave', { originalEvent: event }); }
    function handleRecordTouchStart(event: TouchEvent) {
        // Do NOT call event.preventDefault() here.
        // On Firefox iOS, preventDefault() on touchstart consumes the user-gesture token
        // that getUserMedia() requires to show the microphone permission prompt.
        // Scroll prevention during a hold is handled by `touch-action: none` on the button.
        dispatch('recordTouchStart', { originalEvent: event });
    }
    function handleRecordTouchEnd(event: TouchEvent) { dispatch('recordTouchEnd', { originalEvent: event }); }

    let canSendMessage = $derived(isAuthenticated || allowAnonymousTextSend);
</script>

<div class="action-buttons" data-testid="action-buttons">
    <div class="left-buttons">
        <button
            class="clickable-icon icon_files"
            onclick={handleFileSelectClick}
            aria-label={$text('enter_message.attachments.attach_files')}
            use:tooltip
        ></button>
        <button
            class="clickable-icon icon_maps"
            onclick={handleLocationClick}
            aria-label={$text('enter_message.attachments.share_location')}
            use:tooltip
        ></button>
        <button
            class="clickable-icon icon_sketch {isSketchOpen ? 'active' : ''}"
            onclick={handleSketchClick}
            aria-label={$text('enter_message.attachments.sketch')}
            use:tooltip
        ></button>
    </div>
    <div class="right-buttons {reserveTrailingControlSpace ? 'reserve-trailing-control-space' : ''}">
        <button
            class="clickable-icon icon_camera"
            onclick={handleCameraClick}
            aria-label={$text('enter_message.attachments.take_photo')}
            use:tooltip
        ></button>

        <!-- Audio recording: press to start, then Finish/Cancel in the recording overlay. -->
        <button
            class="clickable-icon icon_recordaudio {isRecordButtonPressed ? 'recording' : ''}"
            data-testid="record-audio-button"
            onmousedown={handleRecordMouseDown}
            onmouseup={handleRecordMouseUp}
            onmouseleave={handleRecordMouseLeave}
            ontouchstart={handleRecordTouchStart}
            ontouchend={handleRecordTouchEnd}
            aria-label={$text('enter_message.attachments.record_audio')}
            use:tooltip
        ></button>

        <button
            type="button"
            class="assistant-speech-toggle"
            class:active={autoSpeakResponse}
            data-testid="assistant-speech-toggle"
            aria-label="Voice replies"
            aria-pressed={autoSpeakResponse}
            title="Voice replies"
            onclick={handleAssistantSpeechToggle}
        >
            <span class="assistant-speech-dot" aria-hidden="true"></span>
            <span>Voice</span>
        </button>

        {#if showSendButton || forceUnauthenticatedCta || (isAuthenticated && hasNoCredits)}
            <!-- fly in from right (x: 40) so camera/record buttons shift smoothly -->
            {#if isAuthenticated && hasNoCredits}
                <!-- Signed-in user with zero credits: show "Buy credits" button -->
                <button
                    class="send-button buy-credits-button"
                    data-action="buy-credits"
                    onclick={handleBuyCreditsClick}
                    aria-label={$text('enter_message.buy_credits')}
                    in:fly={{ x: 40, duration: 200 }}
                    out:fly={{ x: 40, duration: 150 }}
                >
                   {$text('enter_message.buy_credits')}
                </button>
            {:else if canSendMessage && !forceUnauthenticatedCta}
                <button
                    class="send-button"
                    data-action="send-message"
                    onclick={handleSendMessageClick}
                    aria-label={$text('enter_message.send')}
                    in:fly={{ x: 40, duration: 200 }}
                    out:fly={{ x: 40, duration: 150 }}
                >
                   {$text('enter_message.send')}
                </button>
            {:else}
                <!-- Show auth CTA button for non-authenticated users -->
                <button
                    class="send-button"
                    data-action="sign-up-to-send"
                    onclick={handleSignUpClick}
                    aria-label={unauthenticatedCtaLabel}
                    in:fly={{ x: 40, duration: 200 }}
                    out:fly={{ x: 40, duration: 150 }}
                >
                   {unauthenticatedCtaLabel}
                </button>
            {/if}
        {/if}
    </div>
</div>

<style>
    .action-buttons {
        position: absolute;
        bottom: 1rem;
        left: 1rem;
        right: 1rem;
        display: flex;
        justify-content: space-between;
        align-items: center;
        height: 40px;
    }

    .left-buttons,
    .right-buttons {
        display: flex;
        align-items: center;
        gap: 1rem;
        height: 100%;
    }

    .right-buttons {
        gap: 1rem;
        flex-wrap: nowrap;
        /* Smooth shift when send button appears/disappears */
        padding-right: 0;
        transition: gap 200ms ease, padding-right 220ms ease;
    }

    .right-buttons.reserve-trailing-control-space {
        padding-right: 48px;
    }

    /* Highlight sketch button when the sketch overlay is open */
    .icon_sketch.active {
        color: var(--color-accent, #007AFF);
    }

    /* Prevent page scroll during the recording start gesture.
       We rely on CSS instead of event.preventDefault() so that Firefox iOS
       retains the user-gesture token needed for getUserMedia(). */
    .icon_recordaudio {
        touch-action: none;
    }

    .assistant-speech-toggle {
        display: inline-flex;
        align-items: center;
        gap: 6px;
        height: 32px;
        padding: 0 10px;
        border: 1px solid var(--color-grey-20);
        border-radius: 999px;
        color: var(--color-grey-70);
        background: var(--color-grey-10);
        font: inherit;
        font-size: var(--font-size-xxs);
        cursor: pointer;
    }

    .assistant-speech-toggle.active {
        border-color: var(--color-accent);
        color: var(--color-accent);
        background: color-mix(in srgb, var(--color-accent) 10%, transparent);
    }

    .assistant-speech-dot {
        width: 7px;
        height: 7px;
        border-radius: 50%;
        background: currentColor;
        box-shadow: 5px 0 0 -2px currentColor, 10px 0 0 -3px currentColor;
        margin-right: 8px;
    }

    .send-button {
        color: white;
        border: none;
        padding: var(--spacing-4) var(--spacing-8);
        border-radius: var(--radius-8);
        cursor: pointer;
        font-weight: 500;
        height: 40px;
        margin-left: 0.5rem;
    }


</style>
