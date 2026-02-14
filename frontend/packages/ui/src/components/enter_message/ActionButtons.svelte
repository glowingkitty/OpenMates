<!-- frontend/packages/ui/src/components/enter_message/ActionButtons.svelte -->
<script lang="ts">
    import { createEventDispatcher } from 'svelte';
    import { tooltip } from '../../actions/tooltip';
    import { slide } from 'svelte/transition';
    // Assuming text store is available for translations
    import { text } from '@repo/ui'; // Adjust path if needed

    // Props using Svelte 5 $props()
    interface Props {
        showSendButton?: boolean;
        isRecordButtonPressed?: boolean;
        showRecordHint?: boolean;
        micPermissionGranted?: boolean;
        isAuthenticated?: boolean; // Add authentication state prop
    }
    let { 
        showSendButton = false,
        isRecordButtonPressed = false,
        showRecordHint = false,
        micPermissionGranted = false,
        isAuthenticated = true // Default to true for backwards compatibility
    }: Props = $props();

    const dispatch = createEventDispatcher();

    function handleFileSelectClick() {
        dispatch('fileSelect');
    }

    function handleLocationClick() {
        dispatch('locationClick');
    }

    function handleCameraClick(event: MouseEvent | TouchEvent) {
        event.preventDefault();
        dispatch('cameraClick');
    }

    function handleSendMessageClick() {
        dispatch('sendMessage');
    }

    // Handle "Sign up" button click for non-authenticated users
    function handleSignUpClick() {
        dispatch('signUpClick');
    }

    // --- Record Button Handlers ---
    // Forward the ORIGINAL event in the detail payload
    function handleRecordMouseDown(event: MouseEvent) {
        dispatch('recordMouseDown', { originalEvent: event }); // Pass original event
    }

    function handleRecordMouseUp(event: MouseEvent) { // Add event param if needed later
        dispatch('recordMouseUp', { originalEvent: event }); // Pass original event
    }

    function handleRecordMouseLeave(event: MouseEvent) { // Add event param
        dispatch('recordMouseLeave', { originalEvent: event }); // Pass original event
    }

    function handleRecordTouchStart(event: TouchEvent) {
        dispatch('recordTouchStart', { originalEvent: event }); // Pass original event
    }

    function handleRecordTouchEnd(event: TouchEvent) { // Add event param
        dispatch('recordTouchEnd', { originalEvent: event }); // Pass original event
    }

</script>

<div class="action-buttons">
    <div class="left-buttons">
        <!-- TODO uncomment once feature available -->
        <!-- <button
            class="clickable-icon icon_files"
            onclick={handleFileSelectClick}
            aria-label={$text('enter_message.attachments.attach_files')}
            use:tooltip
        ></button> -->
        <!-- <button
            class="clickable-icon icon_maps"
            onclick={handleLocationClick}
            aria-label={$text('enter_message.attachments.share_location')}
            use:tooltip
        ></button> -->
    </div>
    <div class="right-buttons">
        <!-- TODO uncomment once feature available -->
        <!-- <button
            class="clickable-icon icon_camera"
            onclick={handleCameraClick}
            aria-label={$text('enter_message.attachments.take_photo')}
            use:tooltip
        ></button>

        {#if showRecordHint}
            <span
                class="record-hint-inline"
                transition:slide={{ duration: 200 }}
            >
                {$text('enter_message.attachments.record_audio.hint')}
            </span>
        {/if}

        <button
            class="record-button {isRecordButtonPressed ? 'recording' : ''}"
            style="z-index: 901;"
            on:mousedown={handleRecordMouseDown}
            on:mouseup={handleRecordMouseUp}
            on:mouseleave={handleRecordMouseLeave}
            on:touchstart|preventDefault={handleRecordTouchStart}
            on:touchend={handleRecordTouchEnd}
            aria-label={$text('enter_message.attachments.record_audio')}
            use:tooltip
        >
            <div class="clickable-icon icon_recordaudio"></div>
        </button>
         -->
        {#if showSendButton}
            {#if isAuthenticated}
                <button
                    class="send-button"
                    onclick={handleSendMessageClick}
                    aria-label={$text('enter_message.send')}
                >
                   {$text('enter_message.send')}
                </button>
            {:else}
                <!-- Show "Sign up" button for non-authenticated users -->
                <button
                    class="send-button"
                    onclick={handleSignUpClick}
                    aria-label={$text('signup.sign_up')}
                >
                   {$text('signup.sign_up')}
                </button>
            {/if}
        {/if}
    </div>
</div>

<style>
    /* Styles remain the same */
    .action-buttons {
        position: absolute;
        bottom: 1rem;
        left: 1rem;
        right: 1rem;
        display: flex;
        justify-content: space-between;
        align-items: center;
        height: 40px; /* Consistent height */
    }

    .left-buttons,
    .right-buttons {
        display: flex;
        align-items: center;
        gap: 1rem; /* Adjust gap as needed */
        height: 100%;
    }

     .right-buttons {
        gap: 0.5rem; /* Smaller gap for right side */
        flex-wrap: nowrap;
    }

    .send-button {
        color: white;
        border: none;
        padding: 8px 16px;
        border-radius: 20px;
        cursor: pointer;
        font-weight: 500;
        height: 40px; /* Match container height */
        margin-left: 0.5rem; /* Space from record button */
    }
</style>
