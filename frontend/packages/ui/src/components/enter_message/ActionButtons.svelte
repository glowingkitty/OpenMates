<!-- frontend/packages/ui/src/components/enter_message/ActionButtons.svelte -->
<!--
  Action buttons rendered at the bottom of the message field.

  Normal state:
    Left: [Files] [Maps]
    Right: [Camera]  "Press & hold to record" [Mic]  [Send?]

  The "Press & hold to record" label is shown inline to the left of the mic icon
  (matching the Figma messagefield/singlepress_record design) ONLY when:
    - The user single-tapped the mic button (highlightPressHold=true, ~1.5s window)
    - AND mic permission is already granted

  It is NOT shown by default — only as direct feedback after a single tap.
  When mic permission is denied the label is never shown.

  Single-tap feedback (highlightPressHold):
    When the user taps (but does not hold) the mic button, the parent sets
    highlightPressHold=true for ~1.5s after confirming mic is granted.
    This shows and briefly animates the label so the user notices "Press & hold".
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
        /** Mic permission state — controls whether "Press & hold to record" label is shown */
        micPermissionState?: 'unknown' | 'granted' | 'prompt' | 'denied';
        /**
         * When true, briefly highlight the "Press & hold to record" label (and force
         * it visible even when showSendButton is true). Set by parent on a short tap.
         */
        highlightPressHold?: boolean;
    }
    let {
        showSendButton = false,
        isRecordButtonPressed = false,
        isAuthenticated = true,
        micPermissionState = 'unknown',
        highlightPressHold = false
    }: Props = $props();

    const dispatch = createEventDispatcher();

    function handleFileSelectClick() { dispatch('fileSelect'); }
    function handleLocationClick() { dispatch('locationClick'); }
    function handleCameraClick() { dispatch('cameraClick'); }
    function handleSendMessageClick() { dispatch('sendMessage'); }
    function handleSignUpClick() { dispatch('signUpClick'); }

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

    /**
     * Show the "Press & hold to record" inline label only when:
     *  - The user single-tapped the mic button (highlightPressHold=true, set by parent)
     *  - AND mic is already granted (not denied/prompt/unknown)
     *
     * We intentionally do NOT show it by default (even when no send button is visible),
     * because it is distracting before the user has interacted with the mic button.
     * The parent sets highlightPressHold=true for ~1.5s after a short tap so the hint
     * appears only as direct feedback to the tap.
     */
    let showPressHoldLabel = $derived(
        highlightPressHold && micPermissionState === 'granted'
    );
</script>

<div class="action-buttons">
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
    </div>
    <div class="right-buttons">
        <button
            class="clickable-icon icon_camera"
            onclick={handleCameraClick}
            aria-label={$text('enter_message.attachments.take_photo')}
            use:tooltip
        ></button>

        <!-- "Press & hold to record" inline label — hidden when send button is visible or mic blocked.
             When highlightPressHold is true the label is force-shown and briefly flashes. -->
        {#if showPressHoldLabel}
            <span class="press-hold-label {highlightPressHold ? 'highlighted' : ''}" aria-hidden="true">
                {$text('enter_message.record_audio.press_and_hold_reminder')}
            </span>
        {/if}

        <!-- Audio recording: press-and-hold to record, release to transcribe via Mistral Voxtral -->
        <button
            class="clickable-icon icon_recordaudio {isRecordButtonPressed ? 'recording' : ''}"
            onmousedown={handleRecordMouseDown}
            onmouseup={handleRecordMouseUp}
            onmouseleave={handleRecordMouseLeave}
            ontouchstart={handleRecordTouchStart}
            ontouchend={handleRecordTouchEnd}
            aria-label={$text('enter_message.attachments.record_audio')}
            use:tooltip
        ></button>

        {#if showSendButton}
            <!-- fly in from right (x: 40) so camera/record buttons shift smoothly -->
            {#if isAuthenticated}
                <button
                    class="send-button"
                    onclick={handleSendMessageClick}
                    aria-label={$text('enter_message.send')}
                    in:fly={{ x: 40, duration: 200 }}
                    out:fly={{ x: 40, duration: 150 }}
                >
                   {$text('enter_message.send')}
                </button>
            {:else}
                <!-- Show "Sign up" button for non-authenticated users -->
                <button
                    class="send-button"
                    onclick={handleSignUpClick}
                    aria-label={$text('signup.sign_up')}
                    in:fly={{ x: 40, duration: 200 }}
                    out:fly={{ x: 40, duration: 150 }}
                >
                   {$text('signup.sign_up')}
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
        transition: gap 200ms ease;
    }

    /* "Press & hold to record" inline label — muted, sits left of the mic icon */
    .press-hold-label {
        color: var(--color-font-tertiary, rgba(0, 0, 0, 0.4));
        font-size: 13px;
        font-weight: 400;
        white-space: nowrap;
        pointer-events: none;
        user-select: none;
        /* Subtle fade-in when it appears */
        animation: label-fade-in 0.2s ease;
    }

    /* Brief highlight when the user taps (but does not hold) the mic button.
       Pulses to a more visible colour then fades back to the muted default. */
    .press-hold-label.highlighted {
        animation: label-highlight 1.4s ease forwards;
        font-weight: 600;
    }

    @keyframes label-fade-in {
        from { opacity: 0; }
        to   { opacity: 1; }
    }

    @keyframes label-highlight {
        0%   { color: var(--color-font-tertiary, rgba(0, 0, 0, 0.4)); font-weight: 400; }
        15%  { color: var(--color-font-primary,  rgba(0, 0, 0, 0.85)); font-weight: 600; }
        60%  { color: var(--color-font-primary,  rgba(0, 0, 0, 0.85)); font-weight: 600; }
        100% { color: var(--color-font-tertiary, rgba(0, 0, 0, 0.4)); font-weight: 400; }
    }

    /* Prevent page scroll during the press-and-hold recording gesture.
       We rely on CSS instead of event.preventDefault() so that Firefox iOS
       retains the user-gesture token needed for getUserMedia(). */
    .icon_recordaudio {
        touch-action: none;
    }

    .send-button {
        color: white;
        border: none;
        padding: 8px 16px;
        border-radius: 20px;
        cursor: pointer;
        font-weight: 500;
        height: 40px;
        margin-left: 0.5rem;
    }
</style>
