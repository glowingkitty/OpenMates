<!-- frontend/packages/ui/src/components/enter_message/ActionButtons.svelte -->
<!--
  Action buttons rendered at the bottom of the message field.

  Normal state:
    Left: [Files] [Maps]
    Right: [Camera]  "Press & hold to record" [Mic]  [Send?]

  The "Press & hold to record" label is shown inline to the left of the mic icon
  (matching the Figma messagefield/singlepress_record design) when:
    - No content is in the editor (showSendButton=false)
    - AND mic permission is granted or unknown (not denied)

  When the send button is visible the label is hidden to keep the row compact.
  When mic permission is denied the label is also hidden.
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
    }
    let {
        showSendButton = false,
        isRecordButtonPressed = false,
        isAuthenticated = true,
        micPermissionState = 'unknown'
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
    function handleRecordTouchStart(event: TouchEvent) { event.preventDefault(); dispatch('recordTouchStart', { originalEvent: event }); }
    function handleRecordTouchEnd(event: TouchEvent) { dispatch('recordTouchEnd', { originalEvent: event }); }

    /**
     * Show the "Press & hold to record" inline label when:
     *  - No content yet (send button hidden)
     *  - Mic not permanently denied
     */
    let showPressHoldLabel = $derived(!showSendButton && micPermissionState !== 'denied');
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

        <!-- "Press & hold to record" inline label — hidden when send button is visible or mic blocked -->
        {#if showPressHoldLabel}
            <span class="press-hold-label" aria-hidden="true">
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

    @keyframes label-fade-in {
        from { opacity: 0; }
        to { opacity: 1; }
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
