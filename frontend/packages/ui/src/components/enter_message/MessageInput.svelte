<!-- frontend/packages/ui/src/components/enter_message/MessageInput.svelte -->
<script lang="ts">
    import { onMount, onDestroy, tick } from 'svelte';
    import { Editor } from '@tiptap/core';
    import { createEventDispatcher } from 'svelte';
    import { tooltip } from '../../actions/tooltip';
    import { text } from '@repo/ui'; // Use text store

    // Services & Stores
    import {
        initializeDraftService,
        cleanupDraftService,
        setCurrentChatContext,
        clearEditorAndResetDraftState,
        triggerSaveDraft,
        flushSaveDraft
    } from '../../services/draftService';
    import { recordingState, updateRecordingState } from './recordingStore';

    // Config & Extensions
    import { getEditorExtensions } from './editorConfig';

    // Components
    import CameraView from './CameraView.svelte';
    import RecordAudio from './RecordAudio.svelte'; // Import type for ref
    import MapsView from './MapsView.svelte';
    import PressAndHoldMenu from './in_message_previews/PressAndHoldMenu.svelte';
    import ActionButtons from './ActionButtons.svelte';
    import KeyboardShortcuts from '../KeyboardShortcuts.svelte';

    // Utils
    import {
        formatDuration,
        isContentEmptyExceptMention,
        getInitialContent,
        detectAndReplaceMates,
        detectAndReplaceUrls,
    } from './utils';

    // Handlers
    import { handleSend } from './handlers/sendHandlers';
    import {
        processFiles,
        handleDrop as handleFileDrop,
        handleDragOver as handleFileDragOver,
        handleDragLeave as handleFileDragLeave,
        handlePaste as handleFilePaste,
        onFileSelected as handleFileSelectedEvent
    } from './fileHandlers';
    import {
        insertVideo,
        insertImage,
        insertRecording,
        insertMap
    } from './embedHandlers';
    import {
        handleEmbedInteraction as handleMenuEmbedInteraction,
        handleMenuAction as handleMenuActionTrigger
    } from './menuHandlers';
    import {
        // Import the handlers that expect DOM events
        handleRecordMouseDown as handleRecordMouseDownLogic,
        handleRecordMouseUp as handleRecordMouseUpLogic,
        handleRecordMouseLeave as handleRecordMouseLeaveLogic,
        handleRecordTouchStart as handleRecordTouchStartLogic,
        handleRecordTouchEnd as handleRecordTouchEndLogic,
        handleStopRecordingCleanup
    } from './handlers/recordingHandlers';
    import { handleKeyboardShortcut } from './handlers/keyboardShortcutHandler';

    const dispatch = createEventDispatcher();

    // --- Props ---
    export let defaultMention: string = 'sophia';
    export let currentChatId: string | undefined = undefined;
    export let isFullscreen = false;
    export let hasContent = false;

    // --- Refs ---
    let fileInput: HTMLInputElement;
    let cameraInput: HTMLInputElement;
    let videoElement: HTMLVideoElement;
    let editor: Editor;
    let editorElement: HTMLElement | undefined = undefined;
    let scrollableContent: HTMLElement;
    let messageInputWrapper: HTMLElement;
    // Type the ref using the component's type
    let recordAudioComponent: RecordAudio;

    // --- Local UI State ---
    let showCamera = false;
    let showMaps = false;
    let isMessageFieldFocused = false;
    let isScrollable = false;
    let showMenu = false;
    let menuX = 0;
    let menuY = 0;
    let selectedEmbedId: string | null = null;
    let menuType: 'default' | 'pdf' | 'web' = 'default';
    let selectedNode: { node: any; pos: number } | null = null;
    let isMenuInteraction = false;
    let previousHeight = 0;

    // --- Lifecycle ---
    let languageChangeHandler: () => void;
    let resizeObserver: ResizeObserver;

    // onMount, onDestroy, editor handlers, setupEventListeners, cleanup remain the same

    onMount(() => {
        if (!editorElement) {
            console.error("Editor element not found on mount.");
            return;
        }

        editor = new Editor({
            element: editorElement,
            extensions: getEditorExtensions(),
            content: getInitialContent(),
            onFocus: handleEditorFocus,
            onBlur: handleEditorBlur,
            onUpdate: handleEditorUpdate,
        });

        initializeDraftService(editor);
        hasContent = !isContentEmptyExceptMention(editor);

        setupEventListeners();

        resizeObserver = new ResizeObserver(handleResize);
        if (scrollableContent) resizeObserver.observe(scrollableContent);

        tick().then(updateHeight);

        return cleanup;
    });

    onDestroy(cleanup);

    // --- Editor Lifecycle Handlers ---
    function handleEditorFocus({ editor }: { editor: Editor }) {
        isMessageFieldFocused = true;
        if (editor.isEmpty) {
            editor.commands.setContent(getInitialContent(), false);
            editor.chain().insertContent({
                type: 'mate',
                attrs: { name: defaultMention, id: crypto.randomUUID() }
            }).insertContent(' ').focus('end').run();
        }
    }

    function handleEditorBlur({ editor }: { editor: Editor }) {
        isMessageFieldFocused = false;
        setTimeout(() => {
            if (isMenuInteraction) return;
            flushSaveDraft();
            if (isContentEmptyExceptMention(editor)) {
                editor.commands.setContent(getInitialContent());
                hasContent = false;
            }
        }, 100);
    }

    function handleEditorUpdate({ editor }: { editor: Editor }) {
        const newHasContent = !isContentEmptyExceptMention(editor);
        if (hasContent !== newHasContent) {
            hasContent = newHasContent;
            if (!newHasContent) {
                 console.debug("[MessageInput] Content cleared, draft save skipped/potentially cleared on server.");
            }
        }
        if (hasContent) triggerSaveDraft();

        const content = editor.getHTML();
        detectAndReplaceUrls(editor, content);
        detectAndReplaceMates(editor, content);

        tick().then(() => {
            checkScrollable();
            updateHeight();
        });
    }

    // --- Event Listener Setup & Cleanup ---
    function setupEventListeners() {
        document.addEventListener('embedclick', handleEmbedClick as EventListener);
        document.addEventListener('mateclick', handleMateClick as EventListener);
        editorElement?.addEventListener('paste', handlePaste);
        editorElement?.addEventListener('custom-send-message', handleSendMessage as EventListener);
        editorElement?.addEventListener('keydown', handleKeyDown);
        editorElement?.addEventListener('codefullscreen', handleCodeFullscreen as EventListener);
        window.addEventListener('saveDraftBeforeSwitch', flushSaveDraft);
        window.addEventListener('beforeunload', handleBeforeUnload);
        document.addEventListener('visibilitychange', handleVisibilityChange);
        languageChangeHandler = () => {
            if (editor && !editor.isDestroyed) editor.view.dispatch(editor.view.state.tr);
        };
        window.addEventListener('language-changed', languageChangeHandler);
    }

    function cleanup() {
        resizeObserver?.disconnect();
        document.removeEventListener('embedclick', handleEmbedClick as EventListener);
        document.removeEventListener('mateclick', handleMateClick as EventListener);
        editorElement?.removeEventListener('paste', handlePaste);
        editorElement?.removeEventListener('custom-send-message', handleSendMessage as EventListener);
        editorElement?.removeEventListener('keydown', handleKeyDown);
        editorElement?.removeEventListener('codefullscreen', handleCodeFullscreen as EventListener);
        window.removeEventListener('saveDraftBeforeSwitch', flushSaveDraft);
        window.removeEventListener('beforeunload', handleBeforeUnload);
        document.removeEventListener('visibilitychange', handleVisibilityChange);
        window.removeEventListener('language-changed', languageChangeHandler);
        cleanupDraftService();
        if (editor && !editor.isDestroyed) editor.destroy();
        handleStopRecordingCleanup();
    }

    // --- Specific Event Handlers ---
    function handleEmbedClick(event: CustomEvent) { // Use built-in CustomEvent
        const result = handleMenuEmbedInteraction(event, editor, event.detail.id);
        if (result) {
            isMenuInteraction = true;
            menuX = result.menuX; menuY = result.menuY;
            selectedEmbedId = result.selectedEmbedId; menuType = result.menuType;
            selectedNode = result.selectedNode; showMenu = true;
        } else {
            isMenuInteraction = false; showMenu = false; selectedNode = null; selectedEmbedId = null;
        }
    }
    function handleMateClick(event: CustomEvent) { dispatch('mateclick', { id: event.detail.id }); }
    async function handlePaste(event: ClipboardEvent) {
        await handleFilePaste(event, editor, defaultMention);
        tick().then(() => hasContent = !isContentEmptyExceptMention(editor));
    }
    function handleKeyDown(event: KeyboardEvent) {
        if (event.key === 'Escape') {
            if (showCamera) { event.preventDefault(); showCamera = false; }
            else if (showMaps) { event.preventDefault(); showMaps = false; }
            else if (showMenu) { event.preventDefault(); showMenu = false; isMenuInteraction = false; selectedNode = null; }
            else if (isMessageFieldFocused) { event.preventDefault(); editor?.commands.blur(); }
        }
    }
    function handleCodeFullscreen(event: CustomEvent) { dispatch('codefullscreen', event.detail); }
    function handleBeforeUnload() { if (hasContent) flushSaveDraft(); }
    function handleVisibilityChange() { if (document.visibilityState === 'hidden' && hasContent) flushSaveDraft(); }
    function handleResize() { checkScrollable(); updateHeight(); }

    // --- UI Update Functions ---
    function updateHeight() {
        if (!messageInputWrapper) return;
        const currentHeight = messageInputWrapper.offsetHeight;
        if (currentHeight !== previousHeight) {
            previousHeight = currentHeight;
            dispatch('heightchange', { height: currentHeight });
        }
    }
    function checkScrollable() { if (scrollableContent) isScrollable = scrollableContent.scrollHeight > scrollableContent.clientHeight; }
    function toggleFullscreen() {
        isFullscreen = !isFullscreen;
        dispatch('fullscreenToggle', isFullscreen);
        tick().then(checkScrollable);
    }

    // --- Action Handlers (delegating to imported handlers) ---
    // File/Camera/Location handlers remain the same as previous step

    async function handleDrop(event: DragEvent) {
        await handleFileDrop(event, editorElement, editor, defaultMention);
        tick().then(() => hasContent = !isContentEmptyExceptMention(editor));
    }
    function handleDragOver(event: DragEvent) { handleFileDragOver(event, editorElement); }
    function handleDragLeave(event: DragEvent) { handleFileDragLeave(event, editorElement); }
    async function onFileSelected(event: Event) {
        await handleFileSelectedEvent(event, editor, defaultMention);
        tick().then(() => hasContent = !isContentEmptyExceptMention(editor));
    }
    function handleCameraClick() {
        const isMobile = window.matchMedia('(max-width: 768px), (pointer: coarse)').matches && ('ontouchstart' in window || navigator.maxTouchPoints > 0);
        if (isMobile) cameraInput?.click(); else showCamera = true;
    }
    async function handlePhotoCaptured(event: CustomEvent<{ blob: Blob, previewUrl: string }>) {
        const { blob, previewUrl } = event.detail;
        const file = new File([blob], `camera_${Date.now()}.jpg`, { type: 'image/jpeg' });
        showCamera = false; await tick();
        await insertImage(editor, file, true, previewUrl);
        hasContent = true;
    }
    async function handleVideoRecorded(event: CustomEvent<{ blob: Blob, duration: string }>) {
        const { blob, duration } = event.detail;
        const file = new File([blob], `video_${Date.now()}.webm`, { type: 'video/webm' });
        showCamera = false; await tick();
        await insertVideo(editor, file, duration, true);
        hasContent = true;
    }
    async function handleAudioRecorded(event: CustomEvent<{ blob: Blob, duration: number }>) {
        const { blob, duration } = event.detail;
        const url = URL.createObjectURL(blob);
        const filename = `audio_${Date.now()}.webm`;
        const formattedDuration = formatDuration(duration);
        if (editor.isEmpty) { editor.commands.setContent(getInitialContent()); await tick(); }
        insertRecording(editor, url, filename, formattedDuration);
        hasContent = true;
        handleStopRecordingCleanup(); // Called here after recording is inserted
    }
    function handleLocationClick() { showMaps = true; }
    async function handleLocationSelected(event: CustomEvent<{ type: string; attrs: any }>) {
        showMaps = false; await tick();
        if (editor.isEmpty) { editor.commands.setContent(getInitialContent()); await tick(); }
        insertMap(editor, event.detail);
        hasContent = true;
    }
    async function handleMenuAction(action: string) {
        await handleMenuActionTrigger(action, selectedNode, editor, dispatch, selectedEmbedId);
        showMenu = false; isMenuInteraction = false; selectedNode = null; selectedEmbedId = null;
        if (action === 'delete') {
            await tick(); hasContent = !isContentEmptyExceptMention(editor);
        }
    }
    function handleFileSelect() { fileInput.multiple = true; fileInput.click(); }
    function handleSendMessage() {
        handleSend(editor, defaultMention, dispatch, (value) => hasContent = value, currentChatId);
    }
    function handleRecordingLayoutChange(event: CustomEvent<{ active: boolean }>) {
        updateRecordingState({ isRecordingActive: event.detail.active });
        tick().then(updateHeight);
    }

    // --- Handlers to bridge ActionButtons events to recordingHandlers ---
    // These now extract the original event from the detail payload
    function onRecordMouseDown(event: CustomEvent<{ originalEvent: MouseEvent }>) {
        handleRecordMouseDownLogic(event.detail.originalEvent);
    }
    function onRecordMouseUp(event: CustomEvent<{ originalEvent: MouseEvent }>) {
        // Pass the component ref to the logic handler
        handleRecordMouseUpLogic(recordAudioComponent);
    }
    function onRecordMouseLeave(event: CustomEvent<{ originalEvent: MouseEvent }>) {
        // Pass the component ref to the logic handler
        handleRecordMouseLeaveLogic(recordAudioComponent);
    }
    function onRecordTouchStart(event: CustomEvent<{ originalEvent: TouchEvent }>) {
        handleRecordTouchStartLogic(event.detail.originalEvent);
    }
    function onRecordTouchEnd(event: CustomEvent<{ originalEvent: TouchEvent }>) {
        // Pass the component ref to the logic handler
        handleRecordTouchEndLogic(recordAudioComponent);
    }


    // --- Public API ---
    export function focus() { if (editor && !editor.isDestroyed) editor.commands.focus('end'); }
    export function setDraftContent(chatId: string | null, draftContent: any | null, version: number, shouldFocus: boolean = true) {
        setCurrentChatContext(chatId, draftContent, version);
        if (shouldFocus && editor) editor.commands.focus('end');
        hasContent = editor ? !isContentEmptyExceptMention(editor) : false;
    }
    export function clearMessageField(shouldFocus: boolean = true) {
        clearEditorAndResetDraftState(shouldFocus);
        hasContent = false;
    }

    // --- Reactive Calculations ---
    $: containerStyle = isFullscreen ? `height: calc(100vh - 100px); max-height: calc(100vh - 120px); height: calc(100dvh - 100px); max-height: calc(100dvh - 120px);` : 'height: auto; max-height: 350px;';
    $: scrollableStyle = isFullscreen ? `max-height: calc(100vh - 190px); max-height: calc(100dvh - 190px);` : 'max-height: 250px;';
    $: if (isFullscreen !== undefined && messageInputWrapper) tick().then(updateHeight);

</script>

<!-- Template -->
<div bind:this={messageInputWrapper} class="message-input-wrapper">
    <div
        class="message-field {isMessageFieldFocused ? 'focused' : ''} {$recordingState.isRecordingActive ? 'recording-active' : ''}"
        class:drag-over={editorElement?.classList.contains('drag-over')}
        style={containerStyle}
        on:dragover|preventDefault={handleDragOver}
        on:dragleave|preventDefault={handleDragLeave}
        on:drop|preventDefault={handleDrop}
        role="textbox"
        aria-multiline="true"
        tabindex="0"
    >
        {#if isScrollable || isFullscreen}
            <button
                class="clickable-icon icon_fullscreen fullscreen-button"
                on:click={toggleFullscreen}
                aria-label={isFullscreen ? $text('enter_message.fullscreen.exit_fullscreen.text') : $text('enter_message.fullscreen.enter_fullscreen.text')}
                use:tooltip
            ></button>
        {/if}

        <input bind:this={fileInput} type="file" on:change={onFileSelected} style="display: none" multiple accept="*/*" />
        <input bind:this={cameraInput} type="file" accept="image/*,video/*" capture="environment" on:change={onFileSelected} style="display: none" />

        <div class="scrollable-content" bind:this={scrollableContent} style={scrollableStyle}>
            <div class="content-wrapper">
                <div bind:this={editorElement} class="editor-content prose"></div>
            </div>
        </div>

        {#if showCamera}
            <CameraView bind:videoElement on:close={() => showCamera = false} on:focusEditor={focus} on:photocaptured={handlePhotoCaptured} on:videorecorded={handleVideoRecorded} />
        {/if}

        <!-- Action Buttons Component -->
        <!-- Bind handlers that extract originalEvent -->
        <ActionButtons
            {hasContent}
            isRecordButtonPressed={$recordingState.isRecordButtonPressed}
            showRecordHint={$recordingState.showRecordHint}
            micPermissionGranted={$recordingState.micPermissionGranted}
            {editor}
            {defaultMention}
            {currentChatId}
            on:fileSelect={handleFileSelect}
            on:locationClick={handleLocationClick}
            on:cameraClick={handleCameraClick}
            on:sendMessage={handleSendMessage}
            on:recordMouseDown={onRecordMouseDown}
            on:recordMouseUp={onRecordMouseUp}
            on:recordMouseLeave={onRecordMouseLeave}
            on:recordTouchStart={onRecordTouchStart}
            on:recordTouchEnd={onRecordTouchEnd}
        />

        {#if showMenu}
            <PressAndHoldMenu x={menuX} y={menuY} show={showMenu} type={menuType} isYouTube={selectedNode?.node?.attrs?.isYouTube || false} on:close={() => { showMenu = false; isMenuInteraction = false; selectedNode = null; selectedEmbedId = null; }} on:delete={() => handleMenuAction('delete')} on:download={() => handleMenuAction('download')} on:view={() => handleMenuAction('view')} on:copy={() => handleMenuAction('copy')} />
        {/if}

        {#if $recordingState.showRecordAudioUI}
            <!-- Pass the required initialPosition from the store -->
            <RecordAudio
                bind:this={recordAudioComponent}
                initialPosition={$recordingState.recordStartPosition}
                on:audiorecorded={handleAudioRecorded}
                on:close={handleStopRecordingCleanup}
                on:cancel={handleStopRecordingCleanup}
                on:recordingStateChange={handleRecordingLayoutChange}
            />
        {/if}

        {#if showMaps}
            <MapsView on:close={() => showMaps = false} on:locationselected={handleLocationSelected} />
        {/if}
    </div>
</div>

<!-- Keyboard Shortcuts Listener -->
<!-- Pass the component instance directly -->
<KeyboardShortcuts
    on:startRecording={(e) => handleKeyboardShortcut(e, editor, isMessageFieldFocused, recordAudioComponent)}
    on:stopRecording={(e) => handleKeyboardShortcut(e, editor, isMessageFieldFocused, recordAudioComponent)}
    on:cancelRecording={(e) => handleKeyboardShortcut(e, editor, isMessageFieldFocused, recordAudioComponent)}
    on:insertSpace={(e) => handleKeyboardShortcut(e, editor, isMessageFieldFocused, recordAudioComponent)}
/>

<!-- Styles -->
<style>
	/* Styles remain the same as the previous correct version */
    /* Base wrapper */
    .message-input-wrapper { width: 100%; position: relative; }

    /* Main message field container */
    .message-field {
        width: 100%; min-height: 100px; background-color: var(--color-grey-blue);
        border-radius: 24px; padding: 0 0 60px 0; box-sizing: border-box;
        position: relative; box-shadow: 0 4px 12px rgba(0, 0, 0, 0.08);
        transition: padding-bottom 0.3s ease-in-out, max-height 0.3s ease-in-out, height 0.3s ease-in-out;
        display: flex; flex-direction: column; overflow: hidden;
        will-change: padding-bottom, max-height, height;
    }
    .message-field.recording-active { /* Adjust based on RecordAudio height */ }

    /* Scrollable area */
    .scrollable-content {
        flex-grow: 1; width: 100%; overflow-y: auto; position: relative;
        padding-top: 1em; scrollbar-width: thin;
        scrollbar-color: color-mix(in srgb, var(--color-grey-100) 20%, transparent) transparent;
        overflow-x: hidden; box-sizing: border-box;
        transition: max-height 0.3s ease-in-out;
    }

    /* Editor content wrapper */
    .content-wrapper {
        display: flex; flex-direction: column; width: 100%;
        box-sizing: border-box; min-height: 40px; padding: 0 1rem;
    }

    /* Tiptap editor element */
    .editor-content {
        box-sizing: border-box; width: 100%; min-height: 2em;
        position: relative; transition: all 0.2s ease-in-out; flex-grow: 1;
    }

    /* Tiptap ProseMirror base styles */
    :global(.ProseMirror) {
        outline: none !important; white-space: pre-wrap; word-wrap: break-word;
        padding: 0.5rem 0; min-height: 2em; max-width: 100%; box-sizing: border-box;
        color: var(--color-font-primary); line-height: 1.6; caret-color: var(--color-primary);
    }
    :global(.ProseMirror p) { margin: 0 0 0.5em 0; min-height: 1.6em; }
    :global(.ProseMirror p:last-child) { margin-bottom: 0; }

    /* Placeholder styling */
    :global(.ProseMirror p.is-editor-empty:first-child::before) {
        content: attr(data-placeholder); float: left; color: var(--color-font-tertiary);
        pointer-events: none; height: 0; display: block; opacity: 1; width: 100%;
        text-align: center; position: absolute; left: 0; right: 0; top: 0.5rem;
    }
    :global(.ProseMirror.ProseMirror-focused p.is-editor-empty:first-child::before) {
        text-align: left; position: relative; float: none; width: auto; padding-left: 0; top: 0;
    }

    /* Fullscreen button */
    .fullscreen-button {
        position: absolute; top: 10px; right: 15px; opacity: 0.5;
        transition: opacity 0.2s ease-in-out; z-index: 10; background: none;
        border: none; padding: 5px; cursor: pointer;
    }
    .fullscreen-button:hover { opacity: 1; }
    .clickable-icon { /* General style for icon buttons */
        background: none; border: none; padding: 0; cursor: pointer;
        display: flex; align-items: center; justify-content: center;
    }

    /* Drag & Drop overlay styles */
    .message-field.drag-over {
        background-color: var(--color-grey-30) !important; border: 2px dashed var(--color-primary);
        box-shadow: inset 0 0 15px rgba(0, 0, 0, 0.1);
    }
    .message-field.drag-over::after {
        content: 'Drop files here'; position: absolute; top: 0; left: 0; right: 0; bottom: 60px;
        display: flex; align-items: center; justify-content: center; font-size: 1.1em;
        font-weight: 500; color: var(--color-primary); background: rgba(255, 255, 255, 0.8);
        z-index: 5; pointer-events: none; border-radius: 22px;
    }

    /* --- Embed Specific Styles (Keep as is) --- */
    :global(.ProseMirror .embed-wrapper) { display: inline-block; margin: 4px 2px; vertical-align: bottom; max-width: 100%; cursor: pointer; position: relative; }
    :global(.ProseMirror .image-embed-node) { max-width: 300px; max-height: 200px; border-radius: 12px; overflow: hidden; display: block; background-color: var(--color-grey-10); }
    :global(.ProseMirror .image-embed-node img) { display: block; width: 100%; height: 100%; object-fit: cover; }
    :global(.ProseMirror .file-like-embed) { display: inline-flex; align-items: center; gap: 8px; background-color: var(--color-grey-20); padding: 8px 12px; border-radius: 16px; max-width: 250px; height: 40px; box-sizing: border-box; }
    :global(.ProseMirror .file-like-embed:hover) { background-color: var(--color-grey-30); }
    :global(.ProseMirror .file-like-embed .embed-icon) { font-size: 20px; flex-shrink: 0; color: var(--color-font-secondary); }
    :global(.ProseMirror .file-like-embed .embed-filename) { font-size: 14px; color: var(--color-font-primary); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; flex-grow: 1; }
    :global(.ProseMirror .media-embed) { display: inline-flex; align-items: center; gap: 8px; background-color: var(--color-grey-20); padding: 8px 12px; border-radius: 16px; max-width: 300px; height: 40px; box-sizing: border-box; }
    :global(.ProseMirror .media-embed:hover) { background-color: var(--color-grey-30); }
    :global(.ProseMirror .media-embed .embed-icon) { font-size: 20px; flex-shrink: 0; color: var(--color-font-secondary); }
    :global(.ProseMirror .media-embed .media-details) { display: flex; flex-direction: column; overflow: hidden; flex-grow: 1; }
    :global(.ProseMirror .media-embed .embed-filename) { font-size: 14px; color: var(--color-font-primary); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
    :global(.ProseMirror .media-embed .embed-duration) { font-size: 12px; color: var(--color-font-secondary); }
    :global(.ProseMirror .web-preview-node) { display: block; max-width: 400px; }
    :global(.ProseMirror .mate-mention-node) { display: inline-flex; align-items: center; gap: 4px; background-color: color-mix(in srgb, var(--color-primary) 15%, transparent); color: var(--color-primary); padding: 2px 6px; border-radius: 4px; font-weight: 500; cursor: pointer; transition: background-color 0.2s; }
    :global(.ProseMirror .mate-mention-node:hover) { background-color: color-mix(in srgb, var(--color-primary) 25%, transparent); }
    :global(.embed-wrapper.show-copied::after) { content: 'Copied!'; position: absolute; bottom: 100%; left: 50%; transform: translateX(-50%) translateY(-5px); background-color: var(--color-grey-100); color: var(--color-grey-0); padding: 3px 8px; border-radius: 4px; font-size: 12px; white-space: nowrap; z-index: 10; animation: fadeOut 2s forwards; }
    @keyframes fadeOut { 0% { opacity: 1; } 80% { opacity: 1; } 100% { opacity: 0; } }
</style>