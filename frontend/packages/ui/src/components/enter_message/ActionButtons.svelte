<!-- frontend/packages/ui/src/components/enter_message/ActionButtons.svelte -->
<script lang="ts">
    import { createEventDispatcher } from 'svelte';
    import { tooltip } from '../../actions/tooltip';
    import { slide } from 'svelte/transition';
    // Assuming text store is available for translations
    import { text } from '@repo/ui'; // Adjust path if needed

    export let showSendButton: boolean = false;
    export let isRecordButtonPressed: boolean = false;
    export let showRecordHint: boolean = false;
    export let micPermissionGranted: boolean = false;

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
            on:click={handleFileSelectClick}
            aria-label={$text('enter_message.attachments.attach_files.text')}
            use:tooltip
        ></button> -->
        <button
            class="clickable-icon icon_maps"
            on:click={handleLocationClick}
            aria-label={$text('enter_message.attachments.share_location.text')}
            use:tooltip
        ></button>
    </div>
    <div class="right-buttons">
        <!-- TODO uncomment once feature available -->
        <!-- <button
            class="clickable-icon icon_camera"
            on:click={handleCameraClick}
            aria-label={$text('enter_message.attachments.take_photo.text')}
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
            aria-label={$text('enter_message.attachments.record_audio.text')}
            use:tooltip
        >
            <div class="clickable-icon icon_recordaudio"></div>
        </button>
         -->
        {#if showSendButton}
            <button
                class="send-button"
                on:click={handleSendMessageClick}
                aria-label={$text('enter_message.send.text')}
            >
               {$text('enter_message.send.text')}
            </button>
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

    .clickable-icon {
        display: flex;
        align-items: center;
        height: 50px; /* Increased height for better click target */
        margin-top: 10px; /* Align with other elements */
        /* Inherit icon styles from global or add specific ones */
        background: none;
        border: none;
        padding: 0;
        cursor: pointer;
    }

    .record-button {
        position: relative;
        border: none;
        cursor: pointer;
        background: none;
        display: flex;
        align-items: center;
        justify-content: center;
        width: 25px; /* Adjust as needed */
        height: 50px; /* Match clickable-icon height */
        min-width: 25px;
        padding: 0;
        margin-top: 10px; /* Align */
    }

     .record-button .clickable-icon {
        margin: 0; /* Override margin */
        padding: 0;
        position: relative;
        z-index: 1;
        width: 25px; /* Icon size */
        height: 25px; /* Icon size */
        transition: background-color 0.3s ease-out;
    }

    .record-button::before {
        content: '';
        position: absolute;
        top: 50%;
        left: 50%;
        transform: translate(-50%, -50%);
        width: 0;
        height: 0;
        border-radius: 50%;
        background: var(--color-app-audio);
        transition: all 0.3s ease-out;
        z-index: -1;
        opacity: 0;
    }

    .record-button.recording::before {
        width: 60px; /* Pulse effect size */
        height: 60px;
        opacity: 1;
    }

    .record-button.recording .clickable-icon {
        background-color: white; /* Icon color change when recording */
    }

    .record-hint-inline {
        font-size: 14px;
        color: var(--color-font-secondary);
        white-space: nowrap;
        padding: 4px 8px;
        background: var(--color-grey-20);
        border-radius: 12px;
        margin-top: 10px; /* Align */
        display: inline-block;
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
