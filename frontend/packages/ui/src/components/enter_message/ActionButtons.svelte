<!-- frontend/packages/ui/src/components/enter_message/ActionButtons.svelte -->
<!--
  Action buttons rendered at the bottom of the message field.

  Normal state:
    Left: [Attachments] [Model]
    Right: [Camera] [Mic] [Send?]

  Audio recording starts on press/click. The recording overlay owns completion
  and cancellation through Finish/Cancel buttons plus Enter/Escape shortcuts.
-->
<script lang="ts">
    import { createEventDispatcher, onMount } from 'svelte';
    import { tooltip } from '../../actions/tooltip';
    import { fly } from 'svelte/transition';
    import { text } from '@repo/ui';
    import ComposerModelSelector from './ComposerModelSelector.svelte';

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
        /** Label for the unauthenticated CTA shown instead of the send button. */
        unauthenticatedCtaLabel?: string;
        /** Show the auth CTA even when the editor only has a blocked pending upload. */
        forceUnauthenticatedCta?: boolean;
        /** Reserve the bottom-right stop/pause slot so mic/camera do not sit under it. */
        reserveTrailingControlSpace?: boolean;
        modelSelection?: string;
        showModelSelector?: boolean;
        modelSelectionReady?: boolean;
        modelSelectionPersistenceRevision?: number;
    }
    let {
        showSendButton = false,
        isRecordButtonPressed = false,
        isAuthenticated = true,
        allowAnonymousTextSend = false,
        hasNoCredits = false,
        unauthenticatedCtaLabel = $text('signup.sign_up'),
        forceUnauthenticatedCta = false,
        reserveTrailingControlSpace = false,
        modelSelection = 'auto',
        showModelSelector = true,
        modelSelectionReady = true,
        modelSelectionPersistenceRevision = 0
    }: Props = $props();

    const dispatch = createEventDispatcher();

    function handleFileSelectClick() { dispatch('fileSelect'); }
    function handleLocationClick() { dispatch('locationClick'); }
    function handleCameraClick() { dispatch('cameraClick'); }
    function handleSketchClick() { dispatch('sketchClick'); }
    function handleSendMessageClick() { dispatch('sendMessage'); }
    function handleSignUpClick() { dispatch('signUpClick'); }
    function handleBuyCreditsClick() { dispatch('buyCreditsClick'); }
    function handleModelSelect(selection: string) { dispatch('modelSelect', { selection }); }
    function handleModelDetails(modelId: string) { dispatch('modelDetails', { modelId }); }
    let showAttachmentMenu = $state(false);
    let attachmentMenuElement: HTMLDivElement;

    onMount(() => {
        const handlePointerDown = (event: PointerEvent) => {
            if (!attachmentMenuElement.contains(event.target as Node)) closeAttachmentMenu();
        };
        document.addEventListener('pointerdown', handlePointerDown);
        return () => document.removeEventListener('pointerdown', handlePointerDown);
    });

    function closeAttachmentMenu(): void {
        showAttachmentMenu = false;
    }

    function handleAttachmentKeydown(event: KeyboardEvent): void {
        if (event.key === 'Escape') {
            event.preventDefault();
            closeAttachmentMenu();
        } else if (event.key === 'ArrowDown' && !showAttachmentMenu) {
            event.preventDefault();
            showAttachmentMenu = true;
        }
    }

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
        <div class="attachment-menu" bind:this={attachmentMenuElement} data-preserve-composer-focus="true">
            <button
                type="button"
                class="clickable-icon attachment-plus-icon"
                data-testid="composer-attachment-menu-button"
                data-icon="plus"
                onclick={() => showAttachmentMenu = !showAttachmentMenu}
                aria-label={$text('enter_message.attachments.attach_files')}
                aria-haspopup="menu"
                aria-expanded={showAttachmentMenu}
                onkeydown={handleAttachmentKeydown}
                use:tooltip
            ></button>
            {#if showAttachmentMenu}
                <div class="attachment-menu-popover" data-testid="composer-attachment-menu" role="menu" tabindex="-1" onkeydown={handleAttachmentKeydown}>
                    <button type="button" role="menuitem" data-testid="composer-attachment-drawing" onclick={() => { handleSketchClick(); closeAttachmentMenu(); }}><span class="clickable-icon icon_sketch"></span>{$text('enter_message.attachments.sketch')}</button>
                    <button type="button" role="menuitem" data-testid="composer-attachment-location" onclick={() => { handleLocationClick(); closeAttachmentMenu(); }}><span class="clickable-icon icon_maps"></span>{$text('enter_message.attachments.share_location')}</button>
                    <button type="button" role="menuitem" data-testid="composer-attachment-files" onclick={() => { handleFileSelectClick(); closeAttachmentMenu(); }}><span class="clickable-icon icon_files"></span>{$text('enter_message.attachments.attach_files')}</button>
                </div>
            {/if}
        </div>
        {#if showModelSelector}
            <ComposerModelSelector selection={modelSelection} ready={modelSelectionReady} persistenceRevision={modelSelectionPersistenceRevision} onSelect={handleModelSelect} onOpenDetails={handleModelDetails} />
        {/if}
    </div>
    <div class="right-buttons {reserveTrailingControlSpace ? 'reserve-trailing-control-space' : ''}">
        <button
            type="button"
            class="clickable-icon icon_camera"
            data-testid="composer-camera-button"
            onclick={handleCameraClick}
            aria-label={$text('enter_message.attachments.take_photo')}
            use:tooltip
        ></button>

        <!-- Audio recording: press to start, then Finish/Cancel in the recording overlay. -->
        <button
            type="button"
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

        {#if showSendButton || forceUnauthenticatedCta || (isAuthenticated && hasNoCredits)}
            <!-- fly in from right (x: 40) so camera/record buttons shift smoothly -->
            {#if isAuthenticated && hasNoCredits}
                <!-- Signed-in user with zero credits: show "Buy credits" button -->
                <button
                    type="button"
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
                    type="button"
                    class="send-button"
                    data-testid="composer-send-button"
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
                    type="button"
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

    .attachment-menu { position: relative; }
    .attachment-plus-icon {
        -webkit-mask-image: var(--icon-url-plus);
        mask-image: var(--icon-url-plus);
    }
    .attachment-menu-popover { position: absolute; z-index: var(--z-index-dropdown); bottom: calc(100% + var(--spacing-4)); left: 0; min-width: 10rem; padding: var(--spacing-4); background: var(--color-grey-0); border-radius: var(--radius-8); box-shadow: var(--shadow-lg); }
    .attachment-menu-popover button { display: flex; align-items: center; justify-content: flex-start; gap: var(--spacing-4); width: 100%; padding: var(--spacing-4); border: 0; border-radius: var(--radius-3); color: var(--color-font-primary); text-align: start; background: transparent; cursor: pointer; }
    .attachment-menu-popover button:hover { background: var(--color-grey-10); }

    /* Prevent page scroll during the recording start gesture.
       We rely on CSS instead of event.preventDefault() so that Firefox iOS
       retains the user-gesture token needed for getUserMedia(). */
    .icon_recordaudio {
        touch-action: none;
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
