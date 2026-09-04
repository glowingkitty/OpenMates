<!-- frontend/packages/ui/src/components/enter_message/ActionButtons.svelte -->
<!--
  Composer controls keep attachments and model selection on the left.
  Speech, recording, and the conditional send action stay on the right.
  The attachment menu owns drawing, location, camera, and file entry points.
-->
<script lang="ts">
    import { createEventDispatcher, onDestroy, onMount } from 'svelte';
    import { fly } from 'svelte/transition';
    import { tooltip } from '../../actions/tooltip';
    import { text } from '@repo/ui';
    import ComposerModelSelector from './ComposerModelSelector.svelte';

    const SPEECH_STATUS_DURATION_MS = 1800;

    interface Props {
        showSendButton?: boolean;
        isRecordButtonPressed?: boolean;
        isAuthenticated?: boolean;
        allowAnonymousTextSend?: boolean;
        hasNoCredits?: boolean;
        micPermissionState?: 'unknown' | 'granted' | 'prompt' | 'denied';
        highlightPressHold?: boolean;
        isSketchOpen?: boolean;
        unauthenticatedCtaLabel?: string;
        forceUnauthenticatedCta?: boolean;
        reserveTrailingControlSpace?: boolean;
        modelSelection?: string;
        showModelSelector?: boolean;
        modelSelectionReady?: boolean;
        modelSelectionPersistenceRevision?: number;
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
        modelSelection = 'auto',
        showModelSelector = true,
        modelSelectionReady = true,
        modelSelectionPersistenceRevision = 0,
        autoSpeakResponse = false
    }: Props = $props();

    const dispatch = createEventDispatcher();
    let showAttachmentMenu = $state(false);
    let attachmentMenuElement: HTMLDivElement;
    let speechStatus = $state<'on' | 'off' | null>(null);
    let speechStatusTimer: ReturnType<typeof setTimeout> | null = null;
    let previousAutoSpeakResponse = $state(false);
    let speechStatusReady = $state(false);
    let speechEnabled = $state(false);
    let canSendMessage = $derived(isAuthenticated || allowAnonymousTextSend);

    onMount(() => {
        previousAutoSpeakResponse = autoSpeakResponse;
        speechEnabled = autoSpeakResponse;
        speechStatusReady = true;
        const handlePointerDown = (event: PointerEvent) => {
            if (!attachmentMenuElement.contains(event.target as Node)) closeAttachmentMenu();
        };
        document.addEventListener('pointerdown', handlePointerDown);
        return () => document.removeEventListener('pointerdown', handlePointerDown);
    });

    onDestroy(() => {
        if (speechStatusTimer) clearTimeout(speechStatusTimer);
    });

    function closeAttachmentMenu(): void {
        showAttachmentMenu = false;
    }

    function handleAttachmentKeydown(event: KeyboardEvent): void {
        if (event.key === 'Escape') {
            event.preventDefault();
            closeAttachmentMenu();
        } else if (event.key === 'ArrowDown') {
            event.preventDefault();
            showAttachmentMenu = !showAttachmentMenu;
        }
    }

    function selectAttachment(action: () => void): void {
        action();
        closeAttachmentMenu();
    }

    function handleFileSelectClick() { dispatch('fileSelect'); }
    function handleLocationClick() { dispatch('locationClick'); }
    function handleCameraClick() { dispatch('cameraClick'); }
    function handleSketchClick() { dispatch('sketchClick'); }
    function handleSendMessageClick() { dispatch('sendMessage'); }
    function handleSignUpClick() { dispatch('signUpClick'); }
    function handleBuyCreditsClick() { dispatch('buyCreditsClick'); }
    function handleModelSelect(selection: string) { dispatch('modelSelect', { selection }); }
    function handleModelDetails(modelId: string) { dispatch('modelDetails', { modelId }); }

    function showSpeechStatus(enabled: boolean): void {
        speechStatus = enabled ? 'on' : 'off';
        if (speechStatusTimer) clearTimeout(speechStatusTimer);
        speechStatusTimer = setTimeout(() => {
            speechStatus = null;
            speechStatusTimer = null;
        }, SPEECH_STATUS_DURATION_MS);
    }

    $effect(() => {
        if (!speechStatusReady || autoSpeakResponse === previousAutoSpeakResponse) return;
        previousAutoSpeakResponse = autoSpeakResponse;
        speechEnabled = autoSpeakResponse;
        showSpeechStatus(autoSpeakResponse);
    });

    function handleAssistantSpeechToggle(): void {
        const enabled = !speechEnabled;
        speechEnabled = enabled;
        showSpeechStatus(enabled);
        dispatch('assistantSpeechToggle', { enabled });
    }

    function handleRecordMouseDown(event: MouseEvent) { dispatch('recordMouseDown', { originalEvent: event }); }
    function handleRecordMouseUp(event: MouseEvent) { dispatch('recordMouseUp', { originalEvent: event }); }
    function handleRecordMouseLeave(event: MouseEvent) { dispatch('recordMouseLeave', { originalEvent: event }); }
    function handleRecordTouchStart(event: TouchEvent) {
        dispatch('recordTouchStart', { originalEvent: event });
    }
    function handleRecordTouchEnd(event: TouchEvent) { dispatch('recordTouchEnd', { originalEvent: event }); }
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
                    <button class:active={isSketchOpen} type="button" role="menuitem" data-testid="composer-attachment-drawing" onclick={() => selectAttachment(handleSketchClick)}><span class="clickable-icon icon_sketch"></span>{$text('enter_message.attachments.sketch')}</button>
                    <button type="button" role="menuitem" data-testid="composer-attachment-location" onclick={() => selectAttachment(handleLocationClick)}><span class="clickable-icon icon_maps"></span>{$text('enter_message.attachments.share_location')}</button>
                    <button type="button" role="menuitem" data-testid="composer-attachment-camera" onclick={() => selectAttachment(handleCameraClick)}><span class="clickable-icon icon_camera"></span>{$text('enter_message.attachments.take_photo')}</button>
                    <button type="button" role="menuitem" data-testid="composer-attachment-files" onclick={() => selectAttachment(handleFileSelectClick)}><span class="clickable-icon icon_files"></span>{$text('enter_message.attachments.attach_files')}</button>
                </div>
            {/if}
        </div>
        {#if showModelSelector}
            <ComposerModelSelector selection={modelSelection} ready={modelSelectionReady} persistenceRevision={modelSelectionPersistenceRevision} onSelect={handleModelSelect} onOpenDetails={handleModelDetails} />
        {/if}
    </div>

    <div class="right-buttons {reserveTrailingControlSpace ? 'reserve-trailing-control-space' : ''}">
        <div class="assistant-speech-control" data-preserve-composer-focus="true">
            {#if speechStatus}
                <span
                    class="assistant-speech-status"
                    data-testid="assistant-speech-toggle-status"
                    transition:fly={{ x: 16, duration: 180 }}
                >
                    {speechStatus === 'on' ? $text('enter_message.speech_on') : $text('enter_message.speech_off')}
                </span>
            {/if}
            <button
                type="button"
                class="assistant-speech-icon"
                data-testid="assistant-speech-toggle"
                data-icon-only="true"
                data-speech-state={speechEnabled ? 'on' : 'off'}
                aria-label={speechEnabled ? $text('enter_message.speech_disable') : $text('enter_message.speech_enable')}
                aria-pressed={speechEnabled}
                onclick={handleAssistantSpeechToggle}
                use:tooltip
            >
                <svg
                    class="assistant-speech-glyph muted"
                    data-testid="assistant-speech-muted-icon"
                    data-visible={!speechEnabled}
                    aria-hidden="true"
                    viewBox="0 0 48 48"
                >
                    <path d="M20.159 6.661 11.818 15H2.25A2.25 2.25 0 0 0 0 17.25v13.5A2.25 2.25 0 0 0 2.25 33h9.568l8.341 8.339C21.568 42.748 24 41.758 24 39.748V8.251c0-2.011-2.434-2.998-3.841-1.59ZM43.279 24l4.278-4.279a1.513 1.513 0 0 0 0-2.139l-2.139-2.14a1.513 1.513 0 0 0-2.139 0L39 19.722l-4.279-4.279a1.513 1.513 0 0 0-2.139 0l-2.139 2.14a1.513 1.513 0 0 0 0 2.139L34.721 24l-4.278 4.277a1.513 1.513 0 0 0 0 2.14l2.14 2.139a1.513 1.513 0 0 0 2.139 0L39 28.278l4.279 4.279a1.513 1.513 0 0 0 2.139 0l2.139-2.139a1.513 1.513 0 0 0 0-2.139L43.279 24Z" />
                </svg>
                <svg
                    class="assistant-speech-glyph audio"
                    data-testid="assistant-speech-audio-icon"
                    data-visible={speechEnabled}
                    aria-hidden="true"
                    viewBox="0 0 48 48"
                >
                    <path d="M30.003-.001v16.203a8.996 8.996 0 0 1 0 15.594v16.203l-16-12h-14v-24h14l16-12Zm-6 12-8.001 6h-10v12h10l8 6v-24Z" />
                    <path d="m40.8 9.6-2.396-1.8-3.603 4.797 2.4 1.8a12 12 0 0 1 2.4 2.406A11.909 11.909 0 0 1 42 24c0 2.706-.891 5.19-2.4 7.2a12 12 0 0 1-2.4 2.4l-2.4 1.803 3.603 4.8 2.4-1.803a18 18 0 0 0 3.594-3.6A17.94 17.94 0 0 0 48 24c0-4.05-1.341-7.794-3.6-10.8a18.001 18.001 0 0 0-3.6-3.6Z" />
                </svg>
            </button>
        </div>

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
            {#if isAuthenticated && hasNoCredits}
                <button type="button" class="send-button buy-credits-button" data-action="buy-credits" onclick={handleBuyCreditsClick} aria-label={$text('enter_message.buy_credits')} in:fly={{ x: 40, duration: 200 }} out:fly={{ x: 40, duration: 150 }}>
                    {$text('enter_message.buy_credits')}
                </button>
            {:else if canSendMessage && !forceUnauthenticatedCta}
                <button type="button" class="send-button" data-testid="composer-send-button" data-action="send-message" onclick={handleSendMessageClick} aria-label={$text('enter_message.send')} in:fly={{ x: 40, duration: 200 }} out:fly={{ x: 40, duration: 150 }}>
                    {$text('enter_message.send')}
                </button>
            {:else}
                <button type="button" class="send-button" data-action="sign-up-to-send" onclick={handleSignUpClick} aria-label={unauthenticatedCtaLabel} in:fly={{ x: 40, duration: 200 }} out:fly={{ x: 40, duration: 150 }}>
                    {unauthenticatedCtaLabel}
                </button>
            {/if}
        {/if}
    </div>
</div>

<style>
    .action-buttons {
        position: absolute;
        inset-inline: 1rem;
        bottom: 1rem;
        display: flex;
        align-items: center;
        justify-content: space-between;
        height: 40px;
    }

    .left-buttons,
    .right-buttons {
        display: flex;
        align-items: center;
        gap: var(--spacing-8);
        height: 100%;
    }

    .right-buttons {
        flex-wrap: nowrap;
        transition: gap 200ms ease, padding-inline-end 220ms ease;
    }

    .right-buttons.reserve-trailing-control-space {
        padding-inline-end: 48px;
    }

    .attachment-menu { position: relative; }
    .attachment-plus-icon {
        -webkit-mask-image: var(--icon-url-plus);
        mask-image: var(--icon-url-plus);
    }

    .attachment-menu-popover {
        position: absolute;
        z-index: var(--z-index-dropdown);
        bottom: calc(100% + var(--spacing-4));
        inset-inline-start: 0;
        min-width: 10rem;
        padding: var(--spacing-4);
        background: var(--color-grey-0);
        border-radius: var(--radius-8);
        box-shadow: var(--shadow-lg);
    }

    .attachment-menu-popover button {
        display: flex;
        align-items: center;
        justify-content: flex-start;
        gap: var(--spacing-4);
        width: 100%;
        padding: var(--spacing-4);
        border: 0;
        border-radius: var(--radius-3);
        color: var(--color-font-primary);
        text-align: start;
        background: transparent;
        cursor: pointer;
    }

    .attachment-menu-popover button:hover,
    .attachment-menu-popover button.active { background: var(--color-grey-10); }

    .assistant-speech-control {
        display: flex;
        align-items: center;
        justify-content: flex-end;
        min-width: 1.75rem;
        color: var(--color-primary-start);
    }

    .assistant-speech-status {
        margin-inline-end: var(--spacing-4);
        color: var(--color-primary-start);
        font-size: var(--font-size-small);
        font-weight: 700;
        white-space: nowrap;
    }

    .assistant-speech-icon {
        all: unset;
        position: relative;
        display: block;
        width: 25px;
        height: 25px;
        color: var(--color-primary);
        border-radius: 50%;
        cursor: pointer;
    }

    .assistant-speech-icon:focus-visible {
        outline: 2px solid currentColor;
        outline-offset: 2px;
    }

    .assistant-speech-glyph {
        position: absolute;
        inset: 0;
        width: 100%;
        height: 100%;
        fill: currentColor;
        opacity: 0;
        pointer-events: none;
        transition: opacity 180ms ease;
    }

    .assistant-speech-glyph[data-visible='true'] { opacity: 1; }

    .icon_recordaudio { touch-action: none; }

    .send-button {
        height: 40px;
        margin-inline-start: var(--spacing-4);
        padding: var(--spacing-4) var(--spacing-8);
        border: none;
        border-radius: var(--radius-8);
        color: var(--color-grey-0);
        font-weight: 500;
        background: var(--color-button-primary);
        cursor: pointer;
    }

    @media (max-width: 34rem) {
        .left-buttons, .right-buttons { gap: var(--spacing-4); }
        .assistant-speech-status { font-size: var(--font-size-xs); }
    }
</style>
